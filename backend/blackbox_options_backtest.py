"""
Backtest harness for Convexity Window / Gamma Backspread -- replays REAL
Definedge historical data through the exact same signal-logic functions
(blackbox_convexity_window / blackbox_gamma_backspread) the live/paper
engine uses. One implementation, not two (per explicit instruction).

HARD, VERIFIED DATA CONSTRAINT (same one already documented in
blackbox_backtest.py for Prism Alpha, confirmed live again 2026-07-29):
Definedge's symbol master only lists contracts that have NOT expired yet --
there is no way to resolve a token for an option whose expiry has already
passed. Combined with each strategy's DTE entry filter, this means a real
historical day is only backtestable if it falls BEFORE today AND the
CURRENTLY-listed (not-yet-expired) expiry's own real DTE on that past day
happened to already sit inside the strategy's DTE band. Concretely (checked
live against real Definedge data on 2026-07-29): NIFTY's nearest weekly
(expiry 2026-08-04) has DTE=6 today, which is *inside* Gamma Backspread's
[5,12] band right now, so its real 1-minute history over the past several
trading days IS genuinely backtestable for Gamma Backspread. But it is
*outside* Convexity Window's [1,4] band (that window is 2026-07-31 to
2026-08-03 -- in the future, not backtestable yet). BANKNIFTY only lists
monthly-cadence contracts (nearest: 2026-08-25, DTE=27) -- nowhere near
either strategy's band right now. This module does not work around that;
it walks whatever real days genuinely qualify and reports however few (or
zero) trades that produces, exactly as instructed ("do backtest with
whatever small data is available").

IV-percentile history (Gamma Backspread's 252-day filter) is built up
PROGRESSIVELY within the walk itself, in chronological order -- there is no
pre-existing ATM-IV history in this codebase, so day 1 of any walk starts
with zero samples and accumulates one real sample per real day walked.
Short-sample percentiles are real numbers, just statistically weak; that
weakness is reported, not hidden.
"""
import logging
from datetime import date, datetime, timedelta

from black76_greeks import price as b76_price, greeks as b76_greeks, implied_vol as b76_iv, years_to_expiry
from blackbox_options_data import (
    resolve_strike_tokens, list_strikes_near, resolve_futures_token,
    realized_vol, median_true_range, ema_series, aggregate_to_15min, percentile_rank,
)
from blackbox_options_market import STRIKE_INCREMENT, atm_strike
from blackbox_options_costs import evaluate_trade_costs
import blackbox_convexity_window as cw
import blackbox_gamma_backspread as gb
from definedge_service import INDEX_CONFIG, IST, DefinedgeError

logger = logging.getLogger(__name__)

BACKTEST_LOOKBACK_DAYS = 45  # generous cap; real yield is bounded by the DTE-band
                              # constraint above, not by this number, on any
                              # currently-listed contract.
ENTRY_CHECK_TIME = "09:30"


async def _fetch_minute_bars(definedge, segment: str, token: str, frm_dt: datetime, to_dt: datetime) -> list:
    """Same real 1-minute history endpoint used everywhere else in this
    codebase (blackbox_prism_alpha.fetch_minute_bars) -- reimplemented
    inline (not imported) only to avoid a cross-module dependency on a
    Prism-Alpha-specific file for a Black Box options module that has
    nothing else to do with Prism Alpha."""
    import httpx
    from definedge_service import DATA_BASE
    session = await definedge._session_key()
    frm = frm_dt.strftime("%d%m%Y%H%M")
    to = to_dt.strftime("%d%m%Y%H%M")
    url = f"{DATA_BASE}/history/{segment}/{token}/minute/{frm}/{to}"
    async with httpx.AsyncClient(timeout=45) as c:
        r = await c.get(url, headers={"Authorization": session})
    if r.status_code == 401:
        raise DefinedgeError("Definedge session expired. Please login again (OTP).")
    if r.status_code != 200:
        return []
    bars = []
    for line in r.text.strip().splitlines():
        parts = line.split(",")
        if len(parts) < 5:
            continue
        try:
            dt = datetime.strptime(parts[0], "%d%m%Y%H%M").replace(tzinfo=IST)
            bars.append({"dt": dt, "open": float(parts[1]), "high": float(parts[2]),
                         "low": float(parts[3]), "close": float(parts[4])})
        except ValueError:
            continue
    bars.sort(key=lambda b: b["dt"])
    return bars


def _bar_at_or_before(bars: list, when: datetime):
    candidates = [b for b in bars if b["dt"] <= when]
    return candidates[-1] if candidates else None


async def _historical_dte_days(index_key: str, dte_min: int, dte_max: int, today: date) -> list:
    """[{"expiry": date, "day": date, "dte": int}, ...] for every real,
    currently-resolvable expiry, restricted to PAST days only (never today
    or later -- today's/future days are the live/paper engine's job, not
    the backtest's) where that expiry's real DTE fell inside the band."""
    out = []
    for expiry in INDEX_CONFIG[index_key].get("_candidate_expiries", []):
        for back in range(1, BACKTEST_LOOKBACK_DAYS + 1):
            day = today - timedelta(days=back)
            if day.weekday() >= 5:
                continue
            dte = (expiry - day).days
            if dte_min <= dte <= dte_max:
                out.append({"expiry": expiry, "day": day, "dte": dte})
    out.sort(key=lambda x: x["day"])
    return out


async def _list_resolvable_expiries(df, index_key: str, today: date) -> list:
    import pandas as pd
    SYMBOL, INSTR, EXPIRY = 2, 4, 5
    sym = INDEX_CONFIG[index_key]["option_symbol"]
    sub = df[(df[SYMBOL].astype(str) == sym) & (df[INSTR].astype(str) == "OPTIDX")]
    exps = pd.to_datetime(sub[EXPIRY].astype(str), format="%d%m%Y", errors="coerce").dt.date.dropna().unique()
    return sorted(set(e for e in exps if e >= today))


async def _run(db, definedge, index_key: str, strategy_id: str, dte_min: int, dte_max: int, config: dict,
                gather_market_fn, evaluate_exit_fn) -> dict:
    """Shared walk skeleton for both strategies -- fetches real days-in-band,
    fetches real bars once per contract needed, replays entry/exit through
    the pure strategy functions, applies the shared cost model. Returns the
    full result dict (trades, stats, gross vs net, the real-data caveat)."""
    today = datetime.now(IST).date()
    df = await definedge._get_all_master()
    expiries = await _list_resolvable_expiries(df, index_key, today)
    INDEX_CONFIG[index_key]["_candidate_expiries"] = expiries  # scratch, cleared below
    try:
        days_in_band = await _historical_dte_days(index_key, dte_min, dte_max, today)
    finally:
        INDEX_CONFIG[index_key].pop("_candidate_expiries", None)

    result = {
        "index": index_key, "strategy_id": strategy_id,
        "real_days_in_dte_band": len(days_in_band),
        "days_examined": [{"expiry": d["expiry"].isoformat(), "day": d["day"].isoformat(), "dte": d["dte"]} for d in days_in_band],
        "trades": [], "run_at": datetime.now(IST).isoformat(),
    }
    if not days_in_band:
        result["note"] = (
            f"No real historical day currently qualifies: every Definedge-resolvable "
            f"{index_key} expiry's own real DTE never fell inside [{dte_min}, {dte_max}] "
            f"on any past day, because expired contracts can't be re-resolved via the "
            f"master (verified constraint) and today's live DTE hasn't reached that band "
            f"yet either. This will change as the calendar advances -- see module docstring."
        )
        return result

    spot_cfg = INDEX_CONFIG[index_key]
    frm_dt = datetime.combine(days_in_band[0]["day"], datetime.min.time(), tzinfo=IST)
    to_dt = datetime.now(IST)
    spot_bars = await _fetch_minute_bars(definedge, spot_cfg["spot_segment"], spot_cfg["spot_token"], frm_dt, to_dt)
    if not spot_bars:
        result["note"] = "Real spot 1-minute history fetch returned nothing for this window."
        return result

    daily_history = await definedge.daily_history(spot_cfg["spot_segment"], spot_cfg["spot_token"], years=1)

    # Real futures + option contract bars, fetched ONCE per (expiry) and
    # sliced per-day below -- never re-fetched per day.
    fut_bars_by_expiry = {}
    contract_bars = {}  # (expiry, strike, opt_type) -> real bars
    for d in days_in_band:
        expiry = d["expiry"]
        if expiry not in fut_bars_by_expiry:
            fut = resolve_futures_token(df, spot_cfg["option_symbol"], today)
            fut_bars_by_expiry[expiry] = await _fetch_minute_bars(definedge, spot_cfg["option_segment"], fut["token"], frm_dt, to_dt) if fut else []

    iv_history = []  # built progressively, chronologically, real-only
    r = config.get("risk_free_rate", 0.065)

    for d in days_in_band:
        day, expiry, dte = d["day"], d["expiry"], d["dte"]
        entry_h, entry_m = (int(x) for x in ENTRY_CHECK_TIME.split(":"))
        entry_dt = datetime.combine(day, datetime.min.time(), tzinfo=IST).replace(hour=entry_h, minute=entry_m)

        spot_bar = _bar_at_or_before(spot_bars, entry_dt)
        if spot_bar is None or spot_bar["dt"].date() != day:
            continue  # no real spot tick that day at/near entry time — skip, don't fake it

        fut_bars = fut_bars_by_expiry.get(expiry, [])
        fut_bar = _bar_at_or_before(fut_bars, entry_dt)
        F = fut_bar["close"] if fut_bar and fut_bar["dt"].date() == day else spot_bar["close"]

        atm = atm_strike(spot_bar["close"], index_key)
        prior_daily = [b for b in daily_history if b["date"] < day.isoformat()]
        prev_close = prior_daily[-1]["close"] if prior_daily else None
        rv = realized_vol([b["close"] for b in prior_daily], config.get("realized_vol_window_days", 20))
        mtr = median_true_range(prior_daily, config.get("true_range_window_days", 20))

        prior_15m_spot = [b for b in spot_bars if b["dt"] <= entry_dt]
        fifteen = aggregate_to_15min(prior_15m_spot)
        ema = ema_series([b["close"] for b in fifteen], config.get("ema_period_15m", 20))
        ema_now = ema[-1] if ema else None

        strike_range = config.get("strike_range_from_atm") or config.get("otm_strike_search_range", 2)
        strikes = list_strikes_near(atm, STRIKE_INCREMENT[index_key], max(strike_range, 2))

        candidates = {}
        for strike in strikes:
            for opt in ("CE", "PE"):
                key = (expiry, strike, opt)
                if key not in contract_bars:
                    tokens = resolve_strike_tokens(df, spot_cfg["option_symbol"], expiry, strike)
                    token = tokens.get(opt)
                    contract_bars[key] = await _fetch_minute_bars(definedge, spot_cfg["option_segment"], token, frm_dt, to_dt) if token else []
                bars = contract_bars[key]
                bar = _bar_at_or_before(bars, entry_dt)
                if bar is None or bar["dt"].date() != day or bar["close"] <= 0:
                    continue
                T = years_to_expiry(expiry, now=entry_dt)
                iv = b76_iv(bar["close"], F, strike, T, opt, r)
                g = b76_greeks(F, strike, T, iv, opt, r)
                candidates[key] = {"strike": strike, "expiry": expiry, "option_type": opt, "token": None,
                                    "premium": bar["close"], "greeks": g, "iv": iv}

        market, atm_iv_today = gather_market_fn(candidates, atm, spot_bar["close"], prev_close, ema_now, rv, mtr, iv_history, dte)
        if market is None:
            continue

        trade = evaluate_exit_fn(index_key, strategy_id, config, market, contract_bars, entry_dt, expiry, day, r)
        if atm_iv_today is not None:
            iv_history.append(atm_iv_today)
        if trade is not None:
            result["trades"].append(trade)

    result["stats"] = _compute_stats(result["trades"])
    return result


def _compute_stats(trades: list) -> dict:
    if not trades:
        return {"trade_count": 0, "note": "zero real trades — see real_days_in_dte_band / note above"}
    net_pnls = [t["net_pnl"] for t in trades]
    gross_pnls = [t["gross_pnl"] for t in trades]
    wins = [p for p in net_pnls if p > 0]
    losses = [p for p in net_pnls if p <= 0]
    win_rate = len(wins) / len(net_pnls)
    avg_win = sum(wins) / len(wins) if wins else 0.0
    avg_loss = sum(losses) / len(losses) if losses else 0.0
    gross_win = sum(wins)
    gross_loss = abs(sum(losses))
    profit_factor = (gross_win / gross_loss) if gross_loss > 0 else (float("inf") if gross_win > 0 else 0.0)
    cum, peak, max_dd = 0.0, 0.0, 0.0
    for p in net_pnls:
        cum += p
        peak = max(peak, cum)
        max_dd = min(max_dd, cum - peak)
    return {
        "trade_count": len(trades), "win_rate": win_rate, "avg_win": avg_win, "avg_loss": avg_loss,
        "profit_factor": profit_factor, "gross_pnl_total": sum(gross_pnls), "net_pnl_total": sum(net_pnls),
        "max_drawdown": max_dd,
        "sample_size_warning": len(trades) < 20,
    }


# ------------------------------------------------------------- Strategy 1

def _cw_gather(candidates, atm, spot, prev_close, ema_now, rv, mtr, iv_history, dte):
    atm_ce = candidates.get(list(k for k in candidates if k[1] == atm and k[2] == "CE"), None)
    all_candidates = list(candidates.values())
    atm_leg = next((c for c in all_candidates if c["strike"] == atm and c["option_type"] == "CE"), None)
    if atm_leg is None:
        return None, None
    market = {
        "spot": spot, "prev_close": prev_close, "ema20_15m": ema_now,
        "atm_iv": atm_leg["iv"], "realized_vol": rv,
        "atm_theta": atm_leg["greeks"]["theta"], "atm_gamma": atm_leg["greeks"]["gamma"],
        "median_true_range": mtr, "candidates": all_candidates,
    }
    return market, atm_leg["iv"]


def _cw_evaluate(index_key, strategy_id, config, market, contract_bars, entry_dt, expiry, day, r):
    check = cw.check_entry_filters(market, {"convexity_window": config})
    if not check["qualifies"]:
        return None
    sel = check["selected"]
    key = (expiry, sel["strike"], sel["option_type"])
    bars = [b for b in contract_bars.get(key, []) if b["dt"] >= entry_dt and b["dt"].date() == day]
    if not bars:
        return None

    entry_price = bars[0]["close"]
    entry_gamma = sel["greeks"]["gamma"]
    trade_state = {"entry_price": entry_price, "entry_gamma": entry_gamma}
    exit_price, exit_reason = entry_price, "data_ended"
    for bar in bars:
        F_bar = bar["close"]  # option's own premium is the exit-check series
        result = cw.evaluate_exit(F_bar, entry_gamma, trade_state, bar["dt"].time(), config["time_stop_ist"], {"convexity_window": config})
        if result["action"] == "exit":
            exit_price, exit_reason = result["exit_price"], result["exit_reason"]
            break
    else:
        exit_price = bars[-1]["close"]

    lot_size = None  # unresolved per index — see blackbox_options_config; costs computed per-unit, not per-lot, until set
    unit_costs = evaluate_trade_costs(
        [{"side": "long", "entry_price": entry_price, "exit_price": exit_price, "lots": 1}],
        lot_size=1, costs_cfg={"brokerage_per_lot": 0, "stt_sell_pct": 0.001, "exchange_txn_pct": 0.00053,
                                "sebi_fee_pct": 0.0000010, "gst_pct": 0.18, "slippage_pct": 0.02},
    )
    return {
        "index": index_key, "strategy_id": strategy_id, "date": day.isoformat(), "expiry": expiry.isoformat(),
        "strike": sel["strike"], "option_type": sel["option_type"],
        "entry_price": entry_price, "exit_price": exit_price, "exit_reason": exit_reason,
        "gross_pnl": unit_costs["gross_pnl"], "net_pnl": unit_costs["net_pnl"], "costs": unit_costs["total_costs"],
        "note": "per-unit (lot_size unset) — see blackbox_config.lot_size",
    }


async def backtest_convexity_window(db, definedge, index_key: str, config: dict = None) -> dict:
    from blackbox_options_config import default_config_for
    cfg_full = config or default_config_for(index_key)
    cfg = cfg_full["convexity_window"]
    return await _run(db, definedge, index_key, "convexity_window", cfg["dte_min"], cfg["dte_max"], cfg, _cw_gather, _cw_evaluate)


# ------------------------------------------------------------- Strategy 2

def _gb_gather(candidates, atm, spot, prev_close, ema_now, rv, mtr, iv_history, dte):
    all_candidates = list(candidates.values())
    atm_leg = next((c for c in all_candidates if c["strike"] == atm and c["option_type"] in ("CE", "PE")), None)
    if atm_leg is None:
        return None, None
    otm = [c for c in all_candidates if c["strike"] != atm]
    market = {
        "spot": spot, "prev_close": prev_close, "ema20_15m": ema_now,
        "atm_iv": atm_leg["iv"], "iv_history": list(iv_history),
        "atm": atm_leg, "otm_candidates": otm, "expiry": None, "dte": dte,
    }
    return market, atm_leg["iv"]


def _gb_evaluate(index_key, strategy_id, config, market, contract_bars, entry_dt, expiry, day, r):
    check = gb.check_entry_filters(market, {"gamma_backspread": config})
    if not check["qualifies"]:
        return None
    pkg = check["package"]
    atm_key = (expiry, pkg["atm"]["strike"], pkg["atm"]["option_type"])
    otm_key = (expiry, pkg["otm"]["strike"], pkg["otm"]["option_type"])
    atm_bars = [b for b in contract_bars.get(atm_key, []) if b["dt"] >= entry_dt and b["dt"].date() == day]
    otm_bars = [b for b in contract_bars.get(otm_key, []) if b["dt"] >= entry_dt and b["dt"].date() == day]
    if not atm_bars or not otm_bars:
        return None

    atm_entry, otm_entry = atm_bars[0]["close"], otm_bars[0]["close"]
    net_debit = 2 * otm_entry - atm_entry
    trade_state = {"net_debit": net_debit}
    n = min(len(atm_bars), len(otm_bars))
    exit_atm, exit_otm, exit_reason = atm_bars[-1]["close"], otm_bars[-1]["close"], "data_ended"
    for i in range(n):
        pkg_greeks = pkg["package_greeks"]  # static-Greeks approximation intraday — real Greeks recompute is
                                             # possible but expensive per-tick; flagged as a known simplification
        atm_iv_now = pkg["atm"]["iv"]
        result = gb.evaluate_exit(atm_bars[i]["close"], otm_bars[i]["close"], pkg_greeks, atm_iv_now,
                                   market["iv_history"], trade_state, dte=market["dte"], config={"gamma_backspread": config})
        if result["action"] == "exit":
            exit_atm, exit_otm, exit_reason = result["exit_price"]["atm"], result["exit_price"]["otm"], result["exit_reason"]
            break

    costs_cfg = {"brokerage_per_lot": 0, "stt_sell_pct": 0.001, "exchange_txn_pct": 0.00053,
                 "sebi_fee_pct": 0.0000010, "gst_pct": 0.18, "slippage_pct": 0.02}
    legs = [
        {"side": "short", "entry_price": atm_entry, "exit_price": exit_atm, "lots": 1},
        {"side": "long", "entry_price": otm_entry, "exit_price": exit_otm, "lots": 2},
    ]
    costs = evaluate_trade_costs(legs, lot_size=1, costs_cfg=costs_cfg)
    return {
        "index": index_key, "strategy_id": strategy_id, "date": day.isoformat(), "expiry": expiry.isoformat(),
        "atm_strike": pkg["atm"]["strike"], "otm_strike": pkg["otm"]["strike"], "option_type": pkg["atm"]["option_type"],
        "entry_net_debit": net_debit, "exit_reason": exit_reason,
        "gross_pnl": costs["gross_pnl"], "net_pnl": costs["net_pnl"], "costs": costs["total_costs"],
        "note": "per-unit (lot_size unset) — see blackbox_config.lot_size",
    }


async def backtest_gamma_backspread(db, definedge, index_key: str, config: dict = None) -> dict:
    from blackbox_options_config import default_config_for
    cfg_full = config or default_config_for(index_key)
    cfg = cfg_full["gamma_backspread"]
    return await _run(db, definedge, index_key, "gamma_backspread", cfg["dte_min"], cfg["dte_max"], cfg, _gb_gather, _gb_evaluate)
