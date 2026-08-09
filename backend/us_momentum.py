"""
US Markets — Momentum Investing (risk-adjusted, S&P 500 universe) and
Momentum Leaders (short-term momentum scanner), both computed from
yahoo_finance_client.equity_bars() daily history.

Momentum Investing reuses the exact same "12-1" methodology
quant_lab.py's _compute_momentum_stats already implements for the Nifty
500 (see that module's docstring for the full citation/reasoning) --
duplicated here rather than imported since quant_lab's version is a
private, NSE-cache-coupled helper; the formula itself is a standard
academic factor, not something specific to either market.

Momentum Leaders has no NSE equivalent to mirror exactly -- the India
scanner ranks on live intraday tick conviction (Definedge real-time
data), which doesn't exist for this US universe. This ranks on trailing
1-week and 1-month returns instead (same return windows
peter_tingle.py's compute_metrics_from_bars already produces), a
same-spirit "who's moving right now" read built entirely from daily bars.
"""
import asyncio
import math
from datetime import datetime, timezone

import pandas as pd

import yahoo_finance_client as yf
from peter_tingle import compute_metrics_from_bars

TRADING_DAYS_PER_YEAR = 252
MOMENTUM_LOOKBACK_DAYS = 252
MOMENTUM_SKIP_DAYS = 21
MIN_BARS_FOR_MOMENTUM = MOMENTUM_LOOKBACK_DAYS + MOMENTUM_SKIP_DAYS
MIN_UNIVERSE_COVERAGE = 300  # of ~503 S&P 500 constituents


def _clean(v):
    return None if v is None or (isinstance(v, float) and (math.isnan(v) or math.isinf(v))) else round(float(v), 4)


def compute_momentum_stats(bars: list) -> dict | None:
    """Pure function -- see quant_lab.py's identical _compute_momentum_stats
    for the full "12-1" methodology writeup."""
    df = pd.DataFrame(bars)
    if len(df) < MIN_BARS_FOR_MOMENTUM:
        return None
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date").reset_index(drop=True)
    close = df["close"]

    window = close.iloc[-MOMENTUM_LOOKBACK_DAYS:-MOMENTUM_SKIP_DAYS]
    if len(window) < 2:
        return None
    raw_return = float(window.iloc[-1] / window.iloc[0] - 1)
    daily_return = window.pct_change().dropna()
    if daily_return.empty:
        return None
    volatility = daily_return.std() * math.sqrt(TRADING_DAYS_PER_YEAR)
    momentum_score = raw_return / volatility if volatility else float("nan")

    return {
        "stats": {
            "momentum_score": _clean(momentum_score),
            "return_12_1": _clean(raw_return),
            "volatility": _clean(volatility),
        },
        "bars_used": len(df),
        "history_from": df["date"].iloc[0].date().isoformat(),
        "history_to": df["date"].iloc[-1].date().isoformat(),
    }


async def get_or_compute_momentum(db, symbol: str) -> dict | None:
    today = datetime.now(timezone.utc).date().isoformat()
    cached = await db.us_momentum_cache.find_one({"symbol": symbol}, {"_id": 0})
    if cached and cached.get("computed_date") == today:
        cached["cached"] = True
        return cached

    try:
        bars = await yf.equity_bars(db, symbol)
    except yf.YahooFinanceError:
        return None
    if not bars:
        return None
    momentum = compute_momentum_stats(bars)
    if momentum is None:
        return None

    doc = {"symbol": symbol, **momentum, "computed_date": today, "computed_at": datetime.now(timezone.utc).isoformat()}
    await db.us_momentum_cache.update_one({"symbol": symbol}, {"$set": doc}, upsert=True)
    doc["cached"] = False
    return doc


async def refresh_momentum_cache(db):
    """FastAPI BackgroundTask -- one full S&P 500 pass, mirrors
    quant_lab.py's _refresh_momentum_cache exactly (per-symbol guard,
    bounded concurrency, live progress doc for the admin panel)."""
    now_iso = lambda: datetime.now(timezone.utc).isoformat()  # noqa: E731
    symbols = [r["symbol"] for r in await db.us_stock_symbol_master.find({}, {"_id": 0, "symbol": 1}).to_list(1000)]
    total = len(symbols)
    await db.us_momentum_refresh_status.update_one(
        {"id": "current"},
        {"$set": {"id": "current", "status": "running", "started_at": now_iso(), "completed_at": None,
                   "total": total, "done": 0, "cached": 0, "failed": 0}},
        upsert=True,
    )

    semaphore = asyncio.Semaphore(5)
    counters = {"done": 0, "cached": 0, "failed": 0}
    counters_lock = asyncio.Lock()

    async def worker(symbol):
        try:
            async with semaphore:
                doc = await get_or_compute_momentum(db, symbol)
        except Exception:  # noqa: BLE001
            doc = None
        async with counters_lock:
            counters["done"] += 1
            counters["cached" if doc is not None else "failed"] += 1
            await db.us_momentum_refresh_status.update_one(
                {"id": "current"},
                {"$set": {"done": counters["done"], "cached": counters["cached"], "failed": counters["failed"]}},
            )

    await asyncio.gather(*(worker(s) for s in symbols))
    await db.us_momentum_refresh_status.update_one({"id": "current"}, {"$set": {"status": "done", "completed_at": now_iso()}})


# ---------------------------------------------------------------------------
# Momentum Leaders -- short-term (1w/1m return) ranking, same cache/refresh
# shape as above, separate collection since it's a different score/timeframe
# (positional 12-1 vs. "who's moving this week").
# ---------------------------------------------------------------------------
def compute_leader_score(metrics: dict) -> float | None:
    r1w, r1m = metrics.get("return_1w"), metrics.get("return_1m")
    if r1w is None or r1m is None:
        return None
    return round(0.6 * r1w + 0.4 * r1m, 4)


async def get_or_compute_leader(db, symbol: str) -> dict | None:
    today = datetime.now(timezone.utc).date().isoformat()
    cached = await db.us_momentum_leaders_cache.find_one({"symbol": symbol}, {"_id": 0})
    if cached and cached.get("computed_date") == today:
        cached["cached"] = True
        return cached

    try:
        bars = await yf.equity_bars(db, symbol)
    except yf.YahooFinanceError:
        return None
    metrics = compute_metrics_from_bars(bars)
    score = compute_leader_score(metrics)
    if score is None:
        return None

    doc = {
        "symbol": symbol, "score": score,
        "return_1d": metrics.get("return_1d"), "return_1w": metrics.get("return_1w"), "return_1m": metrics.get("return_1m"),
        "computed_date": today, "computed_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.us_momentum_leaders_cache.update_one({"symbol": symbol}, {"$set": doc}, upsert=True)
    doc["cached"] = False
    return doc


async def refresh_leaders_cache(db):
    now_iso = lambda: datetime.now(timezone.utc).isoformat()  # noqa: E731
    symbols = [r["symbol"] for r in await db.us_stock_symbol_master.find({}, {"_id": 0, "symbol": 1}).to_list(1000)]
    total = len(symbols)
    await db.us_momentum_leaders_refresh_status.update_one(
        {"id": "current"},
        {"$set": {"id": "current", "status": "running", "started_at": now_iso(), "completed_at": None,
                   "total": total, "done": 0, "cached": 0, "failed": 0}},
        upsert=True,
    )
    semaphore = asyncio.Semaphore(5)
    counters = {"done": 0, "cached": 0, "failed": 0}
    counters_lock = asyncio.Lock()

    async def worker(symbol):
        try:
            async with semaphore:
                doc = await get_or_compute_leader(db, symbol)
        except Exception:  # noqa: BLE001
            doc = None
        async with counters_lock:
            counters["done"] += 1
            counters["cached" if doc is not None else "failed"] += 1
            await db.us_momentum_leaders_refresh_status.update_one(
                {"id": "current"},
                {"$set": {"done": counters["done"], "cached": counters["cached"], "failed": counters["failed"]}},
            )

    await asyncio.gather(*(worker(s) for s in symbols))
    await db.us_momentum_leaders_refresh_status.update_one({"id": "current"}, {"$set": {"status": "done", "completed_at": now_iso()}})
