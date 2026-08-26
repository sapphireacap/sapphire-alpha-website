"""
Premium Band Strangle parameters live here -- nothing hardcoded in the
strategy logic itself. Every value in DEFAULT_CONFIG is a STARTING VALUE,
not a validated one (per explicit instruction).

get_config(db, index) reads one doc per index from `blackbox_config`
(Nifty and Bank Nifty will NOT share optimal values, per explicit
instruction, so they're never merged into one global config), seeding it
from DEFAULT_CONFIG on first read if no override exists yet.

Convexity Window and Gamma Backspread's config blocks (iv_rv_ratio_max,
theta_band, etc.) plus the risk_free_rate/costs fields only they needed
were removed entirely on 2026-08-26, code and production data both, per
explicit instruction -- see git history if either is ever wanted back.
"""
import copy

DEFAULT_CONFIG = {
    # NOT available from Definedge's master file (checked live: no lot-size
    # column on OPTIDX rows) and NSE lot sizes change periodically via
    # circular -- never guessed. MUST be confirmed/set per index before
    # Phase 2 paper trading starts; None here is a deliberate loud gap, not
    # a silent wrong default.
    "lot_size": None,

    # Premium Band Strangle -- deliberately has NO iv/greeks/ema keys: the
    # source strategy is explicitly "No Greeks, No Indicators" (see
    # blackbox_premium_band_strangle.py), so its config is just the
    # premium band + adjustment thresholds.
    "premium_band_strangle": {
        "band_lo": 60.0,
        "band_hi": 70.0,
        "profit_shift_rupees": 1000.0,
        "loss_trigger_rupees": 3500.0,
        "double_trigger_ratio": 2.0,
        "dte_min": 20,   # monthly expiry, per the source deck
        "dte_max": 35,
        "strike_range_from_atm": 15,  # wide enough to find a Rs 60-70 premium strike most months
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
    {"premium_band_strangle": {...full sub-dict...}}) -- used by the admin
    panel once real calibrated values are chosen. Never touches other
    indices' docs."""
    existing = await get_config(db, index)
    for key, value in updates.items():
        if isinstance(value, dict) and isinstance(existing.get(key), dict):
            existing[key].update(value)
        else:
            existing[key] = value
    await db.blackbox_config.update_one({"index": index}, {"$set": existing}, upsert=True)
    return existing
