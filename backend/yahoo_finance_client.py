"""Yahoo Finance daily-bar client for the US Indices segment of the P&F
platform (Nasdaq 100 / S&P 500).

Free, keyless, and already proven to work from this backend's own
Render-hosted server -- server.py's /terminal/external-spot route hits
the same endpoint (with the same browser User-Agent trick) for the
homepage's live SPX/Gold ticker. Replaces alpha_vantage_client.py, whose
free tier (25 requests/day, ~1/sec burst throttle -- verified live,
2026-08-04, and too tight to survive normal traffic plus testing) made
this segment unreliable. Yahoo's chart endpoint has shown no rate-limit
trouble at this call volume.

Also switches from an ETF tracking proxy (QQQ/SPY, what Alpha Vantage's
free tier required) to the real index itself (^NDX, ^GSPC) -- more
accurate, and Yahoo serves both directly.
"""
from __future__ import annotations

from datetime import datetime, timezone

import httpx

BASE_URL = "https://query1.finance.yahoo.com/v8/finance/chart"
CACHE_COLLECTION = "yahoo_daily_cache"

# Yahoo's unofficial endpoint blocks bare/curl user agents outright
# (verified live, 2026-08-04, same finding as server.py's external-spot
# route) -- this just matches what any real browser already sends.
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

US_INDEX_SYMBOLS = {
    "NDX": {"yahoo": "%5ENDX", "label": "Nasdaq 100"},
    "SPX": {"yahoo": "%5EGSPC", "label": "S&P 500"},
}

# Commodities segment — same free/keyless Yahoo chart endpoint, just a
# different symbol dict. XAUUSD itself (spot forex-style ticker) doesn't
# resolve on Yahoo's endpoint (verified live, 2026-08-06: both "XAU=X" and
# "XAUUSD=X" 404) -- GC=F (COMEX gold futures, USD/troy oz) does and is the
# standard free proxy (futures track spot closely, small basis that
# converges at expiry). Daily/weekly/monthly only, same as US indices — no
# permanent minute-bar caching here (Yahoo's own 1-minute data only reaches
# back ~7-8 days per request, verified live, not worth a whole caching
# layer for a window that short).
COMMODITY_SYMBOLS = {
    "XAUUSD": {"yahoo": "GC=F", "label": "Gold (Futures)"},
}


class YahooFinanceError(Exception):
    """Upstream problems -- safe to show a caller."""


async def _fetch_daily(yahoo_symbol: str, range_: str = "10y") -> list:
    """Real daily OHLC straight off Yahoo's chart endpoint. Drops any bar
    with a null close -- Yahoo includes a still-forming TODAY bar with
    nulls for whatever hasn't printed yet while the US session is open,
    and close is all this close-only engine reads anyway."""
    try:
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.get(
                f"{BASE_URL}/{yahoo_symbol}",
                params={"range": range_, "interval": "1d"},
                headers={"User-Agent": USER_AGENT},
            )
        r.raise_for_status()
        data = r.json()
    except httpx.HTTPError as e:
        raise YahooFinanceError(f"Yahoo Finance request failed: {e}") from e

    result = (data.get("chart") or {}).get("result")
    if not result:
        err = (data.get("chart") or {}).get("error")
        raise YahooFinanceError(f"No chart data for {yahoo_symbol}: {err}")
    r0 = result[0]
    timestamps = r0.get("timestamp") or []
    quote = (r0.get("indicators") or {}).get("quote", [{}])[0]
    closes = quote.get("close") or []
    opens = quote.get("open") or []
    highs = quote.get("high") or []
    lows = quote.get("low") or []

    bars = []
    for i, t in enumerate(timestamps):
        close = closes[i] if i < len(closes) else None
        if close is None:
            continue
        day = datetime.fromtimestamp(t, tz=timezone.utc).date().isoformat()
        bars.append({
            "date": day,
            "open": opens[i], "high": highs[i], "low": lows[i], "close": close,
        })
    if not bars:
        raise YahooFinanceError(f"Empty daily series for {yahoo_symbol}.")
    return bars


def _merge_bars(existing: list, fresh: list) -> list:
    """Union by date, fresh values win on overlap, sorted ascending --
    never truncated, only ever grows. Same shape as the old Alpha Vantage
    cache this module replaces."""
    by_date = {b["date"]: b for b in existing}
    for b in fresh:
        by_date[b["date"]] = b
    return [by_date[d] for d in sorted(by_date)]


async def equity_bars(db, ticker: str) -> list:
    """Accumulated real daily OHLC history for an arbitrary US equity
    ticker (e.g. AAPL) -- same accumulate-forever Mongo cache as
    daily_bars(), just not restricted to the two index symbols. Yahoo
    tickers for US equities are the plain ticker itself, no mapping
    needed the way the indices need ^NDX/^GSPC. Callers are expected to
    validate the ticker against their own known-good list first (see
    relative_strength_groups.py) -- this function itself will happily
    ask Yahoo for anything and surface whatever it says."""
    ticker = ticker.strip().upper()
    today = datetime.now(timezone.utc).date().isoformat()
    doc = await db[CACHE_COLLECTION].find_one({"symbol": ticker})
    if doc and doc.get("last_fetched_date") == today:
        return doc["bars"]

    # NOT "max" -- verified live (2026-08-05): Yahoo silently downsamples
    # interval=1d to ~monthly spacing once the range spans multiple
    # decades (AAPL: 168 bars for range=max vs a real 5031 for range=20y,
    # over the same calendar span). 20y matches the same window
    # relative_strength_routes.py's YEARS_BACK uses for NSE symbols.
    fresh = await _fetch_daily(ticker, range_="20y")
    merged = _merge_bars(doc["bars"] if doc else [], fresh)
    await db[CACHE_COLLECTION].update_one(
        {"symbol": ticker},
        {"$set": {"symbol": ticker, "last_fetched_date": today, "bars": merged}},
        upsert=True,
    )
    return merged


async def quote_snapshot(yahoo_symbol: str) -> dict:
    """{"last", "previous_close", "change_pct"} straight off Yahoo's chart
    endpoint's own `meta` block — no historical accumulation, just the
    live-ish read, for callers that only need "where is it right now" (the
    Market Dashboard's Global Indices card) rather than a chartable
    series. Raises YahooFinanceError (never fabricates) if the meta block
    doesn't carry a live price."""
    try:
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.get(
                f"{BASE_URL}/{yahoo_symbol}",
                params={"interval": "1d", "range": "5d"},
                headers={"User-Agent": USER_AGENT},
            )
        r.raise_for_status()
        data = r.json()
    except httpx.HTTPError as e:
        raise YahooFinanceError(f"Yahoo Finance request failed: {e}") from e

    result = (data.get("chart") or {}).get("result")
    if not result:
        err = (data.get("chart") or {}).get("error")
        raise YahooFinanceError(f"No chart data for {yahoo_symbol}: {err}")
    meta = result[0].get("meta") or {}
    last = meta.get("regularMarketPrice")
    prev = meta.get("chartPreviousClose") or meta.get("previousClose")
    if last is None or prev is None:
        raise YahooFinanceError(f"Incomplete quote meta for {yahoo_symbol}.")
    return {
        "last": last,
        "previous_close": prev,
        "change_pct": round(((last - prev) / prev) * 100.0, 2) if prev else None,
    }


async def daily_bars(db, symbol_key: str, symbol_map: dict = None) -> list:
    """Accumulated real daily OHLC history for a symbol in `symbol_map`
    (defaults to US_INDEX_SYMBOLS — NDX/SPX; pass COMMODITY_SYMBOLS for
    XAUUSD/GC=F). At most one Yahoo call per symbol per real calendar day
    -- every other call today comes straight out of Mongo. Same
    CACHE_COLLECTION for every symbol_map — keys (NDX/SPX vs XAUUSD) don't
    collide since they're distinct strings."""
    symbol_map = symbol_map or US_INDEX_SYMBOLS
    symbol_key = symbol_key.strip().upper()
    if symbol_key not in symbol_map:
        raise YahooFinanceError(f"Unknown symbol {symbol_key}.")

    today = datetime.now(timezone.utc).date().isoformat()
    doc = await db[CACHE_COLLECTION].find_one({"symbol": symbol_key})
    if doc and doc.get("last_fetched_date") == today:
        return doc["bars"]

    yahoo_symbol = symbol_map[symbol_key]["yahoo"]
    fresh = await _fetch_daily(yahoo_symbol)
    merged = _merge_bars(doc["bars"] if doc else [], fresh)
    await db[CACHE_COLLECTION].update_one(
        {"symbol": symbol_key},
        {"$set": {"symbol": symbol_key, "last_fetched_date": today, "bars": merged}},
        upsert=True,
    )
    return merged
