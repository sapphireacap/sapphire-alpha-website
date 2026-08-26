"""
PUBLIC routes for Black Box's three equity strategies (Structural Retest,
Trend Ignition, Volume Cascade) -- same public-by-explicit-instruction
convention as blackbox_options_routes.py's Convexity Window / Gamma
Backspread (new strategies are public; the original three stay
admin-only). Same router-factory / cron-vs-admin-JWT twin pattern as
every other cron-driven feature in this codebase.
"""
import logging
from datetime import datetime

from fastapi import APIRouter, HTTPException, Request, Depends

import blackbox_equity_config as cfgmod
import blackbox_equity_market as market
import blackbox_structural_retest as retest
import blackbox_trend_ignition as ignition
import blackbox_volume_cascade as cascade
from blackbox_equity_engine import evaluate_all, MODE, STRATEGIES
from definedge_service import IST, INDEX_CONFIG, DefinedgeError

logger = logging.getLogger(__name__)

STRATEGY_LABELS = {
    "structural_retest": {
        "name": "Structural Retest",
        "description": "Trades a P&F reversal pattern only once it has been RE-TESTED at the same level by a later pattern of the same bias, gated by the group's own breadth extreme (bullish retests only when the group is oversold, bearish only when overbought).",
    },
    "trend_ignition": {
        "name": "Trend Ignition",
        "description": "A multi-filter momentum confirmation checklist (EMA trend, RSI, ADX, relative volume, candle strength) run once daily across a broad stock universe.",
    },
    "volume_cascade": {
        "name": "Volume Cascade",
        "description": "A volume-surge trigger, confirmed by a relative-strength breakout against NIFTY 50 and the same breakout on the stock's own price chart.",
    },
}


def create_blackbox_equity_router(db, definedge, get_current_admin, cron_secret: str) -> APIRouter:
    router = APIRouter(prefix="/blackbox/equity")

    # ----------------------------------------------------------- public reads

    @router.get("/strategies")
    async def strategies():
        out = []
        for strategy_id in STRATEGIES:
            cfg = await cfgmod.get_config(db, strategy_id)
            status = await db.blackbox_equity_strategy_status.find_one(
                {"strategy_id": strategy_id, "mode": MODE}, {"_id": 0}
            )
            out.append({
                "strategy_id": strategy_id, **STRATEGY_LABELS[strategy_id], "mode": MODE,
                "config": cfg, "universe": cfgmod.UNIVERSE[strategy_id],
                "status": status or {},
            })
        return {"mode": MODE, "strategies": out}

    @router.get("/signals")
    async def signals(limit: int = 100, symbol: str = None, strategy_id: str = None):
        limit = max(1, min(limit, 1000))
        q = {"mode": MODE, "kind": "equity"}
        if symbol:
            q["symbol"] = symbol.upper()
        if strategy_id:
            q["strategy_id"] = strategy_id
        docs = await db.blackbox_signals.find(q, {"_id": 0}).sort("timestamp", -1).to_list(limit)
        return {"mode": MODE, "count": len(docs), "signals": docs}

    @router.get("/positions")
    async def positions(status: str = "open", strategy_id: str = None):
        q = {"mode": MODE, "status": status}
        if strategy_id:
            q["strategy_id"] = strategy_id
        docs = await db.blackbox_equity_positions.find(q, {"_id": 0}).sort("entry_date", -1).to_list(2000)
        return {"mode": MODE, "count": len(docs), "positions": docs}

    # ----------------------------------------------------------- cron + admin

    @router.post("/evaluate")
    async def evaluate_cron(request: Request):
        """External-cron entry point -- once daily, after market close
        (EOD cadence, not the options engine's 5-minute intraday tick;
        see blackbox_equity_engine.py's module docstring)."""
        if not cron_secret or request.headers.get("X-Cron-Key") != cron_secret:
            raise HTTPException(status_code=401, detail="Invalid cron key")
        try:
            return await evaluate_all(db, definedge)
        except Exception as e:  # noqa: BLE001
            raise HTTPException(status_code=502, detail=f"Blackbox equity evaluation failed: {e}")

    @router.post("/evaluate-now")
    async def evaluate_admin(admin: dict = Depends(get_current_admin)):
        """Same evaluation, for manual testing from the admin panel."""
        try:
            return await evaluate_all(db, definedge)
        except Exception as e:  # noqa: BLE001
            raise HTTPException(status_code=502, detail=f"Blackbox equity evaluation failed: {e}")

    @router.post("/backtest-run")
    async def backtest_run(admin: dict = Depends(get_current_admin)):
        """Manual backtest across each strategy's own universe, using
        whatever cached daily-bar history exists (2 years, per
        blackbox_equity_market.YEARS_BACK). Simpler than the options
        backtest harness (blackbox_options_backtest.py): no expired-
        contract/token-resolution constraint here, since equity daily
        bars don't expire -- the only real constraint is how much history
        Definedge actually has for a young listing, same as everywhere
        else in this codebase."""
        try:
            master = await definedge._get_all_master()
        except DefinedgeError as e:
            raise HTTPException(status_code=502, detail=f"Master file unavailable: {e}")

        runs = []
        now_iso = datetime.now(IST).isoformat()
        for strategy_id in STRATEGIES:
            cfg_dict = await cfgmod.get_config(db, strategy_id)
            symbols = await market.get_universe(cfgmod.UNIVERSE[strategy_id])
            trades = []
            benchmark_closes_by_date = None
            if strategy_id == "volume_cascade":
                nifty_cfg = INDEX_CONFIG["NIFTY"]
                nifty_bars = await definedge.daily_history(nifty_cfg["spot_segment"], nifty_cfg["spot_token"], years=2)
                benchmark_closes_by_date = {b["date"]: b["close"] for b in nifty_bars}

            breadth_series = None
            if strategy_id == "structural_retest":
                bars_by_symbol = {}
                for s in symbols:
                    bars = await market.get_daily_bars(db, definedge, master, s)
                    if bars:
                        bars_by_symbol[s] = bars
                cfg = cfgmod.structural_retest_cfg(cfg_dict)
                from blackbox_equity_engine import _compute_breadth_pct
                # A single current-day breadth reading (not a per-day walk-forward
                # series) -- computing a full historical breadth series would need
                # every symbol's FULL column history re-walked per backtest day,
                # which is a much larger project than this first pass. Flagged: the
                # backtest below uses TODAY's breadth for every historical day it
                # walks, which is a real simplification, not the live evaluator's
                # behaviour (which always uses the current day's own breadth).
                breadth_pct = _compute_breadth_pct(bars_by_symbol, cfg.box_pct, cfg.reversal_boxes)
                for symbol, bars in bars_by_symbol.items():
                    closes = [b["close"] for b in bars]
                    for cut in range(30, len(closes)):
                        entry = retest.check_entry(closes[:cut + 1], breadth_pct, cfg)
                        if entry:
                            trades.append({"symbol": symbol, "date": bars[cut]["date"], **entry})

            elif strategy_id == "trend_ignition":
                cfg = cfgmod.trend_ignition_cfg(cfg_dict)
                for s in symbols:
                    bars = await market.get_daily_bars(db, definedge, master, s)
                    if not bars:
                        continue
                    for cut in range(40, len(bars)):
                        entry = ignition.check_entry(bars[:cut + 1], cfg)
                        if entry:
                            trades.append({"symbol": s, "date": bars[cut]["date"], **entry})

            elif strategy_id == "volume_cascade":
                cfg = cfgmod.volume_cascade_cfg(cfg_dict)
                for s in symbols:
                    bars = await market.get_daily_bars(db, definedge, master, s)
                    if not bars:
                        continue
                    for cut in range(40, len(bars)):
                        entry = cascade.check_entry(bars[:cut + 1], benchmark_closes_by_date, cfg)
                        if entry:
                            trades.append({"symbol": s, "date": bars[cut]["date"], **entry})

            runs.append({
                "strategy_id": strategy_id, "mode": MODE, "recorded_at": now_iso,
                "universe_size": len(symbols), "signals_found": len(trades),
                "note": "Signal COUNT only, not a P&L walk-forward -- no forward return is computed "
                        "here yet (that needs per-trade exit simulation, a follow-up build).",
            })
        await db.blackbox_equity_backtest_runs.insert_many([dict(r) for r in runs])
        return {"runs": runs}

    @router.get("/backtest-runs")
    async def backtest_runs():
        docs = await db.blackbox_equity_backtest_runs.find({}, {"_id": 0}).sort("recorded_at", -1).to_list(50)
        return {"count": len(docs), "runs": docs}

    return router
