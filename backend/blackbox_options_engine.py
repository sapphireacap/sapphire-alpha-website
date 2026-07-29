"""
Live/paper cron evaluator for Convexity Window / Gamma Backspread. Called by
the cron-secured POST /api/blackbox/options/evaluate route every 5 minutes
during market hours (GitHub Actions cadence -- same pattern as every other
cron-driven feature in this codebase; there is no real cron-job.org 1-minute
integration anywhere in this repo, confirmed).

MODE IS HARDCODED TO "paper". Going live is Build Order step 7, explicitly
gated on the user approving calibrated parameters AND a completed 30-session
paper run -- LIVE_MODE below is the one place that gate lives in code, and
it is never flipped automatically. No order-placement endpoint is ever
called by this module, paper or live -- "live" mode (once approved) would
still only ever WATCH real Definedge prices and log simulated fills, per
the spec's own framing of this as a signal/track-record product, not an
execution system.

Each call, per (index, strategy): if a position is open, evaluate its exit
against live Definedge quotes; if flat, evaluate entry ONCE per real day
(gated on ENTRY_CHECK_TIME having passed and not already checked today).
Always upserts `blackbox_strategy_status` so the frontend can show live
status without hitting Definedge itself. Trades are logged to
`blackbox_signals`, matching the spec's doc shape exactly.
"""
import logging
import uuid
from datetime import datetime, time as dt_time

from black76_greeks import price as b76_price, greeks as b76_greeks, years_to_expiry
from blackbox_options_config import get_config
from blackbox_options_market import (
    atm_strike, get_futures_price, get_contract_quote, build_candidates,
    get_realized_vol_and_true_range, get_15m_ema, record_atm_iv, get_iv_history,
)
from blackbox_options_costs import evaluate_trade_costs
from blackbox_options_data import list_candidate_expiries, resolve_strike_tokens
import blackbox_convexity_window as cw
import blackbox_gamma_backspread as gb
from definedge_service import INDEX_CONFIG, IST, DefinedgeError

logger = logging.getLogger(__name__)

LIVE_MODE = False  # <-- the one gate. Flips to True only after explicit user
                    # approval of calibrated parameters + a completed 30-session
                    # paper run (Build Order step 7). Never set anywhere else.
MODE = "paper" if not LIVE_MODE else "live"

MARKET_OPEN = dt_time(9, 15)
MARKET_CLOSE = dt_time(15, 30)
ENTRY_CHECK_TIME = dt_time(9, 30)
EOD_CLOSE_TIME = dt_time(15, 35)

STRATEGIES = ("convexity_window", "gamma_backspread")


def _in_market_hours(now: datetime) -> bool:
    return MARKET_OPEN <= now.time() <= MARKET_CLOSE


async def _pick_expiry_in_band(df, index_key: str, dte_min: int, dte_max: int, today) -> "date | None":
    expiries = list_candidate_expiries(df, INDEX_CONFIG[index_key]["option_symbol"], today, dte_min, dte_max)
    return expiries[0] if expiries else None


async def _upsert_status(db, index_key: str, strategy_id: str, status: str, reason: str, filters: dict = None,
                          open_trade_id: str = None) -> None:
    await db.blackbox_strategy_status.update_one(
        {"index": index_key, "strategy_id": strategy_id, "mode": MODE},
        {"$set": {
            "index": index_key, "strategy_id": strategy_id, "mode": MODE,
            "status": status, "reason": reason, "filters": filters or {},
            "open_trade_id": open_trade_id, "updated_at": datetime.now(IST).isoformat(),
        }},
        upsert=True,
    )


async def _open_trade(db, index_key: str, strategy_id: str) -> dict:
    return await db.blackbox_signals.find_one(
        {"index": index_key, "strategy_id": strategy_id, "mode": MODE, "status": "open"}, {"_id": 0}
    )


async def _already_checked_today(db, index_key: str, strategy_id: str, today_iso: str) -> bool:
    doc = await db.blackbox_strategy_status.find_one({"index": index_key, "strategy_id": strategy_id, "mode": MODE})
    return bool(doc and doc.get("last_entry_check_date") == today_iso)


async def _mark_checked_today(db, index_key: str, strategy_id: str, today_iso: str) -> None:
    await db.blackbox_strategy_status.update_one(
        {"index": index_key, "strategy_id": strategy_id, "mode": MODE},
        {"$set": {"last_entry_check_date": today_iso}}, upsert=True,
    )


# ------------------------------------------------------------- Strategy 1

async def _evaluate_convexity_window(db, definedge, df, index_key: str) -> dict:
    now = datetime.now(IST)
    today = now.date()
    today_iso = today.isoformat()
    cfg_full = await get_config(db, index_key)
    cfg = cfg_full["convexity_window"]
    r = cfg_full["risk_free_rate"]

    open_trade = await _open_trade(db, index_key, "convexity_window")
    if open_trade is not None:
        fut_now = await get_futures_price(df, definedge, index_key)
        q = await get_contract_quote(definedge, index_key, fut_now["F"] if fut_now else None, open_trade["strike"],
                                      datetime.fromisoformat(open_trade["expiry"]).date(),
                                      open_trade["side"], open_trade["option_token"], r) if fut_now else None
        if q is None:
            await _upsert_status(db, index_key, "convexity_window", "in_trade",
                                  "live quote unavailable this tick — holding, will retry", open_trade_id=open_trade["id"])
            return {"action": "quote_unavailable"}
        result = cw.evaluate_exit(q["premium"], q["greeks"]["gamma"],
                                   {"entry_price": open_trade["entry_price"], "entry_gamma": open_trade["entry_gamma"]},
                                   now.time(), cfg["time_stop_ist"], {"convexity_window": cfg})
        if result["action"] == "exit":
            costs = evaluate_trade_costs(
                [{"side": "long", "entry_price": open_trade["entry_price"], "exit_price": result["exit_price"], "lots": 1}],
                lot_size=cfg_full.get("lot_size") or 1, costs_cfg=cfg_full["costs"],
            )
            await db.blackbox_signals.update_one(
                {"id": open_trade["id"]},
                {"$set": {"status": "closed", "exit_price": result["exit_price"], "exit_reason": result["exit_reason"],
                          "exit_timestamp": now.isoformat(), "gross_pnl": costs["gross_pnl"], "costs": costs["total_costs"],
                          "net_pnl": costs["net_pnl"],
                          "pnl_pct": (result["exit_price"] - open_trade["entry_price"]) / open_trade["entry_price"]}},
            )
            await _upsert_status(db, index_key, "convexity_window", "flat", f"exited: {result['exit_reason']}")
            return {"action": "exited", "exit_reason": result["exit_reason"]}
        await _upsert_status(db, index_key, "convexity_window", "in_trade", "monitoring", open_trade_id=open_trade["id"])
        return {"action": "monitoring"}

    if now.time() < ENTRY_CHECK_TIME:
        await _upsert_status(db, index_key, "convexity_window", "flat", "before entry check time (09:30 IST)")
        return {"action": "too_early"}
    if await _already_checked_today(db, index_key, "convexity_window", today_iso):
        return {"action": "already_checked_today"}

    expiry = await _pick_expiry_in_band(df, index_key, cfg["dte_min"], cfg["dte_max"], today)
    if expiry is None:
        await _upsert_status(db, index_key, "convexity_window", "flat",
                              f"no listed expiry currently in DTE [{cfg['dte_min']},{cfg['dte_max']}]")
        await _mark_checked_today(db, index_key, "convexity_window", today_iso)
        return {"action": "no_expiry_in_band"}

    fut = await get_futures_price(df, definedge, index_key)
    rv_data = await get_realized_vol_and_true_range(definedge, index_key, cfg)
    ema = await get_15m_ema(definedge, index_key, cfg["ema_period_15m"])
    if fut is None:
        await _upsert_status(db, index_key, "convexity_window", "flat", "live futures price unavailable")
        await _mark_checked_today(db, index_key, "convexity_window", today_iso)
        return {"action": "no_futures_data"}

    spot = fut["F"]
    atm = atm_strike(spot, index_key)
    candidates = await build_candidates(df, definedge, index_key, fut["F"], atm, expiry, r, cfg["strike_range_from_atm"])
    atm_leg = next((c for c in candidates if c["strike"] == atm and c["option_type"] == "CE"), None)

    market = {
        "spot": spot, "prev_close": rv_data["prev_close"], "ema20_15m": ema,
        "atm_iv": atm_leg["iv"] if atm_leg else None, "realized_vol": rv_data["realized_vol"],
        "atm_theta": atm_leg["greeks"]["theta"] if atm_leg else None, "atm_gamma": atm_leg["greeks"]["gamma"] if atm_leg else None,
        "median_true_range": rv_data["median_true_range"], "candidates": candidates,
    }
    check = cw.check_entry_filters(market, {"convexity_window": cfg})
    await _mark_checked_today(db, index_key, "convexity_window", today_iso)

    if not check["qualifies"]:
        await _upsert_status(db, index_key, "convexity_window", "flat", check["reason"], filters=check["filters"])
        return {"action": "no_trade", "reason": check["reason"]}

    sel = check["selected"]
    trade_id = str(uuid.uuid4())
    doc = {
        "id": trade_id, "strategy_id": "convexity_window", "mode": MODE, "index": index_key,
        "timestamp": now.isoformat(), "instrument": INDEX_CONFIG[index_key]["option_symbol"],
        "strike": sel["strike"], "expiry": sel["expiry"].isoformat(), "side": sel["option_type"],
        "option_token": sel["token"], "entry_price": sel["premium"],
        "entry_greeks": sel["greeks"], "entry_gamma": sel["greeks"]["gamma"],
        "filters_at_entry": check["filters"], "status": "open",
        "exit_price": None, "exit_reason": None, "exit_timestamp": None,
        "gross_pnl": None, "costs": None, "net_pnl": None, "pnl_pct": None,
    }
    await db.blackbox_signals.insert_one(dict(doc))
    await _upsert_status(db, index_key, "convexity_window", "in_trade", "entered", open_trade_id=trade_id)
    return {"action": "entered", "trade_id": trade_id}


# ------------------------------------------------------------- Strategy 2

async def _evaluate_gamma_backspread(db, definedge, df, index_key: str) -> dict:
    now = datetime.now(IST)
    today = now.date()
    today_iso = today.isoformat()
    cfg_full = await get_config(db, index_key)
    cfg = cfg_full["gamma_backspread"]
    r = cfg_full["risk_free_rate"]

    open_trade = await _open_trade(db, index_key, "gamma_backspread")
    if open_trade is not None:
        expiry = datetime.fromisoformat(open_trade["expiry"]).date()
        fut_now = await get_futures_price(df, definedge, index_key)
        atm_q = await get_contract_quote(definedge, index_key, fut_now["F"], open_trade["atm_strike"], expiry,
                                          open_trade["side"], open_trade["atm_token"], r) if fut_now else None
        otm_q = await get_contract_quote(definedge, index_key, fut_now["F"], open_trade["otm_strike"], expiry,
                                          open_trade["side"], open_trade["otm_token"], r) if fut_now else None
        if atm_q is None or otm_q is None:
            await _upsert_status(db, index_key, "gamma_backspread", "in_trade",
                                  "live quote unavailable this tick — holding, will retry", open_trade_id=open_trade["id"])
            return {"action": "quote_unavailable"}
        dte = (expiry - today).days
        pkg_greeks = {"delta": -atm_q["greeks"]["delta"] + 2 * otm_q["greeks"]["delta"],
                      "gamma": -atm_q["greeks"]["gamma"] + 2 * otm_q["greeks"]["gamma"],
                      "theta": -atm_q["greeks"]["theta"] + 2 * otm_q["greeks"]["theta"],
                      "vega": -atm_q["greeks"]["vega"] + 2 * otm_q["greeks"]["vega"]}
        iv_history = await get_iv_history(db, index_key, "gamma_backspread", cfg["iv_percentile_window_days"])
        result = gb.evaluate_exit(atm_q["premium"], otm_q["premium"], pkg_greeks, atm_q["iv"], iv_history,
                                   {"net_debit": open_trade["net_debit"]}, dte, {"gamma_backspread": cfg})
        if result["action"] == "exit":
            legs = [
                {"side": "short", "entry_price": open_trade["atm_entry_price"], "exit_price": result["exit_price"]["atm"], "lots": 1},
                {"side": "long", "entry_price": open_trade["otm_entry_price"], "exit_price": result["exit_price"]["otm"], "lots": 2},
            ]
            costs = evaluate_trade_costs(legs, lot_size=cfg_full.get("lot_size") or 1, costs_cfg=cfg_full["costs"])
            await db.blackbox_signals.update_one(
                {"id": open_trade["id"]},
                {"$set": {"status": "closed", "exit_price": result["exit_price"], "exit_reason": result["exit_reason"],
                          "exit_timestamp": now.isoformat(), "gross_pnl": costs["gross_pnl"], "costs": costs["total_costs"],
                          "net_pnl": costs["net_pnl"]}},
            )
            await _upsert_status(db, index_key, "gamma_backspread", "flat", f"exited: {result['exit_reason']}")
            return {"action": "exited", "exit_reason": result["exit_reason"]}
        await _upsert_status(db, index_key, "gamma_backspread", "in_trade", "monitoring", open_trade_id=open_trade["id"])
        return {"action": "monitoring"}

    if now.time() < ENTRY_CHECK_TIME:
        await _upsert_status(db, index_key, "gamma_backspread", "flat", "before entry check time (09:30 IST)")
        return {"action": "too_early"}
    if await _already_checked_today(db, index_key, "gamma_backspread", today_iso):
        return {"action": "already_checked_today"}

    expiry = await _pick_expiry_in_band(df, index_key, cfg["dte_min"], cfg["dte_max"], today)
    if expiry is None:
        await _upsert_status(db, index_key, "gamma_backspread", "flat",
                              f"no listed expiry currently in DTE [{cfg['dte_min']},{cfg['dte_max']}]")
        await _mark_checked_today(db, index_key, "gamma_backspread", today_iso)
        return {"action": "no_expiry_in_band"}

    fut = await get_futures_price(df, definedge, index_key)
    if fut is None:
        await _upsert_status(db, index_key, "gamma_backspread", "flat", "live futures price unavailable")
        await _mark_checked_today(db, index_key, "gamma_backspread", today_iso)
        return {"action": "no_futures_data"}

    spot = fut["F"]
    atm = atm_strike(spot, index_key)
    ema = await get_15m_ema(definedge, index_key, cfg["ema_period_15m"])
    rv_data = await get_realized_vol_and_true_range(definedge, index_key, cfg)
    candidates = await build_candidates(df, definedge, index_key, fut["F"], atm, expiry, r, cfg["otm_strike_search_range"])
    atm_leg = next((c for c in candidates if c["strike"] == atm and c["option_type"] == "CE"), None)
    otm_legs = [c for c in candidates if c["strike"] != atm]

    if atm_leg is not None:
        dte = (expiry - today).days
        await record_atm_iv(db, index_key, "gamma_backspread", atm_leg["iv"])
    iv_history = await get_iv_history(db, index_key, "gamma_backspread", cfg["iv_percentile_window_days"])

    market = {
        "spot": spot, "prev_close": rv_data["prev_close"], "ema20_15m": ema,
        "atm_iv": atm_leg["iv"] if atm_leg else None, "iv_history": iv_history,
        "atm": atm_leg, "otm_candidates": otm_legs, "expiry": expiry, "dte": (expiry - today).days,
    }
    check = gb.check_entry_filters(market, {"gamma_backspread": cfg})
    await _mark_checked_today(db, index_key, "gamma_backspread", today_iso)

    if not check["qualifies"]:
        await _upsert_status(db, index_key, "gamma_backspread", "flat", check["reason"], filters=check["filters"])
        return {"action": "no_trade", "reason": check["reason"]}

    pkg = check["package"]
    net_debit = 2 * pkg["otm"]["premium"] - pkg["atm"]["premium"]
    trade_id = str(uuid.uuid4())
    doc = {
        "id": trade_id, "strategy_id": "gamma_backspread", "mode": MODE, "index": index_key,
        "timestamp": now.isoformat(), "instrument": INDEX_CONFIG[index_key]["option_symbol"],
        "atm_strike": pkg["atm"]["strike"], "otm_strike": pkg["otm"]["strike"], "expiry": expiry.isoformat(),
        "side": pkg["atm"]["option_type"], "atm_token": pkg["atm"]["token"], "otm_token": pkg["otm"]["token"],
        "atm_entry_price": pkg["atm"]["premium"], "otm_entry_price": pkg["otm"]["premium"], "net_debit": net_debit,
        "entry_greeks": pkg["package_greeks"], "filters_at_entry": check["filters"], "status": "open",
        "exit_price": None, "exit_reason": None, "exit_timestamp": None,
        "gross_pnl": None, "costs": None, "net_pnl": None, "pnl_pct": None,
    }
    await db.blackbox_signals.insert_one(dict(doc))
    await _upsert_status(db, index_key, "gamma_backspread", "in_trade", "entered", open_trade_id=trade_id)
    return {"action": "entered", "trade_id": trade_id}


# ------------------------------------------------------------- Cron entry point

async def evaluate_all(db, definedge) -> dict:
    """The single cron-tick entry point -- evaluates both strategies across
    both indices. Skips cleanly (no-op) outside market hours, same
    convention as index-vector's auto-refresh route."""
    now = datetime.now(IST)
    if not _in_market_hours(now):
        return {"skipped": "outside market hours"}

    df = await definedge._get_all_master()
    results = {}
    for index_key in ("NIFTY", "BANKNIFTY"):
        try:
            results[f"{index_key}_convexity_window"] = await _evaluate_convexity_window(db, definedge, df, index_key)
        except DefinedgeError as e:
            logger.warning("Convexity Window (%s) skipped this tick: %s", index_key, e)
            results[f"{index_key}_convexity_window"] = {"action": "error", "detail": str(e)}
        try:
            results[f"{index_key}_gamma_backspread"] = await _evaluate_gamma_backspread(db, definedge, df, index_key)
        except DefinedgeError as e:
            logger.warning("Gamma Backspread (%s) skipped this tick: %s", index_key, e)
            results[f"{index_key}_gamma_backspread"] = {"action": "error", "detail": str(e)}
    return results
