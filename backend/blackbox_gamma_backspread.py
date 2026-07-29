"""
Strategy 2 -- "Gamma Backspread" (near-zero theta convexity) signal logic.
Pure, no-I/O functions only, same split/reasoning as
blackbox_convexity_window.py: one code path shared by the backtest harness
(Step 4) and the live/paper evaluator (Step 5).

Structure: sell 1 ATM option, buy 2 OTM of the SAME type and expiry (a
1x2 ratio backspread). Net Theta must land in [theta_band_lo, theta_band_hi]
per lot per day and net Gamma must be positive.

Open design choice, resolved here (flagged, not silently assumed): among
OTM strikes that land the package's net Theta inside the theta band, this
picks the one CLOSEST TO THETA-NEUTRAL (net theta nearest 0), not the first
one found scanning outward from ATM. Rationale: "near-zero theta convexity"
is the strategy's own stated goal, so within a band that already satisfies
the constraint, minimizing net theta further is the more principled,
deterministic tie-break than an arbitrary scan order. If this isn't the
intended rule, this is the one function to change: `_select_otm_strike`.

Callers hand this module plain dicts/numbers:

  market = {
      "spot": float, "prev_close": float, "ema20_15m": float | None,
      "atm_iv": float,                    # decimal annualized
      "iv_history": [float, ...],         # trailing ATM IV series, oldest -> newest, for percentile
      "atm": {"strike": int, "option_type": "CE"|"PE", "token": str,
               "premium": float, "greeks": {...}},
      "otm_candidates": [
          {"strike": int, "option_type": "CE"|"PE", "token": str,
           "premium": float, "greeks": {...}},
          ...  # same option_type and expiry as `atm`, strikes further OTM,
               # within otm_strike_search_range of the ATM strike
      ],
      "expiry": date, "dte": int,
  }
"""
from blackbox_options_data import percentile_rank

REQUIRED_MOVE_EPS = 1e-9


def select_direction(spot: float, prev_close: float, ema20_15m) -> str | None:
    """Identical price-only rule to Strategy 1 (call backspread on bullish,
    put backspread on bearish)."""
    if ema20_15m is None:
        return None
    if spot > prev_close and spot > ema20_15m:
        return "CE"
    if spot < prev_close and spot < ema20_15m:
        return "PE"
    return None


def _package_greeks(atm: dict, otm: dict) -> dict:
    """Sell 1 ATM, buy 2 OTM -- net Greeks of the package (per 1 lot of the
    ATM leg)."""
    ag, og = atm["greeks"], otm["greeks"]
    return {
        "delta": -ag["delta"] + 2 * og["delta"],
        "gamma": -ag["gamma"] + 2 * og["gamma"],
        "theta": -ag["theta"] + 2 * og["theta"],
        "vega": -ag["vega"] + 2 * og["vega"],
    }


def _select_otm_strike(atm: dict, otm_candidates: list, cfg: dict) -> dict | None:
    """Among otm_candidates, keep those landing net Theta inside
    [theta_band_lo, theta_band_hi] AND net Gamma > 0; of those, pick the one
    closest to theta-neutral (see module docstring). Returns
    {"otm": candidate, "package_greeks": {...}} or None if nothing in the
    search range satisfies the band."""
    best = None
    for otm in otm_candidates:
        pkg = _package_greeks(atm, otm)
        if pkg["gamma"] <= 0:
            continue
        if not (cfg["theta_band_lo"] <= pkg["theta"] <= cfg["theta_band_hi"]):
            continue
        if best is None or abs(pkg["theta"]) < abs(best["package_greeks"]["theta"]):
            best = {"otm": otm, "package_greeks": pkg}
    return best


def check_entry_filters(market: dict, config: dict) -> dict:
    """Returns {"qualifies": bool, "reason": str, "filters": {...}, "direction",
    "package": {"atm", "otm", "package_greeks"} | None}."""
    filters = {}

    direction = select_direction(market["spot"], market["prev_close"], market.get("ema20_15m"))
    filters["direction"] = direction
    if direction is None:
        return {"qualifies": False, "reason": "no directional edge (spot/prev-close/EMA not aligned)",
                "filters": filters, "direction": None, "package": None}

    cfg = config["gamma_backspread"]

    dte = market.get("dte")
    filters["dte"] = dte
    if dte is None or not (cfg["dte_min"] <= dte <= cfg["dte_max"]):
        return {"qualifies": False, "reason": f"DTE {dte} outside [{cfg['dte_min']}, {cfg['dte_max']}]",
                "filters": filters, "direction": direction, "package": None}

    atm_iv = market.get("atm_iv")
    iv_history = market.get("iv_history") or []
    iv_pctile = percentile_rank(iv_history, atm_iv) if atm_iv is not None else None
    filters["atm_iv"] = atm_iv
    filters["iv_percentile"] = iv_pctile
    filters["iv_history_len"] = len(iv_history)
    if iv_pctile is None:
        return {"qualifies": False, "reason": "not enough ATM IV history yet to compute a percentile",
                "filters": filters, "direction": direction, "package": None}
    if iv_pctile >= cfg["iv_percentile_entry_max"]:
        return {"qualifies": False,
                "reason": f"IV percentile {iv_pctile:.1f} >= cap {cfg['iv_percentile_entry_max']} — vol not cheap enough",
                "filters": filters, "direction": direction, "package": None}

    atm = market.get("atm")
    otm_candidates = [c for c in market.get("otm_candidates", []) if c["option_type"] == direction]
    if not atm or atm["option_type"] != direction or not otm_candidates:
        return {"qualifies": False, "reason": f"no {direction} ATM/OTM contracts available",
                "filters": filters, "direction": direction, "package": None}

    selected = _select_otm_strike(atm, otm_candidates, cfg)
    if selected is None:
        return {"qualifies": False,
                "reason": f"no OTM strike lands net theta inside [{cfg['theta_band_lo']}, {cfg['theta_band_hi']}] with positive net gamma",
                "filters": filters, "direction": direction, "package": None}

    filters["net_theta"] = selected["package_greeks"]["theta"]
    filters["net_gamma"] = selected["package_greeks"]["gamma"]
    filters["net_vega"] = selected["package_greeks"]["vega"]
    if selected["package_greeks"]["vega"] <= 0:
        return {"qualifies": False, "reason": "net vega of the package is not positive",
                "filters": filters, "direction": direction, "package": None}

    return {"qualifies": True, "reason": "all entry filters passed", "filters": filters,
            "direction": direction,
            "package": {"atm": atm, "otm": selected["otm"], "package_greeks": selected["package_greeks"]}}


def evaluate_exit(current_atm_premium: float, current_otm_premium: float, current_package_greeks: dict,
                   current_atm_iv: float, iv_history: list, trade: dict, dte: int, config: dict) -> dict:
    """current_*_premium: live prices for the ATM (short) and OTM (long x2)
    legs. trade: {"net_debit", "atm_entry_price", "otm_entry_price", ...} --
    net_debit = 2*otm_entry_price - atm_entry_price (positive = paid a net
    debit; the package can also be entered for a net credit, in which case
    percentage P&L off "net debit" is undefined -- callers must guard that
    case before calling this, since the spec's target/SL are both expressed
    as "% on net debit").

    Checked in order: theta drift -> DTE cutoff -> SL/target -> IV
    percentile repricing (matches the spec's own listed order).

    Returns {"action": "exit", "exit_reason": str, "exit_price": {"atm","otm"}}
    or {"action": "hold"}."""
    cfg = config["gamma_backspread"]

    net_theta = current_package_greeks["theta"]
    if net_theta < cfg["theta_exit_threshold"]:
        return {"action": "exit", "exit_reason": "theta_drift",
                "exit_price": {"atm": current_atm_premium, "otm": current_otm_premium}}

    if dte <= cfg["dte_exit"]:
        return {"action": "exit", "exit_reason": "dte_cutoff",
                "exit_price": {"atm": current_atm_premium, "otm": current_otm_premium}}

    net_debit = trade["net_debit"]
    current_value = 2 * current_otm_premium - current_atm_premium
    if net_debit and abs(net_debit) > REQUIRED_MOVE_EPS:
        pnl_pct = (current_value - net_debit) / abs(net_debit)
        if pnl_pct <= cfg["sl_pct"]:
            return {"action": "exit", "exit_reason": "stop_loss",
                    "exit_price": {"atm": current_atm_premium, "otm": current_otm_premium}}
        if pnl_pct >= cfg["target_pct"]:
            return {"action": "exit", "exit_reason": "target",
                    "exit_price": {"atm": current_atm_premium, "otm": current_otm_premium}}

    iv_pctile = percentile_rank(iv_history, current_atm_iv) if iv_history else None
    if iv_pctile is not None and iv_pctile >= cfg["iv_percentile_exit"]:
        return {"action": "exit", "exit_reason": "iv_repriced",
                "exit_price": {"atm": current_atm_premium, "otm": current_otm_premium}}

    return {"action": "hold"}
