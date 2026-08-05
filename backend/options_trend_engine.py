"""Options Trend Scanner — the pure "three-pillar" computation core.

Method: for one stock, read the CURRENT P&F column (bullish=X / bearish=O)
of three separate instruments — its FUTURE, its ATM CALL, and its ATM
PUT — each on its own chart, independently. A Bullish verdict requires all
three to agree in the bullish direction (future up, call up, PUT DOWN —
the put is expected to be losing value as the underlying rises); Bearish
is the mirror image. Anything else (including a leg that hasn't printed
enough columns to have a direction at all) falls through to Neutral —
same "never guess on an unresolved leg" discipline as
relative_strength_matrix.py/breadth_engine.py.

Deliberately pure — reuses pnf_engine.build_columns() directly on each
leg's own real price series (no ratio/anchor concerns — see
breadth_engine.py's docstring for why that distinction matters and
relative_strength_matrix.py's for what goes wrong when it's ignored).

Box parameters:
  - CALL/PUT legs: 3% box, 3-box reversal — reuses
    definedge_service.ATM_LEG_BOX_PCT/ATM_LEG_REVERSAL_BOXES, independently
    confirmed live against a real Definedge chart titled "(3% x 3)"
    (definedge_service.py's own docstring) for exactly this leg type.
  - FUTURE leg: 0.25% box, 3-box reversal. NOT independently verified the
    way the option-leg box size was — reuses the "short-term" box
    convention already established for relative_strength_matrix.py rather
    than guessing at a source video's ambiguously-transcribed "0.15%/15%"
    figure for this leg. Flagged here, not hidden, per this codebase's
    convention for best-effort parameters (see prism_alpha_blackbox.py's
    XO Zone note for the same honesty pattern).
"""
from __future__ import annotations

from pnf_engine import BoxSettings, build_columns

FUTURE_BOX_PCT = 0.25    # best-effort, see module docstring — not independently verified
FUTURE_REVERSAL = 3
OPTION_BOX_PCT = 3.0     # matches definedge_service.ATM_LEG_BOX_PCT, verified live
OPTION_REVERSAL = 3      # matches definedge_service.ATM_LEG_REVERSAL_BOXES


def leg_direction(closes: list, box_pct: float, reversal_boxes: int) -> str | None:
    """"bullish" | "bearish" | None (not enough real movement yet to print
    even one column at this box size) for one instrument's own price
    series."""
    vals = [c for c in closes if c is not None]
    if len(vals) < 2:
        return None
    settings = BoxSettings(reversal_boxes=reversal_boxes, box_pct=box_pct / 100.0)
    columns = build_columns(vals, settings)
    if not columns:
        return None
    return "bullish" if columns[-1].direction == "up" else "bearish"


def three_pillar_verdict(future_dir: str | None, call_dir: str | None, put_dir: str | None) -> str:
    """"Bullish" | "Bearish" | "Neutral" — see module docstring for the
    exact agreement rule. Any leg being unresolved (None) is Neutral, same
    as any disagreement — an unresolved leg is not evidence of anything."""
    if future_dir is None or call_dir is None or put_dir is None:
        return "Neutral"
    if future_dir == "bullish" and call_dir == "bullish" and put_dir == "bearish":
        return "Bullish"
    if future_dir == "bearish" and call_dir == "bearish" and put_dir == "bullish":
        return "Bearish"
    return "Neutral"


def compute_verdict(future_closes: list, call_closes: list, put_closes: list) -> dict:
    """One stock's full read — {"verdict", "future", "call", "put"} where
    the three leg fields are each "bullish"/"bearish"/None, so a caller can
    show WHY a verdict landed on Neutral rather than just the label."""
    future_dir = leg_direction(future_closes, FUTURE_BOX_PCT, FUTURE_REVERSAL)
    call_dir = leg_direction(call_closes, OPTION_BOX_PCT, OPTION_REVERSAL)
    put_dir = leg_direction(put_closes, OPTION_BOX_PCT, OPTION_REVERSAL)
    return {
        "verdict": three_pillar_verdict(future_dir, call_dir, put_dir),
        "future": future_dir,
        "call": call_dir,
        "put": put_dir,
    }
