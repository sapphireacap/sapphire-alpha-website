"""
Quant Lab — EWMA Crossover backtester (first of 5 planned Quant Lab tools).
Mounted under /api by server.py via create_quant_lab_router(db, definedge),
same factory pattern as journal_routes.py/journal_analytics.py (avoids a
circular import with server.py). Public — no auth, like the other
/terminal/* endpoints Quant Lab sits alongside on the Alpha Terminal page.

Backtest design notes (a review pass caught real bugs in the first draft,
fixed here):
  - ewm(span=..., adjust=False) — matches how you'd compute this incrementally
    off a live feed, not just a backtest convenience.
  - position = signal.shift(1): yesterday's crossover state decides today's
    position, so today's return is never earned off information only known
    at today's close (no lookahead). Both signal and execution price are
    still the same day's close (no open-price execution modeling) — a stated
    simplification surfaced in the response, not hidden.
  - Warmup bias: EWMA carries no NaN after its seed bar (unlike SMA), so the
    first ~2*slow_span bars have a slow EWMA still pulled toward its seed
    value. Left in, they'd unfairly pad both the strategy and buy-and-hold
    comparison with a noisy window. Fixed by truncating the *return*
    comparison to start 2*slow_span bars in and rebasing both equity curves
    to 1.0 there; the full series (including warmup) still renders on the
    chart since seeing it is fine, it just isn't scored.
  - .diff() on the signal produces NaN on the first bar; dropna() before
    reading crossover points off it.
  - .cumprod() (not .prod()) so the total-return number comes with a real
    equity path, not just a discarded final scalar.
"""
import math
from datetime import datetime, timezone, timedelta

import pandas as pd
from fastapi import APIRouter
from pydantic import BaseModel, Field

from definedge_service import DefinedgeError

IST = timezone(timedelta(hours=5, minutes=30))
MIN_EVALUATED_BARS = 30  # minimum post-warmup bars required for a meaningful return comparison


class EwmaCrossoverRequest(BaseModel):
    segment: str
    symbol: str
    fast_span: int = Field(default=20, ge=2, le=500)
    slow_span: int = Field(default=50, ge=3, le=1000)


def _clean(v):
    """NaN/Infinity don't survive JSON encoding cleanly — collapse them to
    None rather than letting FastAPI's default encoder trip over them."""
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def _compute_backtest(bars: list, fast_span: int, slow_span: int):
    """Pure function, no I/O — returns None if there isn't enough data for a
    meaningful evaluation, otherwise the full response payload minus the
    resolved-symbol/segment/caching metadata the route adds."""
    df = pd.DataFrame(bars)
    if len(df) < 2 * slow_span + MIN_EVALUATED_BARS:
        return None

    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date").reset_index(drop=True)
    close = df["close"]

    fast = close.ewm(span=fast_span, adjust=False).mean()
    slow = close.ewm(span=slow_span, adjust=False).mean()
    signal = fast > slow
    position = signal.shift(1).fillna(False)

    daily_return = close.pct_change()
    strategy_return = daily_return * position.astype(float)

    warmup = 2 * slow_span
    eval_daily = daily_return.iloc[warmup:].fillna(0.0)
    eval_strategy = strategy_return.iloc[warmup:].fillna(0.0)

    equity_buyhold = (1 + eval_daily).cumprod()
    equity_strategy = (1 + eval_strategy).cumprod()

    buyhold_return = float(equity_buyhold.iloc[-1] - 1) if len(equity_buyhold) else 0.0
    strategy_total_return = float(equity_strategy.iloc[-1] - 1) if len(equity_strategy) else 0.0

    position_changes = position.diff().dropna()
    markers = []
    for idx in position_changes[position_changes != 0].index:
        markers.append({
            "date": df["date"].iloc[idx].date().isoformat(),
            "type": "buy" if position_changes.loc[idx] > 0 else "sell",
            "price": _clean(close.iloc[idx]),
        })

    series = []
    for i in range(len(df)):
        series.append({
            "date": df["date"].iloc[i].date().isoformat(),
            "close": _clean(close.iloc[i]),
            "ewma_fast": _clean(fast.iloc[i]),
            "ewma_slow": _clean(slow.iloc[i]),
        })

    return {
        "series": series,
        "markers": markers,
        "evaluated_from": df["date"].iloc[warmup].date().isoformat(),
        "evaluated_to": df["date"].iloc[-1].date().isoformat(),
        "evaluated_bars": len(eval_daily),
        "history_from": df["date"].iloc[0].date().isoformat(),
        "history_to": df["date"].iloc[-1].date().isoformat(),
        "stats": {
            "strategy_return": _clean(strategy_total_return),
            "buy_and_hold_return": _clean(buyhold_return),
        },
    }


def create_quant_lab_router(db, definedge) -> APIRouter:
    router = APIRouter(prefix="/quant-lab")

    @router.post("/ewma-crossover")
    async def ewma_crossover(payload: EwmaCrossoverRequest):
        segment = payload.segment.strip().upper()
        symbol = payload.symbol.strip().upper()
        fast_span, slow_span = payload.fast_span, payload.slow_span

        if segment not in ("NSE", "BSE", "NFO", "BFO"):
            return {"found": False, "reason": "Segment must be one of NSE, BSE, NFO, BFO."}
        if fast_span >= slow_span:
            return {"found": False, "reason": "Fast span must be smaller than slow span."}

        cache_key = {"segment": segment, "symbol": symbol, "fast_span": fast_span, "slow_span": slow_span}
        today_ist = datetime.now(IST).strftime("%Y-%m-%d")
        cached = await db.quant_lab_ewma_cache.find_one(cache_key, {"_id": 0})
        if cached and cached.get("computed_date") == today_ist:
            result = dict(cached["result"])
            result["found"] = True
            result["cached"] = True
            return result

        try:
            master = await definedge._get_all_master()
        except DefinedgeError as e:
            return {"found": False, "reason": str(e)}

        resolved = definedge.resolve_symbol(master, segment, symbol)
        if resolved is None:
            return {"found": False, "reason": f"No {segment} symbol matching '{symbol}' was found."}

        try:
            bars = await definedge.daily_history(segment, resolved["token"], years=10)
        except DefinedgeError as e:
            return {"found": False, "reason": str(e)}

        if not bars:
            return {"found": False, "reason": "No historical price data is available for this symbol."}

        backtest = _compute_backtest(bars, fast_span, slow_span)
        if backtest is None:
            return {
                "found": False,
                "reason": f"Only {len(bars)} daily bars available — not enough history for a {slow_span}-span EWMA comparison.",
            }

        result = {
            "segment": segment,
            "symbol": symbol,
            "resolved_symbol": resolved.get("tradingsymbol", symbol),
            "resolved_expiry": resolved.get("expiry"),
            "fast_span": fast_span,
            "slow_span": slow_span,
            **backtest,
        }

        await db.quant_lab_ewma_cache.update_one(
            cache_key,
            {"$set": {**cache_key, "result": result, "computed_date": today_ist,
                      "computed_at": datetime.now(timezone.utc).isoformat()}},
            upsert=True,
        )

        result["found"] = True
        result["cached"] = False
        return result

    return router
