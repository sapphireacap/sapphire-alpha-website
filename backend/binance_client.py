"""Binance public market-data client for the Crypto segment of the P&F
platform. Binance's REST API is public, keyless, and already produces real
native candles at every granularity the platform's interval selector
offers (1m/5m/15m/30m/1h, plus real exchange-produced 1d/1w/1M candles) --
no client-side resampling needed the way the US index proxies need (see
alpha_vantage_client.py), since Binance's own weekly/monthly klines are
real exchange data, not a local rollup of daily bars.

Timestamps are UTC throughout -- Binance's own convention for a 24/7
global market with no single home session, unlike the IST convention the
rest of this platform uses for NSE segments.
"""
from __future__ import annotations

from datetime import datetime, timezone

import httpx

BASE_URL = "https://api.binance.com/api/v3/klines"
MAX_LIMIT = 1000  # Binance's own hard per-request cap

# Same six pairs the free Crypto Markets dashboard already covers
# (frontend/src/pages/alphaterminal/CryptoDashboard.jsx) -- kept identical
# so a symbol that resolves on one page resolves on the other, rather than
# maintaining two lists that can silently drift apart.
CRYPTO_SYMBOLS = {
    "BTCUSDT": "Bitcoin",
    "ETHUSDT": "Ethereum",
    "SOLUSDT": "Solana",
    "BNBUSDT": "BNB",
    "XRPUSDT": "XRP",
    "DOGEUSDT": "Dogecoin",
}

INTERVAL_MAP = {
    "1": "1m", "5": "5m", "15": "15m", "30": "30m", "60": "1h",
    "daily": "1d", "weekly": "1w", "monthly": "1M",
}


class BinanceError(Exception):
    """Upstream/parameter problems -- safe to show a caller."""


async def bars(symbol: str, interval: str, limit: int = MAX_LIMIT) -> list:
    """Native OHLC bars straight off Binance at the requested granularity.

    Returns pnf_chart-ready dicts: a `date` key (ISO, UTC) for
    daily/weekly/monthly, a `ts` key (Definedge's ddmmyyyyHHMM shape, UTC)
    for intraday -- the two bar shapes pnf_chart._bar_label already
    understands, so nothing in the P&F engine itself needed to change to
    support this segment."""
    symbol = symbol.strip().upper()
    if symbol not in CRYPTO_SYMBOLS:
        raise BinanceError(f"Unknown crypto symbol {symbol}.")
    bn_interval = INTERVAL_MAP.get(interval)
    if bn_interval is None:
        raise BinanceError(f"interval must be one of {', '.join(INTERVAL_MAP)}")

    try:
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.get(BASE_URL, params={
                "symbol": symbol, "interval": bn_interval, "limit": min(limit, MAX_LIMIT),
            })
        r.raise_for_status()
        raw = r.json()
    except httpx.HTTPError as e:
        raise BinanceError(f"Binance request failed: {e}") from e
    if not isinstance(raw, list):
        raise BinanceError(f"Unexpected Binance response for {symbol}.")

    out = []
    for k in raw:
        open_time = datetime.fromtimestamp(k[0] / 1000, tz=timezone.utc)
        row = {"open": float(k[1]), "high": float(k[2]), "low": float(k[3]), "close": float(k[4])}
        if interval in ("daily", "weekly", "monthly"):
            row["date"] = open_time.date().isoformat()
        else:
            row["ts"] = open_time.strftime("%d%m%Y%H%M")
        out.append(row)
    return out
