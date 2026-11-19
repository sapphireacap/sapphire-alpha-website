"""Markets tab live index prices from the FYERS feed: name mapping and tick conversion."""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import market_dashboard_engine as mde  # noqa: E402
import market_dashboard_stream as mds  # noqa: E402


class FakeFeed:
    def __init__(self):
        self.symbols, self.latest, self.cbs = [], {}, []

    def add(self, symbols):
        self.symbols += symbols

    def on_tick(self, cb):
        self.cbs.append(cb)


def test_name_mapping():
    assert mds.fyers_symbol("NIFTY 50") == "NSE:NIFTY50-INDEX"
    assert mds.fyers_symbol("NIFTY BANK") == "NSE:NIFTYBANK-INDEX"
    assert mds.fyers_symbol("INDIA VIX") == "NSE:INDIAVIX-INDEX"
    assert mds.fyers_symbol("NIFTY OIL & GAS") == "NSE:NIFTYOILANDGAS-INDEX"
    assert mds.fyers_symbol("NIFTY PRIVATE BANK") == "NSE:NIFTYPVTBANK-INDEX"
    assert mds.fyers_symbol("NIFTY SMALLCAP 250") is None            # not listed by FYERS: stays on the NSE poll


def test_every_index_either_maps_or_is_a_known_gap():
    names = set(mde.STREAMABLE_INDICES) | {"NIFTY CONSUMER DURABLES"}
    mapped = [n for n in names if mds.fyers_symbol(n)]
    assert len(mapped) == len(names) - len(mds.FYERS_UNAVAILABLE & names)
    assert len(mapped) <= 50                                         # one quotes request


def test_ticks_become_dashboard_entries_with_change_from_previous_close():
    async def go():
        feed, sent = FakeFeed(), []

        async def capture(entry):
            sent.append(entry)
        mds.broadcaster.subscribe(capture)
        mgr = mds.MarketDashboardStreamManager(None, None)
        mgr.attach_fyers(feed)
        await mgr.start()
        assert "NSE:NIFTYBANK-INDEX" in feed.symbols and len(feed.cbs) == 1
        feed.latest["NSE:NIFTYBANK-INDEX"] = {"ltp": 62100.0, "prev_close": 62000.0}
        feed.cbs[0]({"t": "tf", "e": "FYERS", "tk": "NSE:NIFTYBANK-INDEX", "lp": "62100.00"})
        feed.cbs[0]({"tk": "NSE:UNKNOWN-INDEX", "lp": "1"})           # ignored
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        mds.broadcaster.unsubscribe(capture)
        entry = mgr.latest()["NIFTY BANK"]
        assert entry["last"] == 62100.0 and entry["change"] == 100.0 and round(entry["change_pct"], 3) == 0.161
        assert sent and sent[0]["index"] == "NIFTY BANK" and len(mgr.latest()) == 1
    asyncio.run(go())


def test_falls_back_to_the_snapshot_reference_when_the_quote_has_no_previous_close():
    async def go():
        feed = FakeFeed()
        mgr = mds.MarketDashboardStreamManager(None, None)
        mgr.attach_fyers(feed)
        await mgr.start()
        mgr.set_reference("NIFTY 50", 25200.0, 50.0)                  # previous close 25150
        feed.cbs[0]({"tk": "NSE:NIFTY50-INDEX", "lp": "25250.00"})
        assert mgr.latest()["NIFTY 50"]["change"] == 100.0
        feed2 = FakeFeed()
        mgr2 = mds.MarketDashboardStreamManager(None, None)
        mgr2.attach_fyers(feed2)
        await mgr2.start()
        feed2.cbs[0]({"tk": "NSE:NIFTY50-INDEX", "lp": "25250.00"})   # no reference at all: price still shown
        assert mgr2.latest()["NIFTY 50"]["change"] is None
        await asyncio.sleep(0)
    asyncio.run(go())
