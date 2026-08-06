"""Renko charting service — turns an instrument + parameters into a
fully rendered Renko chart: the brick grid itself, every pattern the
book defines, and the Renko indicators.

Mirrors `pnf_chart.py`'s shape exactly. All the actual domain logic
lives in three lower modules, sourced from "Renko Charts" (Prashant
Shah):
    renko_engine.py      brick construction (thin wrapper on pnf_engine)
    renko_patterns.py    every documented formation + failure rules
    renko_indicators.py  MA/MACD/Donchian/Bollinger/RSI + brick/breadth family

`build_chart()` is pure — bars in, payload out, no I/O — reusable by a
scanner/backtest without touching the network. Bar prep (resampling,
minute aggregation, live-bar stitching, Definedge fetch) is IDENTICAL
to P&F's, so it's imported from pnf_chart.py rather than duplicated —
none of that logic is P&F-specific, it operates on raw bars before
either engine ever sees them.

CLOSE-ONLY, ALWAYS — same reasoning as pnf_chart.py: the book's own
worked exercises are all closing-price method.
"""
from __future__ import annotations

from dataclasses import replace
from typing import Optional

import renko_indicators as ri
import renko_patterns as rp
from pnf_chart import (  # bar prep is identical for both charting products
    VALID_INTERVALS,
    _bar_label,
    _with_live_bar,
    aggregate_minutes,
    fetch_bars,
    resample_daily,
)
from renko_engine import BoxSettings, brick_settings, build_bricks, expand_to_bricks

DEFAULT_BOX_PCT = 0.25
DEFAULT_REVERSAL = 2  # Renko's fixed brick-reversal distance — see renko_engine.py
MAX_SWINGS_RENDERED = 400


class RenkoError(Exception):
    """Instrument/parameter problems that are safe to show a caller."""


def _serialise_swing(s, n: int, settings: BoxSettings, anchor: float, labels: list) -> dict:
    lo, hi = rp.bottom(s), rp.top(s)
    return {
        "index": n,
        "direction": "up" if s.direction == "up" else "down",
        "top_level": hi,
        "bottom_level": lo,
        "top_price": round(settings.price_at(hi, anchor), 4),
        "bottom_price": round(settings.price_at(lo, anchor), 4),
        "box_count": s.box_count,
        "start_label": labels[s.start_index] if 0 <= s.start_index < len(labels) else None,
        "end_label": labels[s.end_index] if 0 <= s.end_index < len(labels) else None,
    }


def _serialise_pattern(p: rp.Pattern, settings: BoxSettings, anchor: float, swings: list) -> dict:
    failed_at = rp.has_failed(swings, p)
    ft = rp.find_follow_through(swings, p) if p.name in rp.MAJOR_PATTERNS else None
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
        "major": p.name in rp.MAJOR_PATTERNS,
        "meta": p.meta,
        "follow_through_index": ft.index if ft else None,
    }
    out.update({k: round(v, 4) for k, v in p.prices(settings, anchor).items()})
    return out


def build_chart(bars: list, box_pct: Optional[float] = DEFAULT_BOX_PCT,
                 box_value: Optional[float] = None,
                 cfg: rp.PatternConfig = rp.DEFAULT_CONFIG,
                 ma_period: int = 40,
                 max_swings: int = MAX_SWINGS_RENDERED) -> dict:
    """Build the full chart payload from OHLC bars (close is all that is
    read). Exactly one of box_pct (in PERCENT, e.g. 0.25) or box_value
    must be given. reversal_boxes is NOT a parameter — Renko is always
    2 (see renko_engine.py), unlike P&F where reversal varies.

    Patterns/indicators are computed over the WHOLE swing history — only
    the rendered grid is trimmed to `max_swings`."""
    if (box_pct is None) == (box_value is None):
        raise RenkoError("Specify exactly one of box_pct or box_value.")
    if box_pct is not None and box_pct <= 0:
        raise RenkoError("box_pct must be greater than zero.")
    if box_value is not None and box_value <= 0:
        raise RenkoError("box_value must be greater than zero.")

    closes = [b.get("close") for b in bars]
    labels = [_bar_label(b) for b in bars]
    settings = brick_settings(
        box_pct=(box_pct / 100.0) if box_pct is not None else None,
        box_value=box_value,
    )
    swings = build_bricks(closes, settings)
    if not swings:
        raise RenkoError("Not enough price movement to plot a single brick at this brick size.")

    cfg = replace(cfg, settings=settings)
    anchor = swings[0].anchor
    patterns = rp.scan(swings, cfg)
    bricks = expand_to_bricks(swings)

    start = max(0, len(swings) - max_swings)
    rendered = swings[start:]
    min_level = min(rp.bottom(s) for s in rendered)
    max_level = max(rp.top(s) for s in rendered)

    ser_patterns = [_serialise_pattern(p, settings, anchor, swings) for p in patterns]

    last = swings[-1]
    active = [p for p in ser_patterns if p["active"] and p["major"]]

    ma_line = ri.moving_average(bricks, settings, ma_period)
    bollinger = ri.bollinger_bands(bricks, settings)
    donchian = ri.donchian_channel(bricks, settings)

    return {
        "params": {
            "box_pct": box_pct, "box_value": box_value, "reversal_boxes": DEFAULT_REVERSAL,
            "method": "cl", "ma_period": ma_period,
        },
        "meta": {
            "bars": len(bars),
            "first_label": labels[0] if labels else None,
            "last_label": labels[-1] if labels else None,
            "last_price": closes[-1] if closes else None,
            "anchor_price": anchor,
            "total_swings": len(swings),
            "total_bricks": len(bricks),
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
        "swings": [_serialise_swing(s, start + n, settings, anchor, labels)
                   for n, s in enumerate(rendered)],
        "patterns": ser_patterns,
        "indicators": {
            **ri.indicator_snapshot(swings, settings),
            "moving_average": [None if v is None else round(v, 4) for v in ma_line],
            "bollinger_bands": [
                {k: (None if v is None else round(v, 4)) for k, v in row.items()}
                for row in bollinger
            ],
            "donchian_channel": [
                {k: (None if v is None else round(v, 4)) for k, v in row.items()}
                for row in donchian
            ],
        },
        "summary": _summarise(swings, last, active, settings, anchor),
    }


def _summarise(swings: list, last, active: list, settings: BoxSettings, anchor: float) -> dict:
    """The "what is this chart saying right now" block. `bias` weighs
    only ACTIVE (un-negated) major patterns — Ch.5: a failed pattern is
    itself information about the OTHER side, so a negated bullish
    pattern must never count as bullish."""
    bullish = [p for p in active if p["bias"] == "bullish"]
    bearish = [p for p in active if p["bias"] == "bearish"]
    if len(bullish) > len(bearish):
        bias = "bullish"
    elif len(bearish) > len(bullish):
        bias = "bearish"
    else:
        bias = "neutral"
    latest = sorted(active, key=lambda p: p["index"], reverse=True)[:5]

    # Ch.1: continuation needs one more box the same way; reversal needs
    # 2 boxes back off the extreme (renko_engine's reversal_boxes=2).
    if last.direction == "up":
        continuation_level = rp.top(last) + 1
        reversal_level = rp.top(last) - settings.reversal_boxes
    else:
        continuation_level = rp.bottom(last) - 1
        reversal_level = rp.bottom(last) + settings.reversal_boxes

    return {
        "bias": bias,
        "active_bullish": len(bullish),
        "active_bearish": len(bearish),
        "latest_patterns": latest,
        "current_swing": {
            "direction": last.direction,
            "boxes": last.box_count,
            "top_price": round(settings.price_at(rp.top(last), anchor), 4),
            "bottom_price": round(settings.price_at(rp.bottom(last), anchor), 4),
        },
        "reversal_price": round(settings.price_at(reversal_level, anchor), 4),
        "continuation_price": round(settings.price_at(continuation_level, anchor), 4),
    }


async def chart_for_instrument(definedge, segment: str, token: str,
                                interval: str = "daily", **kwargs) -> dict:
    if interval not in VALID_INTERVALS:
        raise RenkoError(f"interval must be one of {', '.join(VALID_INTERVALS)}")
    years = kwargs.pop("years", 10)
    days = kwargs.pop("days", 30)
    bars = await fetch_bars(definedge, segment, token, interval, years=years, days=days)
    if not bars:
        raise RenkoError("No price history available for this instrument.")
    chart = build_chart(bars, **kwargs)
    chart["params"]["interval"] = interval
    return chart
