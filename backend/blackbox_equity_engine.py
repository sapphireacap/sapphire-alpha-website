"""
Live/paper daily evaluator for Black Box's three equity strategies
(Structural Retest, Trend Ignition, Volume Cascade). Same paper-mode-only
discipline as blackbox_options_engine.py (LIVE_MODE is the one gate, never
flipped automatically), but EOD-cadence rather than a 5-minute intraday
tick -- these strategies are all daily-bar/P&F-box based, so there is
nothing for an intraday tick to add (see blackbox_trend_ignition.py's
module docstring for why that's a deliberate scope decision).

Unlike the options engine (one position at a time per index), each of
these strategies can hold many concurrent positions across its universe
(up to one per symbol) -- open positions live in `blackbox_equity_positions`
(one doc per symbol per strategy), not the single-slot
`blackbox_strategy_status` shape the options engine uses. Signals are
still logged to the SAME `blackbox_signals` collection the options engine
uses (with `symbol` set and `index` left None, and `kind: "equity"`), so
admin reporting has one place to look across the whole Black Box.
"""
import asyncio
import logging
from datetime import datetime

import blackbox_equity_config as cfgmod
import blackbox_equity_market as market
import blackbox_structural_retest as retest
import blackbox_trend_ignition as ignition
import blackbox_volume_cascade as cascade
from pnf_engine import BoxSettings, build_columns
from definedge_service import IST, INDEX_CONFIG, DefinedgeError

logger = logging.getLogger(__name__)

LIVE_MODE = False  # same one gate as blackbox_options_engine.py -- never flipped automatically
MODE = "paper" if not LIVE_MODE else "live"

STRATEGIES = ("structural_retest", "trend_ignition", "volume_cascade")
FETCH_CONCURRENCY = 10  # same OOM-safety cap as relative_strength_routes.py's fetch_semaphore


async def _fetch_universe_bars(db, definedge, master, symbols: list) -> dict:
    sem = asyncio.Semaphore(FETCH_CONCURRENCY)

    async def _bounded(symbol):
        async with sem:
            return symbol, await market.get_daily_bars(db, definedge, master, symbol)

    results = await asyncio.gather(*[_bounded(s) for s in symbols])
    return {s: bars for s, bars in results if bars}


def _compute_breadth_pct(bars_by_symbol: dict, box_pct: float, reversal_boxes: int) -> float | None:
    """% of the universe currently sitting on a bullish (X) P&F column, at
    the same box size Structural Retest itself trades -- Datta's own
    definition (see blackbox_structural_retest.py's module docstring)."""
    settings = BoxSettings(reversal_boxes=reversal_boxes, box_pct=box_pct / 100.0)
    bullish, total = 0, 0
    for bars in bars_by_symbol.values():
        closes = [b["close"] for b in bars]
        columns = build_columns(closes, settings)
        if not columns:
            continue
        total += 1
        if columns[-1].direction == "up":
            bullish += 1
    if total == 0:
        return None
    return round(100.0 * bullish / total, 2)


async def _open_position(db, strategy_id: str, symbol: str) -> dict | None:
    return await db.blackbox_equity_positions.find_one(
        {"strategy_id": strategy_id, "symbol": symbol, "mode": MODE, "status": "open"}, {"_id": 0}
    )


async def _log_signal(db, strategy_id: str, symbol: str, doc: dict) -> None:
    await db.blackbox_signals.insert_one({"kind": "equity", "index": None, **doc})


async def _evaluate_structural_retest(db, definedge, master) -> dict:
    strategy_id = "structural_retest"
    cfg_dict = await cfgmod.get_config(db, strategy_id)
    cfg = cfgmod.structural_retest_cfg(cfg_dict)
    symbols = await market.get_universe(cfgmod.UNIVERSE[strategy_id])
    bars_by_symbol = await _fetch_universe_bars(db, definedge, master, symbols)
    breadth_pct = _compute_breadth_pct(bars_by_symbol, cfg.box_pct, cfg.reversal_boxes)
    today_iso = datetime.now(IST).date().isoformat()

    entered, exited, errors = [], [], []
    for symbol, bars in bars_by_symbol.items():
        closes = [b["close"] for b in bars]
        try:
            open_pos = await _open_position(db, strategy_id, symbol)
            if open_pos:
                exit_sig = retest.check_exit(closes, open_pos["bias"], cfg)
                if exit_sig:
                    await db.blackbox_equity_positions.update_one(
                        {"id": open_pos["id"]},
                        {"$set": {"status": "closed", "exit_date": today_iso, **exit_sig}},
                    )
                    await _log_signal(db, strategy_id, symbol, {
                        "strategy_id": strategy_id, "mode": MODE, "symbol": symbol, "status": "closed",
                        "timestamp": datetime.now(IST).isoformat(), **exit_sig,
                    })
                    exited.append(symbol)
                continue
            entry = retest.check_entry(closes, breadth_pct, cfg)
            if entry:
                pos_id = f"{strategy_id}:{symbol}:{today_iso}"
                await db.blackbox_equity_positions.update_one(
                    {"id": pos_id},
                    {"$set": {"id": pos_id, "strategy_id": strategy_id, "symbol": symbol, "mode": MODE,
                              "status": "open", "entry_date": today_iso, **entry}},
                    upsert=True,
                )
                await _log_signal(db, strategy_id, symbol, {
                    "strategy_id": strategy_id, "mode": MODE, "symbol": symbol, "status": "open",
                    "timestamp": datetime.now(IST).isoformat(), **entry,
                })
                entered.append(symbol)
        except Exception as e:  # noqa: BLE001 -- one symbol's bad data must never abort the whole universe scan
            logger.warning("Structural Retest: %s skipped this run: %s", symbol, e)
            errors.append(symbol)

    await db.blackbox_equity_strategy_status.update_one(
        {"strategy_id": strategy_id, "mode": MODE},
        {"$set": {"strategy_id": strategy_id, "mode": MODE, "universe_size": len(symbols),
                  "resolved": len(bars_by_symbol), "breadth_pct": breadth_pct,
                  "entered_today": entered, "exited_today": exited,
                  "last_run_at": datetime.now(IST).isoformat()}},
        upsert=True,
    )
    return {"entered": len(entered), "exited": len(exited), "errors": len(errors), "breadth_pct": breadth_pct}


async def _evaluate_trend_ignition(db, definedge, master) -> dict:
    strategy_id = "trend_ignition"
    cfg_dict = await cfgmod.get_config(db, strategy_id)
    cfg = cfgmod.trend_ignition_cfg(cfg_dict)
    symbols = await market.get_universe(cfgmod.UNIVERSE[strategy_id])
    bars_by_symbol = await _fetch_universe_bars(db, definedge, master, symbols)
    today_iso = datetime.now(IST).date().isoformat()

    entered, exited, errors = [], [], []
    for symbol, bars in bars_by_symbol.items():
        try:
            open_pos = await _open_position(db, strategy_id, symbol)
            if open_pos:
                exit_sig = ignition.check_exit(bars, open_pos, cfg)
                if exit_sig is None:
                    continue
                if exit_sig["action"] in ("partial", "full"):
                    update = {"booked_rungs": exit_sig["rung"]}
                    if exit_sig["action"] == "full":
                        update["status"] = "closed"
                        update["exit_date"] = today_iso
                else:  # stop
                    update = {"status": "closed", "exit_date": today_iso}
                await db.blackbox_equity_positions.update_one({"id": open_pos["id"]}, {"$set": update})
                await _log_signal(db, strategy_id, symbol, {
                    "strategy_id": strategy_id, "mode": MODE, "symbol": symbol,
                    "status": update.get("status", "open"), "timestamp": datetime.now(IST).isoformat(),
                    **exit_sig,
                })
                if update.get("status") == "closed":
                    exited.append(symbol)
                continue
            entry = ignition.check_entry(bars, cfg)
            if entry:
                pos_id = f"{strategy_id}:{symbol}:{today_iso}"
                await db.blackbox_equity_positions.update_one(
                    {"id": pos_id},
                    {"$set": {"id": pos_id, "strategy_id": strategy_id, "symbol": symbol, "mode": MODE,
                              "status": "open", "entry_date": today_iso, "booked_rungs": 0, **entry}},
                    upsert=True,
                )
                await _log_signal(db, strategy_id, symbol, {
                    "strategy_id": strategy_id, "mode": MODE, "symbol": symbol, "status": "open",
                    "timestamp": datetime.now(IST).isoformat(), **entry,
                })
                entered.append(symbol)
        except Exception as e:  # noqa: BLE001
            logger.warning("Trend Ignition: %s skipped this run: %s", symbol, e)
            errors.append(symbol)

    await db.blackbox_equity_strategy_status.update_one(
        {"strategy_id": strategy_id, "mode": MODE},
        {"$set": {"strategy_id": strategy_id, "mode": MODE, "universe_size": len(symbols),
                  "resolved": len(bars_by_symbol), "entered_today": entered, "exited_today": exited,
                  "last_run_at": datetime.now(IST).isoformat()}},
        upsert=True,
    )
    return {"entered": len(entered), "exited": len(exited), "errors": len(errors)}


async def _evaluate_volume_cascade(db, definedge, master) -> dict:
    strategy_id = "volume_cascade"
    cfg_dict = await cfgmod.get_config(db, strategy_id)
    cfg = cfgmod.volume_cascade_cfg(cfg_dict)
    symbols = await market.get_universe(cfgmod.UNIVERSE[strategy_id])
    bars_by_symbol = await _fetch_universe_bars(db, definedge, master, symbols)
    today_iso = datetime.now(IST).date().isoformat()

    nifty_cfg = INDEX_CONFIG["NIFTY"]
    try:
        nifty_bars = await definedge.daily_history(nifty_cfg["spot_segment"], nifty_cfg["spot_token"], years=2)
    except DefinedgeError as e:
        logger.warning("Volume Cascade: NIFTY 50 benchmark unavailable this run: %s", e)
        return {"entered": 0, "exited": 0, "errors": 0, "skipped": "benchmark_unavailable"}
    benchmark_closes_by_date = {b["date"]: b["close"] for b in nifty_bars}

    entered, exited, errors = [], [], []
    for symbol, bars in bars_by_symbol.items():
        try:
            open_pos = await _open_position(db, strategy_id, symbol)
            if open_pos:
                exit_sig = cascade.check_exit(bars, open_pos, cfg)
                if exit_sig is None:
                    continue
                if exit_sig.get("partial") and not open_pos.get("booked"):
                    await db.blackbox_equity_positions.update_one({"id": open_pos["id"]}, {"$set": {"booked": True}})
                else:
                    await db.blackbox_equity_positions.update_one(
                        {"id": open_pos["id"]}, {"$set": {"status": "closed", "exit_date": today_iso, **exit_sig}},
                    )
                    exited.append(symbol)
                await _log_signal(db, strategy_id, symbol, {
                    "strategy_id": strategy_id, "mode": MODE, "symbol": symbol,
                    "status": "closed" if not exit_sig.get("partial") else "open",
                    "timestamp": datetime.now(IST).isoformat(), **exit_sig,
                })
                continue
            entry = cascade.check_entry(bars, benchmark_closes_by_date, cfg)
            if entry:
                pos_id = f"{strategy_id}:{symbol}:{today_iso}"
                await db.blackbox_equity_positions.update_one(
                    {"id": pos_id},
                    {"$set": {"id": pos_id, "strategy_id": strategy_id, "symbol": symbol, "mode": MODE,
                              "status": "open", "entry_date": today_iso, "booked": False, **entry}},
                    upsert=True,
                )
                await _log_signal(db, strategy_id, symbol, {
                    "strategy_id": strategy_id, "mode": MODE, "symbol": symbol, "status": "open",
                    "timestamp": datetime.now(IST).isoformat(), **entry,
                })
                entered.append(symbol)
        except Exception as e:  # noqa: BLE001
            logger.warning("Volume Cascade: %s skipped this run: %s", symbol, e)
            errors.append(symbol)

    await db.blackbox_equity_strategy_status.update_one(
        {"strategy_id": strategy_id, "mode": MODE},
        {"$set": {"strategy_id": strategy_id, "mode": MODE, "universe_size": len(symbols),
                  "resolved": len(bars_by_symbol), "entered_today": entered, "exited_today": exited,
                  "last_run_at": datetime.now(IST).isoformat()}},
        upsert=True,
    )
    return {"entered": len(entered), "exited": len(exited), "errors": len(errors)}


_EVALUATORS = {
    "structural_retest": _evaluate_structural_retest,
    "trend_ignition": _evaluate_trend_ignition,
    "volume_cascade": _evaluate_volume_cascade,
}


async def evaluate_all(db, definedge) -> dict:
    """The single daily cron entry point -- runs all three equity
    strategies once. No market-hours gate (unlike the options engine's
    5-minute intraday tick): this is meant to be scheduled once, after
    market close, same convention as this codebase's other EOD-cadence
    jobs (see server.py's EOD_REFRESH_TARGETS)."""
    try:
        master = await definedge._get_all_master()
    except DefinedgeError as e:
        return {"skipped": f"master file unavailable: {e}"}

    results = {}
    for strategy_id, fn in _EVALUATORS.items():
        try:
            results[strategy_id] = await fn(db, definedge, master)
        except DefinedgeError as e:
            logger.warning("%s skipped this run: %s", strategy_id, e)
            results[strategy_id] = {"error": str(e)}
    return results
