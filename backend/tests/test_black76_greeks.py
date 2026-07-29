"""
Unit tests for black76_greeks.py.

Rather than trusting a single hand-copied "known reference value" (easy to
transcribe wrong from a textbook and then "validate" a bug against itself),
this suite leans on model-independent invariants and self-consistency
checks that any CORRECT Black-76 implementation must satisfy regardless of
the specific numbers chosen:

  1. Put-call parity: C - P = e^(-rT)(F - K), exactly, for any valid input.
     This is a no-arbitrage identity, not a Black-76-specific property --
     if it fails, the pricing formula itself has a bug.
  2. At F == K exactly, C == P exactly (a direct corollary of parity when
     F - K = 0) -- a second, independent check of the same pricing code.
  3. Every closed-form Greek is cross-checked against a finite-difference
     approximation of the pricing function itself (bump F for delta/gamma,
     bump sigma for vega, bump T for theta). This catches sign errors and
     wrong-formula bugs that parity alone wouldn't (parity only constrains
     the RELATIONSHIP between call/put price, not whether e.g. gamma's
     formula is correct).
  4. The IV solver round-trips: price a known sigma, then recover it via
     implied_vol(), confirming the solver actually inverts the pricing
     function it's paired with.
  5. Edge-case handling (T->0, sigma->0) matches the documented "collapses
     to discounted intrinsic" behavior instead of raising or returning NaN.
"""
import math
from datetime import date, timedelta

from black76_greeks import price, greeks, implied_vol, years_to_expiry, IST


def test_put_call_parity_holds_across_a_range_of_inputs():
    r = 0.065
    cases = [
        (24000, 24000, 0.1, 0.15),
        (24000, 24500, 0.05, 0.20),
        (24000, 23000, 0.25, 0.12),
        (57000, 58000, 0.02, 0.30),
    ]
    for F, K, T, sigma in cases:
        c = price(F, K, T, sigma, "CE", r)
        p = price(F, K, T, sigma, "PE", r)
        expected_diff = math.exp(-r * T) * (F - K)
        assert abs((c - p) - expected_diff) < 1e-6, f"parity failed for F={F},K={K},T={T},sigma={sigma}"


def test_call_equals_put_at_the_money():
    """At F == K exactly, C == P exactly -- a direct corollary of parity
    (F - K = 0), checked independently as a second sanity pass on the same
    pricing code."""
    c = price(24000, 24000, 0.08, 0.18, "CE", 0.065)
    p = price(24000, 24000, 0.08, 0.18, "PE", 0.065)
    assert abs(c - p) < 1e-9


def test_delta_matches_finite_difference():
    F, K, T, sigma, r = 24000, 24200, 0.1, 0.15, 0.065
    h = 1.0  # 1 point bump in the futures price
    for opt in ("CE", "PE"):
        fd_delta = (price(F + h, K, T, sigma, opt, r) - price(F - h, K, T, sigma, opt, r)) / (2 * h)
        analytic_delta = greeks(F, K, T, sigma, opt, r)["delta"]
        assert abs(fd_delta - analytic_delta) < 1e-4, f"{opt} delta mismatch: fd={fd_delta} analytic={analytic_delta}"


def test_gamma_matches_finite_difference():
    F, K, T, sigma, r = 24000, 24200, 0.1, 0.15, 0.065
    h = 5.0
    for opt in ("CE", "PE"):
        fd_gamma = (price(F + h, K, T, sigma, opt, r) - 2 * price(F, K, T, sigma, opt, r) + price(F - h, K, T, sigma, opt, r)) / (h * h)
        analytic_gamma = greeks(F, K, T, sigma, opt, r)["gamma"]
        assert abs(fd_gamma - analytic_gamma) < 1e-6, f"{opt} gamma mismatch: fd={fd_gamma} analytic={analytic_gamma}"


def test_vega_matches_finite_difference():
    """greeks()'s vega is "per vol point" (already /100) -- the finite
    difference bumps sigma by 0.0001 (0.01 vol points) and scales up to
    match that convention."""
    F, K, T, sigma, r = 24000, 24200, 0.1, 0.15, 0.065
    h = 0.0001
    for opt in ("CE", "PE"):
        fd_vega_per_unit_sigma = (price(F, K, T, sigma + h, opt, r) - price(F, K, T, sigma - h, opt, r)) / (2 * h)
        fd_vega_per_vol_point = fd_vega_per_unit_sigma / 100.0
        analytic_vega = greeks(F, K, T, sigma, opt, r)["vega"]
        assert abs(fd_vega_per_vol_point - analytic_vega) < 1e-4, f"{opt} vega mismatch: fd={fd_vega_per_vol_point} analytic={analytic_vega}"


def test_theta_matches_finite_difference():
    """greeks()'s theta is per CALENDAR DAY (already /365). Finite-difference
    on T directly: as T (time-to-expiry) decreases by one day's worth of
    years, the price change over that step approximates theta."""
    F, K, T, sigma, r = 24000, 24200, 0.1, 0.15, 0.065
    one_day = 1.0 / 365.0
    h = one_day / 100  # small step, well inside the T=0.1 window
    for opt in ("CE", "PE"):
        fd_theta_per_year = (price(F, K, T - h, sigma, opt, r) - price(F, K, T + h, sigma, opt, r)) / (2 * h)
        fd_theta_per_day = fd_theta_per_year / 365.0
        analytic_theta = greeks(F, K, T, sigma, opt, r)["theta"]
        assert abs(fd_theta_per_day - analytic_theta) < 1e-4, f"{opt} theta mismatch: fd={fd_theta_per_day} analytic={analytic_theta}"


def test_implied_vol_round_trips_a_known_sigma():
    F, K, T, r = 24000, 24300, 0.08, 0.065
    true_sigma = 0.17
    for opt in ("CE", "PE"):
        theo_price = price(F, K, T, true_sigma, opt, r)
        recovered_sigma = implied_vol(theo_price, F, K, T, opt, r)
        assert abs(recovered_sigma - true_sigma) < 1e-3, f"{opt} IV round-trip failed: recovered {recovered_sigma}, expected {true_sigma}"


def test_price_at_expiry_collapses_to_intrinsic():
    assert price(24100, 24000, 0, 0.15, "CE", 0.065) == 100
    assert price(23900, 24000, 0, 0.15, "CE", 0.065) == 0
    assert price(23900, 24000, 0, 0.15, "PE", 0.065) == 100


def test_zero_vol_collapses_to_discounted_intrinsic():
    g = greeks(24000, 24500, 0.1, 0.0, "CE", 0.065)
    assert g == {"delta": 0.0, "gamma": 0.0, "theta": 0.0, "vega": 0.0}


def test_years_to_expiry_never_zero_or_negative_on_expiry_day():
    today = date.today()
    # "now" set to after the 15:30 IST close on the expiry date itself
    from datetime import datetime
    now = datetime.combine(today, datetime.min.time(), tzinfo=IST).replace(hour=16, minute=0)
    T = years_to_expiry(today, now=now)
    assert T > 0


def test_years_to_expiry_is_positive_and_shrinks_as_expiry_approaches():
    today = date.today()
    t_far = years_to_expiry(today + timedelta(days=10))
    t_near = years_to_expiry(today + timedelta(days=1))
    assert t_far > t_near > 0
