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
- "Trading The Markets The Point & Figure Way" (Prashant Shah, 2018)
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

8. Percentage/log box-value charts use an ABSOLUTE box grid - box
   boundaries sit at fixed prices (level = log(price)/log(1+box_pct),
   i.e. anchored at price=1), NOT at offsets from whatever price the
   chart happens to start at.

   CORRECTED 2026-08-01, and this reversed the previous rule here.
   From 2026-07-28 this module anchored the grid to the series' own
   first price, on the strength of an old comment in
   blackbox_prism_alpha.py: "a chart starting at 100 flipped to the
   next box at ~100.5, not 101" under absolute-grid-at-1 anchoring.
   That OBSERVATION was accurate but the conclusion drawn from it was
   backwards - flipping at ~100.5 is precisely what a fixed price grid
   does when a series happens to start at 100, because the boundary
   was never at 101 to begin with. It is not a defect; it is the
   defining behaviour, and it is the only behaviour that lets two
   people looking at the same instrument over different amounts of
   history see the SAME boxes.

   Falsified by real chart data (NIFTY 24400 CE, 3% x 3, 31-Jul-2026):
   chart-relative anchoring made the current column direction depend on
   the lookback - O over a 3/7-day window but X over 15/30/60/90 days,
   on identical parameters - while the absolute grid returned the same
   column (291.57..309.33, flip at 318.61) over every one of those
   windows, and matched what the real platform chart showed. A rule
   whose answer changes with how far back you scroll cannot be what a
   charting platform implements.

   Note the book's own worked exercise cannot distinguish the two: it
   is an ABSOLUTE box-value chart (box=10) starting at 2300, already a
   clean multiple of the box, so both anchorings agree throughout. That
   is why this went unresolved for so long.

   `price_at()`/`level_up()`/`level_down()` still take an explicit
   `anchor` (default 1.0 = the absolute grid). Set
   BoxSettings(absolute_grid=False) to restore the old chart-relative
   behaviour for comparison; nothing in production should need it.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional

_EPS = 1e-9  # float-error guard for level_up/level_down - see their docstrings


@dataclass(frozen=True)
class BoxSettings:
    """Exactly one of box_pct (log/percentage box-value chart) or
    box_value (absolute box-value chart) must be set - the two box-
    value modes the book documents; ATR-based/other exotic modes are
    out of scope."""
    reversal_boxes: int = 3
    box_pct: Optional[float] = None
    box_value: Optional[float] = None
    # See module docstring rule 8. True (the default) puts box boundaries
    # at fixed prices, so the same instrument reads identically no matter
    # how much history is loaded. False restores the superseded
    # chart-relative anchoring, kept only for A/B comparison.
    absolute_grid: bool = True

    def __post_init__(self):
        if (self.box_pct is None) == (self.box_value is None):
            raise ValueError("BoxSettings needs exactly one of box_pct or box_value")

    def _raw(self, price: float, anchor: float = 1.0) -> float:
        if self.box_pct is not None:
            # anchor matters here (see module docstring rule 8) - box_value
            # mode is anchor-independent (a linear grid from 0), so anchor
            # is silently ignored on that path, not an error.
            return math.log(price / anchor) / math.log(1.0 + self.box_pct)
        return price / self.box_value

    def level_up(self, price: float, anchor: float = 1.0) -> int:
        """The highest box-price level reached going UP (floor) - see
        module docstring rule 5. `anchor` must be the series' own first
        price for box_pct mode (rule 8) - box_value mode ignores it.
        The `+ _EPS` guards against a price that's mathematically exactly
        on a boundary landing just under its true integer level due to
        float error - confirmed to actually occur (e.g. log(102.01/100)/
        log(1.01) computes to 1.999999999999999, not exactly 2.0, for a
        price that's precisely 2 boxes above a 1% anchor)."""
        return math.floor(self._raw(price, anchor) + _EPS)

    def level_down(self, price: float, anchor: float = 1.0) -> int:
        """The lowest box-price level reached going DOWN (ceiling) - see
        module docstring rule 5. Same `anchor` requirement and float-error
        guard as level_up, mirrored (subtract instead of add, since this
        rounds up instead of down)."""
        return math.ceil(self._raw(price, anchor) - _EPS)

    def price_at(self, level: int, anchor: float = 1.0) -> float:
        """The real box-price for a level - inverse of level_up/down.
        Same `anchor` requirement as level_up/level_down."""
        if self.box_pct is not None:
            return anchor * math.exp(level * math.log(1.0 + self.box_pct))
        return level * self.box_value


@dataclass
class Column:
    direction: str  # "up" | "down"
    start_level: int
    end_level: int
    anchor: float = 1.0  # the series' own first price (box_pct mode) - pass
                         # this back into settings.price_at(level, anchor)
                         # to recover a real price; unused for box_value mode.
    # Index into the INPUT price series of the sample that opened this
    # column and of the latest sample that extended it. P&F has no time
    # axis, so these are not part of the chart's logic at all - they exist
    # purely so a caller can label a column with the date/timestamp it
    # formed over (a chart needs "this column ran from Jan 3 to Jan 19").
    # Default -1 means "not tracked", which is what hand-built Columns in
    # tests and pattern fixtures carry.
    start_index: int = -1
    end_index: int = -1

    @property
    def box_count(self) -> int:
        return abs(self.end_level - self.start_level) + 1


def build_columns(prices: list, settings: BoxSettings) -> list[Column]:
    """Walks the full close-only price series and returns every column
    printed, in order - not just the final state, so a caller can
    validate column-by-column (count, direction, box range) against a
    real chart, not just the current direction.

    For box_pct (percentage) charts, the series' own first price is
    used as the anchor throughout (rule 8) - box_value (absolute)
    charts are anchor-independent, so this doesn't affect them. Each
    returned Column carries that anchor (see Column.anchor) so a caller
    can convert levels back to real prices without tracking it
    separately."""
    # Keep each kept value's index in the ORIGINAL `prices` list, so a
    # caller can map a column back to the bars/timestamps it spans even
    # when Nones or non-positive prices were filtered out here.
    kept = [(n, float(p)) for n, p in enumerate(prices) if p is not None and float(p) > 0]
    idxs = [n for n, _ in kept]
    vals = [v for _, v in kept]
    if not vals:
        return []

    # Rule 8: an absolute grid ignores where the series starts, so the
    # anchor is the fixed reference price 1.0. Every Column still carries
    # its anchor so price_at() round-trips regardless of which mode built it.
    anchor = 1.0 if settings.absolute_grid else vals[0]
    columns: list[Column] = []
    direction: Optional[str] = None
    # Reference point for the very first column - not itself a
    # printed box, just the starting anchor (rule 4). By construction
    # level_up(anchor, anchor) == 0 always (log(anchor/anchor) == 0).
    ref_level = settings.level_up(vals[0], anchor)
    extreme_level = ref_level

    # `bar` is the index into the caller's original `prices` list of the
    # sample being processed - carried onto each Column purely for
    # labelling (see Column.start_index). end_index advances only when the
    # column actually PRINTS a new box, so it marks the column's last real
    # print rather than the last sample that happened to sit inside it.
    for pos, p in enumerate(vals[1:], start=1):
        bar = idxs[pos]
        if direction is None:
            up_lv = settings.level_up(p, anchor)
            down_lv = settings.level_down(p, anchor)
            if up_lv >= ref_level + 1:
                direction = "up"
                extreme_level = up_lv
                columns.append(Column("up", ref_level + 1, extreme_level, anchor, bar, bar))
            elif down_lv <= ref_level - 1:
                direction = "down"
                extreme_level = down_lv
                columns.append(Column("down", ref_level - 1, extreme_level, anchor, bar, bar))
            continue

        if direction == "up":
            up_lv = settings.level_up(p, anchor)
            if up_lv > extreme_level:
                extreme_level = up_lv
                columns[-1].end_level = extreme_level
                columns[-1].end_index = bar
                continue
            down_lv = settings.level_down(p, anchor)
            if down_lv <= extreme_level - settings.reversal_boxes:
                direction = "down"
                new_start = extreme_level - 1
                extreme_level = down_lv
                columns.append(Column("down", new_start, extreme_level, anchor, bar, bar))
        else:  # down
            down_lv = settings.level_down(p, anchor)
            if down_lv < extreme_level:
                extreme_level = down_lv
                columns[-1].end_level = extreme_level
                columns[-1].end_index = bar
                continue
            up_lv = settings.level_up(p, anchor)
            if up_lv >= extreme_level + settings.reversal_boxes:
                direction = "up"
                new_start = extreme_level + 1
                extreme_level = up_lv
                columns.append(Column("up", new_start, extreme_level, anchor, bar, bar))

    return columns


def current_state(columns: list, settings: BoxSettings) -> dict:
    """{"direction": "up"|"down"|None, "extreme_price": float|None} -
    drop-in-compatible shape with the old pnf_column_state()'s return
    value, for callers that only need the current signal, not the full
    column history."""
    if not columns:
        return {"direction": None, "extreme_price": None}
    last = columns[-1]
    return {"direction": last.direction, "extreme_price": settings.price_at(last.end_level, last.anchor)}


def pnf_state(prices: list, box_pct: float = None, box_value: float = None, reversal_boxes: int = 3) -> dict:
    """Convenience one-shot: build the columns and return just the
    current state. Prefer build_columns() directly when the full
    column history is useful (e.g. rendering, pattern detection)."""
    settings = BoxSettings(reversal_boxes=reversal_boxes, box_pct=box_pct, box_value=box_value)
    return current_state(build_columns(prices, settings), settings)
