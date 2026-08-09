"""
US Markets — X-Percent Breadth for the S&P 500 universe. Reuses
breadth_engine.py's pure P&F-direction computation unchanged (it only
ever takes {date: close} dicts, no Definedge coupling) -- just a
different closes source (yahoo_finance_client.equity_bars) and a single
fixed group instead of breadth_groups.py's NSE index picker.
"""
import asyncio
from datetime import datetime, timezone

import breadth_engine as be
import yahoo_finance_client as yf

CLOSES_CACHE_COLLECTION = "us_breadth_daily_closes"
SERIES_CACHE_COLLECTION = "us_breadth_x_percent_cache"
REFRESH_STATUS_COLLECTION = "us_breadth_refresh_status"
INDEX_CANDLES_COLLECTION = "us_breadth_index_candles"
MAX_CONCURRENT_FETCHES = 5
GROUP_KEY = "sp500"
GROUP_LABEL = "S&P 500"


async def _closes_for(db, symbol: str) -> dict:
    try:
        bars = await yf.equity_bars(db, symbol)
    except yf.YahooFinanceError:
        return {}
    return {b["date"]: b["close"] for b in bars}


async def _refresh_index_candles(db):
    """S&P 500 index (^GSPC) daily OHLC, the reference line plotted above
    the breadth line -- same yahoo_finance_client.daily_bars() US Indices
    already uses elsewhere."""
    try:
        bars = await yf.daily_bars(db, "SPX")
    except yf.YahooFinanceError:
        return
    candles = [{"date": b["date"], "open": b["open"], "high": b["high"], "low": b["low"], "close": b["close"]} for b in bars]
    await db[INDEX_CANDLES_COLLECTION].update_one(
        {"id": "SPX"}, {"$set": {"id": "SPX", "candles": candles, "computed_at": datetime.now(timezone.utc).isoformat()}}, upsert=True,
    )


async def refresh(db):
    """FastAPI BackgroundTask -- one full S&P 500 pass, mirrors
    breadth_routes.py's _refresh_group exactly (per-symbol guard, bounded
    concurrency, direction discarded right after computing so the full
    500-symbol close history is never held in memory at once)."""
    now_iso = lambda: datetime.now(timezone.utc).isoformat()  # noqa: E731
    symbols = [r["symbol"] for r in await db.us_stock_symbol_master.find({}, {"_id": 0, "symbol": 1}).to_list(1000)]
    total = len(symbols)
    await db[REFRESH_STATUS_COLLECTION].update_one(
        {"id": GROUP_KEY},
        {"$set": {"id": GROUP_KEY, "status": "running", "started_at": now_iso(), "completed_at": None,
                   "total": total, "done": 0, "resolved": 0, "failed": 0}},
        upsert=True,
    )

    semaphore = asyncio.Semaphore(MAX_CONCURRENT_FETCHES)
    counters = {"done": 0, "resolved": 0, "failed": 0}
    counters_lock = asyncio.Lock()
    directions_by_symbol = {}

    async def worker(symbol):
        try:
            async with semaphore:
                closes = await _closes_for(db, symbol)
            directions = be.direction_by_date(closes) if closes else None
            async with counters_lock:
                counters["done"] += 1
                if closes:
                    counters["resolved"] += 1
                    directions_by_symbol[symbol] = directions
                else:
                    counters["failed"] += 1
                await db[REFRESH_STATUS_COLLECTION].update_one(
                    {"id": GROUP_KEY},
                    {"$set": {"done": counters["done"], "resolved": counters["resolved"], "failed": counters["failed"]}},
                )
        except Exception:  # noqa: BLE001
            pass

    await asyncio.gather(*(worker(s) for s in symbols), _refresh_index_candles(db))

    series = be.compute_breadth_series_from_directions(directions_by_symbol, total=total) if directions_by_symbol else []
    await db[SERIES_CACHE_COLLECTION].update_one(
        {"group": GROUP_KEY},
        {"$set": {
            "group": GROUP_KEY, "series": series, "universe_total": total, "universe_resolved": counters["resolved"],
            "box_pct": be.DEFAULT_BOX_PCT, "reversal_boxes": be.DEFAULT_REVERSAL,
            "computed_at": now_iso(),
        }},
        upsert=True,
    )
    await db[REFRESH_STATUS_COLLECTION].update_one({"id": GROUP_KEY}, {"$set": {"status": "done", "completed_at": now_iso()}})
