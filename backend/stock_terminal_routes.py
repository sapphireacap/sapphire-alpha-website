"""
Stock Research Terminal routes -- Phase 1 (ingestion + Alpha Pulse overview
+ symbol search). Same router-factory/cron-vs-admin-JWT pattern as every
other feature area in this backend (see blackbox_routes.py, ipo_routes.py).

Every read route here is public (this section is meant to be visible, same
spirit as Lumen SIP -- unlike Prism Alpha's admin-gated trading data). The
ingestion routes are the only ones gated, split cron/admin like everywhere
else in this codebase.
"""
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request, Depends

from stock_terminal_ingestion import run_nightly_ingestion
from stock_terminal_fundamentals import ingest_fundamentals
from stock_terminal_agent import run_agent_analysis, run_debate
from stock_terminal_scoring import scan_red_flags, compute_scorecard
from stock_terminal_verification import verify_price

logger = logging.getLogger(__name__)

MOVERS_LIMIT = 10
INGESTION_STATUS_COLLECTION = "stock_terminal_ingestion_status"
# Confirmed live 2026-08-13: the nightly ~500-symbol pipeline had gone
# completely un-scheduled (no cron anywhere in this repo ever called
# either admin/ingest-* route) AND both routes blocked the request for
# the whole run -- a 500-symbol sequential Definedge pull is minutes
# long, far past any external cron's timeout, the same failure mode
# server.py's OTP auto-login route had before its 2026-08-12 fix. Real
# damage: last successful run was 2026-07-28 (breadth only counted
# 344/500, meaning even that run was itself cut short), and TCS/SBIN/
# TATASTEEL had ZERO price bars ingested at all. Both routes below now
# queue and return immediately; the real outcome is recorded here and
# surfaced via GET .../admin/ingestion-status, same "a 200 means
# queued, not done" discipline as the OTP fix.


def create_stock_terminal_router(db, definedge, get_current_admin, cron_secret: str) -> APIRouter:
    router = APIRouter(prefix="/stock-terminal")

    async def _record_ingestion_status(job_id: str, outcome: str, detail=None, started_at: datetime = None):
        await db[INGESTION_STATUS_COLLECTION].update_one(
            {"id": job_id},
            {"$set": {
                "id": job_id, "outcome": outcome, "detail": detail,
                "started_at": (started_at or datetime.now(timezone.utc)).isoformat(),
                "finished_at": datetime.now(timezone.utc).isoformat(),
            }},
            upsert=True,
        )

    async def _run_ingestion_background(limit: int = None):
        started_at = datetime.now(timezone.utc)
        try:
            result = await run_nightly_ingestion(db, definedge, limit=limit)
        except Exception as e:  # noqa: BLE001 -- background task, must not raise into the event loop
            logger.exception("Stock Terminal nightly ingestion failed")
            await _record_ingestion_status("nightly", "error", str(e), started_at)
            return
        logger.info("Stock Terminal nightly ingestion done: %s", result)
        await _record_ingestion_status("nightly", "ok", result, started_at)

    @router.post("/admin/ingest-nightly")
    async def ingest_nightly_cron(request: Request, background_tasks: BackgroundTasks):
        """External-cron entry point -- recommend once/day after market
        close, same as every other nightly-refresh job in this codebase.
        Queues and returns immediately -- a real ~500-symbol run is
        minutes long, far past any external cron's timeout if it blocked
        the request (confirmed live: this is exactly why the pipeline
        had silently stopped completing, see the module-level note)."""
        if not cron_secret or request.headers.get("X-Cron-Key") != cron_secret:
            raise HTTPException(status_code=401, detail="Invalid cron key")
        background_tasks.add_task(_run_ingestion_background)
        return {"status": "started"}

    @router.post("/admin/ingest-nightly-now")
    async def ingest_nightly_admin(background_tasks: BackgroundTasks, limit: int = None, admin: dict = Depends(get_current_admin)):
        """Same pipeline, for manual/admin-triggered runs -- `limit` lets a
        verification run stay small (e.g. ?limit=50) instead of pulling the
        full ~500-symbol universe every time. Also queued, for the same
        reason as the cron entry point above."""
        background_tasks.add_task(_run_ingestion_background, limit)
        return {"status": "started"}

    @router.get("/admin/ingestion-status")
    async def ingestion_status(admin: dict = Depends(get_current_admin)):
        """Both queued routes return before the work finishes, so this is
        the only place a failure (or even just "still running") shows up."""
        nightly = await db[INGESTION_STATUS_COLLECTION].find_one({"id": "nightly"}, {"_id": 0})
        fundamentals = await db[INGESTION_STATUS_COLLECTION].find_one({"id": "fundamentals"}, {"_id": 0})
        return {"nightly": nightly, "fundamentals": fundamentals}

    @router.get("/market-pulse")
    async def alpha_pulse():
        """Overview data for the Alpha Pulse page: overall breadth, top
        gainers/losers, universe size. Returns has_data=False (not a 404 or
        empty crash) until the first ingestion run has happened."""
        breadth = await db.stock_market_breadth.find_one({"id": "current"}, {"_id": 0})
        universe_count = await db.stock_symbol_master.count_documents({})
        if not breadth or not universe_count:
            return {"has_data": False}

        metrics = await db.stock_computed_metrics.find(
            {"return_1d": {"$ne": None}}, {"_id": 0, "symbol": 1, "return_1d": 1}
        ).to_list(2000)
        metrics.sort(key=lambda m: m["return_1d"], reverse=True)
        gainers, losers = metrics[:MOVERS_LIMIT], list(reversed(metrics[-MOVERS_LIMIT:])) if metrics else []

        symbols = [m["symbol"] for m in gainers + losers]
        names = {
            s["symbol"]: s["company_name"]
            for s in await db.stock_symbol_master.find({"symbol": {"$in": symbols}}, {"_id": 0, "symbol": 1, "company_name": 1}).to_list(len(symbols) or 1)
        }
        for m in gainers + losers:
            m["company_name"] = names.get(m["symbol"])

        return {
            "has_data": True,
            "breadth_pct": breadth.get("breadth_pct"),
            "breadth_counted": breadth.get("counted"),
            "universe_size": universe_count,
            "updated_at": breadth.get("updated_at"),
            "gainers": gainers,
            "losers": losers,
        }

    @router.get("/symbols/search")
    async def search_symbols(q: str = ""):
        """Symbol/company search-as-you-type for Facet View's picker."""
        q = q.strip()
        if len(q) < 1:
            return []
        regex = {"$regex": q, "$options": "i"}
        rows = await db.stock_symbol_master.find(
            {"$or": [{"symbol": regex}, {"company_name": regex}]},
            {"_id": 0, "symbol": 1, "company_name": 1, "industry": 1},
        ).limit(20).to_list(20)
        return rows

    # ---- Phase 2: fundamentals ingestion + Facet View + Lumen Agent -------
    async def _run_fundamentals_ingestion_background(limit: int = None):
        started_at = datetime.now(timezone.utc)
        try:
            result = await ingest_fundamentals(db, limit=limit)
        except Exception as e:  # noqa: BLE001 -- background task, must not raise into the event loop
            logger.exception("Stock Terminal fundamentals ingestion failed")
            await _record_ingestion_status("fundamentals", "error", str(e), started_at)
            return
        logger.info("Stock Terminal fundamentals ingestion done: %s", result)
        await _record_ingestion_status("fundamentals", "ok", result, started_at)

    @router.post("/admin/ingest-fundamentals")
    async def ingest_fundamentals_cron(request: Request, background_tasks: BackgroundTasks):
        """External-cron entry point -- fundamentals change far less often
        than price, a weekly cadence is plenty (unlike the daily price/
        breadth pipeline above). Queued, same reason as ingest-nightly."""
        if not cron_secret or request.headers.get("X-Cron-Key") != cron_secret:
            raise HTTPException(status_code=401, detail="Invalid cron key")
        background_tasks.add_task(_run_fundamentals_ingestion_background)
        return {"status": "started"}

    @router.post("/admin/ingest-fundamentals-now")
    async def ingest_fundamentals_admin(background_tasks: BackgroundTasks, limit: int = None, admin: dict = Depends(get_current_admin)):
        background_tasks.add_task(_run_fundamentals_ingestion_background, limit)
        return {"status": "started"}

    @router.get("/stock/{symbol}")
    async def stock_bundle(symbol: str):
        """Everything Facet View's header/panels need for one symbol:
        symbol master, latest price + computed metrics, fundamentals,
        shareholding trend. Red flags/scorecard/verification join this in
        Phase 3. has_data=False (not a 404) if the symbol isn't in our
        universe yet -- Facet View can still say so cleanly."""
        symbol = symbol.strip().upper()
        master = await db.stock_symbol_master.find_one({"symbol": symbol}, {"_id": 0})
        if not master:
            return {"has_data": False}

        metrics = await db.stock_computed_metrics.find_one({"symbol": symbol}, {"_id": 0})
        fundamentals = await db.stock_fundamentals.find_one({"symbol": symbol}, {"_id": 0})
        shareholding = await db.stock_shareholding.find({"symbol": symbol}, {"_id": 0}).sort("quarter", 1).to_list(12)
        price_bars = await db.stock_prices_daily.find({"symbol": symbol}, {"_id": 0}).sort("date", -1).to_list(260)

        red_flags = scan_red_flags(fundamentals, master, shareholding)
        scorecard = await compute_scorecard(db, symbol, fundamentals, metrics, master, red_flags)
        verification = await verify_price(db, symbol)

        return {
            "has_data": True,
            "symbol_master": master,
            "computed_metrics": metrics,
            "fundamentals": fundamentals,
            "shareholding": shareholding,
            "price_bars": list(reversed(price_bars)),
            "red_flags": red_flags,
            "scorecard": scorecard,
            "verification": verification,
        }

    @router.post("/stock/{symbol}/analyze")
    async def analyze_stock(symbol: str, force: bool = False):
        """Runs (or returns the cached result of) Lumen Agent's analysis for
        one symbol. Returns {"configured": False, ...} cleanly if
        ANTHROPIC_API_KEY isn't set -- never a 500 for that case."""
        symbol = symbol.strip().upper()
        try:
            return await run_agent_analysis(db, symbol, force=force)
        except Exception as e:  # noqa: BLE001
            raise HTTPException(status_code=502, detail=f"Lumen Agent analysis failed: {e}")

    @router.post("/stock/{symbol}/debate")
    async def debate_stock(symbol: str):
        """The Crucible -- Bull vs. Bear debate for one symbol. Same
        {"configured": False, ...} graceful-degradation contract as
        /analyze. Not cached (unlike /analyze) -- each run is a fresh
        3-round debate, cheap relative to the full tool-use analysis since
        it's 6 plain completions over already-fetched data, not 6 more
        tool-use loops."""
        symbol = symbol.strip().upper()
        try:
            return await run_debate(db, symbol)
        except Exception as e:  # noqa: BLE001
            raise HTTPException(status_code=502, detail=f"The Crucible debate failed: {e}")

    return router
