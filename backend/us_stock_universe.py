"""
US stock symbol universe for Peter Tingle's US market toggle -- S&P 500
constituents, the closest US equivalent to the Nifty 500 universe already
used on the India side (stock_terminal_ingestion.py).

Universe source: a public, community-maintained constituents CSV
(github.com/datasets/s-and-p-500-companies) -- same "public CSV, no key"
shape as NIFTY500_CSV_URL, just a US source. No live NSE-style official
archive exists for S&P 500 membership without a paid feed, so this is the
standard free substitute; it lags official index-committee changes by at
most a few days.

Price history for any symbol in this universe is NOT ingested here --
yahoo_finance_client.equity_bars() already fetches-and-caches per ticker
on demand (see peter_tingle_routes.py), so this module only needs to keep
the searchable symbol/company-name list current.
"""
import csv
import io
import logging

import httpx

logger = logging.getLogger(__name__)

SP500_CSV_URL = "https://raw.githubusercontent.com/datasets/s-and-p-500-companies/main/data/constituents.csv"


async def _fetch_universe() -> list:
    async with httpx.AsyncClient(timeout=20) as c:
        r = await c.get(SP500_CSV_URL)
    r.raise_for_status()
    reader = csv.DictReader(io.StringIO(r.text))
    rows = []
    for row in reader:
        symbol = (row.get("Symbol") or "").strip().upper()
        if not symbol:
            continue
        rows.append({
            "symbol": symbol,
            "company_name": (row.get("Security") or "").strip(),
            "sector": (row.get("GICS Sector") or "").strip() or None,
        })
    return rows


async def sync_universe(db) -> dict:
    """Upserts the current S&P 500 list into us_stock_symbol_master. Cheap
    enough (~500 rows) to run as a single replace pass rather than diffing --
    stale symbols (dropped from the index) are left in place rather than
    deleted, same "never silently lose history" stance stock_terminal takes
    with its own universe."""
    rows = await _fetch_universe()
    updated = 0
    for row in rows:
        await db.us_stock_symbol_master.update_one({"symbol": row["symbol"]}, {"$set": row}, upsert=True)
        updated += 1
    return {"updated": updated, "total": len(rows)}
