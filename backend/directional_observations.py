"""
Peter Tingle -- ADX/DMI and Ichimoku Kinko Hyo narrative observations.

NET-NEW math: neither indicator exists anywhere else in this codebase
(confirmed by an explicit repo-wide search before this module was
written). No prior implementation to reuse or stay consistent with,
unlike RSI/Bollinger/Donchian in technical_observations.py -- these are
built straight from each indicator's own standard, published formula
(Wilder's ADX; Hosoda's Ichimoku, traditional 9/26/52 periods), applied
to plain daily closes/highs/lows, and verified here only against
directional sanity checks on synthetic trending/choppy data (no
textbook worked example was available to transcribe the way
pnf_patterns.py's book-sourced detectors were) -- same standard of
rigor already applied to technical_observations.py's new indicators,
not a lower one.
"""

ADX_PERIOD = 14
ICHIMOKU_TENKAN = 9
ICHIMOKU_KIJUN = 26
ICHIMOKU_SENKOU_B = 52


def _wilder_smooth(values: list, period: int) -> list:
    """First smoothed value = sum of the first `period` values (not yet
    divided -- callers that want an average divide it themselves; ADX's
    own DM/TR smoothing is conventionally left as a running sum, not an
    average, which is why +DI/-DI divide two smoothed sums directly
    rather than two smoothed averages). Each later value = prev -
    prev/period + current, Wilder's own recurrence."""
    if len(values) < period:
        return [None] * len(values)
    out = [None] * (period - 1)
    total = sum(values[:period])
    out.append(total)
    prev = total
    for v in values[period:]:
        prev = prev - (prev / period) + v
        out.append(prev)
    return out


def adx_dmi_series(highs: list, lows: list, closes: list, period: int = ADX_PERIOD) -> dict:
    """Wilder's ADX/+DI/-DI. Returns {"plus_di", "minus_di", "adx"},
    each a list the same length as `highs`, front-padded with None:
    index 0 has no prior bar for a directional move, and the smoothing
    itself needs `period` warm-up bars before either +DI/-DI or ADX has
    a first real value."""
    n = len(highs)
    if n < 2:
        return {"plus_di": [None] * n, "minus_di": [None] * n, "adx": [None] * n}

    plus_dm, minus_dm, tr = [], [], []
    for i in range(1, n):
        up = highs[i] - highs[i - 1]
        down = lows[i - 1] - lows[i]
        plus_dm.append(up if (up > down and up > 0) else 0.0)
        minus_dm.append(down if (down > up and down > 0) else 0.0)
        tr.append(max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]), abs(lows[i] - closes[i - 1])))

    sm_plus = _wilder_smooth(plus_dm, period)
    sm_minus = _wilder_smooth(minus_dm, period)
    sm_tr = _wilder_smooth(tr, period)

    plus_di, minus_di, dx = [None], [None], [None]  # index 0 placeholder, see docstring
    for spd, smd, str_ in zip(sm_plus, sm_minus, sm_tr):
        if spd is None or str_ is None or str_ == 0:
            plus_di.append(None)
            minus_di.append(None)
            dx.append(None)
            continue
        pdi = 100 * spd / str_
        mdi = 100 * smd / str_
        plus_di.append(pdi)
        minus_di.append(mdi)
        denom = pdi + mdi
        dx.append(100 * abs(pdi - mdi) / denom if denom else 0.0)

    adx = [None] * len(dx)
    valid_start = next((i for i, v in enumerate(dx) if v is not None), None)
    if valid_start is not None and len(dx) - valid_start >= period:
        first = sum(v for v in dx[valid_start:valid_start + period]) / period
        adx[valid_start + period - 1] = first
        prev = first
        for i in range(valid_start + period, len(dx)):
            prev = (prev * (period - 1) + dx[i]) / period
            adx[i] = prev

    return {"plus_di": plus_di, "minus_di": minus_di, "adx": adx}


def adx_observation(daily_bars: list, period: int = ADX_PERIOD) -> dict | None:
    highs = [b.get("high") for b in daily_bars]
    lows = [b.get("low") for b in daily_bars]
    closes = [b.get("close") for b in daily_bars]
    series = adx_dmi_series(highs, lows, closes, period)
    if not series["adx"] or series["adx"][-1] is None:
        return None
    plus_di, minus_di, adx = series["plus_di"][-1], series["minus_di"][-1], series["adx"][-1]
    prev_adx = series["adx"][-2] if len(series["adx"]) > 1 else None
    return {
        "adx": round(adx, 2),
        "plus_di": round(plus_di, 2),
        "minus_di": round(minus_di, 2),
        "trend": "bullish" if plus_di >= minus_di else "bearish",
        "strong_trend": adx >= 20,  # Wilder's own stated reading: ADX above 20 marks a genuine trend
        "rising": None if prev_adx is None else adx > prev_adx,
    }


def _donchian_mid(highs: list, lows: list, period: int) -> list:
    out = []
    for i in range(len(highs)):
        if i + 1 < period:
            out.append(None)
            continue
        hw, lw = highs[i + 1 - period:i + 1], lows[i + 1 - period:i + 1]
        out.append((max(hw) + min(lw)) / 2.0)
    return out


def ichimoku_observation(daily_bars: list) -> dict | None:
    """'Current cloud' is the cloud visible AT TODAY'S position on a
    real chart -- Senkou Span A/B are plotted `ICHIMOKU_KIJUN` periods
    FORWARD of the bar they're computed from, so what's drawn over
    today's candle was actually computed `ICHIMOKU_KIJUN` bars ago.
    'Future cloud' is what will appear over the next `ICHIMOKU_KIJUN`
    days -- computed from TODAY's data, not yet shifted."""
    highs = [b.get("high") for b in daily_bars]
    lows = [b.get("low") for b in daily_bars]
    closes = [b.get("close") for b in daily_bars]
    n = len(highs)
    if n < ICHIMOKU_SENKOU_B + ICHIMOKU_KIJUN:
        return None

    senkou_a_raw = [None if t is None or k is None else (t + k) / 2.0
                     for t, k in zip(_donchian_mid(highs, lows, ICHIMOKU_TENKAN), _donchian_mid(highs, lows, ICHIMOKU_KIJUN))]
    senkou_b_raw = _donchian_mid(highs, lows, ICHIMOKU_SENKOU_B)

    current_idx = n - 1 - ICHIMOKU_KIJUN
    if current_idx < 0:
        return None
    curr_a, curr_b = senkou_a_raw[current_idx], senkou_b_raw[current_idx]
    fut_a, fut_b = senkou_a_raw[-1], senkou_b_raw[-1]
    if curr_a is None or curr_b is None or fut_a is None or fut_b is None:
        return None

    price = closes[-1]
    cloud_top, cloud_bottom = max(curr_a, curr_b), min(curr_a, curr_b)
    price_vs_cloud = "above" if price > cloud_top else "below" if price < cloud_bottom else "inside"
    cloud_mid = (curr_a + curr_b) / 2.0
    fut_mid = (fut_a + fut_b) / 2.0

    return {
        "price_vs_cloud": price_vs_cloud,
        "cloud_bias": "bullish" if curr_a >= curr_b else "bearish",
        "current_cloud_range_pct": round(abs(curr_a - curr_b) / cloud_mid * 100, 2) if cloud_mid else None,
        "future_cloud_range_pct": round(abs(fut_a - fut_b) / fut_mid * 100, 2) if fut_mid else None,
    }


def directional_observations(daily_bars: list) -> dict:
    """bars: daily OHLC, sorted oldest -> newest. Both sub-sections null
    when there isn't enough history yet (ADX needs 2*period bars to
    warm up cleanly; Ichimoku needs senkou_b_period + kijun_period)."""
    bars = daily_bars or []
    return {
        "adx": adx_observation(bars),
        "ichimoku": ichimoku_observation(bars),
    }
