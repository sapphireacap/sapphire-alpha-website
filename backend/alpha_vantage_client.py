"""Alpha Vantage daily-bar client for the two US index proxies on the P&F
platform (NDX via QQQ, SPX via SPY).

Alpha Vantage's free tier has no real data for raw index tickers — verified
live 2026-08-02: TIME_SERIES_DAILY returns an empty series for both `SPX`
and `GSPC`, despite SPX appearing as a valid symbol under SYMBOL_SEARCH.
The underlying ETF is the only free-tier option with real daily OHLCV, so
every "index" chart built from this module is honestly the ETF's price,
not the index itself — callers must surface that (see pnf_routes.py's
`tradingsymbol` label) rather than imply it's the raw index.

`outputsize=full` is ALSO a premium-only feature on this tier — verified
live 2026-08-02, the free key gets "outputsize=full ... is a premium
feature" back instead of data. The free tier only ever returns `compact`
(the latest ~100 trading days). Rather than pretend to a longer history
than we actually have, this module ACCUMULATES: every real day's compact
pull is merged permanently into Mongo instead of overwriting the cache, so
the stored history only ever grows (one genuine trading day at a time) and
never shrinks back to 100 bars. Starts thin, gets deeper for free over
time — nothing here is ever synthesized to fill the gap.

Free-tier quota is tight (25 requests/day, 5/min), so at most one live
call per symbol per day happens — the accumulated Mongo doc answers every
other request that day.
"""
from __future__ import annotations

from datetime import datetime, timezone

import httpx

BASE_URL = "https://www.alphavantage.co/query"
CACHE_COLLECTION = "av_daily_cache"

# Symbol key exposed to the API/UI -> the real, liquid ETF ticker actually
# fetched. Both are the standard, most-liquid proxy for their index.
US_INDEX_PROXIES = {
    "NDX": {"proxy": "QQQ", "label": "Nasdaq 100"},
    "SPX": {"proxy": "SPY", "label": "S&P 500"},
}


class AlphaVantageError(Exception):
    """Config/upstream problems — caller decides how much to expose."""


def _api_key() -> str:
    import os
    key = os.environ.get("ALPHAVANTAGE_API_KEY")
    if not key:
        raise AlphaVantageError("ALPHAVANTAGE_API_KEY not configured.")
    return key


async def _fetch_daily_compact(proxy_symbol: str) -> list:
    """Latest ~100 real trading days — the free tier's actual ceiling
    (see module docstring; `full` 404s into a premium upsell instead)."""
    params = {
        "function": "TIME_SERIES_DAILY",
        "symbol": proxy_symbol,
        "outputsize": "compact",
        "apikey": _api_key(),
    }
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.get(BASE_URL, params=params)
    data = r.json()
    series = data.get("Time Series (Daily)")
    if not series:
        note = data.get("Note") or data.get("Information") or data.get("Error Message") or str(data)
        raise AlphaVantageError(f"No daily series for {proxy_symbol}: {note}")
    bars = [
        {
            "date": day,
            "open": float(v["1. open"]),
            "high": float(v["2. high"]),
            "low": float(v["3. low"]),
            "close": float(v["4. close"]),
        }
        for day, v in series.items()
    ]
    bars.sort(key=lambda b: b["date"])
    return bars


def _merge_bars(existing: list, fresh: list) -> list:
    """Union by date, fresh values win on overlap (AV occasionally revises
    the last day or two), sorted ascending. This is the only place old and
    new history combine — never truncated, only ever grows."""
    by_date = {b["date"]: b for b in existing}
    for b in fresh:
        by_date[b["date"]] = b
    return [by_date[d] for d in sorted(by_date)]


async def daily_bars(db, symbol_key: str) -> list:
    """Accumulated real daily OHLC history for NDX or SPX (proxy ticker
    under the hood). At most one Alpha Vantage call per symbol per real
    calendar day — every other call today, and every bar from previous
    days, comes straight out of Mongo."""
    symbol_key = symbol_key.strip().upper()
    if symbol_key not in US_INDEX_PROXIES:
        raise AlphaVantageError(f"Unknown US index symbol {symbol_key}.")

    today = datetime.now(timezone.utc).date().isoformat()
    doc = await db[CACHE_COLLECTION].find_one({"symbol": symbol_key})
    if doc and doc.get("last_fetched_date") == today:
        return doc["bars"]

    proxy = US_INDEX_PROXIES[symbol_key]["proxy"]
    fresh = await _fetch_daily_compact(proxy)
    merged = _merge_bars(doc["bars"] if doc else [], fresh)
    await db[CACHE_COLLECTION].update_one(
        {"symbol": symbol_key},
        {"$set": {"symbol": symbol_key, "last_fetched_date": today, "bars": merged}},
        upsert=True,
    )
    return merged
