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
        """Symbol/company search-as-you-type for Prism View's picker."""
        q = q.strip()
        if len(q) < 1:
            return []
        regex = {"$regex": q, "$options": "i"}
        rows = await db.stock_symbol_master.find(
            {"$or": [{"symbol": regex}, {"company_name": regex}]},
            {"_id": 0, "symbol": 1, "company_name": 1, "industry": 1},
        ).limit(20).to_list(20)
        return rows

    return router
