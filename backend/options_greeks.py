"""
Black-Scholes pricing, implied volatility, and Greeks — pure, unit-testable.
No new dependency: normal CDF/PDF via math.erf (already stdlib), not scipy.

Used by index_vector_flip.py to answer "at what spot level would this P&F
leg's premium cross its reversal threshold" — NOT a price-direction
forecast. Definedge's own API doesn't expose Greeks or IV (verified live:
the /quotes response has no delta/gamma/theta/vega/iv field at all), so
both IV and the Greeks are computed here from the same premium/spot/strike/
expiry data already fetched elsewhere in this codebase.

Known, deliberate simplifications (standard for a retail-grade calculator,
not appropriate for market-making precision):
  - European exercise, spot-based (no dividend yield term) — index options
    do carry a small implied yield via the futures basis, ignored here.
  - Time to expiry in calendar days / 365, not trading-day count.
  - A single constant risk-free rate, not a real yield curve.
  - Implied vol is backed out ONCE from the current premium and held
    constant while solving for a flip level — real IV would itself shift
    somewhat as spot moves (vanna), which this does not model.
"""
import math
from datetime import datetime, timezone, timedelta

RISK_FREE_RATE = 0.07  # ~India short-term rate; minor effect on short-dated options
IST = timezone(timedelta(hours=5, minutes=30))


def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _norm_pdf(x: float) -> float:
    return math.exp(-0.5 * x * x) / math.sqrt(2.0 * math.pi)


def years_to_expiry(expiry_date, now: datetime = None) -> float:
    """expiry_date: a date (market close, 15:30 IST, on that date) — now
    defaults to the current moment. Never returns <= 0 (floors at a small
    epsilon) so downstream BS math never divides by zero on expiry day."""
    now = now or datetime.now(IST)
    expiry_dt = datetime.combine(expiry_date, datetime.min.time(), tzinfo=IST).replace(hour=15, minute=30)
    seconds = (expiry_dt - now).total_seconds()
    return max(seconds / (365.0 * 24 * 3600), 1e-6)


def bs_price(S: float, K: float, T: float, sigma: float, option_type: str, r: float = RISK_FREE_RATE) -> float:
    if T <= 0 or sigma <= 0:
        return max(0.0, (S - K) if option_type == "CE" else (K - S))
    d1 = (math.log(S / K) + (r + 0.5 * sigma * sigma) * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)
    if option_type == "CE":
        return S * _norm_cdf(d1) - K * math.exp(-r * T) * _norm_cdf(d2)
    return K * math.exp(-r * T) * _norm_cdf(-d2) - S * _norm_cdf(-d1)


def bs_greeks(S: float, K: float, T: float, sigma: float, option_type: str, r: float = RISK_FREE_RATE) -> dict:
    if T <= 0 or sigma <= 0:
        return {"delta": 0.0, "gamma": 0.0, "theta": 0.0, "vega": 0.0}
    d1 = (math.log(S / K) + (r + 0.5 * sigma * sigma) * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)
    pdf_d1 = _norm_pdf(d1)
    gamma = pdf_d1 / (S * sigma * math.sqrt(T))
    vega = S * pdf_d1 * math.sqrt(T) / 100.0  # per 1 vol point (1.00 = 100%), not per unit sigma
    if option_type == "CE":
        delta = _norm_cdf(d1)
        theta = (-(S * pdf_d1 * sigma) / (2 * math.sqrt(T)) - r * K * math.exp(-r * T) * _norm_cdf(d2)) / 365.0
    else:
        delta = _norm_cdf(d1) - 1.0
        theta = (-(S * pdf_d1 * sigma) / (2 * math.sqrt(T)) + r * K * math.exp(-r * T) * _norm_cdf(-d2)) / 365.0
    return {"delta": delta, "gamma": gamma, "theta": theta, "vega": vega}


def implied_vol(price: float, S: float, K: float, T: float, option_type: str, r: float = RISK_FREE_RATE) -> float:
    """Newton-Raphson (using vega as the derivative), falling back to
    bisection if Newton doesn't converge — vega can be near-zero for deep
    ITM/OTM strikes, which makes Newton unstable right at the extremes."""
    intrinsic = max(0.0, (S - K) if option_type == "CE" else (K - S))
    if price <= intrinsic + 1e-6:
        return 1e-4  # at/below intrinsic — no time value left to solve a vol from

    sigma = 0.25  # reasonable starting guess for index options
    for _ in range(50):
        theo = bs_price(S, K, T, sigma, option_type, r)
        vega_per_unit_sigma = bs_greeks(S, K, T, sigma, option_type, r)["vega"] * 100.0
        diff = theo - price
        if abs(diff) < 1e-4:
            return sigma
        if vega_per_unit_sigma < 1e-8:
            break
        sigma -= diff / vega_per_unit_sigma
        if sigma <= 0 or sigma > 5:
            break
    else:
        return max(1e-4, min(sigma, 5.0))

    # Newton didn't converge cleanly — bisection is slower but always converges for a monotonic function
    lo, hi = 1e-4, 5.0
    for _ in range(100):
        mid = (lo + hi) / 2
        theo = bs_price(S, K, T, mid, option_type, r)
        if abs(theo - price) < 1e-4:
            return mid
        if theo < price:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def spot_for_target_price(target_price: float, K: float, T: float, sigma: float, option_type: str,
                           r: float = RISK_FREE_RATE, s_lo: float = 1.0, s_hi: float = 200000.0) -> float:
    """Inverse of bs_price w.r.t. spot: what S makes bs_price(S,...) equal
    target_price, holding sigma constant (see module docstring for why that's
    an accepted simplification, not a bug). Bisection, not Newton — bs_price
    is monotonic in S for both CE and PE, so this always converges and never
    needs a derivative."""
    lo, hi = s_lo, s_hi
    price_lo = bs_price(lo, K, T, sigma, option_type, r)
    price_hi = bs_price(hi, K, T, sigma, option_type, r)
    increasing = price_hi > price_lo  # calls rise with S; puts fall with S
    for _ in range(100):
        mid = (lo + hi) / 2
        theo = bs_price(mid, K, T, sigma, option_type, r)
        if abs(theo - target_price) < 1e-4:
            return mid
        if (theo < target_price) == increasing:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2
