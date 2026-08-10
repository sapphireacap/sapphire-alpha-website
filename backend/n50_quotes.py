"""
Nifty 50 live quotes -- LTP + previous close + %change for every N50
constituent, refreshed periodically and cached in Mongo. Backs both the
Market Assessment ticker tape (all 50, not the old hardcoded 5) and the
Top Gainers/Losers panel (same data, just sorted/sliced client-side).

Same bounded-concurrency, per-symbol-guarded refresh shape as
intraday_breadth.py, but each symbol only costs 2 lightweight Definedge
calls (equity_quote for LTP, exitline.previous_day_ohlc for the previous
close) instead of a full minute-bar history pull -- this only needs a
single current number per stock, not an intraday series.
"""
import asyncio
import logging
from datetime import datetime, timezone, timedelta

from breadth_groups import fetch_group_symbols, BreadthGroupError
from definedge_service import DefinedgeError
from exitline import previous_day_ohlc

logger = logging.getLogger(__name__)
IST = timezone(timedelta(hours=5, minutes=30))

MAX_CONCURRENT_FETCHES = 5
QUOTES_COLLECTION = "n50_quotes_cache"
REFRESH_STATUS_COLLECTION = "n50_quotes_refresh_status"
GROUP = "nifty-50"


async def _quote_one(definedge, master, symbol: str) -> dict | None:
    found = definedge.resolve_symbol(master, "NSE", symbol)
    if not found:
        return None
    try:
        prev, ltp = await asyncio.gather(
            previous_day_ohlc(definedge, "NSE", found["token"]),
            definedge.equity_quote("NSE", found["token"]),
            return_exceptions=True,
        )
    except Exception:  # noqa: BLE001
        return None
    if isinstance(prev, BaseException) or isinstance(ltp, BaseException):
        return None
    price = ltp if ltp else prev["close"]
    change_pct = ((ltp - prev["close"]) / prev["close"]) * 100 if ltp and prev["close"] else 0.0
    return {"symbol": symbol, "price": round(price, 2), "change_pct": round(change_pct, 2)}


async def refresh(db, definedge):
    """FastAPI BackgroundTask -- refreshes the whole N50 quote board in one
    pass, bounded concurrency same as every other per-symbol job in this
    codebase, one Mongo doc holding the whole board (small payload, no
    reason to shard per-symbol like Options Trend does)."""
    now_iso = lambda: datetime.now(timezone.utc).isoformat()  # noqa: E731

    try:
        symbols = await fetch_group_symbols(GROUP)
    except BreadthGroupError as e:
        await db[REFRESH_STATUS_COLLECTION].update_one(
            {"id": GROUP}, {"$set": {"id": GROUP, "status": "done", "completed_at": now_iso(), "error": str(e)}}, upsert=True,
        )
        return

    total = len(symbols)
    await db[REFRESH_STATUS_COLLECTION].update_one(
        {"id": GROUP},
        {"$set": {"id": GROUP, "status": "running", "started_at": now_iso(), "completed_at": None,
                   "total": total, "done": 0, "resolved": 0, "failed": 0}},
        upsert=True,
    )

    try:
        master = await definedge._get_all_master()
    except DefinedgeError as e:
        await db[REFRESH_STATUS_COLLECTION].update_one(
            {"id": GROUP}, {"$set": {"status": "done", "completed_at": now_iso(), "error": str(e)}}
        )
        return

    semaphore = asyncio.Semaphore(MAX_CONCURRENT_FETCHES)
    counters = {"done": 0, "resolved": 0, "failed": 0}
    counters_lock = asyncio.Lock()
    rows = []

    async def worker(symbol):
        async with semaphore:
            row = await _quote_one(definedge, master, symbol)
        async with counters_lock:
            counters["done"] += 1
            if row is not None:
                counters["resolved"] += 1
                rows.append(row)
            else:
                counters["failed"] += 1
            await db[REFRESH_STATUS_COLLECTION].update_one(
                {"id": GROUP},
                {"$set": {"done": counters["done"], "resolved": counters["resolved"], "failed": counters["failed"]}},
            )

    await asyncio.gather(*(worker(s) for s in symbols))

    if rows:
        await db[QUOTES_COLLECTION].update_one(
            {"id": "current"},
            {"$set": {"id": "current", "rows": rows, "universe_total": total,
                      "universe_resolved": counters["resolved"], "computed_at": now_iso()}},
            upsert=True,
        )
    await db[REFRESH_STATUS_COLLECTION].update_one(
        {"id": GROUP}, {"$set": {"status": "done", "completed_at": now_iso()}}
    )
