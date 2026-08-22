"""
Swing Reversal Patterns — objective candlestick reversal setups sourced
from an Indian trader's price-action framework (read in full this session,
in Definedge's Technical Analysis book — Vayda Bazar Patterns chapter).
Public-facing labels use plain English, not the source material's own
pattern names, matching this site's existing convention for sourced-but-
unattributed methodology (Camarilla, D-Pivot, etc. elsewhere in this repo).

Every pattern is a precise, objective relationship between one session's
OHLC and either the previous session or the previous swing high/low — no
subjective chart-reading, same discipline as pnf_patterns.py/renko_patterns.py.

Two things the source material describes but doesn't pin to an exact
number, so this module makes an explicit, documented choice instead of
guessing silently:
  - "Swing high/low" — the source assumes charts were marked by hand.
    Here it's a simple N-bar fractal (lowest/highest of a `window`-bar
    neighbourhood on each side) — a standard, reproducible definition.
  - "3 steps" (the buffer/stop-loss distance) — described as roughly
    0.5%-1% of the stock's price (spreads were wide when the source was
    written). Implemented as `step_pct` of price, default 0.75% (the
    midpoint of that range).

Four pattern pairs (8 detectors), the ones the source material itself
flags as the strongest / most reliable combinations:
  - Swing Reversal (bull/bear)            — daily, vs. the previous swing point
  - Weekly Breakout Confirmation (bull/bear) — weekly, vs. the prior week
  - Momentum Reversal (bull/bear)         — daily, "3 steps" close breach
  - Trapped Move Reversal (bull/bear)     — daily, prior-session trap + recovery
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

FRACTAL_WINDOW = 3  # bars on each side to confirm a swing high/low
DEFAULT_STEP_PCT = 0.0075  # ~0.75%, midpoint of the source's 0.5%-1% range
NEAR_EXTREME_PCT = 0.30  # "closed near the low/high" - within this fraction of session range


@dataclass
class Bar:
    index: int
    date: str
    open: float
    high: float
    low: float
    close: float


@dataclass
class SwingPoint:
    index: int
    price: float
    kind: str  # "high" | "low"


@dataclass
class PatternSignal:
    key: str              # internal pattern id, e.g. "swing_reversal"
    label: str             # public-facing plain-English label
    bias: str               # "bullish" | "bearish"
    index: int              # bar index the pattern triggered on
    date: str
    trigger_price: float    # close that confirmed the pattern
    stop_loss: float        # suggested SL level (source's "3 steps" rule)


def to_bars(raw: list) -> list[Bar]:
    """raw: [{date, open, high, low, close}, ...] -> list[Bar], skipping
    any row missing a required field (mirrors the tolerant style used by
    pnf_chart.py/renko_chart.py's own bar prep)."""
    out = []
    for i, r in enumerate(raw):
        try:
            out.append(Bar(i, r["date"], float(r["open"]), float(r["high"]),
                            float(r["low"]), float(r["close"])))
        except (KeyError, TypeError, ValueError):
            continue
    return out


def find_swings(bars: list[Bar], window: int = FRACTAL_WINDOW) -> list[SwingPoint]:
    swings: list[SwingPoint] = []
    n = len(bars)
    for i in range(window, n - window):
        nb = bars[i - window:i + window + 1]
        if bars[i].low == min(b.low for b in nb):
            swings.append(SwingPoint(i, bars[i].low, "low"))
        if bars[i].high == max(b.high for b in nb):
            swings.append(SwingPoint(i, bars[i].high, "high"))
    return swings


def _last_swing_before(swings: list[SwingPoint], index: int, kind: str) -> Optional[SwingPoint]:
    matches = [s for s in swings if s.kind == kind and s.index < index]
    return matches[-1] if matches else None


def _step(price: float, step_pct: float = DEFAULT_STEP_PCT) -> float:
    return price * step_pct


def _closed_near_low(bar: Bar) -> bool:
    rng = bar.high - bar.low
    if rng <= 0:
        return True
    return (bar.close - bar.low) / rng <= NEAR_EXTREME_PCT


def _closed_near_high(bar: Bar) -> bool:
    rng = bar.high - bar.low
    if rng <= 0:
        return True
    return (bar.high - bar.close) / rng <= NEAR_EXTREME_PCT


# ---------------------------------------------------------------------------
# 1. Swing Reversal (daily, vs. previous swing point)
# ---------------------------------------------------------------------------
def detect_swing_reversal(bars: list[Bar], swings: list[SwingPoint], i: int,
                           step_pct: float = DEFAULT_STEP_PCT) -> Optional[PatternSignal]:
    if i < 1:
        return None
    cur, prev = bars[i], bars[i - 1]

    swing_low = _last_swing_before(swings, i, "low")
    if swing_low and cur.low < swing_low.price and _closed_near_low(prev) \
            and cur.low < prev.low and cur.close > max(prev.open, prev.close):
        return PatternSignal("swing_reversal", "Swing Reversal", "bullish", i, cur.date,
                              cur.close, cur.low - _step(cur.low, step_pct))

    swing_high = _last_swing_before(swings, i, "high")
    if swing_high and cur.high > swing_high.price and _closed_near_high(prev) \
            and cur.high > prev.high and cur.close < min(prev.open, prev.close):
        return PatternSignal("swing_reversal", "Swing Reversal", "bearish", i, cur.date,
                              cur.close, cur.high + _step(cur.high, step_pct))
    return None


# ---------------------------------------------------------------------------
# 2. Weekly Breakout Confirmation (weekly bars, vs. the prior week)
# ---------------------------------------------------------------------------
def detect_weekly_breakout(weekly_bars: list[Bar], i: int) -> Optional[PatternSignal]:
    if i < 2:
        return None
    cur, prev, before = weekly_bars[i], weekly_bars[i - 1], weekly_bars[i - 2]

    if prev.close < prev.open and cur.close > cur.open \
            and cur.close > max(prev.high, before.close):
        return PatternSignal("weekly_breakout", "Weekly Breakout Confirmation", "bullish",
                              i, cur.date, cur.close, prev.low)

    if prev.close > prev.open and cur.close < cur.open \
            and cur.close < min(prev.low, before.close):
        return PatternSignal("weekly_breakout", "Weekly Breakout Confirmation", "bearish",
                              i, cur.date, cur.close, prev.high)
    return None


# ---------------------------------------------------------------------------
# 3. Momentum Reversal (daily, "3 steps" close breach)
# ---------------------------------------------------------------------------
def detect_momentum_reversal(bars: list[Bar], i: int,
                              step_pct: float = DEFAULT_STEP_PCT) -> Optional[PatternSignal]:
    if i < 1:
        return None
    cur, prev = bars[i], bars[i - 1]

    if cur.low < prev.low and cur.close > prev.close + _step(prev.close, step_pct):
        return PatternSignal("momentum_reversal", "Momentum Reversal", "bullish", i, cur.date,
                              cur.close, cur.low)

    if cur.high > prev.high and cur.close < prev.close - _step(prev.close, step_pct):
        return PatternSignal("momentum_reversal", "Momentum Reversal", "bearish", i, cur.date,
                              cur.close, cur.high)
    return None


# ---------------------------------------------------------------------------
# 4. Trapped Move Reversal (daily, prior-session trap + recovery)
# ---------------------------------------------------------------------------
def detect_trapped_move(bars: list[Bar], swings: list[SwingPoint], i: int,
                         step_pct: float = DEFAULT_STEP_PCT) -> Optional[PatternSignal]:
    if i < 1:
        return None
    cur, prev = bars[i], bars[i - 1]

    swing_low_before_prev = _last_swing_before(swings, i - 1, "low")
    if swing_low_before_prev and prev.low < swing_low_before_prev.price and prev.close < prev.open \
            and abs(cur.open - prev.low) <= _step(prev.low, step_pct) and cur.close > prev.close:
        return PatternSignal("trapped_move", "Trapped Move Reversal", "bullish", i, cur.date,
                              cur.close, prev.low)

    swing_high_before_prev = _last_swing_before(swings, i - 1, "high")
    if swing_high_before_prev and prev.high > swing_high_before_prev.price and prev.close > prev.open \
            and abs(cur.open - prev.high) <= _step(prev.high, step_pct) and cur.close < prev.close:
        return PatternSignal("trapped_move", "Trapped Move Reversal", "bearish", i, cur.date,
                              cur.close, prev.high)
    return None


DETECTORS_DAILY = (detect_swing_reversal, detect_trapped_move, detect_momentum_reversal)


def scan_latest(daily_bars: list[dict], weekly_bars: Optional[list[dict]] = None,
                 step_pct: float = DEFAULT_STEP_PCT) -> list[PatternSignal]:
    """Returns every pattern that triggers on the LATEST bar only — the
    shape a universe-wide scanner needs (today's signals, not history).
    Weekly detection is skipped if weekly_bars isn't supplied."""
    bars = to_bars(daily_bars)
    if len(bars) < 2 * FRACTAL_WINDOW + 2:
        return []
    swings = find_swings(bars)
    last = len(bars) - 1

    signals = []
    for detector in (detect_swing_reversal, detect_trapped_move):
        sig = detector(bars, swings, last, step_pct)
        if sig:
            signals.append(sig)
    sig = detect_momentum_reversal(bars, last, step_pct)
    if sig:
        signals.append(sig)

    if weekly_bars:
        wbars = to_bars(weekly_bars)
        if len(wbars) >= 3 and wbars[-1].date == bars[-1].date:
            sig = detect_weekly_breakout(wbars, len(wbars) - 1)
            if sig:
                signals.append(sig)

    return signals
