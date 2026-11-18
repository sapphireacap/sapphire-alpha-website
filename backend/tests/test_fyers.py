"""FYERS foundation: request budget, automatic login, data client. Mock HTTP only (no network,
no real credentials)."""
import asyncio
import hashlib
import json
import os
import sys
from datetime import datetime, timedelta, timezone

import httpx
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import fyers_auth  # noqa: E402
import fyers_client  # noqa: E402
from fyers_budget import Budget, FyersBudgetError  # noqa: E402

IST = timezone(timedelta(hours=5, minutes=30))


def run(coro):
    return asyncio.run(coro)


# ---- fakes ------------------------------------------------------------------------------
class FakeColl:
    def __init__(self):
        self.docs = []

    async def find_one(self, flt, proj=None):
        for d in self.docs:
            if all(d.get(k) == v for k, v in flt.items()):
                out = dict(d)
                for k, v in (proj or {}).items():
                    if v == 0:
                        out.pop(k, None)
                return out
        return None

    async def update_one(self, flt, upd, upsert=False):
        for d in self.docs:
            if all(d.get(k) == v for k, v in flt.items()):
                d.update(upd["$set"])
                return
        if upsert:
            self.docs.append({**flt, **upd["$set"]})


class FakeDb:
    def __init__(self):
        self.colls = {}

    def __getitem__(self, name):
        return self.colls.setdefault(name, FakeColl())

    def __getattr__(self, name):
        return self[name]


@pytest.fixture(autouse=True)
def env(monkeypatch):
    for k, v in {"FYERS_ENABLED": "1", "FYERS_APP_ID": "ABCD1234E5-100", "FYERS_SECRET_ID": "sekret", "FYERS_REDIRECT_URI": "https://x.test/cb",
                 "FYERS_CLIENT_ID": "XA12345", "FYERS_PIN": "1234", "FYERS_TOTP_SECRET": "JBSWY3DPEHPK3PXP"}.items():
        monkeypatch.setenv(k, v)
    monkeypatch.setattr(fyers_auth, "_last_failure", {"at": 0.0, "message": ""})
    monkeypatch.setattr(fyers_client, "_paused_until", 0.0)
    monkeypatch.setattr(fyers_client, "default_budget", Budget())


def mock_http(monkeypatch, handler):
    factory = lambda **k: httpx.AsyncClient(transport=httpx.MockTransport(handler))  # noqa: E731
    monkeypatch.setattr(fyers_auth, "_http", lambda: factory())
    monkeypatch.setattr(fyers_client, "_http", lambda: factory())


# ---- budget -----------------------------------------------------------------------------------
class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t

    async def sleep(self, s):
        self.t += s


def make_budget(day="2026-11-18"):
    c = Clock()
    state = {"day": day}
    return Budget(clock=c, today=lambda: state["day"], sleep=c.sleep), c, state


def test_per_second_limit_makes_a_call_wait_not_fail():
    b, clock, _ = make_budget()
    start = clock.t

    async def go():
        for _ in range(b.per_second + 1):
            await b.acquire()

    run(go())
    assert clock.t - start >= 0.99          # the 5th call waited for the next second


def test_per_minute_limit_refuses_instead_of_waiting():
    b, clock, _ = make_budget()
    b.per_second = 5

    async def go():
        for i in range(b.per_minute):
            clock.t += 0.3                  # spread out: only the minute window can bite
            await b.acquire()
        with pytest.raises(FyersBudgetError, match="per-minute"):
            await b.acquire()
        clock.t += 61
        await b.acquire()                   # window slid: allowed again

    run(go())


def test_daily_limit_refuses_and_a_new_day_resets():
    b, clock, state = make_budget()
    b.per_day, b.per_minute = 3, 99

    async def go():
        for _ in range(3):
            clock.t += 5
            await b.acquire()
        with pytest.raises(FyersBudgetError, match="daily"):
            await b.acquire()
        state["day"] = "2026-11-19"
        await b.acquire()

    run(go())
    assert b.count == 1


def test_limits_can_never_be_set_above_the_plan(monkeypatch):
    monkeypatch.setenv("FYERS_MAX_PER_MINUTE", "500")
    monkeypatch.setenv("FYERS_MAX_PER_DAY", "999999")
    monkeypatch.setenv("FYERS_MAX_PER_SECOND", "50")
    b = Budget()
    assert (b.per_second, b.per_minute, b.per_day) == (5, 50, 5000)


def test_daily_count_survives_a_restart_via_mongo():
    db = FakeDb()
    b1, c1, st = make_budget()

    async def first():
        for _ in range(12):
            c1.t += 2
            await b1.acquire(db)
        await b1.flush(db)

    run(first())
    b2, c2, _ = make_budget()          # "restarted" process, same day
    run(b2.acquire(db))
    assert b2.count == 13


# ---- auth helpers ---------------------------------------------------------------------------------
def test_app_id_hash_is_sha256_of_appid_colon_secret():
    assert fyers_auth.app_id_hash() == hashlib.sha256(b"ABCD1234E5-100:sekret").hexdigest()


def test_token_expires_at_the_next_0630_ist():
    assert fyers_auth.next_expiry(datetime(2026, 11, 18, 5, 0, tzinfo=IST)) == datetime(2026, 11, 18, 6, 30, tzinfo=IST)
    assert fyers_auth.next_expiry(datetime(2026, 11, 18, 6, 30, tzinfo=IST)) == datetime(2026, 11, 19, 6, 30, tzinfo=IST)
    assert fyers_auth.next_expiry(datetime(2026, 11, 18, 9, 0, tzinfo=IST)) == datetime(2026, 11, 19, 6, 30, tzinfo=IST)


def test_disabled_by_default_sends_nothing(monkeypatch):
    monkeypatch.delenv("FYERS_ENABLED")
    mock_http(monkeypatch, lambda r: (_ for _ in ()).throw(AssertionError("request sent while disabled")))
    with pytest.raises(fyers_auth.FyersAuthError, match="not enabled"):
        run(fyers_auth.get_access_token(FakeDb()))


def test_valid_stored_token_is_used_without_any_request(monkeypatch):
    db = FakeDb()
    run(db.fyers_token.update_one({"id": "current"}, {"$set": {"id": "current", "access_token": "tok", "access_expires_at": fyers_auth.next_expiry().isoformat()}}, upsert=True))
    mock_http(monkeypatch, lambda r: (_ for _ in ()).throw(AssertionError("request sent")))
    assert run(fyers_auth.get_access_token(db)) == "tok"


def _store(db, **kw):
    run(db.fyers_token.update_one({"id": "current"}, {"$set": {"id": "current", **kw}}, upsert=True))


def test_expired_token_is_renewed_with_the_refresh_token_and_pin(monkeypatch):
    db = FakeDb()
    now = datetime.now(IST)
    _store(db, access_token="old", access_expires_at=(now - timedelta(hours=1)).isoformat(),
           refresh_token="R1", refresh_obtained_at=(now - timedelta(days=3)).isoformat())
    seen = []

    def handler(req):
        seen.append((req.url.path, json.loads(req.content)))
        return httpx.Response(200, json={"s": "ok", "code": 200, "access_token": "new"})

    mock_http(monkeypatch, handler)
    assert run(fyers_auth.get_access_token(db)) == "new"
    path, body = seen[0]
    assert path.endswith("/validate-refresh-token") and len(seen) == 1
    assert body == {"grant_type": "refresh_token", "appIdHash": fyers_auth.app_id_hash(), "refresh_token": "R1", "pin": "1234"}
    stored = run(db.fyers_token.find_one({"id": "current"}))
    assert stored["access_token"] == "new" and stored["method"] == "refresh"
    assert stored["refresh_token"] == "R1"                                   # kept: refresh did not rotate it
    assert stored["refresh_obtained_at"] == (now - timedelta(days=3)).isoformat()   # and its age is NOT reset


def _login_handler(calls, fail_at=None):
    def handler(req):
        p = req.url.path
        calls.append(p)
        if fail_at and p.endswith(fail_at):
            return httpx.Response(403, text="forbidden")
        if p.endswith("/send_login_otp_v2"):
            assert json.loads(req.content)["fy_id"] == "WEExMjM0NQ=="        # base64("XA12345")
            return httpx.Response(200, json={"s": "ok", "request_key": "rk1"})
        if p.endswith("/verify_otp"):
            body = json.loads(req.content)
            assert body["request_key"] == "rk1" and len(body["otp"]) == 6
            return httpx.Response(200, json={"s": "ok", "request_key": "rk2"})
        if p.endswith("/verify_pin_v2"):
            body = json.loads(req.content)
            assert body["request_key"] == "rk2" and body["identifier"] == "MTIzNA=="    # base64("1234")
            return httpx.Response(200, json={"s": "ok", "data": {"access_token": "bearer-1"}})
        if p.endswith("/token"):
            assert req.headers["authorization"] == "Bearer bearer-1"
            body = json.loads(req.content)
            assert (body["fyers_id"], body["app_id"], body["appType"]) == ("XA12345", "ABCD1234E5", "100")
            return httpx.Response(308, json={"s": "ok", "code": 308, "Url": "https://x.test/cb?s=ok&code=200&auth_code=AUTH9&state=sas"})
        if p.endswith("/validate-authcode"):
            body = json.loads(req.content)
            assert body["code"] == "AUTH9" and body["grant_type"] == "authorization_code"
            return httpx.Response(200, json={"s": "ok", "access_token": "fresh", "refresh_token": "R2"})
        raise AssertionError(p)
    return handler


def test_first_login_uses_the_totp_flow_in_order_and_stores_both_tokens(monkeypatch):
    db, calls = FakeDb(), []
    mock_http(monkeypatch, _login_handler(calls))
    assert run(fyers_auth.get_access_token(db)) == "fresh"
    assert [c.rsplit("/", 1)[1] for c in calls] == ["send_login_otp_v2", "verify_otp", "verify_pin_v2", "token", "validate-authcode"]
    stored = run(db.fyers_token.find_one({"id": "current"}))
    assert stored["method"] == "totp" and stored["refresh_token"] == "R2"
    assert datetime.fromisoformat(stored["access_expires_at"]) == fyers_auth.next_expiry(datetime.now(IST))


def test_failed_refresh_falls_back_to_totp(monkeypatch):
    db, calls = FakeDb(), []
    now = datetime.now(IST)
    _store(db, access_token="old", access_expires_at=(now - timedelta(hours=1)).isoformat(),
           refresh_token="BAD", refresh_obtained_at=now.isoformat())
    inner = _login_handler(calls)
    mock_http(monkeypatch, lambda r: httpx.Response(400, json={"s": "error", "code": -501, "message": "Please provide valid refresh token"})
              if r.url.path.endswith("validate-refresh-token") else inner(r))
    assert run(fyers_auth.get_access_token(db)) == "fresh"


def test_an_old_refresh_token_is_not_even_tried(monkeypatch):
    db, calls = FakeDb(), []
    now = datetime.now(IST)
    _store(db, access_token="old", access_expires_at=(now - timedelta(hours=1)).isoformat(),
           refresh_token="OLD", refresh_obtained_at=(now - timedelta(days=20)).isoformat())
    mock_http(monkeypatch, _login_handler(calls))
    run(fyers_auth.get_access_token(db))
    assert not any("refresh" in c for c in calls)


def test_failed_login_triggers_a_cooldown_so_totp_attempts_are_not_burned(monkeypatch):
    db, calls = FakeDb(), []
    mock_http(monkeypatch, _login_handler(calls, fail_at="/verify_otp"))
    with pytest.raises(fyers_auth.FyersAuthError, match="step 2"):
        run(fyers_auth.get_access_token(db))
    n = len(calls)
    with pytest.raises(fyers_auth.FyersAuthError, match="cooling down"):
        run(fyers_auth.get_access_token(db))
    assert len(calls) == n                                  # the retry sent NOTHING


def test_errors_never_contain_secrets(monkeypatch):
    mock_http(monkeypatch, _login_handler([], fail_at="/verify_pin_v2"))
    with pytest.raises(fyers_auth.FyersAuthError) as e:
        run(fyers_auth.get_access_token(FakeDb()))
    for secret in ("sekret", "1234", "JBSWY3DPEHPK3PXP", fyers_auth.app_id_hash()):
        assert secret not in str(e.value)


def test_missing_settings_are_named_not_guessed(monkeypatch):
    monkeypatch.delenv("FYERS_PIN")
    mock_http(monkeypatch, lambda r: (_ for _ in ()).throw(AssertionError("request sent")))
    with pytest.raises(fyers_auth.FyersAuthError, match="FYERS_PIN"):
        run(fyers_auth.get_access_token(FakeDb()))


def test_concurrent_callers_cause_exactly_one_login(monkeypatch):
    db, calls = FakeDb(), []
    mock_http(monkeypatch, _login_handler(calls))

    async def go():
        return await asyncio.gather(*[fyers_auth.get_access_token(db) for _ in range(6)])

    assert set(run(go())) == {"fresh"}
    assert calls.count("/api/v3/validate-authcode") == 1


def test_status_hides_token_values(monkeypatch):
    db = FakeDb()
    _store(db, access_token="SECRET-A", refresh_token="SECRET-R", access_expires_at=fyers_auth.next_expiry().isoformat(),
           refreshed_at=datetime.now(IST).isoformat(), refresh_obtained_at=datetime.now(IST).isoformat(), method="refresh")
    st = run(fyers_auth.status(db))
    assert "SECRET" not in json.dumps(st) and st["token_valid"] is True and st["refresh_token_usable"] is True


# ---- data client ------------------------------------------------------------------------------------
def client_with(monkeypatch, handler):
    db = FakeDb()
    _store(db, access_token="tok", access_expires_at=fyers_auth.next_expiry().isoformat())
    mock_http(monkeypatch, handler)
    return fyers_client.FyersClient(db, budget=Budget()), db


def test_requests_carry_appid_colon_token_and_count_against_the_budget(monkeypatch):
    seen = []
    c, _ = client_with(monkeypatch, lambda r: seen.append(dict(r.headers)) or httpx.Response(200, json={"s": "ok", "d": []}))
    run(c.quotes(["NSE:SBIN-EQ"]))
    assert seen[0]["authorization"] == "ABCD1234E5-100:tok" and c.budget.count == 1


def test_minute_history_shape_dedupe_and_window_split(monkeypatch):
    t0 = int(datetime(2026, 11, 17, 9, 15, tzinfo=IST).timestamp())
    reqs = []

    def handler(r):
        reqs.append(dict(r.url.params))
        return httpx.Response(200, json={"s": "ok", "candles": [[t0 + 60, 2, 3, 1, 2.5, 10], [t0, 1, 2, 0.5, 1.5, 5], [t0, 1, 2, 0.5, 1.5, 5]]})

    c, _ = client_with(monkeypatch, handler)
    frm = datetime(2026, 5, 1, tzinfo=IST)
    to = datetime(2026, 11, 17, 15, 30, tzinfo=IST)
    bars = run(c.minute_ohlc("NSE:NIFTY50-INDEX", frm, to))
    assert len(reqs) >= 2 and all(int(q["range_to"]) - int(q["range_from"]) <= 95 * 86400 for q in reqs)
    assert [b["ts"] for b in bars] == ["171120260915", "171120260916"]         # duplicates collapsed, oldest first
    assert bars[0]["close"] == 1.5 and bars[1]["volume"] == 10.0
    assert reqs[0]["symbol"] == "NSE:NIFTY50-INDEX" and reqs[0]["resolution"] == "1" and reqs[0]["cont_flag"] == "1"


def test_daily_history_shape(monkeypatch):
    t = int(datetime(2026, 11, 16, 0, 0, tzinfo=IST).timestamp())
    c, _ = client_with(monkeypatch, lambda r: httpx.Response(200, json={"s": "ok", "candles": [[t, 1, 2, 0.5, 1.5, 9]]}))
    out = run(c.daily_history("NSE:SBIN-EQ", years=1))
    assert out[0]["date"] == "2026-11-16" and out[0]["high"] == 2.0


def test_quotes_are_batched_50_at_a_time(monkeypatch):
    sizes = []

    def handler(r):
        syms = r.url.params["symbols"].split(",")
        sizes.append(len(syms))
        return httpx.Response(200, json={"s": "ok", "d": [{"n": s, "s": "ok", "v": {"lp": 10.0, "volume": 5}} for s in syms]})

    c, _ = client_with(monkeypatch, handler)
    out = run(c.quotes([f"NSE:S{i}-EQ" for i in range(120)]))
    assert sizes == [50, 50, 20] and len(out) == 120 and out["NSE:S7-EQ"]["ltp"] == 10.0


def test_rate_limit_reply_pauses_all_further_calls_without_sending_them(monkeypatch):
    n = {"calls": 0}

    def handler(r):
        n["calls"] += 1
        return httpx.Response(429, json={"s": "error", "code": -429, "message": "limit"})

    c, _ = client_with(monkeypatch, handler)
    with pytest.raises(fyers_client.FyersRateLimited):
        run(c.quotes(["NSE:SBIN-EQ"]))
    with pytest.raises(fyers_client.FyersRateLimited, match="paused"):
        run(c.quotes(["NSE:SBIN-EQ"]))
    assert n["calls"] == 1                                   # the second call never left the building


def test_expired_token_reply_renews_once_and_retries(monkeypatch):
    db = FakeDb()
    _store(db, access_token="stale", access_expires_at=fyers_auth.next_expiry().isoformat(),
           refresh_token="R1", refresh_obtained_at=datetime.now(IST).isoformat())
    sent = []

    def handler(r):
        if r.url.path.endswith("/validate-refresh-token"):
            return httpx.Response(200, json={"s": "ok", "access_token": "renewed"})
        sent.append(r.headers["authorization"])
        if r.headers["authorization"].endswith(":stale"):
            return httpx.Response(401, json={"s": "error", "code": -16, "message": "Could not authenticate the user"})
        return httpx.Response(200, json={"s": "ok", "d": [{"n": "NSE:SBIN-EQ", "s": "ok", "v": {"lp": 7.0}}]})

    mock_http(monkeypatch, handler)
    c = fyers_client.FyersClient(db, budget=Budget())
    assert run(c.ltp("NSE:SBIN-EQ")) == 7.0
    assert sent == ["ABCD1234E5-100:stale", "ABCD1234E5-100:renewed"] and c.budget.count == 2


def test_budget_refusal_stops_the_request_before_it_is_sent(monkeypatch):
    n = {"calls": 0}
    c, _ = client_with(monkeypatch, lambda r: n.__setitem__("calls", n["calls"] + 1) or httpx.Response(200, json={"s": "ok", "d": []}))
    c.budget.per_day = 0 or 1
    c.budget.count = 1
    with pytest.raises(FyersBudgetError):
        run(c.quotes(["NSE:SBIN-EQ"]))
    assert n["calls"] == 0


def test_option_chain_is_normalised_and_iv_unit_is_left_raw(monkeypatch):
    payload = {"s": "ok", "data": {"expiryData": [{"date": "23-11-2026", "expiry": "1795449000"}], "optionsChain": [
        {"symbol": "NSE:NIFTY50-INDEX", "ltp": 25228.0, "option_type": "", "strike_price": -1},
        {"symbol": "NSE:NIFTY2612325200CE", "ltp": 120.5, "option_type": "CE", "strike_price": 25200, "oi": 900, "volume": 50,
         "delta": 0.55, "gamma": 0.002, "theta": -12.5, "vega": 8.1, "iv": 14.2},
        {"symbol": "NSE:NIFTY2612325200PE", "ltp": 95.0, "option_type": "PE", "strike_price": 25200, "iv": 15.0, "delta": -0.45}]}}
    seen = []
    c, _ = client_with(monkeypatch, lambda r: seen.append(dict(r.url.params)) or httpx.Response(200, json=payload))
    ch = run(c.option_chain("NSE:NIFTY50-INDEX", strikecount=500))
    assert seen[0]["strikecount"] == "50" and seen[0]["greeks"] == "1"           # capped at 50, greeks requested
    assert ch["spot"] == 25228.0 and set(ch["strikes"]) == {25200.0}
    ce = ch["strikes"][25200.0]["ce"]
    assert (ce["delta"], ce["vega"], ce["iv_raw"]) == (0.55, 8.1, 14.2) and "iv" not in ce
    assert ch["strikes"][25200.0]["pe"]["delta"] == -0.45


def test_empty_chain_is_an_error(monkeypatch):
    c, _ = client_with(monkeypatch, lambda r: httpx.Response(200, json={"s": "ok", "data": {"optionsChain": []}}))
    with pytest.raises(fyers_client.FyersError, match="empty"):
        run(c.option_chain("NSE:NIFTY50-INDEX"))

def test_a_rate_limit_reply_triggers_a_long_cooldown_not_the_short_one(monkeypatch):
    calls = []

    def handler(r):
        calls.append(r.url.path)
        return httpx.Response(429, json={"s": "error", "code": 429, "message": "Too many requests. Please try again later."})

    mock_http(monkeypatch, handler)
    with pytest.raises(fyers_auth.FyersAuthError, match="HTTP 429"):
        run(fyers_auth.get_access_token(FakeDb()))
    assert fyers_auth._last_failure["wait"] == fyers_auth.RATE_LIMIT_COOLDOWN == 3600
    n = len(calls)
    with pytest.raises(fyers_auth.FyersAuthError, match="cooling down"):
        run(fyers_auth.get_access_token(FakeDb()))
    assert len(calls) == n                                   # nothing was sent while cooling down
