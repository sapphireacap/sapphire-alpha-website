"""
Black Box strategy "Trend Ignition" -- pure signal logic. Public name for
the sourcing deck's "Intraday Momentum Scanner" (DECNOCH 2023, D.T. Bhat) --
renamed for Black Box to avoid colliding with this site's own, unrelated
Alpha Terminal module of the same generic name (VOLAR-based), and per this
codebase's convention of never carrying a presenter's name into a public
strategy name.

Method, from the deck: a candle-based momentum checklist run on DAILY bars
(the deck's own scanner is intraday; this Black Box build runs it EOD --
see the module docstring below for why that's a deliberate scope decision,
not a silent narrowing):
  Bullish -- EMA(8) > EMA(34) and EMA(8) rising; today's close is the
  highest of the last 5 closes; RSI(14) > 60; today's volume is the
  highest of the last 5; today's candle is green with a "high body"
  (large real body relative to its range); ADX(14) > 25.
  Bearish is the mirror image (RSI < 45, lowest close/volume of 5, red
  high-body candle).

CADENCE DECISION (flagged, not silently assumed): the source deck runs
this scanner intraday against live candles. Black Box's other new equity
strategies (Structural Retest, Volume Cascade) are naturally EOD-cadence
(P&F/box charts don't need intraday ticks), and this codebase's dominant
automation pattern for scanning a broad universe is EOD, not per-minute
(see server.py's EOD_REFRESH_TARGETS). Running Trend Ignition once daily
on daily bars, rather than every N minutes on a live candle, is the
scope this build implements -- a genuinely intraday version would need
its own minute-bar cadence and cost, and is a separate, later decision.

EXIT RULE (flagged): the deck says only "I use P&F charts for
entry/exit/TSL" and "book 50% at 1:1, then 1:1.5, then 1:2 R:R" without
giving the P&F setup it uses for that management. Rather than guess which
P&F pattern the presenter meant, this module implements the concretely
stated part only -- partial booking at fixed R:R multiples with a hard
stop -- documented here as this build's own substitution for "P&F
managed", not attributed to the deck.
"""
from __future__ import annotations

from dataclasses import dataclass

from pnf_indicators import ema
from technical_observations import rsi_series
from directional_observations import adx_dmi_series


@dataclass
class TrendIgnitionConfig:
    ema_fast: int = 8
    ema_slow: int = 34
    rsi_period: int = 14
    rsi_bullish_min: float = 60.0
    rsi_bearish_max: float = 45.0
    adx_period: int = 14
    adx_min: float = 25.0
    lookback_bars: int = 5          # "highest/lowest of the last 5" per the deck
    high_body_ratio: float = 0.6    # |close-open| / (high-low) -- this build's own
                                     # numeric definition of "high body candle",
                                     # since the deck names the concept but never
                                     # gives a threshold (flagged in module docstring)
    stop_pct: float = 0.03          # hard stop -- this build's substitution for the
                                     # deck's undefined "individual risk plan" (flagged above)
    rr_targets: tuple = (1.0, 1.5, 2.0)   # partial-booking R:R ladder, per the deck
    rr_booking_pct: tuple = (0.5, 0.25, 0.25)  # fraction of the position booked at each rung


DEFAULT_CONFIG = TrendIgnitionConfig()


def _is_high_body(bar: dict, cfg: TrendIgnitionConfig) -> bool:
    rng = bar["high"] - bar["low"]
    if rng <= 0:
        return False
    return abs(bar["close"] - bar["open"]) / rng >= cfg.high_body_ratio


def check_entry(daily_bars: list, cfg: TrendIgnitionConfig = DEFAULT_CONFIG) -> dict | None:
    """`daily_bars`: oldest -> newest dicts with open/high/low/close/volume
    (definedge_service.daily_history's shape). Returns an entry dict for
    the LATEST bar only, or None if any condition in the checklist fails
    or there isn't enough history yet."""
    n = cfg.adx_period * 2  # ADX needs 2x its period to warm up cleanly
    if len(daily_bars) < max(n, cfg.ema_slow + 2, cfg.rsi_period + 2, cfg.lookback_bars + 1):
        return None
    if any(b.get("volume") is None for b in daily_bars[-cfg.lookback_bars:]):
        return None  # cached bars fetched before the volume fix (definedge_service.py, 2026-08-26) -- don't guess

    closes = [b["close"] for b in daily_bars]
    highs = [b["high"] for b in daily_bars]
    lows = [b["low"] for b in daily_bars]
    volumes = [b["volume"] for b in daily_bars]

    ema_fast_line = ema(closes, cfg.ema_fast)
    ema_slow_line = ema(closes, cfg.ema_slow)
    rsi_line = rsi_series(closes, cfg.rsi_period)
    adx = adx_dmi_series(highs, lows, closes, cfg.adx_period)

    if ema_fast_line[-1] is None or ema_slow_line[-1] is None or ema_fast_line[-2] is None:
        return None
    if rsi_line[-1] is None or adx["adx"][-1] is None:
        return None

    today = daily_bars[-1]
    recent_closes = closes[-cfg.lookback_bars:]
    recent_volumes = volumes[-cfg.lookback_bars:]
    fast_rising = ema_fast_line[-1] > ema_fast_line[-2]
    strong_trend = adx["adx"][-1] > cfg.adx_min
    high_body = _is_high_body(today, cfg)
    is_green = today["close"] > today["open"]
    is_red = today["close"] < today["open"]

    bullish = (
        ema_fast_line[-1] > ema_slow_line[-1] and fast_rising
        and today["close"] == max(recent_closes)
        and rsi_line[-1] > cfg.rsi_bullish_min
        and today["volume"] == max(recent_volumes)
        and strong_trend and is_green and high_body
    )
    bearish = (
        ema_fast_line[-1] < ema_slow_line[-1] and not fast_rising
        and today["close"] == min(recent_closes)
        and rsi_line[-1] < cfg.rsi_bearish_max
        and today["volume"] == max(recent_volumes)
        and strong_trend and is_red and high_body
    )

    if not bullish and not bearish:
        return None

    bias = "bullish" if bullish else "bearish"
    entry_price = today["close"]
    stop_price = entry_price * (1 - cfg.stop_pct) if bias == "bullish" else entry_price * (1 + cfg.stop_pct)
    return {
        "bias": bias, "entry_price": entry_price, "stop_price": stop_price,
        "rsi": round(rsi_line[-1], 2), "adx": round(adx["adx"][-1], 2),
    }


def check_exit(daily_bars: list, position: dict, cfg: TrendIgnitionConfig = DEFAULT_CONFIG) -> dict | None:
    """`position`: {"bias", "entry_price", "stop_price", "booked_rungs": int}.
    Returns {"action": "stop"|"partial"|"full", "exit_price", "rung": int}
    or None if the position should keep running unmanaged this bar.
    Stops and target rungs are checked against the day's high/low (a
    limit/stop order could realistically have filled intrabar), booking
    at the configured price, not an optimistic best-case fill."""
    today = daily_bars[-1]
    bias = position["bias"]
    entry = position["entry_price"]
    stop = position["stop_price"]
    rung = position.get("booked_rungs", 0)

    hit_stop = today["low"] <= stop if bias == "bullish" else today["high"] >= stop
    if hit_stop:
        return {"action": "stop", "exit_price": stop, "rung": rung}

    if rung >= len(cfg.rr_targets):
        return None
    risk = abs(entry - stop)
    target_r = cfg.rr_targets[rung]
    target_price = entry + risk * target_r if bias == "bullish" else entry - risk * target_r
    hit_target = today["high"] >= target_price if bias == "bullish" else today["low"] <= target_price
    if not hit_target:
        return None
    action = "full" if rung == len(cfg.rr_targets) - 1 else "partial"
    return {"action": action, "exit_price": target_price, "rung": rung + 1,
            "booked_fraction": cfg.rr_booking_pct[rung]}
