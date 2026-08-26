"""
Black Box strategy "Premium Band Strangle" -- pure signal logic. Public
name for the sourcing deck's "RK Strangle & Its Adjustment" (DECNOCH 2023,
R.K. Gupta); per this codebase's naming convention, the public name and
internal identifiers never carry the presenter's name.

Method, from the deck (explicitly "No Reading Charts/Indicators", "No
Options Greeks" -- the one Black Box strategy in this family that needs
neither Black-76 pricing nor a chart, only live option premiums):
  Entry: sell the NIFTY CE and PE (next-month expiry) whose live premium
  sits closest to a target band (deck's own worked example: Rs 60-70).
  Roll: if a leg's own profit exceeds `profit_shift_rupees`, close it and
  re-sell a new strike back in the target band (locks in profit, keeps the
  position "fresh").
  Adjust: if a leg's premium is about to double (>= `double_trigger_ratio`
  x its entry premium) OR its running loss exceeds `loss_trigger_rupees`,
  close that leg and re-sell a new strike back in the target band (caps
  further loss on that side).

NOT reproduced (flagged, not silently dropped): the deck's worked example
also shows adding a SECOND leg on the losing side at a ratio to fully
offset the premium collected, rather than a flat roll -- a more elaborate
adjustment the deck presents only through one annotated example, not as a
general rule with its own numbers. This module implements the three
CONCRETELY stated triggers above as a close-and-reopen roll, which is the
safe, unambiguous subset of what was actually specified.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class PremiumBandStrangleConfig:
    band_lo: float = 60.0
    band_hi: float = 70.0
    profit_shift_rupees: float = 1000.0
    loss_trigger_rupees: float = 3500.0
    double_trigger_ratio: float = 2.0


DEFAULT_CONFIG = PremiumBandStrangleConfig()


def select_strike(candidates: list, cfg: PremiumBandStrangleConfig = DEFAULT_CONFIG) -> dict | None:
    """`candidates`: [{"strike": int, "premium": float, "token": str}, ...]
    for one option side (CE or PE), same expiry. Picks whichever premium
    is closest to the BAND MIDPOINT among those inside [band_lo, band_hi];
    if none land inside the band, picks the closest premium to the band
    overall (deck shows the band as a target, not a hard reject -- a
    monthly chain is coarse enough that an exact in-band strike won't
    always exist)."""
    if not candidates:
        return None
    mid = (cfg.band_lo + cfg.band_hi) / 2.0
    in_band = [c for c in candidates if cfg.band_lo <= c["premium"] <= cfg.band_hi]
    pool = in_band if in_band else candidates
    return min(pool, key=lambda c: abs(c["premium"] - mid))


def check_leg_action(entry_premium: float, current_premium: float, current_pnl_rupees: float,
                      cfg: PremiumBandStrangleConfig = DEFAULT_CONFIG) -> dict | None:
    """Evaluates ONE short leg. `current_pnl_rupees` is positive for a
    profitable short (premium has fallen), negative for a loss (premium
    has risen) -- matches how the deck itself narrates P&L on a short
    strangle leg. Returns a roll instruction or None to hold."""
    if current_pnl_rupees >= cfg.profit_shift_rupees:
        return {"action": "roll", "reason": "profit_shift", "pnl": current_pnl_rupees}
    if current_premium >= cfg.double_trigger_ratio * entry_premium:
        return {"action": "roll", "reason": "premium_doubling", "pnl": current_pnl_rupees}
    if current_pnl_rupees <= -cfg.loss_trigger_rupees:
        return {"action": "roll", "reason": "loss_trigger", "pnl": current_pnl_rupees}
    return None
