"""X-Percent Breadth — the pure computation core.

Method (Prashant Shah, "Trading The Markets The Point & Figure Way",
Ch. 10 "Breadth Indicators" / "X-Percent"): every stock in a group is
its own ordinary close-only P&F chart (same pnf_engine.py already used
for the single-symbol chart and Index Vector — a REAL price series, not
a ratio, so none of relative_strength_matrix.py's anchor-scaling
ambiguity applies here; rule 8's absolute grid at price=1.0 is already
verified against real instrument data). X-Percent for a given day is
just: of all stocks in the group, what fraction are CURRENTLY in an X
(bullish) column?

    X-Percent = (count of stocks whose latest P&F column is X) / (total
    resolved stocks in the group) * 100

Deliberately pure — no I/O, no group membership, no date fetching (see
breadth_routes.py for that). Callers hand in each symbol's own raw
{date: close} — NOT pre-aligned across the group. Unlike the pairwise
ratio matrix, there is no cross-symbol alignment concern here: each
stock's own P&F state is fully determined by its own price history
alone, so truncating one stock's calc to another's listing date would
only be pointlessly lossy, never wrong. Alignment only matters for the
OUTPUT date axis (turning per-symbol column state into one shared
daily breadth line), which happens in compute_breadth_series() below.
"""
from __future__ import annotations

from pnf_engine import BoxSettings, build_columns

DEFAULT_BOX_PCT = 1.0   # matches Definedge's own X-Percent default (screenshot, 2026-08-05)
DEFAULT_REVERSAL = 3    # same fixed platform convention as pnf_chart.py / relative_strength_matrix.py


def direction_by_date(closes_by_date: dict, box_pct: float = DEFAULT_BOX_PCT,
                       reversal_boxes: int = DEFAULT_REVERSAL) -> dict:
    """{date: "bullish"|"bearish"} for every date from this symbol's OWN
    first resolvable column onward — dates before any column has printed
    (rule 4's reference period) are simply absent, not guessed.

    Builds columns once off the full close series, then fills each
    column's date range with its own direction — the column's
    start_index/end_index already carry that mapping back to bar
    position (see pnf_engine.Column), so this is just a scan, not a
    second P&F walk."""
    dates = sorted(closes_by_date.keys())
    closes = [closes_by_date[d] for d in dates]
    settings = BoxSettings(reversal_boxes=reversal_boxes, box_pct=box_pct / 100.0)
    columns = build_columns(closes, settings)
    if not columns:
        return {}

    out = {}
    for i, col in enumerate(columns):
        start = col.start_index
        end = columns[i + 1].start_index - 1 if i + 1 < len(columns) else len(dates) - 1
        direction = "bullish" if col.direction == "up" else "bearish"
        for bar in range(start, end + 1):
            out[dates[bar]] = direction
    return out


def compute_breadth_series(closes_by_symbol: dict, box_pct: float = DEFAULT_BOX_PCT,
                            reversal_boxes: int = DEFAULT_REVERSAL) -> list:
    """[{date, value, resolved, total}, ...] sorted ascending — `value` is
    X-Percent (0-100) for that date, `resolved` is how many of `total`
    group members actually had a printed column by that date (thin at
    the start of the series, same "unresolved" honesty as
    relative_strength_matrix.compute_matrix — never padded to make the
    denominator look fuller than it is)."""
    per_symbol_directions = {
        s: direction_by_date(closes, box_pct, reversal_boxes)
        for s, closes in closes_by_symbol.items()
    }
    return compute_breadth_series_from_directions(per_symbol_directions, total=len(closes_by_symbol))


def compute_breadth_series_from_directions(per_symbol_directions: dict, total: int) -> list:
    """Same aggregation as compute_breadth_series, but takes each symbol's
    already-computed {date: direction} map directly. Lets a caller discard
    each symbol's raw multi-year close history right after computing its
    direction map, instead of holding every group member's full price
    history in memory at once until the very end — see breadth_routes.py's
    _refresh_group, the actual 500-symbol Nifty 500 job this split was
    written for."""
    all_dates = sorted(set.union(*(set(d.keys()) for d in per_symbol_directions.values())) if total else set())

    series = []
    for d in all_dates:
        bullish = 0
        resolved = 0
        for directions in per_symbol_directions.values():
            direction = directions.get(d)
            if direction is None:
                continue
            resolved += 1
            if direction == "bullish":
                bullish += 1
        if resolved == 0:
            continue
        series.append({
            "date": d,
            "value": round(100.0 * bullish / resolved, 2),
            "resolved": resolved,
            "total": total,
        })
    return series
