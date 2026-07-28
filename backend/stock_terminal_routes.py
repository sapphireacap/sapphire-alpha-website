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

from fastapi import APIRouter, HTTPException, Request, Depends

from stock_terminal_ingestion import run_nightly_ingestion
from stock_terminal_fundamentals import ingest_fundamentals
from stock_terminal_agent import run_agent_analysis
from stock_terminal_scoring import scan_red_flags, compute_scorecard
from stock_terminal_verification import verify_price

logger = logging.getLogger(__name__)

MOVERS_LIMIT = 10


def create_stock_terminal_router(db, definedge, get_current_admin, cron_secret: str) -> APIRouter:
    router = APIRouter(prefix="/stock-terminal")

    async def _run_ingestion(limit: int = None) -> dict:
        try:
            return await run_nightly_ingestion(db, definedge, limit=limit)
        except Exception as e:  # noqa: BLE001
            raise HTTPException(status_code=502, detail=f"Stock Terminal ingestion failed: {e}")

    @router.post("/admin/ingest-nightly")
    async def ingest_nightly_cron(request: Request):
        """External-cron entry point -- recommend once/day after market
        close, same as every other nightly-refresh job in this codebase."""
        if not cron_secret or request.headers.get("X-Cron-Key") != cron_secret:
            raise HTTPException(status_code=401, detail="Invalid cron key")
        return await _run_ingestion()

    @router.post("/admin/ingest-nightly-now")
    async def ingest_nightly_admin(limit: int = None, admin: dict = Depends(get_current_admin)):
        """Same pipeline, for manual/admin-triggered runs -- `limit` lets a
        verification run stay small (e.g. ?limit=50) instead of pulling the
        full ~500-symbol universe every time."""
        return await _run_ingestion(limit=limit)

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
    async def _run_fundamentals_ingestion(limit: int = None) -> dict:
        try:
            return await ingest_fundamentals(db, limit=limit)
        except Exception as e:  # noqa: BLE001
            raise HTTPException(status_code=502, detail=f"Stock Terminal fundamentals ingestion failed: {e}")

    @router.post("/admin/ingest-fundamentals")
    async def ingest_fundamentals_cron(request: Request):
        """External-cron entry point -- fundamentals change far less often
        than price, a weekly cadence is plenty (unlike the daily price/
        breadth pipeline above)."""
        if not cron_secret or request.headers.get("X-Cron-Key") != cron_secret:
            raise HTTPException(status_code=401, detail="Invalid cron key")
        return await _run_fundamentals_ingestion()

    @router.post("/admin/ingest-fundamentals-now")
    async def ingest_fundamentals_admin(limit: int = None, admin: dict = Depends(get_current_admin)):
        return await _run_fundamentals_ingestion(limit=limit)

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

    return router
