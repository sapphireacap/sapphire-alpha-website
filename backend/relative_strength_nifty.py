"""
Peter Tingle -- relative strength vs NIFTY 50, across Daily/Weekly/
Monthly/Quarterly windows.

ARCHITECTURALLY DIFFERENT from relative_strength_matrix.py's existing
engine, deliberately: that module is pairwise WITHIN a fixed sector
basket (every stock scored by how many of its peers it currently beats
on a P&F ratio chart, per sector -- see relative_strength_groups.py),
confirmed by this session's own earlier codebase survey to have no
stock-vs-a-single-benchmark mode at all. This module is the opposite:
one stock against exactly one benchmark (NIFTY 50), a plain returns
comparison, no P&F ratio charting involved.

NAMING: the reference report this is modeled on uses its own named
categories for each quadrant (a stock moving with/against the index,
over/underperforming it). Those names are Definedge's own branded
terminology, not a published/textbook methodology -- reusing them here
would be exactly the kind of vendor-specific naming this codebase
deliberately avoids elsewhere (see e.g. "Sapphire Levels" replacing
Camarilla's own naming in exitline.py). The numbers and the real
comparison are what's reused; the category labels below are this
codebase's own, plain and descriptive rather than branded.
"""
from datetime import datetime, timezone

from definedge_service import DefinedgeError

RETURN_WINDOWS = {"daily": 1, "weekly": 5, "monthly": 21, "quarterly": 63}

_nifty_bars_cache = None  # (date_str, bars) -- same per-day caching pattern as
                           # definedge_service.py's _master_cache, avoids every
                           # single Peter Tingle scan re-fetching NIFTY's own
                           # history from Definedge.


async def _get_nifty_bars(definedge) -> list:
    global _nifty_bars_cache
    today = datetime.now(timezone.utc).date().isoformat()
    if _nifty_bars_cache and _nifty_bars_cache[0] == today:
        return _nifty_bars_cache[1]
    bars = await definedge.daily_history("NSE", "26000", years=2)  # NIFTY_SPOT_TOKEN, see definedge_service.py
    _nifty_bars_cache = (today, bars)
    return bars


def _pct_return(closes: list, days_back: int):
    if len(closes) <= days_back:
        return None
    prior = closes[-1 - days_back]
    return (closes[-1] / prior - 1) * 100 if prior else None


def _classify(stock_return: float, nifty_return: float) -> dict:
    aligned = (stock_return >= 0) == (nifty_return >= 0)
    relative = stock_return - nifty_return
    outperformed = relative > 0

    if aligned and stock_return >= 0:
        text = f"Advanced along with NIFTY 50 and {'outperformed' if outperformed else 'underperformed'}."
    elif aligned:
        text = f"Declined along with NIFTY 50 and {'outperformed' if outperformed else 'underperformed'}."
    else:
        text = f"Diverged from NIFTY 50 -- {'rose' if stock_return >= 0 else 'fell'} while the index {'rose' if nifty_return >= 0 else 'fell'}."

    label = "Outperforming" if outperformed else "Underperforming"
    if not aligned:
        label = "Diverging"
    return {
        "stock_return": round(stock_return, 2),
        "nifty_return": round(nifty_return, 2),
        "relative_return": round(relative, 2),
        "aligned": aligned,
        "outperformed": outperformed,
        "label": label,
        "bias": "bullish" if outperformed else "bearish",
        "text": text,
    }


def relative_strength_observations(stock_bars: list, nifty_bars: list) -> dict:
    stock_closes = [b.get("close") for b in (stock_bars or [])]
    nifty_closes = [b.get("close") for b in (nifty_bars or [])]
    out = {}
    for period, n in RETURN_WINDOWS.items():
        s_ret = _pct_return(stock_closes, n)
        n_ret = _pct_return(nifty_closes, n)
        if s_ret is None or n_ret is None:
            continue
        out[period] = _classify(s_ret, n_ret)
    return out


async def relative_strength_for_symbol(definedge, stock_bars: list) -> dict:
    """Convenience wrapper -- fetches NIFTY's own bars (cached) and runs
    the comparison. `stock_bars` is the caller's own already-fetched
    daily series (India: stock_prices_daily; this is India-only for now
    since it needs a Definedge NIFTY fetch, which the US route has no
    equivalent session for)."""
    try:
        nifty_bars = await _get_nifty_bars(definedge)
    except DefinedgeError:
        # No active session (daily OTP login hasn't happened yet), or a
        # transient Definedge error -- best-effort section, never break
        # the rest of the scan over a missing benchmark comparison.
        return {}
    return relative_strength_observations(stock_bars, nifty_bars)
