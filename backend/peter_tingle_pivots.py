"""
Peter Tingle -- classic pivot levels (Daily/Weekly/Monthly S1-S3/R1-R3),
the one section of the requested report with no existing implementation
anywhere in this codebase (exitline.py's compute_camarilla_levels() is a
different, Camarilla-family formula -- deliberately not reused here).

Standard formula, textbook (not Camarilla/Woodie/Fibonacci variants):
    Pivot = (H + L + C) / 3
    R1 = 2*Pivot - L        S1 = 2*Pivot - H
    R2 = Pivot + (H - L)    S2 = Pivot - (H - L)
    R3 = H + 2*(Pivot - L)  S3 = L - 2*(H - Pivot)
"""
from datetime import date, datetime

import pnf_chart


def compute_pivot_levels(high: float, low: float, close: float) -> dict:
    pivot = (high + low + close) / 3
    return {
        "R3": high + 2 * (pivot - low),
        "R2": pivot + (high - low),
        "R1": 2 * pivot - low,
        "Pivot": pivot,
        "S1": 2 * pivot - high,
        "S2": pivot - (high - low),
        "S3": low - 2 * (high - pivot),
    }


def _in_current_period(bar_date_str: str, period: str, today: date) -> bool:
    d = datetime.strptime(bar_date_str, "%Y-%m-%d").date()
    if period == "daily":
        return d == today
    if period == "weekly":
        return d.isocalendar()[:2] == today.isocalendar()[:2]
    return (d.year, d.month) == (today.year, today.month)  # monthly


def _previous_complete_period_bar(bars: list, period: str) -> dict | None:
    """The most recently COMPLETED daily/weekly/monthly bar -- classic
    pivots are always computed off the PRIOR period's H/L/C, never a
    still-forming one. `bars` need not already exclude today: in
    practice they never include it (stock_prices_daily and equity_bars
    are both end-of-day-only), but the explicit exclusion here makes
    that an enforced invariant rather than an assumption, and correctly
    handles a partial current week/month regardless of what weekday
    "today" falls on."""
    candidates = bars if period == "daily" else pnf_chart.resample_daily(bars, period)
    if not candidates:
        return None
    today = date.today()
    complete = [b for b in candidates if not _in_current_period(b["date"], period, today)]
    return complete[-1] if complete else None


def pivot_levels_for_bars(bars: list) -> dict:
    """bars: daily OHLC, sorted oldest -> newest (definedge_service's
    daily_history / yahoo_finance_client's equity_bars shape). Returns
    {"daily": {...}|None, "weekly": {...}|None, "monthly": {...}|None} --
    None for a period with no completed bar yet (e.g. a stock listed
    less than a week ago has no weekly pivot)."""
    out = {}
    for period in ("daily", "weekly", "monthly"):
        bar = _previous_complete_period_bar(bars, period)
        out[period] = compute_pivot_levels(bar["high"], bar["low"], bar["close"]) if bar else None
    return out
