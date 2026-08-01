"""P&F charting service — turns an instrument + parameters into a fully
rendered Point & Figure chart: the X/O grid itself, every pattern the
book defines, the P&F indicators, 45-degree trend lines and counts.

This is the layer the API and the frontend chart talk to. All the actual
domain logic lives in three lower modules, each sourced from Prashant
Shah's "Trading The Markets The Point & Figure Way":
    pnf_engine.py      construction (boxes, columns, reversals)
    pnf_patterns.py    every documented formation + failure rules
    pnf_indicators.py  XO family, column MAs/RSI/bands, trend lines, counts

`build_chart()` is deliberately PURE — it takes a list of bars and returns
the payload, with no I/O — so it can be tested against fixed data and
reused by a scanner or backtest without touching the network. The async
`chart_for_instrument()` wrapper is the only part that fetches.

CLOSE-ONLY, ALWAYS. pnf_engine implements the closing-price method only,
which is what the book recommends for time-interval charts ("one-minute
price is probably the best", and every intraday example in it is plotted
"cl"). High-Low charts exist on the vendor platform but are out of scope
here, so every chart this module produces is honestly labelled `"cl"`.
"""
from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta
from typing import Optional

import pnf_indicators as pi
import pnf_patterns as pf
from pnf_engine import BoxSettings, build_columns
from pnf_indicators import DEFAULT_XO_LOOKBACK

# FIXED PLATFORM CONVENTION (standing instruction, 2026-07-31): every
# chart this platform produces is close-only with a 3-box reversal, with
# only the box size varying. The reversal is therefore not exposed as an
# API parameter at all — see pnf_routes.py. `reversal` stays an argument
# on build_chart() because BoxSettings genuinely needs it and the counts
# formulas multiply by it, but callers on the product path pass the
# default and nothing else.
DEFAULT_BOX_PCT = 0.25
DEFAULT_REVERSAL = 3

VALID_INTERVALS = ("1", "3", "5", "15", "30", "60", "daily", "weekly", "monthly")
MAX_COLUMNS_RENDERED = 400


class PnfError(Exception):
    """Instrument/parameter problems that are safe to show a caller."""


# ---------------------------------------------------------------------------
# Bar preparation
# ---------------------------------------------------------------------------


def _period_key(bar: dict, interval: str) -> str:
    """Bucket key for weekly/monthly rollups of daily bars."""
    d = datetime.strptime(bar["date"], "%Y-%m-%d").date()
    if interval == "weekly":
        iso = d.isocalendar()
        return f"{iso[0]}-W{iso[1]:02d}"
    return f"{d.year}-{d.month:02d}"


def resample_daily(bars: list, interval: str) -> list:
    """Roll daily bars up to weekly/monthly. The close of the LAST bar in
    each bucket becomes the bucket's close — the only field P&F needs,
    since this engine is close-only."""
    if interval not in ("weekly", "monthly"):
        return bars
    buckets: dict[str, dict] = {}
    for b in bars:
        buckets.setdefault(_period_key(b, interval), []).append(b)
    out = []
    for key in sorted(buckets):
        group = buckets[key]
        out.append({
            "date": group[-1]["date"],
            "open": group[0]["open"],
            "high": max(g["high"] for g in group),
            "low": min(g["low"] for g in group),
            "close": group[-1]["close"],
        })
    return out


def aggregate_minutes(bars: list, minutes: int) -> list:
    """Group 1-minute bars into `minutes`-wide buckets. Timestamps are
    Definedge's ddmmyyyyHHMM, which is NOT sortable as a raw string
    (day-first), so everything is parsed to a real datetime first — a
    mistake already made and fixed once elsewhere in this codebase."""
    if minutes <= 1:
        return bars
    buckets: dict[datetime, list] = {}
    for b in bars:
        ts = datetime.strptime(b["ts"], "%d%m%Y%H%M")
        anchor = ts.replace(hour=9, minute=15, second=0, microsecond=0)
        if ts < anchor:
            anchor -= timedelta(days=1)
        offset = int((ts - anchor).total_seconds() // 60)
        bucket = anchor + timedelta(minutes=(offset // minutes) * minutes)
        buckets.setdefault(bucket, []).append(b)
    out = []
    for key in sorted(buckets):
        group = buckets[key]
        out.append({
            "ts": key.strftime("%d%m%Y%H%M"),
            "open": group[0]["open"],
            "high": max(g["high"] for g in group),
            "low": min(g["low"] for g in group),
            "close": group[-1]["close"],
        })
    return out


def _bar_label(bar: dict) -> str:
    if "date" in bar:
        return bar["date"]
    ts = bar.get("ts")
    if not ts:
        return ""
    try:
        return datetime.strptime(ts, "%d%m%Y%H%M").isoformat(sep=" ", timespec="minutes")
    except ValueError:
        return str(ts)


# ---------------------------------------------------------------------------
# Chart assembly
# ---------------------------------------------------------------------------


def _serialise_column(c, n: int, settings: BoxSettings, anchor: float, labels: list) -> dict:
    lo, hi = pf.bottom(c), pf.top(c)
    return {
        "index": n,
        "direction": "X" if c.direction == "up" else "O",
        "top_level": hi,
        "bottom_level": lo,
        "top_price": round(settings.price_at(hi, anchor), 4),
        "bottom_price": round(settings.price_at(lo, anchor), 4),
        "box_count": c.box_count,
        "levels": list(range(lo, hi + 1)),
        "start_label": labels[c.start_index] if 0 <= c.start_index < len(labels) else None,
        "end_label": labels[c.end_index] if 0 <= c.end_index < len(labels) else None,
    }


def _serialise_pattern(p: pf.Pattern, settings: BoxSettings, anchor: float,
                       columns: list) -> dict:
    failed_at = pf.has_failed(columns, p)
    ft = pf.find_follow_through(columns, p) if p.name in pf.MAJOR_PATTERNS else None
    out = {
        "name": p.name,
        "label": p.label,
        "bias": p.bias,
        "index": p.index,
        "start_index": p.start_index,
        "trigger_level": p.trigger_level,
        "failure_level": p.failure_level,
        "failed_at": failed_at,
        "active": failed_at is None and p.bias != "neutral",
        "major": p.name in pf.MAJOR_PATTERNS,
        "meta": p.meta,
        "follow_through_index": ft.index if ft else None,
    }
    out.update({k: round(v, 4) for k, v in p.prices(settings, anchor).items()})
    return out


def build_chart(bars: list, box_pct: Optional[float] = DEFAULT_BOX_PCT,
                box_value: Optional[float] = None,
                reversal: int = DEFAULT_REVERSAL,
                cfg: pf.PatternConfig = pf.DEFAULT_CONFIG,
                xo_lookback: int = DEFAULT_XO_LOOKBACK, ma_period: int = 20,
                max_columns: int = MAX_COLUMNS_RENDERED) -> dict:
    """Build the full chart payload from OHLC bars (close is all that is
    read). Exactly one of box_pct (in PERCENT, e.g. 0.25) or box_value
    must be given.

    Patterns, indicators and trend lines are computed over the WHOLE
    history — only the rendered grid is trimmed to `max_columns`, so a
    pattern is never missed just because the viewport is short. Column
    indices in the returned patterns/lines refer to the full column list,
    with `render_offset` telling the caller how many were trimmed off the
    front."""
    if (box_pct is None) == (box_value is None):
        raise PnfError("Specify exactly one of box_pct or box_value.")
    if box_pct is not None and box_pct <= 0:
        raise PnfError("box_pct must be greater than zero.")
    if box_value is not None and box_value <= 0:
        raise PnfError("box_value must be greater than zero.")
    if reversal < 1:
        raise PnfError("reversal must be at least 1.")

    closes = [b.get("close") for b in bars]
    labels = [_bar_label(b) for b in bars]
    settings = BoxSettings(
        reversal_boxes=reversal,
        box_pct=(box_pct / 100.0) if box_pct is not None else None,
        box_value=box_value,
    )
    columns = build_columns(closes, settings)
    if not columns:
        raise PnfError("Not enough price movement to plot a single column at this box size.")

    # The Pole rules need the box settings to measure their 50%
    # retracement in price space (see pnf_patterns.mid_price), so hand the
    # chart's own settings to the detectors rather than letting them fall
    # back to level arithmetic.
    cfg = replace(cfg, settings=settings)

    anchor = columns[0].anchor
    patterns = pf.scan(columns, cfg)
    retests = pf.find_pattern_retest(patterns, cfg)

    # Vertical counts from every column that turned off a swing extreme —
    # book 3.3: "A column of X coming after Bottom should be projected
    # higher and a column of O coming after Top should be projected lower."
    counts = []
    for c in pi.significant_counts(columns, settings):
        counts.append({
            "kind": c.kind, "variant": c.variant, "bias": c.bias,
            "column_index": c.column_index,
            "target_level": c.target_level, "base_level": c.base_level,
            "target_price": round(settings.price_at(c.target_level, anchor), 4),
            "meta": c.meta,
        })

    lines = [{
        "direction": ln.direction,
        "start_index": ln.start_index,
        "start_level": ln.start_level,
        "end_index": ln.end_index,
        "broken_index": ln.broken_index,
        "end_level": ln.level_at(ln.end_index),
    } for ln in pi.trend_lines(columns)]

    start = max(0, len(columns) - max_columns)
    rendered = columns[start:]
    min_level = min(pf.bottom(c) for c in rendered)
    max_level = max(pf.top(c) for c in rendered)

    ser_patterns = [_serialise_pattern(p, settings, anchor, columns) for p in patterns]
    ser_retests = [_serialise_pattern(p, settings, anchor, columns) for p in retests]

    last = columns[-1]
    active = [p for p in ser_patterns if p["active"] and p["major"]]
    return {
        "params": {
            "box_pct": box_pct, "box_value": box_value, "reversal": reversal,
            "method": "cl", "xo_lookback": xo_lookback, "ma_period": ma_period,
        },
        "meta": {
            "bars": len(bars),
            "first_label": labels[0] if labels else None,
            "last_label": labels[-1] if labels else None,
            "last_price": closes[-1] if closes else None,
            "anchor_price": anchor,
            "total_columns": len(columns),
            "render_offset": start,
        },
        "grid": {
            "min_level": min_level,
            "max_level": max_level,
            "levels": [
                {"level": lv, "price": round(settings.price_at(lv, anchor), 4)}
                for lv in range(min_level, max_level + 1)
            ],
        },
        "columns": [_serialise_column(c, start + n, settings, anchor, labels)
                    for n, c in enumerate(rendered)],
        "patterns": ser_patterns,
        "retests": ser_retests,
        "counts": counts,
        "trend_lines": lines,
        "indicators": {
            **pi.indicator_snapshot(columns, settings, xo_lookback, ma_period),
            "xo_zone_series": pi.xo_zone(columns, xo_lookback)[start:],
            "moving_average": [
                None if v is None else round(v, 4)
                for v in pi.column_moving_average(columns, settings, ma_period)[start:]
            ],
        },
        "summary": _summarise(columns, last, active, ser_patterns, settings, anchor),
    }


def _summarise(columns: list, last, active: list, all_patterns: list,
               settings: BoxSettings, anchor: float) -> dict:
    """The "what is this chart saying right now" block.

    `bias` weighs only ACTIVE (un-negated) major patterns, because the
    book is explicit that a negated pattern flips meaning entirely
    ("Negation of bullish pattern is bearish event") — counting a failed
    bullish pattern as bullish would be exactly backwards."""
    bullish = [p for p in active if p["bias"] == "bullish"]
    bearish = [p for p in active if p["bias"] == "bearish"]
    if len(bullish) > len(bearish):
        bias = "bullish"
    elif len(bearish) > len(bullish):
        bias = "bearish"
    else:
        bias = "neutral"
    latest = sorted(active, key=lambda p: p["index"], reverse=True)[:5]

    # The two levels that matter for the very next print, straight off the
    # engine's own rules: one more box the same way continues the column,
    # `reversal_boxes` back off its extreme starts a new one.
    if last.direction == "up":
        continuation_level = pf.top(last) + 1
        reversal_level = pf.top(last) - settings.reversal_boxes
    else:
        continuation_level = pf.bottom(last) - 1
        reversal_level = pf.bottom(last) + settings.reversal_boxes

    return {
        "bias": bias,
        "active_bullish": len(bullish),
        "active_bearish": len(bearish),
        "latest_patterns": latest,
        "current_column": {
            "direction": "X" if last.direction == "up" else "O",
            "boxes": last.box_count,
            "top_price": round(settings.price_at(pf.top(last), anchor), 4),
            "bottom_price": round(settings.price_at(pf.bottom(last), anchor), 4),
        },
        "reversal_price": round(settings.price_at(reversal_level, anchor), 4),
        "continuation_price": round(settings.price_at(continuation_level, anchor), 4),
    }


# ---------------------------------------------------------------------------
# Instrument fetch wrapper (the only I/O in this module)
# ---------------------------------------------------------------------------


async def fetch_bars(definedge, segment: str, token: str, interval: str,
                     years: int = 10, days: int = 30) -> list:
    """Bars at the requested interval. Daily/weekly/monthly come from
    Definedge's day history (rolled up locally); intraday comes from
    minute history aggregated into the requested bucket.

    Minute history only reaches back ~6 months upstream (verified), so a
    long intraday window silently returns whatever really exists rather
    than erroring — the caller reports the achieved range from the payload
    rather than assuming the requested one."""
    if interval in ("daily", "weekly", "monthly"):
        bars = await definedge.daily_history(segment, token, years=years)
        return resample_daily(bars, interval)

    minutes = int(interval)
    now = datetime.now()
    frm = (now - timedelta(days=days)).strftime("%d%m%Y0000")
    to = now.strftime("%d%m%Y%H%M")
    bars = await definedge.minute_ohlc(segment, token, frm=frm, to=to)
    return aggregate_minutes(bars, minutes)


async def chart_for_instrument(definedge, segment: str, token: str,
                               interval: str = "daily", **kwargs) -> dict:
    if interval not in VALID_INTERVALS:
        raise PnfError(f"interval must be one of {', '.join(VALID_INTERVALS)}")
    years = kwargs.pop("years", 10)
    days = kwargs.pop("days", 30)
    bars = await fetch_bars(definedge, segment, token, interval, years=years, days=days)
    if not bars:
        raise PnfError("No price history available for this instrument.")
    chart = build_chart(bars, **kwargs)
    chart["params"]["interval"] = interval
    return chart
