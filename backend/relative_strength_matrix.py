"""Pairwise relative-strength matrix — the pure computation core.

Method (from the same Prashant Shah P&F book pnf_engine.py/pnf_patterns.py
already implement): for every pair of instruments in a group, build a P&F
chart of their price RATIO (numerator / denominator), close-only, 3-box
reversal, at a given box size. A rising ratio (the ratio chart's current
column is X) means the numerator is outperforming; a falling ratio
(current column O) means the denominator is outperforming. Each
instrument's score is how many of its pairwise comparisons currently
favor it — a higher score means it's outperforming more of its peers
right now, not just a single benchmark.

Deliberately pure — no I/O, same discipline as pnf_chart.build_chart().
Callers hand in already-aligned (same trading dates, same length) close
price lists; alignment is the I/O layer's job (see relative_strength_routes.py).
"""
from __future__ import annotations

from pnf_engine import BoxSettings, build_columns

DEFAULT_REVERSAL = 3  # same fixed platform convention as pnf_chart.py


def pair_bias(closes_num: list, closes_den: list, box_pct: float) -> str | None:
    """Bullish for the numerator, bearish for the denominator, or None if
    there isn't enough ratio movement to plot even one column at this box
    size (never guessed — an unresolved pair is left out of both
    instruments' scores rather than counted as a coin flip)."""
    if len(closes_num) != len(closes_den) or len(closes_num) < 2:
        return None
    ratio = [n / d for n, d in zip(closes_num, closes_den) if d]
    if len(ratio) < 2:
        return None
    settings = BoxSettings(reversal_boxes=DEFAULT_REVERSAL, box_pct=box_pct / 100.0)
    columns = build_columns(ratio, settings)
    if not columns:
        return None
    return "bullish" if columns[-1].direction == "up" else "bearish"


def compute_matrix(symbols: list, closes_by_symbol: dict, box_pct: float) -> dict:
    """Full NxN grid + per-symbol total score for one box size.

    Only computes the upper triangle (C(N,2) ratio charts, not N*(N-1)) —
    a rising A/B ratio is mathematically the same movement as a falling
    B/A ratio (1/x is strictly monotonic-decreasing for x>0), so the
    lower triangle is the exact mirror image, not a second computation.
    """
    grid = {s: {} for s in symbols}
    scores = {s: 0 for s in symbols}
    unresolved = {s: 0 for s in symbols}

    for i, a in enumerate(symbols):
        for b in symbols[i + 1:]:
            bias = pair_bias(closes_by_symbol[a], closes_by_symbol[b], box_pct)
            if bias is None:
                grid[a][b] = None
                grid[b][a] = None
                unresolved[a] += 1
                unresolved[b] += 1
                continue
            grid[a][b] = bias
            grid[b][a] = "bearish" if bias == "bullish" else "bullish"
            if bias == "bullish":
                scores[a] += 1
            else:
                scores[b] += 1

    return {"grid": grid, "scores": scores, "unresolved": unresolved}


def compute_ranking(symbols: list, closes_by_symbol: dict, box_pcts: list) -> dict:
    """Runs compute_matrix once per box size and combines them into the
    book's own "multi-timeframe" ranking table — each box size is its own
    independent matrix (not a rolling average), summed into a Total and
    sorted by it, descending."""
    matrices = {}
    for box_pct in box_pcts:
        matrices[box_pct] = compute_matrix(symbols, closes_by_symbol, box_pct)

    ranking = []
    for s in symbols:
        per_box = {box_pct: matrices[box_pct]["scores"][s] for box_pct in box_pcts}
        ranking.append({"symbol": s, "scores": per_box, "total": sum(per_box.values())})
    ranking.sort(key=lambda r: r["total"], reverse=True)

    return {"matrices": matrices, "ranking": ranking}
