"""
Black Box strategy "Volume Cascade" -- pure signal logic. Public name for
the sourcing deck's "Volume Speaks" (DECNOCH 2023, Sandeep Kumar); per this
codebase's naming convention, the public name and internal identifiers
never carry the presenter's name.

Method, from the deck (the "TAAL" funnel -- Trigger, Analyze, Act):
  1. Trigger (Volume): today's volume > `volume_multiplier` x the trailing
     `volume_avg_days`-day average volume, AND today's close > yesterday's
     close.
  2. Analyze (Relative Strength): the stock's price-ratio chart vs. NIFTY
     50 (P&F, `rs_box_pct` box) shows a fresh Turtle Breakout in the
     matching direction -- reuses pnf_patterns.detect_turtle_breakout
     exactly (book section 2.6), fed a ratio series instead of a raw
     price series (same technique relative_strength_matrix.py already
     uses for the Relative Strength Engine).
  3. Act (Price): the stock's own price P&F chart (`price_box_pct` box)
     confirms the SAME Turtle Breakout, with its column-moving-average
     sloping in the trade's direction (pnf_indicators.moving_average_trend,
     book 4.1).

Exit: stop on the opposite Turtle Breakout signal, or the moving average
turning against the position, whichever comes first -- both directly
from the deck ("Stop-loss ... on Turtle Breakout Bearish signal" / "TMA
turns down"). Target/booking is genuinely UNSPECIFIED in the deck ("stop
loss per individual risk plan", "target X% as per individual") -- it
gives neither a stop distance nor a target, only the general shape ("book
50% at 1R, hold the rest"). Rather than invent a plausible-sounding number
silently, this module adds one explicit, disclosed substitution
(`stop_pct`, same pattern as blackbox_trend_ignition.py's own undefined-
parameter fix) so "1R" has an actual distance to be measured against.

The optional fundamentals pre-filter ("FI" step) in the deck is NOT
implemented here -- it needs point-in-time quarterly sales/profit/EBITDA
growth data this codebase doesn't ingest yet (same gap as the shelved
funda_research.md work), and the deck itself calls it optional.
"""
from __future__ import annotations

from dataclasses import dataclass

from pnf_engine import BoxSettings, build_columns
from pnf_patterns import DEFAULT_CONFIG as PATTERN_DEFAULTS, detect_turtle_breakout
from pnf_indicators import moving_average_trend


@dataclass
class VolumeCascadeConfig:
    volume_avg_days: int = 10
    volume_multiplier: float = 2.0
    rs_box_pct: float = 0.25
    price_box_pct: float = 0.25
    reversal_boxes: int = 3
    ma_period_columns: int = 20
    stop_pct: float = 0.05           # this build's own substitution for the deck's
                                      # undefined stop distance (flagged in module docstring)
    booking_r_multiple: float = 1.0  # deck's own worked example: book at 1R
    booking_fraction: float = 0.5


DEFAULT_CONFIG = VolumeCascadeConfig()


def _turtle_bias(columns: list, cfg=PATTERN_DEFAULTS) -> str | None:
    if len(columns) < 2:
        return None
    p = detect_turtle_breakout(columns, len(columns) - 1, cfg)
    return p.bias if p is not None else None


def check_entry(daily_bars: list, benchmark_closes_by_date: dict, cfg: VolumeCascadeConfig = DEFAULT_CONFIG) -> dict | None:
    """`daily_bars`: oldest -> newest OHLCV dicts (with "date" ISO strings)
    for the stock. `benchmark_closes_by_date`: {date: close} for NIFTY 50,
    used to build the ratio (RS) chart aligned to the stock's own dates --
    same per-pair alignment discipline as relative_strength_matrix.py
    (never truncates to a whole-universe date intersection)."""
    if len(daily_bars) < cfg.volume_avg_days + 2:
        return None
    if any(b.get("volume") is None for b in daily_bars[-(cfg.volume_avg_days + 1):]):
        return None

    today = daily_bars[-1]
    prior_volumes = [b["volume"] for b in daily_bars[-(cfg.volume_avg_days + 1):-1]]
    avg_volume = sum(prior_volumes) / len(prior_volumes)
    if avg_volume <= 0 or today["volume"] < cfg.volume_multiplier * avg_volume:
        return None
    if today["close"] <= daily_bars[-2]["close"]:
        return None

    pair_dates = [b["date"] for b in daily_bars if b["date"] in benchmark_closes_by_date]
    if len(pair_dates) < 20:
        return None
    stock_by_date = {b["date"]: b["close"] for b in daily_bars}
    ratio = [1000 * stock_by_date[d] / benchmark_closes_by_date[d] for d in pair_dates]
    rs_settings = BoxSettings(reversal_boxes=cfg.reversal_boxes, box_pct=cfg.rs_box_pct / 100.0)
    rs_columns = build_columns(ratio, rs_settings)
    rs_bias = _turtle_bias(rs_columns)
    if rs_bias is None:
        return None

    price_settings = BoxSettings(reversal_boxes=cfg.reversal_boxes, box_pct=cfg.price_box_pct / 100.0)
    price_closes = [b["close"] for b in daily_bars]
    price_columns = build_columns(price_closes, price_settings)
    price_bias = _turtle_bias(price_columns)
    if price_bias is None or price_bias != rs_bias:
        return None

    ma_trend = moving_average_trend(price_columns, price_settings, cfg.ma_period_columns)
    wanted_trend = "up" if rs_bias == "bullish" else "down"
    if ma_trend != wanted_trend:
        return None

    entry_price = today["close"]
    stop_price = entry_price * (1 - cfg.stop_pct) if rs_bias == "bullish" else entry_price * (1 + cfg.stop_pct)
    return {
        "bias": rs_bias, "entry_price": entry_price, "stop_price": stop_price,
        "volume_ratio": round(today["volume"] / avg_volume, 2),
    }


def check_exit(daily_bars: list, position: dict, cfg: VolumeCascadeConfig = DEFAULT_CONFIG) -> dict | None:
    """Stop on the opposite-direction Turtle Breakout (price chart) or the
    column moving average turning against the position -- whichever the
    latest bar shows first. Books a fixed fraction once at `booking_r_multiple`
    x the entry's own stop distance, per the deck's "book 50% at 1R" shape.
    `position`: {"bias", "entry_price", "stop_price", "booked": bool}."""
    today = daily_bars[-1]
    bias = position["bias"]
    price_settings = BoxSettings(reversal_boxes=cfg.reversal_boxes, box_pct=cfg.price_box_pct / 100.0)
    price_columns = build_columns([b["close"] for b in daily_bars], price_settings)
    if len(price_columns) < 2:
        return None

    opp_bias = "bearish" if bias == "bullish" else "bullish"
    if _turtle_bias(price_columns) == opp_bias:
        return {"reason": "opposite_turtle_breakout", "exit_price": today["close"]}

    ma_trend = moving_average_trend(price_columns, price_settings, cfg.ma_period_columns)
    against_trend = "down" if bias == "bullish" else "up"
    if ma_trend == against_trend:
        return {"reason": "ma_turned", "exit_price": today["close"]}

    if not position.get("booked"):
        risk = abs(position["entry_price"] - position["stop_price"])
        target = (position["entry_price"] + risk * cfg.booking_r_multiple if bias == "bullish"
                  else position["entry_price"] - risk * cfg.booking_r_multiple)
        hit = today["close"] >= target if bias == "bullish" else today["close"] <= target
        if hit:
            return {"reason": "partial_booking", "exit_price": today["close"],
                    "booked_fraction": cfg.booking_fraction, "partial": True}
    return None
