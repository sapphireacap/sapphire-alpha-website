"""
Index Vector flip levels — "at what spot level would this P&F leg's
premium cross its reversal threshold", using live Black-Scholes Greeks
(options_greeks.py) since Definedge's API doesn't expose Greeks/IV itself
(verified live: /quotes has no delta/gamma/theta/vega/iv field). This is a
sensitivity projection, not a price-direction forecast — it answers "at
what level", never "when" or "whether".

A straddle leg's premium is NOT monotonic in spot — it's single-troughed
at spot=strike (falls as spot approaches the strike from either side,
rises moving away in either direction), unlike a single CE/PE leg which
is monotonic. So a straddle can have two valid flip levels (one on each
side of the strike); a single leg has exactly one.
"""
import math
from datetime import date

from options_greeks import bs_price, implied_vol, spot_for_target_price, years_to_expiry, RISK_FREE_RATE

# No import of definedge_service here — compute_leg_flip() takes an
# already-computed pnf_column_state() result as a parameter instead of
# recomputing it, both to avoid definedge_service.py <-> index_vector_flip.py
# becoming a circular import (definedge_service.compute_vector() is the
# caller) and to avoid running the same P&F state machine twice per leg.


def _straddle_price(S: float, K: float, T: float, sigma_ce: float, sigma_pe: float, r: float = RISK_FREE_RATE) -> float:
    return bs_price(S, K, T, sigma_ce, "CE", r) + bs_price(S, K, T, sigma_pe, "PE", r)


def _straddle_flip_spots(target_price: float, K: float, T: float, sigma_ce: float, sigma_pe: float,
                          r: float = RISK_FREE_RATE, s_hi: float = 200000.0):
    """Both spot levels (below and above K) where the straddle premium
    equals target_price — None for a side if target_price is below the
    straddle's minimum possible value (at S=K), i.e. unreachable on that
    side. Bisection on each side independently, since the straddle is
    monotonic on each side of its single trough at S=K."""
    price_at_k = _straddle_price(K, K, T, sigma_ce, sigma_pe, r)
    if target_price < price_at_k:
        return None, None

    def solve(lo, hi, rising_with_s):
        for _ in range(100):
            mid = (lo + hi) / 2
            p = _straddle_price(mid, K, T, sigma_ce, sigma_pe, r)
            if abs(p - target_price) < 1e-4:
                return mid
            if (p < target_price) == rising_with_s:
                lo = mid
            else:
                hi = mid
        return (lo + hi) / 2

    lower_spot = solve(1.0, K, rising_with_s=False)   # price falls as S rises toward K on this side
    upper_spot = solve(K, s_hi, rising_with_s=True)    # price rises as S rises past K on this side
    return lower_spot, upper_spot


def compute_leg_flip(state: dict, current_spot: float, strike: float, expiry: date,
                      box_pct: float, reversal_boxes: int, is_straddle: bool,
                      ce_ltp: float = None, pe_ltp: float = None, option_type: str = None,
                      leg_ltp: float = None) -> dict:
    """state: the caller's own definedge_service.pnf_column_state(...)
    result for this leg (same series/box_pct/reversal_boxes it already
    used to derive the leg's trend label) — passed in rather than
    recomputed here, see the module-level note on why.
    For a straddle leg pass ce_ltp+pe_ltp (today's live legs, to back out
    each side's own IV); for a single CE/PE leg pass leg_ltp+option_type.

    Returns direction, the extreme/flip PREMIUM levels, and the resulting
    SPOT level(s) — `flip_spot` is the one nearest current_spot (the
    practically relevant one), `flip_spot_alt` the other side for a
    straddle (None for a single leg, which only ever has one root)."""
    if state["direction"] is None:
        return {"direction": None}

    scale = math.log(1.0 + box_pct)
    extreme_premium = state["extreme_price"]
    if state["direction"] == "up":
        flip_premium = extreme_premium * math.exp(-reversal_boxes * scale)
    else:
        flip_premium = extreme_premium * math.exp(reversal_boxes * scale)

    T = years_to_expiry(expiry)
    result = {
        "direction": state["direction"],
        "extreme_premium": extreme_premium,
        "flip_premium": flip_premium,
    }

    if is_straddle:
        iv_ce = implied_vol(ce_ltp, current_spot, strike, T, "CE")
        iv_pe = implied_vol(pe_ltp, current_spot, strike, T, "PE")
        lower, upper = _straddle_flip_spots(flip_premium, strike, T, iv_ce, iv_pe)
        result["iv_ce"], result["iv_pe"] = iv_ce, iv_pe
        if lower is None:
            result["flip_spot"] = None
            result["flip_spot_alt"] = None
        else:
            candidates = [c for c in (lower, upper) if c is not None]
            nearest = min(candidates, key=lambda c: abs(c - current_spot))
            other = [c for c in candidates if c != nearest]
            result["flip_spot"] = nearest
            result["flip_spot_alt"] = other[0] if other else None
    else:
        iv = implied_vol(leg_ltp, current_spot, strike, T, option_type)
        result["iv"] = iv
        result["flip_spot"] = spot_for_target_price(flip_premium, strike, T, iv, option_type)
        result["flip_spot_alt"] = None

    return result


# ---------------------------------------------------------------------------
# Index-level aggregation — "at what spot level does the WHOLE confluence
# complete", not just one leg. Mirrors derive_bias()/derive_bias_4()'s own
# per-leg direction requirements exactly (definedge_service.py) — do not
# let these two fall out of sync if the confluence rule ever changes.
# ---------------------------------------------------------------------------
NEEDED_DIRECTION_FOR_BULLISH = {
    "weekly_up": "down", "weekly_down": "up",
    "monthly_up": "down", "monthly_down": "up",
    "monthly_atm_ce": "up", "monthly_atm_pe": "down",
}


def index_flip_summary(leg_results: dict, spot: float) -> dict:
    """leg_results: {leg_name: compute_leg_flip() result}, already scoped
    to the 4 or 6 legs a given index actually has (chart_mode "4" indices
    have no weekly_* keys). Returns {"bullish": {...}, "bearish": {...}},
    each either a real flip level or an honest reason it's not reachable
    via spot movement alone right now — never a fabricated number."""
    leg_names = list(leg_results.keys())

    def summarize_for(target_bias: str):
        misaligned = []
        for name in leg_names:
            base_needed = NEEDED_DIRECTION_FOR_BULLISH[name]
            needed = base_needed if target_bias == "Bullish" else ("up" if base_needed == "down" else "down")
            leg = leg_results[name]
            if leg.get("direction") is None:
                return {"reachable": False, "reason": f"{name} has no established P&F direction yet"}
            if leg["direction"] != needed:
                misaligned.append(name)

        if not misaligned:
            return {"reachable": True, "already_aligned": True, "flip_level": None}

        flip_spots = []
        for name in misaligned:
            fs = leg_results[name].get("flip_spot")
            if fs is None:
                return {"reachable": False, "reason": f"{name} can't reach the required premium via spot movement alone at the current implied vol"}
            flip_spots.append((name, fs))

        signs = {1 if fs > spot else (-1 if fs < spot else 0) for _, fs in flip_spots}
        signs.discard(0)
        if len(signs) > 1:
            return {"reachable": False, "reason": "misaligned legs require spot moves in opposite directions", "legs": dict(flip_spots)}

        sign = signs.pop() if signs else 0
        binding = max(flip_spots, key=lambda x: x[1]) if sign >= 0 else min(flip_spots, key=lambda x: x[1])
        return {"reachable": True, "already_aligned": False, "flip_level": binding[1], "binding_leg": binding[0], "legs": dict(flip_spots)}

    return {"bullish": summarize_for("Bullish"), "bearish": summarize_for("Bearish")}
