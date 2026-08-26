"""
Near-real-time trigger for Index Vector, replacing the 5-minute cron as
the PRIMARY driver (the cron itself stays wired up as a safety-net
fallback -- see server.py -- in case the stream ever drops).

Deliberately simple: subscribes to just the 3 SPOT/INDEX tokens (one per
INDEX_CONFIG entry -- NIFTY, BANKNIFTY, FINNIFTY), not the ~7-11 option
legs each vector actually reads. Reasoning: compute_vector() re-resolves
ATM and re-pulls every leg's full history fresh via REST on every call
(see definedge_service.py:873) -- it was never incremental, and making
it incremental is a separate, much larger project (would need to track
option-leg subscriptions that shift whenever ATM re-centers intraday,
since the specific CE/PE tokens read depend on the current spot price).
All a tick-driven trigger actually needs is "the market just moved for
this index" -- which the spot token alone tells us -- and then it calls
the EXACT SAME compute_vector(index_key) the cron already calls, which
writes to db.index_signal/db.index_signal_history itself. Nothing about
the signal logic changes; only how often it's asked to run.

Debounced (not one recompute per tick): each index's ~7-11 REST history
pulls per compute_vector() call is real work, and spot ticks arrive far
more often than the box/reversal state can meaningfully change.
"""
import asyncio
import logging

from definedge_service import INDEX_CONFIG, DefinedgeError

logger = logging.getLogger(__name__)

DEBOUNCE_SECONDS = 8


class IndexSignalBroadcaster:
    """Fans a freshly-recomputed index signal out to every browser WS
    connection watching that index (server.py's `/terminal/signal/stream`
    route). Notified from BOTH the tick-driven debounce loop below AND the
    existing 5-min cron path (server.py's `_run_auto_refresh`) -- a
    browser gets pushed an update no matter which trigger produced it."""

    def __init__(self):
        self._subscribers: dict[str, set] = {}

    def subscribe(self, index_key: str, handler) -> None:
        self._subscribers.setdefault(index_key, set()).add(handler)

    def unsubscribe(self, index_key: str, handler) -> None:
        subs = self._subscribers.get(index_key)
        if subs is not None:
            subs.discard(handler)

    async def notify(self, index_key: str) -> None:
        for handler in list(self._subscribers.get(index_key, ())):
            try:
                await handler(index_key)
            except Exception:  # noqa: BLE001 -- one dead browser socket must never break the others
                logger.exception("Index Vector broadcaster: handler failed for %s", index_key)


broadcaster = IndexSignalBroadcaster()


class IndexVectorStreamManager:
    def __init__(self, definedge, stream):
        self.definedge = definedge
        self.stream = stream
        self._dirty: set[str] = set()
        self._callbacks: dict[str, callable] = {}
        self._debounce_task: asyncio.Task | None = None
        self._started = False

    async def start(self) -> None:
        if self._started:
            return
        self._started = True
        for index_key, cfg in INDEX_CONFIG.items():
            cb = self._make_callback(index_key)
            self._callbacks[index_key] = cb
            await self.stream.subscribe(cfg["spot_segment"], cfg["spot_token"], cb)
        self._debounce_task = asyncio.create_task(self._debounce_loop())
        logger.info("Index Vector stream: subscribed to %d spot tokens.", len(INDEX_CONFIG))

    async def stop(self) -> None:
        self._started = False
        if self._debounce_task is not None:
            self._debounce_task.cancel()
        for index_key, cfg in INDEX_CONFIG.items():
            cb = self._callbacks.get(index_key)
            if cb is not None:
                await self.stream.unsubscribe(cfg["spot_segment"], cfg["spot_token"], cb)

    def _make_callback(self, index_key: str):
        def _cb(msg: dict) -> None:
            self._dirty.add(index_key)
        return _cb

    async def _debounce_loop(self) -> None:
        while True:
            await asyncio.sleep(DEBOUNCE_SECONDS)
            if not self._dirty:
                continue
            dirty, self._dirty = self._dirty, set()
            for index_key in dirty:
                try:
                    await self.definedge.compute_vector(index_key)
                    await broadcaster.notify(index_key)
                except DefinedgeError as e:
                    logger.warning("Index Vector stream: recompute failed for %s: %s", index_key, e)
                except Exception:  # noqa: BLE001 -- one bad recompute must never kill the loop
                    logger.exception("Index Vector stream: unexpected error recomputing %s", index_key)
