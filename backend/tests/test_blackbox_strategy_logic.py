"""
Smoke tests for blackbox_convexity_window.py and blackbox_gamma_backspread.py
-- synthetic inputs (not live Definedge data) exercising both the "qualifies"
and every "doesn't qualify" / "doesn't exit yet" branch of each pure
function, plus every exit reason. These are signal-LOGIC tests (does the
gating/exit math do what the spec says given known inputs), not a
backtest -- Step 4's harness is where real historical data gets replayed.
"""
from datetime import date, time

import blackbox_convexity_window as cw
import blackbox_gamma_backspread as gb
from blackbox_options_config import DEFAULT_CONFIG


def _greeks(delta=0.5, gamma=0.001, theta=-2.0, vega=10.0):
    return {"delta": delta, "gamma": gamma, "theta": theta, "vega": vega}


# ---------------------------------------------------------------- Strategy 1

def test_cw_select_direction_ce_pe_and_none():
    assert cw.select_direction(24100, 24000, 24050) == "CE"
    assert cw.select_direction(23900, 24000, 23950) == "PE"
    assert cw.select_direction(24000, 24000, 24050) is None  # spot not above EMA
    assert cw.select_direction(24100, 24000, None) is None   # EMA not seeded yet


def test_cw_required_move_matches_formula_and_handles_zero_gamma():
    assert abs(cw.required_move(-4.0, 0.002) - (2 * 4.0 / 0.002) ** 0.5) < 1e-9
    assert cw.required_move(-4.0, 0.0) is None


def test_cw_entry_qualifies_when_all_filters_pass():
    market = {
        "spot": 24100, "prev_close": 24000, "ema20_15m": 24050,
        "atm_iv": 0.12, "realized_vol": 0.14,  # ratio ~0.857 < 0.95
        "atm_theta": -3.0, "atm_gamma": 0.002,  # required_move = sqrt(2*3/0.002) ~= 54.8
        "median_true_range": 100.0,             # threshold = 0.8*100 = 80 > 54.8 -> passes
        "candidates": [
            {"strike": 24100, "option_type": "CE", "token": "1", "premium": 120.0,
             "greeks": _greeks(gamma=0.0015, theta=-2.5, vega=15.0)},
            {"strike": 24200, "option_type": "CE", "token": "2", "premium": 60.0,
             "greeks": _greeks(gamma=0.0025, theta=-2.0, vega=12.0)},  # better gamma/|theta|
            {"strike": 24100, "option_type": "PE", "token": "3", "premium": 90.0,
             "greeks": _greeks(gamma=0.0015, theta=-2.5, vega=15.0)},
        ],
    }
    result = cw.check_entry_filters(market, DEFAULT_CONFIG)
    assert result["qualifies"] is True
    assert result["direction"] == "CE"
    assert result["selected"]["token"] == "2"  # highest gamma/|theta| among CE candidates


def test_cw_entry_rejects_on_iv_rv_too_rich():
    market = {
        "spot": 24100, "prev_close": 24000, "ema20_15m": 24050,
        "atm_iv": 0.20, "realized_vol": 0.14,  # ratio > 0.95
        "atm_theta": -3.0, "atm_gamma": 0.002, "median_true_range": 100.0,
        "candidates": [],
    }
    result = cw.check_entry_filters(market, DEFAULT_CONFIG)
    assert result["qualifies"] is False
    assert "IV/RV" in result["reason"]


def test_cw_entry_rejects_on_required_move_too_large():
    market = {
        "spot": 24100, "prev_close": 24000, "ema20_15m": 24050,
        "atm_iv": 0.10, "realized_vol": 0.14,
        "atm_theta": -20.0, "atm_gamma": 0.0005,  # required_move = sqrt(2*20/0.0005) huge
        "median_true_range": 100.0,
        "candidates": [],
    }
    result = cw.check_entry_filters(market, DEFAULT_CONFIG)
    assert result["qualifies"] is False
    assert "required move" in result["reason"]


def test_cw_entry_rejects_when_no_candidate_within_vega_cap():
    market = {
        "spot": 24100, "prev_close": 24000, "ema20_15m": 24050,
        "atm_iv": 0.10, "realized_vol": 0.14,
        "atm_theta": -3.0, "atm_gamma": 0.002, "median_true_range": 100.0,
        "candidates": [
            {"strike": 24100, "option_type": "CE", "token": "1", "premium": 120.0,
             "greeks": _greeks(vega=999.0)},  # over the default vega_cap of 50
        ],
    }
    result = cw.check_entry_filters(market, DEFAULT_CONFIG)
    assert result["qualifies"] is False
    assert "vega cap" in result["reason"]


def test_cw_exit_stop_loss_and_target():
    trade = {"entry_price": 100.0, "entry_gamma": 0.002}
    sl = cw.evaluate_exit(64.0, 0.002, trade, time(11, 0), "15:15", DEFAULT_CONFIG)  # -36%
    assert sl == {"action": "exit", "exit_reason": "stop_loss", "exit_price": 64.0}
    target = cw.evaluate_exit(171.0, 0.002, trade, time(11, 0), "15:15", DEFAULT_CONFIG)  # +71%
    assert target["action"] == "exit" and target["exit_reason"] == "target"


def test_cw_exit_greeks_stop_and_time_stop_and_hold():
    trade = {"entry_price": 100.0, "entry_gamma": 0.002}
    gstop = cw.evaluate_exit(105.0, 0.0009, trade, time(11, 0), "15:15", DEFAULT_CONFIG)  # gamma < 50% of entry
    assert gstop == {"action": "exit", "exit_reason": "greeks_stop_gamma_decay", "exit_price": 105.0}
    tstop = cw.evaluate_exit(105.0, 0.002, trade, time(15, 15), "15:15", DEFAULT_CONFIG)
    assert tstop["exit_reason"] == "time_stop"
    hold = cw.evaluate_exit(105.0, 0.002, trade, time(11, 0), "15:15", DEFAULT_CONFIG)
    assert hold == {"action": "hold"}


# ---------------------------------------------------------------- Strategy 2

def test_gb_package_greeks_sells_one_atm_buys_two_otm():
    atm = {"greeks": _greeks(delta=0.5, gamma=0.002, theta=-4.0, vega=20.0)}
    otm = {"greeks": _greeks(delta=0.2, gamma=0.0015, theta=-1.5, vega=10.0)}
    pkg = gb._package_greeks(atm, otm)
    assert abs(pkg["delta"] - (-0.5 + 2 * 0.2)) < 1e-9
    assert abs(pkg["gamma"] - (-0.002 + 2 * 0.0015)) < 1e-9
    assert abs(pkg["theta"] - (-(-4.0) + 2 * -1.5)) < 1e-9
    assert abs(pkg["vega"] - (-20.0 + 2 * 10.0)) < 1e-9


def test_gb_select_otm_strike_picks_closest_to_theta_neutral_within_band():
    cfg = DEFAULT_CONFIG["gamma_backspread"]  # band is [-0.05, 0.05]
    atm = {"greeks": _greeks(gamma=0.0020, theta=-4.00, vega=20.0)}
    candidates = [
        # net theta = -(-4.00) + 2*theta_otm ; net gamma = -0.0020 + 2*gamma_otm
        {"strike": 24200, "option_type": "CE", "token": "far",
         "greeks": _greeks(gamma=0.0011, theta=-1.90, vega=8.0)},   # net theta = 4.00-3.80=0.20 -> outside band
        {"strike": 24150, "option_type": "CE", "token": "close",
         "greeks": _greeks(gamma=0.0011, theta=-1.98, vega=8.0)},   # net theta = 4.00-3.96=0.04 -> inside band, closer to 0
        {"strike": 24100, "option_type": "CE", "token": "mid",
         "greeks": _greeks(gamma=0.0011, theta=-1.95, vega=8.0)},   # net theta = 4.00-3.90=0.10 -> outside band
    ]
    best = gb._select_otm_strike(atm, candidates, cfg)
    assert best is not None
    assert best["otm"]["token"] == "close"


def test_gb_entry_qualifies_when_all_filters_pass():
    market = {
        "spot": 24100, "prev_close": 24000, "ema20_15m": 24050,
        "atm_iv": 0.12, "iv_history": [0.10 + 0.001 * i for i in range(300)],  # atm_iv near low end -> low percentile
        "dte": 8,
        "atm": {"strike": 24100, "option_type": "CE", "token": "atm1", "premium": 150.0,
                "greeks": _greeks(gamma=0.0020, theta=-4.00, vega=20.0)},
        "otm_candidates": [
            # net vega = -20 + 2*12 = 4 > 0 (package must have positive net vega)
            {"strike": 24150, "option_type": "CE", "token": "otm1", "premium": 60.0,
             "greeks": _greeks(gamma=0.0011, theta=-1.98, vega=12.0)},
        ],
    }
    result = gb.check_entry_filters(market, DEFAULT_CONFIG)
    assert result["qualifies"] is True
    assert result["package"]["otm"]["token"] == "otm1"


def test_gb_entry_rejects_on_dte_out_of_range():
    market = {
        "spot": 24100, "prev_close": 24000, "ema20_15m": 24050,
        "atm_iv": 0.12, "iv_history": [0.10] * 300, "dte": 20,
        "atm": None, "otm_candidates": [],
    }
    result = gb.check_entry_filters(market, DEFAULT_CONFIG)
    assert result["qualifies"] is False
    assert "DTE" in result["reason"]


def test_gb_entry_rejects_on_iv_percentile_too_high():
    market = {
        "spot": 24100, "prev_close": 24000, "ema20_15m": 24050,
        "atm_iv": 0.50, "iv_history": [0.10 + 0.001 * i for i in range(300)],  # 0.50 is above all history -> ~100th pctile
        "dte": 8, "atm": None, "otm_candidates": [],
    }
    result = gb.check_entry_filters(market, DEFAULT_CONFIG)
    assert result["qualifies"] is False
    assert "IV percentile" in result["reason"]


def test_gb_entry_rejects_without_iv_history():
    market = {
        "spot": 24100, "prev_close": 24000, "ema20_15m": 24050,
        "atm_iv": 0.12, "iv_history": [], "dte": 8, "atm": None, "otm_candidates": [],
    }
    result = gb.check_entry_filters(market, DEFAULT_CONFIG)
    assert result["qualifies"] is False
    assert "history" in result["reason"]


def test_gb_exit_theta_drift_dte_cutoff_sl_target_iv_repriced_and_hold():
    cfg = DEFAULT_CONFIG
    trade = {"net_debit": 40.0}  # paid 2*otm - atm = net debit of 40

    drift = gb.evaluate_exit(150.0, 60.0, {"theta": -0.20, "gamma": 0.001, "vega": 5}, 0.12, [0.1] * 300,
                              trade, dte=8, config=cfg)
    assert drift["exit_reason"] == "theta_drift"

    dte_cut = gb.evaluate_exit(150.0, 60.0, {"theta": 0.0, "gamma": 0.001, "vega": 5}, 0.12, [0.1] * 300,
                                trade, dte=2, config=cfg)
    assert dte_cut["exit_reason"] == "dte_cutoff"

    # net_debit=40; current_value = 2*otm - atm; SL at -25% => current_value <= 30
    sl = gb.evaluate_exit(200.0, 60.0, {"theta": 0.0, "gamma": 0.001, "vega": 5}, 0.12, [0.1] * 300,
                           trade, dte=8, config=cfg)
    assert sl["exit_reason"] == "stop_loss"

    # target at +40% => current_value >= 56
    target = gb.evaluate_exit(20.0, 40.0, {"theta": 0.0, "gamma": 0.001, "vega": 5}, 0.12, [0.1] * 300,
                               trade, dte=8, config=cfg)
    assert target["exit_reason"] == "target"

    # current_value = 2*65-90 = 40 -> pnl_pct = 0.0, inside [-0.25, 0.40] so SL/target
    # don't fire -- isolates the IV-percentile check. atm_iv=0.90 vs a graduated
    # history maxing at ~0.399 -> percentile 100, well above the 60 exit cutoff.
    repriced = gb.evaluate_exit(90.0, 65.0, {"theta": 0.0, "gamma": 0.001, "vega": 5}, 0.90, [0.1] * 300,
                                 trade, dte=8, config=cfg)
    assert repriced["exit_reason"] == "iv_repriced"

    # current_value = 2*62-90 = 34 -> pnl_pct = -0.15, inside the SL/target band;
    # atm_iv=0.12 sits at the ~7th percentile of the graduated history -> well
    # below the 60 exit cutoff -- nothing should fire.
    graduated_history = [0.10 + 0.001 * i for i in range(300)]
    hold = gb.evaluate_exit(90.0, 62.0, {"theta": 0.0, "gamma": 0.001, "vega": 5}, 0.12, graduated_history,
                             trade, dte=8, config=cfg)
    assert hold == {"action": "hold"}
