"""
Intraday X% Breadth -- same X-Percent method as breadth_engine.py (Prashant
Shah, "Trading The Markets The Point & Figure Way", Ch. 10), applied to
TODAY's 1-minute bars instead of daily closes, at a much tighter 0.15% box
(vs the daily reading's 1%) so the column state can actually move within a
single session.

Reuses breadth_engine.py's direction_by_date() and
compute_breadth_series_from_directions() completely unchanged -- both are
already generic over any {key: close} mapping (the "date" in the name is
just what the daily job happens to key by), so feeding them
{minute_ts: close} at box_pct=0.15 instead of {date: close} at 1% is the
entire adaptation. No new P&F logic here, only new orchestration: fetch
today's minute bars, key by minute, cache per (group, trading_date) so a
fresh day starts a fresh series rather than trailing yesterday's.

Nifty 500 (500 stocks) is NOT wired up yet -- scoped down to Nifty 50
only for now given this project's history of Render free-tier memory
crashes on other heavy, frequent jobs; the group is validated but only
"nifty-50" actually has a working refresh path (see intraday_breadth_routes.py).
"""
import asyncio
import logging
from datetime import datetime, timezone, timedelta

import breadth_engine as be
from breadth_groups import fetch_group_symbols, BreadthGroupError
from definedge_service import DefinedgeError

logger = logging.getLogger(__name__)
IST = timezone(timedelta(hours=5, minutes=30))

BOX_PCT = 0.15
REVERSAL = 3
MAX_CONCURRENT_FETCHES = 5
SERIES_CACHE_COLLECTION = "intraday_breadth_x_percent_cache"
REFRESH_STATUS_COLLECTION = "intraday_breadth_refresh_status"

SUPPORTED_GROUPS = ("nifty-50",)  # nifty-500 intentionally not enabled yet


async def _minute_closes_for(definedge, master, symbol: str) -> dict:
    """{minute_ts: close} for one symbol's session-so-far, today only --
    no cross-day caching (unlike the daily job's closes cache), since
    this needs to be genuinely live through the session."""
    found = definedge.resolve_symbol(master, "NSE", symbol)
    if not found:
        return {}
    try:
        bars = await definedge.minute_ohlc("NSE", found["token"])
    except DefinedgeError as e:
        logger.warning("Intraday breadth: minute bars fetch failed for %s: %s", symbol, e)
        return {}
    return {b["ts"]: b["close"] for b in bars if b.get("close") is not None}


async def refresh(db, definedge, group: str):
    """FastAPI BackgroundTask -- same per-symbol-guarded, bounded-
    concurrency shape as breadth_routes.py's _refresh_group, just against
    today's minute bars instead of full daily history, and re-run every
    few minutes through the session (see the cron) rather than once a
    day. Each run recomputes the WHOLE day-so-far series (direction_by_date
    processes every minute key in the fetched series, not just the
    latest), so the chart stays full-resolution even though the refresh
    itself is periodic, not per-tick."""
    if group not in SUPPORTED_GROUPS:
        return
    now_iso = lambda: datetime.now(timezone.utc).isoformat()  # noqa: E731
    trading_date = datetime.now(IST).strftime("%Y-%m-%d")

    try:
        symbols = await fetch_group_symbols(group)
    except BreadthGroupError as e:
        await db[REFRESH_STATUS_COLLECTION].update_one(
            {"id": group}, {"$set": {"id": group, "status": "done", "completed_at": now_iso(), "error": str(e)}}, upsert=True,
        )
        return

    total = len(symbols)
    await db[REFRESH_STATUS_COLLECTION].update_one(
        {"id": group},
        {"$set": {"id": group, "status": "running", "started_at": now_iso(), "completed_at": None,
                   "total": total, "done": 0, "resolved": 0, "failed": 0}},
        upsert=True,
    )

    try:
        master = await definedge._get_all_master()
    except DefinedgeError as e:
        await db[REFRESH_STATUS_COLLECTION].update_one(
            {"id": group}, {"$set": {"status": "done", "completed_at": now_iso(), "error": str(e)}}
        )
        return

    semaphore = asyncio.Semaphore(MAX_CONCURRENT_FETCHES)
    counters = {"done": 0, "resolved": 0, "failed": 0}
    counters_lock = asyncio.Lock()
    directions_by_symbol = {}

    async def worker(symbol):
        try:
            async with semaphore:
                closes = await _minute_closes_for(definedge, master, symbol)
            directions = be.direction_by_date(closes, box_pct=BOX_PCT, reversal_boxes=REVERSAL) if closes else None
            async with counters_lock:
                counters["done"] += 1
                if closes:
                    counters["resolved"] += 1
                    directions_by_symbol[symbol] = directions
                else:
                    counters["failed"] += 1
                await db[REFRESH_STATUS_COLLECTION].update_one(
                    {"id": group},
                    {"$set": {"done": counters["done"], "resolved": counters["resolved"], "failed": counters["failed"]}},
                )
        except Exception:  # noqa: BLE001
            logger.exception("Intraday breadth refresh failed for %s", symbol)

    await asyncio.gather(*(worker(s) for s in symbols))

    series = be.compute_breadth_series_from_directions(directions_by_symbol, total=total) if directions_by_symbol else []
    await db[SERIES_CACHE_COLLECTION].update_one(
        {"group": group, "trading_date": trading_date},
        {"$set": {
            "group": group, "trading_date": trading_date, "series": series,
            "universe_total": total, "universe_resolved": counters["resolved"],
            "box_pct": BOX_PCT, "reversal_boxes": REVERSAL, "computed_at": now_iso(),
        }},
        upsert=True,
    )
    await db[REFRESH_STATUS_COLLECTION].update_one(
        {"id": group}, {"$set": {"status": "done", "completed_at": now_iso()}}
    )
