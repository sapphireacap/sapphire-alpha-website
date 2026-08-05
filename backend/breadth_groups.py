"""Symbol universes for the X-Percent Breadth indicator — NSE's own public
index-constituent CSVs, same unofficial-but-verified-live pattern quant_lab.py
already relies on for its Nifty 500 Sharpe dashboard (see its
_fetch_nifty500_list()). Generalized here to also cover Nifty 50, since
Breadth needs both (Definedge's own Breadth tool offers both as Group
options)."""
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

GROUPS = {
    "nifty-50": {
        "label": "Nifty 50",
        "csv_url": "https://nsearchives.nseindia.com/content/indices/ind_nifty50list.csv",
    },
    "nifty-500": {
        "label": "Nifty 500",
        "csv_url": "https://nsearchives.nseindia.com/content/indices/ind_nifty500list.csv",
    },
}

_cache: dict = {}  # group_key -> (date_str, list[str]) — same per-day TTL as quant_lab.py's _nifty500_cache


class BreadthGroupError(Exception):
    pass


async def fetch_group_symbols(group_key: str) -> list:
    """Plain symbol list (no company name/industry — Breadth only needs
    the ticker to pull price history) for one group, cached once per day.
    Raises BreadthGroupError rather than returning something partial/wrong
    if NSE's archive path 404s or changes shape without notice — same
    fragility caveat as every other unofficial NSE endpoint already relied
    on elsewhere in this codebase."""
    if group_key not in GROUPS:
        raise BreadthGroupError(f"Unknown breadth group '{group_key}'. Must be one of {', '.join(GROUPS)}.")

    today = datetime.now(IST).strftime("%Y-%m-%d")
    cached = _cache.get(group_key)
    if cached and cached[0] == today:
        return cached[1]

    url = GROUPS[group_key]["csv_url"]
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.get(url, headers={"User-Agent": BROWSER_USER_AGENT})
    if r.status_code != 200:
        raise BreadthGroupError(f"{GROUPS[group_key]['label']} constituent list fetch failed (HTTP {r.status_code}).")

    symbols = []
    for row in csv.DictReader(io.StringIO(r.text)):
        symbol = (row.get("Symbol") or "").strip()
        if symbol:
            symbols.append(symbol)
    if not symbols:
        raise BreadthGroupError(f"{GROUPS[group_key]['label']} constituent list came back empty.")

    _cache[group_key] = (today, symbols)
    return symbols
