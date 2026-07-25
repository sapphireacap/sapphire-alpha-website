"""
Prism Alpha — P&F pattern-based Nifty index options signal system (Black Box).

READ-ONLY, SIGNAL-LOGGING ONLY. This module never places, modifies, or
cancels an order. It only calls Definedge's existing read-only market-data
methods (minute/day history, quote, symbol master) already used elsewhere in
this codebase (definedge_service.py) — see the endpoint list in that file's
module docstring and in this module's evaluate_prism_alpha() docstring.

Every pattern definition below is derived directly from Definedge's own
published library (definedgesecurities.com/library/...), worked through
column-by-column against their exact wording — not textbook P&F. Two
conditions (XO Zone's numeric "setting", and the specific dual-EMA-average
RSI variant) are NOT in Definedge's public docs — those are best-effort
interpretations, explicitly flagged below, meant to be validated against a
live Definedge chart during the CE-only dry run. If they can't be
reconciled with real platform behavior, the instruction was to remove them
from entry logic entirely rather than ship a guess permanently.

P&F construction: percentage-box log grid, box 1%, reversal 3 boxes — same
box-math approach as the existing pnf_trend() in definedge_service.py, but
unlike that function (which collapses to a single Bullish/Bearish/Neutral
label), this engine retains the full column history, since every pattern
here (Low/High Pole, Anchor Column, AFT, Turtle Breakout, Triple Top/Bottom,
Double Top/Bottom) needs to inspect actual column structure.
"""
import logging
import math
import uuid
from datetime import datetime, timezone, timedelta

import httpx
import pandas as pd

from definedge_service import DefinedgeService, DefinedgeError, DATA_BASE, NIFTY_SPOT_TOKEN

logger = logging.getLogger(__name__)

IST = timezone(timedelta(hours=5, minutes=30))

# ---------------------------------------------------------------------------
# Strategy parameters (from the approved spec)
# ---------------------------------------------------------------------------
BOX_PCT = 0.01                 # 1%
REVERSAL_BOXES = 3              # 3 boxes (~3%)
ANCHOR_MIN_BOXES = 15           # ">15 boxes" per Definedge's Anchor Column definition
POLE_MIN_BOXES = 5              # "more than 5 boxes after the double bottom/top sell/buy"
POLE_MIN_RETRACE = 0.5          # "more than 50% retracement"
TURTLE_LOOKBACK_COLUMNS = 5     # "five X's/O's as a default period"
XO_ZONE_LOOKBACK = 10           # best-effort — see module docstring
RSI_PERIOD = 7
RSI_AVG1_PERIOD = 5             # EMA of RSI(7) — best-effort, "Average Period 1"
RSI_AVG2_PERIOD = 14            # EMA of RSI(7) — best-effort, "Average Period 2" (logged, NOT gated on: "Avg Line 2 disabled")
ENTRY_RSI_RANGE = (20, 40)      # applies to BOTH CE and PE — see note below
TARGET_POINTS = 60              # Nifty index points — the one thing still measured on the underlying

# The P&F chart, patterns, XO Zone, RSI and stop-loss all run on the OPTION'S
# OWN premium chart, not the underlying index — confirmed against a live
# Definedge screenshot of an actual 23900PE chart (H3/pivot/L3 levels were
# clearly premium-scale, ~₹95-140, not index-scale). This was a real
# correction mid-build: the original version ran everything on the Nifty
# index instead, which made the spec's "₹1 below the low" stop-loss offset
# essentially meaningless (₹1 on a ~24000 index level). On an option's own
# chart that same offset is a real, sensible buffer.
#
# Consequence: buying either a CE or a PE only ever profits from THAT
# option's OWN premium rising (you're never short), so there is no
# bearish/mirror pattern needed for either side — both directions watch
# their own chart for the exact same bullish setup (Low Pole + bullish
# follow-through + XO Zone turning positive + RSI in ENTRY_RSI_RANGE), per
# explicit user instruction. High Pole / Triple Bottom Sell / bearish Turtle
# Breakout / Double Top Buy trailing-stop are no longer used for entry or
# exit — the functions stay in this module as correct, tested, general P&F
# pattern implementations, just unused by Prism Alpha's current logic.


# ---------------------------------------------------------------------------
# Point & Figure engine — retains full column history (pure, unit-testable)
# ---------------------------------------------------------------------------
def _box_level(price: float, box_pct: float = BOX_PCT) -> int:
    """Same log-grid box-level function as pnf_trend() in definedge_service.py,
    reused for consistency between the two P&F approximations in this codebase."""
    return math.floor(math.log(price) / math.log(1.0 + box_pct))


def _bar_ticks(bar: dict):
    """Feed both the high and low of a bar into the box state machine (not
    just the close) so a column's high/low is more realistic than a
    close-only series would give — order depends on whether the bar closed
    up or down (standard P&F convention: assume the bar moved toward its
    close, so a down bar is assumed to have touched its high before its
    low, and vice versa)."""
    o, h, l, c = bar["open"], bar["high"], bar["low"], bar["close"]
    ts = bar["ts"]
    if c >= o:
        return [(ts, l), (ts, h)]
    return [(ts, h), (ts, l)]


def build_pnf_columns(bars: list, box_pct: float = BOX_PCT, reversal_boxes: int = REVERSAL_BOXES) -> list:
    """bars: chronological [{ts, open, high, low, close}, ...] (1-minute bars).
    Returns a chronological list of column dicts:
      {direction: 'X'|'O', high_level, low_level, high_price, low_price,
       box_count, start_ts, end_ts}
    box_count = high_level - low_level (integer box-levels, NOT a box-price
    delta) — what every ">15 boxes" / ">5 boxes" threshold in this module
    compares against.
    """
    bars = [b for b in bars if b.get("close") and float(b["close"]) > 0]
    if len(bars) < 2:
        return []

    samples = []
    for b in bars:
        samples.extend(_bar_ticks(b))

    columns = []
    direction = None
    base_level = _box_level(float(samples[0][1]), box_pct)
    base_price = float(samples[0][1])
    base_ts = samples[0][0]

    cur_high_level = cur_low_level = base_level
    cur_high_price = cur_low_price = base_price
    cur_start_ts = base_ts
    cur_end_ts = base_ts

    def close_column(end_ts):
        columns.append({
            "direction": direction,
            "high_level": cur_high_level,
            "low_level": cur_low_level,
            "high_price": cur_high_price,
            "low_price": cur_low_price,
            "box_count": cur_high_level - cur_low_level,
            "start_ts": cur_start_ts,
            "end_ts": end_ts,
        })

    for ts, raw_p in samples[1:]:
        p = float(raw_p)
        lv = _box_level(p, box_pct)

        if direction is None:
            if lv >= base_level + 1:
                direction = "X"
                cur_low_level, cur_high_level = base_level, lv
                cur_low_price, cur_high_price = base_price, p
                cur_start_ts = ts
            elif lv <= base_level - 1:
                direction = "O"
                cur_high_level, cur_low_level = base_level, lv
                cur_high_price, cur_low_price = base_price, p
                cur_start_ts = ts
            cur_end_ts = ts
            continue

        if direction == "X":
            if lv > cur_high_level:
                cur_high_level, cur_high_price = lv, p
                cur_end_ts = ts
            elif lv <= cur_high_level - reversal_boxes:
                close_column(ts)
                # new O column shares its top boundary with the old X column's high
                old_high_level, old_high_price = cur_high_level, cur_high_price
                direction = "O"
                cur_high_level, cur_high_price = old_high_level, old_high_price
                cur_low_level, cur_low_price = lv, p
                cur_start_ts = ts
                cur_end_ts = ts
        else:  # O
            if lv < cur_low_level:
                cur_low_level, cur_low_price = lv, p
                cur_end_ts = ts
            elif lv >= cur_low_level + reversal_boxes:
                close_column(ts)
                old_low_level, old_low_price = cur_low_level, cur_low_price
                direction = "X"
                cur_low_level, cur_low_price = old_low_level, old_low_price
                cur_high_level, cur_high_price = lv, p
                cur_start_ts = ts
                cur_end_ts = ts

    if direction is not None:
        close_column(cur_end_ts)

    return columns


# ---------------------------------------------------------------------------
# Pattern detectors — pure functions over a column list.
# Each returns None if the pattern doesn't fire at index i, else a dict with
# whatever fields the caller needs (e.g. Low Pole returns the pole column's
# index, used both for "occurred after" ordering and the stop-loss anchor).
# Column alternation (X,O,X,O,...) is guaranteed by build_pnf_columns, so a
# pattern's own direction checks are enough to imply the neighbors' directions.
# ---------------------------------------------------------------------------
def is_double_top_buy(columns: list, i: int) -> bool:
    """Column i (must be X) breaks above the previous X column's high."""
    if i < 2 or columns[i]["direction"] != "X":
        return False
    prev_x = columns[i - 2]
    if prev_x["direction"] != "X":
        return False
    return columns[i]["high_level"] > prev_x["high_level"]


def is_double_bottom_sell(columns: list, i: int) -> bool:
    """Mirror of is_double_top_buy."""
    if i < 2 or columns[i]["direction"] != "O":
        return False
    prev_o = columns[i - 2]
    if prev_o["direction"] != "O":
        return False
    return columns[i]["low_level"] < prev_o["low_level"]


def find_triple_top_buy(columns: list, i: int) -> bool:
    """5 columns ending at i: X,O,X,O,X. col(i-4).high == col(i-2).high
    (shared resistance), and col i breaks above that level."""
    if i < 4:
        return False
    c0, c2, c4 = columns[i - 4], columns[i - 2], columns[i]
    if c0["direction"] != "X" or c2["direction"] != "X" or c4["direction"] != "X":
        return False
    if c0["high_level"] != c2["high_level"]:
        return False
    return c4["high_level"] > c2["high_level"]


def find_triple_bottom_sell(columns: list, i: int) -> bool:
    """Mirror of find_triple_top_buy."""
    if i < 4:
        return False
    c0, c2, c4 = columns[i - 4], columns[i - 2], columns[i]
    if c0["direction"] != "O" or c2["direction"] != "O" or c4["direction"] != "O":
        return False
    if c0["low_level"] != c2["low_level"]:
        return False
    return c4["low_level"] < c2["low_level"]


def find_low_pole(columns: list, i: int):
    """4 columns ending at i: O,X,O,X. col(i-1) is a Double Bottom Sell
    relative to col(i-3) AND continues more than POLE_MIN_BOXES boxes past
    that breakdown level; col(i) retraces more than 50% of col(i-1)'s range.
    Returns {'pole_index': i-1} if it fires, else None — pole_index is the
    "O-column in which the Low Pole occurred" the spec's stop-loss anchors to."""
    if i < 3:
        return None
    c0, c1, c2, c3 = columns[i - 3], columns[i - 2], columns[i - 1], columns[i]
    if c0["direction"] != "O" or c1["direction"] != "X" or c2["direction"] != "O" or c3["direction"] != "X":
        return None
    if c2["low_level"] >= c0["low_level"]:
        return None  # not even a Double Bottom Sell
    if (c0["low_level"] - c2["low_level"]) <= POLE_MIN_BOXES:
        return None
    pole_range = c2["high_level"] - c2["low_level"]
    if pole_range <= 0:
        return None
    retrace = (c3["high_level"] - c2["low_level"]) / pole_range
    if retrace <= POLE_MIN_RETRACE:
        return None
    return {"pole_index": i - 1}


def find_high_pole(columns: list, i: int):
    """Mirror of find_low_pole. Returns {'pole_index': i-1}."""
    if i < 3:
        return None
    c0, c1, c2, c3 = columns[i - 3], columns[i - 2], columns[i - 1], columns[i]
    if c0["direction"] != "X" or c1["direction"] != "O" or c2["direction"] != "X" or c3["direction"] != "O":
        return None
    if c2["high_level"] <= c0["high_level"]:
        return None
    if (c2["high_level"] - c0["high_level"]) <= POLE_MIN_BOXES:
        return None
    pole_range = c2["high_level"] - c2["low_level"]
    if pole_range <= 0:
        return None
    retrace = (c2["high_level"] - c3["low_level"]) / pole_range
    if retrace <= POLE_MIN_RETRACE:
        return None
    return {"pole_index": i - 1}


def is_anchor_column(columns: list, i: int, direction: str) -> bool:
    c = columns[i]
    return c["direction"] == direction and c["box_count"] > ANCHOR_MIN_BOXES


def find_aft_immediate(columns: list, i: int, direction: str) -> bool:
    """3 columns ending at i: anchor(direction) -> opposite -> direction,
    where col i breaks the anchor's extreme (a Double Top/Bottom relative to
    the anchor column, with nothing else of `direction` in between —
    that's what makes it "immediate")."""
    if i < 2:
        return False
    anchor, mid, brk = columns[i - 2], columns[i - 1], columns[i]
    if not is_anchor_column(columns, i - 2, direction):
        return False
    opposite = "O" if direction == "X" else "X"
    if mid["direction"] != opposite or brk["direction"] != direction:
        return False
    if direction == "X":
        return brk["high_level"] > anchor["high_level"]
    return brk["low_level"] < anchor["low_level"]


def find_turtle_breakout(columns: list, i: int, direction: str) -> bool:
    """Current column i (must be `direction`) breaks the extreme of the
    preceding TURTLE_LOOKBACK_COLUMNS columns of the same direction."""
    if columns[i]["direction"] != direction:
        return False
    same_dir = [c for c in columns[:i] if c["direction"] == direction]
    if len(same_dir) < TURTLE_LOOKBACK_COLUMNS:
        return False
    lookback = same_dir[-TURTLE_LOOKBACK_COLUMNS:]
    if direction == "X":
        return columns[i]["high_level"] > max(c["high_level"] for c in lookback)
    return columns[i]["low_level"] < min(c["low_level"] for c in lookback)


# ---------------------------------------------------------------------------
# Indicators — XO Zone and RSI are BEST-EFFORT (see module docstring): the
# exact Definedge formulas for these two aren't in public docs. Both are
# computed and logged for every signal so they can be checked against a live
# Definedge chart during the CE-only dry run; drop from entry logic if they
# don't reconcile with real platform behavior.
# ---------------------------------------------------------------------------
def xo_zone_series(columns: list, lookback: int = XO_ZONE_LOOKBACK) -> list:
    """Rolling (total X-boxes - total O-boxes) over the trailing `lookback`
    columns, one value per column index (aligned to `columns`)."""
    values = []
    for i in range(len(columns)):
        window = columns[max(0, i - lookback + 1):i + 1]
        x_boxes = sum(c["box_count"] for c in window if c["direction"] == "X")
        o_boxes = sum(c["box_count"] for c in window if c["direction"] == "O")
        values.append(x_boxes - o_boxes)
    return values


def xo_zone_turned(columns: list, lookback: int = XO_ZONE_LOOKBACK) -> str:
    """'positive' | 'negative' | None — whether the zone crossed zero on the
    newest column (vs. its value one column back)."""
    series = xo_zone_series(columns, lookback)
    if len(series) < 2:
        return None
    prev, cur = series[-2], series[-1]
    if prev <= 0 < cur:
        return "positive"
    if prev >= 0 > cur:
        return "negative"
    return None


def _ema(values: list, period: int):
    vals = [v for v in values if v is not None]
    if len(vals) < period:
        return None
    k = 2.0 / (period + 1)
    e = sum(vals[:period]) / period
    for v in vals[period:]:
        e = v * k + e * (1 - k)
    return e


def compute_rsi_series(closes: list, period: int = RSI_PERIOD) -> list:
    """Wilder-smoothed RSI, aligned to `closes` (leading Nones where there
    isn't enough data yet for the first average)."""
    if len(closes) < period + 1:
        return [None] * len(closes)
    diffs = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
    gains = [max(d, 0.0) for d in diffs]
    losses = [max(-d, 0.0) for d in diffs]

    rsis = [None] * period  # closes[0..period-1] have no RSI yet
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    rsis.append(100.0 if avg_loss == 0 else 100.0 - 100.0 / (1.0 + avg_gain / avg_loss))

    for i in range(period, len(diffs)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        rsis.append(100.0 if avg_loss == 0 else 100.0 - 100.0 / (1.0 + avg_gain / avg_loss))

    return rsis


def compute_rsi_snapshot(closes: list) -> dict:
    """Latest RSI(7) value plus the two best-effort EMA overlays, all logged
    into conditions_met for audit — entry logic only gates on raw RSI7."""
    rsi_series = compute_rsi_series(closes, RSI_PERIOD)
    rsi7 = rsi_series[-1] if rsi_series else None
    return {
        "rsi7": rsi7,
        "rsi_avg1_ema5": _ema(rsi_series, RSI_AVG1_PERIOD),
        "rsi_avg2_ema14": _ema(rsi_series, RSI_AVG2_PERIOD),
    }


# ---------------------------------------------------------------------------
# Definedge data access — READ-ONLY. Every call below hits an endpoint
# already used elsewhere in definedge_service.py (minute history, symbol
# master); nothing new is introduced, and no order-related endpoint is ever
# referenced. See the endpoint list in evaluate_prism_alpha()'s docstring.
# ---------------------------------------------------------------------------
async def fetch_minute_bars(definedge, segment: str, token: str, frm: str = None, to: str = None) -> list:
    """Full OHLC 1-minute bars — unlike DefinedgeService._closes() (which
    keeps only the close), stop/target breach here must be checked against
    bar high/low, not just close, per the spec ("trades through the current
    stop or target level"). Same endpoint/response format as _closes()."""
    session = await definedge._session_key()
    now = datetime.now(IST)
    if frm is None:
        frm = now.replace(hour=9, minute=15, second=0).strftime("%d%m%Y%H%M")
    if to is None:
        to = now.strftime("%d%m%Y%H%M")
    url = f"{DATA_BASE}/history/{segment}/{token}/minute/{frm}/{to}"
    async with httpx.AsyncClient(timeout=45) as c:
        r = await c.get(url, headers={"Authorization": session})
    if r.status_code == 401:
        raise DefinedgeError("Definedge session expired. Please login again (OTP).")
    if r.status_code != 200:
        raise DefinedgeError(f"History failed ({r.status_code}) for {token}.")
    bars = []
    for line in r.text.strip().splitlines():
        parts = line.split(",")
        if len(parts) < 5:
            continue
        try:
            # Definedge's ts is "ddmmyyyyHHMM" — day-first, so sorting the raw
            # string is NOT chronological (e.g. "01072026..." < "02062026..."
            # lexicographically despite June 2 preceding July 1). Caught live
            # against real history: two weeks of real bars produced column
            # start/end timestamps running backwards until this was parsed
            # into an actual datetime for sorting instead.
            dt = datetime.strptime(parts[0], "%d%m%Y%H%M").replace(tzinfo=IST)
            bars.append({
                "ts": parts[0],
                "dt": dt,
                "open": float(parts[1]),
                "high": float(parts[2]),
                "low": float(parts[3]),
                "close": float(parts[4]),
            })
        except ValueError:
            continue
    bars.sort(key=lambda b: b["dt"])
    return bars


def resolve_atm_option_tokens(df: pd.DataFrame, atm: int) -> dict:
    """Nearest weekly Nifty expiry (via DefinedgeService._pick_expiry's
    Mon/Tue-roll rule, reused directly — not duplicated) + CE/PE tokens for
    a single ATM strike. Same nsefno master schema as
    DefinedgeService._resolve_tokens() (definedge_service.py:263), which is
    hardcoded to ATM+/-200 for the straddle and not reusable as-is here."""
    SEG, TOKEN, SYMBOL, INSTR, EXPIRY, OPTTYPE, STRIKE = 0, 1, 2, 4, 5, 8, 9
    sub = df[(df[SYMBOL].astype(str) == "NIFTY")
             & (df[INSTR].astype(str) == "OPTIDX")
             & (df[OPTTYPE].astype(str).isin(["CE", "PE"]))].copy()
    if sub.empty:
        raise DefinedgeError("No NIFTY index options (OPTIDX) found in master.")

    sub["_strike"] = pd.to_numeric(sub[STRIKE], errors="coerce") / 100.0
    sub["_exp"] = pd.to_datetime(sub[EXPIRY].astype(str), format="%d%m%Y", errors="coerce").dt.date
    sub = sub.dropna(subset=["_strike", "_exp"])

    today = datetime.now(IST).date()
    expiry = DefinedgeService._pick_expiry(sorted(set(sub["_exp"].tolist())), today)
    if expiry is None:
        raise DefinedgeError("No valid NIFTY expiry found in master.")

    out = {"expiry": expiry.isoformat()}
    for opt in ("CE", "PE"):
        row = sub[(sub["_strike"] == float(atm)) & (sub["_exp"] == expiry) & (sub[OPTTYPE].astype(str) == opt)]
        if row.empty:
            raise DefinedgeError(f"Missing {atm} {opt} for expiry {expiry.isoformat()}.")
        out[opt] = str(row.iloc[0][TOKEN])
    return out


# ---------------------------------------------------------------------------
# Orchestration — the single entry point called every poll cycle. Stateless
# and idempotent by design: rebuilds the full column history fresh each
# call rather than tracking incremental state, so there's nothing that can
# drift out of sync between polls.
# ---------------------------------------------------------------------------
HISTORY_LOOKBACK_DAYS = 90  # matches the window already dry-run tested; long
                             # enough that multi-day patterns (Anchor Column,
                             # Turtle Breakout's 5-column lookback, Triple Top
                             # comparisons) see real prior structure, not just
                             # today's columns in isolation.


def _parse_ts(ts: str) -> datetime:
    return datetime.strptime(ts, "%d%m%Y%H%M").replace(tzinfo=IST)


def _is_today(ts: str, today_iso: str) -> bool:
    return _parse_ts(ts).date().isoformat() == today_iso


async def _evaluate_entry(db, definedge, today_iso: str, direction: str) -> dict:
    """direction: 'CE' or 'PE' — which option's own chart to analyze. Both
    use the identical bullish setup: Low Pole + bullish follow-through +
    XO Zone-turned-positive + RSI in ENTRY_RSI_RANGE, all computed on that
    option's own premium series (see module docstring for why)."""
    spot = await definedge.spot_quote()
    spot_ltp = float(str(spot["spot"]).replace(",", ""))
    atm = round(spot_ltp / 100) * 100

    df = await definedge._get_master()
    tokens = resolve_atm_option_tokens(df, atm)
    option_token = tokens[direction]

    now = datetime.now(IST)
    frm = (now - timedelta(days=HISTORY_LOOKBACK_DAYS)).strftime("%d%m%Y0000")
    to = now.strftime("%d%m%Y%H%M")
    opt_bars = await fetch_minute_bars(definedge, "NFO", option_token, frm=frm, to=to)
    if len(opt_bars) < 50:
        return {"action": "flat", "reason": f"insufficient {direction} price data"}
    columns = build_pnf_columns(opt_bars)
    if len(columns) < 4:
        return {"action": "flat", "reason": f"insufficient {direction} P&F column history"}

    pole_idx = None
    for i in range(3, len(columns)):
        if find_low_pole(columns, i) and _is_today(columns[i]["end_ts"], today_iso):
            pole_idx = i  # keep overwriting -> ends as the most recent match today

    if pole_idx is None:
        return {"action": "flat", "reason": f"no Low Pole confirmed today on the {direction} chart"}

    follow_through = None
    for j in range(pole_idx + 1, len(columns)):
        if find_aft_immediate(columns, j, "X"):
            follow_through = {"pattern": "aft_immediate", "column": j}
        elif find_turtle_breakout(columns, j, "X"):
            follow_through = {"pattern": "turtle_breakout", "column": j}
        elif find_triple_top_buy(columns, j):
            follow_through = {"pattern": "triple_top_bottom", "column": j}
    if follow_through is None:
        return {"action": "flat", "reason": "pole confirmed, no follow-through yet",
                "conditions_met": {"pole_column": pole_idx}}

    xo_series = xo_zone_series(columns)
    xo_now, xo_at_pole = xo_series[-1], xo_series[pole_idx]
    xo_ok = xo_at_pole <= 0 and xo_now > 0

    closes = [b["close"] for b in opt_bars]
    rsi_snapshot = compute_rsi_snapshot(closes)
    rsi7 = rsi_snapshot["rsi7"]
    rsi_ok = rsi7 is not None and ENTRY_RSI_RANGE[0] < rsi7 < ENTRY_RSI_RANGE[1]

    conditions_met = {
        "pole_column": pole_idx,
        "pole_price": columns[pole_idx - 1]["low_price"],
        "follow_through_pattern": follow_through["pattern"],
        "follow_through_column": follow_through["column"],
        "xo_zone_at_pole": xo_at_pole,
        "xo_zone_now": xo_now,
        "xo_zone_ok": xo_ok,
        "rsi7": rsi7,
        "rsi_avg1_ema5": rsi_snapshot["rsi_avg1_ema5"],
        "rsi_avg2_ema14": rsi_snapshot["rsi_avg2_ema14"],
        "rsi_ok": rsi_ok,
    }

    if not (xo_ok and rsi_ok):
        return {"action": "flat", "reason": "pattern conditions met, indicator gates not yet aligned",
                "conditions_met": conditions_met}

    entry_price = opt_bars[-1]["close"]
    pole_col = columns[pole_idx - 1]
    initial_stop = pole_col["low_price"] - 1  # in premium terms — directly meaningful now
    target = spot_ltp + TARGET_POINTS if direction == "CE" else spot_ltp - TARGET_POINTS

    trade = {
        "id": str(uuid.uuid4()),
        "date": today_iso,
        "direction": direction,
        "strike": atm,
        "expiry": tokens["expiry"],
        "option_token": option_token,
        "entry_time": now.isoformat(),
        "entry_price": entry_price,
        "entry_spot": spot_ltp,
        "initial_stop": initial_stop,
        "current_stop": initial_stop,
        "stop_shift_history": [],
        "target": target,
        "exit_time": None,
        "exit_price": None,
        "exit_reason": None,
        "pnl": None,
        "conditions_met": conditions_met,
        "status": "open",
    }
    await db.blackbox_prism_alpha_trades.insert_one(dict(trade))
    return {"action": "entered", "trade": trade}


async def _monitor_open_trade(db, definedge, trade: dict) -> dict:
    """Stop-loss and its trailing shifts live entirely on the option's own
    premium chart (Double Bottom Sell, same as the entry pole). The 60-point
    target is the one thing still measured on the underlying, per spec —
    so this pulls both series and checks whichever breaches first."""
    now = datetime.now(IST)
    frm = (now - timedelta(days=HISTORY_LOOKBACK_DAYS)).strftime("%d%m%Y0000")
    to = now.strftime("%d%m%Y%H%M")
    opt_bars = await fetch_minute_bars(definedge, "NFO", trade["option_token"], frm=frm, to=to)
    underlying_bars = await fetch_minute_bars(definedge, "NSE", NIFTY_SPOT_TOKEN, frm=frm, to=to)
    columns = build_pnf_columns(opt_bars)

    entry_dt = datetime.fromisoformat(trade["entry_time"])
    is_ce = trade["direction"] == "CE"
    current_stop = trade["current_stop"]
    target = trade["target"]

    # 1. Trailing stop — best (never-worse) candidate across every qualifying
    # Double Bottom Sell column formed on the option's own chart since entry.
    entry_col_idx = None
    for i, c in enumerate(columns):
        if _parse_ts(c["end_ts"]) >= entry_dt:
            entry_col_idx = i
            break

    best_candidate = None
    if entry_col_idx is not None:
        for j in range(entry_col_idx, len(columns)):
            if is_double_bottom_sell(columns, j):
                candidate = columns[j]["low_price"] - 1
                if candidate > current_stop and (best_candidate is None or candidate > best_candidate):
                    best_candidate = candidate

    if best_candidate is not None:
        shift_event = {
            "timestamp": now.isoformat(),
            "old_stop": current_stop,
            "new_stop": best_candidate,
            "pattern": "double_bottom_sell",
        }
        current_stop = best_candidate
        await db.blackbox_prism_alpha_trades.update_one(
            {"id": trade["id"]},
            {"$set": {"current_stop": current_stop}, "$push": {"stop_shift_history": shift_event}},
        )

    # 2. Stop breach — option's own bar low, vs. target breach — underlying's
    # own bar high/low. Both checked intrabar (not just close), so a level
    # that's only briefly wicked through is still caught. The two breaches
    # live on different time series (option premium vs. index), so whichever
    # has the EARLIER timestamp wins if both would eventually fire.
    opt_since_entry = [b for b in opt_bars if b["dt"] >= entry_dt]
    und_since_entry = [b for b in underlying_bars if b["dt"] >= entry_dt]

    stop_bar = next((b for b in opt_since_entry if b["low"] <= current_stop), None)
    target_bar = next((b for b in und_since_entry if (b["high"] >= target if is_ce else b["low"] <= target)), None)

    if stop_bar is None and target_bar is None:
        return {"action": "monitoring", "trade": {**trade, "current_stop": current_stop}}
    if stop_bar is not None and (target_bar is None or stop_bar["dt"] <= target_bar["dt"]):
        exit_reason, breach_bar = "stop", stop_bar
    else:
        exit_reason, breach_bar = "target", target_bar

    if exit_reason == "stop":
        exit_price = breach_bar["close"]  # already the option's own premium
    else:
        at_or_after = [b for b in opt_bars if b["dt"] >= breach_bar["dt"]]
        exit_price = at_or_after[0]["close"] if at_or_after else opt_bars[-1]["close"]
    pnl = exit_price - trade["entry_price"]

    await db.blackbox_prism_alpha_trades.update_one(
        {"id": trade["id"]},
        {"$set": {
            "status": "closed",
            "exit_time": now.isoformat(),
            "exit_price": exit_price,
            "exit_reason": exit_reason,
            "pnl": pnl,
        }},
    )
    return {"action": "exited", "exit_reason": exit_reason, "exit_price": exit_price, "pnl": pnl}


async def evaluate_prism_alpha(db, definedge) -> dict:
    """The single poll-cycle entry point. READ-ONLY Definedge endpoints only:
      - GET .../sds/history/{segment}/{token}/minute/{from}/{to}  (Nifty index + CE/PE bars)
      - GET .../dart/v1/quotes/NSE/{token}                        (spot LTP at signal time)
      - GET .../public/nsefno.zip (via definedge._get_master())   (CE/PE token resolution)
    No order-placement, modification, or cancellation endpoint is referenced
    anywhere in this module.
    """
    today_iso = datetime.now(IST).date().isoformat()
    existing = await db.blackbox_prism_alpha_trades.find_one({"date": today_iso}, {"_id": 0})

    if existing and existing["status"] == "open":
        return await _monitor_open_trade(db, definedge, existing)
    if existing and existing["status"] == "closed":
        return {"action": "flat", "reason": "already traded today"}

    ce_result = await _evaluate_entry(db, definedge, today_iso, "CE")
    if ce_result["action"] == "entered":
        return ce_result
    return await _evaluate_entry(db, definedge, today_iso, "PE")
