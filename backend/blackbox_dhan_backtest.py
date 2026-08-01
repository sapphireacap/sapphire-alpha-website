"""
Dhan-based backtest harness for Convexity Window / Gamma Backspread --
replays REAL, already-expired option premium data (via dhan_client.py)
through the exact same pure signal functions the live/paper engine uses
(blackbox_convexity_window.py / blackbox_gamma_backspread.py). One
implementation, not two -- same principle as blackbox_options_backtest.py
(the Definedge version), which this module deliberately mirrors in
structure. Dhan exists ONLY for this backtest, because it can return real
data for contracts that have already expired -- Definedge structurally
cannot (verified live, see blackbox_options_backtest.py's docstring).

REAL, VERIFIED DEPTH CONSTRAINT (2026-07-31, not assumed): Dhan's
expired_options_data() only covers the last ~3-4 expiry cycles
(expiry_code 0-3, SDK-enforced). For NIFTY weekly options that's roughly
the last month. This is a genuine improvement over Definedge (which has
ZERO expired-contract coverage) but is not deep history -- reported
honestly in the results, not oversold.

Each option leg's own bars carry Dhan's REAL, per-minute resolved `strike`
and `spot` (requested explicitly, verified live to be populated) -- used
directly for Greeks and the ATM strike, rather than a locally-approximated
"round(spot / increment)" guess that could disagree with Dhan's own
day-by-day ATM reference and silently misprice a leg's Greeks.

Gamma Backspread's IV-percentile-over-252-days entry filter has NO real
data source deep enough to satisfy it (neither Dhan nor Definedge). Per
explicit instruction, this harness does NOT fabricate a percentile: IV
history is built PROGRESSIVELY within the walk itself (day 1 has zero
samples, each subsequent real day adds one), exactly mirroring how the
live/paper engine would actually accumulate it starting today. Trades in
the first few weeks of any walk are flagged with a low-sample-size
percentile; that weakness is surfaced, not hidden.

Gamma Backspread's OTM strike search is deliberately narrowed to +/-5
strikes (not the full otm_strike_search_range, typically 10) for this
backtest specifically, to keep the real Dhan API call volume for the
strike search within reason given observed rate limits -- disclosed in
the result, not silent.
"""
import asyncio
import logging
from datetime import date, datetime, timedelta

import dhan_client
from black76_greeks import greeks as b76_greeks, implied_vol as b76_iv, years_to_expiry
from blackbox_options_data import realized_vol, median_true_range, ema_series, aggregate_to_15min, percentile_rank
from blackbox_options_costs import evaluate_trade_costs
from blackbox_options_config import get_config
import blackbox_convexity_window as cw
import blackbox_gamma_backspread as gb

logger = logging.getLogger(__name__)
IST = dhan_client.IST

STRIKE_INCREMENT = {"NIFTY": 50, "BANKNIFTY": 100}
GB_BACKTEST_OTM_RANGE = 5  # narrowed from the live default (typically 10) -- see module docstring
DHAN_CALL_SLEEP = 0.6  # seconds between sequential Dhan calls, on top of dhan_client's own retry backoff -- keeps us well under their observed rate limit rather than only reacting to it after the fact


def _bar_at_or_before(bars: list, when: datetime):
    candidates = [b for b in bars if b["dt"] <= when]
    return candidates[-1] if candidates else None


async def _fetch_leg(index_key: str, expiry_flag: str, expiry_code: int, strike_label: str, dhan_type: str,
                      from_date: date, to_date: date, interval: int = 1) -> list:
    await asyncio.sleep(DHAN_CALL_SLEEP)
    result = await dhan_client.expired_option_bars(index_key, expiry_flag, expiry_code, strike_label, dhan_type, from_date, to_date, interval)
    return result["bars"]


def _strike_label(offset: int) -> str:
    if offset == 0:
        return "ATM"
    return f"ATM+{offset}" if offset > 0 else f"ATM{offset}"


def _estimate_cycle_window(expiry_flag: str, expiry_code: int, today: date) -> tuple:
    """Dhan's expired-options endpoint needs a NARROW, roughly cycle-
    aligned date window -- verified live (2026-07-31): a wide 70-day
    'search the last N weeks' span was rejected ("bad values"), while a
    ~10-day window aligned to the actual cycle worked cleanly and returned
    a full, non-clipped cycle both times (200 bars @ 15-min == 3000 bars
    @ 1-min, both exactly 8 trading days' worth). There's no documented way
    to ask "give me code N's real calendar range" directly, so this
    estimates it from two REAL, tested data points, not a single guess:
    code=2 -> real cycle ending 2026-07-10; code=1 -> real cycle ending
    2026-07-17. That's 7 real days apart, giving end_estimate = today -
    7*(code+1) for WEEK (verified against both known points, not
    extrapolated from only one). MONTH's 30-day cadence is NOT yet
    independently verified the same way -- padded more generously to
    compensate for that lower confidence."""
    if expiry_flag == "WEEK":
        end_estimate = today - timedelta(days=7 * (expiry_code + 1))
        return end_estimate - timedelta(days=9), end_estimate + timedelta(days=3)
    end_estimate = today - timedelta(days=30 * expiry_code)
    return end_estimate - timedelta(days=25), end_estimate + timedelta(days=15)


async def _discover_cycle(index_key: str, expiry_flag: str, expiry_code: int, search_from: date, search_to: date) -> dict | None:
    """Real ATM CALL bars for one rolling cycle, used to discover the
    cycle's actual real calendar window and infer its expiry date (the
    last real trading day -- NSE weekly/monthly options trade right
    through expiry). Returns None if this cycle has no real data inside
    the search window (nothing to fake)."""
    bars = await _fetch_leg(index_key, expiry_flag, expiry_code, "ATM", "CALL", search_from, search_to, interval=15)
    if not bars:
        return None
    days = sorted({b["dt"].date() for b in bars})
    return {"first_day": days[0], "last_day": days[-1], "inferred_expiry": days[-1], "trading_days": days, "atm_bars": bars}


def _quote_from_leg(leg_bars: list, day: date, entry_dt: datetime, T: float, option_type: str, r: float) -> dict | None:
    """Builds one candidate's real premium + Black-76 Greeks from a leg's
    own bars, using DHAN'S OWN real strike/spot carried on that exact bar
    -- never a locally re-derived guess."""
    bars_today = [b for b in leg_bars if b["dt"].date() == day]
    bar = _bar_at_or_before(bars_today, entry_dt)
    if bar is None or bar["close"] <= 0 or bar.get("strike") is None or bar.get("spot") is None:
        return None
    strike, spot = bar["strike"], bar["spot"]
    iv = b76_iv(bar["close"], spot, strike, T, option_type, r)
    g = b76_greeks(spot, strike, T, iv, option_type, r)
    return {"strike": strike, "spot": spot, "option_type": option_type, "premium": bar["close"], "greeks": g, "iv": iv, "dt": bar["dt"]}


def _compute_stats(trades: list) -> dict:
    if not trades:
        return {"trade_count": 0, "note": "zero real trades in this window"}
    net_pnls = [t["net_pnl"] for t in trades]
    gross_pnls = [t["gross_pnl"] for t in trades]
    wins = [p for p in net_pnls if p > 0]
    losses = [p for p in net_pnls if p <= 0]
    win_rate = len(wins) / len(net_pnls)
    avg_win = sum(wins) / len(wins) if wins else 0.0
    avg_loss = sum(losses) / len(losses) if losses else 0.0
    gross_win, gross_loss = sum(wins), abs(sum(losses))
    profit_factor = (gross_win / gross_loss) if gross_loss > 0 else (float("inf") if gross_win > 0 else 0.0)
    cum, peak, max_dd = 0.0, 0.0, 0.0
    for p in net_pnls:
        cum += p
        peak = max(peak, cum)
        max_dd = min(max_dd, cum - peak)
    return {
        "trade_count": len(trades), "win_rate": win_rate, "avg_win": avg_win, "avg_loss": avg_loss,
        "profit_factor": profit_factor, "gross_pnl_total": sum(gross_pnls), "net_pnl_total": sum(net_pnls),
        "max_drawdown": max_dd, "sample_size_warning": len(trades) < 20,
    }


# ------------------------------------------------------------- Strategy 1

async def backtest_convexity_window_dhan(db, index_key: str, max_cycles: int = dhan_client.MAX_EXPIRY_CODE + 1,
                                          today: date = None) -> dict:
    today = today or datetime.now(IST).date()
    cfg_full = await get_config(db, index_key)
    cfg = cfg_full["convexity_window"]
    r = cfg_full.get("risk_free_rate", 0.065)
    lot_size = cfg_full.get("lot_size") or 1

    trades, cycles_examined = [], []
    for expiry_code in range(dhan_client.MIN_EXPIRY_CODE, min(max_cycles, dhan_client.MAX_EXPIRY_CODE) + 1):
        search_from, search_to = _estimate_cycle_window("WEEK", expiry_code, today)
        cycle = await _discover_cycle(index_key, "WEEK", expiry_code, search_from, search_to)
        if cycle is None:
            cycles_examined.append({"expiry_code": expiry_code, "found": False})
            continue
        cycles_examined.append({"expiry_code": expiry_code, "found": True,
                                 "first_day": cycle["first_day"].isoformat(), "inferred_expiry": cycle["inferred_expiry"].isoformat()})

        days_in_band = [d for d in cycle["trading_days"] if cfg["dte_min"] <= (cycle["inferred_expiry"] - d).days <= cfg["dte_max"]]
        if not days_in_band:
            continue

        # Real daily index history (well before the cycle, for realized
        # vol / true range) and real 15-min index bars spanning the cycle
        # (for the EMA direction filter) -- separate from the option legs'
        # own per-bar spot, since those only start once the cycle itself
        # began trading.
        daily_hist = await dhan_client.index_daily_history(index_key, cycle["first_day"] - timedelta(days=60), today)
        intraday_15m = await dhan_client.index_intraday_bars(index_key, cycle["first_day"] - timedelta(days=5), cycle["last_day"], interval=15)

        offsets = list(range(-cfg["strike_range_from_atm"], cfg["strike_range_from_atm"] + 1))
        leg_bars = {}
        for off in offsets:
            label = _strike_label(off)
            for dhan_type, opt in (("CALL", "CE"), ("PUT", "PE")):
                leg_bars[(off, opt)] = await _fetch_leg(index_key, "WEEK", expiry_code, label, dhan_type, cycle["first_day"], cycle["last_day"], interval=1)

        for day in days_in_band:
            entry_dt = datetime.combine(day, datetime.min.time(), tzinfo=IST).replace(hour=9, minute=30)
            dte = (cycle["inferred_expiry"] - day).days
            T_entry = years_to_expiry(cycle["inferred_expiry"], now=entry_dt)

            atm_ce = _quote_from_leg(leg_bars.get((0, "CE"), []), day, entry_dt, T_entry, "CE", r)
            if atm_ce is None:
                continue
            spot = atm_ce["spot"]

            prior_daily = [b for b in daily_hist if b["date"] < day.isoformat()]
            prev_close = prior_daily[-1]["close"] if prior_daily else None
            rv = realized_vol([b["close"] for b in prior_daily], cfg["realized_vol_window_days"])
            mtr = median_true_range(prior_daily, cfg["true_range_window_days"])

            prior_15m = [b for b in intraday_15m if b["dt"] <= entry_dt]
            fifteen_closes = [b["close"] for b in aggregate_to_15min(prior_15m)]
            ema = ema_series(fifteen_closes, cfg["ema_period_15m"])
            ema_now = ema[-1] if ema else None

            candidates = []
            for off in offsets:
                for opt in ("CE", "PE"):
                    q = _quote_from_leg(leg_bars.get((off, opt), []), day, entry_dt, T_entry, opt, r)
                    if q is not None:
                        q["_offset"] = off
                        candidates.append(q)

            market = {
                "spot": spot, "prev_close": prev_close, "ema20_15m": ema_now,
                "atm_iv": atm_ce["iv"], "realized_vol": rv,
                "atm_theta": atm_ce["greeks"]["theta"], "atm_gamma": atm_ce["greeks"]["gamma"],
                "median_true_range": mtr, "candidates": candidates,
            }
            check = cw.check_entry_filters(market, {"convexity_window": cfg})
            if not check["qualifies"]:
                continue

            sel = check["selected"]
            sel_bars_today = sorted(
                [b for b in leg_bars.get((sel["_offset"], sel["option_type"]), []) if b["dt"].date() == day and b["dt"] >= entry_dt],
                key=lambda b: b["dt"],
            )
            if not sel_bars_today:
                continue
            entry_price = sel_bars_today[0]["close"]
            entry_gamma = sel["greeks"]["gamma"]
            trade_state = {"entry_price": entry_price, "entry_gamma": entry_gamma}
            exit_price, exit_reason = sel_bars_today[-1]["close"], "data_ended"
            for bar in sel_bars_today:
                result = cw.evaluate_exit(bar["close"], entry_gamma, trade_state, bar["dt"].time(), cfg["time_stop_ist"], {"convexity_window": cfg})
                if result["action"] == "exit":
                    exit_price, exit_reason = result["exit_price"], result["exit_reason"]
                    break

            costs = evaluate_trade_costs(
                [{"side": "long", "entry_price": entry_price, "exit_price": exit_price, "lots": 1}],
                lot_size=lot_size, costs_cfg=cfg_full["costs"],
            )
            trades.append({
                "index": index_key, "strategy_id": "convexity_window", "date": day.isoformat(),
                "expiry_code": expiry_code, "inferred_expiry": cycle["inferred_expiry"].isoformat(), "dte": dte,
                "strike": sel["strike"], "option_type": sel["option_type"],
                "entry_price": entry_price, "exit_price": exit_price, "exit_reason": exit_reason,
                "gross_pnl": costs["gross_pnl"], "net_pnl": costs["net_pnl"], "costs": costs["total_costs"],
            })

    return {
        "index": index_key, "strategy_id": "convexity_window", "data_source": "dhan_expired_options",
        "cycles_examined": cycles_examined, "trades": trades, "stats": _compute_stats(trades),
        "run_at": datetime.now(IST).isoformat(),
    }


# ------------------------------------------------------------- Strategy 2

async def backtest_gamma_backspread_dhan(db, index_key: str, max_cycles: int = dhan_client.MAX_EXPIRY_CODE + 1,
                                          today: date = None) -> dict:
    today = today or datetime.now(IST).date()
    cfg_full = await get_config(db, index_key)
    cfg = cfg_full["gamma_backspread"]
    r = cfg_full.get("risk_free_rate", 0.065)
    lot_size = cfg_full.get("lot_size") or 1
    expiry_flag = "MONTH" if index_key == "BANKNIFTY" else "WEEK"

    trades, cycles_examined = [], []
    iv_history = []  # built progressively across the whole chronological walk -- see module docstring

    for expiry_code in range(dhan_client.MIN_EXPIRY_CODE, min(max_cycles, dhan_client.MAX_EXPIRY_CODE) + 1):
        search_from, search_to = _estimate_cycle_window(expiry_flag, expiry_code, today)
        cycle = await _discover_cycle(index_key, expiry_flag, expiry_code, search_from, search_to)
        if cycle is None:
            cycles_examined.append({"expiry_code": expiry_code, "found": False})
            continue
        cycles_examined.append({"expiry_code": expiry_code, "found": True,
                                 "first_day": cycle["first_day"].isoformat(), "inferred_expiry": cycle["inferred_expiry"].isoformat()})

        days_in_band = [d for d in cycle["trading_days"] if cfg["dte_min"] <= (cycle["inferred_expiry"] - d).days <= cfg["dte_max"]]
        if not days_in_band:
            continue

        daily_hist = await dhan_client.index_daily_history(index_key, cycle["first_day"] - timedelta(days=60), today)
        intraday_15m = await dhan_client.index_intraday_bars(index_key, cycle["first_day"] - timedelta(days=5), cycle["last_day"], interval=15)

        offsets = list(range(-GB_BACKTEST_OTM_RANGE, GB_BACKTEST_OTM_RANGE + 1))
        leg_bars = {}
        for off in offsets:
            label = _strike_label(off)
            for dhan_type, opt in (("CALL", "CE"), ("PUT", "PE")):
                leg_bars[(off, opt)] = await _fetch_leg(index_key, expiry_flag, expiry_code, label, dhan_type, cycle["first_day"], cycle["last_day"], interval=1)

        open_position = None  # at most one open Gamma Backspread position per index at a time, mirrors the live engine

        for day in sorted(days_in_band):
            entry_dt = datetime.combine(day, datetime.min.time(), tzinfo=IST).replace(hour=9, minute=30)
            dte = (cycle["inferred_expiry"] - day).days
            T_entry = years_to_expiry(cycle["inferred_expiry"], now=entry_dt)

            atm_ce = _quote_from_leg(leg_bars.get((0, "CE"), []), day, entry_dt, T_entry, "CE", r)
            if atm_ce is None:
                continue
            spot = atm_ce["spot"]
            atm_iv_today = atm_ce["iv"]

            if open_position is None:
                prior_daily = [b for b in daily_hist if b["date"] < day.isoformat()]
                prev_close = prior_daily[-1]["close"] if prior_daily else None

                prior_15m = [b for b in intraday_15m if b["dt"] <= entry_dt]
                fifteen_closes = [b["close"] for b in aggregate_to_15min(prior_15m)]
                ema = ema_series(fifteen_closes, cfg["ema_period_15m"])
                ema_now = ema[-1] if ema else None

                direction = gb.select_direction(spot, prev_close, ema_now) if prev_close is not None else None
                atm_leg, otm_candidates = None, []
                if direction is not None:
                    atm_leg = _quote_from_leg(leg_bars.get((0, direction), []), day, entry_dt, T_entry, direction, r)
                    for off in offsets:
                        if off == 0:
                            continue
                        q = _quote_from_leg(leg_bars.get((off, direction), []), day, entry_dt, T_entry, direction, r)
                        if q is not None:
                            q["_offset"] = off
                            otm_candidates.append(q)

                market = {
                    "spot": spot, "prev_close": prev_close, "ema20_15m": ema_now,
                    "atm_iv": atm_leg["iv"] if atm_leg else atm_iv_today,
                    "iv_history": list(iv_history), "atm": atm_leg, "otm_candidates": otm_candidates,
                    "expiry": cycle["inferred_expiry"], "dte": dte,
                }
                check = gb.check_entry_filters(market, {"gamma_backspread": cfg})
                if check["qualifies"]:
                    pkg = check["package"]
                    atm_entry, otm_entry = pkg["atm"]["premium"], pkg["otm"]["premium"]
                    open_position = {
                        "entry_day": day, "atm_strike": pkg["atm"]["strike"], "otm_strike": pkg["otm"]["strike"],
                        "option_type": direction, "atm_entry": atm_entry, "otm_entry": otm_entry,
                        "net_debit": 2 * otm_entry - atm_entry, "otm_off": pkg["otm"]["_offset"],
                    }
            else:
                # Position already open -- re-quote both legs today using the
                # SAME relative-offset keys they were entered at (Dhan keeps
                # resolving "ATM+N" against ITS OWN day-by-day ATM, so this
                # naturally follows the position's actual listed strikes,
                # not a fixed absolute strike).
                cur_atm = _quote_from_leg(leg_bars.get((0, open_position["option_type"]), []), day, entry_dt, T_entry, open_position["option_type"], r)
                cur_otm = _quote_from_leg(leg_bars.get((open_position["otm_off"], open_position["option_type"]), []), day, entry_dt, T_entry, open_position["option_type"], r) if open_position["otm_off"] is not None else None
                if cur_atm is None or cur_otm is None:
                    iv_history.append(atm_iv_today)
                    continue
                pkg_greeks = {
                    "delta": -cur_atm["greeks"]["delta"] + 2 * cur_otm["greeks"]["delta"],
                    "gamma": -cur_atm["greeks"]["gamma"] + 2 * cur_otm["greeks"]["gamma"],
                    "theta": -cur_atm["greeks"]["theta"] + 2 * cur_otm["greeks"]["theta"],
                    "vega": -cur_atm["greeks"]["vega"] + 2 * cur_otm["greeks"]["vega"],
                }
                trade_state = {"net_debit": open_position["net_debit"]}
                result = gb.evaluate_exit(cur_atm["premium"], cur_otm["premium"], pkg_greeks, cur_atm["iv"],
                                           list(iv_history), trade_state, dte=dte, config={"gamma_backspread": cfg})
                if result["action"] == "exit":
                    legs = [
                        {"side": "short", "entry_price": open_position["atm_entry"], "exit_price": result["exit_price"]["atm"], "lots": 1},
                        {"side": "long", "entry_price": open_position["otm_entry"], "exit_price": result["exit_price"]["otm"], "lots": 2},
                    ]
                    costs = evaluate_trade_costs(legs, lot_size=lot_size, costs_cfg=cfg_full["costs"])
                    trades.append({
                        "index": index_key, "strategy_id": "gamma_backspread",
                        "entry_date": open_position["entry_day"].isoformat(), "exit_date": day.isoformat(),
                        "expiry_code": expiry_code, "inferred_expiry": cycle["inferred_expiry"].isoformat(),
                        "atm_strike": open_position["atm_strike"], "otm_strike": open_position["otm_strike"],
                        "option_type": open_position["option_type"], "exit_reason": result["exit_reason"],
                        "gross_pnl": costs["gross_pnl"], "net_pnl": costs["net_pnl"], "costs": costs["total_costs"],
                        "iv_history_samples_at_entry": len(iv_history),
                    })
                    open_position = None

            iv_history.append(atm_iv_today)

        if open_position is not None:
            # Cycle's real data ran out with a position still open -- force-
            # close at the last real available bar rather than silently
            # drop it from the stats.
            last_day = days_in_band[-1]
            last_entry_dt = datetime.combine(last_day, datetime.min.time(), tzinfo=IST).replace(hour=15, minute=25)
            T_last = years_to_expiry(cycle["inferred_expiry"], now=last_entry_dt)
            cur_atm = _quote_from_leg(leg_bars.get((0, open_position["option_type"]), []), last_day, last_entry_dt, T_last, open_position["option_type"], r)
            cur_otm = _quote_from_leg(leg_bars.get((open_position["otm_off"], open_position["option_type"]), []), last_day, last_entry_dt, T_last, open_position["option_type"], r) if open_position["otm_off"] is not None else None
            if cur_atm and cur_otm:
                legs = [
                    {"side": "short", "entry_price": open_position["atm_entry"], "exit_price": cur_atm["premium"], "lots": 1},
                    {"side": "long", "entry_price": open_position["otm_entry"], "exit_price": cur_otm["premium"], "lots": 2},
                ]
                costs = evaluate_trade_costs(legs, lot_size=lot_size, costs_cfg=cfg_full["costs"])
                trades.append({
                    "index": index_key, "strategy_id": "gamma_backspread",
                    "entry_date": open_position["entry_day"].isoformat(), "exit_date": last_day.isoformat(),
                    "expiry_code": expiry_code, "inferred_expiry": cycle["inferred_expiry"].isoformat(),
                    "atm_strike": open_position["atm_strike"], "otm_strike": open_position["otm_strike"],
                    "option_type": open_position["option_type"], "exit_reason": "data_ended",
                    "gross_pnl": costs["gross_pnl"], "net_pnl": costs["net_pnl"], "costs": costs["total_costs"],
                    "iv_history_samples_at_entry": None,
                })

    return {
        "index": index_key, "strategy_id": "gamma_backspread", "data_source": "dhan_expired_options",
        "otm_search_range_used": GB_BACKTEST_OTM_RANGE, "otm_search_range_live_default": cfg["otm_strike_search_range"],
        "cycles_examined": cycles_examined, "trades": trades, "stats": _compute_stats(trades),
        "run_at": datetime.now(IST).isoformat(),
    }
