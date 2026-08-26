"""
Shared REAL-DATA assembly layer for Black Box's three equity strategies --
same role blackbox_options_market.py plays for the options strategies.
Universe lists are fetched live from NSE's own index-constituent CSVs
(same technique relative_strength_routes.py's `_fetch_index_csv` already
uses), and daily OHLCV bars (with volume -- see definedge_service.py's
2026-08-26 fix) are cached per symbol, refreshed once today's own close
is actually in the cache, matching relative_strength_routes.py's
`_closes_for_nse` freshness rule exactly.
"""
import csv
import io
import logging
from datetime import datetime

import httpx

from definedge_service import IST, DefinedgeError

logger = logging.getLogger(__name__)

CACHE_COLLECTION = "blackbox_equity_daily_bars"
YEARS_BACK = 2  # equity strategies here only ever look back a few dozen bars;
                 # 2y is generous headroom without pulling the full 20y
                 # relative_strength_routes.py needs for its box-percentage grid

BROWSER_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)

UNIVERSE_CSV_URL = {
    "nifty50": "https://nsearchives.nseindia.com/content/indices/ind_nifty50list.csv",
    "nifty500": "https://nsearchives.nseindia.com/content/indices/ind_nifty500list.csv",
}
_universe_cache: dict = {}  # kind -> (date_str, list[str])


async def get_universe(kind: str) -> list:
    today = datetime.now(IST).strftime("%Y-%m-%d")
    cached = _universe_cache.get(kind)
    if cached and cached[0] == today:
        return cached[1]
    url = UNIVERSE_CSV_URL[kind]
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.get(url, headers={"User-Agent": BROWSER_USER_AGENT})
    if r.status_code != 200:
        raise DefinedgeError(f"{kind} constituent list fetch failed (HTTP {r.status_code}).")
    symbols = []
    for row in csv.DictReader(io.StringIO(r.text)):
        symbol = (row.get("Symbol") or "").strip()
        if symbol:
            symbols.append(symbol)
    _universe_cache[kind] = (today, symbols)
    return symbols


async def get_daily_bars(db, definedge, master, symbol: str) -> list | None:
    """Oldest -> newest OHLCV dicts for one NSE symbol, or None if it
    can't be resolved/fetched this tick (never fabricated -- caller skips
    the symbol for this run rather than guessing)."""
    today = datetime.now(IST).date().isoformat()
    doc = await db[CACHE_COLLECTION].find_one({"symbol": symbol})
    if doc and doc.get("bars") and doc["bars"][-1]["date"] == today and doc.get("years_back") == YEARS_BACK:
        return doc["bars"]

    found = definedge.resolve_symbol(master, "NSE", symbol)
    if not found:
        logger.warning("Black Box equity: could not resolve %s, skipping.", symbol)
        return None
    try:
        bars = await definedge.daily_history("NSE", found["token"], years=YEARS_BACK)
    except DefinedgeError as e:
        logger.warning("Black Box equity: daily history fetch failed for %s, skipping: %s", symbol, e)
        return None
    if not bars:
        return None
    await db[CACHE_COLLECTION].update_one(
        {"symbol": symbol},
        {"$set": {"symbol": symbol, "years_back": YEARS_BACK, "bars": bars, "last_fetched_date": today}},
        upsert=True,
    )
    return bars
