"""
Peter Tingle -- "Point & Figure Chart Observations" narrative text.

Built directly on the book-validated P&F engine (pnf_engine.py) and
pattern library (pnf_patterns.py) -- deliberately NOT through
pnf_chart.build_chart()/pnf_routes.py's paid /pnf/chart (gated behind
get_current_pnf_subscriber). This module never touches that gate; it's
a separate, free, text-only consumer of the same underlying engine,
built from raw Column objects rather than build_chart()'s serialized
payload, since that payload is shaped for the paid charting UI (grid,
trend lines, indicators, rendered-column trimming) this module has no
use for -- reusing it here would mean either dragging that shape into
a free feature or reshaping it and risking the paid consumer.

Box sizes match the requested reference report exactly: 0.25%, 1%, 3%.
"Qualified on the X% chart" is read literally: only patterns/signals
completing AT THE LAST (current) column are reported, not the chart's
whole history -- this is a "what does today's print mean" read, not a
pattern-history dump.
"""
from pnf_engine import BoxSettings, build_columns
import pnf_patterns as pf

OBSERVATION_BOX_PCTS = [0.25, 1.0, 3.0]
REVERSAL_BOXES = 3  # same convention as every other P&F use in this codebase


def _box_key(box_pct: float) -> str:
    return f"{box_pct:g}%"


def _observations_for_box(closes: list, box_pct: float) -> dict | None:
    settings = BoxSettings(reversal_boxes=REVERSAL_BOXES, box_pct=box_pct / 100.0)
    columns = build_columns(closes, settings)
    if not columns:
        return None
    last_index = len(columns) - 1
    last = columns[last_index]

    basic = pf.classify_basic_signal(columns, last_index)
    patterns_here = pf.detect_at(columns, last_index)

    # A pattern's OWN `index` is where it completed, which can be well
    # before its follow-through actually prints -- book 2.3: "it is not
    # necessary that Follow-through must occur in the immediate column".
    # So finding "did a follow-through land on THIS column" means
    # checking every major pattern in the chart's history, not just ones
    # completing here.
    follow_throughs = []
    for p in pf.scan(columns):
        if p.name not in pf.MAJOR_PATTERNS:
            continue
        ft = pf.find_follow_through(columns, p)
        if ft is not None and ft.index == last_index:
            follow_throughs.append(ft)

    return {
        "box_pct": box_pct,
        "column_direction": "X" if last.direction == "up" else "O",
        "column_boxes": last.box_count,
        "basic_signal": basic["label"] if basic else None,
        "basic_signal_bias": basic["signal"] if basic else None,
        "patterns": [{"label": p.label, "bias": p.bias} for p in patterns_here],
        "follow_throughs": [{"label": p.label, "bias": p.bias} for p in follow_throughs],
    }


def _bullets_for_box(key: str, obs: dict) -> list:
    out = [f"Price is in column of {obs['column_direction']} on the {key} chart."]
    if obs["basic_signal"]:
        out.append(f"{obs['basic_signal']} was formed in the current session on the {key} chart.")
    for p in obs["patterns"]:
        out.append(f"{p['bias'].capitalize()} {p['label']} qualified on the {key} chart.")
    for ft in obs["follow_throughs"]:
        out.append(f"{ft['label']} on the {key} chart.")
    return out


def pnf_observations(bars: list) -> dict:
    """bars: daily OHLC (close-only read here), sorted oldest -> newest --
    same shape definedge_service.daily_history()/yahoo_finance_client.
    equity_bars() both already return. Returns {"by_box": {key: obs|None},
    "bullets": [...]} across all OBSERVATION_BOX_PCTS -- `bullets` is the
    flat, ready-to-render sentence list; `by_box` is the structured form
    for a caller that wants to render its own layout instead."""
    closes = [b.get("close") for b in (bars or [])]
    by_box = {}
    bullets = []
    for box_pct in OBSERVATION_BOX_PCTS:
        key = _box_key(box_pct)
        obs = _observations_for_box(closes, box_pct)
        by_box[key] = obs
        if obs is not None:
            bullets.extend(_bullets_for_box(key, obs))
    return {"by_box": by_box, "bullets": bullets}
