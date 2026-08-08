"""Alpaca Market Data client — the live/intraday data source for the US
Indices segment of the P&F and Renko charting platforms.

Daily/weekly/monthly history for US Indices still comes from
yahoo_finance_client.py's real index tickers (^NDX, ^GSPC) — that's a
deliberate, already-documented choice (see that module's own docstring)
and this client doesn't touch it. What Yahoo's free endpoint cannot do at
all is real intraday history, and Alpaca can: this module fills exactly
that gap, nothing more.

The tradeoff this introduces, and why it's disclosed rather than hidden:
Alpaca has no index-level product (^NDX/^GSPC aren't tradable securities,
confirmed live — the API 400s on them), only real securities. So intraday
bars come from each index's most liquid tracking ETF (QQQ for Nasdaq 100,
SPY for S&P 500) — the same proxy relationship this platform already uses
for Gold (COMEX futures standing in for spot XAUUSD, see
yahoo_finance_client.py's COMMODITY_SYMBOLS). The daily chart and an
intraday chart of "the same" instrument are therefore reading two
related-but-distinct instruments; callers must surface that, the same way
the Gold segment already discloses its own proxy in the UI.

Feed is IEX (free tier) — real trades, one exchange's worth of the tape,
not the full consolidated SIP feed (which needs a paid subscription).
Confirmed live: IEX serves genuine 1-minute-resolution intraday bars with
real volume, going back years, with no rate-limit trouble observed at
this call volume.
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import httpx

BASE_URL = "https://data.alpaca.markets/v2"
FEED = "iex"

# The Render/K8s env historically used lowercase, inconsistently-cased
# names for these two (alpaca_Key / alpaca_Secret) before being
# standardized to match every other credential in this codebase
# (RAZORPAY_KEY_ID, DEFINEDGE_API_TOKEN, ...). Set these exact names on
# Render — the old names are not read as a fallback.
ALPACA_API_KEY_ID = os.environ.get("ALPACA_API_KEY_ID")
ALPACA_API_SECRET_KEY = os.environ.get("ALPACA_API_SECRET_KEY")

NY_TZ = ZoneInfo("America/New_York")

# index selector key (matches yahoo_finance_client.US_INDEX_SYMBOLS) ->
# tracking-ETF ticker Alpaca actually serves.
US_INDEX_PROXY = {
    "NDX": {"ticker": "QQQ", "label": "Nasdaq 100 (via QQQ)"},
    "SPX": {"ticker": "SPY", "label": "S&P 500 (via SPY)"},
}

# This platform's interval keys -> Alpaca's timeframe query values.
TIMEFRAME_MAP = {
    "1": "1Min", "5": "5Min", "15": "15Min", "30": "30Min", "60": "1Hour",
}


class AlpacaError(Exception):
    """Upstream/config problems — safe to show a caller."""


def _auth_headers() -> dict:
    if not ALPACA_API_KEY_ID or not ALPACA_API_SECRET_KEY:
        raise AlpacaError("Live US intraday data is not configured.")
    return {"APCA-API-KEY-ID": ALPACA_API_KEY_ID, "APCA-API-SECRET-KEY": ALPACA_API_SECRET_KEY}


async def intraday_bars(symbol_key: str, interval: str, days: int = 30) -> list:
    """Real intraday OHLC bars for a US index's tracking ETF, already at
    the requested granularity — Alpaca aggregates server-side, unlike the
    Binance client elsewhere in this codebase which fetches 1-minute bars
    and rolls them up locally.

    Labelled in US/Eastern local time (this segment's own exchange
    session), the same convention NSE bars use IST — a UTC or IST label on
    a 9:30am ET open would read as meaningless to the person looking at
    it. `ts` is DDMMYYYYHHMM to match this platform's existing intraday
    bar shape (see pnf_chart.py's aggregate_minutes / _bar_label)."""
    symbol_key = symbol_key.strip().upper()
    proxy = US_INDEX_PROXY.get(symbol_key)
    if not proxy:
        raise AlpacaError(f"No US index proxy configured for {symbol_key}.")
    timeframe = TIMEFRAME_MAP.get(interval)
    if not timeframe:
        raise AlpacaError(f"Unsupported intraday interval {interval!r}.")

    now_utc = datetime.now(ZoneInfo("UTC"))
    start = (now_utc - timedelta(days=days)).isoformat()

    try:
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.get(
                f"{BASE_URL}/stocks/{proxy['ticker']}/bars",
                params={"timeframe": timeframe, "start": start, "limit": 10000, "feed": FEED,
                        "adjustment": "raw"},
                headers=_auth_headers(),
            )
        r.raise_for_status()
        data = r.json()
    except httpx.HTTPStatusError as e:
        raise AlpacaError(f"Alpaca request failed ({e.response.status_code}): {e.response.text[:200]}") from e
    except httpx.HTTPError as e:
        raise AlpacaError(f"Alpaca request failed: {e}") from e

    raw_bars = data.get("bars") or []
    if not raw_bars:
        raise AlpacaError(f"No intraday bars returned for {proxy['ticker']}.")

    bars = []
    for b in raw_bars:
        # Alpaca's "t" is RFC3339 UTC ("...Z") — parse then convert to the
        # exchange's own local wall-clock time for the label.
        ts_utc = datetime.fromisoformat(b["t"].replace("Z", "+00:00"))
        ts_ny = ts_utc.astimezone(NY_TZ)
        bars.append({
            "ts": ts_ny.strftime("%d%m%Y%H%M"),
            "open": b["o"], "high": b["h"], "low": b["l"], "close": b["c"],
        })
    return bars
