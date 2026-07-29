"""
End-of-day job for Convexity Window / Gamma Backspread -- runs once daily
at 15:35 IST via its own GitHub Actions cron trigger (separate from the
5-minute intraday evaluate cron). Two jobs, in order:
  1. Force-close any position still open at session end (exit_reason
     "session_end", using the last available live quote -- never a
     fabricated fill).
  2. Compute and write an IMMUTABLE blackbox_daily_performance doc per
     (index, strategy, mode) for today.

IMMUTABILITY IS A HARD INVARIANT (spec's own words: "a daily record must
NEVER be edited or deleted by application code"). write_daily_performance()
below is the ONLY function in this codebase that writes to
blackbox_daily_performance, and it refuses outright if a doc already exists
for that (date, index, strategy, mode) -- no upsert, no update_one, ever.
Re-running the EOD job twice for the same day is therefore always safe: the
second run's write attempt is a clean no-op, not a silent overwrite.
"""
import logging
from datetime import datetime, date

from blackbox_options_config import get_config
from blackbox_options_market import get_futures_price, get_contract_quote
from blackbox_options_costs import evaluate_trade_costs
import blackbox_convexity_window as cw
from definedge_service import IST, DefinedgeError

logger = logging.getLogger(__name__)


class ImmutableRecordError(Exception):
    """Raised when application code attempts to write over an
    already-recorded daily performance doc. Should never be caught and
    suppressed anywhere except EOD's own idempotent re-run check."""


async def write_daily_performance(db, doc: dict) -> dict:
    """The one and only writer for blackbox_daily_performance. Refuses to
    touch a date that already has a record -- see module docstring."""
    existing = await db.blackbox_daily_performance.find_one(
        {"date": doc["date"], "index": doc["index"], "strategy_id": doc["strategy_id"], "mode": doc["mode"]}
    )
    if existing is not None:
        raise ImmutableRecordError(
            f"Refusing to overwrite existing daily performance record for "
            f"{doc['index']}/{doc['strategy_id']}/{doc['mode']} on {doc['date']}."
        )
    await db.blackbox_daily_performance.insert_one(dict(doc))
    return doc


async def force_close_open_positions(db, definedge, df, index_key: str) -> list:
    """Force-closes any still-open Convexity Window / Gamma Backspread
    paper position for this index at the current live quote. Real
    quote-or-skip, same as every other exit path -- if a live quote can't
    be fetched, the position is left open and flagged rather than closed
    on a guessed price."""
    now = datetime.now(IST)
    closed = []
    cfg_full = await get_config(db, index_key)
    r = cfg_full["risk_free_rate"]
    fut = await get_futures_price(df, definedge, index_key)

    cw_trade = await db.blackbox_signals.find_one(
        {"index": index_key, "strategy_id": "convexity_window", "status": "open"}, {"_id": 0}
    )
    if cw_trade is not None and fut is not None:
        q = await get_contract_quote(definedge, index_key, fut["F"], cw_trade["strike"],
                                      datetime.fromisoformat(cw_trade["expiry"]).date(),
                                      cw_trade["side"], cw_trade["option_token"], r)
        if q is not None:
            costs = evaluate_trade_costs(
                [{"side": "long", "entry_price": cw_trade["entry_price"], "exit_price": q["premium"], "lots": 1}],
                lot_size=cfg_full.get("lot_size") or 1, costs_cfg=cfg_full["costs"],
            )
            await db.blackbox_signals.update_one(
                {"id": cw_trade["id"]},
                {"$set": {"status": "closed", "exit_price": q["premium"], "exit_reason": "session_end",
                          "exit_timestamp": now.isoformat(), "gross_pnl": costs["gross_pnl"],
                          "costs": costs["total_costs"], "net_pnl": costs["net_pnl"],
                          "pnl_pct": (q["premium"] - cw_trade["entry_price"]) / cw_trade["entry_price"]}},
            )
            closed.append({"strategy_id": "convexity_window", "trade_id": cw_trade["id"]})
        else:
            logger.warning("EOD (%s convexity_window): live quote unavailable, leaving position open across the close.", index_key)

    gb_trade = await db.blackbox_signals.find_one(
        {"index": index_key, "strategy_id": "gamma_backspread", "status": "open"}, {"_id": 0}
    )
    if gb_trade is not None and fut is not None:
        expiry = datetime.fromisoformat(gb_trade["expiry"]).date()
        atm_q = await get_contract_quote(definedge, index_key, fut["F"], gb_trade["atm_strike"], expiry,
                                          gb_trade["side"], gb_trade["atm_token"], r)
        otm_q = await get_contract_quote(definedge, index_key, fut["F"], gb_trade["otm_strike"], expiry,
                                          gb_trade["side"], gb_trade["otm_token"], r)
        if atm_q is not None and otm_q is not None:
            legs = [
                {"side": "short", "entry_price": gb_trade["atm_entry_price"], "exit_price": atm_q["premium"], "lots": 1},
                {"side": "long", "entry_price": gb_trade["otm_entry_price"], "exit_price": otm_q["premium"], "lots": 2},
            ]
            costs = evaluate_trade_costs(legs, lot_size=cfg_full.get("lot_size") or 1, costs_cfg=cfg_full["costs"])
            await db.blackbox_signals.update_one(
                {"id": gb_trade["id"]},
                {"$set": {"status": "closed", "exit_reason": "session_end", "exit_timestamp": now.isoformat(),
                          "exit_price": {"atm": atm_q["premium"], "otm": otm_q["premium"]},
                          "gross_pnl": costs["gross_pnl"], "costs": costs["total_costs"], "net_pnl": costs["net_pnl"]}},
            )
            closed.append({"strategy_id": "gamma_backspread", "trade_id": gb_trade["id"]})
        else:
            logger.warning("EOD (%s gamma_backspread): live quote unavailable, leaving position open across the close.", index_key)

    return closed


def _compute_stats_from_trades(trades: list) -> dict:
    net_pnls = [t["net_pnl"] for t in trades if t.get("net_pnl") is not None]
    gross_pnls = [t["gross_pnl"] for t in trades if t.get("gross_pnl") is not None]
    wins = [p for p in net_pnls if p > 0]
    losses = [p for p in net_pnls if p <= 0]
    win_rate = (len(wins) / len(net_pnls)) if net_pnls else None
    avg_win = (sum(wins) / len(wins)) if wins else 0.0
    avg_loss = (sum(losses) / len(losses)) if losses else 0.0
    gross_win, gross_loss = sum(wins), abs(sum(losses))
    profit_factor = (gross_win / gross_loss) if gross_loss > 0 else (None if gross_win == 0 else float("inf"))
    return {
        "trades": len(net_pnls), "wins": len(wins), "losses": len(losses), "win_rate": win_rate,
        "avg_win": avg_win, "avg_loss": avg_loss, "profit_factor": profit_factor,
        "gross_pnl": sum(gross_pnls), "net_pnl": sum(net_pnls),
    }


async def _compute_running_series(db, index_key: str, strategy_id: str, mode: str, upto_date_iso: str) -> dict:
    """Cumulative P&L, max drawdown, and a running Sharpe over every prior
    day's daily performance doc PLUS today's, in date order. Reads only
    already-immutable prior records plus today's just-computed one -- never
    recomputes or touches a past doc."""
    prior = await db.blackbox_daily_performance.find(
        {"index": index_key, "strategy_id": strategy_id, "mode": mode, "date": {"$lt": upto_date_iso}}, {"_id": 0}
    ).sort("date", 1).to_list(length=10000)
    return prior


async def compute_and_record_daily_performance(db, index_key: str, strategy_id: str, mode: str, date_iso: str) -> dict:
    trades = await db.blackbox_signals.find(
        {"index": index_key, "strategy_id": strategy_id, "mode": mode, "status": "closed",
         "exit_timestamp": {"$regex": f"^{date_iso}"}},
        {"_id": 0},
    ).to_list(length=10000)

    stats = _compute_stats_from_trades(trades)
    prior_days = await _compute_running_series(db, index_key, strategy_id, mode, date_iso)

    prior_cum = prior_days[-1]["cumulative_pnl"] if prior_days else 0.0
    cumulative_pnl = prior_cum + stats["net_pnl"]

    daily_net_series = [d["net_pnl"] for d in prior_days] + [stats["net_pnl"]]
    n = len(daily_net_series)
    mean = sum(daily_net_series) / n
    variance = sum((x - mean) ** 2 for x in daily_net_series) / n if n > 1 else 0.0
    stdev = variance ** 0.5
    sharpe = (mean / stdev * (252 ** 0.5)) if stdev > 1e-9 else None

    cum_series, peak, max_dd = 0.0, 0.0, 0.0
    for d in prior_days + [{"net_pnl": stats["net_pnl"]}]:
        cum_series += d["net_pnl"]
        peak = max(peak, cum_series)
        max_dd = min(max_dd, cum_series - peak)

    doc = {
        "date": date_iso, "index": index_key, "strategy_id": strategy_id, "mode": mode,
        "trades": stats["trades"], "wins": stats["wins"], "losses": stats["losses"], "win_rate": stats["win_rate"],
        "gross_pnl": stats["gross_pnl"], "net_pnl": stats["net_pnl"],
        "avg_win": stats["avg_win"], "avg_loss": stats["avg_loss"], "profit_factor": stats["profit_factor"],
        "cumulative_pnl": cumulative_pnl, "max_drawdown": max_dd, "sharpe": sharpe,
        "recorded_at": datetime.now(IST).isoformat(),
        "sample_size_warning": n < 20,
    }
    try:
        return await write_daily_performance(db, doc)
    except ImmutableRecordError as e:
        logger.info("EOD (%s/%s/%s %s): %s (already recorded — normal on a re-run)", index_key, strategy_id, mode, date_iso, e)
        return {"skipped": str(e)}


async def run_eod(db, definedge) -> dict:
    today_iso = datetime.now(IST).date().isoformat()
    df = await definedge._get_all_master()
    result = {"date": today_iso, "closed_positions": [], "daily_performance": []}
    for index_key in ("NIFTY", "BANKNIFTY"):
        try:
            closed = await force_close_open_positions(db, definedge, df, index_key)
            result["closed_positions"].extend([{**c, "index": index_key} for c in closed])
        except DefinedgeError as e:
            logger.warning("EOD force-close (%s) hit a Definedge error: %s", index_key, e)
        for strategy_id in ("convexity_window", "gamma_backspread"):
            doc = await compute_and_record_daily_performance(db, index_key, strategy_id, "paper", today_iso)
            result["daily_performance"].append(doc)
    return result
