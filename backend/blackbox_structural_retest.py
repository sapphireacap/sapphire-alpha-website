"""
Black Box strategy "Structural Retest" -- pure signal logic. Public name
for what the sourcing deck (DECNOCH 2023, Abhishek Datta) called "P&F
Pattern Retest & Breadth"; per this codebase's naming convention (see
proprietary_naming.md / Convexity Window / Gamma Backspread), the public
name never carries the presenter's or vendor's attribution, and internal
identifiers stay generic ("structural_retest", not "datta_retest").

Method, in the deck's own terms: a P&F reversal pattern (Triple Top/Bottom
Buy/Sell, or a Pole) that gets RE-TESTED by a later pattern of the same
bias at the same level is a stronger signal than either pattern alone --
the level has now been defended twice. Entries are gated by a group
breadth reading (bullish retests only traded when the group is oversold,
bearish only when overbought) so the strategy isn't fighting the group's
own prevailing extreme.

Deliberately thin: pnf_patterns.py already implements the entire pattern-
retest mechanism (find_pattern_retest, book section 2.5) exactly as
Datta's deck described it -- same "double/triple test, 4th test = avoid"
rule, same MAJOR_PATTERNS restriction. This module does NOT reimplement
that; it only adds the breadth gate and the entry/exit/stop mapping
Datta's deck specified on top of it. Nothing here is book-validated (the
retest mechanism it calls IS; the breadth-gate/entry-table wrapper is
sourced from the conference deck, not the book -- flagged per this
codebase's provenance discipline, same as pnf_patterns.detect_anchor_column's
own "Definedge platform, not the book" note).
"""
from __future__ import annotations

from dataclasses import dataclass

from pnf_engine import BoxSettings, build_columns
from pnf_patterns import (
    DEFAULT_CONFIG as PATTERN_DEFAULTS, scan, find_pattern_retest, has_failed,
    is_double_top_buy, is_double_bottom_sell,
)


@dataclass
class StructuralRetestConfig:
    box_pct: float = 1.0          # Datta's deck default box size for the pattern chart
    reversal_boxes: int = 3       # standard P&F convention (pnf_engine/pnf_patterns default)
    breadth_bullish_max: float = 25.0   # only trade bullish retests when group breadth <= this (%)
    breadth_bearish_min: float = 75.0   # only trade bearish retests when group breadth >= this (%)


DEFAULT_CONFIG = StructuralRetestConfig()


def _box_settings(cfg: StructuralRetestConfig) -> BoxSettings:
    return BoxSettings(reversal_boxes=cfg.reversal_boxes, box_pct=cfg.box_pct / 100.0)


def check_entry(closes: list, breadth_pct: float | None, cfg: StructuralRetestConfig = DEFAULT_CONFIG) -> dict | None:
    """`closes`: oldest -> newest daily closes for one symbol. `breadth_pct`:
    the group's current % of members on a bullish P&F column (see
    blackbox_equity_market.compute_group_breadth) -- None disables the gate
    (treated as "no reading available", not as neutral 50%, so an entry
    can't accidentally slip through on missing data).

    Returns an entry dict only if a retest pattern completed at the chart's
    LAST column (i.e. today's bar is the one that made it a retest) and the
    breadth gate for that bias is satisfied. A retest sitting a few columns
    back (already known before today) does not re-fire -- callers should
    only ever see a fresh completion once, the same day it completes."""
    if breadth_pct is None:
        return None
    settings = _box_settings(cfg)
    columns = build_columns(closes, settings)
    if len(columns) < 4:
        return None

    patterns = scan(columns, PATTERN_DEFAULTS)
    retests = find_pattern_retest(patterns, PATTERN_DEFAULTS)
    if not retests:
        return None
    last = retests[-1]
    if last.index != len(columns) - 1:
        return None  # this retest completed on an earlier column, not today
    if last.meta.get("avoid"):
        return None  # book: 4th+ test of the same zone -- avoid, don't trade it

    if last.bias == "bullish" and breadth_pct > cfg.breadth_bullish_max:
        return None
    if last.bias == "bearish" and breadth_pct < cfg.breadth_bearish_min:
        return None

    anchor = columns[0].anchor
    prices = last.prices(settings, anchor)
    return {
        "bias": last.bias,
        "pattern": last.name,
        "label": last.label,
        "retest_count": last.meta["count"],
        "entry_price": closes[-1],
        "stop_price": prices.get("failure_price"),
        "breadth_pct": breadth_pct,
    }


def check_exit(closes: list, position_bias: str, cfg: StructuralRetestConfig = DEFAULT_CONFIG) -> dict | None:
    """Datta's own stop/exit table: a bullish position exits on a Double
    Bottom Sell or a High Pole (the bearish counterparts of what would
    confirm it); a bearish position exits on a Double Top Buy or a Low
    Pole. Also exits if the ORIGINAL entry pattern's own failure level is
    breached (has_failed) -- whichever comes first."""
    settings = _box_settings(cfg)
    columns = build_columns(closes, settings)
    if len(columns) < 2:
        return None
    last_i = len(columns) - 1

    # Poles are full DETECTORS entries; Double Top/Bottom are the book's
    # "basic signal" primitives (is_double_top_buy/is_double_bottom_sell),
    # not wrapped into named Pattern objects elsewhere in pnf_patterns.py,
    # so they're checked directly rather than via scan().
    pole_wanted = {"bullish": "high_pole", "bearish": "low_pole"}.get(position_bias)
    if pole_wanted:
        for p in scan(columns, PATTERN_DEFAULTS, only={pole_wanted}):
            if p.index == last_i:
                return {"reason": f"exit_signal:{p.name}", "exit_price": closes[-1]}

    if position_bias == "bullish" and is_double_bottom_sell(columns, last_i):
        return {"reason": "exit_signal:double_bottom_sell", "exit_price": closes[-1]}
    if position_bias == "bearish" and is_double_top_buy(columns, last_i):
        return {"reason": "exit_signal:double_top_buy", "exit_price": closes[-1]}

    return None
