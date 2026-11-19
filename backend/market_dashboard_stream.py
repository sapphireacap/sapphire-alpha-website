"""
Live per-index price ticks for Market Dashboard, layered on the same shared
Dhan relay P&F Studio and Index Vector already use (dhan_stream.py).
Market Dashboard's numbers are index LEVELS (LTP), not an option-derived
signal that needs recomputing -- so unlike index_vector_stream.py there's
no recompute step here: a tick just overwrites this index's cached
last/change/change_pct and pushes straight to whoever's watching.

Market Dashboard's underlying source stays NSE's own `allIndices` poll for
everything this can't cover (advances/declines, 52-week hi/lo, FII/DII,
Yahoo global indices, and NIFTY CONSUMER DURABLES which Dhan's master has
no equivalent for -- see market_dashboard_engine.DHAN_INDEX_ALIAS and
STREAMABLE_INDICES). This only makes the price *ticks* for the ~20
resolvable indices feel live between snapshot refreshes -- same
"additive, poll stays as fallback" pattern already used for P&F Studio
and Index Vector.

change/change_pct need a previous-close reference that LTP alone can't
supply -- Dhan's Ticker packet (RequestCode 15) carries only price, no
change. So every snapshot refresh (market_dashboard_routes.py's existing
cron cycle) feeds this module that index's freshly NSE-computed
last/change pair via set_reference(), which backs out
previousClose = last - change and caches it; every tick after that
recomputes change/change_pct against that cached reference until the next
snapshot refresh replaces it.
"""
import asyncio
import logging
import re

import dhan_master
import market_dashboard_engine as mde

logger = logging.getLogger(__name__)


# Fyers' names for the few indices whose NSE name differs, verified against Fyers' public symbol file
# 2026-11-19. Two indices have no Fyers symbol at all and stay on the NSE poll like before.
FYERS_INDEX_ALIAS = {
    "NIFTY HEALTHCARE INDEX": "NIFTYHEALTHCARE", "NIFTY TOTAL MARKET": "NIFTYTOTALMKT",
    "NIFTY PRIVATE BANK": "NIFTYPVTBANK", "NIFTY CONSUMER DURABLES": "NIFTYCONSRDURBL",
}
FYERS_UNAVAILABLE = {"NIFTY SMALLCAP 250", "NIFTY MIDSMALLCAP 400"}


def fyers_symbol(name: str):
    """'NIFTY BANK' -> 'NSE:NIFTYBANK-INDEX'; None for indices Fyers does not list."""
    if name in FYERS_UNAVAILABLE:
        return None
    core = FYERS_INDEX_ALIAS.get(name) or re.sub(r"[^A-Z0-9]", "", name.upper().replace("&", "AND"))
    return f"NSE:{core}-INDEX"


class MarketDashboardBroadcaster:
    """Fans a freshly-ticked index price out to every browser WS connection
    on market_dashboard_routes.py's `/stream` route."""

    def __init__(self):
        self._subscribers: set = set()

    def subscribe(self, handler) -> None:
        self._subscribers.add(handler)

    def unsubscribe(self, handler) -> None:
        self._subscribers.discard(handler)

    async def notify(self, payload: dict) -> None:
        for handler in list(self._subscribers):
            try:
                await handler(payload)
            except Exception:  # noqa: BLE001 -- one dead browser socket must never break the others
                logger.exception("Market Dashboard broadcaster: handler failed")


broadcaster = MarketDashboardBroadcaster()


class MarketDashboardStreamManager:
    def __init__(self, stream, db):
        self.stream = stream
        self.db = db
        self._key_by_name: dict[str, tuple[str, str]] = {}
        self._prev_close: dict[str, float] = {}
        self._latest: dict[str, dict] = {}
        self._callbacks: dict[str, callable] = {}
        self._started = False
        self._fyers_feed = None
        self._name_by_symbol: dict[str, str] = {}

    def attach_fyers(self, feed) -> None:
        """Take the live index prices from a FYERS feed instead of the Dhan relay (which stays untouched
        and unused while this is attached)."""
        self._fyers_feed = feed

    def _start_fyers(self) -> None:
        for name in sorted(set(mde.STREAMABLE_INDICES) | {"NIFTY CONSUMER DURABLES"}):
            symbol = fyers_symbol(name)
            if symbol:
                self._name_by_symbol[symbol] = name
        self._fyers_feed.add(list(self._name_by_symbol))
        self._fyers_feed.on_tick(self._fyers_tick)
        logger.info("Market Dashboard stream: %d indices on the FYERS feed.", len(self._name_by_symbol))

    def _fyers_tick(self, msg: dict) -> None:
        name = self._name_by_symbol.get(msg.get("tk"))
        if name is None:
            return
        ltp = float(msg["lp"])
        quote = self._fyers_feed.latest.get(msg["tk"]) or {}
        prev_close = quote.get("prev_close") or self._prev_close.get(name)
        change = (ltp - prev_close) if prev_close else None
        change_pct = (change / prev_close * 100) if change is not None and prev_close else None
        entry = {"index": name, "last": ltp, "change": change, "change_pct": change_pct}
        self._latest[name] = entry
        asyncio.ensure_future(broadcaster.notify(entry))

    async def start(self) -> None:
        if self._started:
            return
        self._started = True
        if self._fyers_feed is not None:
            self._start_fyers()
            return
        resolved = 0
        for name in mde.STREAMABLE_INDICES:
            dhan_name = mde.DHAN_INDEX_ALIAS.get(name, name)
            try:
                entry = await dhan_master.resolve("NSE", dhan_name, db=self.db)
            except dhan_master.DhanMasterError as e:
                logger.warning("Market Dashboard stream: master lookup failed for %s: %s", name, e)
                continue
            if not entry:
                logger.warning("Market Dashboard stream: %s (%s) did not resolve on Dhan's master.", name, dhan_name)
                continue
            key = (entry["exchange_segment"], entry["security_id"])
            self._key_by_name[name] = key
            cb = self._make_callback(name)
            self._callbacks[name] = cb
            await self.stream.subscribe(*key, cb)
            resolved += 1
        logger.info("Market Dashboard stream: subscribed to %d/%d indices.", resolved, len(mde.STREAMABLE_INDICES))

    async def stop(self) -> None:
        self._started = False
        for name, key in list(self._key_by_name.items()):
            cb = self._callbacks.get(name)
            if cb is not None:
                await self.stream.unsubscribe(*key, cb)
        self._callbacks.clear()
        self._key_by_name.clear()

    def set_reference(self, name: str, last, change) -> None:
        """Called after every snapshot refresh with that index's freshly
        NSE-computed last/change -- backs out previousClose so subsequent
        LTP-only ticks can keep computing a live change/change_pct."""
        if last is None or change is None:
            return
        try:
            self._prev_close[name] = float(last) - float(change)
        except (TypeError, ValueError):
            pass

    def latest(self) -> dict:
        """{name: {index, last, change, change_pct}} for whatever's ticked
        so far -- used to seed a browser WS connection immediately on
        open, rather than making it wait for the first live tick."""
        return dict(self._latest)

    def _make_callback(self, name: str):
        def _cb(msg: dict) -> None:
            ltp = msg.get("ltp")
            if ltp is None:
                return
            prev_close = self._prev_close.get(name)
            change = (ltp - prev_close) if prev_close else None
            change_pct = (change / prev_close * 100) if change is not None and prev_close else None
            entry = {"index": name, "last": ltp, "change": change, "change_pct": change_pct}
            self._latest[name] = entry
            asyncio.create_task(broadcaster.notify(entry))
        return _cb
