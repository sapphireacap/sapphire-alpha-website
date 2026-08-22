"""Regression tests for intraday_momentum.py's pure compute functions."""
from intraday_momentum import (
    return_pct, volatility_pct, volar_score, retracement_pct,
    passes_ema_filter, relative_series, scan_symbol,
)


def test_return_pct_basic():
    closes = [100, 101, 102, 103, 104, 105]
    assert round(return_pct(closes, 5), 2) == 5.0


def test_return_pct_none_without_enough_bars():
    assert return_pct([100, 101], 5) is None


def test_volatility_pct_smooth_vs_choppy():
    smooth = [100 + i * 0.5 for i in range(21)]  # steady drift
    choppy = [100, 103, 98, 104, 97, 105, 96, 106, 95, 107, 94, 108, 93,
              109, 92, 110, 91, 111, 90, 112, 89]
    smooth_vol = volatility_pct(smooth, 20)
    choppy_vol = volatility_pct(choppy, 20)
    assert smooth_vol is not None and choppy_vol is not None
    assert choppy_vol > smooth_vol


def test_volar_score_matches_return_over_volatility():
    assert round(volar_score(10.0, 2.0), 3) == 5.0


def test_volar_score_none_on_zero_volatility():
    assert volar_score(5.0, 0.0) is None


def test_retracement_pct_zero_at_period_high():
    closes = [100, 102, 104, 106, 108, 110]  # strictly rising, latest IS the high
    assert retracement_pct(closes, 5) == 0.0


def test_retracement_pct_measures_pullback_from_high():
    closes = [100, 110, 105]  # high of 110, pulled back to 105
    result = retracement_pct(closes, 2)
    assert round(result, 2) == round((110 - 105) / 110 * 100, 2)


def test_passes_ema_filter_true_when_above_all_selected_emas():
    closes = [100 + i for i in range(30)]  # steady uptrend, latest above any EMA
    assert passes_ema_filter(closes, [10, 20]) is True


def test_passes_ema_filter_false_when_below_an_ema():
    closes = [130 - i for i in range(30)]  # steady downtrend, latest below any EMA
    assert passes_ema_filter(closes, [10]) is False


def test_passes_ema_filter_true_with_no_emas_selected():
    assert passes_ema_filter([100, 99, 98], []) is True


def test_relative_series_divides_elementwise():
    stock = [110, 121, 132]
    denom = [100, 110, 120]
    result = relative_series(stock, denom)
    assert result == [1.1, 1.1, 1.1]


def test_relative_series_aligns_from_the_end_on_length_mismatch():
    stock = [1, 2, 3, 4]
    denom = [10, 20, 30]  # one bar shorter — align from the end
    result = relative_series(stock, denom)
    assert result == [2 / 10, 3 / 20, 4 / 30]


def test_scan_symbol_absolute_mode():
    closes = [100 + i for i in range(10)]
    result = scan_symbol(closes, period=5, ema_periods=[])
    assert result is not None
    assert result["return_pct"] > 0
    assert result["ema_pass"] is True


def test_scan_symbol_none_without_enough_history():
    assert scan_symbol([100, 101], period=20, ema_periods=[]) is None


def test_scan_symbol_relative_mode_uses_ratio_series():
    stock = [100 + i * 2 for i in range(10)]   # outperforming
    denom = [100 + i for i in range(10)]        # baseline
    absolute = scan_symbol(stock, period=5, ema_periods=[])
    relative = scan_symbol(stock, period=5, ema_periods=[], relative_closes=denom)
    assert absolute["return_pct"] != relative["return_pct"]
