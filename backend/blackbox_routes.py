"""
Black Box tab routes — Prism Alpha (RSI + XO Zone gated) and Prism Alpha 2
(identical pattern logic, no indicator gate — a parallel comparison track).

Public routes intentionally return performance/trade-log data only — never
conditions_met (pattern names, indicator values) or stop_shift_history's
pattern field, per the "stays a black box" requirement. Those fields exist
in Mongo for audit but are stripped before leaving this router.

Same factory pattern as quant_lab.py's create_quant_lab_router — takes the
existing shared `definedge` instance, no new auth.
"""
import logging
from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, HTTPException, Request, Response, Depends

from blackbox_prism_alpha import evaluate_prism_alpha, VARIANT_CONFIG
from blackbox_backtest import run_backtest, BACKTEST_COLLECTIONS
from blackbox_lumen_sip import evaluate_lumen_sip_live, run_lumen_sip_backtest, INSTRUMENTS as LUMEN_SIP_INSTRUMENTS

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


def _public_trade(t: dict, chart_url: str = None) -> dict:
    """Entry/exit/P&L/duration only — no conditions_met, no pattern names."""
    out = {
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
    if chart_url is not None:
        out["chart_url"] = chart_url
    return out


def create_blackbox_router(db, definedge, get_current_admin, cron_secret: str) -> APIRouter:
    router = APIRouter(prefix="/blackbox")

    async def _status(collection_name: str):
        today_iso = datetime.now(IST).date().isoformat()
        trade = await db[collection_name].find_one({"date": today_iso}, {"_id": 0})
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

    async def _stats(collection_name: str):
        trades = await db[collection_name].find({}, {"_id": 0}).to_list(5000)
        return _compute_stats(trades)

    async def _trades(collection_name: str):
        trades = await db[collection_name].find({}, {"_id": 0}).sort("entry_time", -1).to_list(500)
        return [_public_trade(t) for t in trades]

    @router.post("/admin/prism-alpha-evaluate")
    async def prism_alpha_evaluate_cron(request: Request):
        """External-cron entry point (same X-Cron-Key mechanism as every
        other scheduled job in this codebase) — recommend every 1 minute
        during 09:15-15:30 IST. Runs both Prism Alpha and Prism Alpha 2 in
        one call (they share the same underlying ATM CE/PE contracts)."""
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
        return await _status(VARIANT_CONFIG["prism_alpha"]["collection"])

    @router.get("/prism-alpha/stats")
    async def prism_alpha_stats():
        return await _stats(VARIANT_CONFIG["prism_alpha"]["collection"])

    @router.get("/prism-alpha/trades")
    async def prism_alpha_trades():
        return await _trades(VARIANT_CONFIG["prism_alpha"]["collection"])

    @router.get("/prism-alpha-2/status")
    async def prism_alpha2_status():
        return await _status(VARIANT_CONFIG["prism_alpha_2"]["collection"])

    @router.get("/prism-alpha-2/stats")
    async def prism_alpha2_stats():
        return await _stats(VARIANT_CONFIG["prism_alpha_2"]["collection"])

    @router.get("/prism-alpha-2/trades")
    async def prism_alpha2_trades():
        return await _trades(VARIANT_CONFIG["prism_alpha_2"]["collection"])

    # ---- Backtest (intraday, real 1-minute Definedge data — see
    # blackbox_backtest.py's module docstring for the real, verified data
    # constraints this works around) ------------------------------------
    async def _backtest_summary(variant: str, api_path: str):
        latest_run = await db.blackbox_backtest_runs.find_one({}, {"_id": 0}, sort=[("run_at", -1)])
        if not latest_run:
            return {"run": None, "stats": _compute_stats([])}
        collection_name = BACKTEST_COLLECTIONS[variant]
        trades = await db[collection_name].find(
            {"backtest_run_id": latest_run["backtest_run_id"]}, {"_id": 0, "chart_png": 0}
        ).to_list(5000)
        return {"run": latest_run, "stats": _compute_stats(trades)}

    async def _backtest_trades(variant: str, api_path: str):
        latest_run = await db.blackbox_backtest_runs.find_one({}, {"_id": 0}, sort=[("run_at", -1)])
        if not latest_run:
            return []
        collection_name = BACKTEST_COLLECTIONS[variant]
        trades = await db[collection_name].find(
            {"backtest_run_id": latest_run["backtest_run_id"]}, {"_id": 0, "chart_png": 0}
        ).sort("entry_time", -1).to_list(500)
        return [_public_trade(t, chart_url=f"/blackbox/{api_path}/backtest/chart/{t['id']}") for t in trades]

    async def _backtest_chart(variant: str, trade_id: str):
        collection_name = BACKTEST_COLLECTIONS[variant]
        trade = await db[collection_name].find_one({"id": trade_id}, {"_id": 0, "chart_png": 1})
        if not trade or not trade.get("chart_png"):
            raise HTTPException(status_code=404, detail="No chart for this trade.")
        return Response(content=bytes(trade["chart_png"]), media_type="image/png")

    @router.post("/admin/prism-alpha-backtest-run")
    async def prism_alpha_backtest_run(admin: dict = Depends(get_current_admin)):
        """On-demand, not scheduled — a backtest run fetches real 1-minute
        history for every candidate strike, which is heavier than a single
        live poll. Runs BOTH variants in one pass (see run_backtest)."""
        try:
            return await run_backtest(db, definedge)
        except Exception as e:  # noqa: BLE001
            raise HTTPException(status_code=502, detail=f"Backtest run failed: {e}")

    @router.get("/prism-alpha/backtest/summary")
    async def prism_alpha_backtest_summary():
        return await _backtest_summary("prism_alpha", "prism-alpha")

    @router.get("/prism-alpha/backtest/trades")
    async def prism_alpha_backtest_trades():
        return await _backtest_trades("prism_alpha", "prism-alpha")

    @router.get("/prism-alpha/backtest/chart/{trade_id}")
    async def prism_alpha_backtest_chart(trade_id: str):
        return await _backtest_chart("prism_alpha", trade_id)

    @router.get("/prism-alpha-2/backtest/summary")
    async def prism_alpha2_backtest_summary():
        return await _backtest_summary("prism_alpha_2", "prism-alpha-2")

    @router.get("/prism-alpha-2/backtest/trades")
    async def prism_alpha2_backtest_trades():
        return await _backtest_trades("prism_alpha_2", "prism-alpha-2")

    @router.get("/prism-alpha-2/backtest/chart/{trade_id}")
    async def prism_alpha2_backtest_chart(trade_id: str):
        return await _backtest_chart("prism_alpha_2", trade_id)

    # ---- Lumen SIP (Renko + MAST-cloud long-term ETF SIP allocation) -----
    # Phase is intentionally NOT concealed here — the underlying mechanics
    # come from a public Definedge education source, not a proprietary
    # pattern engine, so no field-stripping like Prism Alpha's _public_trade.
    #
    # LIVE (blackbox_lumen_sip_*) is a real, forward-only portfolio that
    # resumes from its last state. BACKTEST (blackbox_lumen_sip_backtest_*)
    # is an illustrative "since inception" replay, always rebuilt from zero
    # — same live/backtest split as Prism Alpha, just daily-bar-cadence
    # instead of per-minute.
    async def _lumen_sip_status(collection_name: str):
        latest = await db[collection_name].find_one({}, {"_id": 0}, sort=[("date", -1)])
        if not latest:
            return {"has_data": False}
        total = latest["total_value"] or 1.0  # guard div-by-zero on an all-cash, zero-value start
        return {
            "has_data": True,
            "as_of": latest["date"],
            "total_value": latest["total_value"],
            "instruments": {
                symbol.lower(): {
                    "phase": latest[f"{symbol.lower()}_phase"],
                    "units": latest[f"{symbol.lower()}_units"],
                    "cash": latest[f"{symbol.lower()}_cash"],
                    "value": latest[f"{symbol.lower()}_value"],
                    "allocation_pct": latest[f"{symbol.lower()}_value"] / total,
                }
                for symbol in LUMEN_SIP_INSTRUMENTS
            },
        }

    @router.post("/admin/lumen-sip-evaluate")
    async def lumen_sip_evaluate_cron(request: Request):
        """External-cron entry point for LIVE tracking — daily-bar strategy,
        recommend once/day after market close, not per-minute like Prism
        Alpha. Resumes from the last recorded live snapshot; safe to run
        even if a day or more was missed (catches up)."""
        if not cron_secret or request.headers.get("X-Cron-Key") != cron_secret:
            raise HTTPException(status_code=401, detail="Invalid cron key")
        try:
            return await evaluate_lumen_sip_live(db, definedge)
        except Exception as e:  # noqa: BLE001
            raise HTTPException(status_code=502, detail=f"Lumen SIP evaluation failed: {e}")

    @router.post("/admin/lumen-sip-evaluate-now")
    async def lumen_sip_evaluate_admin(admin: dict = Depends(get_current_admin)):
        """Same live evaluation, for manual testing from the admin panel."""
        try:
            return await evaluate_lumen_sip_live(db, definedge)
        except Exception as e:  # noqa: BLE001
            raise HTTPException(status_code=502, detail=f"Lumen SIP evaluation failed: {e}")

    @router.post("/admin/lumen-sip-backtest-run")
    async def lumen_sip_backtest_run(admin: dict = Depends(get_current_admin)):
        """On-demand only — replays the full available history (up to 10y)
        from a zero starting portfolio. Heavier than a live evaluation
        (re-fetches full history), not scheduled."""
        try:
            return await run_lumen_sip_backtest(db, definedge)
        except Exception as e:  # noqa: BLE001
            raise HTTPException(status_code=502, detail=f"Lumen SIP backtest run failed: {e}")

    @router.get("/lumen-sip/status")
    async def lumen_sip_status():
        return await _lumen_sip_status("blackbox_lumen_sip_portfolio")

    @router.get("/lumen-sip/portfolio")
    async def lumen_sip_portfolio():
        return await db.blackbox_lumen_sip_portfolio.find({}, {"_id": 0}).sort("date", 1).to_list(5000)

    @router.get("/lumen-sip/signals")
    async def lumen_sip_signals():
        return await db.blackbox_lumen_sip_signals.find({}, {"_id": 0}).sort("date", -1).to_list(2000)

    @router.get("/lumen-sip/backtest/status")
    async def lumen_sip_backtest_status():
        return await _lumen_sip_status("blackbox_lumen_sip_backtest_portfolio")

    @router.get("/lumen-sip/backtest/portfolio")
    async def lumen_sip_backtest_portfolio():
        return await db.blackbox_lumen_sip_backtest_portfolio.find({}, {"_id": 0}).sort("date", 1).to_list(5000)

    @router.get("/lumen-sip/backtest/signals")
    async def lumen_sip_backtest_signals():
        return await db.blackbox_lumen_sip_backtest_signals.find({}, {"_id": 0}).sort("date", -1).to_list(2000)

    @router.get("/lumen-sip/backtest/metrics")
    async def lumen_sip_backtest_metrics():
        """Institutional-grade metrics (XIRR, max drawdown, round-trip trade
        stats, vanilla-SIP benchmark) — precomputed once per backtest run
        (see run_lumen_sip_backtest), not recalculated on every page view."""
        doc = await db.blackbox_lumen_sip_backtest_metrics.find_one({"id": "current"}, {"_id": 0})
        return doc or {"has_data": False}

    return router
