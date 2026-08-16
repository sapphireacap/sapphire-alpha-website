"""
US Markets — the US counterpart to Alpha Terminal's India module set,
public and free-tier same as every other live module here. One router
file covering every US module built so far (Exitline, Momentum Investing,
Momentum Leaders, Breadth, Market Assessment) rather than one file per
module like the India side, since each is a thin adapter over an already-
existing pure engine (see us_exitline.py / us_momentum.py / us_breadth.py)
plumbed onto US data sources -- there's no Definedge-instrument-resolution
complexity here to justify separate files per module.

Index Vector and Options Trend Scanner have NO US equivalent here --
both read live options-market structure, which only exists in this
codebase via Definedge (India-only). Alpaca does serve real US options
quotes (confirmed live), but replicating those two modules' full P&F
options-structure confluence engines is separate, dedicated work, not
attempted in this pass. Swing Picks also has no US equivalent yet (it's
hand-curated pick data on the India side, not a live scan).
"""
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request

import alpaca_client as ac
import us_breadth
import us_exitline
import us_momentum
import yahoo_finance_client as yf

logger = logging.getLogger(__name__)

MOMENTUM_INVESTING_MIN_COVERAGE = 300
INDEX_QUOTES = {"SPX": "%5EGSPC", "NDX": "%5ENDX"}


def create_us_markets_router(db, get_current_admin, get_current_user, cron_secret: str) -> APIRouter:
    # Alpha Terminal access rule: only Index Vector and Exitline are open to
    # signed-out visitors; every other module needs an account. Enforced on
    # the server too, since these endpoints are directly callable.
    require_user = Depends(get_current_user)

    router = APIRouter(prefix="/us-markets", tags=["us-markets"])

    def _require_cron(request: Request):
        if not cron_secret or request.headers.get("X-Cron-Key") != cron_secret:
            raise HTTPException(status_code=401, detail="Invalid cron key")

    # -- shared symbol search (public -- unlike peter-tingle's admin-gated
    #    /us/symbols/search, every US Markets module here is a public tile) --
    @router.get("/symbols/search")
    async def search_symbols(q: str = ""):
        q = q.strip()
        regex = {"$regex": q, "$options": "i"}
        rows = await db.us_stock_symbol_master.find(
            {"$or": [{"symbol": regex}, {"company_name": regex}]},
            {"_id": 0, "symbol": 1, "company_name": 1, "sector": 1},
        ).limit(20).to_list(20)
        return rows

    # -- Exitline -----------------------------------------------------------
    @router.get("/exitline")
    async def exitline(symbol: str, interval: int = 5):
        symbol = symbol.strip().upper()
        master = await db.us_stock_symbol_master.find_one({"symbol": symbol}, {"_id": 0})
        if not master:
            raise HTTPException(status_code=404, detail=f"No instrument found for {symbol}.")
        try:
            result = await us_exitline.build_exitline_response(db, symbol, interval)
        except yf.YahooFinanceError as e:
            logger.warning("US Exitline failed for %s: %s", symbol, e)
            raise HTTPException(status_code=502, detail="Chart data is temporarily unavailable — please try again shortly.")
        result["tradingsymbol"] = master.get("company_name") or symbol
        return result

    # -- Momentum Investing (12-1, risk-adjusted, positional) ---------------
    @router.get("/momentum-investing/top")
    async def momentum_investing_top(limit: int = 20, user: dict = require_user):
        today = datetime.now(timezone.utc).date().isoformat()
        docs = await db.us_momentum_cache.find({}, {"_id": 0}).to_list(600)
        fresh = [d for d in docs if d.get("computed_date") == today and d.get("stats", {}).get("momentum_score") is not None]
        if len(fresh) < MOMENTUM_INVESTING_MIN_COVERAGE:
            return {"found": False, "reason": f"S&P 500 momentum ranking isn't ready yet — only {len(fresh)} of ~500 constituents are cached today."}
        ranked = sorted(fresh, key=lambda d: d["stats"]["momentum_score"], reverse=True)[:limit]
        names = {r["symbol"]: r.get("company_name") for r in await db.us_stock_symbol_master.find(
            {"symbol": {"$in": [d["symbol"] for d in ranked]}}, {"_id": 0, "symbol": 1, "company_name": 1}).to_list(limit)}
        for d in ranked:
            d["company_name"] = names.get(d["symbol"])
        return {"found": True, "results": ranked, "universe_coverage": {"cached": len(fresh), "total": len(docs)}}

    @router.get("/momentum-investing/refresh-status")
    async def momentum_investing_status():
        return await db.us_momentum_refresh_status.find_one({"id": "current"}, {"_id": 0}) or {"status": "idle", "total": 0, "done": 0}

    @router.post("/momentum-investing/admin/refresh")
    async def momentum_investing_refresh_cron(request: Request, background_tasks: BackgroundTasks):
        _require_cron(request)
        background_tasks.add_task(us_momentum.refresh_momentum_cache, db)
        return {"status": "started"}

    @router.post("/momentum-investing/admin/refresh-now")
    async def momentum_investing_refresh_admin(background_tasks: BackgroundTasks, admin: dict = Depends(get_current_admin)):
        background_tasks.add_task(us_momentum.refresh_momentum_cache, db)
        return {"status": "started"}

    # -- Momentum Leaders (1w/1m short-term ranking) -------------------------
    @router.get("/momentum-leaders/top")
    async def momentum_leaders_top(limit: int = 20, user: dict = require_user):
        today = datetime.now(timezone.utc).date().isoformat()
        docs = await db.us_momentum_leaders_cache.find({}, {"_id": 0}).to_list(600)
        fresh = [d for d in docs if d.get("computed_date") == today]
        if len(fresh) < MOMENTUM_INVESTING_MIN_COVERAGE:
            return {"found": False, "reason": f"S&P 500 momentum leaders ranking isn't ready yet — only {len(fresh)} of ~500 constituents are cached today."}
        ranked = sorted(fresh, key=lambda d: d["score"], reverse=True)[:limit]
        names = {r["symbol"]: r.get("company_name") for r in await db.us_stock_symbol_master.find(
            {"symbol": {"$in": [d["symbol"] for d in ranked]}}, {"_id": 0, "symbol": 1, "company_name": 1}).to_list(limit)}
        for d in ranked:
            d["company_name"] = names.get(d["symbol"])
        return {"found": True, "results": ranked, "universe_coverage": {"cached": len(fresh), "total": len(docs)}}

    @router.post("/momentum-leaders/admin/refresh")
    async def momentum_leaders_refresh_cron(request: Request, background_tasks: BackgroundTasks):
        _require_cron(request)
        background_tasks.add_task(us_momentum.refresh_leaders_cache, db)
        return {"status": "started"}

    @router.post("/momentum-leaders/admin/refresh-now")
    async def momentum_leaders_refresh_admin(background_tasks: BackgroundTasks, admin: dict = Depends(get_current_admin)):
        background_tasks.add_task(us_momentum.refresh_leaders_cache, db)
        return {"status": "started"}

    # -- Breadth --------------------------------------------------------------
    @router.get("/breadth")
    async def breadth(user: dict = require_user):
        doc = await db[us_breadth.SERIES_CACHE_COLLECTION].find_one({"group": us_breadth.GROUP_KEY}, {"_id": 0})
        if not doc or not doc.get("series"):
            raise HTTPException(status_code=404, detail="S&P 500 breadth hasn't been computed yet — trigger a refresh.")
        index_doc = await db[us_breadth.INDEX_CANDLES_COLLECTION].find_one({"id": "SPX"}, {"_id": 0})
        doc["index_candles"] = index_doc["candles"] if index_doc else []
        return doc

    @router.get("/breadth/refresh-status")
    async def breadth_status():
        return await db[us_breadth.REFRESH_STATUS_COLLECTION].find_one({"id": us_breadth.GROUP_KEY}, {"_id": 0}) or {"status": "idle", "total": 0, "done": 0}

    @router.post("/breadth/admin/refresh")
    async def breadth_refresh_cron(request: Request, background_tasks: BackgroundTasks):
        _require_cron(request)
        background_tasks.add_task(us_breadth.refresh, db)
        return {"status": "started"}

    @router.post("/breadth/admin/refresh-now")
    async def breadth_refresh_admin(background_tasks: BackgroundTasks, admin: dict = Depends(get_current_admin)):
        background_tasks.add_task(us_breadth.refresh, db)
        return {"status": "started"}

    # -- Market Assessment (composite: index levels, breadth, sectors, movers) --
    @router.get("/market-assessment")
    async def market_assessment(user: dict = require_user):
        index_levels = {}
        for key, yahoo_sym in INDEX_QUOTES.items():
            try:
                index_levels[key] = await yf.quote_snapshot(yahoo_sym)
            except yf.YahooFinanceError:
                index_levels[key] = None

        breadth_doc = await db[us_breadth.SERIES_CACHE_COLLECTION].find_one({"group": us_breadth.GROUP_KEY}, {"_id": 0})
        breadth_pct = breadth_doc["series"][-1]["value"] if breadth_doc and breadth_doc.get("series") else None

        movers = await db.us_momentum_leaders_cache.find({}, {"_id": 0}).to_list(600)
        today = datetime.now(timezone.utc).date().isoformat()
        movers = [m for m in movers if m.get("computed_date") == today and m.get("return_1d") is not None]
        movers.sort(key=lambda m: m["return_1d"], reverse=True)
        gainers, losers = movers[:10], list(reversed(movers[-10:])) if movers else []

        sector_by_symbol = {r["symbol"]: r.get("sector") for r in await db.us_stock_symbol_master.find({}, {"_id": 0, "symbol": 1, "sector": 1}).to_list(1000)}
        sector_returns: dict = {}
        for m in movers:
            sector = sector_by_symbol.get(m["symbol"])
            if not sector:
                continue
            sector_returns.setdefault(sector, []).append(m["return_1d"])
        sector_performance = sorted(
            [{"sector": s, "avg_return_1d": round(sum(v) / len(v), 2), "count": len(v)} for s, v in sector_returns.items()],
            key=lambda r: r["avg_return_1d"], reverse=True,
        )

        return {
            "has_data": bool(movers),
            "index_levels": index_levels,
            "breadth_pct": breadth_pct,
            "universe_size": len(sector_by_symbol),
            "gainers": gainers,
            "losers": losers,
            "sector_performance": sector_performance,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }

    return router
