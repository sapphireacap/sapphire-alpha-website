"""
PUBLIC routes for the two new options-buying strategies (Convexity Window,
Gamma Backspread) inside the existing Black Box tab. Deliberately separate
from blackbox_routes.py's create_blackbox_router, which is entirely
admin-gated by explicit prior instruction for the ORIGINAL three
strategies (Prism Alpha, Prism Alpha 2, Lumen SIP) -- these two are public
by a LATER, separate explicit instruction ("New strategies go public,
existing 3 stay admin-only"). Same router-factory / cron-vs-admin-JWT twin
pattern as every other cron-driven feature in this codebase, just with the
read routes left open instead of admin-gated.

Every read route only ever returns paper-mode data right now (MODE is
hardcoded "paper" in blackbox_options_engine.py until the user explicitly
approves going live) -- there is nothing to accidentally leak.
"""
import logging
from datetime import datetime

from fastapi import APIRouter, HTTPException, Request, Depends

from blackbox_options_config import get_config
from blackbox_options_engine import evaluate_all, MODE, STRATEGIES
from blackbox_options_eod import run_eod
from blackbox_options_backtest import backtest_convexity_window, backtest_gamma_backspread
from definedge_service import IST, INDEX_CONFIG

logger = logging.getLogger(__name__)

INDICES = ("NIFTY", "BANKNIFTY")

STRATEGY_LABELS = {
    "convexity_window": {
        "name": "Convexity Window",
        "description": "Conditional long ATM options — enters only when the vol regime suggests convexity is underpriced (IV/RV filter, required-move filter, Gamma/Theta contract selection, price-only direction).",
    },
    "gamma_backspread": {
        "name": "Gamma Backspread",
        "description": "Sells 1 ATM option, buys 2 OTM of the same type/expiry — a near-zero-theta convexity structure, entered only when ATM IV percentile is cheap.",
    },
}


def create_blackbox_options_router(db, definedge, get_current_admin, cron_secret: str) -> APIRouter:
    router = APIRouter(prefix="/blackbox")

    # ----------------------------------------------------------- public reads

    @router.get("/strategies")
    async def strategies():
        out = []
        for strategy_id in STRATEGIES:
            entry = {"strategy_id": strategy_id, **STRATEGY_LABELS[strategy_id], "mode": MODE, "indices": {}}
            for index_key in INDICES:
                cfg = await get_config(db, index_key)
                status = await db.blackbox_strategy_status.find_one(
                    {"index": index_key, "strategy_id": strategy_id, "mode": MODE}, {"_id": 0}
                )
                entry["indices"][index_key] = {
                    "config": cfg[strategy_id],
                    "status": (status or {}).get("status", "flat"),
                    "reason": (status or {}).get("reason"),
                    "filters": (status or {}).get("filters", {}),
                    "updated_at": (status or {}).get("updated_at"),
                }
            out.append(entry)
        return {"mode": MODE, "strategies": out}

    @router.get("/signals")
    async def signals(limit: int = 100, index: str = None, strategy_id: str = None):
        limit = max(1, min(limit, 1000))
        q = {"mode": MODE}
        if index:
            q["index"] = index.upper()
        if strategy_id:
            q["strategy_id"] = strategy_id
        docs = await db.blackbox_signals.find(q, {"_id": 0}).sort("timestamp", -1).to_list(limit)
        return {"mode": MODE, "count": len(docs), "signals": docs}

    @router.get("/performance")
    async def performance(index: str = None, strategy_id: str = None):
        q = {"mode": MODE}
        if index:
            q["index"] = index.upper()
        if strategy_id:
            q["strategy_id"] = strategy_id
        docs = await db.blackbox_daily_performance.find(q, {"_id": 0}).sort("date", 1).to_list(5000)
        return {"mode": MODE, "count": len(docs), "daily": docs}

    @router.get("/backtest-runs")
    async def backtest_runs():
        """The Phase-1 backtest findings — real Definedge data, whatever
        small sample currently exists (see blackbox_options_backtest.py's
        module docstring for the exact data-availability constraint)."""
        docs = await db.blackbox_options_backtest_runs.find({}, {"_id": 0}).sort("recorded_at", -1).to_list(50)
        return {"count": len(docs), "runs": docs}

    # ----------------------------------------------------------- cron + admin

    @router.post("/options-evaluate")
    async def options_evaluate_cron(request: Request):
        """External-cron entry point — every 5 minutes during 09:15-15:30
        IST (GitHub Actions' real granularity ceiling; there is no
        cron-job.org 1-minute integration anywhere in this repo)."""
        if not cron_secret or request.headers.get("X-Cron-Key") != cron_secret:
            raise HTTPException(status_code=401, detail="Invalid cron key")
        try:
            return await evaluate_all(db, definedge)
        except Exception as e:  # noqa: BLE001
            raise HTTPException(status_code=502, detail=f"Blackbox options evaluation failed: {e}")

    @router.post("/options-evaluate-now")
    async def options_evaluate_admin(admin: dict = Depends(get_current_admin)):
        """Same evaluation, for manual testing from the admin panel."""
        try:
            return await evaluate_all(db, definedge)
        except Exception as e:  # noqa: BLE001
            raise HTTPException(status_code=502, detail=f"Blackbox options evaluation failed: {e}")

    @router.post("/options-eod-close")
    async def options_eod_cron(request: Request):
        """External-cron entry point — once daily at 15:35 IST. Force-closes
        open positions and writes the day's IMMUTABLE performance record."""
        if not cron_secret or request.headers.get("X-Cron-Key") != cron_secret:
            raise HTTPException(status_code=401, detail="Invalid cron key")
        try:
            return await run_eod(db, definedge)
        except Exception as e:  # noqa: BLE001
            raise HTTPException(status_code=502, detail=f"Blackbox options EOD job failed: {e}")

    @router.post("/options-eod-close-now")
    async def options_eod_admin(admin: dict = Depends(get_current_admin)):
        try:
            return await run_eod(db, definedge)
        except Exception as e:  # noqa: BLE001
            raise HTTPException(status_code=502, detail=f"Blackbox options EOD job failed: {e}")

    @router.post("/options-backtest-run")
    async def options_backtest_run(admin: dict = Depends(get_current_admin)):
        """Manual re-run of the Phase-1 backtest (admin only — this hits
        Definedge with a real, moderately expensive data pull, not something
        to expose for public/cron triggering)."""
        results = []
        for index_key in INDICES:
            try:
                results.append(await backtest_convexity_window(db, definedge, index_key))
                results.append(await backtest_gamma_backspread(db, definedge, index_key))
            except Exception as e:  # noqa: BLE001
                raise HTTPException(status_code=502, detail=f"Backtest failed for {index_key}: {e}")
        now_iso = datetime.now(IST).isoformat()
        for r in results:
            r["recorded_at"] = now_iso
        await db.blackbox_options_backtest_runs.insert_many([dict(r) for r in results])
        return {"runs": results}

    return router
