"""Stock-level FUT/ATM CE/ATM PE token resolution for the Options Trend
Scanner — generalizes blackbox_options_data.py's index-only
resolve_futures_token()/resolve_strike_tokens() (hard-filtered to
FUTIDX/OPTIDX) to individual stocks (FUTSTK/OPTSTK), and resolves ATM by
picking the nearest ACTUALLY LISTED strike to spot rather than assuming a
fixed strike increment — unlike NIFTY/BANKNIFTY (blackbox_options_market.py's
STRIKE_INCREMENT), individual stocks have no single confirmed increment
(it varies stock to stock and Definedge doesn't publish one), so guessing
an increment risks landing on a strike that isn't actually listed.

Unlike index options, individual stock options only ever list MONTHLY
expiries (no weekly contract exists for stocks) — confirmed by NSE's own
market-lots file (fo_mktlots.csv) listing exactly 3 monthly columns per
stock, no weekly ones. So expiry selection here is just "nearest listed
expiry still in the future", no Mon/Tue weekly-roll logic needed (that's
specific to index options' weekly cadence).

Same allmaster.zip column layout already established elsewhere in this
codebase (blackbox_options_data.py, blackbox_prism_alpha.py) — not
re-derived: 0=SEG 1=TOKEN 2=SYMBOL 3=TRADINGSYM 4=INSTR 5=EXPIRY(ddmmyyyy)
8=OPTTYPE 9=STRIKE.
"""
from __future__ import annotations

from datetime import date

SEG, TOKEN, SYMBOL, TRADINGSYM, INSTR, EXPIRY, OPTTYPE, STRIKE = 0, 1, 2, 3, 4, 5, 8, 9


def resolve_stock_futures_token(df, symbol: str, today: date) -> dict:
    """Nearest-expiry FUTSTK contract for `symbol` — {"token", "expiry"} or
    None if nothing listed (e.g. symbol has options but no futures, or
    isn't F&O-eligible at all)."""
    import pandas as pd
    sub = df[(df[SYMBOL].astype(str) == symbol) & (df[INSTR].astype(str) == "FUTSTK")].copy()
    if sub.empty:
        return None
    sub["_exp"] = pd.to_datetime(sub[EXPIRY].astype(str), format="%d%m%Y", errors="coerce").dt.date
    sub = sub.dropna(subset=["_exp"])
    future = sub[sub["_exp"] >= today]
    if future.empty:
        return None
    expiry = future["_exp"].min()
    row = future[future["_exp"] == expiry].iloc[0]
    return {"token": str(row[TOKEN]), "expiry": expiry}


def resolve_stock_atm_tokens(df, symbol: str, spot: float, today: date) -> dict:
    """{"strike", "expiry", "CE": token, "PE": token} for the nearest-expiry,
    nearest-to-spot ACTUALLY LISTED strike — None if no OPTSTK contracts
    resolve at all (symbol has futures but no options, illiquid, etc.)."""
    import pandas as pd
    sub = df[(df[SYMBOL].astype(str) == symbol) & (df[INSTR].astype(str) == "OPTSTK")
             & (df[OPTTYPE].astype(str).isin(["CE", "PE"]))].copy()
    if sub.empty:
        return None
    sub["_exp"] = pd.to_datetime(sub[EXPIRY].astype(str), format="%d%m%Y", errors="coerce").dt.date
    sub = sub.dropna(subset=["_exp"])
    future = sub[sub["_exp"] >= today]
    if future.empty:
        return None
    expiry = future["_exp"].min()
    at_expiry = future[future["_exp"] == expiry].copy()
    at_expiry["_strike"] = pd.to_numeric(at_expiry[STRIKE], errors="coerce") / 100.0
    at_expiry = at_expiry.dropna(subset=["_strike"])
    if at_expiry.empty:
        return None

    listed_strikes = sorted(at_expiry["_strike"].unique())
    nearest_strike = min(listed_strikes, key=lambda k: abs(k - spot))

    out = {"strike": nearest_strike, "expiry": expiry}
    for opt in ("CE", "PE"):
        row = at_expiry[(at_expiry["_strike"] == nearest_strike) & (at_expiry[OPTTYPE].astype(str) == opt)]
        if row.empty:
            return None  # one-sided strike (only CE or only PE listed) isn't usable — need both legs
        out[opt] = str(row.iloc[0][TOKEN])
    return out
