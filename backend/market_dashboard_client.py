"""NSE public data fetchers for the Market Dashboard — unofficial endpoints,
same fragility caveat as every other unofficial NSE integration already
relied on in this codebase (breadth_groups.py, options_trend_groups.py,
gmp_scraper.py): no SLA, can change shape without notice, ToS restricts
automated access. Verified live, 2026-08-06: all three work with just a
real browser User-Agent + Referer header — no cookie/session handshake
against the homepage needed first (confirmed twice in a row), which is
less fragile than the cookie-jar dance some NSE integrations need.

Deliberately three separate small functions, not one "fetch everything"
call, so market_dashboard_routes.py can let one source fail without
blocking the other two (see that module's docstring for why that's
load-bearing here).
"""
from __future__ import annotations

import httpx

BROWSER_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)
NSE_HEADERS = {
    "User-Agent": BROWSER_USER_AGENT,
    "Accept": "application/json",
    "Referer": "https://www.nseindia.com/",
}


class MarketDashboardError(Exception):
    """Upstream (NSE) problems — safe to show a caller."""


async def fetch_all_indices() -> dict:
    """Every NSE index (broad + sectoral) in one call — level, change%,
    52-week high/low, PE/PB/DY, and each index's own constituent
    advances/declines/unchanged — plus root-level advances/declines/
    unchanged for the WHOLE market (not just one index's constituents).
    Verified live, 2026-08-06: 139 index rows, root counts
    3699/5746/125. This one call backs the index-levels, sectoral
    heatmap, India VIX, and market-wide advance/decline cards."""
    try:
        async with httpx.AsyncClient(timeout=20) as c:
            r = await c.get("https://www.nseindia.com/api/allIndices", headers=NSE_HEADERS)
    except httpx.HTTPError as e:
        raise MarketDashboardError(f"NSE allIndices request failed: {e}") from e
    if r.status_code != 200:
        raise MarketDashboardError(f"NSE allIndices failed (HTTP {r.status_code}).")
    try:
        return r.json()
    except ValueError as e:
        raise MarketDashboardError(f"NSE allIndices returned non-JSON: {e}") from e


async def fetch_fii_dii() -> list:
    """[{category: "FII/FPI"|"DII", date, buyValue, sellValue, netValue},
    ...] — today's (or the most recently published) provisional cash-
    market FII/DII activity. Values are strings as NSE returns them (e.g.
    "19723.68") — caller's job to float() them, not guessed/parsed here."""
    try:
        async with httpx.AsyncClient(timeout=20) as c:
            r = await c.get("https://www.nseindia.com/api/fiidiiTradeReact", headers=NSE_HEADERS)
    except httpx.HTTPError as e:
        raise MarketDashboardError(f"NSE fiidiiTradeReact request failed: {e}") from e
    if r.status_code != 200:
        raise MarketDashboardError(f"NSE fiidiiTradeReact failed (HTTP {r.status_code}).")
    try:
        return r.json()
    except ValueError as e:
        raise MarketDashboardError(f"NSE fiidiiTradeReact returned non-JSON: {e}") from e


async def fetch_52week_hilo() -> dict:
    """{"high": N, "low": N} — count of NSE-listed stocks currently at a
    new 52-week high / low. EOD-driven (doesn't meaningfully change
    intraday), verified live, 2026-08-06."""
    try:
        async with httpx.AsyncClient(timeout=20) as c:
            r = await c.get("https://www.nseindia.com/api/live-analysis-52weekhighstock", headers=NSE_HEADERS)
    except httpx.HTTPError as e:
        raise MarketDashboardError(f"NSE 52-week hi/lo request failed: {e}") from e
    if r.status_code != 200:
        raise MarketDashboardError(f"NSE 52-week hi/lo failed (HTTP {r.status_code}).")
    try:
        return r.json()
    except ValueError as e:
        raise MarketDashboardError(f"NSE 52-week hi/lo returned non-JSON: {e}") from e
