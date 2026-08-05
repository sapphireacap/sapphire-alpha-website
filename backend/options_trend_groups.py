"""Liquid F&O stock universe for the Options Trend Scanner — NSE's own
public "market lots" CSV, which lists every symbol currently permitted for
trading in the F&O segment (index rows first, then a
"Derivatives on Individual Securities" marker row, then one row per stock
with its current lot size). A stock's presence here with a real lot size IS
the liquidity/eligibility filter the video's "Options Liquid Futures" group
implements on Definedge's own platform — there's no separate "how liquid"
score published, eligibility to trade F&O at all is the gate NSE itself
applies.

Verified live, 2026-08-05: HTTP 200, ~207 individual-security rows under
the marker row, 5 index rows above it (NIFTY, BANKNIFTY, FINNIFTY,
MIDCPNIFTY, NIFTYNXT50) — same unofficial-but-verified-live pattern already
relied on for Nifty 50/500 (breadth_groups.py) and IPO GMP.
"""
from __future__ import annotations

import csv
import io
from datetime import datetime, timezone, timedelta

import httpx

IST = timezone(timedelta(hours=5, minutes=30))

BROWSER_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)

MKTLOTS_URL = "https://nsearchives.nseindia.com/content/fo/fo_mktlots.csv"

# The marker row's own first column, verbatim — everything from the row
# after this onward is an individual stock; everything before it (NIFTY,
# BANKNIFTY, FINNIFTY, MIDCPNIFTY, NIFTYNXT50) is an index, which the
# Options Trend Scanner doesn't cover (that's Index Vector's job).
_STOCK_SECTION_MARKER = "Derivatives on Individual Securities"

_cache = None  # (date_str, list[str]) — same per-day TTL as breadth_groups.py


class OptionsTrendGroupError(Exception):
    pass


async def fetch_fo_stock_universe() -> list:
    """Plain symbol list for every stock currently listed in the F&O
    segment, cached once per day. Raises OptionsTrendGroupError rather than
    returning something partial/wrong if NSE's file 404s, changes shape, or
    the stock section marker row isn't found — never silently falls back to
    a guessed or stale list."""
    global _cache
    today = datetime.now(IST).strftime("%Y-%m-%d")
    if _cache and _cache[0] == today:
        return _cache[1]

    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.get(MKTLOTS_URL, headers={"User-Agent": BROWSER_USER_AGENT})
    if r.status_code != 200:
        raise OptionsTrendGroupError(f"F&O market-lots list fetch failed (HTTP {r.status_code}).")

    rows = list(csv.reader(io.StringIO(r.text)))
    marker_idx = next((i for i, row in enumerate(rows) if row and row[0].strip() == _STOCK_SECTION_MARKER), None)
    if marker_idx is None:
        raise OptionsTrendGroupError("F&O market-lots list came back without its expected stock-section marker row.")

    symbols = []
    for row in rows[marker_idx + 1:]:
        if len(row) < 2:
            continue
        symbol = row[1].strip()
        if symbol:
            symbols.append(symbol)
    if not symbols:
        raise OptionsTrendGroupError("F&O market-lots list's stock section came back empty.")

    _cache = (today, symbols)
    return symbols
