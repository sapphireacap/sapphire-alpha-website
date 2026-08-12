"""
Peter Tingle routes -- combined technical + fundamental caution scan for
one stock, India and US.

Read routes made public 2026-08-12 at the user's explicit direction
(modules.js's `adminOnly: true` removed from its directory entry at the
same time) -- Peter Tingle was previously an internal-only research tool
(Depends(get_current_admin) on every read route). The two universe-sync
routes keep their existing cron-secret / admin split, unrelated to and
predating this change.

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
from fastapi import APIRouter, HTTPException, Request, Depends  # Depends still used by the admin-gated sync-universe-now route

from stock_terminal_scoring import scan_red_flags
from peter_tingle import (
    scan_technical_red_flags, scan_us_fundamental_red_flags,
    compute_metrics_from_bars, combine_verdict,
)
from peter_tingle_pivots import pivot_levels_for_bars
from pnf_observations import pnf_observations
from peter_tingle_fundamentals import fundamental_observations
from us_stock_universe import sync_universe
from us_stock_fundamentals import fetch_fundamentals
import yahoo_finance_client as yf

# Both markets' `metrics` dicts (stock_computed_metrics for India,
# compute_metrics_from_bars()'s output for US) already carry these exact
# keys -- see stock_terminal_ingestion.py's RETURN_WINDOWS and
# peter_tingle.py's identical RETURN_WINDOWS -- so Price Performance is
# just a relabel, not new computation. "Quarterly" maps to the existing
# 3-month window, matching the report's own bucket names.
_PRICE_PERFORMANCE_KEYS = {
    "daily": "return_1d", "weekly": "return_1w", "monthly": "return_1m",
    "quarterly": "return_3m", "yearly": "return_1y",
}


def _price_performance(metrics: dict) -> dict:
    m = metrics or {}
    return {label: m.get(key) for label, key in _PRICE_PERFORMANCE_KEYS.items()}


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
        # Pivot levels need real OHLC, which stock_computed_metrics doesn't
        # carry (it's derived closes-only) -- stock_prices_daily is the
        # same nightly-ingested 5-year daily series compute_derived_metrics
        # itself reads from (stock_terminal_ingestion.py), so this is a
        # second read of already-fetched data, not a new upstream call.
        bars = await db.stock_prices_daily.find({"symbol": symbol}, {"_id": 0}).sort("date", 1).to_list(2000)

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
            "price_performance": _price_performance(metrics),
            "pivot_levels": pivot_levels_for_bars(bars) if bars else {"daily": None, "weekly": None, "monthly": None},
            "pnf_observations": pnf_observations(bars),
            "fundamental_observations": fundamental_observations(fundamentals, shareholding),
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
            "price_performance": _price_performance(metrics),
            "pivot_levels": pivot_levels_for_bars(bars) if bars else {"daily": None, "weekly": None, "monthly": None},
            "pnf_observations": pnf_observations(bars),
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
