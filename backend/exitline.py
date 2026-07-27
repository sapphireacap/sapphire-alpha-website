"""
Exitline — Camarilla pivot levels + suggested SL/TP for a manually-picked
NSE cash/futures/options instrument. Public Alpha Terminal module (see
exitline_routes.py) — reads use the site's own shared Definedge session,
same pattern as Quant Lab's EWMA/Sharpe tools, no per-visitor broker login.

Flow: segment (NSE/FUT/OPT) -> scrip (+ expiry/strike/CE-PE for FUT/OPT,
always manual, never auto-picked) -> previous day's H/L/C from Definedge
-> Pivot + H1-H5/L1-L5 ladder -> zone classification against live LTP -> SL/TP.

Recalibrated 2026-07-27 to match a real reference chart's exact levels
(verified: Pivot, H4, H3, L4, L3, and the H5/L5 pair all matched the
reference to the cent on a real TCS-EQ example) — this is a different,
well-known Camarilla variant from the textbook R1-R4/S1-S4 scheme this
module used originally: a real central Pivot exists here, and the H/L
divisors are 1.1 divided by 12/6/4/2 rather than the textbook's direct
0.183/0.366/0.55/1.1 multipliers. H4/L4 keep the same structural role the
old R4/S4 breakout boundary had; H3/L3 keep the old R3/S3 trading-zone-edge
role; H1/H2/L1/L2 keep the old R1/R2/S1/S2 momentum-commentary-only role.
H5/L5 are shown on the ladder (matching the reference) but aren't a
signal boundary — real Camarilla practice treats them as rarely-used
extreme/panic targets, and the original zone design was never spec'd
beyond the H4/L4 edge.

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
import asyncio
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
# Level ladder — pure, unit-testable. Verified 2026-07-27 against a real
# reference chart for TCS-EQ (H=2264.30 L=2205.10 C=2254.30): Pivot, H4, H3,
# L4, L3, and H5/L5 all matched the reference to the cent.
# ---------------------------------------------------------------------------
def compute_camarilla_levels(high: float, low: float, close: float) -> dict:
    r = high - low
    h5 = (high / low) * close
    return {
        "H5": h5,
        "H4": close + r * 1.1 / 2,
        "H3": close + r * 1.1 / 4,
        "H2": close + r * 1.1 / 6,
        "H1": close + r * 1.1 / 12,
        "Pivot": (high + low + close) / 3,
        "L1": close - r * 1.1 / 12,
        "L2": close - r * 1.1 / 6,
        "L3": close - r * 1.1 / 4,
        "L4": close - r * 1.1 / 2,
        "L5": 2 * close - h5,
    }


def classify_and_suggest(levels: dict, ltp: float, prev_close: float) -> dict:
    """Zone classification + SL/TP:
      - Beyond H4/L4: Breakout Zone, trend day, no fixed TP, trail the stop.
      - At/between H3-H4 (or L4-L3): Trading Zone edge, mean-reversion
        trigger — short at H3 (SL above H4, TP toward H1/H2/prev close),
        long at L3 (SL below L4, TP toward L1/L2/prev close).
      - Between L3 and H3 but not near either edge: mid-range, no
        standalone trigger — H1/H2/L1/L2 only ever surface as momentum
        commentary here, never a separate signal. H5/L5 are shown on the
        ladder but are never a signal boundary either way.
    """
    H4, H3, H2, H1 = levels["H4"], levels["H3"], levels["H2"], levels["H1"]
    L1, L2, L3, L4 = levels["L1"], levels["L2"], levels["L3"], levels["L4"]

    if ltp > H4:
        return {
            "zone": "breakout_upper",
            "zone_label": "Breakout Zone (Upper)",
            "bias": "Long",
            "sl": round(H4, 2),
            "tp": None,
            "tp_alt": None,
            "trail_stop": True,
            "reason": f"Broke above H4 ({H4:.2f}) — trend day, mean-reversion invalidated. Buy the breakout (or on retest of H4); no fixed target, trail the stop.",
            "commentary": None,
        }
    if ltp < L4:
        return {
            "zone": "breakout_lower",
            "zone_label": "Breakout Zone (Lower)",
            "bias": "Short",
            "sl": round(L4, 2),
            "tp": None,
            "tp_alt": None,
            "trail_stop": True,
            "reason": f"Broke below L4 ({L4:.2f}) — trend day, mean-reversion invalidated. Short the breakdown (or on retest of L4); no fixed target, trail the stop.",
            "commentary": None,
        }
    if H3 <= ltp <= H4:
        return {
            "zone": "trading_upper",
            "zone_label": "Trading Zone — At H3",
            "bias": "Short",
            "sl": round(H4 * 1.001, 2),
            "tp": round(H1, 2),
            "tp_alt": round(H2, 2),
            "trail_stop": False,
            "reason": f"At H3 ({H3:.2f}) — short bias, TP toward H1/H2 or previous close ({prev_close:.2f}), SL just above H4.",
            "commentary": None,
        }
    if L4 <= ltp <= L3:
        return {
            "zone": "trading_lower",
            "zone_label": "Trading Zone — At L3",
            "bias": "Long",
            "sl": round(L4 * 0.999, 2),
            "tp": round(L1, 2),
            "tp_alt": round(L2, 2),
            "trail_stop": False,
            "reason": f"At L3 ({L3:.2f}) — long bias, TP toward L1/L2 or previous close ({prev_close:.2f}), SL just below L4.",
            "commentary": None,
        }

    # Mid-range (strictly inside L3..H3): no standalone trigger. H1/H2/L1/L2
    # are checkpoints only — surfaced as momentum commentary on whichever one
    # price currently sits closest to.
    checkpoints = [("H2", H2), ("H1", H1), ("L1", L1), ("L2", L2)]
    label, val = min(checkpoints, key=lambda kv: abs(ltp - kv[1]))
    above = ltp >= val
    if label in ("H1", "H2"):
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
        "reason": "Inside L3/H3 — range-bound, no standalone entry trigger at current levels.",
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
# Intraday chart — today's session, aggregated from real 1-minute OHLC (not
# just close) into a caller-chosen bucket size, for Exitline's candlestick
# chart with the level ladder overlaid as reference lines.
# ---------------------------------------------------------------------------
VALID_INTERVALS = (1, 3, 5, 15, 30, 60)


def _aggregate_bars(bars: list, minutes: int) -> list:
    """Group 1-minute bars into `minutes`-wide buckets aligned to market
    open (09:15) — bucket N covers [09:15 + N*minutes, 09:15 + (N+1)*minutes)."""
    buckets = {}
    for b in bars:
        try:
            dt = datetime.strptime(b["ts"], "%d%m%Y%H%M")
        except ValueError:
            continue
        minutes_since_open = (dt.hour * 60 + dt.minute) - (9 * 60 + 15)
        if minutes_since_open < 0:
            continue
        bucket_start = dt.replace(hour=9, minute=15, second=0, microsecond=0) + timedelta(minutes=minutes * (minutes_since_open // minutes))
        key = bucket_start.strftime("%d%m%Y%H%M")
        if key not in buckets:
            buckets[key] = {"ts": key, "open": b["open"], "high": b["high"], "low": b["low"], "close": b["close"]}
        else:
            bucket = buckets[key]
            bucket["high"] = max(bucket["high"], b["high"])
            bucket["low"] = min(bucket["low"], b["low"])
            bucket["close"] = b["close"]  # bars arrive time-sorted, so the latest overwrite is the bucket's real close
    return [buckets[k] for k in sorted(buckets)]


async def intraday_chart(definedge, segment: str, token: str, interval_minutes: int = 5, target_date=None) -> list:
    """`target_date`'s session as `interval_minutes`-wide candles (defaults
    to today) — best-effort: an empty list (holiday, or an illiquid
    contract with zero prints that day) is a normal, valid result, not an
    error, and must never take down the rest of the /levels response (the
    ladder doesn't depend on this at all).

    Caller picks `target_date` — build_exitline_response() passes the last
    COMPLETED session's date pre-market, so the chart keeps showing that
    session (never goes blank) right up until the next one actually opens,
    rather than resetting to an empty chart the instant the calendar date
    rolls over at midnight."""
    now = datetime.now(IST)
    target_date = target_date or now.date()
    date_str = target_date.strftime("%d%m%Y")
    frm = f"{date_str}0915"
    to = now.strftime("%d%m%Y%H%M") if target_date == now.date() else f"{date_str}1530"
    try:
        bars = await definedge.minute_ohlc(segment, token, frm=frm, to=to)
    except DefinedgeError as e:
        logger.warning("Exitline: intraday chart unavailable for %s/%s: %s", segment, token, e)
        return []
    agg = _aggregate_bars(bars, interval_minutes)
    out = []
    for b in agg:
        try:
            dt = datetime.strptime(b["ts"], "%d%m%Y%H%M").replace(tzinfo=IST)
            label = dt.strftime("%H:%M")
            time = int(dt.timestamp())
        except ValueError:
            label, time = b["ts"], None
        out.append({"t": label, "time": time, "open": b["open"], "high": b["high"], "low": b["low"], "close": b["close"]})
    return out


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
                                   expiry: str = None, strike: float = None, option_type: str = None,
                                   interval_minutes: int = 5) -> dict:
    master = await definedge._get_all_master()
    resolved = resolve_instrument(master, exitline_segment, symbol, expiry, strike, option_type)
    if not resolved:
        raise DefinedgeError("Instrument not found — check the symbol, expiry, strike, and option type.")

    levels_doc = await get_or_compute_levels(db, definedge, resolved["segment"], resolved["token"], resolved["tradingsymbol"])

    # Pre-market, the chart should keep showing the last COMPLETED session
    # (never go blank) right up until the next one actually opens — same
    # "most recent real session" date the ladder's own H/L/C already uses.
    now = datetime.now(IST)
    is_premarket = now.hour * 60 + now.minute < 9 * 60 + 15
    chart_date = datetime.strptime(levels_doc["prev_date"], "%Y-%m-%d").date() if is_premarket else now.date()

    ltp, chart = await asyncio.gather(
        definedge.equity_quote(resolved["segment"], resolved["token"]),
        intraday_chart(definedge, resolved["segment"], resolved["token"], interval_minutes, chart_date),
    )
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
        "chart": chart,
        **zone,
    }
