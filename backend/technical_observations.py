"""
Peter Tingle -- RSI/Bollinger/Donchian/Moving-Average narrative text.

Deliberately NEW, bar-based implementations, not reuses of the existing
RSI/Bollinger/Donchian in pnf_indicators.py/renko_indicators.py: those
compute one value per P&F COLUMN or Renko BRICK (a documented, real
convention for those engines -- "10 columns of P&F represent 10
trends", not 10 candles), which is the wrong granularity for a
standard daily-bar technical report. This module reads plain daily
closes/highs/lows instead, at the widely-used textbook defaults (RSI
14, Bollinger/Donchian 20) -- not the Renko modules' 40-period
defaults, which are tuned for a much higher-frequency brick series.

RSI uses Wilder's smoothing, same formula pnf_indicators.rsi() already
uses (just applied to daily closes instead of column closes) --
verified consistent with that module's own implementation.
"""
import pnf_chart

RSI_PERIOD = 14
BOLLINGER_PERIOD = 20
BOLLINGER_STDEV = 2.0
DONCHIAN_PERIOD = 20


def rsi_series(closes: list, period: int = RSI_PERIOD) -> list:
    """Wilder's RSI, one value per close (None until the window fills).
    Same recurrence as pnf_indicators.rsi(), applied to raw closes."""
    out = [None] * len(closes)
    if len(closes) <= period:
        return out
    gains = losses = 0.0
    for i in range(1, period + 1):
        d = closes[i] - closes[i - 1]
        gains += max(d, 0.0)
        losses += max(-d, 0.0)
    avg_gain, avg_loss = gains / period, losses / period
    out[period] = 100.0 if avg_loss == 0 else 100.0 - 100.0 / (1 + avg_gain / avg_loss)
    for i in range(period + 1, len(closes)):
        d = closes[i] - closes[i - 1]
        avg_gain = (avg_gain * (period - 1) + max(d, 0.0)) / period
        avg_loss = (avg_loss * (period - 1) + max(-d, 0.0)) / period
        out[i] = 100.0 if avg_loss == 0 else 100.0 - 100.0 / (1 + avg_gain / avg_loss)
    return out


def bollinger_bands(closes: list, period: int = BOLLINGER_PERIOD, stdev: float = BOLLINGER_STDEV) -> list:
    """{"mid","upper","lower"} per close, population stdev over the
    trailing `period` window -- same shape/statistic as
    pnf_indicators.bollinger_bands(), applied to raw closes."""
    out = []
    for i in range(len(closes)):
        if i + 1 < period:
            out.append(None)
            continue
        window = closes[i + 1 - period:i + 1]
        m = sum(window) / period
        var = sum((v - m) ** 2 for v in window) / period
        sd = var ** 0.5
        out.append({"mid": m, "upper": m + stdev * sd, "lower": m - stdev * sd})
    return out


def donchian_channel(highs: list, lows: list, period: int = DONCHIAN_PERIOD) -> list:
    """{"upper","lower","mid"} per bar, highest-high/lowest-low over the
    trailing `period` window INCLUDING the current bar -- same
    convention as renko_indicators.donchian_channel()."""
    out = []
    for i in range(len(highs)):
        if i + 1 < period:
            out.append(None)
            continue
        hw, lw = highs[i + 1 - period:i + 1], lows[i + 1 - period:i + 1]
        upper, lower = max(hw), min(lw)
        out.append({"upper": upper, "lower": lower, "mid": (upper + lower) / 2.0})
    return out


def _rsi_observation(bars: list, label: str) -> dict | None:
    closes = [b.get("close") for b in bars]
    series = rsi_series(closes)
    if not series or series[-1] is None:
        return None
    value = series[-1]
    zone = "bullish" if value >= 50 else "bearish"
    return {"period": label, "value": round(value, 2), "zone": zone}


def rsi_observations(daily_bars: list) -> dict:
    """RSI read on Daily/Weekly/Monthly closes -- weekly/monthly via the
    same resample_daily() rollup pivot levels and P&F Observations both
    already use, so all three "periods" in this report agree with each
    other on what a trading week/month actually was."""
    weekly = pnf_chart.resample_daily(daily_bars, "weekly")
    monthly = pnf_chart.resample_daily(daily_bars, "monthly")
    out = {}
    for key, bars in (("daily", daily_bars), ("weekly", weekly), ("monthly", monthly)):
        obs = _rsi_observation(bars, key)
        if obs:
            out[key] = obs
    return out


def bollinger_observation(daily_bars: list) -> dict | None:
    closes = [b.get("close") for b in daily_bars]
    bands = bollinger_bands(closes)
    if not bands or bands[-1] is None:
        return None
    last, prev = bands[-1], bands[-2] if len(bands) > 1 else None
    price = closes[-1]
    width_pct = (last["upper"] - last["lower"]) / last["mid"] * 100 if last["mid"] else None
    prev_width_pct = ((prev["upper"] - prev["lower"]) / prev["mid"] * 100) if prev and prev["mid"] else None
    converging = None if prev_width_pct is None or width_pct is None else width_pct < prev_width_pct
    return {
        "price_vs_mid": "above" if price >= last["mid"] else "below",
        "zone": "bullish" if price >= last["mid"] else "bearish",
        "converging": converging,
        "width_pct": round(width_pct, 2) if width_pct is not None else None,
    }


def donchian_observation(daily_bars: list) -> dict | None:
    highs = [b.get("high") for b in daily_bars]
    lows = [b.get("low") for b in daily_bars]
    closes = [b.get("close") for b in daily_bars]
    channel = donchian_channel(highs, lows)
    if not channel or channel[-1] is None:
        return None
    last, prev = channel[-1], channel[-2] if len(channel) > 1 else None
    price = closes[-1]
    lower_rising = None if prev is None else last["lower"] > prev["lower"]
    upper_rising = None if prev is None else last["upper"] > prev["upper"]
    width_pct = (last["upper"] - last["lower"]) / last["mid"] * 100 if last["mid"] else None
    return {
        "price_vs_mid": "above" if price >= last["mid"] else "below",
        "zone": "bullish" if price >= last["mid"] else "bearish",
        "lower_rising": lower_rising,
        "upper_rising": upper_rising,
        "width_pct": round(width_pct, 2) if width_pct is not None else None,
    }


def moving_average_observation(daily_bars: list, metrics: dict) -> dict | None:
    """dma_50/dma_200 are already computed for both markets (stock_
    computed_metrics for India, compute_metrics_from_bars() for US, see
    peter_tingle.py's DMA_WINDOWS) -- reused as-is, not recomputed here.
    `daily_bars` supplies only the one thing `metrics` doesn't carry:
    today's actual close, needed for the reference report's real
    wording ("Price remains below 200-day Moving average"), not just
    the DMA-vs-DMA golden/death-cross relationship."""
    m = metrics or {}
    dma50, dma200 = m.get("dma_50"), m.get("dma_200")
    if dma50 is None or dma200 is None or not daily_bars:
        return None
    price = daily_bars[-1].get("close")
    if price is None:
        return None
    return {
        "dma_50": round(dma50, 2), "dma_200": round(dma200, 2),
        "golden_cross": dma50 >= dma200,
        "price_vs_dma200": "above" if price >= dma200 else "below",
        "price_vs_dma50": "above" if price >= dma50 else "below",
    }


def technical_observations(daily_bars: list, metrics: dict) -> dict:
    """bars: daily OHLC, sorted oldest -> newest. Returns the four
    sub-sections; any of them individually null when there isn't enough
    history yet (e.g. a stock listed less than 20 sessions ago has no
    Bollinger/Donchian reading), same "None over fabricating" rule as
    every other Peter Tingle addition today."""
    return {
        "rsi": rsi_observations(daily_bars or []),
        "bollinger": bollinger_observation(daily_bars or []),
        "donchian": donchian_observation(daily_bars or []),
        "moving_average": moving_average_observation(daily_bars, metrics),
    }
