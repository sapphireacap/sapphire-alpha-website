"""
Stock Research Terminal -- nightly data ingestion pipeline (Phase 1: symbol
universe, daily prices, derived metrics/breadth). Read-only throughout, no
order-placement endpoint referenced anywhere.

Universe source: NSE's own Nifty 500 constituent CSV
(nsearchives.nseindia.com/content/indices/ind_nifty500list.csv) -- the exact
same already-verified endpoint quant_lab.py's Sharpe Dashboard already uses
for its own universe. This doubles as the correct breadth-calculation
universe the original spec calls for ("% of Nifty 500 constituents with
positive 1D return"), so no separate NSE/BSE full-archive scrape
(EQUITY_L.csv/SME_EQUITY_L.csv) is needed on top of it for Phase 1.

Price data source: DefinedgeService.daily_history() -- the same
already-authorized, already-integrated broker API every other market-data
feature on this site uses, replacing the original spec's Yahoo Finance v8
chart API scrape entirely.

Known, disclosed gaps (not fabricated, not silently guessed):
- `volume` is stored as null -- DefinedgeService.daily_history() doesn't
  parse a volume field out of Definedge's response.
- `market_cap_cr`/`mcap_rank`/`cap_segment`/`sector` are stored as null in
  Phase 1 -- no real market-cap data source is wired up yet (Definedge's
  master and the Nifty 500 CSV both lack it). Filling these in later needs a
  real market-cap source, not an estimate from price alone.
- `pe_percentile_5y`/`price_percentile_5y` (spec's computed_metrics table)
  need cross-sectional fundamentals data, which Phase 1 doesn't ingest yet
  (see backend/stock_terminal_fundamentals.py, Phase 2) -- left out of
  compute_derived_metrics() until then.
"""
import csv
import io
import logging
from datetime import datetime, timezone, timedelta

import httpx
from pymongo import ReplaceOne

from definedge_service import DefinedgeError

logger = logging.getLogger(__name__)
IST = timezone(timedelta(hours=5, minutes=30))

BROWSER_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)
NIFTY500_CSV_URL = "https://nsearchives.nseindia.com/content/indices/ind_nifty500list.csv"

DMA_WINDOWS = {"dma_50": 50, "dma_200": 200}
RETURN_WINDOWS = {
    "return_1d": 1, "return_1w": 5, "return_1m": 21, "return_3m": 63,
    "return_6m": 126, "return_1y": 252, "return_5y": 1260,
}


async def _fetch_universe() -> list:
    """[{symbol, company_name, industry}, ...] -- see module docstring for
    the source. Raises DefinedgeError on a non-200 (matches the existing
    convention for this exact endpoint in quant_lab.py) rather than
    returning a silently-empty universe."""
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.get(NIFTY500_CSV_URL, headers={"User-Agent": BROWSER_USER_AGENT})
    if r.status_code != 200:
        raise DefinedgeError(f"Nifty 500 list fetch failed (HTTP {r.status_code}).")
    rows = []
    for row in csv.DictReader(io.StringIO(r.text)):
        symbol = (row.get("Symbol") or "").strip()
        if not symbol:
            continue
        rows.append({
            "symbol": symbol,
            "company_name": (row.get("Company Name") or "").strip(),
            "industry": (row.get("Industry") or "").strip(),
        })
    return rows


async def ingest_symbol_master(db, definedge, limit: int = None) -> dict:
    """Upserts stock_symbol_master from the Nifty 500 universe, cross-
    referenced against Definedge's own master for exchange confirmation and
    a company-name fallback. `limit` truncates the universe -- for quick
    manual verification runs only, never passed by the real nightly cron."""
    universe = await _fetch_universe()
    if limit:
        universe = universe[:limit]
    df = await definedge._get_all_master()

    updated, failed = 0, 0
    for row in universe:
        try:
            resolved = definedge.resolve_symbol(df, "NSE", row["symbol"])
            doc = {
                "symbol": row["symbol"],
                "company_name": row["company_name"] or definedge.company_name(df, row["symbol"]) or row["symbol"],
                "exchange": "NSE" if resolved else None,
                "industry": row["industry"] or None,
                "sector": None,
                "market_cap_cr": None,
                "mcap_rank": None,
                "cap_segment": None,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
            await db.stock_symbol_master.update_one({"symbol": row["symbol"]}, {"$set": doc}, upsert=True)
            updated += 1
        except Exception as e:  # noqa: BLE001 -- one symbol's failure must not stop the rest
            logger.warning("Stock Terminal: symbol master ingest failed for %s: %s", row["symbol"], e)
            failed += 1
    return {"updated": updated, "failed": failed, "total": len(universe)}


async def ingest_daily_prices(db, definedge, limit: int = None) -> dict:
    """Upserts stock_prices_daily for every symbol currently in
    stock_symbol_master, via DefinedgeService.daily_history(). Per-day
    upsert (ReplaceOne, not insert_many) so a re-run never duplicates rows."""
    symbols = await db.stock_symbol_master.find({}, {"_id": 0, "symbol": 1}).to_list(1000)
    if limit:
        symbols = symbols[:limit]
    df = await definedge._get_all_master()

    updated, failed = 0, 0
    for s in symbols:
        symbol = s["symbol"]
        try:
            resolved = definedge.resolve_symbol(df, "NSE", symbol)
            if not resolved:
                logger.warning("Stock Terminal: could not resolve %s on NSE, skipping price ingest.", symbol)
                failed += 1
                continue
            bars = await definedge.daily_history("NSE", resolved["token"], years=5)
            if not bars:
                failed += 1
                continue
            ops = [
                ReplaceOne(
                    {"symbol": symbol, "date": b["date"]},
                    {"symbol": symbol, "date": b["date"], "open": b["open"], "high": b["high"],
                     "low": b["low"], "close": b["close"], "volume": None},
                    upsert=True,
                )
                for b in bars
            ]
            if ops:
                await db.stock_prices_daily.bulk_write(ops, ordered=False)
            updated += 1
        except Exception as e:  # noqa: BLE001
            logger.warning("Stock Terminal: daily price ingest failed for %s: %s", symbol, e)
            failed += 1
    return {"updated": updated, "failed": failed, "total": len(symbols)}


def _pct_return(closes: list, days_back: int):
    if len(closes) <= days_back:
        return None
    prior = closes[-1 - days_back]
    if not prior:
        return None
    return (closes[-1] / prior - 1) * 100


async def compute_derived_metrics(db) -> dict:
    """Recomputes stock_computed_metrics for every symbol with price history
    on file, plus overall market breadth (% of the universe with a positive
    1-day return) into stock_market_breadth (single doc, id='current').
    Pure Mongo reads -- no external calls, safe to run right after
    ingest_daily_prices in the same pipeline invocation."""
    symbols = await db.stock_symbol_master.find({}, {"_id": 0, "symbol": 1}).to_list(1000)
    updated, failed = 0, 0
    positive_1d, counted = 0, 0

    for s in symbols:
        symbol = s["symbol"]
        try:
            bars = await db.stock_prices_daily.find({"symbol": symbol}, {"_id": 0}).sort("date", 1).to_list(2000)
            if len(bars) < 2:
                failed += 1
                continue
            closes = [b["close"] for b in bars]
            highs = [b["high"] for b in bars]
            lows = [b["low"] for b in bars]
            dates = [b["date"] for b in bars]

            ath, atl = max(highs), min(lows)
            r1d = _pct_return(closes, 1)

            metrics = {
                "symbol": symbol,
                **{k: (sum(closes[-n:]) / len(closes[-n:])) for k, n in DMA_WINDOWS.items()},
                **{k: _pct_return(closes, n) for k, n in RETURN_WINDOWS.items()},
                "ath": ath, "ath_date": dates[highs.index(ath)],
                "atl": atl, "atl_date": dates[lows.index(atl)],
                "pct_from_ath": ((closes[-1] / ath) - 1) * 100 if ath else None,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
            await db.stock_computed_metrics.update_one({"symbol": symbol}, {"$set": metrics}, upsert=True)
            updated += 1
            if r1d is not None:
                counted += 1
                if r1d > 0:
                    positive_1d += 1
        except Exception as e:  # noqa: BLE001
            logger.warning("Stock Terminal: derived metrics failed for %s: %s", symbol, e)
            failed += 1

    breadth_pct = (positive_1d / counted * 100) if counted else None
    await db.stock_market_breadth.update_one(
        {"id": "current"},
        {"$set": {"id": "current", "breadth_pct": breadth_pct, "counted": counted,
                   "updated_at": datetime.now(timezone.utc).isoformat()}},
        upsert=True,
    )
    return {"updated": updated, "failed": failed, "total": len(symbols), "breadth_pct": breadth_pct}


async def run_nightly_ingestion(db, definedge, limit: int = None) -> dict:
    """The single nightly pipeline entry point -- symbol master, then daily
    prices, then derived metrics/breadth, strictly in that order since each
    step reads what the previous one just wrote. `limit` is for manual
    verification runs against a small slice of the universe."""
    sm = await ingest_symbol_master(db, definedge, limit=limit)
    dp = await ingest_daily_prices(db, definedge, limit=limit)
    dm = await compute_derived_metrics(db)
    return {
        "symbol_master": sm, "daily_prices": dp, "derived_metrics": dm,
        "run_at": datetime.now(timezone.utc).isoformat(),
    }
