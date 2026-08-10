"""
Open Interest Build-Up -- classic long/short buildup/unwinding
classification for every NSE F&O stock, combining two independent public
sources:

  - NSE's own "OI Spurts in Underlying" endpoint (api/live-analysis-oi-
    spurts-underlyings) for latestOI/prevOI per symbol -- unofficial but
    unauthenticated (no Definedge session needed), verified live,
    2026-08-10.
  - Definedge equity LTP + previous close (same two calls n50_quotes.py
    already uses) for each symbol's price %change, since NSE's OI-spurts
    payload only carries the current underlying value, not yesterday's
    close.

Standard, publicly-documented quadrant classification (not proprietary to
any vendor):
  price up   + OI up   -> Long Buildup    (new longs opening)
  price down + OI up   -> Short Buildup   (new shorts opening)
  price down + OI down -> Long Unwinding  (longs closing out)
  price up   + OI down -> Short Covering  (shorts closing out)

Universe is options_trend_groups' own F&O stock list (~207 symbols) --
same eligibility gate the Options Trend Scanner already uses, no reason
to define a second one.
"""
import asyncio
import logging
from datetime import datetime, timezone, timedelta

import httpx

from options_trend_groups import fetch_fo_stock_universe, OptionsTrendGroupError
from definedge_service import DefinedgeError
from exitline import previous_day_ohlc

logger = logging.getLogger(__name__)
IST = timezone(timedelta(hours=5, minutes=30))

MAX_CONCURRENT_FETCHES = 5
BOARD_COLLECTION = "oi_buildup_board"
REFRESH_STATUS_COLLECTION = "oi_buildup_refresh_status"

QUADRANTS = ("long_buildup", "short_buildup", "long_unwinding", "short_covering")

NSE_HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"),
    "Accept": "application/json",
    "Referer": "https://www.nseindia.com/",
}


class OiBuildupError(Exception):
    pass


async def _fetch_oi_spurts() -> dict:
    """{symbol: {latestOI, prevOI, changeInOI}} for every underlying NSE
    currently reports an OI spurt for -- verified live, 2026-08-10: 200
    OK, ~213 rows, no cookie handshake needed (same discipline as
    market_dashboard_client.py's allIndices/fiidii/52-week-hilo calls)."""
    try:
        async with httpx.AsyncClient(timeout=20) as c:
            r = await c.get("https://www.nseindia.com/api/live-analysis-oi-spurts-underlyings", headers=NSE_HEADERS)
    except httpx.HTTPError as e:
        raise OiBuildupError(f"NSE OI spurts request failed: {e}") from e
    if r.status_code != 200:
        raise OiBuildupError(f"NSE OI spurts failed (HTTP {r.status_code}).")
    try:
        rows = r.json().get("data") or []
    except ValueError as e:
        raise OiBuildupError(f"NSE OI spurts returned non-JSON: {e}") from e
    return {row["symbol"]: row for row in rows if row.get("symbol")}


def _classify(price_change_pct: float, oi_change_pct: float) -> str | None:
    if price_change_pct == 0 or oi_change_pct == 0:
        return None
    if price_change_pct > 0 and oi_change_pct > 0:
        return "long_buildup"
    if price_change_pct < 0 and oi_change_pct > 0:
        return "short_buildup"
    if price_change_pct < 0 and oi_change_pct < 0:
        return "long_unwinding"
    return "short_covering"


async def _price_change_one(definedge, master, symbol: str) -> float | None:
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
    if not ltp or not prev["close"]:
        return None
    return ((ltp - prev["close"]) / prev["close"]) * 100


async def refresh(db, definedge):
    """FastAPI BackgroundTask -- fetches the OI-spurts board once (no
    Definedge dependency), then resolves price %change per symbol with
    bounded concurrency (same shape as n50_quotes.py), classifies each,
    and writes the whole board in one Mongo doc."""
    now_iso = lambda: datetime.now(timezone.utc).isoformat()  # noqa: E731
    status_id = "current"

    try:
        symbols = await fetch_fo_stock_universe()
    except OptionsTrendGroupError as e:
        await db[REFRESH_STATUS_COLLECTION].update_one(
            {"id": status_id}, {"$set": {"id": status_id, "status": "done", "completed_at": now_iso(), "error": str(e)}}, upsert=True,
        )
        return

    try:
        oi_spurts = await _fetch_oi_spurts()
    except OiBuildupError as e:
        await db[REFRESH_STATUS_COLLECTION].update_one(
            {"id": status_id}, {"$set": {"id": status_id, "status": "done", "completed_at": now_iso(), "error": str(e)}}, upsert=True,
        )
        return

    total = len(symbols)
    await db[REFRESH_STATUS_COLLECTION].update_one(
        {"id": status_id},
        {"$set": {"id": status_id, "status": "running", "started_at": now_iso(), "completed_at": None,
                   "total": total, "done": 0, "resolved": 0, "failed": 0}},
        upsert=True,
    )

    try:
        master = await definedge._get_all_master()
    except DefinedgeError as e:
        await db[REFRESH_STATUS_COLLECTION].update_one(
            {"id": status_id}, {"$set": {"status": "done", "completed_at": now_iso(), "error": str(e)}}
        )
        return

    semaphore = asyncio.Semaphore(MAX_CONCURRENT_FETCHES)
    counters = {"done": 0, "resolved": 0, "failed": 0}
    counters_lock = asyncio.Lock()
    rows = []

    async def worker(symbol):
        spurt = oi_spurts.get(symbol)
        if not spurt or not spurt.get("prevOI"):
            async with counters_lock:
                counters["done"] += 1
                counters["failed"] += 1
            return
        oi_change_pct = (spurt["changeInOI"] / spurt["prevOI"]) * 100

        async with semaphore:
            price_change_pct = await _price_change_one(definedge, master, symbol)

        async with counters_lock:
            counters["done"] += 1
            if price_change_pct is not None:
                counters["resolved"] += 1
                quadrant = _classify(price_change_pct, oi_change_pct)
                if quadrant:
                    rows.append({
                        "symbol": symbol,
                        "price_change_pct": round(price_change_pct, 2),
                        "oi_change_pct": round(oi_change_pct, 2),
                        "quadrant": quadrant,
                    })
            else:
                counters["failed"] += 1
            await db[REFRESH_STATUS_COLLECTION].update_one(
                {"id": status_id},
                {"$set": {"done": counters["done"], "resolved": counters["resolved"], "failed": counters["failed"]}},
            )

    await asyncio.gather(*(worker(s) for s in symbols))

    if rows:
        await db[BOARD_COLLECTION].update_one(
            {"id": "current"},
            {"$set": {"id": "current", "rows": rows, "universe_total": total,
                      "universe_resolved": counters["resolved"], "computed_at": now_iso()}},
            upsert=True,
        )
    await db[REFRESH_STATUS_COLLECTION].update_one(
        {"id": status_id}, {"$set": {"status": "done", "completed_at": now_iso()}}
    )
