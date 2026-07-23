"""
Black-Scholes pricing + implied-volatility solver for NIFTY/Bank Nifty index
options (European-style, no dividend adjustment needed for an index).

Definedge's API provides no Greeks/IV directly (confirmed by querying its
quotes endpoint and NSE master files directly during Phase 1/2 design) — this
module computes them from the option's own traded premium instead.

All functions here work in plain floats, not Decimal — `math` doesn't mix
with Decimal, and these are approximations anyway (fixed risk-free rate,
no dividend yield). Callers (journal_routes.py's background enrichment)
convert results to Decimal at the point they're stored on a Trade document.

Every public function returns None instead of raising when inputs don't
support a meaningful answer (expired options, bad/stale prices, solver
non-convergence) — this feeds a best-effort auto-fill path where a null
field is the correct outcome, not a 500 error.
"""
import math
from typing import Optional

RISK_FREE_RATE = 0.065  # approximate current Indian short-term rate; not live-fetched
IV_MIN = 0.01   # 1%
IV_MAX = 3.00   # 300% — bounds outside this are treated as solver garbage, not real IV


def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _norm_pdf(x: float) -> float:
    return math.exp(-0.5 * x * x) / math.sqrt(2.0 * math.pi)


def _d1_d2(S: float, K: float, T: float, r: float, sigma: float):
    if T <= 0 or sigma <= 0:
        return None, None
    d1 = (math.log(S / K) + (r + 0.5 * sigma * sigma) * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)
    return d1, d2


def bs_price(S: float, K: float, T: float, r: float, sigma: float, option_type: str) -> Optional[float]:
    """European Black-Scholes price. option_type: 'CE' or 'PE'."""
    if T <= 0 or sigma <= 0 or S <= 0 or K <= 0:
        return None
    d1, d2 = _d1_d2(S, K, T, r, sigma)
    if d1 is None:
        return None
    disc_k = K * math.exp(-r * T)
    if option_type == "CE":
        return S * _norm_cdf(d1) - disc_k * _norm_cdf(d2)
    elif option_type == "PE":
        return disc_k * _norm_cdf(-d2) - S * _norm_cdf(-d1)
    return None


def _vega(S: float, K: float, T: float, r: float, sigma: float) -> float:
    d1, _ = _d1_d2(S, K, T, r, sigma)
    if d1 is None:
        return 0.0
    return S * _norm_pdf(d1) * math.sqrt(T)


def greeks(S: float, K: float, T: float, r: float, sigma: float, option_type: str) -> Optional[dict]:
    """Returns {'delta', 'theta', 'vega'} — theta is per-day (annual/365), the
    unit traders actually think in for decay; vega is per 1.0 (100%) vol move."""
    if T <= 0 or sigma <= 0 or S <= 0 or K <= 0:
        return None
    d1, d2 = _d1_d2(S, K, T, r, sigma)
    if d1 is None:
        return None
    disc_k = K * math.exp(-r * T)
    vega = S * _norm_pdf(d1) * math.sqrt(T)

    if option_type == "CE":
        delta = _norm_cdf(d1)
        theta_annual = -(S * _norm_pdf(d1) * sigma) / (2 * math.sqrt(T)) - r * disc_k * _norm_cdf(d2)
    elif option_type == "PE":
        delta = _norm_cdf(d1) - 1.0
        theta_annual = -(S * _norm_pdf(d1) * sigma) / (2 * math.sqrt(T)) + r * disc_k * _norm_cdf(-d2)
    else:
        return None

    return {"delta": delta, "theta": theta_annual / 365.0, "vega": vega}


def _intrinsic(S: float, K: float, T: float, r: float, option_type: str) -> float:
    if option_type == "CE":
        undiscounted = max(S - K, 0.0)
    else:
        undiscounted = max(K - S, 0.0)
    return undiscounted * math.exp(-r * T)


def _bisect_iv(market_price: float, S: float, K: float, T: float, r: float, option_type: str,
                lo: float = 0.001, hi: float = 5.0, tol: float = 1e-4, max_iter: int = 100) -> Optional[float]:
    price_lo = bs_price(S, K, T, r, lo, option_type)
    price_hi = bs_price(S, K, T, r, hi, option_type)
    if price_lo is None or price_hi is None:
        return None
    # bs_price is monotonically increasing in sigma — if the market price
    # isn't bracketed, bisection would silently converge to a boundary
    # instead of failing loudly, so bail out explicitly.
    if not (price_lo <= market_price <= price_hi):
        return None
    for _ in range(max_iter):
        mid = (lo + hi) / 2
        price_mid = bs_price(S, K, T, r, mid, option_type)
        if price_mid is None:
            return None
        if abs(price_mid - market_price) < tol:
            return mid
        if price_mid < market_price:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def implied_vol(market_price: float, S: float, K: float, T: float, r: float = RISK_FREE_RATE,
                 option_type: str = "CE") -> Optional[float]:
    """Solves for sigma given a traded option premium. Returns None (never
    raises) whenever the inputs don't support a meaningful answer — expired
    options, a price below intrinsic value (stale/bad data), or a solver
    result outside a sane IV range."""
    if T <= 0 or S <= 0 or K <= 0 or market_price <= 0:
        return None
    if market_price < _intrinsic(S, K, T, r, option_type):
        return None  # no real sigma solves this — bad/stale entry_price

    sigma = 0.30  # initial guess
    converged = None
    for _ in range(50):
        price = bs_price(S, K, T, r, sigma, option_type)
        if price is None:
            break
        vega = _vega(S, K, T, r, sigma)
        if vega < 1e-6:
            break  # deep ITM/OTM or T~0 — don't let Newton divide by ~0, fall to bisection
        diff = price - market_price
        if abs(diff) < 1e-4:
            converged = sigma
            break
        sigma -= diff / vega
        if sigma <= 0 or sigma > 5:
            break  # left the sane search space — fall to bisection

    if converged is None:
        converged = _bisect_iv(market_price, S, K, T, r, option_type)

    if converged is None or not (IV_MIN <= converged <= IV_MAX):
        return None
    return converged
