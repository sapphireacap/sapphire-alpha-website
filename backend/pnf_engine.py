"""
Point & Figure engine — implements Definedge's documented construction
rules as closely as verified, close-only method exclusively (no
High-Low/HLC mode — out of scope by explicit instruction, and not what
Definedge's own material recommends for time-interval/intraday charts
anyway, see below).

Every rule below is sourced, not assumed — see the docstring on each
one for where it came from. `tests/test_pnf_engine.py` encodes the
book's own fully worked construction exercise (Ch. 1.1, Bajaj Auto,
Sept 2014-Jan 2015, 10 x 3 absolute box-value) as a step-by-step
regression test; this module should never be changed without that
test passing every single step, not just the final state.

Sources:
- "Trading The Markets The Point & Figure Way" (Vivek Patil / Definedge)
  — the book's own worked exercise, Ch. 1.1.
- shelf.definedgesecurities.com/point-figure-chart/... — Definedge's
  public Shelf documentation (some pages login-gated; the ones quoted
  below were accessible).

Verified rules:
1. Box-price (not raw/traded price) is the tracking reference:
   "we calculate box-value and reversal value from the last box-price
   and not the actual price" (book, p.21). Continuation/reversal
   thresholds are always computed from the last PRINTED box-price.
2. Reversal is symmetric: `reversal_boxes` (3, standard) required off
   the open column's extreme box-price, in EITHER direction. Confirmed
   both from Definedge's shelf worked example ("Reversal price is
   2300... three boxes away from box-price of 2330") and the book's
   full Bajaj Auto exercise.
3. Continuation (another box the same direction) only ever needs 1 box.
4. The very FIRST column (before any direction is established) only
   needs 1 box off the starting reference price, NOT `reversal_boxes`
   -- book, step 1 of the exercise: "Plotting will begin with column
   of 'X' if price goes 10 points higher [i.e. ONE box]... and it
   shall begin with column of 'O' if it goes 10 points lower." There is
   no existing column to reverse FROM at the start, so it is treated
   like any other continuation, not a reversal.
5. Box-level calculation is DIRECTION-DEPENDENT, not a single floor/
   ceiling applied uniformly. Confirmed by the book's own exercise:
   price 2302.65 (X column open, extreme 2350, box=10) flips to O and
   is explicitly said to stop at box-price 2310, NOT 2300 - i.e. for a
   falling/O column, a box-price level L only counts as "reached" once
   price <= L (a CEILING of price/box_value), whereas for a rising/X
   column a level only counts as reached once price >= L (a FLOOR).
   Concretely: floor(2302.65/10)=230 -> 2300, which the book says is
   explicitly NOT reached; ceil(2302.65/10)=231 -> 2310, which the
   book says IS reached. Confirmed against several other steps in the
   same exercise (2353.65 -> 2360 not 2350; 2539.70 -> 2540; 2517.90 ->
   2520) - all match ceiling-on-the-way-down, floor-on-the-way-up.
6. Gaps need no special handling: "Gaps are in any case irrelevant...
   I fail to understand this logic [that not displaying gaps is a
   disadvantage]" (book, Ch 5.5). A price series is walked level by
   level; a big single-step move crossing many boxes at once is
   handled identically to several smaller moves reaching the same
   level would be - no gap-fill logic needed or wanted.
7. Close-only (one value per bar) is what the book recommends for
   time-interval/intraday charts specifically: "one-minute price is
   probably the best" and every 1-minute worked example in the book is
   plotted "cl" (closing method), never High-Low. This engine only
   ever processes one value per input bar - High-Low/HLC modes exist
   on Definedge's platform but are deliberately not implemented here.

ASSUMPTION (ties rule 5 to percentage/log box-value charts specifically
-- not directly re-verified against a percentage-chart worked example,
only the book's absolute-box-value exercise): the same floor-up/
ceiling-down asymmetry is applied on the log scale for percentage box
charts (floor(ln(price)/ln(1+box_pct)) rising, ceil(...) falling). This
is the natural generalization of rule 5 to log space, but has not been
independently confirmed against a real percentage-value Definedge
chart's exact printed box prices.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class BoxSettings:
    """Exactly one of box_pct (log/percentage box-value chart) or
    box_value (absolute box-value chart) must be set - the two box-
    value modes the book documents; ATR-based/other exotic modes are
    out of scope."""
    reversal_boxes: int = 3
    box_pct: Optional[float] = None
    box_value: Optional[float] = None

    def __post_init__(self):
        if (self.box_pct is None) == (self.box_value is None):
            raise ValueError("BoxSettings needs exactly one of box_pct or box_value")

    def _raw(self, price: float) -> float:
        if self.box_pct is not None:
            return math.log(price) / math.log(1.0 + self.box_pct)
        return price / self.box_value

    def level_up(self, price: float) -> int:
        """The highest box-price level reached going UP (floor) - see
        module docstring rule 5."""
        return math.floor(self._raw(price))

    def level_down(self, price: float) -> int:
        """The lowest box-price level reached going DOWN (ceiling) -
        see module docstring rule 5."""
        return math.ceil(self._raw(price))

    def price_at(self, level: int) -> float:
        """The real box-price for a level - inverse of level_up/down."""
        if self.box_pct is not None:
            return math.exp(level * math.log(1.0 + self.box_pct))
        return level * self.box_value


@dataclass
class Column:
    direction: str  # "up" | "down"
    start_level: int
    end_level: int

    @property
    def box_count(self) -> int:
        return abs(self.end_level - self.start_level) + 1


def build_columns(prices: list, settings: BoxSettings) -> list[Column]:
    """Walks the full close-only price series and returns every column
    printed, in order - not just the final state, so a caller can
    validate column-by-column (count, direction, box range) against a
    real chart, not just the current direction."""
    vals = [float(p) for p in prices if p is not None and float(p) > 0]
    if not vals:
        return []

    columns: list[Column] = []
    direction: Optional[str] = None
    # Reference point for the very first column - not itself a
    # printed box, just the starting anchor (rule 4).
    ref_level = settings.level_up(vals[0])
    extreme_level = ref_level

    for p in vals[1:]:
        if direction is None:
            up_lv = settings.level_up(p)
            down_lv = settings.level_down(p)
            if up_lv >= ref_level + 1:
                direction = "up"
                extreme_level = up_lv
                columns.append(Column("up", ref_level + 1, extreme_level))
            elif down_lv <= ref_level - 1:
                direction = "down"
                extreme_level = down_lv
                columns.append(Column("down", ref_level - 1, extreme_level))
            continue

        if direction == "up":
            up_lv = settings.level_up(p)
            if up_lv > extreme_level:
                extreme_level = up_lv
                columns[-1].end_level = extreme_level
                continue
            down_lv = settings.level_down(p)
            if down_lv <= extreme_level - settings.reversal_boxes:
                direction = "down"
                new_start = extreme_level - 1
                extreme_level = down_lv
                columns.append(Column("down", new_start, extreme_level))
        else:  # down
            down_lv = settings.level_down(p)
            if down_lv < extreme_level:
                extreme_level = down_lv
                columns[-1].end_level = extreme_level
                continue
            up_lv = settings.level_up(p)
            if up_lv >= extreme_level + settings.reversal_boxes:
                direction = "up"
                new_start = extreme_level + 1
                extreme_level = up_lv
                columns.append(Column("up", new_start, extreme_level))

    return columns


def current_state(columns: list[Column], settings: BoxSettings) -> dict:
    """{"direction": "up"|"down"|None, "extreme_price": float|None} -
    drop-in-compatible shape with the old pnf_column_state()'s return
    value, for callers that only need the current signal, not the full
    column history."""
    if not columns:
        return {"direction": None, "extreme_price": None}
    last = columns[-1]
    return {"direction": last.direction, "extreme_price": settings.price_at(last.end_level)}


def pnf_state(prices: list, box_pct: float = None, box_value: float = None, reversal_boxes: int = 3) -> dict:
    """Convenience one-shot: build the columns and return just the
    current state. Prefer build_columns() directly when the full
    column history is useful (e.g. rendering, pattern detection)."""
    settings = BoxSettings(reversal_boxes=reversal_boxes, box_pct=box_pct, box_value=box_value)
    return current_state(build_columns(prices, settings), settings)
