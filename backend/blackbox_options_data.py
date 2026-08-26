"""
Shared symbol/expiry/strike resolution for Premium Band Strangle --
reuses definedge_service.py's existing master-file column layout and
expiry-picking utilities rather than reinventing them. Pure functions.

Convexity Window / Gamma Backspread's realized-volatility, 15-minute-bar,
EMA, and IV-percentile helpers that used to live here were removed
entirely on 2026-08-26, code and production data both, per explicit
instruction -- see git history if either strategy is ever wanted back.
"""
from datetime import date

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
