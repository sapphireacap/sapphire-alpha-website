"""API for the X-Percent Breadth indicator — public, no auth, same tier as
the other Alpha Terminal live modules. See breadth_engine.py for the
computation and breadth_groups.py for the NSE constituent lists.

500 symbols' worth of daily history is a multi-minute job (same shape as
quant_lab.py's Nifty 500 Sharpe dashboard) — never computed inline on a
request. A background refresh (cron-triggered, same X-Cron-Key convention
as every other scheduled job in this codebase) populates
breadth_x_percent_cache; reads are always served from there.
"""
import asyncio
import logging
from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request

import breadth_engine as be
from breadth_groups import GROUPS, BreadthGroupError, fetch_group_symbols
from definedge_service import IST, DefinedgeError, NIFTY_SPOT_TOKEN

logger = logging.getLogger(__name__)

CLOSES_CACHE_COLLECTION = "breadth_daily_closes"
SERIES_CACHE_COLLECTION = "breadth_x_percent_cache"
REFRESH_STATUS_COLLECTION = "breadth_refresh_status"
INDEX_CANDLES_COLLECTION = "breadth_index_candles"
YEARS_BACK = 15  # generous — this is each stock's OWN P&F state, not a ratio anchor concern (see breadth_engine.py)
MAX_CONCURRENT_FETCHES = 5  # courteous to Definedge, same bound quant_lab.py uses for its 500-symbol refresh


def create_breadth_router(db, definedge, get_current_admin, cron_secret: str) -> APIRouter:
    router = APIRouter(prefix="/terminal/breadth", tags=["breadth"])

    async def _closes_for(symbol: str, master) -> dict:
        """{date: close} for one symbol, cached in Mongo once today's own
        close is in it — same freshness rule as relative_strength_routes.py's
        _closes_for (Definedge's day-history only grows a TODAY row once
        that day's candle is finalised)."""
        today = datetime.now(IST).date().isoformat()
        doc = await db[CLOSES_CACHE_COLLECTION].find_one({"symbol": symbol})
        if doc and today in doc.get("closes", {}) and doc.get("years_back") == YEARS_BACK:
            return doc["closes"]

        found = definedge.resolve_symbol(master, "NSE", symbol)
        if not found:
            return {}
        try:
            bars = await definedge.daily_history("NSE", found["token"], years=YEARS_BACK)
        except DefinedgeError as e:
            logger.warning("Breadth daily history fetch failed for %s: %s", symbol, e)
            return {}
        closes = {b["date"]: b["close"] for b in bars}
        await db[CLOSES_CACHE_COLLECTION].update_one(
            {"symbol": symbol},
            {"$set": {"symbol": symbol, "last_fetched_date": today, "years_back": YEARS_BACK, "closes": closes}},
            upsert=True,
        )
        return closes

    async def _refresh_index_candles():
        """NIFTY 50 index daily OHLC — the reference price chart plotted
        above the breadth line (same NIFTY_SPOT_TOKEN Index Vector already
        uses for the live quote; daily_history() is the generic OHLC path,
        not options-specific). One shared series for both groups' pages,
        refreshed alongside whichever group triggers a refresh — cheap
        (a single API call), so no separate schedule needed for it."""
        try:
            bars = await definedge.daily_history("NSE", NIFTY_SPOT_TOKEN, years=YEARS_BACK)
        except DefinedgeError as e:
            logger.warning("Breadth index candle fetch failed: %s", e)
            return
        candles = [{"date": b["date"], "open": b["open"], "high": b["high"], "low": b["low"], "close": b["close"]} for b in bars]
        await db[INDEX_CANDLES_COLLECTION].update_one(
            {"id": "NIFTY"},
            {"$set": {"id": "NIFTY", "candles": candles, "computed_at": datetime.now(timezone.utc).isoformat()}},
            upsert=True,
        )

    async def _refresh_group(group_key: str):
        """Runs as a background task — fetches the group's constituent
        list, pulls (or reuses cached) daily closes for every member
        bounded to MAX_CONCURRENT_FETCHES concurrent Definedge calls, then
        computes the full X-Percent series and stores it. Progress is
        written as it goes so the admin panel isn't staring at a black
        box (same UX as quant_lab.py's Sharpe refresh)."""
        now_iso = lambda: datetime.now(timezone.utc).isoformat()  # noqa: E731
        status_id = group_key

        try:
            symbols = await fetch_group_symbols(group_key)
        except BreadthGroupError as e:
            await db[REFRESH_STATUS_COLLECTION].update_one(
                {"id": status_id},
                {"$set": {"id": status_id, "status": "done", "completed_at": now_iso(), "error": str(e)}},
                upsert=True,
            )
            return

        total = len(symbols)
        await db[REFRESH_STATUS_COLLECTION].update_one(
            {"id": status_id},
            {"$set": {
                "id": status_id, "status": "running", "started_at": now_iso(), "completed_at": None,
                "total": total, "done": 0, "resolved": 0, "failed": 0, "error": None,
            }},
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
        closes_by_symbol = {}

        async def worker(symbol):
            async with semaphore:
                closes = await _closes_for(symbol, master)
            async with counters_lock:
                counters["done"] += 1
                if closes:
                    counters["resolved"] += 1
                    closes_by_symbol[symbol] = closes
                else:
                    counters["failed"] += 1
                await db[REFRESH_STATUS_COLLECTION].update_one(
                    {"id": status_id},
                    {"$set": {"done": counters["done"], "resolved": counters["resolved"], "failed": counters["failed"]}},
                )

        await asyncio.gather(*(worker(s) for s in symbols), _refresh_index_candles())

        series = be.compute_breadth_series(closes_by_symbol) if closes_by_symbol else []
        today_ist = datetime.now(IST).strftime("%Y-%m-%d")
        await db[SERIES_CACHE_COLLECTION].update_one(
            {"group": group_key},
            {"$set": {
                "group": group_key,
                "series": series,
                "universe_total": total,
                "universe_resolved": counters["resolved"],
                "box_pct": be.DEFAULT_BOX_PCT,
                "reversal_boxes": be.DEFAULT_REVERSAL,
                "computed_date": today_ist,
                "computed_at": now_iso(),
            }},
            upsert=True,
        )
        await db[REFRESH_STATUS_COLLECTION].update_one(
            {"id": status_id}, {"$set": {"status": "done", "completed_at": now_iso()}}
        )

    @router.get("/groups")
    async def groups():
        return {"groups": [{"key": k, "label": v["label"]} for k, v in GROUPS.items()]}

    @router.get("/x-percent")
    async def x_percent(group: str):
        if group not in GROUPS:
            raise HTTPException(status_code=404, detail=f"Unknown group '{group}'. Must be one of {', '.join(GROUPS)}.")
        doc = await db[SERIES_CACHE_COLLECTION].find_one({"group": group}, {"_id": 0})
        if not doc or not doc.get("series"):
            raise HTTPException(
                status_code=404,
                detail=f"{GROUPS[group]['label']} breadth hasn't been computed yet — trigger a refresh.",
            )
        index_doc = await db[INDEX_CANDLES_COLLECTION].find_one({"id": "NIFTY"}, {"_id": 0})
        doc["index_candles"] = index_doc["candles"] if index_doc else []
        return doc

    @router.get("/refresh-status")
    async def refresh_status(group: str):
        if group not in GROUPS:
            raise HTTPException(status_code=404, detail=f"Unknown group '{group}'. Must be one of {', '.join(GROUPS)}.")
        doc = await db[REFRESH_STATUS_COLLECTION].find_one({"id": group}, {"_id": 0})
        return doc or {"status": "idle", "total": 0, "done": 0, "resolved": 0, "failed": 0}

    @router.post("/admin/refresh")
    async def refresh_cron(request: Request, background_tasks: BackgroundTasks, group: str = "nifty-50"):
        """External-cron entry point (same X-Cron-Key mechanism as every
        other scheduled job in this codebase)."""
        if not cron_secret or request.headers.get("X-Cron-Key") != cron_secret:
            raise HTTPException(status_code=401, detail="Invalid cron key")
        if group not in GROUPS:
            raise HTTPException(status_code=400, detail=f"Unknown group '{group}'. Must be one of {', '.join(GROUPS)}.")
        background_tasks.add_task(_refresh_group, group)
        return {"status": "started", "group": group}

    @router.post("/admin/refresh-now")
    async def refresh_admin(background_tasks: BackgroundTasks, group: str, admin: dict = Depends(get_current_admin)):
        if group not in GROUPS:
            raise HTTPException(status_code=400, detail=f"Unknown group '{group}'. Must be one of {', '.join(GROUPS)}.")
        background_tasks.add_task(_refresh_group, group)
        return {"status": "started", "group": group}

    return router
