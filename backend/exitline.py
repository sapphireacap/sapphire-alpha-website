"""
Exitline — Camarilla pivot levels + suggested SL/TP for a manually-picked
NSE cash/futures/options instrument. Public Alpha Terminal module (see
exitline_routes.py) — reads use the site's own shared Definedge session,
same pattern as Quant Lab's EWMA/Sharpe tools, no per-visitor broker login.

Flow: segment (NSE/FUT/OPT) -> scrip (+ expiry/strike/CE-PE for FUT/OPT,
always manual, never auto-picked) -> previous day's H/L/C from Definedge
-> 8-level Camarilla ladder -> zone classification against live LTP -> SL/TP.

Reuses DefinedgeService's existing OTP-session auth and allmaster.zip
master file (same unified NSE/BSE/NFO/BFO/MCX/CDS frame Index Vector and
Quant Lab already read) — no new auth path, no new master download.
Master column layout (confirmed in definedge_service.py): 0=SEG 1=TOKEN
2=SYMBOL 3=TRADINGSYM 4=INSTRUMENT 5=EXPIRY(ddmmyyyy) 8=OPTIONTYPE(CE/PE)
9=STRIKE(x100).

Camarilla levels are fixed for the trading day (computed once from the
previous day's H/L/C and cached in db.exitline_levels); LTP is fetched
fresh on every /levels request since this is a user-triggered lookup, not
a polling dashboard.
"""
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional

import pandas as pd

from definedge_service import DefinedgeError

logger = logging.getLogger(__name__)
IST = timezone(timedelta(hours=5, minutes=30))

SEG, TOKEN, SYMBOL, TRADINGSYM, INSTR, EXPIRY, OPTTYPE, STRIKE = 0, 1, 2, 3, 4, 5, 8, 9
FUT_INSTR = ["FUTSTK", "FUTIDX"]
OPT_INSTR = ["OPTSTK", "OPTIDX"]
DERIVATIVE_SEGMENTS = ("NFO", "BFO")  # stock/index derivatives can live in either


# ---------------------------------------------------------------------------
# Camarilla levels — pure, unit-testable
# ---------------------------------------------------------------------------
def compute_camarilla_levels(high: float, low: float, close: float) -> dict:
    r = high - low
    return {
        "R4": close + r * 1.1000,
        "R3": close + r * 0.5500,
        "R2": close + r * 0.3660,
        "R1": close + r * 0.1830,
        "S1": close - r * 0.1830,
        "S2": close - r * 0.3660,
        "S3": close - r * 0.5500,
        "S4": close - r * 1.1000,
    }


def classify_and_suggest(levels: dict, ltp: float, prev_close: float) -> dict:
    """Zone classification + SL/TP, per the Camarilla rules in the module
    docstring's design brief:
      - Beyond R4/S4: Breakout Zone, trend day, no fixed TP, trail the stop.
      - At/between R3-R4 (or S4-S3): Trading Zone edge, mean-reversion
        trigger — short at R3 (SL above R4, TP toward R1/R2/prev close),
        long at S3 (SL below S4, TP toward S1/S2/prev close).
      - Between S3 and R3 but not near either edge: mid-range, no
        standalone trigger — R1/R2/S1/S2 only ever surface as momentum
        commentary here, never a separate signal.
    """
    R4, R3, R2, R1 = levels["R4"], levels["R3"], levels["R2"], levels["R1"]
    S1, S2, S3, S4 = levels["S1"], levels["S2"], levels["S3"], levels["S4"]

    if ltp > R4:
        return {
            "zone": "breakout_upper",
            "zone_label": "Breakout Zone (Upper)",
            "bias": "Long",
            "sl": round(R4, 2),
            "tp": None,
            "tp_alt": None,
            "trail_stop": True,
            "reason": f"Broke above R4 ({R4:.2f}) — trend day, mean-reversion invalidated. Buy the breakout (or on retest of R4); no fixed target, trail the stop.",
            "commentary": None,
        }
    if ltp < S4:
        return {
            "zone": "breakout_lower",
            "zone_label": "Breakout Zone (Lower)",
            "bias": "Short",
            "sl": round(S4, 2),
            "tp": None,
            "tp_alt": None,
            "trail_stop": True,
            "reason": f"Broke below S4 ({S4:.2f}) — trend day, mean-reversion invalidated. Short the breakdown (or on retest of S4); no fixed target, trail the stop.",
            "commentary": None,
        }
    if R3 <= ltp <= R4:
        return {
            "zone": "trading_upper",
            "zone_label": "Trading Zone — At R3",
            "bias": "Short",
            "sl": round(R4 * 1.001, 2),
            "tp": round(R1, 2),
            "tp_alt": round(R2, 2),
            "trail_stop": False,
            "reason": f"At R3 ({R3:.2f}) — short bias, TP toward R1/R2 or previous close ({prev_close:.2f}), SL just above R4.",
            "commentary": None,
        }
    if S4 <= ltp <= S3:
        return {
            "zone": "trading_lower",
            "zone_label": "Trading Zone — At S3",
            "bias": "Long",
            "sl": round(S4 * 0.999, 2),
            "tp": round(S1, 2),
            "tp_alt": round(S2, 2),
            "trail_stop": False,
            "reason": f"At S3 ({S3:.2f}) — long bias, TP toward S1/S2 or previous close ({prev_close:.2f}), SL just below S4.",
            "commentary": None,
        }

    # Mid-range (strictly inside S3..R3): no standalone trigger. R1/R2/S1/S2
    # are checkpoints only — surfaced as momentum commentary on whichever one
    # price currently sits closest to.
    checkpoints = [("R2", R2), ("R1", R1), ("S1", S1), ("S2", S2)]
    label, val = min(checkpoints, key=lambda kv: abs(ltp - kv[1]))
    above = ltp >= val
    if label in ("R1", "R2"):
        commentary = (
            f"Holding above {label} ({val:.2f}) — firm bullish momentum, not a standalone trigger."
            if above else
            f"Struggling near {label} ({val:.2f}) — weak bullish momentum, not a standalone trigger."
        )
    else:
        commentary = (
            f"Holding above {label} ({val:.2f}) — support test holding, not a standalone trigger."
            if above else
            f"Slipping below {label} ({val:.2f}) — weak bearish momentum, not a standalone trigger."
        )
    return {
        "zone": "trading_mid",
        "zone_label": "Trading Zone — Mid-Range",
        "bias": "Neutral",
        "sl": None,
        "tp": None,
        "tp_alt": None,
        "trail_stop": False,
        "reason": "Inside S3/R3 — range-bound, no standalone entry trigger at current levels.",
        "commentary": commentary,
    }


# ---------------------------------------------------------------------------
# Master-file lookups (allmaster.zip) — segment here means the Exitline
# NSE/FUT/OPT selector value, not the raw exchange SEG column (a FUT/OPT
# underlying can live in NFO or BFO — both are probed).
# ---------------------------------------------------------------------------
def list_symbols(df: pd.DataFrame, exitline_segment: str, query: str = "") -> list:
    exitline_segment = exitline_segment.strip().upper()
    if exitline_segment == "NSE":
        sub = df[(df[SEG].astype(str) == "NSE") & (df[INSTR].astype(str).isin(["EQ", "IDX"]))]
    else:
        instr_codes = FUT_INSTR if exitline_segment == "FUT" else OPT_INSTR
        sub = df[(df[SEG].astype(str).isin(DERIVATIVE_SEGMENTS)) & (df[INSTR].astype(str).isin(instr_codes))]

    symbols = sorted(set(sub[SYMBOL].astype(str).str.upper()))
    query = query.strip().upper()
    if query:
        symbols = [s for s in symbols if query in s]
    return symbols[:100]


def list_expiries(df: pd.DataFrame, exitline_segment: str, symbol: str) -> list:
    """Sorted ISO expiry dates for a FUT/OPT underlying, probing NFO then BFO."""
    symbol = symbol.strip().upper()
    instr_codes = FUT_INSTR if exitline_segment == "FUT" else OPT_INSTR
    for exch in DERIVATIVE_SEGMENTS:
        sub = df[(df[SEG].astype(str) == exch) & (df[SYMBOL].astype(str).str.upper() == symbol)
                 & (df[INSTR].astype(str).isin(instr_codes))]
        if sub.empty:
            continue
        exp = pd.to_datetime(sub[EXPIRY].astype(str), format="%d%m%Y", errors="coerce").dt.date.dropna()
        if not exp.empty:
            return sorted(e.isoformat() for e in set(exp.tolist()))
    return []


def list_strikes(df: pd.DataFrame, symbol: str, expiry: str) -> list:
    """Sorted strikes for an OPT underlying+expiry, probing NFO then BFO."""
    symbol = symbol.strip().upper()
    exp_date = datetime.strptime(expiry, "%Y-%m-%d").date()
    for exch in DERIVATIVE_SEGMENTS:
        sub = df[(df[SEG].astype(str) == exch) & (df[SYMBOL].astype(str).str.upper() == symbol)
                 & (df[INSTR].astype(str).isin(OPT_INSTR))].copy()
        if sub.empty:
            continue
        sub["_exp"] = pd.to_datetime(sub[EXPIRY].astype(str), format="%d%m%Y", errors="coerce").dt.date
        sub = sub[sub["_exp"] == exp_date]
        if sub.empty:
            continue
        strikes = pd.to_numeric(sub[STRIKE], errors="coerce") / 100.0
        strikes = sorted(set(strikes.dropna().tolist()))
        if strikes:
            return strikes
    return []


def resolve_instrument(df: pd.DataFrame, exitline_segment: str, symbol: str,
                        expiry: str = None, strike: float = None, option_type: str = None) -> Optional[dict]:
    """Resolve the exact tradeable token for the manually-chosen instrument.
    Returns {segment, token, tradingsymbol} or None if nothing matches —
    never raises, so the route can turn that into a clean 404."""
    symbol = symbol.strip().upper()

    if exitline_segment == "NSE":
        sub = df[(df[SEG].astype(str) == "NSE") & (df[SYMBOL].astype(str).str.upper() == symbol)
                 & (df[INSTR].astype(str).isin(["EQ", "IDX"]))]
        if sub.empty:
            return None
        row = sub.iloc[0]
        return {"segment": "NSE", "token": str(row[TOKEN]), "tradingsymbol": str(row[TRADINGSYM])}

    if not expiry:
        return None
    exp_date = datetime.strptime(expiry, "%Y-%m-%d").date()
    instr_codes = FUT_INSTR if exitline_segment == "FUT" else OPT_INSTR

    for exch in DERIVATIVE_SEGMENTS:
        sub = df[(df[SEG].astype(str) == exch) & (df[SYMBOL].astype(str).str.upper() == symbol)
                 & (df[INSTR].astype(str).isin(instr_codes))].copy()
        if sub.empty:
            continue
        sub["_exp"] = pd.to_datetime(sub[EXPIRY].astype(str), format="%d%m%Y", errors="coerce").dt.date
        sub = sub[sub["_exp"] == exp_date]
        if sub.empty:
            continue

        if exitline_segment == "OPT":
            if strike is None or not option_type:
                return None
            sub["_strike"] = pd.to_numeric(sub[STRIKE], errors="coerce") / 100.0
            sub = sub[(sub["_strike"] == float(strike)) & (sub[OPTTYPE].astype(str).str.upper() == option_type.strip().upper())]
            if sub.empty:
                continue

        row = sub.iloc[0]
        return {"segment": exch, "token": str(row[TOKEN]), "tradingsymbol": str(row[TRADINGSYM])}

    return None


# ---------------------------------------------------------------------------
# Definedge data fetch + orchestration
# ---------------------------------------------------------------------------
async def previous_day_ohlc(definedge, segment: str, token: str) -> dict:
    """Most recent COMPLETED trading day's H/L/C — explicitly excludes
    today's date rather than trusting the daily-bar endpoint to omit an
    in-progress session, since Exitline is meant to be used mid-session."""
    bars = await definedge.daily_history(segment, token, years=1)
    today = datetime.now(IST).date().isoformat()
    past = [b for b in bars if b["date"] < today]
    if not past:
        raise DefinedgeError(f"No previous-day data for {segment}/{token} (illiquid or newly-listed contract?).")
    b = past[-1]
    return {"date": b["date"], "high": b["high"], "low": b["low"], "close": b["close"]}


async def get_or_compute_levels(db, definedge, segment: str, token: str, tradingsymbol: str) -> dict:
    """Camarilla levels are fixed for the day — computed once from the
    previous day's H/L/C and cached per (date, segment, token)."""
    today = datetime.now(IST).date().isoformat()
    key = {"date": today, "segment": segment, "token": token}
    cached = await db.exitline_levels.find_one(key, {"_id": 0})
    if cached:
        return cached

    prev = await previous_day_ohlc(definedge, segment, token)
    levels = compute_camarilla_levels(prev["high"], prev["low"], prev["close"])
    doc = {
        **key,
        "tradingsymbol": tradingsymbol,
        "prev_date": prev["date"],
        "high": prev["high"],
        "low": prev["low"],
        "close": prev["close"],
        "levels": levels,
        "computed_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.exitline_levels.update_one(key, {"$set": doc}, upsert=True)
    return doc


async def build_exitline_response(db, definedge, exitline_segment: str, symbol: str,
                                   expiry: str = None, strike: float = None, option_type: str = None) -> dict:
    master = await definedge._get_all_master()
    resolved = resolve_instrument(master, exitline_segment, symbol, expiry, strike, option_type)
    if not resolved:
        raise DefinedgeError("Instrument not found — check the symbol, expiry, strike, and option type.")

    levels_doc = await get_or_compute_levels(db, definedge, resolved["segment"], resolved["token"], resolved["tradingsymbol"])
    ltp = await definedge.equity_quote(resolved["segment"], resolved["token"])
    zone = classify_and_suggest(levels_doc["levels"], ltp, levels_doc["close"])

    return {
        "segment": exitline_segment,
        "symbol": symbol.strip().upper(),
        "tradingsymbol": resolved["tradingsymbol"],
        "expiry": expiry,
        "strike": strike,
        "option_type": option_type.strip().upper() if option_type else None,
        "prev_date": levels_doc["prev_date"],
        "high": levels_doc["high"],
        "low": levels_doc["low"],
        "close": levels_doc["close"],
        "levels": levels_doc["levels"],
        "ltp": ltp,
        **zone,
    }
