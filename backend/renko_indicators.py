"""Renko indicators — Chapters 7 and 8 of "Renko Charts" (Prashant Shah).

THE RULE THAT GOVERNS EVERYTHING HERE (Ch.7 opening): an indicator's
formula is unchanged on a Renko chart, but its INPUT is not — every
indicator here consumes ONE PRICE PER BRICK, not per bar. "The closing
price of a bullish brick is the high price of that brick... the closing
price of a bearish brick is the low price." Because a run of same-
direction bricks is bundled into one `renko_engine.Column`/`Brick`
object, this module works off the FLAT per-brick list
(`renko_engine.expand_to_bricks`), not the run list `renko_patterns.py`
uses — a 40-brick average genuinely means the last 40 printed boxes,
which is not the same as the last 40 swings.

Standard indicators (MA, MACD, Donchian, Bollinger, RSI) reuse the
generic, value-list primitives already in `pnf_indicators.py`
(`sma`/`ema`/`wma`) rather than duplicating them — those functions are
generic over any `values: list`, so they apply unchanged to a brick-
close price series.

Renko-unique indicators (Brick Count, Brick Zone, Brick Indicator,
Breadth family) have no P&F equivalent and are implemented fresh here,
per Ch.8.
"""
from __future__ import annotations

import math
from typing import Optional

from pnf_indicators import ema, sma, wma
from renko_engine import BoxSettings, BrickUnit, expand_to_bricks

_MA_FUNCS = {"sma": sma, "ema": ema, "wma": wma}

# Ch.7's own stated defaults throughout: "I recommend applying 40-brick
# exponential moving average on Renko charts for all instruments and
# all time frames."
DEFAULT_MA_PERIOD = 40
DEFAULT_MACD_FAST = 20
DEFAULT_MACD_SLOW = 40
DEFAULT_MACD_SIGNAL = 9
# Ch.7's second, special MACD reading used as a price/average disparity
# proxy: "I plot the MACD line with the parameters 1 and 40. The
# 1-period average is just a proxy for the actual price."
DISPARITY_MACD = (1, 40, 9)
DEFAULT_DONCHIAN_LOOKBACK = 40
DEFAULT_BOLLINGER_PERIOD = 40
DEFAULT_BOLLINGER_STDEV = 2.0
DEFAULT_RSI_PERIOD = 14
RSI_OVERBOUGHT = 80  # Ch.7: wider than the classic 70/30, "readings of 80 and 20"
RSI_OVERSOLD = 20
DEFAULT_BRICK_COUNT_LOOKBACK = 40
BREADTH_EXTREME_HIGH = 75  # Ch.8, groups of 30+ constituents
BREADTH_EXTREME_LOW = 25
BREADTH_EXTREME_HIGH_SMALL = 90  # Ch.8, groups under 30 constituents
BREADTH_EXTREME_LOW_SMALL = 10


# ---------------------------------------------------------------------------
# Per-brick price series — the input every indicator below consumes
# ---------------------------------------------------------------------------


def brick_close_prices(bricks: list, settings: BoxSettings, anchor: float = None) -> list:
    """One real price per printed brick: a bullish brick's close = its
    high, a bearish brick's close = its low (Ch.7) — i.e. simply the
    BrickUnit's own level, converted to price."""
    if not bricks:
        return []
    anchor = bricks[0].anchor if anchor is None else anchor
    return [settings.price_at(b.level, anchor) for b in bricks]


# ---------------------------------------------------------------------------
# Ch.7 — Moving Average
# ---------------------------------------------------------------------------


def moving_average(bricks: list, settings: BoxSettings, period: int = DEFAULT_MA_PERIOD,
                    kind: str = "ema") -> list:
    """Ch.7: a moving average of the last N Renko bricks, one price per
    brick. Book recommends EMA ("gives more weight to the more recent
    bricks") at 40-brick default, plus a 20/40 crossover system."""
    fn = _MA_FUNCS.get(kind)
    if fn is None:
        raise ValueError(f"unknown moving-average kind: {kind}")
    prices = brick_close_prices(bricks, settings)
    return fn(prices, period)


def moving_average_trend(bricks: list, settings: BoxSettings, period: int = DEFAULT_MA_PERIOD,
                          kind: str = "ema") -> Optional[str]:
    """Ch.7: 'An up trend can be objectively defined as a phase when the
    price is trading above the moving average line' (and vice versa)."""
    line = moving_average(bricks, settings, period, kind)
    if not line or line[-1] is None:
        return None
    prices = brick_close_prices(bricks, settings)
    return "up" if prices[-1] > line[-1] else "down"


def ma_crossover_state(bricks: list, settings: BoxSettings,
                        fast: int = 20, slow: int = DEFAULT_MA_PERIOD, kind: str = "ema") -> dict:
    """Ch.7: 'With two moving averages, the trend is bullish when the
    short term moving average line crosses above the longer term
    moving average line' — book's own recommended pairing is 20/40."""
    fast_line = moving_average(bricks, settings, fast, kind)
    slow_line = moving_average(bricks, settings, slow, kind)
    if not fast_line or not slow_line or fast_line[-1] is None or slow_line[-1] is None:
        return {"bias": None, "fast": None, "slow": None, "crossover": None}
    bias = "bullish" if fast_line[-1] > slow_line[-1] else "bearish"
    crossover = None
    if len(fast_line) >= 2 and fast_line[-2] is not None and slow_line[-2] is not None:
        prev_bias = "bullish" if fast_line[-2] > slow_line[-2] else "bearish"
        if prev_bias != bias:
            crossover = bias
    return {"bias": bias, "fast": fast_line[-1], "slow": slow_line[-1], "crossover": crossover}


# ---------------------------------------------------------------------------
# Ch.7 — MACD
# ---------------------------------------------------------------------------


def macd(bricks: list, settings: BoxSettings, fast: int = DEFAULT_MACD_FAST,
          slow: int = DEFAULT_MACD_SLOW, signal: int = DEFAULT_MACD_SIGNAL) -> dict:
    """Ch.7: MACD line = fast EMA - slow EMA of brick closes; signal =
    EMA of the MACD line. Pass fast=1 for the book's disparity-proxy
    reading (see DISPARITY_MACD)."""
    prices = brick_close_prices(bricks, settings)
    fast_line = ema(prices, fast)
    slow_line = ema(prices, slow)
    macd_line = [None if (a is None or b is None) else a - b for a, b in zip(fast_line, slow_line)]
    clean = [v for v in macd_line if v is not None]
    signal_line_clean = ema(clean, signal)
    signal_line = [None] * (len(macd_line) - len(clean)) + signal_line_clean
    histogram = [None if (m is None or s is None) else m - s for m, s in zip(macd_line, signal_line)]
    return {"macd": macd_line, "signal": signal_line, "histogram": histogram}


def macd_state(bricks: list, settings: BoxSettings, **kwargs) -> dict:
    result = macd(bricks, settings, **kwargs)
    if not result["macd"] or result["macd"][-1] is None:
        return {"macd": None, "signal": None, "crossover": None, "above_zero": None}
    m, s = result["macd"][-1], result["signal"][-1]
    crossover = None
    if len(result["macd"]) >= 2 and result["macd"][-2] is not None and result["signal"][-2] is not None:
        prev_diff = result["macd"][-2] - result["signal"][-2]
        cur_diff = m - s if s is not None else None
        if cur_diff is not None:
            if prev_diff <= 0 < cur_diff:
                crossover = "bullish"
            elif prev_diff >= 0 > cur_diff:
                crossover = "bearish"
    return {"macd": m, "signal": s, "crossover": crossover, "above_zero": m > 0}


# ---------------------------------------------------------------------------
# Ch.7 — Donchian Channel
# ---------------------------------------------------------------------------


def donchian_channel(bricks: list, settings: BoxSettings,
                      lookback: int = DEFAULT_DONCHIAN_LOOKBACK) -> list:
    """Ch.7: upper = highest high, lower = lowest low over the last N
    bricks, mid = their average. One reading per brick (None until the
    window is full)."""
    out = []
    for i in range(len(bricks)):
        if i + 1 < lookback:
            out.append({"upper": None, "lower": None, "mid": None})
            continue
        window = bricks[i + 1 - lookback:i + 1]
        levels = [b.level for b in window]
        upper_lv, lower_lv = max(levels), min(levels)
        upper = settings.price_at(upper_lv, bricks[i].anchor)
        lower = settings.price_at(lower_lv, bricks[i].anchor)
        out.append({"upper": upper, "lower": lower, "mid": (upper + lower) / 2.0})
    return out


def donchian_zone(bricks: list, settings: BoxSettings,
                   lookback: int = DEFAULT_DONCHIAN_LOOKBACK) -> Optional[str]:
    """Ch.7: 'bullish zone' = between mid and upper band, 'bearish zone'
    = between mid and lower band; 'flat' when both bands are stagnant
    (range-bound — the book: 'you must not trade breakouts when both
    the bands are flat')."""
    channel = donchian_channel(bricks, settings, lookback)
    if len(channel) < 2 or channel[-1]["mid"] is None:
        return None
    cur, prev = channel[-1], channel[-2]
    price = brick_close_prices(bricks, settings)[-1]
    flat = prev["upper"] is not None and cur["upper"] == prev["upper"] and cur["lower"] == prev["lower"]
    if flat:
        return "flat"
    return "bullish" if price >= cur["mid"] else "bearish"


# ---------------------------------------------------------------------------
# Ch.7 — Bollinger Bands + Bandwidth
# ---------------------------------------------------------------------------


def bollinger_bands(bricks: list, settings: BoxSettings, period: int = DEFAULT_BOLLINGER_PERIOD,
                     stdev: float = DEFAULT_BOLLINGER_STDEV) -> list:
    """Ch.7: standard Bollinger Bands, except the standard deviation is
    calculated from brick-close averages, not price bars. 40-brick,
    2-stdev is the book's stated preference on Renko charts."""
    prices = brick_close_prices(bricks, settings)
    out = []
    for i in range(len(prices)):
        if i + 1 < period:
            out.append({"mid": None, "upper": None, "lower": None})
            continue
        window = prices[i + 1 - period:i + 1]
        m = sum(window) / period
        var = sum((v - m) ** 2 for v in window) / period
        sd = math.sqrt(var)
        out.append({"mid": m, "upper": m + stdev * sd, "lower": m - stdev * sd})
    return out


def bollinger_bandwidth(bricks: list, settings: BoxSettings, period: int = DEFAULT_BOLLINGER_PERIOD,
                         stdev: float = DEFAULT_BOLLINGER_STDEV, ma_period: int = DEFAULT_BOLLINGER_PERIOD) -> dict:
    """Ch.7 Bollinger Bandwidth: band-width line (upper - lower) plus its
    own moving average; a crossover of the two suggests a possible band
    expansion (direction still needs price-pattern confirmation, per the
    book), and a flat bandwidth line signals a squeeze."""
    bands = bollinger_bands(bricks, settings, period, stdev)
    width = [None if b["upper"] is None else b["upper"] - b["lower"] for b in bands]
    clean = [w for w in width if w is not None]
    ma_clean = sma(clean, ma_period)
    ma_line = [None] * (len(width) - len(clean)) + ma_clean
    return {"bandwidth": width, "bandwidth_ma": ma_line}


# ---------------------------------------------------------------------------
# Ch.7 — RSI
# ---------------------------------------------------------------------------


def rsi(bricks: list, settings: BoxSettings, period: int = DEFAULT_RSI_PERIOD) -> list:
    """Wilder's RSI on brick closes. Ch.7: 'the corresponding RSI on
    Renko charts would get plotted based on 14 bricks, instead of 14
    days.'"""
    prices = brick_close_prices(bricks, settings)
    out = [None] * len(prices)
    if len(prices) <= period:
        return out
    gains = losses = 0.0
    for i in range(1, period + 1):
        d = prices[i] - prices[i - 1]
        gains += max(d, 0.0)
        losses += max(-d, 0.0)
    avg_gain, avg_loss = gains / period, losses / period
    out[period] = 100.0 if avg_loss == 0 else 100.0 - 100.0 / (1 + avg_gain / avg_loss)
    for i in range(period + 1, len(prices)):
        d = prices[i] - prices[i - 1]
        avg_gain = (avg_gain * (period - 1) + max(d, 0.0)) / period
        avg_loss = (avg_loss * (period - 1) + max(-d, 0.0)) / period
        out[i] = 100.0 if avg_loss == 0 else 100.0 - 100.0 / (1 + avg_gain / avg_loss)
    return out


def rsi_state(bricks: list, settings: BoxSettings, period: int = DEFAULT_RSI_PERIOD) -> dict:
    series = rsi(bricks, settings, period)
    if not series or series[-1] is None:
        return {"value": None, "zone": None}
    v = series[-1]
    zone = "overbought" if v >= RSI_OVERBOUGHT else ("oversold" if v <= RSI_OVERSOLD else "neutral")
    return {"value": v, "zone": zone}


# ---------------------------------------------------------------------------
# Ch.8 — Brick Count Indicator, Brick Zone, Brick Indicator
# ---------------------------------------------------------------------------


def brick_count_indicator(bricks: list, lookback: int = DEFAULT_BRICK_COUNT_LOOKBACK) -> list:
    """Ch.8: rolling count of bullish vs bearish bricks over the last N
    bricks — two lines. 'A trend is established when the distance
    between the two lines widens; congestion is indicated when the
    lines converge.'"""
    out = []
    for i in range(len(bricks)):
        if i + 1 < lookback:
            out.append({"bullish": None, "bearish": None})
            continue
        window = bricks[i + 1 - lookback:i + 1]
        out.append({
            "bullish": sum(1 for b in window if b.direction == "up"),
            "bearish": sum(1 for b in window if b.direction == "down"),
        })
    return out


def brick_zone(bricks: list, lookback: int = DEFAULT_BRICK_COUNT_LOOKBACK) -> list:
    """Ch.8: Brick Zone = Number of Bullish Bricks - Number of Bearish
    Bricks, a histogram oscillating around zero."""
    counts = brick_count_indicator(bricks, lookback)
    return [None if c["bullish"] is None else c["bullish"] - c["bearish"] for c in counts]


def brick_zone_state(bricks: list, lookback: int = DEFAULT_BRICK_COUNT_LOOKBACK) -> dict:
    """Ch.8's three readings: Zone (above/below zero), Crossover (zero-
    line cross), Caution (price in a zone but the indicator turning
    against it)."""
    series = [v for v in brick_zone(bricks, lookback) if v is not None]
    if not series:
        return {"value": None, "zone": None, "crossover": None, "caution": None}
    cur = series[-1]
    zone = "bullish" if cur > 0 else ("bearish" if cur < 0 else "neutral")
    crossover = None
    caution = None
    if len(series) >= 2:
        prev = series[-2]
        if prev <= 0 < cur:
            crossover = "bullish"
        elif prev >= 0 > cur:
            crossover = "bearish"
        if zone == "bullish" and cur < prev:
            caution = "bullish_zone_weakening"
        elif zone == "bearish" and cur > prev:
            caution = "bearish_zone_regaining"
    return {"value": cur, "zone": zone, "crossover": crossover, "caution": caution}


def brick_indicator(bricks: list, lookback: int = DEFAULT_BRICK_COUNT_LOOKBACK,
                     ma_period: int = DEFAULT_BRICK_COUNT_LOOKBACK) -> dict:
    """Ch.8 Brick Indicator: Brick Zone plotted as a line with its own
    moving average overlaid — crossover-driven, rather than the plain
    histogram reading of Brick Zone alone."""
    zone = brick_zone(bricks, lookback)
    clean = [v for v in zone if v is not None]
    ma_clean = sma(clean, ma_period)
    ma_line = [None] * (len(zone) - len(clean)) + ma_clean
    crossover = None
    if len(zone) >= 2 and zone[-1] is not None and zone[-2] is not None and ma_line[-1] is not None and ma_line[-2] is not None:
        prev_diff = zone[-2] - ma_line[-2]
        cur_diff = zone[-1] - ma_line[-1]
        if prev_diff <= 0 < cur_diff:
            crossover = "bullish"
        elif prev_diff >= 0 > cur_diff:
            crossover = "bearish"
    return {"zone": zone, "zone_ma": ma_line, "crossover": crossover}


# ---------------------------------------------------------------------------
# Ch.8 — Breadth family (group/sector-level, not single-instrument)
# ---------------------------------------------------------------------------


def bullish_brick_percent(directions: list) -> Optional[float]:
    """Ch.8: 'Bullish brick percent breadth indicator is arrived at by
    measuring the number of stocks where the latest brick is bullish
    and dividing it by the total number of stocks in that group.'
    `directions` is one "up"/"down" string per constituent's latest
    brick direction."""
    if not directions:
        return None
    bullish = sum(1 for d in directions if d == "up")
    return 100.0 * bullish / len(directions)


def breadth_extreme_zone(value: Optional[float], group_size: int) -> Optional[str]:
    """Ch.8: extreme zone at 75/25 for groups of 30+ constituents, 90/10
    for smaller groups (the book: 'if there are fewer constituents, 10%
    and 90% should be treated as extreme readings')."""
    if value is None:
        return None
    hi, lo = (BREADTH_EXTREME_HIGH, BREADTH_EXTREME_LOW) if group_size >= 30 \
        else (BREADTH_EXTREME_HIGH_SMALL, BREADTH_EXTREME_LOW_SMALL)
    if value >= hi:
        return "overbought"
    if value <= lo:
        return "oversold"
    return "neutral"


def sector_group_breadth(groups: dict) -> dict:
    """Ch.8 sector-group breadth table: `groups` is {sector_name:
    [direction, ...]} for that sector's constituents; returns
    {sector_name: {"breadth": pct, "zone": ...}}."""
    out = {}
    for name, directions in groups.items():
        pct = bullish_brick_percent(directions)
        out[name] = {"breadth": pct, "zone": breadth_extreme_zone(pct, len(directions))}
    return out


def breadth_divergence(breadth_series: list, index_price_series: list) -> Optional[str]:
    """Ch.8: 'Positive divergence in the breadth indicator ... occurs
    when the price makes a new low but breadth does not. Correspondingly,
    a negative divergence is marked when the price makes new high but
    the indicator is unable to do so.' Compares only the latest two
    points of each series (a simple two-bar swing check — a full swing-
    pivot divergence scan is the caller's job if a richer read is
    needed)."""
    if len(breadth_series) < 2 or len(index_price_series) < 2:
        return None
    b_prev, b_cur = breadth_series[-2], breadth_series[-1]
    p_prev, p_cur = index_price_series[-2], index_price_series[-1]
    if p_cur < p_prev and b_cur >= b_prev:
        return "positive"
    if p_cur > p_prev and b_cur <= b_prev:
        return "negative"
    return None


# ---------------------------------------------------------------------------
# Combined snapshot
# ---------------------------------------------------------------------------


def indicator_snapshot(columns: list, settings: BoxSettings) -> dict:
    """Everything a signal gate typically wants, in one pass. `columns`
    is the run-level swing list from `renko_engine.build_bricks` — this
    expands it to the flat per-brick series internally."""
    bricks = expand_to_bricks(columns)
    if not bricks:
        return {}
    return {
        "ma_trend": moving_average_trend(bricks, settings),
        "ma_crossover": ma_crossover_state(bricks, settings),
        "macd": macd_state(bricks, settings),
        "donchian_zone": donchian_zone(bricks, settings),
        "rsi": rsi_state(bricks, settings),
        "brick_zone": brick_zone_state(bricks),
        "brick_indicator": brick_indicator(bricks),
        "brick_count": len(bricks),
        "current_direction": bricks[-1].direction,
    }
