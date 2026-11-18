"""The FYERS live-price feed: polling, 1-minute bars, market hours, budget behaviour, error handling.
Fake client and fake clock only: no network."""
import asyncio
import os
import sys
from datetime import datetime, timedelta, timezone

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import fyers_auth  # noqa: E402
import fyers_feed  # noqa: E402
from fyers_budget import Budget, FyersBudgetError  # noqa: E402
from fyers_client import FyersError, FyersRateLimited  # noqa: E402

IST = timezone(timedelta(hours=5, minutes=30))
NIFTY, BANK = "NSE:NIFTY50-INDEX", "NSE:NIFTYBANK-INDEX"


def run(coro):
    return asyncio.run(coro)


class FakeClient:
    def __init__(self, prices=None):
        self.prices = prices or {NIFTY: 25000.0, BANK: 55000.0}
        self.calls = []
        self.raise_next = None

    async def quotes(self, symbols):
        self.calls.append(list(symbols))
        if self.raise_next:
            e, self.raise_next = self.raise_next, None
            raise e
        return {s: {"ltp": self.prices[s], "open": 1, "high": 2, "low": 0.5, "prev_close": 3} for s in symbols if s in self.prices}


class Clock:
    def __init__(self, t):
        self.t = t

    def now(self):
        return self.t

    def advance(self, seconds):
        self.t += timedelta(seconds=seconds)


@pytest.fixture(autouse=True)
def enabled(monkeypatch):
    monkeypatch.setenv("FYERS_ENABLED", "1")
    monkeypatch.delenv("FYERS_FEED_INTERVAL", raising=False)


def make(prices=None, t=None, is_open=lambda n: True, budget=None):
    clock = Clock(t or datetime(2026, 11, 19, 10, 0, 5, tzinfo=IST))
    client = FakeClient(prices)
    feed = fyers_feed.FyersFeed(client, is_open, budget=budget or Budget(), now=clock.now)
    return feed, client, clock


def test_poll_updates_latest_prices_and_emits_ticks_in_the_shared_shape():
    feed, client, _ = make()
    feed.add([NIFTY, BANK])
    ticks = []
    feed.on_tick(ticks.append)
    assert run(feed.poll_once()) == 2
    assert feed.latest[NIFTY]["ltp"] == 25000.0 and len(client.calls) == 1            # ONE request for both symbols
    assert {"t": "tf", "e": "FYERS", "tk": NIFTY, "lp": "25000.00"} in ticks


def test_symbol_cap_is_one_quotes_request():
    feed, *_ = make()
    feed.add([f"NSE:S{i}-EQ" for i in range(50)])
    with pytest.raises(ValueError, match="limited to 50"):
        feed.add(["NSE:ONE-MORE-EQ"])
    assert feed.add(["NSE:S0-EQ"]) == []              # exactly 50 are allowed; re-adding an existing symbol is harmless


def test_duplicates_are_not_added_twice():
    feed, *_ = make()
    assert feed.add([NIFTY, NIFTY, BANK]) == [NIFTY, BANK]
    assert feed.add([NIFTY]) == []


def test_samples_within_a_minute_become_one_ohlc_bar_emitted_at_the_next_minute():
    feed, client, clock = make()
    feed.add([NIFTY])
    bars = []
    feed.on_bar(lambda sym, bar: bars.append((sym, bar)))
    for price in (100.0, 103.0, 99.0, 101.0):               # four 15-second polls inside 10:00
        client.prices[NIFTY] = price
        run(feed.poll_once())
        clock.advance(15)
    assert bars == []                                        # minute still open
    client.prices[NIFTY] = 102.0
    clock.advance(10)                                        # now in 10:01
    run(feed.poll_once())
    assert len(bars) == 1
    sym, bar = bars[0]
    assert sym == NIFTY and bar["ts"] == "191120261000"
    assert (bar["open"], bar["high"], bar["low"], bar["close"]) == (100.0, 103.0, 99.0, 101.0)
    assert bar["dt"].tzinfo is not None and list(feed.bars[NIFTY])[0]["close"] == 101.0


def test_flush_finishes_the_open_bar():
    feed, *_ = make()
    feed.add([NIFTY])
    run(feed.poll_once())
    assert feed.bars.get(NIFTY) is None
    feed.flush()
    assert len(feed.bars[NIFTY]) == 1


def test_missing_or_null_prices_are_skipped_not_invented():
    feed, client, _ = make({NIFTY: 25000.0})
    feed.add([NIFTY, BANK])
    assert run(feed.poll_once()) == 1 and BANK not in feed.latest


def test_a_failing_callback_does_not_stop_the_feed():
    feed, *_ = make()
    feed.add([NIFTY])
    seen = []
    feed.on_tick(lambda t: 1 / 0)
    feed.on_tick(seen.append)
    run(feed.poll_once())
    assert len(seen) == 1


def test_interval_stretches_then_polling_stops_as_the_daily_budget_is_used():
    b = Budget()
    feed, *_ = make(budget=b)
    assert feed.effective_interval() == 15 and not feed.budget_exhausted()
    b.count = 3600
    assert feed.effective_interval() == 60 and not feed.budget_exhausted()
    b.count = 4300
    assert feed.budget_exhausted()


def test_interval_comes_from_env_but_never_below_five_seconds(monkeypatch):
    monkeypatch.setenv("FYERS_FEED_INTERVAL", "1")
    assert fyers_feed._base_interval() == 5.0
    monkeypatch.setenv("FYERS_FEED_INTERVAL", "30")
    assert fyers_feed._base_interval() == 30.0
    monkeypatch.setenv("FYERS_FEED_INTERVAL", "junk")
    assert fyers_feed._base_interval() == 15.0


def _drive(feed, steps):
    """Runs the feed loop for `steps` iterations with a fake sleep that records waits."""
    waits = []

    async def sleep(s):
        waits.append(s)
        if len(waits) >= steps:
            feed._stopping = True

    feed._sleep = sleep
    run(feed._run())
    return waits


def test_loop_polls_only_while_the_market_is_open_and_flushes_when_it_closes():
    state = {"open": True}
    feed, client, _ = make(is_open=lambda n: state["open"])
    feed.add([NIFTY])
    waits = []

    async def sleep(s):
        waits.append(s)
        if len(waits) == 1:
            state["open"] = False                            # the session ends after the first poll
        if len(waits) >= 3:
            feed._stopping = True

    feed._sleep = sleep
    run(feed._run())
    assert len(client.calls) == 1                            # polled once while open, never after
    assert waits[0] == 15 and waits[1] == 30                 # normal interval, then the idle wait
    assert len(feed.bars[NIFTY]) == 1                        # the last minute was flushed at the close


def test_loop_is_idle_when_fyers_is_disabled(monkeypatch):
    monkeypatch.delenv("FYERS_ENABLED")
    feed, client, _ = make()
    feed.add([NIFTY])
    _drive(feed, 2)
    assert client.calls == []


@pytest.mark.parametrize("error, expected_wait", [
    (FyersRateLimited("429"), 60), (FyersBudgetError("minute"), 60),
    (fyers_auth.FyersAuthError("login cooling down"), 120), (FyersError("bad"), 30), (RuntimeError("boom"), 30)])
def test_errors_are_counted_and_the_loop_backs_off_instead_of_dying(error, expected_wait):
    feed, client, _ = make()
    feed.add([NIFTY])
    client.raise_next = error
    waits = _drive(feed, 2)
    assert waits[0] == expected_wait and feed.errors == 1 and type(error).__name__ in feed.last_error
    assert len(client.calls) == 2                            # it kept going and polled again


def test_no_symbols_means_no_requests():
    feed, client, _ = make()
    _drive(feed, 2)
    assert client.calls == []


def test_snapshot_is_admin_safe():
    feed, *_ = make()
    feed.add([NIFTY])
    run(feed.poll_once())
    snap = feed.snapshot()
    assert snap["prices"] == {NIFTY: 25000.0} and snap["polls"] == 1 and snap["symbols"] == [NIFTY]
    assert "token" not in str(snap).lower()
