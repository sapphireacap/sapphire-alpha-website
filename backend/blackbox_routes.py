"""
Black Box tab routes — "Prism Alpha" P&F signal system.

Public routes intentionally return performance/trade-log data only — never
conditions_met (pattern names, indicator values) or stop_shift_history's
pattern field, per the "stays a black box" requirement. Those fields exist
in Mongo for audit but are stripped before leaving this router.

Same factory pattern as quant_lab.py's create_quant_lab_router — takes the
existing shared `definedge` instance, no new auth.
"""
import logging
from datetime import datetime, timezone, timedelta

from typing import Optional

from fastapi import APIRouter, HTTPException, Request, Depends

from blackbox_prism_alpha import evaluate_prism_alpha
from blackbox_backtest import run_backtest

logger = logging.getLogger(__name__)
IST = timezone(timedelta(hours=5, minutes=30))


def _compute_stats(trades: list) -> dict:
    closed = [t for t in trades if t.get("status") == "closed" and t.get("pnl") is not None]
    closed.sort(key=lambda t: t.get("exit_time") or "")
    total = len(closed)
    if total == 0:
        return {"total_trades": 0, "win_rate": None, "avg_pnl": None, "max_drawdown": None, "equity_curve": []}

    wins = sum(1 for t in closed if t["pnl"] > 0)
    cum = peak = max_dd = 0.0
    equity_curve = []
    for t in closed:
        cum += t["pnl"]
        peak = max(peak, cum)
        max_dd = max(max_dd, peak - cum)
        equity_curve.append({"exit_time": t.get("exit_time"), "cumulative_pnl": cum})

    return {
        "total_trades": total,
        "win_rate": wins / total,
        "avg_pnl": sum(t["pnl"] for t in closed) / total,
        "max_drawdown": max_dd,
        "equity_curve": equity_curve,
    }


def _public_trade(t: dict) -> dict:
    """Entry/exit/P&L/duration only — no conditions_met, no pattern names."""
    return {
        "id": t["id"],
        "date": t["date"],
        "direction": t["direction"],
        "strike": t["strike"],
        "expiry": t["expiry"],
        "entry_time": t["entry_time"],
        "entry_price": t["entry_price"],
        "exit_time": t.get("exit_time"),
        "exit_price": t.get("exit_price"),
        "exit_reason": t.get("exit_reason"),
        "pnl": t.get("pnl"),
        "status": t["status"],
    }


def create_blackbox_router(db, definedge, get_current_admin, cron_secret: str) -> APIRouter:
    router = APIRouter(prefix="/blackbox")

    @router.post("/admin/prism-alpha-evaluate")
    async def prism_alpha_evaluate_cron(request: Request):
        """External-cron entry point (same X-Cron-Key mechanism as every
        other scheduled job in this codebase) — recommend every 1 minute
        during 09:15-15:30 IST, the tightest end of the spec's 1-5 minute
        range, needed for prompt stop/target detection."""
        if not cron_secret or request.headers.get("X-Cron-Key") != cron_secret:
            raise HTTPException(status_code=401, detail="Invalid cron key")
        try:
            return await evaluate_prism_alpha(db, definedge)
        except Exception as e:  # noqa: BLE001
            raise HTTPException(status_code=502, detail=f"Prism Alpha evaluation failed: {e}")

    @router.post("/admin/prism-alpha-evaluate-now")
    async def prism_alpha_evaluate_admin(admin: dict = Depends(get_current_admin)):
        """Same evaluation, for manual testing from the admin panel."""
        try:
            return await evaluate_prism_alpha(db, definedge)
        except Exception as e:  # noqa: BLE001
            raise HTTPException(status_code=502, detail=f"Prism Alpha evaluation failed: {e}")

    @router.get("/prism-alpha/status")
    async def prism_alpha_status():
        today_iso = datetime.now(IST).date().isoformat()
        trade = await db.blackbox_prism_alpha_trades.find_one({"date": today_iso}, {"_id": 0})
        if not trade:
            return {"position": "flat", "today_signal": None}
        signal = {
            "direction": trade["direction"],
            "strike": trade["strike"],
            "entry_time": trade["entry_time"],
            "exit_time": trade.get("exit_time"),
            "pnl": trade.get("pnl"),
        }
        return {"position": "in_position" if trade["status"] == "open" else "flat", "today_signal": signal}

    @router.get("/prism-alpha/stats")
    async def prism_alpha_stats():
        trades = await db.blackbox_prism_alpha_trades.find({}, {"_id": 0}).to_list(5000)
        return _compute_stats(trades)

    @router.get("/prism-alpha/trades")
    async def prism_alpha_trades():
        trades = await db.blackbox_prism_alpha_trades.find({}, {"_id": 0}).sort("entry_time", -1).to_list(500)
        return [_public_trade(t) for t in trades]

    @router.post("/admin/prism-alpha-backtest-run")
    async def prism_alpha_backtest_run(
        start_date: Optional[str] = None, end_date: Optional[str] = None,
        admin: dict = Depends(get_current_admin),
    ):
        """On-demand, not scheduled — a backtest run is a heavy one-off
        computation (NSE bhavcopy fetches for every entry/exit day), not
        something to poll on a cron. start_date/end_date default to the
        full available real-premium window (2024-01-01 to today) if omitted."""
        try:
            sd = datetime.strptime(start_date, "%Y-%m-%d").date() if start_date else None
            ed = datetime.strptime(end_date, "%Y-%m-%d").date() if end_date else None
            return await run_backtest(db, definedge, start_date=sd, end_date=ed)
        except Exception as e:  # noqa: BLE001
            raise HTTPException(status_code=502, detail=f"Backtest run failed: {e}")

    @router.get("/prism-alpha/backtest/summary")
    async def prism_alpha_backtest_summary():
        """Latest run's metadata + stats — the date range, granularity and
        trade count are surfaced prominently so it's never mistaken for a
        full-history backtest, per the transparency requirement."""
        latest_run = await db.blackbox_backtest_runs.find_one({}, {"_id": 0}, sort=[("run_at", -1)])
        if not latest_run:
            return {"run": None, "stats": _compute_stats([])}
        trades = await db.blackbox_prism_alpha_backtest_trades.find(
            {"backtest_run_id": latest_run["backtest_run_id"]}, {"_id": 0}
        ).to_list(5000)
        return {"run": latest_run, "stats": _compute_stats(trades)}

    @router.get("/prism-alpha/backtest/trades")
    async def prism_alpha_backtest_trades():
        latest_run = await db.blackbox_backtest_runs.find_one({}, {"_id": 0}, sort=[("run_at", -1)])
        if not latest_run:
            return []
        trades = await db.blackbox_prism_alpha_backtest_trades.find(
            {"backtest_run_id": latest_run["backtest_run_id"]}, {"_id": 0}
        ).sort("entry_time", -1).to_list(500)
        return [_public_trade(t) for t in trades]

    return router
