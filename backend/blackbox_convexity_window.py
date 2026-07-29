"""
Strategy 1 -- "Convexity Window" (conditional long ATM) signal logic. Pure,
no-I/O functions only (mirrors blackbox_prism_alpha.py's _gate_entry /
_evaluate_exit split) so the backtest harness (Step 4) and the live/paper
evaluator (Step 5) call this exact same code path -- never two
implementations that can silently drift apart.

Every threshold referenced here comes from a `config["convexity_window"]`
dict (see blackbox_options_config.py) -- nothing is hardcoded, and every
value in that default config is an unvalidated STARTING point per explicit
instruction, to be calibrated by Step 4's backtest sweep.

Callers are responsible for all I/O and Greeks computation (via
black76_greeks.py + blackbox_options_data.py) and hand this module plain
dicts/numbers:

  market = {
      "spot": float, "prev_close": float, "ema20_15m": float | None,
      "atm_iv": float,                 # decimal annualized, ATM option of the trade direction
      "realized_vol": float | None,    # decimal annualized, from blackbox_options_data.realized_vol
      "median_true_range": float | None,
      "atm_theta": float, "atm_gamma": float,  # ATM option's own Greeks, direction-side
      "candidates": [
          {"strike": int, "expiry": date, "dte": int, "option_type": "CE"|"PE",
           "token": str, "premium": float, "greeks": {"delta","gamma","theta","vega"}},
          ...  # every strike within +/- strike_range_from_atm, both expiries in [dte_min, dte_max]
      ],
  }
"""

REQUIRED_MOVE_EPS = 1e-9


def select_direction(spot: float, prev_close: float, ema20_15m) -> str | None:
    """Price-only directional rule (d): CE if spot above BOTH prev close and
    the 15m EMA; PE on the mirror; otherwise no trade. None (not a coin
    flip) until ema20_15m has actually seeded (needs >= ema_period_15m
    15-minute bars)."""
    if ema20_15m is None:
        return None
    if spot > prev_close and spot > ema20_15m:
        return "CE"
    if spot < prev_close and spot < ema20_15m:
        return "PE"
    return None


def required_move(theta_per_day: float, gamma: float) -> float | None:
    """sqrt(2 * Theta_per_day / Gamma) -- the standard gamma-scalping
    breakeven-move formula. Theta is negative for a long option and Gamma is
    always >= 0, so this uses abs(theta); returns None (not a fabricated 0)
    if gamma is ~0, which would make the "cheap convexity" question
    undefined rather than trivially true."""
    if gamma is None or gamma < REQUIRED_MOVE_EPS or theta_per_day is None:
        return None
    return (2.0 * abs(theta_per_day) / gamma) ** 0.5


def check_entry_filters(market: dict, config: dict) -> dict:
    """Returns {"qualifies": bool, "reason": str, "filters": {...all values
    checked, for the signal doc's "all filter values at entry" requirement},
    "direction": "CE"|"PE"|None, "selected": candidate dict | None}.

    Filters are evaluated in the order given in the spec (a -> b -> c -> d
    is the spec's own lettering, but direction (d) is resolved FIRST here
    since (a)/(b)/(c) all need to know which option side "ATM" refers to --
    the spec's lettering is a list of conditions, not a mandated evaluation
    order, and Gamma is side-independent under Black-76 so this doesn't
    change what (a)/(b) actually test)."""
    filters = {}

    direction = select_direction(market["spot"], market["prev_close"], market.get("ema20_15m"))
    filters["direction"] = direction
    if direction is None:
        return {"qualifies": False, "reason": "no directional edge (spot/prev-close/EMA not aligned)",
                "filters": filters, "direction": None, "selected": None}

    cfg = config["convexity_window"]

    atm_iv = market.get("atm_iv")
    realized_vol = market.get("realized_vol")
    filters["atm_iv"] = atm_iv
    filters["realized_vol"] = realized_vol
    if not atm_iv or not realized_vol:
        return {"qualifies": False, "reason": "IV or realized vol not available yet",
                "filters": filters, "direction": direction, "selected": None}
    iv_rv_ratio = atm_iv / realized_vol
    filters["iv_rv_ratio"] = iv_rv_ratio
    if iv_rv_ratio >= cfg["iv_rv_ratio_max"]:
        return {"qualifies": False, "reason": f"IV/RV {iv_rv_ratio:.3f} >= cap {cfg['iv_rv_ratio_max']} — convexity not cheap",
                "filters": filters, "direction": direction, "selected": None}

    req_move = required_move(market.get("atm_theta"), market.get("atm_gamma"))
    median_tr = market.get("median_true_range")
    filters["required_move"] = req_move
    filters["median_true_range"] = median_tr
    if req_move is None or median_tr is None:
        return {"qualifies": False, "reason": "required-move or true-range history not available yet",
                "filters": filters, "direction": direction, "selected": None}
    move_threshold = cfg["required_move_multiplier"] * median_tr
    filters["required_move_threshold"] = move_threshold
    if req_move >= move_threshold:
        return {"qualifies": False,
                "reason": f"required move {req_move:.2f} >= {move_threshold:.2f} ({cfg['required_move_multiplier']}x median true range) — not cheap enough",
                "filters": filters, "direction": direction, "selected": None}

    candidates = [c for c in market.get("candidates", [])
                  if c["option_type"] == direction and c["greeks"]["vega"] <= cfg["vega_cap"]]
    filters["candidate_count_within_vega_cap"] = len(candidates)
    if not candidates:
        return {"qualifies": False, "reason": f"no {direction} candidate within vega cap {cfg['vega_cap']}",
                "filters": filters, "direction": direction, "selected": None}

    def efficiency(c):
        theta = c["greeks"]["theta"]
        gamma = c["greeks"]["gamma"]
        return gamma / max(abs(theta), REQUIRED_MOVE_EPS)

    selected = max(candidates, key=efficiency)
    filters["selected_gamma_theta_ratio"] = efficiency(selected)

    return {"qualifies": True, "reason": "all entry filters passed", "filters": filters,
            "direction": direction, "selected": selected}


def evaluate_exit(current_premium: float, current_gamma: float, trade: dict, now_time_ist, time_stop_ist: str,
                   config: dict) -> dict:
    """Pure exit evaluation against the four exit rules (SL, target, time
    stop, Greeks stop). trade: {"entry_price", "entry_gamma", ...}.
    now_time_ist: a datetime.time. Checked in the order SL/target -> Greeks
    stop -> time stop, since a hard SL/target breach should win over a
    Greeks-stop reason if both are true on the same evaluation.

    Returns {"action": "exit", "exit_reason": str, "exit_price": float} or
    {"action": "hold"}."""
    cfg = config["convexity_window"]
    entry_price = trade["entry_price"]
    pnl_pct = (current_premium - entry_price) / entry_price

    if pnl_pct <= cfg["sl_pct"]:
        return {"action": "exit", "exit_reason": "stop_loss", "exit_price": current_premium}
    if pnl_pct >= cfg["target_pct"]:
        return {"action": "exit", "exit_reason": "target", "exit_price": current_premium}

    entry_gamma = trade.get("entry_gamma")
    if entry_gamma and entry_gamma > REQUIRED_MOVE_EPS and current_gamma is not None:
        if current_gamma < cfg["gamma_stop_ratio"] * entry_gamma:
            return {"action": "exit", "exit_reason": "greeks_stop_gamma_decay", "exit_price": current_premium}

    stop_h, stop_m = (int(x) for x in time_stop_ist.split(":"))
    if now_time_ist.hour > stop_h or (now_time_ist.hour == stop_h and now_time_ist.minute >= stop_m):
        return {"action": "exit", "exit_reason": "time_stop", "exit_price": current_premium}

    return {"action": "hold"}
