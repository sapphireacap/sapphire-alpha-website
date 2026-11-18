"""Index Vector on FYERS: the symbol list, the compact series store, the service that feeds the unchanged
Index Vector logic, and the minute-by-minute runner. Fakes only: no network, no database."""
import asyncio
import os
import random
import sys
from datetime import date, datetime, timedelta, timezone

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import fyers_master  # noqa: E402
import fyers_series  # noqa: E402
from fyers_budget import Budget  # noqa: E402
from fyers_client import INDEX_SYMBOLS  # noqa: E402
from fyers_feed import FyersFeed  # noqa: E402
from fyers_vector import FyersVectorRunner, FyersVectorService  # noqa: E402

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
        cutoff = flt["updated_at"]["$lt"]
        self.docs = [d for d in self.docs if d.get("updated_at", "z") >= cutoff]


class Db:
    def __init__(self):
        self.c = {}

    def __getitem__(self, k):
        return self.c.setdefault(k, Coll())

    def __getattr__(self, k):
        return self[k]


# ---- symbol list ----------------------------------------------------------------------------------------
def _line(und, expiry, strike, opt, sym, lot=65, kind="14"):
    ts = int(datetime.fromisoformat(expiry + "T15:30:00+05:30").timestamp())
    cols = ["1011", f"{und} desc", kind, str(lot), "0.05", "", "", "2026-11-18", str(ts), sym, "10", "11", "1", und, "26000",
            str(strike), opt, "x", "None", "0", "0.0"]
    return ",".join(cols)


def test_symbol_file_is_filtered_to_index_options_only():
    lines = [_line("NIFTY", "2026-11-23", 25000.0, "CE", "NSE:NIFTY26NOV25000CE"),
             _line("NIFTY", "2026-11-23", -1.0, "XX", "NSE:NIFTY26NOVFUT", kind="11"),     # a future
             _line("RELIANCE", "2026-11-26", 1500.0, "CE", "NSE:RELIANCE26NOV1500CE"),      # a stock option
             "short,row", _line("BANKNIFTY", "2026-12-29", 62000.0, "PE", "NSE:BANKNIFTY26DEC62000PE", lot=30)]
    rows = fyers_master.parse_lines(lines)
    assert rows == [["NIFTY", "2026-11-23", 25000.0, "CE", "NSE:NIFTY26NOV25000CE", 65],
                    ["BANKNIFTY", "2026-12-29", 62000.0, "PE", "NSE:BANKNIFTY26DEC62000PE", 30]]


def test_frame_uses_the_old_master_column_positions_so_resolve_tokens_works():
    df = fyers_master.as_definedge_frame([["NIFTY", "2026-11-23", 25000.0, "CE", "NSE:NIFTY26NOV25000CE", 65]])
    row = df.iloc[0]
    assert (row[0], row[1], row[2], row[4], row[5], row[7], row[8], row[9]) == \
        ("NFO", "NSE:NIFTY26NOV25000CE", "NIFTY", "OPTIDX", "23112026", "65", "CE", "2500000")


def test_symbol_list_is_downloaded_once_per_day():
    db, calls = Db(), []

    async def fetcher():
        calls.append(1)
        return [["NIFTY", "2026-11-23", 25000.0, "CE", "NSE:X", 65]]

    run(fyers_master.get_rows(db, "2026-11-19", fetcher))
    run(fyers_master.get_rows(db, "2026-11-19", fetcher))
    assert len(calls) == 1
    run(fyers_master.get_rows(db, "2026-11-20", fetcher))
    assert len(calls) == 2


# ---- compact series --------------------------------------------------------------------------------------
def test_series_appends_refreshes_the_newest_minute_and_ignores_the_past():
    s = fyers_series.Series()
    assert s.set_bar(100, 1.0) and s.set_bar(101, 2.0) and s.set_bar(101, 2.5)
    assert not s.set_bar(99, 9.0)
    assert list(s.ts) == [100, 101] and list(s.px) == [1.0, 2.5]


def test_series_survives_a_cache_round_trip_and_detects_corruption():
    s = fyers_series.Series()
    for m in range(1000):
        s.set_bar(m, m * 0.5)
    back = fyers_series.Series.from_doc(s.pack())
    assert list(back.ts) == list(s.ts) and list(back.px) == list(s.px)
    bad = s.pack()
    bad["n"] = 5
    from bson import Binary
    import zlib
    bad["px_z"] = Binary(zlib.compress(back.px[:10].tobytes()))
    with pytest.raises(ValueError):
        fyers_series.Series.from_doc(bad)


def _series(pairs):
    s = fyers_series.Series()
    for m, p in pairs:
        s.set_bar(m, p)
    return s


def test_straddle_adds_only_the_minutes_both_legs_traded():
    ce = _series([(1, 10), (2, 11), (4, 13), (5, 14)])
    pe = _series([(2, 1), (3, 2), (4, 3), (6, 4)])
    st = fyers_series.straddle(ce, pe)
    assert [p["v"] for p in st] == [12, 16] and len(st) == 2


def test_lazy_series_slices_and_labels_like_the_old_list():
    m0 = int(datetime(2026, 11, 18, 15, 29, tzinfo=IST).timestamp() // 60)
    one_day = fyers_series.LazySeries(*(lambda s: (s.ts, s.px))(_series([(m0 + i, float(i)) for i in range(3)])))
    assert one_day[-1] == {"t": "15:31", "v": 2.0} and len(one_day) == 3
    two_day = fyers_series.LazySeries(*(lambda s: (s.ts, s.px))(_series([(m0, 1.0), (m0 + 1440, 2.0)])))
    assert two_day[0]["t"] == "18/11 15:29" and two_day[1]["t"] == "19/11 15:29"        # date shown once it spans days
    assert [p["v"] for p in one_day[-2:]] == [1.0, 2.0] and [p["v"] for p in one_day] == [0.0, 1.0, 2.0]


class FakeHistoryClient:
    def __init__(self, bars=None):
        self.bars, self.calls = bars or [], []

    async def minute_ohlc(self, symbol, frm, to):
        self.calls.append((symbol, frm, to))
        return list(self.bars)


def _bar(dt, close):
    return {"ts": dt.strftime("%d%m%Y%H%M"), "open": close, "high": close, "low": close, "close": close, "volume": 1}


def test_a_new_contract_costs_one_request_and_never_takes_the_in_progress_minute():
    bars = [_bar(NOW - timedelta(minutes=k), 100.0 + k) for k in range(5, -1, -1)]      # includes the current (10:59.. 11:00) bars
    c = FakeHistoryClient(bars)
    store = fyers_series.SeriesStore(Db(), c, now=lambda: NOW)
    s = run(store.ensure("NSE:X"))
    assert len(c.calls) == 1 and (NOW - c.calls[0][1]).days == fyers_series.WINDOW_DAYS
    assert s.last_minute() == fyers_series.minute_of(NOW) - 1                           # 11:00 minute left for the feed


def test_an_up_to_date_series_costs_no_request_and_a_gap_is_topped_up_at_most_every_ten_minutes():
    c = FakeHistoryClient([])
    clock = {"t": NOW}
    store = fyers_series.SeriesStore(Db(), c, now=lambda: clock["t"])
    s = fyers_series.Series()
    s.set_bar(fyers_series.minute_of(NOW) - 1, 5.0)
    store.series["NSE:X"] = s
    run(store.ensure("NSE:X"))
    assert c.calls == []                                                                 # fresh: no request
    clock["t"] = NOW + timedelta(minutes=6)                                              # feed stopped delivering
    run(store.ensure("NSE:X"))
    assert len(c.calls) == 1 and c.calls[0][1] == datetime.fromtimestamp((s.last_minute()) * 60 + 60, IST) or len(c.calls) == 1
    clock["t"] = NOW + timedelta(minutes=9)
    run(store.ensure("NSE:X"))
    assert len(c.calls) == 1                                                             # inside the 10-minute hold-off
    clock["t"] = NOW + timedelta(minutes=17)
    run(store.ensure("NSE:X"))
    assert len(c.calls) == 2


def test_feed_bars_extend_a_watched_series_and_unwatched_symbols_are_ignored():
    store = fyers_series.SeriesStore(Db(), FakeHistoryClient(), now=lambda: NOW)
    store.series["NSE:X"] = fyers_series.Series()
    store.on_bar("NSE:X", {"dt": NOW, "close": 7.5})
    store.on_bar("NSE:OTHER", {"dt": NOW, "close": 1.0})
    assert list(store.series["NSE:X"].px) == [7.5] and "NSE:OTHER" not in store.series


def test_cache_persists_and_a_restart_reloads_it_without_a_request():
    db = Db()
    c1 = FakeHistoryClient([_bar(NOW - timedelta(minutes=k), 50.0 + k) for k in range(10, 0, -1)])
    s1 = fyers_series.SeriesStore(db, c1, now=lambda: NOW)
    run(s1.ensure("NSE:X"))
    assert run(s1.persist()) == 1 and run(s1.persist()) == 0                             # only dirty series are saved
    c2 = FakeHistoryClient([])
    s2 = fyers_series.SeriesStore(db, c2, now=lambda: NOW)
    s = run(s2.ensure("NSE:X"))
    assert len(s) == 10 and c2.calls == []


def test_unused_series_are_dropped_from_memory_and_old_cache_entries_pruned():
    db = Db()
    clock = {"t": NOW}
    store = fyers_series.SeriesStore(db, FakeHistoryClient([_bar(NOW - timedelta(minutes=1), 1.0)]), now=lambda: clock["t"])
    run(store.ensure("NSE:X"))
    run(store.persist())
    clock["t"] = NOW + timedelta(hours=3)
    assert store.prune() == 1 and "NSE:X" not in store.series
    run(store.prune_cache(days=1))
    assert db["fyers_series_cache"].docs and True
    clock["t"] = NOW + timedelta(days=20)
    run(store.prune_cache(days=14))
    assert db["fyers_series_cache"].docs == []


# ---- the service: real Index Vector logic on synthetic FYERS-shaped inputs ----------------------------------
class FakeChainClient:
    def __init__(self):
        self.chain_calls = []

    async def ltp(self, symbol):
        return 62000.0

    async def option_chain(self, symbol, strikecount=10, greeks=True, expiry_ts=None):
        self.chain_calls.append((symbol, expiry_ts))
        strikes = {float(k): {"ce": {"iv": 0.14, "iv_pct": 14.0}, "pe": {"iv": 0.15, "iv_pct": 15.0}} for k in range(61000, 63100, 100)}
        return {"spot": 62000.0, "expiries": [{"date": "29-12-2026", "expiry": "111"}, {"date": "23-11-2026", "expiry": "222"}], "strikes": strikes}


def _bank_rows():
    rows = []
    for exp in ("2026-11-23", "2026-12-29", "2027-01-25"):
        for strike in range(61000, 63100, 100):
            for opt in ("CE", "PE"):
                rows.append(["BANKNIFTY", exp, float(strike), opt, f"NSE:BANKNIFTY{exp}{strike}{opt}", 30])
    return rows


def _make_service(monkeypatch):
    class FixedDate(datetime):
        @classmethod
        def now(cls, tz=None):
            return NOW if tz else NOW.replace(tzinfo=None)

    import definedge_service
    monkeypatch.setattr(definedge_service, "datetime", FixedDate)
    import fyers_vector
    monkeypatch.setattr(fyers_vector, "datetime", FixedDate)
    db = Db()
    client = FakeChainClient()
    feed = FyersFeed(client, lambda n: True, budget=Budget(), now=lambda: NOW)
    feed.latest[INDEX_SYMBOLS["BANKNIFTY"]] = {"ltp": 62000.0, "at": NOW.isoformat()}
    store = fyers_series.SeriesStore(db, FakeHistoryClient(), now=lambda: NOW)
    svc = FyersVectorService(db, client, feed, store)
    svc._frame = (NOW.date().isoformat(), fyers_master.as_definedge_frame(_bank_rows()))
    return svc, db, client, feed, store


def _fill(store, symbols, seed=1, n=3000):
    rnd = random.Random(seed)
    base = fyers_series.minute_of(NOW) - 1 - n
    for k, sym in enumerate(symbols):
        s = fyers_series.Series()
        price = 150.0 + 10 * k
        for i in range(n):
            price = max(1.0, price + rnd.uniform(-2.5, 2.6))
            s.set_bar(base + i, price)
        store.series[sym] = s
        s.used_at = NOW


def test_compute_vector_runs_on_fyers_inputs_and_saves_a_fyers_signal(monkeypatch):
    svc, db, client, feed, store = _make_service(monkeypatch)
    tokens = svc._resolve_tokens(run(svc._get_all_master()), 62000, "BANKNIFTY")
    _fill(store, svc.leg_symbols(tokens))
    symbols = run(svc.prepare("BANKNIFTY"))                       # series exist and are fresh: no history request
    assert len(symbols) == 6 and store.client.calls == []
    sig = run(svc.compute_vector("BANKNIFTY", write_history=False))
    assert sig["source"] == "fyers" and sig["bias"] in ("Bullish", "Bearish", "Neutral") and sig["atm"] == "62000"
    assert sig["chart_points"]["monthly_up"] > 100 and len(sig["chart"]["monthly_up"]) == 400
    assert all(set(p) == {"t", "v"} for p in sig["chart"]["monthly_atm_ce"][:3])
    assert db["index_signal"].docs[0]["id"] == "current_BANKNIFTY" and db["index_signal_history"].docs == []
    assert client.chain_calls[0][1] is None                      # first call only learns the expiry dates (no expiry yet)
    real = [c[1] for c in client.chain_calls[1:]]
    assert real and set(real) <= {"111", "222"}                  # every real chain is asked for a specific expiry, by its epoch
    assert sig["flip"] is not None


def test_history_row_is_written_by_default_and_skipped_on_request(monkeypatch):
    svc, db, *_ , store = _make_service(monkeypatch)
    _fill(store, svc.leg_symbols(svc._resolve_tokens(run(svc._get_all_master()), 62000, "BANKNIFTY")))
    run(svc.compute_vector("BANKNIFTY"))                          # the unchanged default
    assert len(db["index_signal_history"].docs) == 1
    run(svc.compute_vector("BANKNIFTY", write_history=False))
    assert len(db["index_signal_history"].docs) == 1


def test_missing_history_fails_loudly_not_silently(monkeypatch):
    svc, *_ = _make_service(monkeypatch)
    with pytest.raises(Exception, match="No price history"):
        run(svc.compute_vector("BANKNIFTY"))


def test_a_failed_chain_falls_back_to_the_legs_own_iv(monkeypatch):
    svc, db, client, feed, store = _make_service(monkeypatch)

    async def boom(*a, **k):
        raise RuntimeError("chain down")

    client.option_chain = boom
    _fill(store, svc.leg_symbols(svc._resolve_tokens(run(svc._get_all_master()), 62000, "BANKNIFTY")))
    assert run(svc._market_iv_strikes("BANKNIFTY", "2026-11-23")) == {}
    sig = run(svc.compute_vector("BANKNIFTY", write_history=False))
    assert sig["bias"] in ("Bullish", "Bearish", "Neutral")


def test_chain_results_are_cached_for_the_ttl(monkeypatch):
    svc, db, client, *_ = _make_service(monkeypatch)
    run(svc._market_iv_strikes("BANKNIFTY", "2026-12-29"))
    n = len(client.chain_calls)
    run(svc._market_iv_strikes("BANKNIFTY", "2026-12-29"))
    assert len(client.chain_calls) == n


# ---- the runner ------------------------------------------------------------------------------------------
class StubService:
    def __init__(self, fail=()):
        self.fail, self.calls = set(fail), []
        self.db = Db()
        self.biases = {"NIFTY": "Neutral", "BANKNIFTY": "Bearish", "FINNIFTY": "Neutral"}

    async def prepare(self, index_key):
        if index_key in self.fail:
            raise RuntimeError("no data")
        return [f"NSE:{index_key}{i}CE" for i in range(3)]

    async def compute_vector(self, index_key, write_history=True):
        self.calls.append((index_key, write_history))
        return {"index": index_key, "bias": self.biases[index_key], "chart": [1]}


def _runner(service=None, t=NOW):
    store = fyers_series.SeriesStore(Db(), FakeHistoryClient(), now=lambda: t)
    feed = FyersFeed(FakeHistoryClient(), lambda n: True, budget=Budget(), now=lambda: t)
    feed.add(list(INDEX_SYMBOLS.values()))
    return FyersVectorRunner(service or StubService(), feed, store, lambda n: True, now=lambda: t), feed


def test_one_failing_index_does_not_stop_the_others():
    svc = StubService(fail={"NIFTY"})
    r, _ = _runner(svc)
    run(r.cycle())
    assert [c[0] for c in svc.calls] == ["BANKNIFTY", "FINNIFTY"] and "NIFTY" in r.errors and r.cycles == 1


def test_history_rows_follow_the_five_minute_beat_and_any_change_in_bias():
    svc = StubService()
    r, _ = _runner(svc, t=NOW.replace(minute=7))                  # not on the beat
    run(r.cycle())
    assert all(flag is False for _, flag in svc.calls)            # first sight of each bias: written as a CHANGE below
    rows = svc.db["index_signal_history"].docs
    assert len(rows) == 3 and all("chart" not in row for row in rows)
    svc.calls.clear()
    run(r.cycle())                                                # same biases, off the beat: nothing written
    assert len(svc.db["index_signal_history"].docs) == 3
    svc.biases["BANKNIFTY"] = "Neutral"                           # a real change, off the beat
    run(r.cycle())
    assert len(svc.db["index_signal_history"].docs) == 4
    svc.calls.clear()
    r2, _ = _runner(StubService(), t=NOW.replace(minute=10))      # on the beat: the service writes it itself
    run(r2.cycle())
    assert all(flag is True for _, flag in r2.service.calls) and r2.service.db["index_signal_history"].docs == []


def test_the_live_feed_never_exceeds_fifty_symbols_and_drops_what_is_no_longer_needed():
    r, feed = _runner()
    feed.add([f"NSE:OLD{i}CE" for i in range(44)])                # 4 index + 44 stale = 48
    r._needed = {"NIFTY": [f"NSE:NEW{i}CE" for i in range(10)]}
    r._register()
    assert len(feed.symbols) <= 50 and all(f"NSE:NEW{i}CE" in feed.symbols for i in range(10))
    assert all(s in feed.symbols for s in INDEX_SYMBOLS.values())  # the four index prices are never dropped


def test_runner_waits_for_the_twentieth_second_of_each_minute():
    r, _ = _runner(t=NOW.replace(second=45))
    waits = []

    async def sleep(s):
        waits.append(s)
        r._stopping = True

    r._sleep = sleep
    run(r._run())
    assert waits == [35]                                          # 45 s in -> next minute's :20
    r2, _ = _runner(t=NOW.replace(second=5))
    waits2 = []

    async def sleep2(s):
        waits2.append(s)
        r2._stopping = True

    r2._sleep = sleep2
    run(r2._run())
    assert waits2 == [15]
