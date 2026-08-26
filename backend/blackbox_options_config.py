"""
All Convexity Window / Gamma Backspread parameters live here -- nothing
hardcoded in the strategy logic itself. Every value in DEFAULT_CONFIG is a
STARTING VALUE, not a validated one (per explicit instruction) -- Phase 1's
backtest parameter sweep is what actually calibrates these before anything
goes live or even into paper trading.

get_config(db, index) reads one doc per index from `blackbox_config`
(Nifty and Bank Nifty will NOT share optimal values, per explicit
instruction, so they're never merged into one global config), seeding it
from DEFAULT_CONFIG on first read if no override exists yet. The backtest
harness bypasses this and passes its own swept parameter dicts directly to
the signal functions instead -- this loader is for the live/paper path only.
"""
import copy

DEFAULT_CONFIG = {
    "risk_free_rate": 0.065,
    # NOT available from Definedge's master file (checked live: no lot-size
    # column on OPTIDX rows) and NSE lot sizes change periodically via
    # circular -- never guessed. MUST be confirmed/set per index before
    # Phase 2 paper trading starts; None here is a deliberate loud gap, not
    # a silent wrong default.
    "lot_size": None,

    "convexity_window": {
        "entry_time_ist": "09:30",
        "time_stop_ist": "15:15",
        "iv_rv_ratio_max": 0.95,
        "realized_vol_window_days": 20,
        "required_move_multiplier": 0.8,
        "true_range_window_days": 20,
        "strike_range_from_atm": 2,
        "dte_min": 1,
        "dte_max": 4,
        "vega_cap": 50.0,          # rupee vega per lot -- starting guess, untested
        "ema_period_15m": 20,
        "sl_pct": -0.35,
        "target_pct": 0.70,
        "gamma_stop_ratio": 0.50,  # exit if position gamma falls below this fraction of entry gamma
    },

    # Premium Band Strangle -- deliberately has NO iv/greeks/ema keys, unlike
    # the two strategies above: the source strategy is explicitly "No
    # Greeks, No Indicators" (see blackbox_premium_band_strangle.py), so its
    # config is just the premium band + adjustment thresholds.
    "premium_band_strangle": {
        "band_lo": 60.0,
        "band_hi": 70.0,
        "profit_shift_rupees": 1000.0,
        "loss_trigger_rupees": 3500.0,
        "double_trigger_ratio": 2.0,
        "dte_min": 20,   # monthly expiry, per the source deck (not weekly like the other two)
        "dte_max": 35,
        "strike_range_from_atm": 15,  # wide enough to find a Rs 60-70 premium strike most months
    },

    "gamma_backspread": {
        "iv_percentile_window_days": 252,
        "iv_percentile_entry_max": 30,
        "theta_band_lo": -0.05,
        "theta_band_hi": 0.05,
        "otm_strike_search_range": 10,  # how many strikes out (each direction) to search for a theta-neutral OTM leg
        "dte_min": 5,
        "dte_max": 12,
        "theta_exit_threshold": -0.15,
        "dte_exit": 2,
        "target_pct": 0.40,
        "sl_pct": -0.25,
        "iv_percentile_exit": 60,
        "ema_period_15m": 20,
    },

    "costs": {
        "brokerage_per_lot": 20.0,     # flat per order, starting assumption
        "stt_sell_pct": 0.001,         # STT on the sell side only (options), starting assumption
        "exchange_txn_pct": 0.00053,   # NSE F&O transaction charge, starting assumption
        "gst_pct": 0.18,               # on (brokerage + exchange txn)
        "sebi_fee_pct": 0.0000010,
        # Deliberately conservative per explicit instruction ("option
        # buying P&L is highly sensitive to slippage") -- applied per leg.
        "slippage_pct": 0.02,
    },
}


def default_config_for(index: str) -> dict:
    cfg = copy.deepcopy(DEFAULT_CONFIG)
    cfg["index"] = index
    return cfg


async def get_config(db, index: str) -> dict:
    doc = await db.blackbox_config.find_one({"index": index}, {"_id": 0})
    if doc:
        # A doc written before a new strategy was added (e.g.
        # "premium_band_strangle", 2026-08-26) won't have that top-level
        # key yet -- backfill it from DEFAULT_CONFIG rather than letting
        # every reader KeyError on a real, pre-existing production doc.
        missing = {k: v for k, v in DEFAULT_CONFIG.items() if k not in doc}
        if missing:
            doc.update(copy.deepcopy(missing))
            await db.blackbox_config.update_one({"index": index}, {"$set": missing})
        return doc
    cfg = default_config_for(index)
    await db.blackbox_config.insert_one(dict(cfg))
    return cfg


async def set_config(db, index: str, updates: dict) -> dict:
    """Shallow-merges `updates` into the stored config for one index (e.g.
    {"convexity_window": {...full sub-dict...}}) -- used by the admin panel
    once real calibrated values are chosen, and by the backtest harness's
    recommended-parameter-set output. Never touches other indices' docs."""
    existing = await get_config(db, index)
    for key, value in updates.items():
        if isinstance(value, dict) and isinstance(existing.get(key), dict):
            existing[key].update(value)
        else:
            existing[key] = value
    await db.blackbox_config.update_one({"index": index}, {"$set": existing}, upsert=True)
    return existing
