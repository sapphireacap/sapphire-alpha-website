"""
Lumen Verify -- cross-source verification for price-critical fields
(Phase 3).

**Design deviation from the original spec, disclosed here rather than
silently made**: the spec compares against NSE's direct quote-equity API.
Tested live from this environment: `nseindia.com/api/quote-equity` returns
403, and so does `nseindia.com/` itself (the homepage a cookie-based
workaround would need to warm up against first) -- while OTHER NSE API
paths already used elsewhere in this codebase (`ipo_routes.py`'s
`public-past-issues`) return 200 with the exact same plain User-Agent
header. That's a specific block on quote-equity/the homepage, not a
blanket NSE block, and not fixable by better request code -- there's no
session cookie this environment can obtain.

Adapted instead to compare Definedge's own daily close (already ingested,
`stock_terminal_ingestion.py`) against Screener.in's own "Current Price"
(already scraped, `stock_terminal_fundamentals.py`'s `screener_price`
field) -- two genuinely independent pipelines (a live broker feed vs. a
third-party aggregator's own scrape). Still catches real staleness or
pipeline bugs even though both ultimately trace back to exchange data,
which is the actual point of this membrane (per the spec: "the system
never displays a number it cannot attribute to a verified source").
"""
CONFLICT_THRESHOLD_PCT = 1.5


async def verify_price(db, symbol: str) -> dict:
    """{"status": "VERIFIED"|"SINGLE_SOURCE"|"CONFLICT"|"NO_DATA",
    "definedge_price", "screener_price", "delta_pct", "as_of"}. On a
    CONFLICT, both values are returned rather than the membrane silently
    picking one -- the caller renders both, per the spec's own design."""
    latest_bar = await db.stock_prices_daily.find_one(
        {"symbol": symbol}, sort=[("date", -1)], projection={"_id": 0, "close": 1, "date": 1}
    )
    fundamentals = await db.stock_fundamentals.find_one({"symbol": symbol}, {"_id": 0, "screener_price": 1})

    definedge_price = latest_bar["close"] if latest_bar else None
    screener_price = fundamentals.get("screener_price") if fundamentals else None

    if definedge_price is None and screener_price is None:
        return {"status": "NO_DATA", "definedge_price": None, "screener_price": None, "delta_pct": None, "as_of": None}
    if definedge_price is None or screener_price is None:
        return {
            "status": "SINGLE_SOURCE", "definedge_price": definedge_price, "screener_price": screener_price,
            "delta_pct": None, "as_of": latest_bar.get("date") if latest_bar else None,
        }

    delta_pct = abs(definedge_price - screener_price) / screener_price * 100 if screener_price else None
    status = "CONFLICT" if (delta_pct is not None and delta_pct > CONFLICT_THRESHOLD_PCT) else "VERIFIED"
    return {
        "status": status, "definedge_price": definedge_price, "screener_price": screener_price,
        "delta_pct": delta_pct, "as_of": latest_bar.get("date") if latest_bar else None,
    }
