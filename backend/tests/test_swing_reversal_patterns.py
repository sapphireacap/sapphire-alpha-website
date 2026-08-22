"""Regression tests for swing_reversal_patterns.py — hand-constructed
cases confirming each detector fires (and stays silent) exactly per the
rules documented in that module's docstring."""
from swing_reversal_patterns import (
    to_bars, find_swings, detect_swing_reversal, detect_momentum_reversal,
    detect_trapped_move, detect_weekly_breakout,
)


def _decline_then_bounce_then_decline(start=100):
    """Builds: decline -> bounce (forms a fractal swing low) -> decline
    again below that swing low - the shared setup several tests build on."""
    raw = []
    price = start
    for i in range(6):
        raw.append({"date": f"d{i}", "open": price + 1, "high": price + 2, "low": price - 1, "close": price})
        price -= 2
    for i in range(4):
        price += 2
        raw.append({"date": f"d{6+i}", "open": price - 1, "high": price + 1, "low": price - 2, "close": price})
    for i in range(4):
        price -= 2
        raw.append({"date": f"d{10+i}", "open": price + 1, "high": price + 1.5, "low": price - 1, "close": price})
    return raw, price


def test_swing_reversal_bullish_fires():
    raw, price = _decline_then_bounce_then_decline()
    prev_low = price - 4
    raw.append({"date": "dprev", "open": price + 1, "high": price + 1.2, "low": prev_low, "close": prev_low + 0.2})
    prev_open, prev_close = raw[-1]["open"], raw[-1]["close"]
    raw.append({"date": "dcur", "open": prev_low - 0.5, "high": prev_open + 2, "low": prev_low - 2, "close": prev_open + 1})

    bars = to_bars(raw)
    swings = find_swings(bars)
    sig = detect_swing_reversal(bars, swings, len(bars) - 1)
    assert sig is not None
    assert sig.bias == "bullish"
    assert sig.key == "swing_reversal"


def test_swing_reversal_silent_without_prior_swing_low():
    """A pure monotonic decline has no interior fractal turning point -
    the pattern must not fire without an established swing low to
    compare against (this was caught during manual verification: a
    strictly monotonic decline produced no swing point at all)."""
    raw = []
    price = 100
    for i in range(10):
        raw.append({"date": f"d{i}", "open": price + 1, "high": price + 2, "low": price - 1, "close": price})
        price -= 2
    raw.append({"date": "d10", "open": price + 2, "high": price + 2.2, "low": price - 3, "close": price - 2.8})
    prev_close, prev_open = raw[-1]["close"], raw[-1]["open"]
    raw.append({"date": "d11", "open": prev_close - 1, "high": prev_open + 3, "low": prev_close - 5, "close": prev_open + 1})

    bars = to_bars(raw)
    swings = find_swings(bars)
    assert detect_swing_reversal(bars, swings, len(bars) - 1) is None


def test_momentum_reversal_bullish_fires():
    raw = [
        {"date": "d0", "open": 101, "high": 102, "low": 99, "close": 100},
        {"date": "d1", "open": 100, "high": 100.5, "low": 96, "close": 96.5},
    ]
    bars = to_bars(raw)
    sig = detect_momentum_reversal(bars, 1)
    assert sig is None  # 96.5 isn't > prev.close(100) + step - not a reversal yet

    raw[1]["close"] = 101.5  # now clears prev.close + ~0.75% step
    bars = to_bars(raw)
    sig = detect_momentum_reversal(bars, 1)
    assert sig is not None
    assert sig.bias == "bullish"


def test_trapped_move_bullish_fires():
    raw, price = _decline_then_bounce_then_decline()
    prev_low = price - 4
    raw.append({"date": "dprev", "open": prev_low + 3, "high": prev_low + 3.2, "low": prev_low, "close": prev_low + 0.5})
    prev_close = raw[-1]["close"]
    raw.append({"date": "dcur", "open": prev_low + 0.1, "high": prev_close + 3, "low": prev_low - 0.2, "close": prev_close + 1})

    bars = to_bars(raw)
    swings = find_swings(bars)
    sig = detect_trapped_move(bars, swings, len(bars) - 1)
    assert sig is not None
    assert sig.bias == "bullish"


def test_weekly_breakout_bullish_fires():
    raw = [
        {"date": "w0", "open": 100, "high": 105, "low": 95, "close": 102},
        {"date": "w1", "open": 102, "high": 103, "low": 90, "close": 92},
        {"date": "w2", "open": 92, "high": 106, "low": 91, "close": 105},
    ]
    bars = to_bars(raw)
    sig = detect_weekly_breakout(bars, 2)
    assert sig is not None
    assert sig.bias == "bullish"


def test_weekly_breakout_silent_when_previous_week_not_bearish():
    raw = [
        {"date": "w0", "open": 100, "high": 105, "low": 95, "close": 102},
        {"date": "w1", "open": 92, "high": 103, "low": 90, "close": 102},  # bullish, not bearish
        {"date": "w2", "open": 102, "high": 106, "low": 101, "close": 105},
    ]
    bars = to_bars(raw)
    assert detect_weekly_breakout(bars, 2) is None
