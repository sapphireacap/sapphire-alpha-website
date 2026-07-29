"""
Shared data/computation helpers for Convexity Window and Gamma Backspread --
symbol/expiry/strike resolution (reusing definedge_service.py's existing
master-file column layout and expiry-picking utilities, not reinventing
them), realized volatility, 15-minute bar aggregation, EMA, and IV
percentile. Pure functions wherever possible so the backtest harness and
the live evaluator call the exact same code.
"""
import math
from datetime import date, datetime, timedelta

IST_OFFSET_HOURS = 5.5

# Same allmaster.zip column layout already established and verified live
# elsewhere in this codebase (blackbox_prism_alpha.py's
# resolve_atm_option_tokens, blackbox_backtest.py's _resolve_strike_tokens)
# -- not re-derived here.
SEG, TOKEN, SYMBOL, TRADINGSYM, INSTR, EXPIRY, OPTTYPE, STRIKE = 0, 1, 2, 3, 4, 5, 8, 9


def list_candidate_expiries(df, symbol: str, today: date, dte_min: int, dte_max: int) -> list:
    """Every real listed weekly expiry for `symbol` whose DTE (calendar
    days from `today`) falls in [dte_min, dte_max] -- may be empty (never
    fabricates an expiry that isn't actually listed)."""
    sub = df[(df[SYMBOL].astype(str) == symbol) & (df[INSTR].astype(str) == "OPTIDX")]
    if sub.empty:
        return []
    import pandas as pd
    exps = pd.to_datetime(sub[EXPIRY].astype(str), format="%d%m%Y", errors="coerce").dt.date.dropna().unique()
    return sorted(e for e in set(exps) if dte_min <= (e - today).days <= dte_max)


def resolve_strike_tokens(df, symbol: str, expiry: date, strike: int) -> dict:
    """{"CE": token, "PE": token} for one (symbol, expiry, strike) --
    returns an empty dict for a leg that isn't actually listed, never a
    fabricated token."""
    sub = df[(df[SYMBOL].astype(str) == symbol) & (df[INSTR].astype(str) == "OPTIDX")
             & (df[OPTTYPE].astype(str).isin(["CE", "PE"]))].copy()
    import pandas as pd
    sub["_strike"] = pd.to_numeric(sub[STRIKE], errors="coerce") / 100.0
    sub["_exp"] = pd.to_datetime(sub[EXPIRY].astype(str), format="%d%m%Y", errors="coerce").dt.date
    out = {}
    for opt in ("CE", "PE"):
        row = sub[(sub["_strike"] == float(strike)) & (sub["_exp"] == expiry) & (sub[OPTTYPE].astype(str) == opt)]
        if not row.empty:
            out[opt] = str(row.iloc[0][TOKEN])
    return out


def list_strikes_near(atm: int, increment: int, count: int) -> list:
    """ATM +/- `count` strikes, inclusive, at the given increment."""
    return [atm + i * increment for i in range(-count, count + 1)]


def resolve_futures_token(df, symbol: str, today: date) -> dict:
    """Nearest-expiry future for `symbol` -- {"token", "expiry"} or None if
    nothing listed. Same Mon/Tue-roll convention as the rest of this
    codebase (DefinedgeService._pick_expiry), imported from there rather
    than re-implemented."""
    from definedge_service import DefinedgeService
    sub = df[(df[SYMBOL].astype(str) == symbol) & (df[INSTR].astype(str) == "FUTIDX")].copy()
    if sub.empty:
        return None
    import pandas as pd
    sub["_exp"] = pd.to_datetime(sub[EXPIRY].astype(str), format="%d%m%Y", errors="coerce").dt.date
    sub = sub.dropna(subset=["_exp"])
    if sub.empty:
        return None
    expiry = DefinedgeService._pick_expiry(sorted(set(sub["_exp"].tolist())), today)
    if expiry is None:
        return None
    row = sub[sub["_exp"] == expiry]
    if row.empty:
        return None
    return {"token": str(row.iloc[0][TOKEN]), "expiry": expiry}


def realized_vol(daily_closes: list, window: int) -> float:
    """Close-to-close log-return realized vol, annualized (x sqrt(252)).
    Needs at least `window` + 1 closes; returns None (never a fabricated
    number) if there isn't enough real history yet."""
    if len(daily_closes) < window + 1:
        return None
    recent = daily_closes[-(window + 1):]
    log_returns = [math.log(recent[i] / recent[i - 1]) for i in range(1, len(recent)) if recent[i - 1] > 0]
    if len(log_returns) < 2:
        return None
    mean = sum(log_returns) / len(log_returns)
    variance = sum((r - mean) ** 2 for r in log_returns) / (len(log_returns) - 1)
    return math.sqrt(variance) * math.sqrt(252)


def true_range_series(daily_bars: list) -> list:
    """daily_bars: [{date, open, high, low, close}, oldest -> newest]. True
    range per bar (gap-aware: max of high-low, |high-prev_close|,
    |low-prev_close|) -- the first bar has no previous close, so it's
    dropped, not approximated."""
    out = []
    for i in range(1, len(daily_bars)):
        b, prev = daily_bars[i], daily_bars[i - 1]
        tr = max(b["high"] - b["low"], abs(b["high"] - prev["close"]), abs(b["low"] - prev["close"]))
        out.append(tr)
    return out


def median_true_range(daily_bars: list, window: int) -> float:
    tr = true_range_series(daily_bars)
    if len(tr) < window:
        return None
    recent = sorted(tr[-window:])
    n = len(recent)
    mid = n // 2
    return recent[mid] if n % 2 else (recent[mid - 1] + recent[mid]) / 2


def ema_series(values: list, period: int) -> list:
    """Standard EMA, full series (not just the latest value) -- callers
    that only need the current value take [-1]. None (not a partial/biased
    average) until at least `period` values are available."""
    if len(values) < period:
        return [None] * len(values)
    k = 2 / (period + 1)
    out = [None] * (period - 1)
    seed = sum(values[:period]) / period
    out.append(seed)
    prev = seed
    for v in values[period:]:
        prev = v * k + prev * (1 - k)
        out.append(prev)
    return out


def aggregate_to_15min(bars_1min: list) -> list:
    """bars_1min: [{"dt": datetime, "open","high","low","close"}, ...],
    chronological. Buckets aligned to NSE's real 15-minute session grid
    (09:15, 09:30, 09:45, ...), not an arbitrary rolling window."""
    buckets = {}
    for b in bars_1min:
        dt = b["dt"]
        minute_of_day = dt.hour * 60 + dt.minute
        bucket_start_minute = (minute_of_day // 15) * 15
        bucket_key = dt.replace(hour=bucket_start_minute // 60, minute=bucket_start_minute % 60, second=0, microsecond=0)
        if bucket_key not in buckets:
            buckets[bucket_key] = {"dt": bucket_key, "open": b["open"], "high": b["high"], "low": b["low"], "close": b["close"]}
        else:
            agg = buckets[bucket_key]
            agg["high"] = max(agg["high"], b["high"])
            agg["low"] = min(agg["low"], b["low"])
            agg["close"] = b["close"]
    return [buckets[k] for k in sorted(buckets)]


def percentile_rank(history: list, current: float) -> float:
    """% of `history` strictly below `current`, 0-100 -- the standard
    "IV percentile" definition (distinct from IV RANK, which is
    (current-min)/(max-min); the spec says percentile, so percentile is
    what's implemented). None if there's no real history yet."""
    if not history:
        return None
    below = sum(1 for h in history if h < current)
    return (below / len(history)) * 100.0
