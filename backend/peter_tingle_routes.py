"""
Peter Tingle routes -- combined technical + fundamental caution scan for
one stock, India and US.

India (`/scan/{symbol}`) reuses Stock Research Terminal's already-ingested
collections and its Fracture Scan fundamental ruleset directly, rather
than standing up a second ingestion pipeline -- symbol search stays on
/stock-terminal/symbols/search, this router only adds the scan itself.

US (`/us/scan/{symbol}`) has no equivalent nightly ingestion pipeline: US
daily bars come from yahoo_finance_client.equity_bars() (fetch-and-cache
per ticker, already used elsewhere in this codebase) and derived metrics
are computed on the fly from those bars (peter_tingle.compute_metrics_from_bars)
rather than via a batch job, since Yahoo's free endpoint is cheap enough
to call per request. Fundamentals come from us_stock_fundamentals.py
(Yahoo quoteSummary, day-cached). The only batch step is keeping the
searchable S&P 500 symbol list current (us_stock_universe.py), run
nightly/weekly via the admin+cron routes below, same split every other
ingestion job in this codebase uses.
"""
from fastapi import APIRouter, HTTPException, Request, Depends

from stock_terminal_scoring import scan_red_flags
from peter_tingle import (
    scan_technical_red_flags, scan_us_fundamental_red_flags,
    compute_metrics_from_bars, combine_verdict,
)
from us_stock_universe import sync_universe
from us_stock_fundamentals import fetch_fundamentals
import yahoo_finance_client as yf


def create_peter_tingle_router(db, get_current_admin, cron_secret: str) -> APIRouter:
    router = APIRouter(prefix="/peter-tingle")

    @router.get("/scan/{symbol}")
    async def scan(symbol: str):
        symbol = symbol.strip().upper()
        master = await db.stock_symbol_master.find_one({"symbol": symbol}, {"_id": 0})
        if not master:
            return {"has_data": False}

        metrics = await db.stock_computed_metrics.find_one({"symbol": symbol}, {"_id": 0})
        fundamentals = await db.stock_fundamentals.find_one({"symbol": symbol}, {"_id": 0})
        shareholding = await db.stock_shareholding.find({"symbol": symbol}, {"_id": 0}).sort("quarter", 1).to_list(12)

        technical_flags = scan_technical_red_flags(metrics)
        fundamental_flags = scan_red_flags(fundamentals, master, shareholding)
        verdict = combine_verdict(technical_flags, fundamental_flags)

        return {
            "has_data": True,
            "symbol": symbol,
            "company_name": master.get("company_name"),
            "verdict": verdict,
            "technical_flags": technical_flags,
            "fundamental_flags": fundamental_flags,
        }

    @router.get("/us/symbols/search")
    async def search_us_symbols(q: str = ""):
        q = q.strip()
        if len(q) < 1:
            return []
        regex = {"$regex": q, "$options": "i"}
        rows = await db.us_stock_symbol_master.find(
            {"$or": [{"symbol": regex}, {"company_name": regex}]},
            {"_id": 0, "symbol": 1, "company_name": 1, "sector": 1},
        ).limit(20).to_list(20)
        return rows

    @router.get("/us/scan/{symbol}")
    async def scan_us(symbol: str):
        symbol = symbol.strip().upper()
        master = await db.us_stock_symbol_master.find_one({"symbol": symbol}, {"_id": 0})
        if not master:
            return {"has_data": False}

        try:
            bars = await yf.equity_bars(db, symbol)
        except yf.YahooFinanceError:
            bars = []
        metrics = compute_metrics_from_bars(bars)
        fundamentals = await fetch_fundamentals(db, symbol)

        technical_flags = scan_technical_red_flags(metrics)
        fundamental_flags = scan_us_fundamental_red_flags(fundamentals)
        verdict = combine_verdict(technical_flags, fundamental_flags)

        return {
            "has_data": True,
            "symbol": symbol,
            "company_name": master.get("company_name"),
            "verdict": verdict,
            "technical_flags": technical_flags,
            "fundamental_flags": fundamental_flags,
        }

    async def _run_universe_sync() -> dict:
        try:
            return await sync_universe(db)
        except Exception as e:  # noqa: BLE001
            raise HTTPException(status_code=502, detail=f"Peter Tingle US universe sync failed: {e}")

    @router.post("/us/admin/sync-universe")
    async def sync_universe_cron(request: Request):
        """External-cron entry point -- S&P 500 membership changes rarely,
        weekly is plenty (unlike NSE's daily price/breadth pipeline)."""
        if not cron_secret or request.headers.get("X-Cron-Key") != cron_secret:
            raise HTTPException(status_code=401, detail="Invalid cron key")
        return await _run_universe_sync()

    @router.post("/us/admin/sync-universe-now")
    async def sync_universe_admin(admin: dict = Depends(get_current_admin)):
        return await _run_universe_sync()

    return router
