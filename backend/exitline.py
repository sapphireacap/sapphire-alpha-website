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
# Intraday chart — aggregated from real 1-minute OHLC (not just close) into
# a caller-chosen bucket size, for Exitline's candlestick chart with each
# session's own level ladder overlaid as reference lines.
# ---------------------------------------------------------------------------
VALID_INTERVALS = (1, 3, 5, 15, 30, 60)
HISTORY_SESSIONS = 30  # trading days of chart + per-session levels Exitline shows


def _aggregate_bars(bars: list, minutes: int, open_hour: int = 9, open_minute: int = 15) -> list:
    """Group 1-minute bars into `minutes`-wide buckets aligned to the
    market's own open (09:15 IST for NSE; callers on a different exchange
    calendar, e.g. US Exitline's 09:30 ET, pass their own open_hour/
    open_minute) — bucket N covers [open + N*minutes, open + (N+1)*minutes).
    Each bar's own calendar date drives its bucket alignment, so bars
    spanning many different days (a multi-session history fetch, not just
    one day) still bucket correctly per-day without any extra grouping
    step — every bucket key also carries its own `date` for the caller."""
    buckets = {}
    for b in bars:
        try:
            dt = datetime.strptime(b["ts"], "%d%m%Y%H%M")
        except ValueError:
            continue
        minutes_since_open = (dt.hour * 60 + dt.minute) - (open_hour * 60 + open_minute)
        if minutes_since_open < 0:
            continue
        bucket_start = dt.replace(hour=open_hour, minute=open_minute, second=0, microsecond=0) + timedelta(minutes=minutes * (minutes_since_open // minutes))
        key = bucket_start.strftime("%d%m%Y%H%M")
        if key not in buckets:
            buckets[key] = {"ts": key, "date": bucket_start.date().isoformat(), "_sort": bucket_start,
                             "open": b["open"], "high": b["high"], "low": b["low"], "close": b["close"]}
        else:
            bucket = buckets[key]
            bucket["high"] = max(bucket["high"], b["high"])
            bucket["low"] = min(bucket["low"], b["low"])
            bucket["close"] = b["close"]  # bars arrive time-sorted, so the latest overwrite is the bucket's real close
    # Sort by the real parsed datetime, NOT the "ts" string -- DDMMYYYYHHMM
    # sorts correctly within a single day (the original single-day use
    # case, where DD/MM/YYYY are constant), but lexicographic string sort
    # scrambles month/day boundaries once bars span multiple months (a real
    # bug hit live: "01082026..." (Aug 1) sorts BEFORE "31072026..." (Jul
    # 31) as strings, since '0' < '3' in the DAY digit alone) -- exactly
    # the multi-session case this function now also serves.
    ordered = sorted(buckets.values(), key=lambda v: v["_sort"])
    for v in ordered:
        del v["_sort"]
    return ordered


def build_session_ladder(daily_bars: list, now_local: datetime, session_open_minutes: int, window: int = HISTORY_SESSIONS) -> list:
    """Pure, unit-testable: given real daily bars (each {date: 'YYYY-MM-DD',
    high, low, close}, ascending, real trading days only) and the caller's
    own "now" already converted to the exchange's local wall-clock time,
    returns up to `window` {date, prev_date, high, low, close, levels}
    entries, ascending by date — one per session, each with its OWN
    Camarilla ladder computed from THAT session's own previous-day H/L/C
    (levels are NOT the same day to day, unlike a naive "today's levels"
    read).

    The most recent entry is the ACTIVE session: if the exchange's session
    hasn't opened yet today (now_local's minute-of-day < session_open_minutes),
    that's the last COMPLETED day, not today -- today's own levels (though
    already mathematically computable from yesterday's close) aren't shown
    until the session they actually apply to has started. This is the fix
    for a real gap: previously, levels flipped to "today's" the instant the
    calendar date rolled over at midnight, hours before the market itself
    opened and while the chart was still (correctly) showing yesterday's
    session -- levels and chart could disagree about which session was
    current."""
    if not daily_bars:
        return []
    today_str = now_local.date().isoformat()
    minute_of_day = now_local.hour * 60 + now_local.minute
    session_open_today = minute_of_day >= session_open_minutes

    completed = [b for b in daily_bars if b["date"] < today_str]
    if not completed:
        return []

    session_dates = ([today_str] if session_open_today else []) + [b["date"] for b in reversed(completed)]
    session_dates = session_dates[:window]

    out = []
    for date in session_dates:
        prev_bar = next((b for b in reversed(completed) if b["date"] < date), None)
        if prev_bar is None:
            continue
        levels = compute_camarilla_levels(prev_bar["high"], prev_bar["low"], prev_bar["close"])
        out.append({
            "date": date, "prev_date": prev_bar["date"],
            "high": prev_bar["high"], "low": prev_bar["low"], "close": prev_bar["close"],
            "levels": levels,
        })
    return list(reversed(out))  # ascending -- oldest session first, active session last


async def multi_session_chart(definedge, segment: str, token: str, sessions: list,
                               interval_minutes: int, open_hour: int = 9, open_minute: int = 15) -> list:
    """One continuous candle series spanning every session in `sessions`
    (ascending), each bar tagged with its own `date` so the frontend can
    match it to that day's own level ladder -- best-effort: an empty list
    (illiquid contract, no prints in the window) is a normal, valid result,
    not an error, and must never take down the rest of the /levels
    response (the ladder doesn't depend on this at all)."""
    if not sessions:
        return []
    now = datetime.now(IST)
    frm = f"{datetime.strptime(sessions[0]['date'], '%Y-%m-%d').strftime('%d%m%Y')}0000"
    to = now.strftime("%d%m%Y%H%M")
    try:
        bars = await definedge.minute_ohlc(segment, token, frm=frm, to=to)
    except DefinedgeError as e:
        logger.warning("Exitline: multi-session chart unavailable for %s/%s: %s", segment, token, e)
        return []
    agg = _aggregate_bars(bars, interval_minutes, open_hour, open_minute)
    out = []
    for b in agg:
        try:
            dt = datetime.strptime(b["ts"], "%d%m%Y%H%M").replace(tzinfo=IST)
            label = dt.strftime("%H:%M")
            time = int(dt.timestamp())
        except ValueError:
            label, time = b["ts"], None
        out.append({"t": label, "time": time, "date": b["date"],
                     "open": b["open"], "high": b["high"], "low": b["low"], "close": b["close"]})
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


async def build_exitline_response(db, definedge, exitline_segment: str, symbol: str,
                                   expiry: str = None, strike: float = None, option_type: str = None,
                                   interval_minutes: int = 5) -> dict:
    master = await definedge._get_all_master()
    resolved = resolve_instrument(master, exitline_segment, symbol, expiry, strike, option_type)
    if not resolved:
        raise DefinedgeError("Instrument not found — check the symbol, expiry, strike, and option type.")

    # Camarilla levels are cheap pure math (see build_session_ladder) --
    # recomputed fresh from real daily bars every request instead of
    # cached in Mongo, since there's no expensive work worth caching here
    # (one daily_history call, same one previous_day_ohlc used to make
    # anyway) and a cache keyed only by "today" was exactly what let
    # levels flip to the new session before that session had actually
    # opened (see build_session_ladder's docstring).
    daily_bars = await definedge.daily_history(resolved["segment"], resolved["token"], years=1)
    now = datetime.now(IST)
    sessions = build_session_ladder(daily_bars, now, session_open_minutes=9 * 60 + 15)
    if not sessions:
        raise DefinedgeError(f"No previous-day data for {resolved['segment']}/{resolved['token']} (illiquid or newly-listed contract?).")
    active = sessions[-1]

    # equity_quote and multi_session_chart are independent failures: a
    # missing live quote (market closed -- Definedge returns no `ltp`
    # field for an option/future outside trading hours, confirmed live)
    # must not also discard the chart or the levels ladder, which don't
    # depend on it at all. gather(..., return_exceptions=True) keeps one
    # from taking the other down; multi_session_chart already fails open
    # to [] internally and never actually raises, so only equity_quote
    # needs handling here.
    ltp_or_exc, chart = await asyncio.gather(
        definedge.equity_quote(resolved["segment"], resolved["token"]),
        multi_session_chart(definedge, resolved["segment"], resolved["token"], sessions, interval_minutes),
        return_exceptions=True,
    )
    if isinstance(ltp_or_exc, DefinedgeError):
        logger.warning("Exitline: live quote unavailable for %s/%s: %s",
                        resolved["segment"], resolved["token"], ltp_or_exc)
        ltp = None
        zone = {
            "zone": None, "zone_label": "Live Price Unavailable", "bias": "Neutral",
            "sl": None, "tp": None, "tp_alt": None, "trail_stop": False,
            "reason": "No live quote right now (market may be closed) — levels are still shown "
                      "against yesterday's close; zone/SL/TP need a live price.",
            "commentary": None,
        }
    elif isinstance(ltp_or_exc, BaseException):
        raise ltp_or_exc
    else:
        ltp = ltp_or_exc
        zone = classify_and_suggest(active["levels"], ltp, active["close"])

    return {
        "segment": exitline_segment,
        "symbol": symbol.strip().upper(),
        "tradingsymbol": resolved["tradingsymbol"],
        "expiry": expiry,
        "strike": strike,
        "option_type": option_type.strip().upper() if option_type else None,
        "prev_date": active["prev_date"],
        "high": active["high"],
        "low": active["low"],
        "close": active["close"],
        "levels": active["levels"],
        "active_date": active["date"],
        "sessions": sessions,
        "ltp": ltp,
        "chart": chart,
        **zone,
    }
