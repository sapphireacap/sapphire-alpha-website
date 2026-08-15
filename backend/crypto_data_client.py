"""Crypto OHLC client — SERVER-SIDE crypto market data.

Why this exists alongside binance_client.py: that module deliberately
does no fetching at all, because Binance geo-blocks this backend's own
Render box (verified live, 2026-08-04 — an identical klines request works
from a real browser and 502s from Render). The existing Crypto pages
therefore fetch Binance straight from the client.

That arrangement cannot serve the cron-driven modules. Market Breadth has
to walk a 30-symbol universe on a schedule and cache the result; there is
no browser in that loop. So this module adds a real server-side path with
an explicit source chain, tried in order:

    1. Binance      api.binance.com          — richest history (1000
                                               daily bars/request, back
                                               to 2017, paginates via
                                               startTime). Used when it
                                               works; expected to fail
                                               from Render.
    2. Coinbase     api.exchange.coinbase.com — US-hosted and not
                                               geo-blocked from Render.
                                               300 candles/request, so
                                               paginated backwards with
                                               start/end.
    3. Kraken       api.kraken.com            — last resort. Serves at
                                               most ~720 recent daily
                                               candles with no way to
                                               page further back, which
                                               is thinner than the P&F
                                               engines want; accepted
                                               only because a short real
                                               series beats no series.

All three were verified live from this machine on 2026-08-16, and all 30
universe symbols below resolved on both Binance and Coinbase.

Whichever source answers is recorded on the cached document as `source`,
so the UI can name the real origin rather than implying one. Bars are
normalized to this codebase's usual {date, open, high, low, close} shape
regardless of which upstream produced them — the three have genuinely
different array orders (see each parser), a real trap worth reading
before touching them.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

import httpx

logger = logging.getLogger(__name__)

CACHE_COLLECTION = "crypto_daily_cache"
HISTORY_DAYS = 5 * 365


class CryptoDataError(Exception):
    """Upstream problems -- safe to show a caller."""


# Normalized symbol -> {label, binance, coinbase, kraken}. Symbols are
# Binance-style (BTCUSDT) to stay identical to the pairs the existing
# CryptoDashboard/binance_client.py already use, so a symbol that
# resolves on one crypto page resolves on all of them.
def _pair(base: str, label: str, group: str) -> tuple:
    return base + "USDT", {
        "label": label, "group": group,
        "binance": base + "USDT",
        "coinbase": base + "-USD",
        # Kraken renames BTC to XBT and prefixes several legacy assets.
        "kraken": ("XBT" if base == "BTC" else base) + "USD",
    }


CRYPTO_SYMBOLS = dict([
    _pair("BTC", "Bitcoin", "Majors"),
    _pair("ETH", "Ethereum", "Majors"),
    _pair("SOL", "Solana", "Majors"),
    _pair("BNB", "BNB", "Majors"),
    _pair("XRP", "XRP", "Majors"),
    _pair("DOGE", "Dogecoin", "Majors"),
    _pair("ADA", "Cardano", "Layer 1"),
    _pair("AVAX", "Avalanche", "Layer 1"),
    _pair("DOT", "Polkadot", "Layer 1"),
    _pair("ATOM", "Cosmos", "Layer 1"),
    _pair("NEAR", "NEAR Protocol", "Layer 1"),
    _pair("APT", "Aptos", "Layer 1"),
    _pair("SUI", "Sui", "Layer 1"),
    _pair("ALGO", "Algorand", "Layer 1"),
    _pair("ICP", "Internet Computer", "Layer 1"),
    _pair("HBAR", "Hedera", "Layer 1"),
    _pair("VET", "VeChain", "Layer 1"),
    _pair("ETC", "Ethereum Classic", "Layer 1"),
    _pair("MATIC", "Polygon", "Layer 2"),
    _pair("ARB", "Arbitrum", "Layer 2"),
    _pair("OP", "Optimism", "Layer 2"),
    _pair("LINK", "Chainlink", "DeFi"),
    _pair("UNI", "Uniswap", "DeFi"),
    _pair("AAVE", "Aave", "DeFi"),
    _pair("INJ", "Injective", "DeFi"),
    _pair("TIA", "Celestia", "DeFi"),
    _pair("FIL", "Filecoin", "Infrastructure"),
    _pair("LTC", "Litecoin", "Payments"),
    _pair("BCH", "Bitcoin Cash", "Payments"),
    _pair("XLM", "Stellar", "Payments"),
])

GROUPS = ["Majors", "Layer 1", "Layer 2", "DeFi", "Infrastructure", "Payments"]


def group_members(group: str) -> list:
    return [s for s, m in CRYPTO_SYMBOLS.items() if m["group"] == group]


def all_symbols() -> list:
    return list(CRYPTO_SYMBOLS.keys())


def search(query: str = "", limit: int = 30) -> list:
    q = (query or "").strip().upper()
    out = []
    for symbol, meta in CRYPTO_SYMBOLS.items():
        if not q or q in symbol or q in meta["label"].upper():
            out.append({"symbol": symbol, "label": meta["label"], "group": meta["group"]})
        if len(out) >= limit:
            break
    return out


def _iso(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).date().isoformat()


# --------------------------------------------------------------------------
# Source 1 — Binance. klines row: [openTime, open, high, low, close, volume, ...]
# --------------------------------------------------------------------------
async def _from_binance(client: httpx.AsyncClient, meta: dict, days: int) -> list:
    start = int((datetime.now(timezone.utc) - timedelta(days=days)).timestamp() * 1000)
    bars, cursor = [], start
    for _ in range(10):  # 10 x 1000 daily bars comfortably covers HISTORY_DAYS
        r = await client.get(
            "https://api.binance.com/api/v3/klines",
            params={"symbol": meta["binance"], "interval": "1d", "limit": 1000, "startTime": cursor},
        )
        r.raise_for_status()
        rows = r.json()
        if not rows:
            break
        for row in rows:
            bars.append({
                "date": _iso(row[0]), "open": float(row[1]), "high": float(row[2]),
                "low": float(row[3]), "close": float(row[4]),
            })
        if len(rows) < 1000:
            break
        cursor = rows[-1][0] + 86_400_000
    return bars


# --------------------------------------------------------------------------
# Source 2 — Coinbase. candle row: [time, LOW, HIGH, OPEN, close, volume]
# Note the order: low/high precede open. Getting this wrong silently
# produces plausible-looking but wrong OHLC, which the P&F engines would
# happily chart. Verified against live data, 2026-08-16.
# --------------------------------------------------------------------------
async def _from_coinbase(client: httpx.AsyncClient, meta: dict, days: int) -> list:
    end = datetime.now(timezone.utc)
    seen, bars = set(), []
    # 300 candles/request max -> walk backwards in 290-day windows.
    for _ in range(int(days / 290) + 2):
        start = end - timedelta(days=290)
        r = await client.get(
            f"https://api.exchange.coinbase.com/products/{meta['coinbase']}/candles",
            params={
                "granularity": 86400,
                "start": start.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "end": end.strftime("%Y-%m-%dT%H:%M:%SZ"),
            },
        )
        r.raise_for_status()
        rows = r.json()
        if not rows:
            break
        for row in rows:
            date = _iso(int(row[0]) * 1000)
            if date in seen:
                continue
            seen.add(date)
            bars.append({
                "date": date, "open": float(row[3]), "high": float(row[2]),
                "low": float(row[1]), "close": float(row[4]),
            })
        end = start
        await asyncio.sleep(0.15)  # stay well inside Coinbase's public rate limit
    return sorted(bars, key=lambda b: b["date"])


# --------------------------------------------------------------------------
# Source 3 — Kraken. OHLC row: [time, open, high, low, close, vwap, vol, count]
# --------------------------------------------------------------------------
async def _from_kraken(client: httpx.AsyncClient, meta: dict, days: int) -> list:
    r = await client.get(
        "https://api.kraken.com/0/public/OHLC",
        params={"pair": meta["kraken"], "interval": 1440},
    )
    r.raise_for_status()
    payload = r.json()
    if payload.get("error"):
        raise CryptoDataError(f"Kraken: {payload['error']}")
    result = payload.get("result") or {}
    rows = next((v for k, v in result.items() if k != "last"), [])
    return [{
        "date": _iso(int(row[0]) * 1000), "open": float(row[1]), "high": float(row[2]),
        "low": float(row[3]), "close": float(row[4]),
    } for row in rows]


SOURCES = [("binance", _from_binance), ("coinbase", _from_coinbase), ("kraken", _from_kraken)]


async def _fetch_with_fallback(meta: dict, days: int) -> tuple:
    """(bars, source_name). Tries each source in order; a source that
    raises or returns nothing is logged and skipped. Raises only when
    every source has failed — never returns a partial//synthetic series."""
    errors = []
    async with httpx.AsyncClient(timeout=25) as client:
        for name, fn in SOURCES:
            try:
                bars = await fn(client, meta, days)
                if bars:
                    return bars, name
                errors.append(f"{name}: empty series")
            except Exception as e:  # noqa: BLE001 — any upstream failure falls through to the next source
                errors.append(f"{name}: {e}")
                logger.info("Crypto data: %s failed for %s (%s)", name, meta.get("binance"), e)
    raise CryptoDataError(f"No crypto source returned data. Tried — {'; '.join(errors)}")


def _merge_bars(existing: list, fresh: list) -> list:
    by_date = {b["date"]: b for b in existing}
    for b in fresh:
        by_date[b["date"]] = b
    return [by_date[d] for d in sorted(by_date)]


async def daily_bars(db, symbol: str, days: int = HISTORY_DAYS) -> list:
    """Accumulated real daily OHLC for one crypto pair — same
    accumulate-forever, at-most-one-upstream-call-per-symbol-per-day
    Mongo cache the Yahoo clients use."""
    symbol = symbol.strip().upper()
    meta = CRYPTO_SYMBOLS.get(symbol)
    if not meta:
        raise CryptoDataError(f"Unknown crypto symbol {symbol}.")

    today = datetime.now(timezone.utc).date().isoformat()
    doc = await db[CACHE_COLLECTION].find_one({"symbol": symbol})
    if doc and doc.get("last_fetched_date") == today:
        return doc["bars"]

    fresh, source = await _fetch_with_fallback(meta, days)
    merged = _merge_bars(doc["bars"] if doc else [], fresh)
    await db[CACHE_COLLECTION].update_one(
        {"symbol": symbol},
        {"$set": {"symbol": symbol, "last_fetched_date": today, "bars": merged, "source": source}},
        upsert=True,
    )
    return merged


async def daily_closes(db, symbol: str) -> dict:
    try:
        bars = await daily_bars(db, symbol)
    except CryptoDataError:
        return {}
    return {b["date"]: b["close"] for b in bars}


async def latest_price(symbol: str) -> float:
    """Live last trade. Same source chain, cheapest endpoint on each."""
    symbol = symbol.strip().upper()
    meta = CRYPTO_SYMBOLS.get(symbol)
    if not meta:
        raise CryptoDataError(f"Unknown crypto symbol {symbol}.")

    async with httpx.AsyncClient(timeout=15) as c:
        try:
            r = await c.get("https://api.binance.com/api/v3/ticker/price", params={"symbol": meta["binance"]})
            r.raise_for_status()
            return float(r.json()["price"])
        except Exception:  # noqa: BLE001
            pass
        try:
            r = await c.get(f"https://api.exchange.coinbase.com/products/{meta['coinbase']}/ticker")
            r.raise_for_status()
            return float(r.json()["price"])
        except Exception as e:  # noqa: BLE001
            raise CryptoDataError(f"No live price for {symbol}: {e}") from e


async def intraday_bars(symbol: str, interval_minutes: int = 5, days: int = 30) -> list:
    """Real intraday OHLC. Binance first (finest granularity), Coinbase as
    the Render-safe fallback — Coinbase only supports a fixed granularity
    set (60/300/900/3600/21600/86400 seconds), so an interval it cannot
    serve falls back to the nearest supported one rather than being
    silently resampled here."""
    symbol = symbol.strip().upper()
    meta = CRYPTO_SYMBOLS.get(symbol)
    if not meta:
        raise CryptoDataError(f"Unknown crypto symbol {symbol}.")

    async with httpx.AsyncClient(timeout=25) as c:
        try:
            r = await c.get(
                "https://api.binance.com/api/v3/klines",
                params={"symbol": meta["binance"], "interval": f"{interval_minutes}m", "limit": 1000},
            )
            r.raise_for_status()
            rows = r.json()
            return [{
                "t": datetime.fromtimestamp(row[0] / 1000, tz=timezone.utc).strftime("%H:%M"),
                "time": int(row[0] / 1000),
                "date": _iso(row[0]),
                "open": float(row[1]), "high": float(row[2]), "low": float(row[3]), "close": float(row[4]),
            } for row in rows]
        except Exception:  # noqa: BLE001
            pass

        supported = [60, 300, 900, 3600, 21600, 86400]
        want = interval_minutes * 60
        granularity = min(supported, key=lambda g: abs(g - want))
        r = await c.get(
            f"https://api.exchange.coinbase.com/products/{meta['coinbase']}/candles",
            params={"granularity": granularity},
        )
        r.raise_for_status()
        rows = sorted(r.json(), key=lambda x: x[0])
        return [{
            "t": datetime.fromtimestamp(row[0], tz=timezone.utc).strftime("%H:%M"),
            "time": int(row[0]),
            "date": _iso(int(row[0]) * 1000),
            "open": float(row[3]), "high": float(row[2]), "low": float(row[1]), "close": float(row[4]),
        } for row in rows]
