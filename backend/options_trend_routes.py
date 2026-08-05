"""API for the Options Trend Scanner — public, no auth, same tier as the
other Alpha Terminal live modules. See options_trend_engine.py for the
three-pillar computation, options_trend_data.py for stock-level FUT/ATM
CE/PE token resolution, and options_trend_groups.py for the F&O universe.

~208 stocks x 3 legs (future, ATM call, ATM put) x minute-bar history is a
much bigger job than Breadth's daily-close refresh (breadth_routes.py) —
expect it to run considerably longer. Learned live from that refresh
(2026-08-05): a batch job that only writes its result ONCE AT THE END loses
ALL progress if a deploy restarts the process mid-run (Render redeploys on
every push, killing in-flight background tasks). This module writes each
STOCK'S result to Mongo as soon as it's computed instead, so an interrupted
refresh keeps whatever it already finished rather than losing the whole run.
"""
import asyncio
import logging
from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request

import options_trend_engine as oe
from options_trend_data import resolve_stock_futures_token, resolve_stock_atm_tokens
from options_trend_groups import fetch_fo_stock_universe, OptionsTrendGroupError
from definedge_service import IST, DefinedgeError

logger = logging.getLogger(__name__)

SCAN_COLLECTION = "options_trend_scan"
REFRESH_STATUS_COLLECTION = "options_trend_refresh_status"
MINUTE_HISTORY_DAYS = 180  # ~6 months — Definedge's own real minute-bar ceiling (see options_trend_engine.py docstring)
MAX_CONCURRENT_FETCHES = 3  # each stock costs ~5 Definedge calls (spot, futures resolve, 3x minute history) —
                            # more conservative than Breadth's 5 given the far heavier per-symbol payload


def create_options_trend_router(db, definedge, get_current_admin, cron_secret: str) -> APIRouter:
    router = APIRouter(prefix="/terminal/options-trend", tags=["options-trend"])

    async def _minute_closes(segment: str, token: str) -> list:
        now = datetime.now(IST)
        frm = (now - timedelta(days=MINUTE_HISTORY_DAYS)).strftime("%d%m%Y0000")
        to = now.strftime("%d%m%Y%H%M")
        try:
            bars = await definedge.minute_ohlc(segment, token, frm=frm, to=to)
        except DefinedgeError as e:
            logger.warning("Options Trend minute history fetch failed for token %s: %s", token, e)
            return []
        return [b["close"] for b in bars]

    async def _scan_one(symbol: str, master) -> dict | None:
        """Full resolve-and-compute for one stock — None if any required
        leg (equity spot, futures, or a matched ATM CE+PE pair) doesn't
        resolve at all (illiquid name, no listed options this cycle,
        etc.), never a partial/fabricated verdict."""
        today = datetime.now(IST).date()

        eq = definedge.resolve_symbol(master, "NSE", symbol)
        if eq is None:
            return None
        try:
            spot = await definedge.equity_quote("NSE", eq["token"])
        except DefinedgeError:
            return None
        if not spot or spot <= 0:
            return None

        fut = resolve_stock_futures_token(master, symbol, today)
        atm = resolve_stock_atm_tokens(master, symbol, spot, today)
        if fut is None or atm is None:
            return None

        future_closes, call_closes, put_closes = await asyncio.gather(
            _minute_closes("NFO", fut["token"]),
            _minute_closes("NFO", atm["CE"]),
            _minute_closes("NFO", atm["PE"]),
        )
        result = oe.compute_verdict(future_closes, call_closes, put_closes)

        return {
            "symbol": symbol,
            "spot": spot,
            "future_expiry": fut["expiry"].isoformat(),
            "atm_strike": atm["strike"],
            "atm_expiry": atm["expiry"].isoformat(),
            **result,
        }

    async def _refresh_universe():
        """Runs as a background task — one Mongo upsert PER STOCK as soon
        as its verdict is computed (see module docstring for why that's
        load-bearing here, not just tidiness)."""
        now_iso = lambda: datetime.now(timezone.utc).isoformat()  # noqa: E731
        status_id = "current"

        try:
            symbols = await fetch_fo_stock_universe()
        except OptionsTrendGroupError as e:
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
        today_ist = datetime.now(IST).strftime("%Y-%m-%d")

        async def worker(symbol):
            async with semaphore:
                try:
                    result = await _scan_one(symbol, master)
                except Exception:  # noqa: BLE001
                    logger.exception("Options Trend scan failed for %s", symbol)
                    result = None
            if result is not None:
                await db[SCAN_COLLECTION].update_one(
                    {"symbol": symbol},
                    {"$set": {**result, "computed_date": today_ist, "computed_at": now_iso()}},
                    upsert=True,
                )
            async with counters_lock:
                counters["done"] += 1
                counters["resolved" if result is not None else "failed"] += 1
                await db[REFRESH_STATUS_COLLECTION].update_one(
                    {"id": status_id},
                    {"$set": {"done": counters["done"], "resolved": counters["resolved"], "failed": counters["failed"]}},
                )

        await asyncio.gather(*(worker(s) for s in symbols))

        await db[REFRESH_STATUS_COLLECTION].update_one(
            {"id": status_id}, {"$set": {"status": "done", "completed_at": now_iso()}}
        )

    @router.get("/scan")
    async def scan():
        today_ist = datetime.now(IST).strftime("%Y-%m-%d")
        docs = await db[SCAN_COLLECTION].find({}, {"_id": 0}).to_list(length=600)
        if not docs:
            raise HTTPException(status_code=404, detail="Options Trend Scanner hasn't been computed yet — trigger a refresh.")
        fresh = [d for d in docs if d.get("computed_date") == today_ist]
        return {
            "results": docs,
            "as_of": today_ist,
            "universe_total": len(docs),
            "fresh_today": len(fresh),
        }

    @router.get("/refresh-status")
    async def refresh_status():
        doc = await db[REFRESH_STATUS_COLLECTION].find_one({"id": "current"}, {"_id": 0})
        return doc or {"status": "idle", "total": 0, "done": 0, "resolved": 0, "failed": 0}

    @router.post("/admin/refresh")
    async def refresh_cron(request: Request, background_tasks: BackgroundTasks):
        """External-cron entry point (same X-Cron-Key mechanism as every
        other scheduled job in this codebase)."""
        if not cron_secret or request.headers.get("X-Cron-Key") != cron_secret:
            raise HTTPException(status_code=401, detail="Invalid cron key")
        background_tasks.add_task(_refresh_universe)
        return {"status": "started"}

    @router.post("/admin/refresh-now")
    async def refresh_admin(background_tasks: BackgroundTasks, admin: dict = Depends(get_current_admin)):
        background_tasks.add_task(_refresh_universe)
        return {"status": "started"}

    return router
