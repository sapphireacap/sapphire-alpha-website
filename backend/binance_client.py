"""Static config for the Crypto segment of the P&F platform.

OHLC fetching for this segment happens CLIENT-SIDE (see the frontend's
PnfChart.jsx), not here. Binance's public API is CORS-open for browsers,
but geo-blocks requests that originate from this backend's own server
(verified live, 2026-08-04: an identical klines request works fine from a
real browser and 502s when made from Render's US-hosted box). So the
browser fetches the raw bars itself -- exactly like the existing Crypto
Markets dashboard already does -- and this backend's only job for Crypto
is running the P&F engine over bars the browser hands it; see
pnf_routes.py's POST /pnf/chart/crypto.
"""
from __future__ import annotations

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

# Binance's own per-request kline cap, reused here as the ceiling on how
# many client-submitted bars POST /pnf/chart/crypto will accept.
MAX_BARS = 1000
