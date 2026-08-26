"""
Live/paper cron evaluator for Premium Band Strangle. Called by the
cron-secured POST /api/blackbox/options/evaluate route every 5 minutes
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

Each call, per index: if a position is open, evaluate roll triggers (or
force-close at expiry) against live Definedge quotes; if flat, evaluate
entry ONCE per real day (gated on ENTRY_CHECK_TIME having passed and not
already checked today). Always upserts `blackbox_strategy_status` so the
frontend can show live status without hitting Definedge itself. Trades
are logged to `blackbox_signals`.

Convexity Window and Gamma Backspread (the original two strategies here)
were removed entirely on 2026-08-26, code and production data both, per
explicit instruction -- see git history if either is ever wanted back.
"""
import logging
import uuid
from datetime import datetime, time as dt_time

from blackbox_options_config import get_config
from blackbox_options_market import atm_strike, get_futures_price, STRIKE_INCREMENT
from blackbox_options_data import list_candidate_expiries, resolve_strike_tokens, list_strikes_near
import blackbox_premium_band_strangle as pbs
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

STRATEGIES = ("premium_band_strangle",)


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


async def _fetch_premium_candidates(definedge, df, index_key: str, expiry, option_type: str,
                                     atm: int, strike_range: int) -> list:
    """Live premium only, no Greeks/IV -- Premium Band Strangle explicitly
    needs neither (see blackbox_premium_band_strangle.py's module
    docstring: "No Greeks, No Indicators"). `df` is the already-fetched
    master file (evaluate_all's own single per-tick fetch), not re-pulled."""
    inc = STRIKE_INCREMENT[index_key]
    strikes = list_strikes_near(atm, inc, strike_range)
    out = []
    for strike in strikes:
        tokens = resolve_strike_tokens(df, INDEX_CONFIG[index_key]["option_symbol"], expiry, strike)
        token = tokens.get(option_type)
        if not token:
            continue
        try:
            premium = await definedge.equity_quote(INDEX_CONFIG[index_key]["option_segment"], token)
        except DefinedgeError:
            continue
        if premium is None or premium <= 0:
            continue
        out.append({"strike": strike, "premium": premium, "token": token})
    return out


async def _evaluate_premium_band_strangle(db, definedge, df, index_key: str) -> dict:
    now = datetime.now(IST)
    today = now.date()
    today_iso = today.isoformat()
    cfg_full = await get_config(db, index_key)
    cfg = cfg_full["premium_band_strangle"]
    lot_size = cfg_full.get("lot_size") or 1

    open_trade = await _open_trade(db, index_key, "premium_band_strangle")
    if open_trade is not None:
        expiry = datetime.fromisoformat(open_trade["expiry"]).date()
        legs = open_trade["legs"]

        # The deck's own examples never show a final unwind (it's a
        # continuously-rolled position) -- but a real index option is
        # cash-settled at expiry regardless of what this module does, so
        # the PAPER position must be marked closed then too, or it would
        # sit "open" against a contract that no longer exists.
        if today >= expiry:
            gross_pnl = 0.0
            for side in ("CE", "PE"):
                leg = legs[side]
                try:
                    settle_premium = await definedge.equity_quote(INDEX_CONFIG[index_key]["option_segment"], leg["token"])
                except DefinedgeError:
                    settle_premium = leg["entry_premium"]  # last resort only, at expiry, not mid-life
                gross_pnl += (leg["entry_premium"] - (settle_premium or leg["entry_premium"])) * lot_size
            await db.blackbox_signals.update_one(
                {"id": open_trade["id"]},
                {"$set": {"status": "closed", "exit_reason": "expiry", "exit_timestamp": now.isoformat(),
                          "gross_pnl": gross_pnl, "net_pnl": gross_pnl}},
            )
            await _upsert_status(db, index_key, "premium_band_strangle", "flat", "closed at expiry")
            return {"action": "exited", "exit_reason": "expiry"}

        actions = {}
        for side in ("CE", "PE"):
            leg = legs[side]
            try:
                current_premium = await definedge.equity_quote(INDEX_CONFIG[index_key]["option_segment"], leg["token"])
            except DefinedgeError:
                current_premium = None
            if current_premium is None or current_premium <= 0:
                continue
            pnl_rupees = (leg["entry_premium"] - current_premium) * lot_size  # short leg: premium falling = profit
            action = pbs.check_leg_action(leg["entry_premium"], current_premium, pnl_rupees, _cfg_obj(cfg))
            if action:
                actions[side] = {**action, "current_premium": current_premium}

        if actions:
            fut_now = await get_futures_price(df, definedge, index_key)
            if fut_now is None:
                await _upsert_status(db, index_key, "premium_band_strangle", "in_trade",
                                      "roll triggered but live futures price unavailable — holding, will retry",
                                      open_trade_id=open_trade["id"])
                return {"action": "quote_unavailable"}
            atm_now = atm_strike(fut_now["F"], index_key)
            for side in list(actions.keys()):
                candidates = await _fetch_premium_candidates(definedge, df, index_key, expiry, side, atm_now,
                                                              cfg["strike_range_from_atm"])
                sel = pbs.select_strike(candidates, _cfg_obj(cfg))
                if sel is None:
                    continue  # can't roll this tick -- hold and retry next tick, never fabricate a strike
                legs[side] = {"token": sel["token"], "strike": sel["strike"], "entry_premium": sel["premium"],
                              "entry_timestamp": now.isoformat()}
            await db.blackbox_signals.update_one({"id": open_trade["id"]}, {"$set": {"legs": legs}})
            reasons = ", ".join(f"{side}({a['reason']})" for side, a in actions.items())
            await _upsert_status(db, index_key, "premium_band_strangle", "in_trade", f"rolled: {reasons}",
                                  open_trade_id=open_trade["id"])
            return {"action": "rolled", "legs": list(actions.keys())}

        await _upsert_status(db, index_key, "premium_band_strangle", "in_trade", "monitoring",
                              open_trade_id=open_trade["id"])
        return {"action": "monitoring"}

    if now.time() < ENTRY_CHECK_TIME:
        await _upsert_status(db, index_key, "premium_band_strangle", "flat", "before entry check time (09:30 IST)")
        return {"action": "too_early"}
    if await _already_checked_today(db, index_key, "premium_band_strangle", today_iso):
        return {"action": "already_checked_today"}

    expiry = await _pick_expiry_in_band(df, index_key, cfg["dte_min"], cfg["dte_max"], today)
    if expiry is None:
        await _upsert_status(db, index_key, "premium_band_strangle", "flat",
                              f"no listed expiry currently in DTE [{cfg['dte_min']},{cfg['dte_max']}]")
        await _mark_checked_today(db, index_key, "premium_band_strangle", today_iso)
        return {"action": "no_expiry_in_band"}

    fut = await get_futures_price(df, definedge, index_key)
    await _mark_checked_today(db, index_key, "premium_band_strangle", today_iso)
    if fut is None:
        await _upsert_status(db, index_key, "premium_band_strangle", "flat", "live futures price unavailable")
        return {"action": "no_futures_data"}

    atm = atm_strike(fut["F"], index_key)
    ce_candidates = await _fetch_premium_candidates(definedge, df, index_key, expiry, "CE", atm, cfg["strike_range_from_atm"])
    pe_candidates = await _fetch_premium_candidates(definedge, df, index_key, expiry, "PE", atm, cfg["strike_range_from_atm"])
    ce_sel = pbs.select_strike(ce_candidates, _cfg_obj(cfg))
    pe_sel = pbs.select_strike(pe_candidates, _cfg_obj(cfg))
    if ce_sel is None or pe_sel is None:
        await _upsert_status(db, index_key, "premium_band_strangle", "flat", "no strike found near the premium band")
        return {"action": "no_strike_in_band"}

    trade_id = str(uuid.uuid4())
    doc = {
        "id": trade_id, "strategy_id": "premium_band_strangle", "mode": MODE, "index": index_key,
        "timestamp": now.isoformat(), "instrument": INDEX_CONFIG[index_key]["option_symbol"],
        "expiry": expiry.isoformat(), "status": "open",
        "legs": {
            "CE": {"token": ce_sel["token"], "strike": ce_sel["strike"], "entry_premium": ce_sel["premium"],
                   "entry_timestamp": now.isoformat()},
            "PE": {"token": pe_sel["token"], "strike": pe_sel["strike"], "entry_premium": pe_sel["premium"],
                   "entry_timestamp": now.isoformat()},
        },
        "exit_price": None, "exit_reason": None, "exit_timestamp": None,
        "gross_pnl": None, "costs": None, "net_pnl": None, "pnl_pct": None,
    }
    await db.blackbox_signals.insert_one(dict(doc))
    await _upsert_status(db, index_key, "premium_band_strangle", "in_trade", "entered", open_trade_id=trade_id)
    return {"action": "entered", "trade_id": trade_id}


def _cfg_obj(cfg: dict) -> pbs.PremiumBandStrangleConfig:
    """dict -> dataclass, since this config is stored/loaded as a plain
    Mongo doc but the pure logic module takes its own dataclass."""
    return pbs.PremiumBandStrangleConfig(
        band_lo=cfg["band_lo"], band_hi=cfg["band_hi"],
        profit_shift_rupees=cfg["profit_shift_rupees"], loss_trigger_rupees=cfg["loss_trigger_rupees"],
        double_trigger_ratio=cfg["double_trigger_ratio"],
    )


# ------------------------------------------------------------- Cron entry point

async def evaluate_all(db, definedge) -> dict:
    """The single cron-tick entry point -- evaluates Premium Band Strangle
    across both indices. Skips cleanly (no-op) outside market hours, same
    convention as index-vector's auto-refresh route."""
    now = datetime.now(IST)
    if not _in_market_hours(now):
        return {"skipped": "outside market hours"}

    df = await definedge._get_all_master()
    results = {}
    for index_key in ("NIFTY", "BANKNIFTY"):
        try:
            results[f"{index_key}_premium_band_strangle"] = await _evaluate_premium_band_strangle(db, definedge, df, index_key)
        except DefinedgeError as e:
            logger.warning("Premium Band Strangle (%s) skipped this tick: %s", index_key, e)
            results[f"{index_key}_premium_band_strangle"] = {"action": "error", "detail": str(e)}
    return results
