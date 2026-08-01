"""Point & Figure indicators, counts and trend lines — Chapters 3 and 4 of
"Trading The Markets The Point & Figure Way" (Prashant Shah, 2018).

THE ONE RULE THAT GOVERNS EVERYTHING HERE (book, Ch. 4 opening): an
indicator's formula is unchanged on a P&F chart, but its INPUT is not.
"There is a difference between 10 candles and 10 columns. 10 candles on a
daily chart will consist of the prices of 10 days, but 10 columns of P&F
represent 10 trends." So every indicator in this module consumes ONE
PRICE PER COLUMN, never raw bars. Two ways to pick that price, both
documented in 4.1 and both provided here:

  * closing-price method (`column_close_prices`) — an X column's high, an
    O column's low. The book's own recommendation: "a moving average with
    closing price method would be preferred because it doesn't require
    the mid-price of column to be above the moving average to indicate a
    valid breakout."
  * mid-price method (`column_mid_prices`) — (high + low) / 2, the
    traditional choice. Breakout semantics differ: with this method the
    column's MID must clear the line, not merely its extreme. Callers get
    that for free by using `crossed_above`/`crossed_below` with the
    matching price series.

Levels vs prices: the counts and trend lines work in integer BOX LEVELS
(one level == one box), because that is the unit the book's formulas are
actually expressed in — "Length of the pattern x Box-value x Reversal
value" is just `boxes * reversal` levels. Convert to a real price with
`settings.price_at(level, anchor)`.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional

from pnf_engine import BoxSettings, Column
from pnf_patterns import bottom, is_up, mid_level, top

# Standing instruction (2026-07-31): the XO family runs on a 10-column
# lookback across this platform. The book's own "20" is explicitly an
# illustration, not a recommendation ("Parameter 20 is an example and not
# a recommendation"); its only actual requirement is that the number be
# even, "to keep number of columns equal for X and O during the period",
# which 10 satisfies. 10 also matches what blackbox_prism_alpha already
# uses, so both modules now read this indicator identically.
DEFAULT_XO_LOOKBACK = 10

# ---------------------------------------------------------------------------
# Per-column price series (the input every other indicator here consumes)
# ---------------------------------------------------------------------------


def column_close_levels(columns: list) -> list:
    """Closing-price method, in box levels: X column -> its high, O column
    -> its low (book 4.1: "the closing price of column of X is high price
    of that column and need not be the actual closing price on any given
    day")."""
    return [top(c) if is_up(c) else bottom(c) for c in columns]


def column_mid_levels(columns: list) -> list:
    """Mid-price method, in box levels: (high + low) / 2 per column."""
    return [mid_level(c) for c in columns]


def _to_prices(levels: list, settings: BoxSettings, anchor: float) -> list:
    return [settings.price_at(lv, anchor) for lv in levels]


def column_close_prices(columns: list, settings: BoxSettings, anchor: float = None) -> list:
    """Closing-price method as real prices."""
    if not columns:
        return []
    anchor = columns[0].anchor if anchor is None else anchor
    return _to_prices(column_close_levels(columns), settings, anchor)


def column_mid_prices(columns: list, settings: BoxSettings, anchor: float = None) -> list:
    if not columns:
        return []
    anchor = columns[0].anchor if anchor is None else anchor
    return _to_prices(column_mid_levels(columns), settings, anchor)


# ---------------------------------------------------------------------------
# 4.5 — P&F's own indicators: XO count, XO lines, XO Zone
# ---------------------------------------------------------------------------


def xo_count(columns: list, lookback: int = DEFAULT_XO_LOOKBACK) -> list:
    """Book 4.5: "the XO indicator that counts total number of boxes
    whether X or O during the period. For example, a 20 column indicator
    will show total number of boxes during last 20 columns."

    Rising = expansion / strong trend; falling = congestion. Returns one
    value per column (None until the window is full)."""
    out = []
    for i in range(len(columns)):
        if i + 1 < lookback:
            out.append(None)
            continue
        window = columns[i + 1 - lookback:i + 1]
        out.append(sum(c.box_count for c in window))
    return out


def xo_lines(columns: list, lookback: int = DEFAULT_XO_LOOKBACK) -> list:
    """Book 4.5's two-line XO indicator:
        X: total boxes in columns of X over the last `lookback` columns
        O: total boxes in columns of O over the same window
    "Bullish line crossing bearish line shows that there are more number
    of X's in comparison to the O's, indicating bullish undertone."

    The book advises an even `lookback` "to keep number of columns equal
    for X and O during the period"."""
    out = []
    for i in range(len(columns)):
        if i + 1 < lookback:
            out.append({"x": None, "o": None})
            continue
        window = columns[i + 1 - lookback:i + 1]
        out.append({
            "x": sum(c.box_count for c in window if is_up(c)),
            "o": sum(c.box_count for c in window if not is_up(c)),
        })
    return out


def xo_zone(columns: list, lookback: int = DEFAULT_XO_LOOKBACK) -> list:
    """Book 4.5: "XO zone = Number of X boxes - Number of O boxes",
    plotted as a histogram oscillating around zero. Positive zone = X
    dominance, negative = O dominance, hovering near zero = congestion."""
    return [None if v["x"] is None else v["x"] - v["o"] for v in xo_lines(columns, lookback)]


def xo_zone_crossover(columns: list, lookback: int = DEFAULT_XO_LOOKBACK) -> Optional[str]:
    """The book's documented way to TRADE the XO Zone: "trade bullish
    pattern post bullish XO zone crossover and bearish pattern post
    bearish XO zone crossover" — i.e. a zero-line crossover on the newest
    reading, NOT a "net positive at some point since" condition.

    Returns "bullish"/"bearish" if the newest column crossed the zero
    line, else None."""
    series = [v for v in xo_zone(columns, lookback) if v is not None]
    if len(series) < 2:
        return None
    prev, cur = series[-2], series[-1]
    if prev <= 0 < cur:
        return "bullish"
    if prev >= 0 > cur:
        return "bearish"
    return None


def xo_zone_state(columns: list, lookback: int = DEFAULT_XO_LOOKBACK) -> dict:
    """Snapshot for display: current zone value, its sign, and whether the
    histogram is expanding (trend establishing) or converging (congestion,
    per the book: "The trend is established when distance between the
    lines widen and it is a congestion when they converge")."""
    series = [v for v in xo_zone(columns, lookback) if v is not None]
    if not series:
        return {"value": None, "zone": None, "crossover": None, "expanding": None}
    cur = series[-1]
    expanding = None
    if len(series) >= 2:
        expanding = abs(cur) > abs(series[-2])
    return {
        "value": cur,
        "zone": "bullish" if cur > 0 else ("bearish" if cur < 0 else "neutral"),
        "crossover": xo_zone_crossover(columns, lookback),
        "expanding": expanding,
    }


# ---------------------------------------------------------------------------
# 4.1 — Moving averages on columns
# ---------------------------------------------------------------------------


def sma(values: list, period: int) -> list:
    out, run = [], []
    for v in values:
        run.append(v)
        if len(run) > period:
            run.pop(0)
        out.append(sum(run) / len(run) if len(run) == period else None)
    return out


def ema(values: list, period: int) -> list:
    if not values:
        return []
    k = 2.0 / (period + 1)
    out, prev = [], None
    for n, v in enumerate(values):
        if n + 1 < period:
            out.append(None)
            continue
        if prev is None:
            prev = sum(values[:period]) / period
        else:
            prev = v * k + prev * (1 - k)
        out.append(prev)
    return out


def wma(values: list, period: int) -> list:
    out = []
    denom = period * (period + 1) / 2
    for i in range(len(values)):
        if i + 1 < period:
            out.append(None)
            continue
        window = values[i + 1 - period:i + 1]
        out.append(sum(v * (n + 1) for n, v in enumerate(window)) / denom)
    return out


_MA_FUNCS = {"sma": sma, "ema": ema, "wma": wma}


def column_moving_average(columns: list, settings: BoxSettings, period: int = 20,
                          method: str = "close", kind: str = "sma") -> list:
    """A moving average of the last `period` COLUMNS (book 4.1: "a 10
    column average on P&F chart is average price of last 10 swings").

    method: "close" (X high / O low — the book's preference) or "mid".
    kind:   "sma" | "ema" | "wma".

    Book on parameter choice: "Broadly 5, 10, 15, 20 or 30 column averages
    can be used... If you are trading a system for price average crossover
    then begin with applying 20. If you are looking for pullback setup
    then 10 would be better."""
    if not columns:
        return []
    fn = _MA_FUNCS.get(kind)
    if fn is None:
        raise ValueError(f"unknown moving-average kind: {kind}")
    anchor = columns[0].anchor
    prices = (column_close_prices(columns, settings, anchor) if method == "close"
              else column_mid_prices(columns, settings, anchor))
    return fn(prices, period)


def moving_average_trend(columns: list, settings: BoxSettings, period: int = 20,
                         method: str = "close", kind: str = "sma") -> Optional[str]:
    """Book 4.1: "Uptrend can be defined as price trading above the moving
    average and Downtrend as price positioned below moving average."

    Uses the same per-column price the average itself was built from, so
    the mid-price method correctly requires the column's MID to clear the
    line (the book is explicit that a column's extreme poking above a
    mid-price average is NOT a valid breakout)."""
    line = column_moving_average(columns, settings, period, method, kind)
    if not line or line[-1] is None:
        return None
    anchor = columns[0].anchor
    prices = (column_close_prices(columns, settings, anchor) if method == "close"
              else column_mid_prices(columns, settings, anchor))
    return "up" if prices[-1] > line[-1] else "down"


def ma_convergence(columns: list, settings: BoxSettings,
                   periods=(10, 15, 20), method: str = "close",
                   threshold_pct: float = 1.0) -> Optional[bool]:
    """Book 4.1: "Three averages coming close to each other is a
    convergence that shows the consolidation phase... Trade patterns
    during such cases and ignore when averages are in converging mode."

    True when the spread between the fastest and slowest average is within
    `threshold_pct` of the middle one."""
    lines = [column_moving_average(columns, settings, p, method) for p in periods]
    latest = [ln[-1] for ln in lines if ln and ln[-1] is not None]
    if len(latest) < len(periods):
        return None
    spread = max(latest) - min(latest)
    base = sum(latest) / len(latest)
    if base <= 0:
        return None
    return (spread / base) * 100.0 <= threshold_pct


# ---------------------------------------------------------------------------
# 4.2 — Bollinger Bands on columns
# ---------------------------------------------------------------------------


def bollinger_bands(columns: list, settings: BoxSettings, period: int = 10,
                    stdev: float = 2.0, method: str = "close") -> list:
    """Book 4.2: standard Bollinger Bands, except "the standard deviation
    is calculated from average of columns, not price bars". Returns one
    {"mid","upper","lower"} per column."""
    if not columns:
        return []
    anchor = columns[0].anchor
    prices = (column_close_prices(columns, settings, anchor) if method == "close"
              else column_mid_prices(columns, settings, anchor))
    out = []
    for i in range(len(prices)):
        if i + 1 < period:
            out.append({"mid": None, "upper": None, "lower": None})
            continue
        window = prices[i + 1 - period:i + 1]
        m = sum(window) / period
        var = sum((v - m) ** 2 for v in window) / period
        sd = math.sqrt(var)
        out.append({"mid": m, "upper": m + stdev * sd, "lower": m - stdev * sd})
    return out


# ---------------------------------------------------------------------------
# 4.3 — RSI on columns
# ---------------------------------------------------------------------------


def rsi(columns: list, settings: BoxSettings, period: int = 14,
        method: str = "close") -> list:
    """Wilder's RSI computed on one price per COLUMN, not per bar — the
    book's Ch. 4 rule applied to RSI specifically. Returns one value per
    column (None until enough columns exist)."""
    if not columns:
        return []
    anchor = columns[0].anchor
    prices = (column_close_prices(columns, settings, anchor) if method == "close"
              else column_mid_prices(columns, settings, anchor))
    out = [None] * len(prices)
    if len(prices) <= period:
        return out
    gains = losses = 0.0
    for i in range(1, period + 1):
        d = prices[i] - prices[i - 1]
        gains += max(d, 0.0)
        losses += max(-d, 0.0)
    avg_gain, avg_loss = gains / period, losses / period
    out[period] = 100.0 if avg_loss == 0 else 100.0 - 100.0 / (1 + avg_gain / avg_loss)
    for i in range(period + 1, len(prices)):
        d = prices[i] - prices[i - 1]
        avg_gain = (avg_gain * (period - 1) + max(d, 0.0)) / period
        avg_loss = (avg_loss * (period - 1) + max(-d, 0.0)) / period
        out[i] = 100.0 if avg_loss == 0 else 100.0 - 100.0 / (1 + avg_gain / avg_loss)
    return out


# ---------------------------------------------------------------------------
# 3.2 — 45-degree objective trend lines
# ---------------------------------------------------------------------------


@dataclass
class TrendLine:
    """A 45-degree line. On P&F's square grid one column of horizontal
    travel equals exactly one box of vertical travel, so the line is fully
    determined by a single anchor point — no second point, no subjectivity
    (book 3.2: "Just one point is required to draw it because angle of the
    line is always 45-degrees")."""

    direction: str        # "bullish" (rising support) | "bearish" (falling resistance)
    start_index: int
    start_level: int
    end_index: int        # last column the line was still intact
    broken_index: Optional[int] = None

    def level_at(self, column_index: int) -> int:
        step = 1 if self.direction == "bullish" else -1
        return self.start_level + step * (column_index - self.start_index)


def trend_lines(columns: list) -> list:
    """Walks the chart producing the book's traditional single active
    line: "if 45-degree bullish line is active, bearish line is not drawn
    and the moment bullish line gets broken, bearish line becomes active."

    A bullish line is anchored one box BELOW the low of the column that
    made the bottom, and rises one box per column; it breaks when a
    column prints at or below the line. The bearish line mirrors it from
    one box above the high that made the top."""
    if len(columns) < 2:
        return []

    lines: list[TrendLine] = []
    # Seed from the chart's first turning point: if the first column is an
    # O, the bottom it makes anchors a bullish line, and vice versa.
    first = columns[0]
    if is_up(first):
        active = TrendLine("bearish", 0, top(first) + 1, 0)
    else:
        active = TrendLine("bullish", 0, bottom(first) - 1, 0)

    for i in range(1, len(columns)):
        line_level = active.level_at(i)
        c = columns[i]
        broken = (bottom(c) <= line_level) if active.direction == "bullish" else (top(c) >= line_level)
        if not broken:
            active.end_index = i
            continue

        active.broken_index = i
        active.end_index = i
        lines.append(active)

        # Re-anchor the opposite line from the extreme reached during the
        # life of the line just broken.
        span = columns[active.start_index:i + 1]
        if active.direction == "bullish":
            peak_i = max(range(active.start_index, i + 1), key=lambda k: top(columns[k]))
            active = TrendLine("bearish", peak_i, top(columns[peak_i]) + 1, i)
        else:
            trough_i = min(range(active.start_index, i + 1), key=lambda k: bottom(columns[k]))
            active = TrendLine("bullish", trough_i, bottom(columns[trough_i]) - 1, i)
        # The freshly anchored line must not already be broken at i.
        while active.start_index < i and (
            (active.direction == "bullish" and bottom(columns[i]) <= active.level_at(i))
            or (active.direction == "bearish" and top(columns[i]) >= active.level_at(i))
        ):
            active.start_index += 1
            active.start_level = (bottom(columns[active.start_index]) - 1
                                  if active.direction == "bullish"
                                  else top(columns[active.start_index]) + 1)
        active.end_index = i

    lines.append(active)
    return lines


def trend_state(columns: list) -> Optional[str]:
    """"up" / "down" from the currently active 45-degree line — the book's
    primary objective trend filter ("A 45-degree trend line is a far
    superior method for trend identification")."""
    lines = trend_lines(columns)
    if not lines:
        return None
    return "up" if lines[-1].direction == "bullish" else "down"


# ---------------------------------------------------------------------------
# 3.3 — Counts (price projection)
# ---------------------------------------------------------------------------


@dataclass
class Count:
    kind: str            # "vertical" | "horizontal"
    variant: str         # "standard" | "aggressive" | "conservative"
    bias: str            # "bullish" | "bearish"
    column_index: int
    target_level: int
    base_level: int
    meta: dict


def is_swing_bottom(columns: list, i: int) -> bool:
    """An O column whose low is lower than the O columns either side of it
    — the "Bottom" a bullish vertical count is projected from (book 3.3,
    Image 3.3.4). Needs a completed column on both sides, so the newest
    column can never qualify."""
    if i < 2 or i + 2 >= len(columns) or is_up(columns[i]):
        return False
    return bottom(columns[i]) < bottom(columns[i - 2]) and bottom(columns[i]) < bottom(columns[i + 2])


def is_swing_top(columns: list, i: int) -> bool:
    if i < 2 or i + 2 >= len(columns) or not is_up(columns[i]):
        return False
    return top(columns[i]) > top(columns[i - 2]) and top(columns[i]) > top(columns[i + 2])


def significant_counts(columns: list, settings: BoxSettings,
                       conservative: bool = False) -> list:
    """Every vertical count the book would actually plot: one per column
    that turns off a confirmed swing extreme.

    Book 3.3: "the projection cannot be taken from every column. There are
    rules to define the column that qualifies... It is basically applied
    to the column occurring after a significant Top or Bottom." Projecting
    from every column instead produces one target per swing leg, which is
    noise, not analysis."""
    out = []
    for i in range(1, len(columns)):
        if not (is_swing_bottom(columns, i - 1) or is_swing_top(columns, i - 1)):
            continue
        c = vertical_count(columns, i, settings, conservative)
        if c is not None:
            out.append(c)
    return out


def vertical_count(columns: list, i: int, settings: BoxSettings,
                   conservative: bool = False) -> Optional[Count]:
    """Book 3.3: "Bullish Vertical count = Bottom of the pattern +
    (Length of the pattern x Box-value x Reversal value)", where length is
    the number of boxes in the column and the bottom is the low of the
    PREVIOUS O column. In box-level arithmetic that is exactly
    `bottom_level + boxes * reversal_boxes`, which also makes it correct
    on percentage/log charts where prices are not linear in boxes.

    "Bullish count is always taken from the column of X and Bearish count
    is always taken from column of O", and only from a column following a
    significant top or bottom — the caller decides significance; this
    function projects whichever column it is handed.

    conservative=True halves the multiplier, the book's "Vertical count -
    conservative" variant. Halving can land the projection on a half-box,
    which is not a real box level; the offset is truncated toward the base
    rather than rounded, so a conservative count is never nudged FURTHER
    away than the arithmetic gives (rounding 7.5 boxes up to 8 would make
    the "conservative" target the more aggressive of the two)."""
    if i < 1 or i >= len(columns):
        return None
    c, prev = columns[i], columns[i - 1]
    rv = settings.reversal_boxes
    mult = rv / 2.0 if conservative else rv
    boxes = c.box_count
    offset = int(boxes * mult)  # truncates toward zero; exact when mult is integral
    if is_up(c):
        base = bottom(prev)
        target = base + offset
        bias = "bullish"
    else:
        base = top(prev)
        target = base - offset
        bias = "bearish"
    return Count(
        kind="vertical",
        variant="conservative" if conservative else "standard",
        bias=bias,
        column_index=i,
        target_level=target,
        base_level=base,
        meta={"boxes": boxes, "reversal": rv},
    )


def horizontal_count(columns: list, start: int, end: int, settings: BoxSettings,
                     aggressive: bool = False) -> Optional[Count]:
    """Book 3.3: "Bullish Horizontal count = Bottom of the pattern +
    (Width of the pattern x Box-value x Reversal value)", width being the
    number of columns in the congestion INCLUDING the entry and exit
    columns.

    aggressive=True adds the width to the BREAKOUT level instead of the
    pattern's bottom — the book's own tweak "to make it applicable on
    small horizontal formations", where projecting from the bottom would
    land inside the pattern itself.

    Direction is taken from the exit column: an exit above the pattern's
    highs projects up, below its lows projects down."""
    if start < 0 or end >= len(columns) or end <= start:
        return None
    block = columns[start:end + 1]
    width = len(block)
    rv = settings.reversal_boxes
    move = width * rv
    exit_col = columns[end]
    lo = min(bottom(c) for c in block)
    hi = max(top(c) for c in block)
    if is_up(exit_col):
        base = top(exit_col) if aggressive else lo
        return Count("horizontal", "aggressive" if aggressive else "standard", "bullish",
                     end, base + move, base, {"width": width, "reversal": rv,
                                              "pattern_low": lo, "pattern_high": hi})
    base = bottom(exit_col) if aggressive else hi
    return Count("horizontal", "aggressive" if aggressive else "standard", "bearish",
                 end, base - move, base, {"width": width, "reversal": rv,
                                          "pattern_low": lo, "pattern_high": hi})


def count_to_price(count: Count, settings: BoxSettings, anchor: float) -> dict:
    return {
        "target_price": settings.price_at(count.target_level, anchor),
        "base_price": settings.price_at(count.base_level, anchor),
    }


# ---------------------------------------------------------------------------
# Combined snapshot
# ---------------------------------------------------------------------------


def indicator_snapshot(columns: list, settings: BoxSettings,
                       xo_lookback: int = DEFAULT_XO_LOOKBACK, ma_period: int = 20,
                       rsi_period: int = 14) -> dict:
    """Everything a signal gate typically wants, in one pass."""
    if not columns:
        return {}
    rsi_series = rsi(columns, settings, rsi_period)
    return {
        "trend_45": trend_state(columns),
        "ma_trend": moving_average_trend(columns, settings, ma_period),
        "ma_convergence": ma_convergence(columns, settings),
        "xo_zone": xo_zone_state(columns, xo_lookback),
        "xo_count": (xo_count(columns, xo_lookback) or [None])[-1],
        "rsi": rsi_series[-1] if rsi_series else None,
        "column_count": len(columns),
        "current_direction": "up" if is_up(columns[-1]) else "down",
    }
