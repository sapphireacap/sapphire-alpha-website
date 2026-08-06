"""Renko pattern library — every formation catalogued in "Renko Charts"
(Prashant Shah), implemented against the book-validated brick engine in
`renko_engine.py`.

TERMINOLOGY. The book calls a single printed box a "brick" and the run
of consecutive same-direction bricks between two reversals a "swing"
(my label for `renko_engine.Brick`/`Column` — the book itself mostly
just says "the price moved N bricks up/down" without a fixed noun, but
"swing" matches how it discusses breakouts, pullbacks and extensions,
and avoids colliding with "brick" = one box). Every detector below
therefore operates on the SWING list (one entry per same-direction run,
exactly what `renko_engine.build_bricks()` returns), the same geometry
`pnf_patterns.py` uses for P&F columns — reuse `top()`/`bottom()`/
`is_up()`/`is_down()` conventions accordingly. Patterns that care about
individual brick counts within a swing (One-Back, Two-Back, Weak
Breakout, Anchor Bricks) read `swing.box_count` directly rather than
needing the brick-level expansion (`renko_engine.expand_to_bricks`,
kept for the frontend's diagonal-brick renderer, not pattern logic).

SOURCES — chapters refer to the book, read and extracted in full this
session (chapters 1-9, `renko_ch*.txt` in this session's scratchpad):
  Ch.1  Construction, Brick Reversal Pattern
  Ch.2  Two-brick/reversal patterns: Double/Triple Top-Bottom,
        Higher-Low/Lower-High
  Ch.3  Continuation patterns: One-Back, Two-Back, Anchor Bricks,
        Multi-Brick Swing Breakout, Weak Breakout
  Ch.4  Swing/breakout patterns: Swing Breakout, Swing Extension,
        Multi-Swing Extension, Strike-Back, Swing Engulfing, Zigzag
  Ch.5  Pattern Failure — every pattern carries an invalidation level
        distinct from a trade's stop; a failed pattern is itself
        information about the other side.
  Ch.6  Extensions — every swing/breakout pattern projects a price
        target = the length of its originating swing, applied from the
        breakout point, with a minimum 2-brick swing before an
        extension is plotted at all. Also: Renko ABCD, 123 Pullback
        (Open/Negated/Achieved), Retracement Pullback Zone, M/W
        patterns, Principle of Polarity.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Optional

from renko_engine import BoxSettings

# ---------------------------------------------------------------------------
# Swing geometry helpers (mirrors pnf_patterns.py's column helpers)
# ---------------------------------------------------------------------------


def top(s) -> int:
    return max(s.start_level, s.end_level)


def bottom(s) -> int:
    return min(s.start_level, s.end_level)


def is_up(s) -> bool:
    return s.direction == "up"


def is_down(s) -> bool:
    return s.direction == "down"


def _px(s, level: int, cfg) -> float:
    if cfg.settings is None:
        return float(level)
    return cfg.settings.price_at(level, s.anchor)


@dataclass(frozen=True)
class PatternConfig:
    """Book-stated tunable parameters; defaults are the book's own."""

    # Ch.3: "one or two boxes" defines a One-Back/Two-Back pullback.
    one_back_max_boxes: int = 1
    two_back_max_boxes: int = 2
    # Ch.3: Anchor Bricks — an unusually long single swing. The book
    # illustrates the concept without fixing a universal box count (it
    # depends on typical swing length for the instrument/brick value in
    # use), so this mirrors pnf_patterns.py's own anchor_min_boxes
    # convention: configurable, not hard-coded to a specific citation.
    anchor_min_boxes: int = 8
    # Ch.3: Weak Breakout — a breakout swing of only 1-2 bricks before
    # reversing.
    weak_breakout_max_boxes: int = 2
    # Ch.6: extensions require the originating swing to be at least 2
    # bricks — "we will not plot an extension when the breakout or
    # retracement swing move is of less than two bricks."
    extension_min_boxes: int = 2
    # Ch.6: Retracement Pullback Zone — 25% to 66% of the prior swing.
    retracement_zone_min: float = 0.25
    retracement_zone_max: float = 0.66
    # Ch.4: Swing Engulfing — the counter-swing must fully engulf the
    # PRIOR same-direction swing's box range.
    settings: Optional[BoxSettings] = None


DEFAULT_CONFIG = PatternConfig()


@dataclass
class Pattern:
    """One detected formation. `index` is the swing at which the
    pattern completes; `start_index` is the first swing belonging to
    it. `trigger_level`/`failure_level` are box levels (Ch.5: every
    pattern carries an explicit invalidation level, distinct from a
    trade's stop loss)."""

    name: str
    label: str
    bias: str  # "bullish" | "bearish" | "neutral"
    index: int
    start_index: int
    trigger_level: Optional[int] = None
    failure_level: Optional[int] = None
    extension_target_level: Optional[int] = None
    meta: dict = field(default_factory=dict)

    def prices(self, settings: BoxSettings, anchor: float) -> dict:
        out = {}
        if self.trigger_level is not None:
            out["trigger_price"] = settings.price_at(self.trigger_level, anchor)
        if self.failure_level is not None:
            out["failure_price"] = settings.price_at(self.failure_level, anchor)
        if self.extension_target_level is not None:
            out["extension_target_price"] = settings.price_at(self.extension_target_level, anchor)
        return out


# ---------------------------------------------------------------------------
# Ch.1 — Brick Reversal (the raw direction flip; a building block, not
# reported as its own Pattern — every swing after the first IS one).
# ---------------------------------------------------------------------------


def is_brick_reversal(swings: list, i: int) -> bool:
    """Book Ch.1: 'the change of brick from bearish to bullish, or vice
    versa, is called a brick reversal pattern.' True for i>0 by
    construction (swings always alternate direction)."""
    return i > 0


# ---------------------------------------------------------------------------
# Ch.2 — Double/Triple Top-Bottom, Higher-Low/Lower-High
# ---------------------------------------------------------------------------


def is_swing_breakout_up(swings: list, i: int) -> bool:
    """Book Ch.2/Ch.4 basic breakout: swing i (up) prints above the high
    of the previous up-swing (i-2, since swings strictly alternate)."""
    if i < 2 or not is_up(swings[i]) or not is_up(swings[i - 2]):
        return False
    return top(swings[i]) > top(swings[i - 2])


def is_swing_breakout_down(swings: list, i: int) -> bool:
    if i < 2 or not is_down(swings[i]) or not is_down(swings[i - 2]):
        return False
    return bottom(swings[i]) < bottom(swings[i - 2])


def swing_breakout_bias(swings: list, i: int) -> Optional[str]:
    if is_swing_breakout_up(swings, i):
        return "bullish"
    if is_swing_breakout_down(swings, i):
        return "bearish"
    return None


def breakout_level(swings: list, i: int) -> Optional[int]:
    if is_swing_breakout_up(swings, i):
        return top(swings[i - 2]) + 1
    if is_swing_breakout_down(swings, i):
        return bottom(swings[i - 2]) - 1
    return None


def swing_extension_target(swings: list, i: int, cfg=DEFAULT_CONFIG) -> Optional[int]:
    """Ch.6 Extensions: the target = the length (in boxes) of the swing
    that INITIATED the breakout, projected from the breakout level.
    Book: no extension plotted when that originating swing is under
    `extension_min_boxes` (default 2)."""
    bias = swing_breakout_bias(swings, i)
    if bias is None:
        return None
    origin = swings[i - 2]
    length = origin.box_count
    if length < cfg.extension_min_boxes:
        return None
    lvl = breakout_level(swings, i)
    return lvl + length if bias == "bullish" else lvl - length


def detect_double_top(swings: list, i: int, cfg=DEFAULT_CONFIG) -> Optional[Pattern]:
    """Ch.2 Double Top: an up-swing breaking above the high of the prior
    up-swing. Fails below the low of the pattern's down-swing (i-1)."""
    if not is_swing_breakout_up(swings, i):
        return None
    return Pattern(
        name="double_top", label="Double Top", bias="bullish",
        index=i, start_index=i - 2,
        trigger_level=breakout_level(swings, i),
        failure_level=bottom(swings[i - 1]) - 1,
        extension_target_level=swing_extension_target(swings, i, cfg),
        meta={"resistance_level": top(swings[i - 2])},
    )


def detect_double_bottom(swings: list, i: int, cfg=DEFAULT_CONFIG) -> Optional[Pattern]:
    if not is_swing_breakout_down(swings, i):
        return None
    return Pattern(
        name="double_bottom", label="Double Bottom", bias="bearish",
        index=i, start_index=i - 2,
        trigger_level=breakout_level(swings, i),
        failure_level=top(swings[i - 1]) + 1,
        extension_target_level=swing_extension_target(swings, i, cfg),
        meta={"support_level": bottom(swings[i - 2])},
    )


def detect_triple_top(swings: list, i: int, cfg=DEFAULT_CONFIG) -> Optional[Pattern]:
    """Ch.2 Triple Top: two up-swings at the same high, then a third
    breaking above it — five swings, mirroring P&F's Triple Top Buy."""
    if i < 4:
        return None
    a, b, c = swings[i - 4], swings[i - 2], swings[i]
    if not (is_up(a) and is_up(b) and is_up(c)):
        return None
    if top(a) != top(b) or top(c) <= top(b):
        return None
    return Pattern(
        name="triple_top", label="Triple Top", bias="bullish",
        index=i, start_index=i - 4,
        trigger_level=top(b) + 1,
        failure_level=min(bottom(s) for s in swings[i - 4:i + 1]) - 1,
        extension_target_level=swing_extension_target(swings, i, cfg),
        meta={"resistance_level": top(b)},
    )


def detect_triple_bottom(swings: list, i: int, cfg=DEFAULT_CONFIG) -> Optional[Pattern]:
    if i < 4:
        return None
    a, b, c = swings[i - 4], swings[i - 2], swings[i]
    if not (is_down(a) and is_down(b) and is_down(c)):
        return None
    if bottom(a) != bottom(b) or bottom(c) >= bottom(b):
        return None
    return Pattern(
        name="triple_bottom", label="Triple Bottom", bias="bearish",
        index=i, start_index=i - 4,
        trigger_level=bottom(b) - 1,
        failure_level=max(top(s) for s in swings[i - 4:i + 1]) + 1,
        extension_target_level=swing_extension_target(swings, i, cfg),
        meta={"support_level": bottom(b)},
    )


def detect_higher_low(swings: list, i: int, cfg=DEFAULT_CONFIG) -> Optional[Pattern]:
    """Ch.2: a down-swing (pullback) whose low sits above the low of the
    prior down-swing — bullish market-structure confirmation, reported
    at the down-swing itself (not a breakout)."""
    if i < 2 or not is_down(swings[i]) or not is_down(swings[i - 2]):
        return None
    if bottom(swings[i]) <= bottom(swings[i - 2]):
        return None
    return Pattern(
        name="higher_low", label="Higher Low", bias="bullish",
        index=i, start_index=i - 2,
        trigger_level=None,
        failure_level=bottom(swings[i - 2]) - 1,
        meta={"prior_low": bottom(swings[i - 2]), "new_low": bottom(swings[i])},
    )


def detect_lower_high(swings: list, i: int, cfg=DEFAULT_CONFIG) -> Optional[Pattern]:
    if i < 2 or not is_up(swings[i]) or not is_up(swings[i - 2]):
        return None
    if top(swings[i]) >= top(swings[i - 2]):
        return None
    return Pattern(
        name="lower_high", label="Lower High", bias="bearish",
        index=i, start_index=i - 2,
        trigger_level=None,
        failure_level=top(swings[i - 2]) + 1,
        meta={"prior_high": top(swings[i - 2]), "new_high": top(swings[i])},
    )


# ---------------------------------------------------------------------------
# Ch.3 — Continuation patterns: One-Back, Two-Back, Anchor Bricks,
# Multi-Brick Swing Breakout, Weak Breakout
# ---------------------------------------------------------------------------


def detect_one_back(swings: list, i: int, cfg=DEFAULT_CONFIG) -> Optional[Pattern]:
    """Ch.3 One-Back: after a swing breakout (swing i-2), the very next
    counter-swing (i-1) pulls back only ONE brick before swing i resumes
    and clears the breakout swing's extreme — the shallowest, strongest
    continuation read."""
    bias = swing_breakout_bias(swings, i - 2)
    if bias is None or i < 3:
        return None
    pullback = swings[i - 1]
    if pullback.box_count > cfg.one_back_max_boxes:
        return None
    cont = swings[i]
    if bias == "bullish":
        if not is_up(cont) or top(cont) <= top(swings[i - 2]):
            return None
        fail = bottom(pullback) - 1
    else:
        if not is_down(cont) or bottom(cont) >= bottom(swings[i - 2]):
            return None
        fail = top(pullback) + 1
    return Pattern(
        name="one_back_bullish" if bias == "bullish" else "one_back_bearish",
        label="Bullish One-Back" if bias == "bullish" else "Bearish One-Back",
        bias=bias, index=i, start_index=i - 3,
        trigger_level=breakout_level(swings, i - 2),
        failure_level=fail,
        extension_target_level=swing_extension_target(swings, i - 2, cfg),
        meta={"pullback_boxes": pullback.box_count},
    )


def detect_two_back(swings: list, i: int, cfg=DEFAULT_CONFIG) -> Optional[Pattern]:
    """Ch.3 Two-Back: same as One-Back but the pullback is exactly two
    bricks (still shallow, slightly less aggressive continuation read)."""
    bias = swing_breakout_bias(swings, i - 2)
    if bias is None or i < 3:
        return None
    pullback = swings[i - 1]
    if pullback.box_count != cfg.two_back_max_boxes:
        return None
    cont = swings[i]
    if bias == "bullish":
        if not is_up(cont) or top(cont) <= top(swings[i - 2]):
            return None
        fail = bottom(pullback) - 1
    else:
        if not is_down(cont) or bottom(cont) >= bottom(swings[i - 2]):
            return None
        fail = top(pullback) + 1
    return Pattern(
        name="two_back_bullish" if bias == "bullish" else "two_back_bearish",
        label="Bullish Two-Back" if bias == "bullish" else "Bearish Two-Back",
        bias=bias, index=i, start_index=i - 3,
        trigger_level=breakout_level(swings, i - 2),
        failure_level=fail,
        extension_target_level=swing_extension_target(swings, i - 2, cfg),
        meta={"pullback_boxes": pullback.box_count},
    )


def detect_weak_breakout(swings: list, i: int, cfg=DEFAULT_CONFIG) -> Optional[Pattern]:
    """Ch.3 Weak Breakout: a breakout swing (i-1) of only 1-2 bricks
    before the very next swing (i) reverses — a caution/trap-leaning
    signal, so bias is the OPPOSITE of the breakout direction (mirrors
    pnf_patterns.detect_weak_breakout)."""
    if i < 3:
        return None
    bias = swing_breakout_bias(swings, i - 1)
    if bias is None:
        return None
    breakout_swing = swings[i - 1]
    if breakout_swing.box_count > cfg.weak_breakout_max_boxes:
        return None
    if swings[i].direction == breakout_swing.direction:
        return None
    weakened_bullish = bias == "bullish"
    return Pattern(
        name="weak_bullish_breakout" if weakened_bullish else "weak_bearish_breakout",
        label="Weak Bullish Breakout" if weakened_bullish else "Weak Bearish Breakout",
        bias="bearish" if weakened_bullish else "bullish",
        index=i, start_index=i - 3,
        trigger_level=None, failure_level=None,
        meta={"breakout_boxes": breakout_swing.box_count, "breakout_index": i - 1},
    )


def detect_anchor_bricks(swings: list, i: int, cfg=DEFAULT_CONFIG) -> Optional[Pattern]:
    """Ch.3 Anchor Bricks: an unusually long single swing, signalling a
    strong, well-established trend leg."""
    s = swings[i]
    if s.box_count <= cfg.anchor_min_boxes:
        return None
    return Pattern(
        name="anchor_bricks", label="Anchor Bricks",
        bias="bullish" if is_up(s) else "bearish",
        index=i, start_index=i,
        trigger_level=None, failure_level=None,
        meta={"boxes": s.box_count},
    )


def detect_multi_brick_breakout(swings: list, i: int, cfg=DEFAULT_CONFIG) -> Optional[Pattern]:
    """Ch.3 Multi-Brick Swing Breakout: the breakout swing itself
    travels multiple bricks PAST the trigger level (not just one) —
    reported once the swing that broke out is complete (superseded by
    the next swing beginning), so its final length is known."""
    if i < 1:
        return None
    prior = swings[i - 1]
    bias = swing_breakout_bias(swings, i - 1)
    if bias is None:
        return None
    trig = breakout_level(swings, i - 1)
    boxes_past_trigger = (top(prior) - trig + 1) if bias == "bullish" else (trig - bottom(prior) + 1)
    if boxes_past_trigger < 2:
        return None
    return Pattern(
        name="multi_brick_breakout_bullish" if bias == "bullish" else "multi_brick_breakout_bearish",
        label="Multi-Brick Swing Breakout",
        bias=bias, index=i - 1, start_index=i - 3 if i >= 3 else 0,
        trigger_level=trig, failure_level=bottom(prior) - 1 if bias == "bullish" else top(prior) + 1,
        extension_target_level=swing_extension_target(swings, i - 1, cfg),
        meta={"boxes_past_trigger": boxes_past_trigger},
    )


# ---------------------------------------------------------------------------
# Ch.4 — Swing Breakout family: Strike-Back, Swing Engulfing, Zigzag
# ---------------------------------------------------------------------------


def detect_strike_back(swings: list, i: int, cfg=DEFAULT_CONFIG) -> Optional[Pattern]:
    """Ch.4 Strike-Back: after a swing breakout (i-2) the counter-swing
    (i-1) is a DEEP pullback (more than a One-Back/Two-Back, i.e. more
    than `two_back_max_boxes`) that fails to invalidate the pattern, and
    swing i then 'strikes back' past the original breakout's extreme —
    a resumption after a real test, stronger confirmation than a shallow
    One-Back/Two-Back precisely because the pullback was deeper and
    still held."""
    bias = swing_breakout_bias(swings, i - 2)
    if bias is None or i < 3:
        return None
    pullback = swings[i - 1]
    if pullback.box_count <= cfg.two_back_max_boxes:
        return None  # that shallow a pullback is a One-Back/Two-Back, not a Strike-Back
    cont = swings[i]
    if bias == "bullish":
        if not is_up(cont) or top(cont) <= top(swings[i - 2]):
            return None
        if bottom(pullback) <= bottom(swings[i - 2]):
            return None  # would have invalidated the original pattern entirely
        fail = bottom(pullback) - 1
    else:
        if not is_down(cont) or bottom(cont) >= bottom(swings[i - 2]):
            return None
        if top(pullback) >= top(swings[i - 2]):
            return None
        fail = top(pullback) + 1
    return Pattern(
        name="strike_back_bullish" if bias == "bullish" else "strike_back_bearish",
        label="Bullish Strike-Back" if bias == "bullish" else "Bearish Strike-Back",
        bias=bias, index=i, start_index=i - 3,
        trigger_level=breakout_level(swings, i - 2), failure_level=fail,
        extension_target_level=swing_extension_target(swings, i - 2, cfg),
        meta={"pullback_boxes": pullback.box_count},
    )


def find_strike_back_follow_through(swings: list, pattern: Pattern, cfg=DEFAULT_CONFIG) -> Optional[Pattern]:
    """Ch.4: a Strike-Back's own follow-through — the next swing in the
    same direction after it, confirming the resumption held."""
    if pattern.name not in ("strike_back_bullish", "strike_back_bearish"):
        return None
    for k in range(pattern.index + 1, len(swings)):
        if swings[k].direction == swings[pattern.index].direction:
            return Pattern(
                name=f"strike_back_follow_through_{pattern.bias}",
                label=f"Follow-through to {pattern.label}",
                bias=pattern.bias, index=k, start_index=pattern.start_index,
                trigger_level=pattern.trigger_level, failure_level=pattern.failure_level,
                meta={"strike_back_index": pattern.index},
            )
    return None


def detect_swing_engulfing(swings: list, i: int, cfg=DEFAULT_CONFIG) -> Optional[Pattern]:
    """Ch.4 Swing Engulfing: a swing whose range fully engulfs the box
    range of the prior swing of the SAME direction (i-2) — i.e. it
    both exceeds that swing's extreme AND retraces past its own start,
    covering more ground than a plain breakout. Read as a reversal-
    strength signal in the direction of swing i."""
    if i < 2 or swings[i].direction != swings[i - 2].direction:
        return None
    cur, prior = swings[i], swings[i - 2]
    if is_up(cur):
        engulfs = top(cur) > top(prior) and bottom(cur) < bottom(swings[i - 1])
    else:
        engulfs = bottom(cur) < bottom(prior) and top(cur) > top(swings[i - 1])
    if not engulfs:
        return None
    bias = "bullish" if is_up(cur) else "bearish"
    return Pattern(
        name="swing_engulfing_bullish" if bias == "bullish" else "swing_engulfing_bearish",
        label="Bullish Swing Engulfing" if bias == "bullish" else "Bearish Swing Engulfing",
        bias=bias, index=i, start_index=i - 2,
        trigger_level=top(prior) + 1 if bias == "bullish" else bottom(prior) - 1,
        failure_level=bottom(cur) - 1 if bias == "bullish" else top(cur) + 1,
        extension_target_level=(top(cur) + cur.box_count) if bias == "bullish" and cur.box_count >= cfg.extension_min_boxes
        else (bottom(cur) - cur.box_count) if bias == "bearish" and cur.box_count >= cfg.extension_min_boxes
        else None,
        meta={"engulfed_index": i - 2},
    )


def detect_zigzag(swings: list, i: int, cfg=DEFAULT_CONFIG) -> Optional[Pattern]:
    """Ch.4 Zigzag: three or more consecutive swings making progressively
    higher highs AND higher lows (bullish zigzag) or lower highs and
    lower lows (bearish zigzag) — a clean staircase trend structure,
    reported at the swing that completes the third confirming step."""
    if i < 4:
        return None
    a, b, c = swings[i - 4], swings[i - 2], swings[i]
    if is_up(a) and is_up(b) and is_up(c):
        if not (top(b) > top(a) and top(c) > top(b)):
            return None
        return Pattern(
            name="zigzag_bullish", label="Bullish Zigzag", bias="bullish",
            index=i, start_index=i - 4,
            trigger_level=top(b) + 1, failure_level=bottom(swings[i - 1]) - 1,
            meta={"legs": [top(a), top(b), top(c)]},
        )
    if is_down(a) and is_down(b) and is_down(c):
        if not (bottom(b) < bottom(a) and bottom(c) < bottom(b)):
            return None
        return Pattern(
            name="zigzag_bearish", label="Bearish Zigzag", bias="bearish",
            index=i, start_index=i - 4,
            trigger_level=bottom(b) - 1, failure_level=top(swings[i - 1]) + 1,
            meta={"legs": [bottom(a), bottom(b), bottom(c)]},
        )
    return None


# ---------------------------------------------------------------------------
# Ch.6 — ABCD, 123 Pullback, M/W, Retracement Pullback Zone, Polarity
# ---------------------------------------------------------------------------


def retracement_ratio(swing_range_hi: int, swing_range_lo: int, retrace_to: int) -> float:
    span = swing_range_hi - swing_range_lo
    if span <= 0:
        return 0.0
    return (swing_range_hi - retrace_to) / span


def in_retracement_zone(ratio: float, cfg=DEFAULT_CONFIG) -> bool:
    """Ch.6 Retracement Pullback Zone: a pullback retracing between 25%
    and 66% of the prior swing is considered a healthy, tradable zone."""
    return cfg.retracement_zone_min <= ratio <= cfg.retracement_zone_max


def detect_123_pullback(swings: list, i: int, cfg=DEFAULT_CONFIG) -> Optional[Pattern]:
    """Ch.6 123 Pullback: point 1 = an established swing extreme
    (swings[i-2]), point 2 = the retracement swing back toward it
    (swings[i-1], within the Retracement Pullback Zone of swing i-2's
    range), point 3 = swing i resuming and testing/clearing point 1.

    State model per the book: Open (point 3 forming, hasn't yet cleared
    point 1), Achieved (point 3 clears point 1 — trend resumes),
    Negated (point 2 instead breaks fully through point 1's origin,
    invalidating the setup). Reported once point 3 exists; `meta.state`
    carries which of the three applies."""
    if i < 2:
        return None
    p1, p2, p3 = swings[i - 2], swings[i - 1], swings[i]
    if p1.direction != p3.direction or p1.direction == p2.direction:
        return None
    bias = "bullish" if is_up(p1) else "bearish"
    rng_hi, rng_lo = top(p1), bottom(p1)
    if bias == "bullish":
        retrace_to = bottom(p2)
        ratio = retracement_ratio(rng_hi, rng_lo, retrace_to)
        if not in_retracement_zone(ratio, cfg):
            return None
        if retrace_to <= rng_lo:
            state = "negated"
        elif top(p3) > rng_hi:
            state = "achieved"
        else:
            state = "open"
        fail = bottom(p2) - 1
    else:
        retrace_to = top(p2)
        ratio = retracement_ratio(rng_hi, rng_lo, rng_hi - (retrace_to - rng_lo))
        # mirrored ratio for a bearish leg measured off the same span
        span = rng_hi - rng_lo
        ratio = (retrace_to - rng_lo) / span if span > 0 else 0.0
        if not in_retracement_zone(ratio, cfg):
            return None
        if retrace_to >= rng_hi:
            state = "negated"
        elif bottom(p3) < rng_lo:
            state = "achieved"
        else:
            state = "open"
        fail = top(p2) + 1
    return Pattern(
        name="pullback_123_bullish" if bias == "bullish" else "pullback_123_bearish",
        label="Bullish 123 Pullback" if bias == "bullish" else "Bearish 123 Pullback",
        bias=bias if state != "negated" else ("bearish" if bias == "bullish" else "bullish"),
        index=i, start_index=i - 2,
        trigger_level=rng_hi + 1 if bias == "bullish" else rng_lo - 1,
        failure_level=fail,
        extension_target_level=swing_extension_target(swings, i, cfg) if state == "achieved" else None,
        meta={"state": state, "retrace_ratio": round(ratio, 3), "point1": i - 2, "point2": i - 1, "point3": i},
    )


def detect_abcd(swings: list, i: int, cfg=DEFAULT_CONFIG) -> Optional[Pattern]:
    """Ch.6 Renko ABCD: a four-swing measured move — leg A-B, retracement
    B-C (within the Retracement Pullback Zone of A-B), then leg C-D
    projected to the same length as A-B from point C. Reported once D
    (swing i) is underway; `extension_target_level` carries the
    projected D level."""
    if i < 3:
        return None
    a, b, c, d = swings[i - 3], swings[i - 2], swings[i - 1], swings[i]
    if a.direction != c.direction or a.direction == b.direction or c.direction != d.direction:
        return None
    bias = "bullish" if is_up(a) else "bearish"
    ab_len = a.box_count
    if ab_len < cfg.extension_min_boxes:
        return None
    if bias == "bullish":
        ratio = retracement_ratio(top(a), bottom(a), bottom(b))
        if not in_retracement_zone(ratio, cfg):
            return None
        target = bottom(c) + ab_len
        fail = bottom(b) - 1
    else:
        span = top(a) - bottom(a)
        ratio = (top(b) - bottom(a)) / span if span > 0 else 0.0
        if not in_retracement_zone(ratio, cfg):
            return None
        target = top(c) - ab_len
        fail = top(b) + 1
    return Pattern(
        name="abcd_bullish" if bias == "bullish" else "abcd_bearish",
        label="Bullish Renko ABCD" if bias == "bullish" else "Bearish Renko ABCD",
        bias=bias, index=i, start_index=i - 3,
        trigger_level=None, failure_level=fail, extension_target_level=target,
        meta={"leg_ab_boxes": ab_len, "retrace_ratio": round(ratio, 3)},
    )


def detect_m_w_pattern(swings: list, i: int, cfg=DEFAULT_CONFIG) -> Optional[Pattern]:
    """Ch.6 M/W Pattern: two swing highs at (near) the same level with a
    pullback between them, then a break BELOW the pullback low = M
    (bearish); mirrored as W (bullish) for two swing lows. A classic
    double-top/double-bottom read at the STRUCTURE level rather than the
    simple Double Top/Bottom breakout (this one confirms on the
    breakdown of the pattern's neckline, the opposite side)."""
    if i < 4:
        return None
    a, b, c = swings[i - 4], swings[i - 2], swings[i]
    if is_up(a) and is_up(b) and is_down(c):
        if abs(top(a) - top(b)) > 1:
            return None
        neckline = bottom(swings[i - 3])
        if bottom(c) >= neckline:
            return None
        return Pattern(
            name="m_pattern", label="M Pattern", bias="bearish",
            index=i, start_index=i - 4,
            trigger_level=neckline - 1, failure_level=max(top(a), top(b)) + 1,
            extension_target_level=neckline - (top(a) - neckline),
            meta={"peak_level": top(a)},
        )
    if is_down(a) and is_down(b) and is_up(c):
        if abs(bottom(a) - bottom(b)) > 1:
            return None
        neckline = top(swings[i - 3])
        if top(c) <= neckline:
            return None
        return Pattern(
            name="w_pattern", label="W Pattern", bias="bullish",
            index=i, start_index=i - 4,
            trigger_level=neckline + 1, failure_level=min(bottom(a), bottom(b)) - 1,
            extension_target_level=neckline + (neckline - bottom(a)),
            meta={"trough_level": bottom(a)},
        )
    return None


def polarity_level(swings: list, pattern: Pattern) -> Optional[dict]:
    """Ch.6 Principle of Polarity: a broken resistance level becomes
    support (and vice versa). Given a completed breakout Pattern, report
    its trigger level re-framed as the opposite role for any LATER
    price action to be checked against — a filter/confirmation helper,
    not a standalone detector."""
    if pattern.trigger_level is None:
        return None
    return {
        "level": pattern.trigger_level,
        "acts_as": "support" if pattern.bias == "bullish" else "resistance",
        "since_index": pattern.index,
    }


# ---------------------------------------------------------------------------
# Registry + scanning (mirrors pnf_patterns.py's scan()/has_failed()/
# find_follow_through() shape)
# ---------------------------------------------------------------------------

DETECTORS: dict[str, Callable[..., Optional[Pattern]]] = {
    "double_top": detect_double_top,
    "double_bottom": detect_double_bottom,
    "triple_top": detect_triple_top,
    "triple_bottom": detect_triple_bottom,
    "higher_low": detect_higher_low,
    "lower_high": detect_lower_high,
    "one_back": detect_one_back,
    "two_back": detect_two_back,
    "weak_breakout": detect_weak_breakout,
    "anchor_bricks": detect_anchor_bricks,
    "multi_brick_breakout": detect_multi_brick_breakout,
    "strike_back": detect_strike_back,
    "swing_engulfing": detect_swing_engulfing,
    "zigzag": detect_zigzag,
    "pullback_123": detect_123_pullback,
    "abcd": detect_abcd,
    "m_w_pattern": detect_m_w_pattern,
}

MAJOR_PATTERNS = {
    "double_top", "double_bottom", "triple_top", "triple_bottom",
    "one_back_bullish", "one_back_bearish", "two_back_bullish", "two_back_bearish",
    "strike_back_bullish", "strike_back_bearish",
    "swing_engulfing_bullish", "swing_engulfing_bearish",
    "zigzag_bullish", "zigzag_bearish",
    "pullback_123_bullish", "pullback_123_bearish",
    "abcd_bullish", "abcd_bearish",
    "m_pattern", "w_pattern",
    "multi_brick_breakout_bullish", "multi_brick_breakout_bearish",
}


def detect_at(swings: list, i: int, cfg=DEFAULT_CONFIG, only: Optional[set] = None) -> list:
    out = []
    for key, fn in DETECTORS.items():
        if only is not None and key not in only:
            continue
        try:
            p = fn(swings, i, cfg)
        except (IndexError, ZeroDivisionError):
            continue
        if p is not None:
            out.append(p)
    return out


def scan(swings: list, cfg=DEFAULT_CONFIG, only: Optional[set] = None) -> list:
    out = []
    for i in range(len(swings)):
        out.extend(detect_at(swings, i, cfg, only))
    return out


def has_failed(swings: list, pattern: Pattern) -> Optional[int]:
    """Ch.5 Pattern Failure: returns the swing index at which the
    pattern's failure level was breached after completion, or None if
    it still stands."""
    if pattern.failure_level is None or pattern.bias == "neutral":
        return None
    for k in range(pattern.index + 1, len(swings)):
        if pattern.bias == "bullish" and bottom(swings[k]) <= pattern.failure_level:
            return k
        if pattern.bias == "bearish" and top(swings[k]) >= pattern.failure_level:
            return k
    return None


def find_follow_through(swings: list, pattern: Pattern, cfg=DEFAULT_CONFIG) -> Optional[Pattern]:
    """A basic swing breakout in the same direction as an earlier major
    pattern, occurring while that pattern has not been negated — the
    Renko equivalent of P&F's Follow-through concept, ported directly
    since the book (Ch.5) treats failure/follow-through the same way."""
    if pattern.bias == "neutral":
        return None
    for k in range(pattern.index + 1, len(swings)):
        if pattern.failure_level is not None:
            if pattern.bias == "bullish" and bottom(swings[k]) <= pattern.failure_level:
                return None
            if pattern.bias == "bearish" and top(swings[k]) >= pattern.failure_level:
                return None
        if swing_breakout_bias(swings, k) == pattern.bias:
            return Pattern(
                name=f"follow_through_{pattern.bias}",
                label=f"Follow-through to {pattern.label}",
                bias=pattern.bias, index=k, start_index=pattern.start_index,
                trigger_level=breakout_level(swings, k), failure_level=pattern.failure_level,
                meta={"initial_pattern": pattern.name, "initial_index": pattern.index},
            )
    return None
