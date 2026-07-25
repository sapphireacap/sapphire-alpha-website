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
RSI variant) are NOT in Definedge's public docs. XO Zone's formula and
trading usage (zero-line crossover) were subsequently cross-checked against
Prashant Shah's "Trading the Markets the Point & Figure Way" (a general P&F
reference, not Definedge-specific) and confirmed to match exactly — no
longer a guess. RSI's specific dual-EMA variant remains unconfirmed; the
same book confirmed P&F indicators (including RSI) should be computed on
one price per column (see column_close_prices()), which this module now
does, but the exact Period-7/dual-EMA settings are still best-effort. If
RSI still can't be reconciled with real platform behavior, remove it from
entry logic rather than ship a guess permanently.

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
from datetime import time as dt_time

import httpx
import pandas as pd

from definedge_service import DefinedgeService, DefinedgeError, DATA_BASE

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
TARGET_POINTS = 60              # ₹60 of OPTION PREMIUM movement from entry — confirmed: since entry/exit
                                 # now live entirely on the option's own chart, "60 points" means ₹60 on
                                 # that chart, not 60 Nifty index points (an earlier version used the
                                 # underlying here — corrected).
ATM_STRIKE_INCREMENT = 100      # ATM = round(spot/100)*100 — strikes are multiples of 100 (24000, 24100, ...)
MAX_TRADES_PER_SESSION = 3      # once a trade closes, a new one may be taken the same session, up to this cap
ENTRY_START_TIME = dt_time(9, 20)  # no new entries before 9:20 AM IST; exit-monitoring on an already-open
                                    # trade is never gated by this — only fresh entries are
EXIT_FORCE_TIME = dt_time(15, 10)  # every trade must be flat by this time — no overnight holding. If
                                    # neither target nor stop has hit by 15:10 IST, force-close at the
                                    # latest available close, exit_reason="session_end".
POLE_SEARCH_WINDOW = 60         # backward pole/follow-through search only looks this many columns back.
                                 # A pole further back than this would almost always be rejected by the
                                 # stale-pole sanity guard anyway (price has typically moved too far from
                                 # it by then), so this just bounds the cost on long-lived contracts —
                                 # caught live: an uncapped search made a real backtest run take 30+
                                 # minutes without finishing on a contract that accumulated hundreds of
                                 # columns over a long backfilled history.

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
def _box_level(price: float, anchor: float, box_pct: float = BOX_PCT) -> int:
    """Box level RELATIVE to `anchor` (the chart's own starting price), not an
    absolute grid anchored at price=1. Anchoring at 1 (the earlier version's
    bug — same one still present in pnf_trend()'s independent implementation)
    puts box boundaries at essentially arbitrary offsets that only coincide
    with clean round-number moves by luck: verified live that a chart
    starting at 100 flipped to the next box at ~100.5, not 101. Anchoring to
    the chart's own start makes each box exactly box_pct away from the LAST
    LOCKED price, compounding forward (100 -> 101 -> 102.01 -> 103.03 -> ...)
    — confirmed against the user's own description of how the real chart
    locks boxes. The `+ 1e-9` guards against float error landing a price
    that's exactly on a boundary just under its true integer level."""
    return math.floor(math.log(price / anchor) / math.log(1.0 + box_pct) + 1e-9)


def build_pnf_columns(bars: list, box_pct: float = BOX_PCT, reversal_boxes: int = REVERSAL_BOXES) -> list:
    """bars: chronological [{ts, open, high, low, close}, ...] (1-minute bars
    for the live engine, daily bars for the backtest). Samples ONLY each
    bar's close/LTP — one price point per bar, per spec ("at each 1-minute
    close, take the option's LTP... x and o prints only if they move the
    set % rules within 1min"). Earlier version also fed each bar's high/low
    as separate ticks; that's intentionally gone now — a bar contributes
    exactly one sample, matching how the chart is meant to be sampled.
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

    samples = [(b["ts"], b["close"]) for b in bars]

    columns = []
    direction = None
    base_price = float(samples[0][1])
    base_level = 0  # by construction: _box_level(base_price, anchor=base_price) == 0
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
        lv = _box_level(p, base_price, box_pct)

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
# Indicators. XO Zone's formula and usage are confirmed against Prashant
# Shah's "Trading the Markets the Point & Figure Way" (Ch. 4.5): XO Zone =
# (total X-boxes - total O-boxes) over a trailing N columns, and the
# documented trading usage is a zero-line CROSSOVER on the newest reading —
# not a "net positive since some earlier column" condition. An earlier
# version of this module gated entries on the latter (self-invented, no
# source), which mechanically vetoed ~100% of real setups since a Low Pole is
# by definition preceded by a large O column that dominates the window right
# when follow-through confirms. xo_zone_turned() below is the correct
# reading and is what entries actually gate on now.
# RSI's exact Definedge dual-EMA variant is still undocumented publicly (see
# module docstring) — logged for audit, not gated on for that part — but the
# book confirms P&F indicators including RSI are computed on ONE PRICE PER
# COLUMN (closing-price method: X column's high, O column's low), not on the
# raw underlying bars. See column_close_prices() below.
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
    newest column (vs. its value one column back). This is the textbook
    "XO zone crossover" reading and what entries actually gate on."""
    series = xo_zone_series(columns, lookback)
    if len(series) < 2:
        return None
    prev, cur = series[-2], series[-1]
    if prev <= 0 < cur:
        return "positive"
    if prev >= 0 > cur:
        return "negative"
    return None


def column_close_prices(columns: list) -> list:
    """P&F 'closing price method' proxy price for each column: high price
    for X (rising), low price for O (falling) — per the book's definition,
    used as the single input price for every column-based indicator (RSI,
    moving averages, etc.), not the raw underlying bars."""
    return [c["high_price"] if c["direction"] == "X" else c["low_price"] for c in columns]


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


async def _check_entry_conditions(definedge, direction: str, option_token: str) -> dict:
    """direction: 'CE' or 'PE' — which option's own chart to analyze. Both
    use the identical bullish setup: Low Pole + bullish follow-through +
    XO Zone-turned-positive + RSI in ENTRY_RSI_RANGE, all computed on that
    option's own premium series (see module docstring for why). Pure check,
    no DB write — split out so both CE and PE can be evaluated in full
    before deciding which (if either) to actually enter, so a same-day
    simultaneous qualification can be detected rather than short-circuited
    away by whichever direction happened to be checked first."""
    now = datetime.now(IST)
    frm = (now - timedelta(days=HISTORY_LOOKBACK_DAYS)).strftime("%d%m%Y0000")
    to = now.strftime("%d%m%Y%H%M")
    opt_bars = await fetch_minute_bars(definedge, "NFO", option_token, frm=frm, to=to)
    if len(opt_bars) < 50:
        return {"qualifies": False, "reason": f"insufficient {direction} price data"}
    columns = build_pnf_columns(opt_bars)
    if len(columns) < 4:
        return {"qualifies": False, "reason": f"insufficient {direction} P&F column history"}

    # "All align on the same day" means all four conditions are checked and
    # found true TOGETHER on the evaluation day — not that each one must
    # have freshly triggered that exact day. That reading is structurally
    # impossible for the pole specifically: follow-through can only occur
    # in columns AFTER the pole's confirming column, so if the pole were
    # required to confirm today, there could never be a later column today
    # for the follow-through to occur in. Caught live: with that gate, every
    # single pole confirmation in a real backtest run showed "no
    # follow-through yet" — 100% of the time, by construction, not chance.
    #
    # Search backward from the newest column for the freshest (pole,
    # follow-through) PAIR — not "the single most recent pole ever, then any
    # follow-through however much later." Taking the absolute latest pole
    # regardless of how long ago it was, paired with a follow-through many
    # columns later, surfaced a real bad trade in testing: price had since
    # moved far from that old pole's level, making its low a stale,
    # economically meaningless stop-loss anchor (caught by the sanity guard
    # below, but the root cause is picking a stale pole in the first place).
    # Walking backward and taking the first pole that already has a
    # follow-through after it keeps both anchored to the same, recent move.
    pole_idx = None
    follow_through = None
    search_floor = max(2, len(columns) - 1 - POLE_SEARCH_WINDOW)
    for i in range(len(columns) - 1, search_floor, -1):
        if not find_low_pole(columns, i):
            continue
        candidate_ft = None
        for j in range(i + 1, len(columns)):
            if find_aft_immediate(columns, j, "X"):
                candidate_ft = {"pattern": "aft_immediate", "column": j}
            elif find_turtle_breakout(columns, j, "X"):
                candidate_ft = {"pattern": "turtle_breakout", "column": j}
            elif find_triple_top_buy(columns, j):
                candidate_ft = {"pattern": "triple_top_bottom", "column": j}
        if candidate_ft is not None:
            pole_idx, follow_through = i, candidate_ft
            break  # freshest pole that already has a follow-through — stop here

    if pole_idx is None:
        return {"qualifies": False, "reason": f"no Low Pole with a follow-through found on the {direction} chart"}

    # XO Zone gate: a zero-line crossover on the newest column (confirmed
    # against Prashant Shah's P&F book, Ch. 4.5 — see module-level comment
    # above xo_zone_series). Bullish entries need the zone to have just
    # turned positive.
    xo_series = xo_zone_series(columns)
    xo_now = xo_series[-1]
    xo_turn = xo_zone_turned(columns)
    xo_ok = xo_turn == "positive"

    # RSI(7) computed on column closing-price-method values (X->high,
    # O->low), per the book's confirmation that P&F indicators use one price
    # per column, not raw bars. Definedge's exact dual-EMA variant is still
    # undocumented (see module docstring) — the two EMA overlays are logged
    # for audit, not gated on.
    col_closes = column_close_prices(columns)
    rsi_snapshot = compute_rsi_snapshot(col_closes)
    rsi7 = rsi_snapshot["rsi7"]
    rsi_ok = rsi7 is not None and ENTRY_RSI_RANGE[0] < rsi7 < ENTRY_RSI_RANGE[1]

    conditions_met = {
        "pole_column": pole_idx,
        "pole_price": columns[pole_idx - 1]["low_price"],
        "follow_through_pattern": follow_through["pattern"],
        "follow_through_column": follow_through["column"],
        "xo_zone_now": xo_now,
        "xo_zone_turned": xo_turn,
        "xo_zone_ok": xo_ok,
        "rsi7": rsi7,
        "rsi_avg1_ema5": rsi_snapshot["rsi_avg1_ema5"],
        "rsi_avg2_ema14": rsi_snapshot["rsi_avg2_ema14"],
        "rsi_ok": rsi_ok,
    }

    if not (xo_ok and rsi_ok):
        return {"qualifies": False, "reason": "pattern conditions met, indicator gates not yet aligned",
                "conditions_met": conditions_met}

    entry_price = opt_bars[-1]["close"]
    initial_stop = columns[pole_idx - 1]["low_price"] - 1  # in premium terms — directly meaningful now

    # Sanity guard: a stop-loss can never sit at or above entry on a long
    # position. Taking "the most recent Low Pole anywhere in the window" (no
    # same-day gate — see above) can surface a pole that price has since
    # fallen back through, invalidating the bullish thesis the pole was
    # supposed to represent even though a later, unrelated follow-through +
    # XO Zone + RSI still happen to align. Caught live: a real backtest
    # trade came out with initial_stop > entry_price, which would have
    # triggered an exit almost immediately for a guaranteed loss. Rather
    # than take that trade, it's rejected outright.
    if initial_stop >= entry_price:
        return {"qualifies": False, "reason": "pole stop would be at/above entry — stale pole, rejecting",
                "conditions_met": conditions_met}

    return {
        "qualifies": True,
        "conditions_met": conditions_met,
        "entry_price": entry_price,
        "initial_stop": initial_stop,
    }


async def _enter_trade(db, today_iso: str, direction: str, atm: int, expiry: str, option_token: str,
                        check: dict, flagged_conflict: bool) -> dict:
    conditions_met = dict(check["conditions_met"])
    if flagged_conflict:
        conditions_met["simultaneous_signal_conflict"] = True
        conditions_met["other_direction_also_qualified"] = "PE" if direction == "CE" else "CE"
        logger.warning("Prism Alpha: both CE and PE qualified simultaneously on %s — taking %s "
                        "(checked first), flagging the conflict rather than silently dropping it.",
                        today_iso, direction)

    entry_price = check["entry_price"]
    target = entry_price + TARGET_POINTS  # premium terms — "60 points" = ₹60 of option premium, confirmed

    trade = {
        "id": str(uuid.uuid4()),
        "date": today_iso,
        "direction": direction,
        "strike": atm,
        "expiry": expiry,
        "option_token": option_token,
        "entry_time": datetime.now(IST).isoformat(),
        "entry_price": entry_price,
        "initial_stop": check["initial_stop"],
        "current_stop": check["initial_stop"],
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
    """Stop-loss, its trailing shifts, and the target all live entirely on
    the option's own premium chart — target = entry_price + TARGET_POINTS
    in premium terms (confirmed: "60 points" means ₹60 of option premium,
    not underlying, since everything moved to the option's own chart).
    Checked against 1-minute CLOSES only (not intrabar high/low), matching
    the chart's own close-only sampling: "check continuously against 1-min
    closes... not tick-by-tick, since the chart itself is only updated once
    per minute."""
    now = datetime.now(IST)
    frm = (now - timedelta(days=HISTORY_LOOKBACK_DAYS)).strftime("%d%m%Y0000")
    to = now.strftime("%d%m%Y%H%M")
    opt_bars = await fetch_minute_bars(definedge, "NFO", trade["option_token"], frm=frm, to=to)
    columns = build_pnf_columns(opt_bars)

    entry_dt = datetime.fromisoformat(trade["entry_time"])
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

    # 2. Stop/target breach — close-only, same series, same sampling as the
    # chart itself. First 1-min close since entry that clears either level.
    opt_since_entry = [b for b in opt_bars if b["dt"] >= entry_dt]
    breach_bar = next((b for b in opt_since_entry if b["close"] <= current_stop or b["close"] >= target), None)

    if breach_bar is None:
        # 3. No overnight holding — force flat by 15:10 IST if neither
        # target nor stop has hit yet. Also closes a real gap this caught:
        # without a hard session cutoff, a position with no further exit
        # trigger could otherwise sit open indefinitely.
        if now.time() >= EXIT_FORCE_TIME and opt_since_entry:
            exit_reason = "session_end"
            exit_price = opt_since_entry[-1]["close"]
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
        return {"action": "monitoring", "trade": {**trade, "current_stop": current_stop}}

    exit_reason = "stop" if breach_bar["close"] <= current_stop else "target"
    exit_price = breach_bar["close"]
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
      - GET .../sds/history/{segment}/{token}/minute/{from}/{to}  (CE/PE option bars)
      - GET .../dart/v1/quotes/NSE/{token}                        (Nifty spot LTP — ATM selection only)
      - GET .../public/nsefno.zip (via definedge._get_master())   (CE/PE token resolution)
    No order-placement, modification, or cancellation endpoint is referenced
    anywhere in this module.
    """
    today_iso = datetime.now(IST).date().isoformat()
    todays_trades = await db.blackbox_prism_alpha_trades.find({"date": today_iso}, {"_id": 0}).to_list(MAX_TRADES_PER_SESSION + 1)
    open_trade = next((t for t in todays_trades if t["status"] == "open"), None)

    if open_trade is not None:
        # Once a trade is on, keep tracking that exact strike/contract until
        # exit — never re-pick ATM mid-trade, even if spot has since drifted.
        return await _monitor_open_trade(db, definedge, open_trade)

    closed_count = sum(1 for t in todays_trades if t["status"] == "closed")
    if closed_count >= MAX_TRADES_PER_SESSION:
        return {"action": "flat", "reason": f"max {MAX_TRADES_PER_SESSION} trades already taken this session"}

    if datetime.now(IST).time() < ENTRY_START_TIME:
        return {"action": "flat", "reason": "before 9:20 AM entry window"}

    # Spot is used ONLY to pick the current ATM strike while flat — it never
    # feeds pattern detection, XO Zone, or RSI, all of which run on the
    # option's own chart. Re-resolved fresh every poll cycle while flat, so
    # ATM naturally tracks spot drift in 100-point increments until a trade
    # is actually taken (see the "no re-pick mid-trade" note above).
    spot = await definedge.spot_quote()
    spot_ltp = float(str(spot["spot"]).replace(",", ""))
    atm = round(spot_ltp / ATM_STRIKE_INCREMENT) * ATM_STRIKE_INCREMENT

    df = await definedge._get_master()
    tokens = resolve_atm_option_tokens(df, atm)

    # Both charts checked in full before deciding — never short-circuited —
    # so a same-day simultaneous CE+PE qualification is actually detected
    # instead of silently masked by whichever direction got checked first.
    ce_check = await _check_entry_conditions(definedge, "CE", tokens["CE"])
    pe_check = await _check_entry_conditions(definedge, "PE", tokens["PE"])
    both_qualify = ce_check["qualifies"] and pe_check["qualifies"]

    if ce_check["qualifies"]:
        return await _enter_trade(db, today_iso, "CE", atm, tokens["expiry"], tokens["CE"], ce_check, both_qualify)
    if pe_check["qualifies"]:
        return await _enter_trade(db, today_iso, "PE", atm, tokens["expiry"], tokens["PE"], pe_check, both_qualify)

    return {"action": "flat", "reason": "no entry conditions aligned",
            "ce_reason": ce_check.get("reason"), "pe_reason": pe_check.get("reason")}
