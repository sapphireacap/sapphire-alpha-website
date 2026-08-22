"""
Intraday Momentum Scanner routes — mounted under /api by server.py via
create_intraday_momentum_router(db, definedge, get_current_admin, cron_secret).

Architecture: cache each symbol's raw intraday closes + volume (refreshed
frequently via admin/cron — short TTL, not once-daily, since this scanner
is meant to track the live session, not yesterday's numbers), then compute
every derived metric (Return%, VOLAR, Retracement%, EMA pass/fail) LIVE
per request from that cached series. This is what lets every filter
(period, EMA choice, volume/retracement thresholds, relative-vs-absolute)
be changed and re-scanned instantly without re-fetching bars — the same
"raw data cached, math computed live" split already used by
options_analytics_routes.py.
"""
import asyncio
import csv
import io
import logging
from datetime import datetime, timezone, timedelta

import httpx
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from typing import List, Optional

from definedge_service import DefinedgeError
from pnf_chart import aggregate_minutes
from intraday_momentum import scan_symbol

logger = logging.getLogger(__name__)
IST = timezone(timedelta(hours=5, minutes=30))

NIFTY500_CSV_URL = "https://nsearchives.nseindia.com/content/indices/ind_nifty500list.csv"
BROWSER_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)
_nifty500_cache = None  # (date_str, list[dict])

BAR_MINUTES = 5
CACHE_STALE_SECONDS = 600  # 10 minutes — refresh cadence during the trading session
MAX_PERIOD_BARS = 150  # ~1 trading day of 5-minute bars (375/5 = 75) plus headroom for a prior day


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


async def _get_or_refresh_series(db, definedge, master_df, symbol: str) -> Optional[dict]:
    """Cache-or-fetch for one symbol's raw 5-minute closes + volume.
    Returns None (never raises) on any failure so a universe refresh can
    report per-item rather than failing the whole batch."""
    now = datetime.now(IST)
    cached = await db.intraday_momentum_cache.find_one({"symbol": symbol}, {"_id": 0})
    if cached and (now - datetime.fromisoformat(cached["fetched_at"])).total_seconds() < CACHE_STALE_SECONDS:
        return cached

    resolved = definedge.resolve_symbol(master_df, "NSE", symbol)
    if resolved is None:
        return None
    try:
        minute_bars = await definedge.minute_ohlc("NSE", resolved["token"])
    except DefinedgeError:
        return None
    if not minute_bars:
        return None

    bars_5m = aggregate_minutes(minute_bars, BAR_MINUTES)[-MAX_PERIOD_BARS:]
    closes = [b["close"] for b in bars_5m]
    total_volume = sum(b.get("volume") or 0 for b in bars_5m)

    doc = {
        "symbol": symbol, "resolved_symbol": resolved.get("tradingsymbol", symbol),
        "closes": closes, "total_volume": total_volume,
        "fetched_at": now.isoformat(),
    }
    await db.intraday_momentum_cache.update_one({"symbol": symbol}, {"$set": doc}, upsert=True)
    return doc


async def _refresh_universe(db, definedge):
    """Runs as a FastAPI BackgroundTask — refreshes every Nifty 500
    constituent's raw closes/volume, same bounded-concurrency shape as
    the other universe-wide refreshers in this codebase."""
    now_iso = lambda: datetime.now(timezone.utc).isoformat()  # noqa: E731
    try:
        universe = await _fetch_nifty500_list()
    except Exception as e:  # noqa: BLE001
        logger.exception("Nifty 500 list fetch failed during intraday-momentum refresh")
        await db.intraday_momentum_refresh_status.update_one(
            {"id": "current"},
            {"$set": {"id": "current", "status": "done", "completed_at": now_iso(), "error": str(e)}},
            upsert=True,
        )
        return

    total = len(universe)
    await db.intraday_momentum_refresh_status.update_one(
        {"id": "current"},
        {"$set": {"id": "current", "status": "running", "started_at": now_iso(), "completed_at": None,
                  "total": total, "done": 0, "failed": 0, "error": None}},
        upsert=True,
    )

    try:
        master = await definedge._get_all_master()
    except Exception as e:  # noqa: BLE001
        logger.exception("Master file fetch failed during intraday-momentum refresh")
        await db.intraday_momentum_refresh_status.update_one(
            {"id": "current"}, {"$set": {"status": "done", "completed_at": now_iso(), "error": str(e)}}
        )
        return

    semaphore = asyncio.Semaphore(5)
    counters = {"done": 0, "failed": 0}
    counters_lock = asyncio.Lock()

    async def worker(row):
        symbol = row["symbol"]
        async with semaphore:
            try:
                doc = await _get_or_refresh_series(db, definedge, master, symbol)
            except Exception:  # noqa: BLE001
                logger.exception("Intraday-momentum refresh failed for %s", symbol)
                doc = None
        async with counters_lock:
            counters["done"] += 1
            if doc is None:
                counters["failed"] += 1
            await db.intraday_momentum_refresh_status.update_one(
                {"id": "current"}, {"$set": {"done": counters["done"], "failed": counters["failed"]}}
            )

    await asyncio.gather(*(worker(row) for row in universe))
    await db.intraday_momentum_refresh_status.update_one(
        {"id": "current"}, {"$set": {"status": "done", "completed_at": now_iso()}}
    )


class ScanRequest(BaseModel):
    period: int = Field(default=20, ge=2, le=MAX_PERIOD_BARS - 1)
    ema_periods: List[int] = Field(default_factory=list)
    min_volume: Optional[int] = None
    max_retracement_pct: Optional[float] = None
    relative: bool = False
    denominator: Optional[str] = None  # required when relative=True
    top_n: int = Field(default=25, ge=1, le=100)


def create_intraday_momentum_router(db, definedge, get_current_admin, cron_secret: str):
    router = APIRouter(prefix="/intraday-momentum")

    @router.get("/universe")
    async def universe():
        try:
            return await _fetch_nifty500_list()
        except DefinedgeError as e:
            raise HTTPException(status_code=502, detail=str(e))

    @router.post("/scan")
    async def scan(payload: ScanRequest):
        if payload.relative and not payload.denominator:
            return {"found": False, "reason": "Select a denominator symbol for relative momentum mode."}

        docs = await db.intraday_momentum_cache.find({}, {"_id": 0}).to_list(600)
        if not docs:
            return {"found": False, "reason": "No intraday data cached yet — trigger a refresh from the admin panel, or wait for the next scheduled one."}

        denom_closes = None
        if payload.relative:
            denom_doc = next((d for d in docs if d["symbol"] == payload.denominator.strip().upper()), None)
            if denom_doc is None:
                return {"found": False, "reason": f"Denominator '{payload.denominator}' isn't cached right now."}
            denom_closes = denom_doc["closes"]

        results = []
        for d in docs:
            metrics = scan_symbol(d["closes"], payload.period, payload.ema_periods, denom_closes)
            if metrics is None:
                continue
            if not metrics["ema_pass"]:
                continue
            if payload.min_volume is not None and d.get("total_volume", 0) < payload.min_volume:
                continue
            if payload.max_retracement_pct is not None and metrics["retracement_pct"] > payload.max_retracement_pct:
                continue
            results.append({
                "symbol": d["symbol"], "resolved_symbol": d.get("resolved_symbol", d["symbol"]),
                "total_volume": d.get("total_volume", 0),
                **metrics,
            })

        results.sort(key=lambda r: r["volar_score"] if r["volar_score"] is not None else -1e9, reverse=True)
        top = results[: payload.top_n]

        fresh_count = sum(
            1 for d in docs
            if (datetime.now(IST) - datetime.fromisoformat(d["fetched_at"])).total_seconds() < CACHE_STALE_SECONDS
        )
        return {
            "found": True,
            "results": top,
            "qualified": len(results),
            "universe_coverage": {"cached": len(docs), "fresh": fresh_count},
        }

    @router.get("/refresh-status")
    async def refresh_status():
        doc = await db.intraday_momentum_refresh_status.find_one({"id": "current"}, {"_id": 0})
        return doc or {"status": "idle", "total": 0, "done": 0, "failed": 0}

    @router.post("/admin/refresh")
    async def refresh_cron(request: Request, background_tasks: BackgroundTasks):
        """External-cron entry point (same X-Cron-Key mechanism used
        elsewhere) — meant to run every 10-15 minutes during market hours
        so the scanner tracks the live session, not a stale snapshot."""
        if not cron_secret or request.headers.get("X-Cron-Key") != cron_secret:
            raise HTTPException(status_code=401, detail="Invalid cron key")
        background_tasks.add_task(_refresh_universe, db, definedge)
        return {"status": "started"}

    @router.post("/admin/refresh-now")
    async def refresh_admin(background_tasks: BackgroundTasks, admin: dict = Depends(get_current_admin)):
        background_tasks.add_task(_refresh_universe, db, definedge)
        return {"status": "started"}

    return router
