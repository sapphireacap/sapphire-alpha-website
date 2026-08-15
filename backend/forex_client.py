"""Forex data client — the Forex segment's equivalent of
yahoo_finance_client.py's US equity coverage.

Same free, keyless Yahoo chart endpoint this codebase already relies on
for US indices, US equities and Gold (see yahoo_finance_client.py's own
docstring for why Alpha Vantage was ripped out and why a browser
User-Agent is mandatory). Nothing new is introduced here: this module is
a symbol map plus a thin wrapper over that client's existing
_fetch_daily/_merge_bars, so the Forex tab inherits the same proven
transport rather than a second HTTP stack.

Universe (verified live, 2026-08-16 — every symbol below returned a real
daily series, none 404'd):
  - 7 majors, the pairs any forex desk quotes first
  - 21 crosses, needed because the P&F breadth and pairwise
    relative-strength engines are statistically hollow over 7 members
    (the India side runs them over 500 stocks). 28 FX pairs is still a
    much smaller denominator than an equity index — surfaced in the UI
    as the real resolved/total count, never padded.
  - 6 USD "exotics" (SGD/HKD/MXN/NOK/SEK/ZAR) for extra breadth depth
  - XAUUSD and XAGUSD

XAUUSD deliberately maps to GC=F (COMEX gold futures), NOT a spot FX
ticker: "XAU=X"/"XAUUSD=X" both 404 on Yahoo's endpoint — already
established and documented in yahoo_finance_client.COMMODITY_SYMBOLS,
reused verbatim here rather than re-derived. XAGUSD/SI=F is the exact
same futures-proxy relationship. Both are flagged `proxy: True` so
callers can disclose it, the same way the Gold segment already does.
"""
from __future__ import annotations

from datetime import datetime, timezone

from yahoo_finance_client import (
    YahooFinanceError,
    _fetch_daily,
    _merge_bars,
    quote_snapshot,
)

CACHE_COLLECTION = "forex_daily_cache"

# {our symbol: {yahoo ticker, label, group}} — `group` drives the Relative
# Strength Engine's group picker (the FX analogue of a GICS sector /
# NSE sector basket) and nothing else.
FOREX_SYMBOLS: dict[str, dict] = {}


def _add(symbol: str, yahoo: str, label: str, group: str, proxy: bool = False) -> None:
    FOREX_SYMBOLS[symbol] = {"yahoo": yahoo, "label": label, "group": group, "proxy": proxy}


for _s, _label in [
    ("EURUSD", "Euro / US Dollar"), ("GBPUSD", "British Pound / US Dollar"),
    ("USDJPY", "US Dollar / Japanese Yen"), ("USDCHF", "US Dollar / Swiss Franc"),
    ("AUDUSD", "Australian Dollar / US Dollar"), ("USDCAD", "US Dollar / Canadian Dollar"),
    ("NZDUSD", "New Zealand Dollar / US Dollar"),
]:
    _add(_s, f"{_s}=X", _label, "Majors")

for _s, _label in [
    ("EURGBP", "Euro / British Pound"), ("EURJPY", "Euro / Japanese Yen"),
    ("GBPJPY", "British Pound / Japanese Yen"), ("AUDJPY", "Australian Dollar / Japanese Yen"),
    ("EURCHF", "Euro / Swiss Franc"), ("EURAUD", "Euro / Australian Dollar"),
    ("CADJPY", "Canadian Dollar / Japanese Yen"), ("CHFJPY", "Swiss Franc / Japanese Yen"),
    ("NZDJPY", "New Zealand Dollar / Japanese Yen"), ("AUDNZD", "Australian Dollar / New Zealand Dollar"),
    ("AUDCAD", "Australian Dollar / Canadian Dollar"), ("GBPAUD", "British Pound / Australian Dollar"),
    ("GBPCAD", "British Pound / Canadian Dollar"), ("EURCAD", "Euro / Canadian Dollar"),
    ("EURNZD", "Euro / New Zealand Dollar"), ("GBPCHF", "British Pound / Swiss Franc"),
    ("AUDCHF", "Australian Dollar / Swiss Franc"), ("CADCHF", "Canadian Dollar / Swiss Franc"),
    ("NZDCAD", "New Zealand Dollar / Canadian Dollar"), ("NZDCHF", "New Zealand Dollar / Swiss Franc"),
    ("GBPNZD", "British Pound / New Zealand Dollar"),
]:
    _add(_s, f"{_s}=X", _label, "Crosses")

for _s, _label in [
    ("USDSGD", "US Dollar / Singapore Dollar"), ("USDHKD", "US Dollar / Hong Kong Dollar"),
    ("USDMXN", "US Dollar / Mexican Peso"), ("USDNOK", "US Dollar / Norwegian Krone"),
    ("USDSEK", "US Dollar / Swedish Krona"), ("USDZAR", "US Dollar / South African Rand"),
]:
    _add(_s, f"{_s}=X", _label, "USD Exotics")

# Futures proxies, not spot FX tickers — see module docstring.
_add("XAUUSD", "GC=F", "Gold / US Dollar", "Metals", proxy=True)
_add("XAGUSD", "SI=F", "Silver / US Dollar", "Metals", proxy=True)

GROUPS = ["Majors", "Crosses", "USD Exotics", "Metals"]


def group_members(group: str) -> list:
    return [s for s, m in FOREX_SYMBOLS.items() if m["group"] == group]


def all_symbols() -> list:
    return list(FOREX_SYMBOLS.keys())


def search(query: str = "", limit: int = 25) -> list:
    """Symbol/label substring search for the Exitline-style pickers."""
    q = (query or "").strip().upper()
    out = []
    for symbol, meta in FOREX_SYMBOLS.items():
        if not q or q in symbol or q in meta["label"].upper():
            out.append({"symbol": symbol, "label": meta["label"], "group": meta["group"], "proxy": meta["proxy"]})
        if len(out) >= limit:
            break
    return out


async def daily_bars(db, symbol: str) -> list:
    """Accumulated real daily OHLC for one forex symbol — same
    accumulate-forever, one-Yahoo-call-per-symbol-per-day Mongo cache as
    yahoo_finance_client.equity_bars(), in its own collection so FX
    symbols can never collide with an equity ticker of the same name.

    range=20y matches the window equity_bars() settled on (Yahoo silently
    downsamples 1d bars to ~monthly once a range spans decades, so "max"
    is not safe here either)."""
    symbol = symbol.strip().upper()
    meta = FOREX_SYMBOLS.get(symbol)
    if not meta:
        raise YahooFinanceError(f"Unknown forex symbol {symbol}.")

    today = datetime.now(timezone.utc).date().isoformat()
    doc = await db[CACHE_COLLECTION].find_one({"symbol": symbol})
    if doc and doc.get("last_fetched_date") == today:
        return doc["bars"]

    fresh = await _fetch_daily(meta["yahoo"], range_="20y")
    merged = _merge_bars(doc["bars"] if doc else [], fresh)
    await db[CACHE_COLLECTION].update_one(
        {"symbol": symbol},
        {"$set": {"symbol": symbol, "last_fetched_date": today, "bars": merged}},
        upsert=True,
    )
    return merged


async def daily_closes(db, symbol: str) -> dict:
    """{date: close} — the shape breadth_engine/relative_strength_matrix
    take directly."""
    try:
        bars = await daily_bars(db, symbol)
    except YahooFinanceError:
        return {}
    return {b["date"]: b["close"] for b in bars}


async def latest_price(symbol: str) -> float:
    """Live-ish last price off Yahoo's own meta block. Raises rather than
    fabricating when Yahoo doesn't carry one."""
    symbol = symbol.strip().upper()
    meta = FOREX_SYMBOLS.get(symbol)
    if not meta:
        raise YahooFinanceError(f"Unknown forex symbol {symbol}.")
    snap = await quote_snapshot(meta["yahoo"])
    return snap["last"]


async def intraday_bars(symbol: str, interval_minutes: int = 5, days: int = 30) -> list:
    """Real intraday OHLC for one forex symbol.

    Yahoo's chart endpoint serves genuine intraday FX bars, but only over
    a short trailing window (roughly 60 days at 5m, ~7-8 days at 1m —
    the same limit yahoo_finance_client.py records for equities, which is
    why permanent minute-bar caching was never built there either). The
    caller gets whatever really exists; nothing is back-filled or
    synthesised to reach `days`."""
    symbol = symbol.strip().upper()
    meta = FOREX_SYMBOLS.get(symbol)
    if not meta:
        raise YahooFinanceError(f"Unknown forex symbol {symbol}.")

    interval = f"{interval_minutes}m"
    range_ = f"{min(days, 59)}d" if interval_minutes < 60 else f"{min(days, 729)}d"

    import httpx
    from yahoo_finance_client import BASE_URL, USER_AGENT

    try:
        async with httpx.AsyncClient(timeout=20) as c:
            r = await c.get(
                f"{BASE_URL}/{meta['yahoo']}",
                params={"range": range_, "interval": interval},
                headers={"User-Agent": USER_AGENT},
            )
        r.raise_for_status()
        data = r.json()
    except httpx.HTTPError as e:
        raise YahooFinanceError(f"Yahoo intraday request failed: {e}") from e

    result = (data.get("chart") or {}).get("result")
    if not result:
        raise YahooFinanceError(f"No intraday data for {symbol}.")
    r0 = result[0]
    stamps = r0.get("timestamp") or []
    quote = (r0.get("indicators") or {}).get("quote", [{}])[0]
    closes, opens = quote.get("close") or [], quote.get("open") or []
    highs, lows = quote.get("high") or [], quote.get("low") or []

    bars = []
    for i, t in enumerate(stamps):
        close = closes[i] if i < len(closes) else None
        if close is None:
            continue
        dt = datetime.fromtimestamp(t, tz=timezone.utc)
        bars.append({
            "t": dt.strftime("%H:%M"), "time": int(t), "date": dt.date().isoformat(),
            "open": opens[i], "high": highs[i], "low": lows[i], "close": close,
        })
    return bars
