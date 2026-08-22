"""Regression tests for options_analytics.py's pure compute functions."""
import random

from options_analytics import (
    max_pain, put_call_ratio, atm_iv, realized_vol_series, iv_rank_and_percentile,
)


def test_max_pain_picks_lowest_aggregate_payout():
    # All OI concentrated at 110 on both sides — 110 must be the max pain
    # strike since it's the only level with zero payout to itself.
    strikes = {
        100: {"ce": {"oi": 5}, "pe": {"oi": 5}},
        110: {"ce": {"oi": 1000}, "pe": {"oi": 1000}},
        120: {"ce": {"oi": 5}, "pe": {"oi": 5}},
    }
    result = max_pain(strikes)
    assert result["strike"] == 110


def test_max_pain_none_when_no_oi():
    strikes = {100: {"ce": {"oi": 0}, "pe": {"oi": 0}}}
    assert max_pain(strikes) is None


def test_put_call_ratio_basic():
    strikes = {
        100: {"ce": {"oi": 100}, "pe": {"oi": 300}},
        110: {"ce": {"oi": 100}, "pe": {"oi": 100}},
    }
    assert put_call_ratio(strikes) == 2.0  # 400 puts / 200 calls


def test_put_call_ratio_none_when_no_calls():
    strikes = {100: {"ce": {"oi": 0}, "pe": {"oi": 50}}}
    assert put_call_ratio(strikes) is None


def test_atm_iv_averages_nearest_strike():
    strikes = {
        100: {"ce": {"iv": 0.20}, "pe": {"iv": 0.20}},
        110: {"ce": {"iv": 0.10}, "pe": {"iv": 0.14}},
    }
    assert round(atm_iv(strikes, 111), 4) == 0.12


def test_atm_iv_uses_whichever_side_has_a_reading():
    strikes = {100: {"ce": {"iv": None}, "pe": {"iv": 0.18}}}
    assert atm_iv(strikes, 100) == 0.18


def test_iv_rank_above_historical_high():
    # current_iv strictly above every historical reading -> both figures
    # clamp/cap at 100 rather than exceeding it.
    history = [0.10, 0.12, 0.14]
    result = iv_rank_and_percentile(0.15, history)
    assert result["iv_rank"] == 100.0
    assert result["iv_percentile"] == 100.0


def test_iv_rank_none_without_history():
    result = iv_rank_and_percentile(0.15, [])
    assert result["iv_rank"] is None
    assert result["iv_percentile"] is None


def test_realized_vol_series_needs_window_plus_one_closes():
    closes = [100.0] * 15  # fewer than window(20)+1 -> no readings possible
    assert realized_vol_series(closes, window=20) == []


def test_realized_vol_series_length_matches_available_days():
    random.seed(7)
    closes = [100.0]
    for _ in range(60):
        closes.append(closes[-1] * (1 + random.uniform(-0.01, 0.01)))
    series = realized_vol_series(closes, window=20)
    # one reading per day once `window` prior closes exist
    assert len(series) == len(closes) - 20
    assert all(v > 0 for v in series)


def test_realized_vol_series_flags_a_choppier_window_as_higher_vol():
    calm = [100.0]
    for _ in range(30):
        calm.append(calm[-1] * 1.001)  # smooth, steady drift
    choppy = [100.0]
    random.seed(3)
    for _ in range(30):
        choppy.append(choppy[-1] * (1 + random.choice([-0.03, 0.03])))  # wide daily swings

    calm_vol = realized_vol_series(calm, window=20)[-1]
    choppy_vol = realized_vol_series(choppy, window=20)[-1]
    assert choppy_vol > calm_vol


def test_iv_rank_against_realized_vol_history_end_to_end():
    """The actual pipeline the route uses: build a realized-vol history
    from closes, then rank a live IV reading against it."""
    random.seed(11)
    closes = [100.0]
    for _ in range(300):
        closes.append(closes[-1] * (1 + random.uniform(-0.01, 0.01)))
    history = realized_vol_series(closes, window=20)
    assert len(history) > 0

    very_high_iv = max(history) + 0.5
    result = iv_rank_and_percentile(very_high_iv, history)
    assert result["iv_rank"] == 100.0
    assert result["history_days"] == len(history)
