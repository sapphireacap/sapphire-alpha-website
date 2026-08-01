"""Point & Figure pattern library — every formation documented in
"Trading The Markets The Point & Figure Way" (Prashant Shah, 2018), the
book written by Definedge's own founder, implemented against the
book-validated construction engine in `pnf_engine.py`.

WHY THIS MODULE EXISTS SEPARATELY from the pattern helpers already in
`blackbox_prism_alpha.py`: those are strategy-local, deliberately tuned
for one options setup (e.g. its Low Pole intentionally does NOT require
the retracement in the immediately-following column, because that
strategy's live validation against a real Definedge chart demanded the
looser reading). This module is the opposite: a faithful, general
transcription of the book's rules, meant for charting/scanning across
any instrument. Neither should be "fixed" to match the other — they
answer different questions. See the notes on each detector where they
diverge.

EVERYTHING WORKS IN BOX LEVELS (integers), NOT PRICES. `pnf_engine`
already resolves a price to an exact integer box level, so "two columns
whose highs are at the same level" is an exact `==`, never a float
comparison with a tolerance. Convert a level back to a real price with
`settings.price_at(level, column.anchor)`.

COLUMN GEOMETRY. `pnf_engine.Column` stores start_level/end_level in
travel order, so an X column's end_level is its high while an O
column's end_level is its low. Always go through `top()`/`bottom()`
below rather than touching start/end directly.

SOURCES — section numbers refer to the book:
  2.1 Major patterns .... Triple Top/Bottom, Trap, Pole, Triangle
  2.2 Other patterns .... Broadening, Double Broadening, 100% Pole,
                          Pattern Reversed, Catapult
  2.3 Follow-through
  2.5 Pattern retest ..... double/triple pattern
  2.6 Turtle on P&F ...... N-column breakout
  2.7 Variations ......... Quadruple, Spread Triple, Weak Breakout,
                          Five-box Trap, Ziddi, Diamond, Super pattern
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Optional

from pnf_engine import BoxSettings, Column

# ---------------------------------------------------------------------------
# Column geometry helpers
# ---------------------------------------------------------------------------


def top(c: Column) -> int:
    """Highest box level printed in the column (an X column's high, an O
    column's starting level)."""
    return max(c.start_level, c.end_level)


def bottom(c: Column) -> int:
    """Lowest box level printed in the column."""
    return min(c.start_level, c.end_level)


def mid_level(c: Column) -> float:
    """Midpoint in LEVEL space. Correct only for absolute box-value
    charts, where levels are linear in price. For percentage/log charts
    use mid_price() — see the warning there."""
    return (top(c) + bottom(c)) / 2.0


def mid_price(c: Column, settings: Optional[BoxSettings] = None) -> float:
    """Book 2.1: 'Mid-box-price of column: (High Box-price + Low
    Box-price)/2' — the ARITHMETIC mean of the two PRICES.

    On a percentage/log chart that is NOT the same as the midpoint of the
    box levels: averaging levels and converting back gives the GEOMETRIC
    mean. Verified against the real platform's own commentary panel
    (NIFTY 24400 CE, 3% x 3, 31-Jul-2026): a column spanning 291.57 to
    309.33 is reported MidVal 300.45, which is (291.57 + 309.33) / 2 =
    300.45, not the geometric 300.32; and 283.08..318.61 is reported
    300.85, again the arithmetic mean. This matters because the Pole
    rules are 50%-retracement tests measured off exactly this value.

    Falls back to the level midpoint when no settings are supplied, which
    is exact for absolute box-value charts (linear grid) and only
    approximate for percentage ones."""
    if settings is None:
        return mid_level(c)
    return (settings.price_at(top(c), c.anchor) + settings.price_at(bottom(c), c.anchor)) / 2.0


def is_up(c: Column) -> bool:
    return c.direction == "up"


def is_down(c: Column) -> bool:
    return c.direction == "down"


@dataclass(frozen=True)
class PatternConfig:
    """Every book-documented parameter that the text itself says is
    tunable. Defaults are the book's own stated values."""

    # 2.1 Pole: "Minimum five boxes in favor after Buy signal" and the
    # 50% retracement. The book says minimum five (>=5); Definedge's own
    # platform wording reads as strictly more than five. The default
    # follows the book, since the book IS the founder's specification —
    # set pole_min_boxes=6 to reproduce the stricter platform reading.
    pole_min_boxes: int = 5
    # 2.1: "50% requirement can be replaced by some Fib number like 61.8
    # or 38.2 or any other number."
    pole_retrace: float = 0.50
    # 2.6 Turtle: "a bullish breakout may be defined as a column of 'X'
    # rising above the prior 10-columns of 'X'."
    turtle_columns: int = 10
    # 2.7 Super pattern: "Price travels minimum ten boxes after Buy
    # signal" / "Immediate column of 'O' forming less than or equal to
    # four boxes". Book: "It can be Super 8... or Super 3."
    super_min_boxes: int = 10
    super_max_pullback: int = 4
    # 2.7 Weak breakout: "only one or two boxes of 'X' after a Double Top
    # Buy signal".
    weak_breakout_max_boxes: int = 2
    # 2.7 Five-box trap: "the number of boxes in the column preceding the
    # breakout is less than 5".
    small_trap_max_boxes: int = 5
    # 2.1 Triangle: the 50% rule applies only to three-column triangles.
    triangle_50_rule: bool = False
    # 2.5 Pattern retest: "there should be at least three columns between
    # the two patterns to call it a valid double pattern retest".
    retest_min_gap_columns: int = 3
    # 2.5: how close two patterns must sit to count as "the same zone",
    # as a fraction of the instrument's own recent box range.
    retest_zone_boxes: int = 3
    # Anchor Column is Definedge-platform terminology (not in the book,
    # which describes only a general "long column"); kept configurable.
    anchor_min_boxes: int = 15
    # The chart's own box settings. Only the Pole family needs this — its
    # 50%-retracement test is measured off the column's mid-PRICE, which
    # on a percentage/log chart cannot be derived from box levels alone
    # (see mid_price). Left None, the Pole rules fall back to level-space
    # arithmetic, which stays exact for absolute box-value charts.
    settings: Optional[BoxSettings] = None


DEFAULT_CONFIG = PatternConfig()


@dataclass
class Pattern:
    """One detected formation.

    `index` is the column at which the pattern COMPLETES (the column whose
    printing qualifies it) — that is the bar-equivalent of "the signal
    fired here". `start_index` is the first column belonging to the
    formation, so `columns[start_index:index + 1]` is the whole thing.

    `trigger_level` is the box level at which it qualified, and
    `failure_level` the level whose breach negates it (book: every pattern
    carries its own predefined failure rule — see 2.8). Both are box
    levels; convert with settings.price_at(level, anchor)."""

    name: str
    label: str
    bias: str  # "bullish" | "bearish" | "neutral"
    index: int
    start_index: int
    trigger_level: Optional[int] = None
    failure_level: Optional[int] = None
    meta: dict = field(default_factory=dict)

    def prices(self, settings: BoxSettings, anchor: float) -> dict:
        """Real prices for trigger/failure, for display or order levels."""
        out = {}
        if self.trigger_level is not None:
            out["trigger_price"] = settings.price_at(self.trigger_level, anchor)
        if self.failure_level is not None:
            out["failure_price"] = settings.price_at(self.failure_level, anchor)
        return out


# ---------------------------------------------------------------------------
# 1.2 / 2.1 — Basic signals. Every other breakout pattern in the book is
# built on top of these two, so they are plain booleans rather than
# Pattern objects, and get wrapped into Patterns further down.
# ---------------------------------------------------------------------------


def is_double_top_buy(columns: list, i: int) -> bool:
    """Column i (X) prints a box above the high of the previous X column.
    Columns strictly alternate by construction, so 'the previous X
    column' is always i-2."""
    if i < 2 or not is_up(columns[i]) or not is_up(columns[i - 2]):
        return False
    return top(columns[i]) > top(columns[i - 2])


def is_double_bottom_sell(columns: list, i: int) -> bool:
    """Mirror of is_double_top_buy."""
    if i < 2 or not is_down(columns[i]) or not is_down(columns[i - 2]):
        return False
    return bottom(columns[i]) < bottom(columns[i - 2])


def is_basic_signal(columns: list, i: int) -> Optional[str]:
    """"bullish"/"bearish"/None — which basic signal, if any, column i fired."""
    if is_double_top_buy(columns, i):
        return "bullish"
    if is_double_bottom_sell(columns, i):
        return "bearish"
    return None


def breakout_level(columns: list, i: int) -> Optional[int]:
    """The level column i broke to fire its basic signal — i.e. one box
    past the reference column's extreme. Book 1.1: the signal triggers at
    the box beyond the prior column's extreme, not at the extreme itself."""
    if is_double_top_buy(columns, i):
        return top(columns[i - 2]) + 1
    if is_double_bottom_sell(columns, i):
        return bottom(columns[i - 2]) - 1
    return None


def _px(c: Column, level: int, cfg) -> float:
    """A box level as a real price, for the rules that must be measured in
    price space rather than box space (the Pole retracements — see
    mid_price). With no settings on the config this degrades to the level
    itself, which keeps every comparison self-consistent and is exactly
    right for absolute box-value charts."""
    if cfg.settings is None:
        return float(level)
    return cfg.settings.price_at(level, c.anchor)


def _lowest(columns: list, a: int, b: int) -> int:
    return min(bottom(c) for c in columns[a:b + 1])


def _highest(columns: list, a: int, b: int) -> int:
    return max(top(c) for c in columns[a:b + 1])


# ---------------------------------------------------------------------------
# 2.1 — Triple Top Buy / Triple Bottom Sell
# ---------------------------------------------------------------------------


def detect_triple_top_buy(columns: list, i: int, cfg=DEFAULT_CONFIG) -> Optional[Pattern]:
    """Strictly a five-column formation (book 2.1: 'if someone asks, is it
    ok if it is a six-column setup instead of five, or X is not exactly at
    the same level? The answer is No'): two X columns with their highs at
    exactly the same level, then a breakout above that level in the fifth
    column.

    Failure level: 'the pattern does not fail unless price falls below the
    lowest O in the pattern'."""
    if i < 4:
        return None
    c0, c2, c4 = columns[i - 4], columns[i - 2], columns[i]
    if not (is_up(c0) and is_up(c2) and is_up(c4)):
        return None
    if top(c0) != top(c2):
        return None
    if top(c4) <= top(c2):
        return None
    return Pattern(
        name="triple_top_buy",
        label="Triple Top Buy",
        bias="bullish",
        index=i,
        start_index=i - 4,
        trigger_level=top(c2) + 1,
        failure_level=_lowest(columns, i - 4, i) - 1,
        meta={"resistance_level": top(c2)},
    )


def detect_triple_bottom_sell(columns: list, i: int, cfg=DEFAULT_CONFIG) -> Optional[Pattern]:
    """Mirror of detect_triple_top_buy; fails above the highest X in the pattern."""
    if i < 4:
        return None
    c0, c2, c4 = columns[i - 4], columns[i - 2], columns[i]
    if not (is_down(c0) and is_down(c2) and is_down(c4)):
        return None
    if bottom(c0) != bottom(c2):
        return None
    if bottom(c4) >= bottom(c2):
        return None
    return Pattern(
        name="triple_bottom_sell",
        label="Triple Bottom Sell",
        bias="bearish",
        index=i,
        start_index=i - 4,
        trigger_level=bottom(c2) - 1,
        failure_level=_highest(columns, i - 4, i) + 1,
        meta={"support_level": bottom(c2)},
    )


# ---------------------------------------------------------------------------
# 2.7 — Quadruple / Spread Triple (multi-column breakout variations)
# ---------------------------------------------------------------------------


def detect_quadruple_top_buy(columns: list, i: int, cfg=DEFAULT_CONFIG) -> Optional[Pattern]:
    """Book 2.7: 'If there is a Double Top Buy signal after three X's at
    similar level instead of two, then it is known as Quadruple Top Buy'.
    A seven-column formation; rare but stronger."""
    if i < 6:
        return None
    xs = [columns[i - 6], columns[i - 4], columns[i - 2]]
    if not all(is_up(c) for c in xs) or not is_up(columns[i]):
        return None
    if not (top(xs[0]) == top(xs[1]) == top(xs[2])):
        return None
    if top(columns[i]) <= top(xs[2]):
        return None
    return Pattern(
        name="quadruple_top_buy",
        label="Quadruple Top Buy",
        bias="bullish",
        index=i,
        start_index=i - 6,
        trigger_level=top(xs[2]) + 1,
        failure_level=_lowest(columns, i - 6, i) - 1,
        meta={"resistance_level": top(xs[2])},
    )


def detect_quadruple_bottom_sell(columns: list, i: int, cfg=DEFAULT_CONFIG) -> Optional[Pattern]:
    if i < 6:
        return None
    os_ = [columns[i - 6], columns[i - 4], columns[i - 2]]
    if not all(is_down(c) for c in os_) or not is_down(columns[i]):
        return None
    if not (bottom(os_[0]) == bottom(os_[1]) == bottom(os_[2])):
        return None
    if bottom(columns[i]) >= bottom(os_[2]):
        return None
    return Pattern(
        name="quadruple_bottom_sell",
        label="Quadruple Bottom Sell",
        bias="bearish",
        index=i,
        start_index=i - 6,
        trigger_level=bottom(os_[2]) - 1,
        failure_level=_highest(columns, i - 6, i) + 1,
        meta={"support_level": bottom(os_[2])},
    )


def detect_spread_triple_top_buy(columns: list, i: int, cfg=DEFAULT_CONFIG) -> Optional[Pattern]:
    """Book 2.7: a seven-column Triple Top where the two shoulders are at
    the same level but an extra X column sits between them without
    breaking out. 'Still a breakout from resistance... simply defined as
    multi-column breakout patterns.' Excludes the strict Triple (which is
    five columns) and the Quadruple (three equal highs)."""
    if i < 6:
        return None
    a, mid, b, brk = columns[i - 6], columns[i - 4], columns[i - 2], columns[i]
    if not all(is_up(c) for c in (a, mid, b, brk)):
        return None
    if top(a) != top(b):
        return None
    if top(mid) >= top(a):  # would be a breakout or a Quadruple, not a spread
        return None
    if top(brk) <= top(b):
        return None
    return Pattern(
        name="spread_triple_top_buy",
        label="Spread Triple Top Buy",
        bias="bullish",
        index=i,
        start_index=i - 6,
        trigger_level=top(b) + 1,
        failure_level=_lowest(columns, i - 6, i) - 1,
        meta={"resistance_level": top(b)},
    )


def detect_spread_triple_bottom_sell(columns: list, i: int, cfg=DEFAULT_CONFIG) -> Optional[Pattern]:
    if i < 6:
        return None
    a, mid, b, brk = columns[i - 6], columns[i - 4], columns[i - 2], columns[i]
    if not all(is_down(c) for c in (a, mid, b, brk)):
        return None
    if bottom(a) != bottom(b):
        return None
    if bottom(mid) <= bottom(a):
        return None
    if bottom(brk) >= bottom(b):
        return None
    return Pattern(
        name="spread_triple_bottom_sell",
        label="Spread Triple Bottom Sell",
        bias="bearish",
        index=i,
        start_index=i - 6,
        trigger_level=bottom(b) - 1,
        failure_level=_highest(columns, i - 6, i) + 1,
        meta={"support_level": bottom(b)},
    )


# ---------------------------------------------------------------------------
# 2.1 — Traps
# ---------------------------------------------------------------------------


def detect_bull_trap(columns: list, i: int, cfg=DEFAULT_CONFIG) -> Optional[Pattern]:
    """Book 2.1: 'when a sell pattern occurs immediately after a buy
    pattern, it is a Bull Trap formation' — strictly a four-column
    pattern, qualifying at the box-price that completes the Double Bottom
    Sell. Bearish.

    'the basic Buy-Sell signal and pattern failure level is the same in
    case of traps' — so it fails on the next Double Top Buy, i.e. above
    the high of the trapped X column."""
    if i < 3:
        return None
    if not is_double_bottom_sell(columns, i):
        return None
    if not is_double_top_buy(columns, i - 1):
        return None
    return Pattern(
        name="bull_trap",
        label="Bull Trap",
        bias="bearish",
        index=i,
        start_index=i - 3,
        trigger_level=bottom(columns[i - 2]) - 1,
        failure_level=top(columns[i - 1]) + 1,
        meta={"trapped_buy_index": i - 1},
    )


def detect_bear_trap(columns: list, i: int, cfg=DEFAULT_CONFIG) -> Optional[Pattern]:
    """Mirror of Bull Trap: a Double Top Buy immediately after a Double
    Bottom Sell. Bullish. Book: 'Bear traps in Uptrend and Bull traps in
    Downtrend are effective setups' — direction filtering is the caller's
    job (see pnf_indicators.trend_state)."""
    if i < 3:
        return None
    if not is_double_top_buy(columns, i):
        return None
    if not is_double_bottom_sell(columns, i - 1):
        return None
    return Pattern(
        name="bear_trap",
        label="Bear Trap",
        bias="bullish",
        index=i,
        start_index=i - 3,
        trigger_level=top(columns[i - 2]) + 1,
        failure_level=bottom(columns[i - 1]) - 1,
        meta={"trapped_sell_index": i - 1},
    )


def detect_five_box_trap(columns: list, i: int, cfg=DEFAULT_CONFIG) -> Optional[Pattern]:
    """Book 2.7: 'It is a five-box Trap because the number of boxes in the
    column preceding the breakout is less than 5' — a trap whose trapped
    column was a weak breakout, so the initial risk is smaller. Reported
    alongside (not instead of) the plain trap.

    Deliberately NOT named "five-box"/"four-box" per the book's own
    numbering: the text calls a trap "five-box" when the preceding column
    has fewer than five boxes, yet also says a one-box weak breakout makes
    a "four-box Trap" — the two statements don't reduce to one arithmetic
    rule from the text alone (the accompanying image isn't in the
    extractable content). The exact box count is carried in meta instead
    of inventing a numbering scheme that might be wrong."""
    trap = detect_bull_trap(columns, i, cfg) or detect_bear_trap(columns, i, cfg)
    if trap is None:
        return None
    trapped = columns[i - 1]
    if trapped.box_count >= cfg.small_trap_max_boxes:
        return None
    return Pattern(
        name="small_box_trap",
        label=f"Small-Box Trap ({trapped.box_count})",
        bias=trap.bias,
        index=i,
        start_index=trap.start_index,
        trigger_level=trap.trigger_level,
        failure_level=trap.failure_level,
        meta={"trapped_boxes": trapped.box_count, "base": trap.name},
    )


# ---------------------------------------------------------------------------
# 2.1 — Poles (the only reversal formation in P&F)
# ---------------------------------------------------------------------------


def _pole_breakout_boxes(columns: list, j: int) -> Optional[int]:
    """Boxes travelled past the basic signal by column j, counting the
    breakout box itself. Book 2.1's worked example: Double Top Buy at
    box-price 100 travelling to 140 on a 10-box chart is called 'five
    boxes after the buy signal', i.e. top(j) - top(j-2) == 5."""
    if is_double_top_buy(columns, j):
        return top(columns[j]) - top(columns[j - 2])
    if is_double_bottom_sell(columns, j):
        return bottom(columns[j - 2]) - bottom(columns[j])
    return None


def detect_high_pole(columns: list, i: int, cfg=DEFAULT_CONFIG) -> Optional[Pattern]:
    """Bearish. Three stages, all inside four columns (book 2.1):
      1. Double Top Buy in column i-1,
      2. at least `pole_min_boxes` boxes in favour after that signal,
      3. the IMMEDIATELY following column of O falls below the mid-price
         of that X column (mid of the whole column, not just the boxes
         after the breakout).

    Note the immediacy requirement is enforced here, faithful to the book
    — `blackbox_prism_alpha.find_low_pole` deliberately relaxes it for its
    own strategy; see this module's docstring.

    'High price of breakout column of X is the highest point of the High
    Pole formation; pattern fails if price goes above the same.'"""
    if i < 3 or not is_down(columns[i]):
        return None
    j = i - 1
    boxes = _pole_breakout_boxes(columns, j)
    if boxes is None or not is_up(columns[j]) or boxes < cfg.pole_min_boxes:
        return None
    # Retracement is measured in PRICE space off the pole column's high
    # and low (book: mid-price = (High Box-price + Low Box-price)/2), not
    # in box levels — see mid_price(). Identical on absolute box-value
    # charts, materially different on percentage/log ones.
    hi, lo = _px(columns[j], top(columns[j]), cfg), _px(columns[j], bottom(columns[j]), cfg)
    if hi <= lo:
        return None
    retrace_price = hi - cfg.pole_retrace * (hi - lo)
    if _px(columns[i], bottom(columns[i]), cfg) >= retrace_price:
        return None
    return Pattern(
        name="high_pole",
        label="High Pole",
        bias="bearish",
        index=i,
        start_index=j - 2,
        trigger_level=bottom(columns[i]),
        failure_level=top(columns[j]) + 1,
        meta={
            "pole_index": j,
            "pole_boxes": columns[j].box_count,
            "boxes_after_breakout": boxes,
            "mid_level": mid_level(columns[j]),
            "mid_price": mid_price(columns[j], cfg.settings),
            "retrace_pct": (hi - _px(columns[i], bottom(columns[i]), cfg)) / (hi - lo),
        },
    )


def detect_low_pole(columns: list, i: int, cfg=DEFAULT_CONFIG) -> Optional[Pattern]:
    """Bullish mirror of High Pole. 'Low Pole gets formed in the column of
    X, being bullish formation.' Fails below the low of the breakout O
    column."""
    if i < 3 or not is_up(columns[i]):
        return None
    j = i - 1
    boxes = _pole_breakout_boxes(columns, j)
    if boxes is None or not is_down(columns[j]) or boxes < cfg.pole_min_boxes:
        return None
    hi, lo = _px(columns[j], top(columns[j]), cfg), _px(columns[j], bottom(columns[j]), cfg)
    if hi <= lo:
        return None
    retrace_price = lo + cfg.pole_retrace * (hi - lo)
    if _px(columns[i], top(columns[i]), cfg) <= retrace_price:
        return None
    return Pattern(
        name="low_pole",
        label="Low Pole",
        bias="bullish",
        index=i,
        start_index=j - 2,
        trigger_level=top(columns[i]),
        failure_level=bottom(columns[j]) - 1,
        meta={
            "pole_index": j,
            "pole_boxes": columns[j].box_count,
            "boxes_after_breakout": boxes,
            "mid_level": mid_level(columns[j]),
            "mid_price": mid_price(columns[j], cfg.settings),
            "retrace_pct": (_px(columns[i], top(columns[i]), cfg) - lo) / (hi - lo),
        },
    )


def detect_bullish_100_pole(columns: list, i: int, cfg=DEFAULT_CONFIG) -> Optional[Pattern]:
    """Book 2.2: 'after forming Low Pole, if X continues to rise and
    generate Double Top Buy formation in the same column, then it is a
    bullish 100% Pole'. Simultaneously a Low Pole, a Bear Trap and a
    Double Top Buy — the book is explicit that all three are true at
    once, so this is reported IN ADDITION to those, never instead."""
    pole = detect_low_pole(columns, i, cfg)
    if pole is None:
        return None
    if not is_double_top_buy(columns, i):
        return None
    return Pattern(
        name="bullish_100_pole",
        label="Bullish 100% Pole",
        bias="bullish",
        index=i,
        start_index=pole.start_index,
        trigger_level=top(columns[i - 2]) + 1,
        failure_level=bottom(columns[i - 1]) - 1,
        meta={**pole.meta, "base": "low_pole"},
    )


def detect_bearish_100_pole(columns: list, i: int, cfg=DEFAULT_CONFIG) -> Optional[Pattern]:
    """Mirror: a High Pole whose O column carries on to complete a Double
    Bottom Sell in the same column."""
    pole = detect_high_pole(columns, i, cfg)
    if pole is None:
        return None
    if not is_double_bottom_sell(columns, i):
        return None
    return Pattern(
        name="bearish_100_pole",
        label="Bearish 100% Pole",
        bias="bearish",
        index=i,
        start_index=pole.start_index,
        trigger_level=bottom(columns[i - 2]) - 1,
        failure_level=top(columns[i - 1]) + 1,
        meta={**pole.meta, "base": "high_pole"},
    )


# ---------------------------------------------------------------------------
# 2.1 — Inside columns and Triangles
# ---------------------------------------------------------------------------


def is_inside_column(columns: list, i: int) -> bool:
    """Book 2.1: 'the high of the inside column is below the high of its
    previous column and low is above the low of its previous column'."""
    if i < 1:
        return False
    return top(columns[i]) < top(columns[i - 1]) and bottom(columns[i]) > bottom(columns[i - 1])


def _triangle_run(columns: list, i: int) -> int:
    """How many consecutive inside columns end at column i."""
    n = 0
    k = i
    while k >= 1 and is_inside_column(columns, k):
        n += 1
        k -= 1
    return n


def detect_triangle(columns: list, i: int, cfg=DEFAULT_CONFIG) -> Optional[Pattern]:
    """A converging formation, reported at the column that LOCKS it.

    Book 2.1: 'an Inside Column actually forms upon occurrence of third
    column... Occurrence of third column locks the Inside Column pattern',
    and 'a three-column Triangle gets locked over appearance of fourth
    column'. So the triangle is reported at column i once the run of
    inside columns ENDING AT i-1 is long enough — column i is the one that
    locks it and is also the earliest possible breakout column.

    Two inside columns => three-column triangle; three => four-column, and
    so on. Neutral until broken: 'Triangle is a neutral formation and it
    becomes bullish or bearish based on the direction of the breakout'.

    The 50% rule ('each column in the series of three-column triangle
    should be at least half the length of its previous column') applies
    only to three-column triangles and only when cfg.triangle_50_rule is
    on — the book presents it as an optional refinement to learn later."""
    if i < 3:
        return None
    run = _triangle_run(columns, i - 1)
    if run < 2:
        return None
    start = i - 1 - run  # the reference column the first inside column sat within
    cols = columns[start:i]
    if run == 2 and cfg.triangle_50_rule:
        for a, b in zip(cols, cols[1:]):
            if a.box_count > 2 * b.box_count:
                return None
    return Pattern(
        name="triangle",
        label=f"{run + 1}-Column Triangle",
        bias="neutral",
        index=i,
        start_index=start,
        trigger_level=None,
        # Book: bullish breakout stays valid until price falls below the
        # recent O of the pattern (and vice versa) — both edges are
        # meaningful until a direction exists, so expose them in meta.
        failure_level=None,
        meta={
            "inside_columns": run,
            "upper_level": _highest(columns, start, i - 1),
            "lower_level": _lowest(columns, start, i - 1),
        },
    )


def detect_triangle_breakout(columns: list, i: int, cfg=DEFAULT_CONFIG) -> Optional[Pattern]:
    """Book 2.1: 'a Double Top Buy after Triangle is a bullish Triangle
    breakout'. 'Breakout can happen in the fifth column or any column
    after that' — so this walks back over any further inside columns
    rather than requiring the breakout to be immediate.

    Failure: 'Triangle formation when followed after bullish breakout
    remains valid until price falls below recent O of the pattern.'"""
    signal = is_basic_signal(columns, i)
    if signal is None:
        return None
    # Walk back for the triangle this signal breaks out of. Any basic
    # signal strictly between the triangle's locking column and i means
    # the breakout already happened earlier and THIS signal is just a
    # later continuation — so the search stops there rather than
    # attributing every subsequent signal to a long-past triangle.
    tri = None
    for k in range(i, 2, -1):
        if k < i and is_basic_signal(columns, k) is not None:
            break
        cand = detect_triangle(columns, k, cfg)
        if cand is not None:
            tri = cand
            break
    if tri is None:
        return None
    if tri.meta["inside_columns"] < 2:
        return None
    bullish = signal == "bullish"
    return Pattern(
        name="triangle_breakout_bullish" if bullish else "triangle_breakout_bearish",
        label="Bullish Triangle Breakout" if bullish else "Bearish Triangle Breakout",
        bias=signal,
        index=i,
        start_index=tri.start_index,
        trigger_level=breakout_level(columns, i),
        failure_level=(_lowest(columns, tri.start_index, i) - 1) if bullish
        else (_highest(columns, tri.start_index, i) + 1),
        meta={"triangle_index": tri.index, "inside_columns": tri.meta["inside_columns"]},
    )


# ---------------------------------------------------------------------------
# 2.2 — Broadening / Double Broadening
# ---------------------------------------------------------------------------


def detect_bullish_broadening(columns: list, i: int, cfg=DEFAULT_CONFIG) -> Optional[Pattern]:
    """Book 2.2: 'A buy pattern immediately formed after Bull Trap is a
    five-column pattern with consecutive Buy-Sell-Buy patterns known as
    Bullish Broadening formation.' Fails below the lowest O of the
    pattern."""
    if i < 4:
        return None
    if not is_double_top_buy(columns, i):
        return None
    if detect_bull_trap(columns, i - 1, cfg) is None:
        return None
    return Pattern(
        name="bullish_broadening",
        label="Bullish Broadening",
        bias="bullish",
        index=i,
        start_index=i - 4,
        trigger_level=top(columns[i - 2]) + 1,
        failure_level=_lowest(columns, i - 4, i) - 1,
        meta={},
    )


def detect_bearish_broadening(columns: list, i: int, cfg=DEFAULT_CONFIG) -> Optional[Pattern]:
    """Sell-Buy-Sell over five columns — a failed Bear Trap."""
    if i < 4:
        return None
    if not is_double_bottom_sell(columns, i):
        return None
    if detect_bear_trap(columns, i - 1, cfg) is None:
        return None
    return Pattern(
        name="bearish_broadening",
        label="Bearish Broadening",
        bias="bearish",
        index=i,
        start_index=i - 4,
        trigger_level=bottom(columns[i - 2]) - 1,
        failure_level=_highest(columns, i - 4, i) + 1,
        meta={},
    )


def detect_bullish_double_broadening(columns: list, i: int, cfg=DEFAULT_CONFIG) -> Optional[Pattern]:
    """Book 2.2: 'Bullish Double Broadening formation is a consecutive
    Sell-Buy-Sell-Buy pattern where Bearish Broadening pattern is
    immediately followed by Bullish Broadening pattern' — six columns,
    a signal in each of the last four. Quite rare."""
    if i < 5:
        return None
    if detect_bullish_broadening(columns, i, cfg) is None:
        return None
    if detect_bearish_broadening(columns, i - 1, cfg) is None:
        return None
    return Pattern(
        name="bullish_double_broadening",
        label="Bullish Double Broadening",
        bias="bullish",
        index=i,
        start_index=i - 5,
        trigger_level=top(columns[i - 2]) + 1,
        failure_level=_lowest(columns, i - 5, i) - 1,
        meta={},
    )


def detect_bearish_double_broadening(columns: list, i: int, cfg=DEFAULT_CONFIG) -> Optional[Pattern]:
    if i < 5:
        return None
    if detect_bearish_broadening(columns, i, cfg) is None:
        return None
    if detect_bullish_broadening(columns, i - 1, cfg) is None:
        return None
    return Pattern(
        name="bearish_double_broadening",
        label="Bearish Double Broadening",
        bias="bearish",
        index=i,
        start_index=i - 5,
        trigger_level=bottom(columns[i - 2]) - 1,
        failure_level=_highest(columns, i - 5, i) + 1,
        meta={},
    )


# ---------------------------------------------------------------------------
# 2.2 — Pattern Reversed
# ---------------------------------------------------------------------------


def detect_bearish_pattern_reversed(columns: list, i: int, cfg=DEFAULT_CONFIG) -> Optional[Pattern]:
    """BULLISH signal despite the name (book 2.2: 'Bearish pattern that
    reversed is a bullish pattern'). A Buy signal after two consecutive
    Sell signals — six columns, reversing in the sixth.

    'there shouldn't be a Buy signal before the sixth column, meaning that
    column of X in second and fourth column shouldn't have produced
    Double Top Buy' — equivalently, column i-2 must not be a Bull Trap
    trigger."""
    if i < 5:
        return None
    if not is_double_top_buy(columns, i):
        return None
    if not (is_double_bottom_sell(columns, i - 1) and is_double_bottom_sell(columns, i - 3)):
        return None
    if is_double_top_buy(columns, i - 2) or is_double_top_buy(columns, i - 4):
        return None
    return Pattern(
        name="bearish_pattern_reversed",
        label="Bearish Pattern Reversed",
        bias="bullish",
        index=i,
        start_index=i - 5,
        trigger_level=top(columns[i - 2]) + 1,
        failure_level=_lowest(columns, i - 5, i) - 1,
        meta={},
    )


def detect_bullish_pattern_reversed(columns: list, i: int, cfg=DEFAULT_CONFIG) -> Optional[Pattern]:
    """BEARISH signal: a Double Bottom Sell immediately after two
    consecutive Double Top Buys, with no Sell signal before the sixth
    column."""
    if i < 5:
        return None
    if not is_double_bottom_sell(columns, i):
        return None
    if not (is_double_top_buy(columns, i - 1) and is_double_top_buy(columns, i - 3)):
        return None
    if is_double_bottom_sell(columns, i - 2) or is_double_bottom_sell(columns, i - 4):
        return None
    return Pattern(
        name="bullish_pattern_reversed",
        label="Bullish Pattern Reversed",
        bias="bearish",
        index=i,
        start_index=i - 5,
        trigger_level=bottom(columns[i - 2]) - 1,
        failure_level=_highest(columns, i - 5, i) + 1,
        meta={},
    )


# ---------------------------------------------------------------------------
# 2.2 — Catapult
# ---------------------------------------------------------------------------


def detect_bullish_catapult(columns: list, i: int, cfg=DEFAULT_CONFIG) -> Optional[Pattern]:
    """Book 2.2 — a seven-column formation:
      * Triple Top Breakout in the fifth column,
      * column of O in the sixth that has NOT generated a Double Bottom Sell,
      * that O column sits below the high of the third column of X,
      * Double Top Buy in the seventh column.
    Fails below the lowest O of all seven columns."""
    if i < 6:
        return None
    if not is_double_top_buy(columns, i):
        return None
    if detect_triple_top_buy(columns, i - 2, cfg) is None:
        return None
    if is_double_bottom_sell(columns, i - 1):
        return None
    if bottom(columns[i - 1]) >= top(columns[i - 4]):
        return None
    return Pattern(
        name="bullish_catapult",
        label="Bullish Catapult",
        bias="bullish",
        index=i,
        start_index=i - 6,
        trigger_level=top(columns[i - 2]) + 1,
        failure_level=_lowest(columns, i - 6, i) - 1,
        meta={},
    )


def detect_bearish_catapult(columns: list, i: int, cfg=DEFAULT_CONFIG) -> Optional[Pattern]:
    if i < 6:
        return None
    if not is_double_bottom_sell(columns, i):
        return None
    if detect_triple_bottom_sell(columns, i - 2, cfg) is None:
        return None
    if is_double_top_buy(columns, i - 1):
        return None
    if top(columns[i - 1]) <= bottom(columns[i - 4]):
        return None
    return Pattern(
        name="bearish_catapult",
        label="Bearish Catapult",
        bias="bearish",
        index=i,
        start_index=i - 6,
        trigger_level=bottom(columns[i - 2]) - 1,
        failure_level=_highest(columns, i - 6, i) + 1,
        meta={},
    )


# ---------------------------------------------------------------------------
# 2.7 — Weak breakout, Ziddi, Super pattern, Diamond
# ---------------------------------------------------------------------------


def detect_weak_breakout(columns: list, i: int, cfg=DEFAULT_CONFIG) -> Optional[Pattern]:
    """Book 2.7: 'If there are only one or two boxes of X after a Double
    Top Buy signal and if the price flips to a column of O thereafter,
    such a pattern is defined as a Weak Bullish Breakout.'

    Reported at column i, the column that flips — that is when the
    weakness is confirmed. Named by the direction of the breakout it
    weakens, so a 'weak bullish breakout' is a cautionary/bearish-leaning
    observation, hence bias is the OPPOSITE of the breakout: the book
    calls it 'a potential trap formation'."""
    if i < 3:
        return None
    j = i - 1
    boxes = _pole_breakout_boxes(columns, j)
    if boxes is None or boxes > cfg.weak_breakout_max_boxes:
        return None
    if columns[i].direction == columns[j].direction:
        return None
    bullish_breakout = is_up(columns[j])
    return Pattern(
        name="weak_bullish_breakout" if bullish_breakout else "weak_bearish_breakout",
        label="Weak Bullish Breakout" if bullish_breakout else "Weak Bearish Breakout",
        bias="bearish" if bullish_breakout else "bullish",
        index=i,
        start_index=j - 2,
        trigger_level=None,
        failure_level=None,
        meta={"boxes_after_breakout": boxes, "breakout_index": j},
    )


def detect_ziddi(columns: list, i: int, cfg=DEFAULT_CONFIG) -> Optional[Pattern]:
    """Book 2.7: 'Consecutive weak breakouts followed by trap are called
    Ziddi formations.' Ziddi Bulls = two weak BEARISH breakouts (bulls
    refusing to let price fall) then a Bear Trap; Ziddi Bears is the
    mirror. 'For Ziddi bulls, there shouldn't be a Buy pattern in the
    earlier columns of the pattern.'"""
    trap = detect_bear_trap(columns, i, cfg) or detect_bull_trap(columns, i, cfg)
    if trap is None:
        return None
    bullish = trap.bias == "bullish"  # Bear Trap -> Ziddi Bulls
    weak = []
    for k in (i - 2, i - 4):
        w = detect_weak_breakout(columns, k, cfg)
        if w is None:
            return None
        # Ziddi Bulls needs the weak breakouts to be the bearish ones.
        want_bearish_breakout = bullish
        if want_bearish_breakout and w.name != "weak_bearish_breakout":
            return None
        if not want_bearish_breakout and w.name != "weak_bullish_breakout":
            return None
        weak.append(w)
    # No opposing basic signal earlier in the formation.
    for k in range(i - 5, i):
        if bullish and is_double_top_buy(columns, k):
            return None
        if not bullish and is_double_bottom_sell(columns, k):
            return None
    return Pattern(
        name="ziddi_bulls" if bullish else "ziddi_bears",
        label="Ziddi Bulls" if bullish else "Ziddi Bears",
        bias=trap.bias,
        index=i,
        start_index=i - 5,
        trigger_level=trap.trigger_level,
        failure_level=trap.failure_level,
        meta={"weak_breakouts": [w.index for w in weak], "base": trap.name},
    )


def detect_super_pattern(columns: list, i: int, cfg=DEFAULT_CONFIG) -> Optional[Pattern]:
    """Book 2.7 — the author's own setup, in four steps:
      1. basic Double Top Buy,
      2. price travels at least `super_min_boxes` boxes after that signal,
      3. the immediate column of O forms <= `super_max_pullback` boxes,
      4. Follow-through Buy that completes the pattern.
    Bearish Super pattern is the exact mirror. Low initial risk by
    construction — the stop sits just under a shallow pullback."""
    if i < 4:
        return None
    signal = is_basic_signal(columns, i)
    if signal is None:
        return None
    thrust, pull = columns[i - 2], columns[i - 1]
    boxes = _pole_breakout_boxes(columns, i - 2)
    if boxes is None or boxes < cfg.super_min_boxes:
        return None
    if pull.box_count > cfg.super_max_pullback:
        return None
    bullish = signal == "bullish"
    if bullish != is_up(thrust):
        return None
    return Pattern(
        name="bullish_super" if bullish else "bearish_super",
        label="Bullish Super Pattern" if bullish else "Bearish Super Pattern",
        bias=signal,
        index=i,
        start_index=i - 4,
        trigger_level=breakout_level(columns, i),
        failure_level=(bottom(pull) - 1) if bullish else (top(pull) + 1),
        meta={"thrust_boxes": boxes, "pullback_boxes": pull.box_count},
    )


def detect_diamond(columns: list, i: int, cfg=DEFAULT_CONFIG) -> Optional[Pattern]:
    """Book 2.7: 'it can be described as a P&F Broadening formation
    followed by P&F triangle'. Reported at the triangle-locking column,
    with the breakout then governed by the usual Triangle rules."""
    tri = detect_triangle(columns, i, cfg)
    if tri is None:
        return None
    for k in range(tri.start_index, max(tri.start_index - 4, 3), -1):
        broad = (detect_bullish_broadening(columns, k, cfg)
                 or detect_bearish_broadening(columns, k, cfg))
        if broad is not None:
            return Pattern(
                name="diamond",
                label="P&F Diamond",
                bias="neutral",
                index=i,
                start_index=broad.start_index,
                trigger_level=None,
                failure_level=None,
                meta={
                    "broadening_index": broad.index,
                    "triangle_index": tri.index,
                    "upper_level": tri.meta["upper_level"],
                    "lower_level": tri.meta["lower_level"],
                },
            )
    return None


# ---------------------------------------------------------------------------
# 2.6 — Turtle breakout (N-column breakout)
# ---------------------------------------------------------------------------


def detect_turtle_breakout(columns: list, i: int, cfg=DEFAULT_CONFIG) -> Optional[Pattern]:
    """Book 2.6: 'a bullish breakout may be defined as a column of X
    rising above the prior 10-columns of X. And a bearish breakout can be
    defined as column of O going below previous 10 columns of O.'

    Counts COLUMNS of the same direction, not raw column indices — a
    10-column breakout on P&F spans however many days it takes."""
    n = cfg.turtle_columns
    c = columns[i]
    same = [k for k in range(i) if columns[k].direction == c.direction]
    if len(same) < n:
        return None
    window = same[-n:]
    if is_up(c):
        ref = max(top(columns[k]) for k in window)
        if top(c) <= ref:
            return None
        trigger, fail = ref + 1, min(bottom(columns[k]) for k in window) - 1
    else:
        ref = min(bottom(columns[k]) for k in window)
        if bottom(c) >= ref:
            return None
        trigger, fail = ref - 1, max(top(columns[k]) for k in window) + 1
    return Pattern(
        name="turtle_breakout_bullish" if is_up(c) else "turtle_breakout_bearish",
        label=f"{n}-Column Turtle Breakout ({'Bullish' if is_up(c) else 'Bearish'})",
        bias="bullish" if is_up(c) else "bearish",
        index=i,
        start_index=window[0],
        trigger_level=trigger,
        failure_level=fail,
        meta={"columns": n, "reference_level": ref},
    )


def detect_anchor_column(columns: list, i: int, cfg=DEFAULT_CONFIG) -> Optional[Pattern]:
    """A long column. The book describes the concept ('large columns
    display strong trends') without fixing a threshold; the specific
    'Anchor Column' name and its box count come from Definedge's own
    platform, which is why the threshold is configurable rather than
    hard-coded to a book citation."""
    c = columns[i]
    if c.box_count <= cfg.anchor_min_boxes:
        return None
    return Pattern(
        name="anchor_column",
        label="Anchor Column",
        bias="bullish" if is_up(c) else "bearish",
        index=i,
        start_index=i,
        trigger_level=None,
        failure_level=None,
        meta={"boxes": c.box_count},
    )


# ---------------------------------------------------------------------------
# 2.7 — Basic-signal variants (what preceded the breakout)
# ---------------------------------------------------------------------------


def classify_basic_signal(columns: list, i: int) -> Optional[dict]:
    """Book 2.7 partitions every basic signal into exactly three cases by
    what the preceding opposite column did:

      Double Top Buy  -> Rising Double Top Buy (rising O before it)
                       / Double Top Buy after Support (O at same level)
                       / Bear Trap (O made a Sell signal)
      Double Bottom Sell -> Falling / after Resistance / Bull Trap

    Returns {'signal', 'variant', 'label'} or None."""
    signal = is_basic_signal(columns, i)
    if signal is None or i < 3:
        return None
    prev_opp, prev_opp2 = columns[i - 1], columns[i - 3]
    if signal == "bullish":
        if is_double_bottom_sell(columns, i - 1):
            variant, label = "bear_trap", "Bear Trap"
        elif bottom(prev_opp) == bottom(prev_opp2):
            variant, label = "after_support", "Double Top Buy after Support"
        elif bottom(prev_opp) > bottom(prev_opp2):
            variant, label = "rising", "Rising Double Top Buy"
        else:
            variant, label = "plain", "Double Top Buy"
    else:
        if is_double_top_buy(columns, i - 1):
            variant, label = "bull_trap", "Bull Trap"
        elif top(prev_opp) == top(prev_opp2):
            variant, label = "after_resistance", "Double Bottom Sell after Resistance"
        elif top(prev_opp) < top(prev_opp2):
            variant, label = "falling", "Falling Double Bottom Sell"
        else:
            variant, label = "plain", "Double Bottom Sell"
    return {"signal": signal, "variant": variant, "label": label}


# ---------------------------------------------------------------------------
# Registry + scanning
# ---------------------------------------------------------------------------

# Order matters only for readability of output; every detector that fires
# is reported, because the book is explicit that patterns genuinely
# overlap (a 100% Pole "is a High Pole, a Bull Trap and a Double Bottom
# Sell as well"). Never short-circuit on the first match.
DETECTORS: dict[str, Callable[..., Optional[Pattern]]] = {
    "triple_top_buy": detect_triple_top_buy,
    "triple_bottom_sell": detect_triple_bottom_sell,
    "quadruple_top_buy": detect_quadruple_top_buy,
    "quadruple_bottom_sell": detect_quadruple_bottom_sell,
    "spread_triple_top_buy": detect_spread_triple_top_buy,
    "spread_triple_bottom_sell": detect_spread_triple_bottom_sell,
    "bull_trap": detect_bull_trap,
    "bear_trap": detect_bear_trap,
    "small_box_trap": detect_five_box_trap,
    "high_pole": detect_high_pole,
    "low_pole": detect_low_pole,
    "bullish_100_pole": detect_bullish_100_pole,
    "bearish_100_pole": detect_bearish_100_pole,
    "triangle": detect_triangle,
    "triangle_breakout": detect_triangle_breakout,
    "bullish_broadening": detect_bullish_broadening,
    "bearish_broadening": detect_bearish_broadening,
    "bullish_double_broadening": detect_bullish_double_broadening,
    "bearish_double_broadening": detect_bearish_double_broadening,
    "bearish_pattern_reversed": detect_bearish_pattern_reversed,
    "bullish_pattern_reversed": detect_bullish_pattern_reversed,
    "bullish_catapult": detect_bullish_catapult,
    "bearish_catapult": detect_bearish_catapult,
    "weak_breakout": detect_weak_breakout,
    "ziddi": detect_ziddi,
    "super_pattern": detect_super_pattern,
    "diamond": detect_diamond,
    "turtle_breakout": detect_turtle_breakout,
    "anchor_column": detect_anchor_column,
}

# Formations the book calls "major" (2.1) — the ones worth trading a
# Follow-through to, and the default filter for a scanner.
MAJOR_PATTERNS = {
    "triple_top_buy", "triple_bottom_sell",
    "bull_trap", "bear_trap",
    "high_pole", "low_pole",
    "bullish_100_pole", "bearish_100_pole",
    "triangle_breakout_bullish", "triangle_breakout_bearish",
    "bullish_broadening", "bearish_broadening",
    "bullish_double_broadening", "bearish_double_broadening",
    "bearish_pattern_reversed", "bullish_pattern_reversed",
    "bullish_catapult", "bearish_catapult",
    "quadruple_top_buy", "quadruple_bottom_sell",
    "bullish_super", "bearish_super",
    "ziddi_bulls", "ziddi_bears",
}


def detect_at(columns: list, i: int, cfg=DEFAULT_CONFIG, only: Optional[set] = None) -> list:
    """Every pattern completing at column i."""
    out = []
    for key, fn in DETECTORS.items():
        if only is not None and key not in only:
            continue
        try:
            p = fn(columns, i, cfg)
        except (IndexError, ZeroDivisionError):
            continue
        if p is not None:
            out.append(p)
    return out


def scan(columns: list, cfg=DEFAULT_CONFIG, only: Optional[set] = None) -> list:
    """Every pattern across the whole chart, in column order."""
    out = []
    for i in range(len(columns)):
        out.extend(detect_at(columns, i, cfg, only))
    return out


def has_failed(columns: list, pattern: Pattern) -> Optional[int]:
    """Book 2.8: 'Failure or negation of a pattern is a significant piece
    of information.' Returns the column index at which `pattern`'s failure
    level was breached after completion, or None if it still stands.

    Bullish patterns fail on a print AT OR BELOW their failure level;
    bearish ones at or above (failure_level is already set one box beyond
    the protected extreme by each detector, so a plain <=/>= is correct)."""
    if pattern.failure_level is None or pattern.bias == "neutral":
        return None
    for k in range(pattern.index + 1, len(columns)):
        if pattern.bias == "bullish" and bottom(columns[k]) <= pattern.failure_level:
            return k
        if pattern.bias == "bearish" and top(columns[k]) >= pattern.failure_level:
            return k
    return None


def find_follow_through(columns: list, pattern: Pattern, cfg=DEFAULT_CONFIG) -> Optional[Pattern]:
    """Book 2.3 — 'the best P&F formation': a basic Double Top Buy /
    Double Bottom Sell in the same direction as an earlier major pattern,
    occurring while that pattern has NOT been negated.

    'it is not necessary that Follow-though must occur in the immediate
    column; it can happen in subsequent columns as well' — so this scans
    forward. 'a bullish Follow-through formation is valid only if price
    has not gone below the bottom of the initial bullish pattern' — hence
    the failure check inside the loop, before the signal check.

    Returns the follow-through as its own Pattern (whose failure level is
    inherited from the initial pattern, which is what a trader would
    actually stop out on), or None if the pattern failed first or no
    follow-through has appeared yet."""
    if pattern.bias == "neutral":
        return None
    for k in range(pattern.index + 1, len(columns)):
        if pattern.failure_level is not None:
            if pattern.bias == "bullish" and bottom(columns[k]) <= pattern.failure_level:
                return None
            if pattern.bias == "bearish" and top(columns[k]) >= pattern.failure_level:
                return None
        if is_basic_signal(columns, k) == pattern.bias:
            return Pattern(
                name=f"follow_through_{pattern.bias}",
                label=f"Follow-through to {pattern.label}",
                bias=pattern.bias,
                index=k,
                start_index=pattern.start_index,
                trigger_level=breakout_level(columns, k),
                failure_level=pattern.failure_level,
                meta={"initial_pattern": pattern.name, "initial_index": pattern.index},
            )
    return None


def find_pattern_retest(patterns: list, cfg=DEFAULT_CONFIG) -> list:
    """Book 2.5 — 'a pattern testing a previous pattern'. Two same-bias
    patterns whose trigger levels sit within `retest_zone_boxes` of each
    other, separated by at least `retest_min_gap_columns` columns, form a
    double pattern; a third in the same zone makes it a triple pattern.

    Book: 'it is very rare that price takes support or faces resistance
    for a fourth time at the same zone... avoid the pattern and look for
    breakout when a level is being tested for the fourth time' — so a
    fourth hit is reported with `avoid=True` rather than as another retest.

    Only MAJOR patterns count. The book's whole point is that "the major
    patterns that we have discussed are important reference point when
    revisited" — letting every minor variation qualify turns a rare,
    meaningful setup into noise (measured: it produced hundreds of
    "retests" on a single chart before this filter)."""
    tradable = [p for p in patterns
                if p.bias in ("bullish", "bearish")
                and p.trigger_level is not None
                and p.name in MAJOR_PATTERNS]
    # Several detectors legitimately fire on the same column (a 100% Pole
    # is also a Pole and a Trap). Collapse to one representative per
    # column so overlapping labels can't inflate the test count.
    seen, deduped = set(), []
    for p in tradable:
        key = (p.index, p.bias)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(p)
    tradable = deduped
    out = []
    for n, p in enumerate(tradable):
        zone = [q for q in tradable[:n]
                if q.bias == p.bias
                and abs(q.trigger_level - p.trigger_level) <= cfg.retest_zone_boxes
                and p.index - q.index >= cfg.retest_min_gap_columns]
        if not zone:
            continue
        count = len(zone) + 1
        if count == 2:
            label, name = "Double Pattern Retest", "double_pattern"
        elif count == 3:
            label, name = "Triple Pattern Retest", "triple_pattern"
        else:
            label, name = f"{count}th Test of Zone (avoid)", "over_tested_zone"
        out.append(Pattern(
            name=name,
            label=label,
            bias=p.bias,
            index=p.index,
            start_index=zone[0].index,
            trigger_level=p.trigger_level,
            failure_level=p.failure_level,
            meta={
                "count": count,
                "avoid": count >= 4,
                "members": [q.index for q in zone] + [p.index],
                "patterns": [q.name for q in zone] + [p.name],
            },
        ))
    return out
