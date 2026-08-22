"""
Swing Reversal scanner — universe-wide scan for the swing_reversal_patterns.py
detectors, mounted under /api by server.py via create_swing_reversal_router
(db, definedge, get_current_admin, cron_secret), same factory pattern as the
other /terminal-adjacent routers.

Cache/refresh shape mirrors quant_lab.py's Sharpe/Momentum dashboards (a
BackgroundTask populates a per-symbol-per-day cache; the public route just
reads it) — but this module is intentionally self-contained and does NOT
import from quant_lab.py, since quant_lab's heavy pandas-based module is
gated behind DISABLED_FEATURES=quant_lab to save Render free-tier memory,
and this scanner is its own always-on product module, not a Quant Lab
experiment. The small Nifty 500 constituent-list fetch is duplicated here
rather than shared, to keep that gate meaningful.
"""
import asyncio
import csv
import io
import logging
from datetime import datetime, timezone, timedelta

import httpx
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request

from definedge_service import DefinedgeError
from pnf_chart import resample_daily
from swing_reversal_patterns import scan_latest

logger = logging.getLogger(__name__)
IST = timezone(timedelta(hours=5, minutes=30))

NIFTY500_CSV_URL = "https://nsearchives.nseindia.com/content/indices/ind_nifty500list.csv"
BROWSER_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)
_nifty500_cache = None  # (date_str, list[dict]) — same per-day TTL pattern used elsewhere


async def _fetch_nifty500_list() -> list:
    global _nifty500_cache
    today = datetime.now(IST).strftime("%Y-%m-%d")
    if _nifty500_cache and _nifty500_cache[0] == today:
        return _nifty500_cache[1]
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.get(NIFTY500_CSV_URL, headers={"User-Agent": BROWSER_USER_AGENT})
    if r.status_code != 200:
        raise DefinedgeError(f"Nifty 500 list fetch failed (HTTP {r.status_code}).")
    rows = []
    for row in csv.DictReader(io.StringIO(r.text)):
        symbol = (row.get("Symbol") or "").strip()
        if not symbol:
            continue
        rows.append({"symbol": symbol, "company_name": (row.get("Company Name") or "").strip()})
    _nifty500_cache = (today, rows)
    return rows


async def _get_or_compute_signals(db, definedge, master_df, symbol: str) -> list:
    """Cache-or-compute for one symbol — returns [] (never raises) when the
    symbol can't be resolved, lacks enough history, or has no active
    pattern today, so a universe scan can report per-item rather than
    failing the whole batch."""
    today_ist = datetime.now(IST).strftime("%Y-%m-%d")
    cached = await db.swing_reversal_cache.find_one({"symbol": symbol}, {"_id": 0})
    if cached and cached.get("computed_date") == today_ist:
        return cached.get("signals", [])

    resolved = definedge.resolve_symbol(master_df, "NSE", symbol)
    if resolved is None:
        return []
    try:
        daily_bars = await definedge.daily_history("NSE", resolved["token"], years=2)
    except DefinedgeError:
        return []
    if not daily_bars:
        return []

    weekly_bars = resample_daily(daily_bars, "weekly")
    signals = scan_latest(daily_bars, weekly_bars)
    signal_dicts = [
        {"key": s.key, "label": s.label, "bias": s.bias, "date": s.date,
         "trigger_price": round(s.trigger_price, 2), "stop_loss": round(s.stop_loss, 2)}
        for s in signals
    ]

    await db.swing_reversal_cache.update_one(
        {"symbol": symbol},
        {"$set": {
            "symbol": symbol, "resolved_symbol": resolved.get("tradingsymbol", symbol),
            "signals": signal_dicts, "computed_date": today_ist,
            "computed_at": datetime.now(timezone.utc).isoformat(),
        }},
        upsert=True,
    )
    return signal_dicts


async def _refresh_universe_cache(db, definedge):
    """Runs as a FastAPI BackgroundTask — same shape as quant_lab.py's
    _refresh_nifty500_cache, scoring pattern signals instead of Sharpe/momentum."""
    now_iso = lambda: datetime.now(timezone.utc).isoformat()  # noqa: E731
    try:
        universe = await _fetch_nifty500_list()
    except Exception as e:  # noqa: BLE001
        logger.exception("Nifty 500 list fetch failed during swing-reversal refresh")
        await db.swing_reversal_refresh_status.update_one(
            {"id": "current"},
            {"$set": {"id": "current", "status": "done", "completed_at": now_iso(), "error": str(e)}},
            upsert=True,
        )
        return

    total = len(universe)
    await db.swing_reversal_refresh_status.update_one(
        {"id": "current"},
        {"$set": {
            "id": "current", "status": "running", "started_at": now_iso(), "completed_at": None,
            "total": total, "done": 0, "with_signal": 0, "failed": 0, "error": None,
        }},
        upsert=True,
    )

    try:
        master = await definedge._get_all_master()
    except Exception as e:  # noqa: BLE001
        logger.exception("Master file fetch failed during swing-reversal refresh")
        await db.swing_reversal_refresh_status.update_one(
            {"id": "current"}, {"$set": {"status": "done", "completed_at": now_iso(), "error": str(e)}}
        )
        return

    semaphore = asyncio.Semaphore(5)
    counters = {"done": 0, "with_signal": 0, "failed": 0}
    counters_lock = asyncio.Lock()

    async def worker(row):
        symbol = row["symbol"]
        async with semaphore:
            try:
                signals = await _get_or_compute_signals(db, definedge, master, symbol)
            except Exception:  # noqa: BLE001
                logger.exception("Swing-reversal refresh failed for %s", symbol)
                signals = None
        async with counters_lock:
            counters["done"] += 1
            if signals is None:
                counters["failed"] += 1
            elif signals:
                counters["with_signal"] += 1
            await db.swing_reversal_refresh_status.update_one(
                {"id": "current"},
                {"$set": {"done": counters["done"], "with_signal": counters["with_signal"],
                          "failed": counters["failed"]}},
            )

    await asyncio.gather(*(worker(row) for row in universe))

    await db.swing_reversal_refresh_status.update_one(
        {"id": "current"}, {"$set": {"status": "done", "completed_at": now_iso()}}
    )


def create_swing_reversal_router(db, definedge, get_current_admin, cron_secret: str) -> APIRouter:
    router = APIRouter(prefix="/swing-reversal")

    @router.get("/scan")
    async def scan():
        """Public — today's active pattern signals across the Nifty 500,
        strictly off the pre-computed cache (a 500-symbol scan is a
        multi-minute job, not something a page load can compute inline)."""
        today_ist = datetime.now(IST).strftime("%Y-%m-%d")
        docs = await db.swing_reversal_cache.find({}, {"_id": 0}).to_list(600)
        fresh = [d for d in docs if d.get("computed_date") == today_ist]
        results = []
        for d in fresh:
            for sig in d.get("signals", []):
                results.append({
                    "symbol": d["symbol"], "resolved_symbol": d.get("resolved_symbol", d["symbol"]),
                    **sig,
                })
        return {
            "found": len(fresh) > 0,
            "results": results,
            "universe_coverage": {"cached": len(fresh), "total": len(docs)},
        }

    @router.get("/refresh-status")
    async def refresh_status():
        doc = await db.swing_reversal_refresh_status.find_one({"id": "current"}, {"_id": 0})
        return doc or {"status": "idle", "total": 0, "done": 0, "with_signal": 0, "failed": 0}

    @router.post("/admin/refresh")
    async def refresh_cron(request: Request, background_tasks: BackgroundTasks):
        """External-cron entry point, same X-Cron-Key mechanism used by the
        other daily refresh endpoints."""
        if not cron_secret or request.headers.get("X-Cron-Key") != cron_secret:
            raise HTTPException(status_code=401, detail="Invalid cron key")
        background_tasks.add_task(_refresh_universe_cache, db, definedge)
        return {"status": "started"}

    @router.post("/admin/refresh-now")
    async def refresh_admin(background_tasks: BackgroundTasks, admin: dict = Depends(get_current_admin)):
        """Same refresh, admin-JWT-gated for the admin panel's manual button."""
        background_tasks.add_task(_refresh_universe_cache, db, definedge)
        return {"status": "started"}

    return router
