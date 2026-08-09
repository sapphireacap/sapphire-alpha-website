"""
US equity fundamentals for Peter Tingle -- Yahoo Finance's unofficial
quoteSummary endpoint (same free/keyless-of-an-API-key, browser-User-Agent
approach yahoo_finance_client.py already uses for the chart endpoint). No
Screener.in equivalent exists for US names, and no paid fundamentals API
is configured on this deployment, so this is the only real
(non-estimated) source available.

Unlike the chart endpoint, quoteSummary now hard-requires Yahoo's
cookie+crumb handshake -- a bare request 401s (verified live, 2026-08-09).
The handshake itself is still free and keyless: GET fc.yahoo.com for a
session cookie, then GET /v1/test/getcrumb with that cookie for a crumb
token, then send both on every quoteSummary call. The crumb is cached
process-wide (module-level, not per-ticker) and only re-fetched if a
request comes back 401 with it -- one handshake covers every ticker for
the life of the process, not one per symbol.

Every field read here is still defensive (`.get` chains, never raises for
a missing field) so a partial or failed fetch degrades to NA rule rows
downstream (peter_tingle.scan_us_fundamental_red_flags), never a
fabricated number.
"""
from __future__ import annotations

from datetime import datetime, timezone

import httpx

BASE_URL = "https://query1.finance.yahoo.com/v10/finance/quoteSummary"
CRUMB_URL = "https://query2.finance.yahoo.com/v1/test/getcrumb"
COOKIE_URL = "https://fc.yahoo.com"
MODULES = "financialData,defaultKeyStatistics"
CACHE_COLLECTION = "us_stock_fundamentals_cache"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

# Process-wide crumb/cookie cache -- one handshake serves every ticker.
_crumb_cache: dict = {"crumb": None, "cookies": None}


async def _get_crumb(force: bool = False) -> tuple[str, httpx.Cookies]:
    if not force and _crumb_cache["crumb"]:
        return _crumb_cache["crumb"], _crumb_cache["cookies"]

    async with httpx.AsyncClient(timeout=15, headers={"User-Agent": USER_AGENT}) as c:
        await c.get(COOKIE_URL)  # sets the session cookie Yahoo expects; 404 body itself is irrelevant
        r = await c.get(CRUMB_URL, cookies=c.cookies)
        r.raise_for_status()
        crumb = r.text.strip()
        cookies = c.cookies

    _crumb_cache["crumb"], _crumb_cache["cookies"] = crumb, cookies
    return crumb, cookies


class UsFundamentalsError(Exception):
    """Upstream problems -- safe to show a caller."""


def _raw(block: dict, key: str):
    v = (block or {}).get(key)
    return v.get("raw") if isinstance(v, dict) else v


async def _fetch_live(ticker: str) -> dict:
    try:
        crumb, cookies = await _get_crumb()
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.get(
                f"{BASE_URL}/{ticker}",
                params={"modules": MODULES, "crumb": crumb},
                headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
                cookies=cookies,
            )
            if r.status_code == 401:
                # Crumb/cookie can go stale independent of process uptime --
                # one forced re-handshake and retry before giving up.
                crumb, cookies = await _get_crumb(force=True)
                r = await c.get(
                    f"{BASE_URL}/{ticker}",
                    params={"modules": MODULES, "crumb": crumb},
                    headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
                    cookies=cookies,
                )
        r.raise_for_status()
        data = r.json()
    except httpx.HTTPError as e:
        raise UsFundamentalsError(f"Yahoo quoteSummary request failed: {e}") from e

    result = ((data.get("quoteSummary") or {}).get("result")) or []
    if not result:
        err = (data.get("quoteSummary") or {}).get("error")
        raise UsFundamentalsError(f"No fundamentals for {ticker}: {err}")

    fin = result[0].get("financialData") or {}
    stats = result[0].get("defaultKeyStatistics") or {}

    current_price = _raw(fin, "currentPrice")
    target_mean = _raw(fin, "targetMeanPrice")
    target_upside_pct = (
        (target_mean / current_price - 1) * 100
        if current_price and target_mean else None
    )
    profit_margin = _raw(fin, "profitMargins")

    return {
        "debt_to_equity": _raw(fin, "debtToEquity"),
        "profit_margin_pct": profit_margin * 100 if profit_margin is not None else None,
        "current_ratio": _raw(fin, "currentRatio"),
        "short_pct_float": (lambda v: v * 100 if v is not None else None)(_raw(stats, "shortPercentOfFloat")),
        "target_upside_pct": target_upside_pct,
    }


async def fetch_fundamentals(db, ticker: str) -> dict | None:
    """At most one Yahoo call per ticker per real calendar day -- same
    accumulate-and-reuse cache shape as yahoo_finance_client.equity_bars().
    Returns None (not a raised error) on total failure with nothing cached
    yet, so the route can hand back NA rows instead of a 502."""
    ticker = ticker.strip().upper()
    today = datetime.now(timezone.utc).date().isoformat()
    doc = await db[CACHE_COLLECTION].find_one({"symbol": ticker})
    if doc and doc.get("last_fetched_date") == today:
        return doc["fundamentals"]

    try:
        fresh = await _fetch_live(ticker)
    except UsFundamentalsError:
        return doc["fundamentals"] if doc else None

    await db[CACHE_COLLECTION].update_one(
        {"symbol": ticker},
        {"$set": {"symbol": ticker, "last_fetched_date": today, "fundamentals": fresh}},
        upsert=True,
    )
    return fresh
