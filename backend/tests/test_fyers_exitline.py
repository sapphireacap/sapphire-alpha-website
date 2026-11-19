"""Exitline on FYERS: the symbol-file parsing, the daily-rebuilt lookup documents, the price/history
caching and the response. Fakes only: no network, no database."""
import asyncio
import os
import sys
from datetime import datetime, timedelta, timezone

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import fyers_exitline as fx  # noqa: E402
from fyers_feed import FyersFeed  # noqa: E402

IST = timezone(timedelta(hours=5, minutes=30))
NOW = datetime(2026, 11, 19, 11, 0, 30, tzinfo=IST)


def run(coro):
    return asyncio.run(coro)


class Coll:
    def __init__(self):
        self.docs = []

    async def find_one(self, flt, proj=None):
        for d in self.docs:
            if all(d.get(k) == v for k, v in flt.items()):
                return dict(d)
        return None

    async def update_one(self, flt, upd, upsert=False):
        for d in self.docs:
            if all(d.get(k) == v for k, v in flt.items()):
                d.update(upd["$set"])
                return
        if upsert:
            self.docs.append({**flt, **upd["$set"]})

    async def insert_one(self, doc):
        self.docs.append(dict(doc))

    async def delete_many(self, flt):
        if "date" not in flt.get("id", {}) and "date" not in flt:
            return
        keep = []
        for d in self.docs:
            gone = d["id"].startswith("fo:") and d.get("date") != flt["date"]["$ne"]
            if not gone:
                keep.append(d)
        self.docs = keep


class Db:
    def __init__(self):
        self.c = {}

    def __getitem__(self, k):
        return self.c.setdefault(k, Coll())

    def __getattr__(self, k):
        return self[k]


def epoch(iso):
    return int(datetime.fromisoformat(iso).replace(hour=15, minute=30, tzinfo=IST).timestamp())


def cm(kind, symbol, name):
    return ",".join(["1", "d", kind, "1", "0.05", "", "", "", "", symbol, "10", "10", "1", name, "1", "-1.0", "XX", "1", "None", "0", "0"])


def fo(kind, symbol, name, exp, strike, opt):
    return ",".join(["1", "d", kind, "50", "0.05", "", "", "", str(epoch(exp)), symbol, "10", "11", "1", name, "1", str(strike), opt])


CASH = [cm("0", "NSE:RELIANCE-EQ", "RELIANCE"), cm("0", "NSE:20MICRONS-BE", "20MICRONS"), cm("10", "NSE:NIFTY50-INDEX", "NIFTY"),
        cm("10", "NSE:NIFTYBANK-INDEX", "BANKNIFTY"), cm("0", "NSE:NIFTY-EQ", "NIFTY")]
FO = [fo("13", "NSE:RELIANCE26NOVFUT", "RELIANCE", "2026-11-24", -1.0, "XX"),
      fo("13", "NSE:RELIANCE26DECFUT", "RELIANCE", "2026-12-29", -1.0, "XX"),
      fo("15", "NSE:RELIANCE26NOV1400CE", "RELIANCE", "2026-11-24", 1400.0, "CE"),
      fo("15", "NSE:RELIANCE26NOV1400PE", "RELIANCE", "2026-11-24", 1400.0, "PE"),
      fo("15", "NSE:RELIANCE26NOV1500CE", "RELIANCE", "2026-11-24", 1500.0, "CE"),
      fo("14", "NSE:NIFTY26NOV25250CE", "NIFTY", "2026-11-24", 25250.0, "CE"),
      fo("14", "NSE:NIFTY26NOV25250PE", "NIFTY", "2026-11-24", 25250.0, "PE"),
      "short,row"]


def master(today="2026-11-19"):
    calls = {"n": 0}

    async def fetcher():
        calls["n"] += 1
        cash, fo_ = {}, {}
        fx.parse_cash(CASH, cash)
        fx.parse_fo(FO, fo_)
        return cash, fo_

    return fx.MasterStore(Db(), fetcher, lambda: today), calls


# ---- parsing --------------------------------------------------------------------------------------
def test_cash_keeps_only_eq_stocks_and_indices_and_stock_beats_index():
    out = {}
    fx.parse_cash(CASH, out)
    assert out["RELIANCE"] == "NSE:RELIANCE-EQ"
    assert "20MICRONS" not in out                         # -BE series is not a plain equity
    assert out["BANKNIFTY"] == "NSE:NIFTYBANK-INDEX"
    assert out["NIFTY"] == "NSE:NIFTY-EQ"                 # the stock wins, whichever row comes first
    out2 = {}
    fx.parse_cash(list(reversed(CASH)), out2)
    assert out2["NIFTY"] == "NSE:NIFTY-EQ"


def test_fo_groups_futures_and_option_pairs_and_skips_junk():
    out = {}
    fx.parse_fo(FO, out)
    assert out["RELIANCE"]["fut"] == {"2026-11-24": "NSE:RELIANCE26NOVFUT", "2026-12-29": "NSE:RELIANCE26DECFUT"}
    assert out["RELIANCE"]["opt"]["2026-11-24"][1400.0] == ["NSE:RELIANCE26NOV1400CE", "NSE:RELIANCE26NOV1400PE"]
    assert out["RELIANCE"]["opt"]["2026-11-24"][1500.0] == ["NSE:RELIANCE26NOV1500CE", None]
    assert out["NIFTY"]["fut"] == {}


# ---- the lookups ---------------------------------------------------------------------------------
def test_lookups_end_to_end():
    m, calls = master()
    assert run(m.list_symbols("NSE", "rel")) == ["RELIANCE"]
    assert run(m.list_symbols("FUT")) == ["RELIANCE"]
    assert run(m.list_symbols("OPT")) == ["NIFTY", "RELIANCE"]
    assert run(m.list_expiries("FUT", "reliance")) == ["2026-11-24", "2026-12-29"]
    assert run(m.list_expiries("OPT", "RELIANCE")) == ["2026-11-24"]
    assert run(m.list_strikes("RELIANCE", "2026-11-24")) == [1400.0, 1500.0]
    assert run(m.list_expiries("OPT", "NOPE")) == []
    assert run(m.resolve("NSE", "reliance")) == {"symbol": "NSE:RELIANCE-EQ", "tradingsymbol": "RELIANCE-EQ"}
    assert run(m.resolve("FUT", "RELIANCE", "2026-12-29"))["symbol"] == "NSE:RELIANCE26DECFUT"
    assert run(m.resolve("OPT", "RELIANCE", "2026-11-24", 1400, "pe"))["symbol"] == "NSE:RELIANCE26NOV1400PE"
    assert run(m.resolve("OPT", "RELIANCE", "2026-11-24", 1400.5, "CE")) is None
    assert run(m.resolve("OPT", "RELIANCE", "2026-11-24", None, "CE")) is None
    assert run(m.resolve("FUT", "RELIANCE", "2030-01-01")) is None
    assert run(m.resolve("NSE", "NOSUCH")) is None
    assert calls["n"] == 1                                 # one download served every lookup


def test_second_instance_reads_todays_documents_instead_of_downloading():
    m1, calls = master()
    run(m1.list_symbols("NSE"))
    m2 = fx.MasterStore(m1.db, m1._fetch, lambda: "2026-11-19")
    assert run(m2.resolve("NSE", "RELIANCE"))["symbol"] == "NSE:RELIANCE-EQ"
    assert calls["n"] == 1


def test_new_day_rebuilds_and_failed_refresh_falls_back_to_yesterday():
    day = {"d": "2026-11-19"}
    calls = {"n": 0, "fail": False}

    async def fetcher():
        calls["n"] += 1
        if calls["fail"]:
            raise RuntimeError("down")
        cash, fo_ = {}, {}
        fx.parse_cash(CASH, cash)
        fx.parse_fo(FO, fo_)
        return cash, fo_

    m = fx.MasterStore(Db(), fetcher, lambda: day["d"])
    run(m.list_symbols("NSE"))
    day["d"], calls["fail"] = "2026-11-20", True
    m._index = None                                       # a fresh process on the new day
    assert run(m.resolve("NSE", "RELIANCE"))["symbol"] == "NSE:RELIANCE-EQ"      # yesterday's list still serves
    assert calls["n"] == 2
    calls["fail"] = False
    m._index = None
    run(m.list_symbols("NSE"))
    assert run(m.db[fx.COLLECTION].find_one({"id": "index"}))["date"] == "2026-11-20"


def test_first_ever_failure_gives_a_public_message_without_the_vendor():
    async def fetcher():
        raise RuntimeError("HTTP 503 from public.fyers.in")

    m = fx.MasterStore(Db(), fetcher, lambda: "2026-11-19")
    with pytest.raises(fx.ExitlineError) as e:
        run(m.list_symbols("NSE"))
    assert "fyers" not in str(e.value).lower()


# ---- data -------------------------------------------------------------------------------------------
def bar(dt, o=100.0):
    return {"ts": dt.strftime("%d%m%Y%H%M"), "open": o, "high": o + 2, "low": o - 1, "close": o + 1, "volume": 1}


class FakeClient:
    def __init__(self):
        self.minute_calls, self.daily_calls, self.ltp_calls = [], 0, 0

    async def daily_history(self, symbol, years=1, days=None):
        self.daily_calls += 1
        out, d = [], datetime(2026, 11, 19, tzinfo=IST).date() - timedelta(days=1)
        while len(out) < 40:
            if d.weekday() < 5:
                out.append({"date": d.isoformat(), "open": 100, "high": 110, "low": 95, "close": 105, "volume": 1})
            d -= timedelta(days=1)
        return list(reversed(out))

    async def minute_ohlc(self, symbol, frm, to):
        self.minute_calls.append((frm, to))
        out, t = [], frm.replace(hour=9, minute=15)
        while t <= to:
            if t.weekday() < 5 and (9, 15) <= (t.hour, t.minute) <= (15, 29):
                out.append(bar(t))
            t += timedelta(minutes=1)
            if t.hour == 15 and t.minute == 30:
                t = (t + timedelta(days=1)).replace(hour=9, minute=15)
        return out

    async def ltp(self, symbol):
        self.ltp_calls += 1
        return 106.0


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def make(now=NOW):
    feed = FyersFeed(FakeClient(), lambda n: True, interval=15)
    client = FakeClient()
    clock = Clock()
    return fx.ExitlineData(client, feed, now=lambda: now, clock=clock), client, feed, clock


RESOLVED = {"symbol": "NSE:RELIANCE-EQ", "tradingsymbol": "RELIANCE-EQ"}
META = {"segment": "NSE", "symbol": "RELIANCE"}


def test_cold_look_costs_three_history_requests_and_returns_the_old_shape():
    data, client, feed, clock = make()
    out = run(data.build(RESOLVED, META, 5))
    assert client.daily_calls == 1 and len(client.minute_calls) == 2 and client.ltp_calls == 1
    assert out["segment"] == "NSE" and out["tradingsymbol"] == "RELIANCE-EQ"
    assert out["ltp"] == 106.0 and out["levels"] and out["sessions"][-1]["date"] == "2026-11-19"
    assert out["chart"][-1]["date"] == "2026-11-19" and out["chart"][0]["date"] < "2026-11-19"
    assert {"t", "time", "date", "open", "high", "low", "close"} <= set(out["chart"][0])
    assert out["chart"] == sorted(out["chart"], key=lambda r: r["time"])
    assert "RELIANCE-EQ" not in feed.symbols and "NSE:RELIANCE-EQ" in feed.symbols     # followed on the live feed


def test_refresh_costs_one_request_and_viewers_share_a_response():
    data, client, feed, clock = make()
    run(data.build(RESOLVED, META, 5))
    before = len(client.minute_calls)
    run(data.build(RESOLVED, META, 5))                     # within 20 s: shared, no request
    assert len(client.minute_calls) == before
    clock.t += 30
    run(data.build(RESOLVED, META, 5))                     # later: only today's bars again
    assert len(client.minute_calls) == before + 1 and client.daily_calls == 1
    run(data.build(RESOLVED, META, 15))                    # another interval needs its own past chart
    assert len(client.minute_calls) == before + 3


def test_live_feed_price_is_preferred_and_stale_prices_are_not_used():
    data, client, feed, clock = make()
    feed.latest["NSE:RELIANCE-EQ"] = {"ltp": 111.5, "at": NOW.isoformat()}
    assert run(data.live_price("NSE:RELIANCE-EQ")) == 111.5 and client.ltp_calls == 0
    feed.latest["NSE:RELIANCE-EQ"] = {"ltp": 99.0, "at": (NOW - timedelta(minutes=10)).isoformat()}
    assert run(data.live_price("NSE:RELIANCE-EQ")) == 106.0 and client.ltp_calls == 1
    run(data.live_price("NSE:RELIANCE-EQ"))
    assert client.ltp_calls == 1                           # shared for QUOTE_TTL


def test_missing_live_price_keeps_levels_and_chart():
    data, client, feed, clock = make()

    async def boom(symbol):
        raise RuntimeError("no quote")
    client.ltp = boom
    out = run(data.build(RESOLVED, META, 5))
    assert out["ltp"] is None and out["zone_label"] == "Live Price Unavailable" and out["levels"] and out["chart"]


def test_before_the_open_no_todays_request_and_levels_are_last_sessions():
    early = datetime(2026, 11, 19, 8, 0, tzinfo=IST)
    data, client, feed, clock = make(early)
    out = run(data.build(RESOLVED, META, 5))
    assert len(client.minute_calls) == 1                   # past sessions only
    assert out["sessions"][-1]["date"] == "2026-11-18"


def test_no_daily_history_is_a_public_error():
    data, client, feed, clock = make()

    async def none(symbol, years=1, days=None):
        return []
    client.daily_history = none
    with pytest.raises(fx.ExitlineError):
        run(data.build(RESOLVED, META, 5))


def test_watch_list_is_capped_pruned_and_pinned():
    data, client, feed, clock = make()
    for i in range(30):
        data._touch(f"NSE:S{i}-EQ")
    assert len(feed.symbols) <= fx.WATCH_MAX
    assert feed.pinned == set(data._watch)
    clock.t += fx.WATCH_IDLE + 1
    data._touch("NSE:NEW-EQ")
    assert set(data._watch) == {"NSE:NEW-EQ"} and feed.symbols == ["NSE:NEW-EQ"]


def test_a_full_feed_never_overflows():
    data, client, feed, clock = make()
    feed.add([f"NSE:X{i}-EQ" for i in range(50)])
    data._touch("NSE:RELIANCE-EQ")                         # no room: silently not added, price comes from the quote route
    assert len(feed.symbols) == 50


def test_a_failed_chart_still_returns_levels_but_is_not_cached():
    data, client, feed, clock = make()
    real = client.minute_ohlc
    state = {"fail": True}

    async def flaky(symbol, frm, to):
        if state["fail"]:
            raise RuntimeError("transient")
        return await real(symbol, frm, to)
    client.minute_ohlc = flaky
    first = run(data.build(RESOLVED, META, 5))
    assert first["chart"] == [] and first["levels"]
    state["fail"] = False
    second = run(data.build(RESOLVED, META, 5))             # same instant: must retry, not reuse the empty answer
    assert second["chart"]
