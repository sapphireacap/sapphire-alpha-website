"""
Black-76 (options on futures) pricing, implied volatility, and Greeks --
pure, unit-testable, no dependency beyond stdlib math (normal CDF/PDF via
math.erf, same technique already used by options_greeks.py elsewhere in
this codebase).

**Why Black-76 and not the existing options_greeks.py (Black-Scholes on
spot)**: explicitly requested for the Convexity Window / Gamma Backspread
strategies -- Black-76 prices off the FUTURES price directly (which already
embeds the cost-of-carry/dividend-yield effect), rather than spot plus a
separate drift term. `options_greeks.py` stays untouched and in place for
the Index Vector flip-level feature that already depends on it; this is a
new, separate engine, not a replacement.

Formulas (standard Black-76 / "Black model", matching Haug's "The Complete
Guide to Option Pricing Formulas"):
    d1 = [ln(F/K) + (sigma^2/2)*T] / (sigma*sqrt(T))
    d2 = d1 - sigma*sqrt(T)
    call = e^(-rT) * [F*N(d1) - K*N(d2)]
    put  = e^(-rT) * [K*N(-d2) - F*N(-d1)]
    delta_call = e^(-rT) * N(d1)
    delta_put  = e^(-rT) * (N(d1) - 1)
    gamma      = e^(-rT) * N'(d1) / (F * sigma * sqrt(T))      [same both sides]
    vega       = F * e^(-rT) * N'(d1) * sqrt(T)                 [same both sides,
                 per 1.00 = 100% change in sigma; divide by 100 for "per vol point"]
    theta_call = -[F*e^(-rT)*N'(d1)*sigma]/(2*sqrt(T)) + r*F*e^(-rT)*N(d1)  - r*K*e^(-rT)*N(d2)
    theta_put  = -[F*e^(-rT)*N'(d1)*sigma]/(2*sqrt(T)) - r*F*e^(-rT)*N(-d1) + r*K*e^(-rT)*N(-d2)
    (theta above is PER YEAR; divide by 365 for per calendar day)

Deliberate simplifications, same spirit/scope as options_greeks.py's own
documented ones -- retail-grade, not market-making precision:
  - European exercise.
  - Time to expiry in calendar days / 365, not trading-day count.
  - A single constant risk-free rate, not a real yield curve.
  - Implied vol is backed out once and held constant while used elsewhere
    (e.g. a required-move calc) -- real IV shifts somewhat as F moves
    (vanna), not modeled here.
"""
import math
from datetime import datetime, timezone, timedelta

RISK_FREE_RATE_DEFAULT = 0.065  # configurable per the brief; NOT read from
                                  # an env var here -- callers (blackbox_config)
                                  # own where the live value comes from.
IST = timezone(timedelta(hours=5, minutes=30))


def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _norm_pdf(x: float) -> float:
    return math.exp(-0.5 * x * x) / math.sqrt(2.0 * math.pi)


def years_to_expiry(expiry_date, now: datetime = None) -> float:
    """expiry_date: a date (contract expiry, 15:30 IST on that date). Never
    returns <= 0 (floors at a small epsilon) so downstream math never
    divides by zero on expiry day itself."""
    now = now or datetime.now(IST)
    expiry_dt = datetime.combine(expiry_date, datetime.min.time(), tzinfo=IST).replace(hour=15, minute=30)
    seconds = (expiry_dt - now).total_seconds()
    return max(seconds / (365.0 * 24 * 3600), 1e-6)


def _d1_d2(F: float, K: float, T: float, sigma: float):
    d1 = (math.log(F / K) + 0.5 * sigma * sigma * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)
    return d1, d2


def price(F: float, K: float, T: float, sigma: float, option_type: str, r: float = RISK_FREE_RATE_DEFAULT) -> float:
    """option_type: 'CE' or 'PE'. Falls back to discounted intrinsic value
    at/after expiry or with zero vol, matching options_greeks.py's own
    edge-case handling."""
    if T <= 0 or sigma <= 0:
        intrinsic = max(0.0, (F - K) if option_type == "CE" else (K - F))
        return intrinsic * math.exp(-r * T) if T > 0 else intrinsic
    d1, d2 = _d1_d2(F, K, T, sigma)
    disc = math.exp(-r * T)
    if option_type == "CE":
        return disc * (F * _norm_cdf(d1) - K * _norm_cdf(d2))
    return disc * (K * _norm_cdf(-d2) - F * _norm_cdf(-d1))


def greeks(F: float, K: float, T: float, sigma: float, option_type: str, r: float = RISK_FREE_RATE_DEFAULT) -> dict:
    """Returns {"delta", "gamma", "theta", "vega"}. theta is PER DAY
    (already divided by 365); vega is PER VOL POINT (already divided by
    100) -- both chosen to match how the strategies' filters express their
    thresholds (e.g. "net Theta between -0.05 and +0.05 per lot per day")."""
    if T <= 0 or sigma <= 0:
        return {"delta": 0.0, "gamma": 0.0, "theta": 0.0, "vega": 0.0}
    d1, d2 = _d1_d2(F, K, T, sigma)
    disc = math.exp(-r * T)
    pdf_d1 = _norm_pdf(d1)

    gamma = disc * pdf_d1 / (F * sigma * math.sqrt(T))
    vega_per_unit_sigma = F * disc * pdf_d1 * math.sqrt(T)

    if option_type == "CE":
        delta = disc * _norm_cdf(d1)
        theta_per_year = (
            -(F * disc * pdf_d1 * sigma) / (2 * math.sqrt(T))
            + r * F * disc * _norm_cdf(d1)
            - r * K * disc * _norm_cdf(d2)
        )
    else:
        delta = disc * (_norm_cdf(d1) - 1.0)
        theta_per_year = (
            -(F * disc * pdf_d1 * sigma) / (2 * math.sqrt(T))
            - r * F * disc * _norm_cdf(-d1)
            + r * K * disc * _norm_cdf(-d2)
        )

    return {
        "delta": delta,
        "gamma": gamma,
        "theta": theta_per_year / 365.0,
        "vega": vega_per_unit_sigma / 100.0,
    }


def implied_vol(target_price: float, F: float, K: float, T: float, option_type: str,
                 r: float = RISK_FREE_RATE_DEFAULT) -> float:
    """Newton-Raphson (vega as the derivative), falling back to bisection if
    Newton doesn't converge -- vega is near-zero for deep ITM/OTM strikes,
    which makes Newton unstable right at the extremes. Same two-stage
    approach as options_greeks.py's implied_vol(), same reasoning."""
    intrinsic = max(0.0, (F - K) if option_type == "CE" else (K - F)) * math.exp(-r * T)
    if target_price <= intrinsic + 1e-6:
        return 1e-4  # at/below discounted intrinsic -- no time value to solve a vol from

    sigma = 0.25  # reasonable starting guess for index options
    for _ in range(50):
        theo = price(F, K, T, sigma, option_type, r)
        diff = theo - target_price
        if abs(diff) < 1e-4:
            return sigma
        vega_per_unit_sigma = greeks(F, K, T, sigma, option_type, r)["vega"] * 100.0
        if vega_per_unit_sigma < 1e-8:
            break
        sigma -= diff / vega_per_unit_sigma
        if sigma <= 0 or sigma > 5:
            break
    else:
        return max(1e-4, min(sigma, 5.0))

    # Newton didn't converge cleanly -- bisection always converges for a
    # monotonic function (price is monotonic in sigma for both CE and PE).
    lo, hi = 1e-4, 5.0
    for _ in range(100):
        mid = (lo + hi) / 2
        theo = price(F, K, T, mid, option_type, r)
        if abs(theo - target_price) < 1e-4:
            return mid
        if theo < target_price:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2
