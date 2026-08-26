"""
Config for Black Box's three equity/cash-market strategies (Structural
Retest, Trend Ignition, Volume Cascade) -- same "nothing hardcoded in the
strategy logic, everything a starting value pending calibration" discipline
as blackbox_options_config.py, but per-STRATEGY rather than per-index (the
options strategies run one NIFTY/BANKNIFTY position at a time; these run
across a whole stock universe, where index-level segmentation doesn't
apply).
"""
import copy

from blackbox_structural_retest import StructuralRetestConfig
from blackbox_trend_ignition import TrendIgnitionConfig
from blackbox_volume_cascade import VolumeCascadeConfig

# Universe each strategy scans -- see blackbox_equity_market.py for the
# actual NSE index-constituent CSV each key maps to. Structural Retest is
# scoped to NIFTY 50 (Datta's own deck: "Bullish Pattern Retest on NIFTY 50
# names"); Volume Cascade to NIFTY 500 (Kumar's deck: "NF500/BSE500
# universe"); Trend Ignition's deck doesn't specify a universe, so it uses
# the same broad NIFTY 500 list.
UNIVERSE = {
    "structural_retest": "nifty50",
    "trend_ignition": "nifty500",
    "volume_cascade": "nifty500",
}

DEFAULT_CONFIG = {
    "structural_retest": {
        "box_pct": StructuralRetestConfig().box_pct,
        "reversal_boxes": StructuralRetestConfig().reversal_boxes,
        "breadth_bullish_max": StructuralRetestConfig().breadth_bullish_max,
        "breadth_bearish_min": StructuralRetestConfig().breadth_bearish_min,
    },
    "trend_ignition": {
        "ema_fast": TrendIgnitionConfig().ema_fast,
        "ema_slow": TrendIgnitionConfig().ema_slow,
        "rsi_period": TrendIgnitionConfig().rsi_period,
        "rsi_bullish_min": TrendIgnitionConfig().rsi_bullish_min,
        "rsi_bearish_max": TrendIgnitionConfig().rsi_bearish_max,
        "adx_period": TrendIgnitionConfig().adx_period,
        "adx_min": TrendIgnitionConfig().adx_min,
        "lookback_bars": TrendIgnitionConfig().lookback_bars,
        "high_body_ratio": TrendIgnitionConfig().high_body_ratio,
        "stop_pct": TrendIgnitionConfig().stop_pct,
    },
    "volume_cascade": {
        "volume_avg_days": VolumeCascadeConfig().volume_avg_days,
        "volume_multiplier": VolumeCascadeConfig().volume_multiplier,
        "rs_box_pct": VolumeCascadeConfig().rs_box_pct,
        "price_box_pct": VolumeCascadeConfig().price_box_pct,
        "reversal_boxes": VolumeCascadeConfig().reversal_boxes,
        "ma_period_columns": VolumeCascadeConfig().ma_period_columns,
        "stop_pct": VolumeCascadeConfig().stop_pct,
        "booking_r_multiple": VolumeCascadeConfig().booking_r_multiple,
        "booking_fraction": VolumeCascadeConfig().booking_fraction,
    },
}


def default_config_for(strategy_id: str) -> dict:
    return copy.deepcopy(DEFAULT_CONFIG[strategy_id])


async def get_config(db, strategy_id: str) -> dict:
    doc = await db.blackbox_equity_config.find_one({"strategy_id": strategy_id}, {"_id": 0})
    if doc:
        return doc["config"]
    cfg = default_config_for(strategy_id)
    await db.blackbox_equity_config.insert_one({"strategy_id": strategy_id, "config": cfg})
    return cfg


async def set_config(db, strategy_id: str, updates: dict) -> dict:
    existing = await get_config(db, strategy_id)
    existing.update(updates)
    await db.blackbox_equity_config.update_one(
        {"strategy_id": strategy_id}, {"$set": {"config": existing}}, upsert=True,
    )
    return existing


def structural_retest_cfg(cfg: dict) -> StructuralRetestConfig:
    return StructuralRetestConfig(**cfg)


def trend_ignition_cfg(cfg: dict) -> TrendIgnitionConfig:
    return TrendIgnitionConfig(**cfg)


def volume_cascade_cfg(cfg: dict) -> VolumeCascadeConfig:
    return VolumeCascadeConfig(**cfg)
