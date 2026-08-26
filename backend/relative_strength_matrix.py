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
Callers hand in raw {date: close} per symbol (not pre-aligned lists) —
alignment happens PER PAIR in compute_matrix, not once across the whole
group. That distinction matters: a group basket almost always has one
newer listing in it (BANDHANBNK IPO'd 2018, AUBANK 2017, IDFCFIRSTB's
current form dates to the 2018 Capital First merger). Intersecting dates
across the WHOLE group before computing any single pair would truncate
every pair's history to that youngest member's listing date, even a pair
of two other stocks that have both traded for 20 years — starving their
box chart of history it actually has, for no reason connected to that
pair at all.

Verified live (2026-08-05, real Dhan daily closes as an independent
source, Nifty Bank basket): fixing this did NOT move the aggregate
scores for that specific basket — several long-listed pairs (e.g.
HDFCBANK/PNB) DO get a different verdict on full history vs the
BANDHANBNK-truncated window, but liquid 1%/3% ratio charts had already
gone through a fresh 3-box reversal within the truncated window anyway,
so the extra pre-2018 history happened to be moot for THIS group's
current state. The fix is still correct on its own terms (group-wide
truncation for a reason unconnected to the pair is never right) and will
matter for other groups/box-size combinations even where it was a no-op
here."""
from __future__ import annotations

from pnf_engine import BoxSettings, build_columns

DEFAULT_REVERSAL = 3  # same fixed platform convention as pnf_chart.py


def pair_bias(closes_num: list, closes_den: list, box_pct: float) -> str | None:
    """Bullish for the numerator, bearish for the denominator, or None if
    there isn't enough ratio movement to plot even one column at this box
    size (never guessed — an unresolved pair is left out of both
    instruments' scores rather than counted as a coin flip).

    The ratio is scaled x1000 before construction — NOT cosmetic. Verified
    live against a real Definedge ratio chart (PNB/IDFCFIRSTB, 2026-08-04):
    pnf_engine's box grid is a fixed ABSOLUTE grid anchored at price=1.0
    (see pnf_engine.py's rule 8), and a raw ratio sits right around 1.0 by
    construction (two similarly-priced stocks). Scaling by a non-integer
    factor shifts every box boundary by a fractional box-width in log
    space, which is enough to flip a close call. Unscaled, this pair
    computed "down"; x1000-scaled, it computed "up" with a column range of
    1317.54-1324.14, formed 2026-08-04 — an exact match (to the cent) with
    Definedge's own live chart, which is not a coincidence. x1000 matches
    how Definedge itself displays a price ratio (e.g. "CMP: 1325.47" for a
    raw ratio of 1.32547)."""
    if len(closes_num) != len(closes_den) or len(closes_num) < 2:
        return None
    ratio = [1000 * n / d for n, d in zip(closes_num, closes_den) if d]
    if len(ratio) < 2:
        return None
    settings = BoxSettings(reversal_boxes=DEFAULT_REVERSAL, box_pct=box_pct / 100.0)
    columns = build_columns(ratio, settings)
    if not columns:
        return None
    return "bullish" if columns[-1].direction == "up" else "bearish"


def compute_matrix(symbols: list, closes_by_symbol: dict, box_pct: float, on_pair=None) -> dict:
    """Full NxN grid + per-symbol total score for one box size.

    `on_pair`, if given, is called once per pair processed (no arguments)
    — purely a progress hook for callers computing a big group (see
    relative_strength_routes.py's job-based /matrix-start, which uses this
    to report real percent-complete rather than a fabricated one). Every
    other caller (multi_market_engine.py, this module's own compute_ranking)
    omits it and behaves exactly as before.

    Computes BOTH directions of every pair (A/B and B/A) as their own
    independently-built ratio charts — NOT a mirror image of each other.
    A rising A/B ratio is the same underlying price movement as a falling
    B/A ratio, but P&F box/reversal construction is nonlinear under
    reciprocation (box boundaries don't map to their reciprocal boundaries
    at a fixed offset), so near a reversal boundary A/B and B/A can print
    the SAME last-column direction instead of opposite ones. Verified
    against Definedge's own "Ultimate Matrix" pairwise grid (Nifty Bank,
    2026-08-25): e.g. HDFCBANK/ICICIBANK and ICICIBANK/HDFCBANK both showed
    bearish (0) simultaneously at the 0.25% box — impossible if one side
    were merely inferred as the other's negation, which is exactly what
    this function used to do (a documented, now-fixed bug: see git history
    for relative_strength_matrix.py around 2026-08-26).

    `closes_by_symbol[s]` is {date: close} — each pair aligns to ITS OWN
    common dates here, not a group-wide intersection (see module
    docstring for why that distinction is load-bearing)."""
    grid = {s: {} for s in symbols}
    scores = {s: 0 for s in symbols}
    unresolved = {s: 0 for s in symbols}

    for i, a in enumerate(symbols):
        for b in symbols[i + 1:]:
            pair_dates = sorted(set(closes_by_symbol[a]) & set(closes_by_symbol[b]))
            closes_a = [closes_by_symbol[a][d] for d in pair_dates]
            closes_b = [closes_by_symbol[b][d] for d in pair_dates]

            bias_ab = pair_bias(closes_a, closes_b, box_pct)
            bias_ba = pair_bias(closes_b, closes_a, box_pct)

            grid[a][b] = bias_ab
            grid[b][a] = bias_ba

            if bias_ab is None:
                unresolved[a] += 1
            elif bias_ab == "bullish":
                scores[a] += 1

            if bias_ba is None:
                unresolved[b] += 1
            elif bias_ba == "bullish":
                scores[b] += 1

            if on_pair:
                on_pair()

    return {"grid": grid, "scores": scores, "unresolved": unresolved}


def compute_ranking(symbols: list, closes_by_symbol: dict, box_pcts: list, on_pair=None) -> dict:
    """Runs compute_matrix once per box size and combines them into the
    book's own "multi-timeframe" ranking table — each box size is its own
    independent matrix (not a rolling average), summed into a Total and
    sorted by it, descending. `on_pair` is passed straight through to each
    compute_matrix call (see there) — it fires once per pair PER box size,
    i.e. len(box_pcts) times per pair overall."""
    matrices = {}
    for box_pct in box_pcts:
        matrices[box_pct] = compute_matrix(symbols, closes_by_symbol, box_pct, on_pair=on_pair)

    ranking = []
    for s in symbols:
        per_box = {box_pct: matrices[box_pct]["scores"][s] for box_pct in box_pcts}
        ranking.append({"symbol": s, "scores": per_box, "total": sum(per_box.values())})
    ranking.sort(key=lambda r: r["total"], reverse=True)

    return {"matrices": matrices, "ranking": ranking}
