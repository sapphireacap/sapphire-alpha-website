"""Renko relative strength — Chapter 9 of "Renko Charts" (Prashant Shah).

Direct port of `relative_strength_matrix.py`'s method: for every pair of
instruments, build a Renko chart of their price RATIO (numerator /
denominator). A bullish last brick means the numerator is currently
outperforming; a bearish last brick means the denominator is. Each
instrument's score is how many of its pairwise comparisons currently
favor it. Book (Ch.9, Renko Relative Strength Matrix): "score it 1 when
a sector is bullish and score 0 when it is bearish... resulting total
score will help us to analyse the performance of all the sectors at a
glance" — exactly this method, just described for Renko instead of P&F.

The ratio-chart construction itself is identical to the P&F version
(same x1000 scaling rationale — see relative_strength_matrix.pair_bias's
docstring for why that isn't cosmetic) except reversal_boxes=2 (Renko;
renko_engine.brick_settings), not 3 (P&F).

Deliberately pure — no I/O, same discipline as pnf_chart.build_chart()
and relative_strength_matrix.py itself.
"""
from __future__ import annotations

from renko_engine import brick_settings, build_bricks

DEFAULT_REVERSAL = 2  # Renko's brick-reversal distance — see renko_engine.py


def pair_bias(closes_num: list, closes_den: list, box_pct: float) -> str | None:
    """Bullish for the numerator, bearish for the denominator, or None if
    there isn't enough ratio movement to plot even one brick at this
    brick size."""
    if len(closes_num) != len(closes_den) or len(closes_num) < 2:
        return None
    ratio = [1000 * n / d for n, d in zip(closes_num, closes_den) if d]
    if len(ratio) < 2:
        return None
    settings = brick_settings(box_pct=box_pct / 100.0)
    bricks = build_bricks(ratio, settings)
    if not bricks:
        return None
    return "bullish" if bricks[-1].direction == "up" else "bearish"


def compute_matrix(symbols: list, closes_by_symbol: dict, box_pct: float) -> dict:
    """Full NxN grid + per-symbol total score for one brick size. Only
    computes the upper triangle — a rising A/B ratio is the same
    movement as a falling B/A ratio, so the lower triangle is the exact
    mirror image, not a second computation.

    `closes_by_symbol[s]` is {date: close} — each pair aligns to ITS OWN
    common dates (see relative_strength_matrix.py's module docstring for
    why group-wide date intersection is wrong here)."""
    grid = {s: {} for s in symbols}
    scores = {s: 0 for s in symbols}
    unresolved = {s: 0 for s in symbols}

    for i, a in enumerate(symbols):
        for b in symbols[i + 1:]:
            pair_dates = sorted(set(closes_by_symbol[a]) & set(closes_by_symbol[b]))
            closes_num = [closes_by_symbol[a][d] for d in pair_dates]
            closes_den = [closes_by_symbol[b][d] for d in pair_dates]
            bias = pair_bias(closes_num, closes_den, box_pct)
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
    """Runs compute_matrix once per brick size and combines them into the
    book's "multi-timeframe" ranking table — Ch.9: '0.25% brick-value
    chart for trading portfolio, 1% for intermediate and 3% for
    long-term investments' is the book's own suggested box_pcts set."""
    matrices = {}
    for box_pct in box_pcts:
        matrices[box_pct] = compute_matrix(symbols, closes_by_symbol, box_pct)

    ranking = []
    for s in symbols:
        per_box = {box_pct: matrices[box_pct]["scores"][s] for box_pct in box_pcts}
        ranking.append({"symbol": s, "scores": per_box, "total": sum(per_box.values())})
    ranking.sort(key=lambda r: r["total"], reverse=True)

    return {"matrices": matrices, "ranking": ranking}


def top_down(sector_symbols: list, sector_closes: dict, index_closes: dict,
             stock_symbols_by_sector: dict, stock_closes: dict,
             box_pcts: list) -> dict:
    """Ch.9 Top-Down Approach: first rank sectors against each other AND
    against the broad index (so the index is folded in as an extra
    "symbol" in the sector-level ranking), then — for the sector(s)
    that come out strongest — rank that sector's own constituent
    stocks against each other.

    `stock_symbols_by_sector` is {sector_name: [stock_symbol, ...]}; the
    strongest sector's stock-level ranking is what the book calls
    picking "strong stocks among the strong sectors."""
    sector_pool = list(sector_symbols)
    sector_closes_pool = dict(sector_closes)
    if "__INDEX__" not in sector_closes_pool and index_closes:
        sector_pool = sector_pool + ["__INDEX__"]
        sector_closes_pool = {**sector_closes_pool, "__INDEX__": index_closes}

    sector_ranking = compute_ranking(sector_pool, sector_closes_pool, box_pcts)
    strongest = next((r["symbol"] for r in sector_ranking["ranking"] if r["symbol"] != "__INDEX__"), None)

    stock_ranking = None
    if strongest is not None and strongest in stock_symbols_by_sector:
        stocks = stock_symbols_by_sector[strongest]
        stock_ranking = compute_ranking(stocks, stock_closes, box_pcts)

    return {
        "sector_ranking": sector_ranking,
        "strongest_sector": strongest,
        "stock_ranking": stock_ranking,
    }
