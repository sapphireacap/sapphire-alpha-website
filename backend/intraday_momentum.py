"""
Intraday Momentum Scanner — pure compute functions, no I/O.

Adapts Definedge's own published "Momentum Investing Scanner" methodology
(their public product description, quoted by the user this session) to
intraday bars instead of daily ones. That description fully explains:
  - Return% over a selected period (period count = number of bars, not
    calendar days — "252 represents 1 year" on the daily version, so here
    it's simply "N intraday bars back").
  - VOLAR = "volatility adjusted returns" = Return% divided by the
    volatility realized over that same period — Definedge's own term for
    a Sharpe-style ratio, conceptually identical to what this codebase
    already computes for Momentum Investing/Sharpe Dashboard, just
    labelled with their public name since they've published that name
    and definition (unlike "Star Momentum"/"iVolar" from the separate
    scanner screenshot earlier this session, which remain undocumented
    and are NOT implemented here).
  - Max retracement — how far price has pulled back from its high over
    the period (the daily version anchors to the 52-week/all-time high;
    intraday has no such reference, so this anchors to the period's own
    high instead — the closest honest equivalent).
  - EMA filter(s) — only pass stocks trading above one or two chosen EMAs.
  - Relative momentum — score off a ratio series (stock ÷ denominator)
    instead of the stock's own raw closes, so a bullish stock in a
    stronger uptrend than its benchmark ranks above one merely following
    the market up.
"""
from __future__ import annotations

import math
from typing import Optional

from pnf_indicators import ema


def return_pct(closes: list, period: int) -> Optional[float]:
    if len(closes) < period + 1 or closes[-(period + 1)] <= 0:
        return None
    start, end = closes[-(period + 1)], closes[-1]
    return (end - start) / start * 100.0


def volatility_pct(closes: list, period: int) -> Optional[float]:
    """Stdev of bar-to-bar % returns over the trailing `period` bars — not
    annualized, since this is read over the same short intraday window
    the return figure itself covers (annualizing a handful of 5-minute
    bars would produce a meaningless, wildly inflated number)."""
    if len(closes) < period + 1:
        return None
    window = closes[-(period + 1):]
    rets = [(window[i] - window[i - 1]) / window[i - 1] * 100.0
            for i in range(1, len(window)) if window[i - 1] > 0]
    if len(rets) < 2:
        return None
    mean = sum(rets) / len(rets)
    variance = sum((r - mean) ** 2 for r in rets) / (len(rets) - 1)
    return math.sqrt(variance)


def volar_score(ret_pct: Optional[float], vol_pct: Optional[float]) -> Optional[float]:
    if ret_pct is None or vol_pct is None or vol_pct == 0:
        return None
    return ret_pct / vol_pct


def retracement_pct(closes: list, period: int) -> Optional[float]:
    """% pullback from the period's own high to the latest close — 0 if
    the latest close IS the period high (no retracement to report)."""
    if len(closes) < period + 1:
        return None
    window = closes[-(period + 1):]
    period_high = max(window)
    if period_high <= 0:
        return None
    return max(0.0, (period_high - closes[-1]) / period_high * 100.0)


def passes_ema_filter(closes: list, ema_periods: list) -> bool:
    """True if the latest close sits above EVERY listed EMA (an empty
    list always passes — "no EMA filter selected")."""
    for p in ema_periods:
        line = ema(closes, p)
        if not line or line[-1] is None or closes[-1] <= line[-1]:
            return False
    return True


def relative_series(stock_closes: list, denom_closes: list) -> list:
    """Elementwise stock/denominator ratio, aligned from the END of both
    series (the two symbols' bar counts may differ slightly if one has a
    gap) — same alignment convention as this codebase's other ratio-chart
    tools (relative_strength_matrix.py)."""
    n = min(len(stock_closes), len(denom_closes))
    if n == 0:
        return []
    s, d = stock_closes[-n:], denom_closes[-n:]
    return [s[i] / d[i] for i in range(n) if d[i] > 0]


def scan_symbol(closes: list, period: int, ema_periods: list,
                 relative_closes: Optional[list] = None) -> Optional[dict]:
    """Full per-symbol computation for one candidate — closes: the
    symbol's own intraday closes, oldest -> newest. relative_closes: the
    chosen denominator's closes, aligned the same way, when relative
    momentum mode is on (None for absolute mode). Returns None if there
    isn't enough history for this period yet, rather than a partial/
    fabricated result."""
    series = relative_series(closes, relative_closes) if relative_closes else closes
    ret = return_pct(series, period)
    vol = volatility_pct(series, period)
    if ret is None or vol is None:
        return None
    return {
        "return_pct": round(ret, 2),
        "volatility_pct": round(vol, 3),
        "volar_score": round(volar_score(ret, vol), 3) if vol else None,
        "retracement_pct": round(retracement_pct(series, period) or 0.0, 2),
        "ema_pass": passes_ema_filter(closes, ema_periods),  # EMA filter always reads the stock's OWN price, even in relative mode — "trading above its EMA" is a real-price condition, not a ratio one.
    }
