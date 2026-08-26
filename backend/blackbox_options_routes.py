"""
PUBLIC routes for Premium Band Strangle inside the existing Black Box tab.
Deliberately separate from blackbox_routes.py's create_blackbox_router,
which is entirely admin-gated by explicit prior instruction for the
ORIGINAL three strategies (Prism Alpha, Prism Alpha 2, Lumen SIP) -- this
one is public by a LATER, separate explicit instruction ("New strategies
go public, existing 3 stay admin-only"). Same router-factory /
cron-vs-admin-JWT twin pattern as every other cron-driven feature in this
codebase, just with the read routes left open instead of admin-gated.

FULL detail (real config numbers, live signals, performance) is further
gated to a single named account (see blackbox_access.py) -- every read
route stays publicly reachable (200 for anyone), but a visitor who isn't
that account gets a locked/"coming soon" shape back instead of the real
numbers. `get_current_user_optional` never 401s (unlike get_current_admin),
so this doesn't require signing in at all to get a response -- it only
changes WHAT the response contains.

Every read route only ever returns paper-mode data right now (MODE is
hardcoded "paper" in blackbox_options_engine.py until the user explicitly
approves going live) -- there is nothing to accidentally leak.

Convexity Window and Gamma Backspread (the original two strategies here,
plus their EOD job and backtest harness) were removed entirely on
2026-08-26, code and production data both, per explicit instruction --
see git history if either is ever wanted back.
"""
import logging

from fastapi import APIRouter, HTTPException, Request, Depends

from blackbox_access import is_owner
from blackbox_options_config import get_config
from blackbox_options_engine import evaluate_all, MODE, STRATEGIES

logger = logging.getLogger(__name__)

INDICES = ("NIFTY", "BANKNIFTY")

STRATEGY_LABELS = {
    "premium_band_strangle": {
        "name": "Premium Band Strangle",
        "description": "Sells a monthly-expiry NIFTY call and put whose live premium sits closest to a fixed target band — no Greeks, no chart reading. Legs are rolled back into the band on a fixed profit, a fixed loss, or the premium approaching double its entry value.",
    },
}


def create_blackbox_options_router(db, definedge, get_current_admin, get_current_user_optional, cron_secret: str) -> APIRouter:
    router = APIRouter(prefix="/blackbox")
    require_user_optional = Depends(get_current_user_optional)

    # ----------------------------------------------------------- public reads

    @router.get("/strategies")
    async def strategies(user: dict | None = require_user_optional):
        out = []
        for strategy_id in STRATEGIES:
            entry = {"strategy_id": strategy_id, **STRATEGY_LABELS[strategy_id], "mode": MODE, "indices": {}}
            if not is_owner(user):
                entry["locked"] = True
                out.append(entry)
                continue
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
        return {"mode": MODE, "strategies": out, "locked": not is_owner(user)}

    @router.get("/signals")
    async def signals(limit: int = 100, index: str = None, strategy_id: str = None,
                      user: dict | None = require_user_optional):
        if not is_owner(user):
            return {"mode": MODE, "count": 0, "signals": [], "locked": True}
        limit = max(1, min(limit, 1000))
        q = {"mode": MODE}
        if index:
            q["index"] = index.upper()
        if strategy_id:
            q["strategy_id"] = strategy_id
        docs = await db.blackbox_signals.find(q, {"_id": 0}).sort("timestamp", -1).to_list(limit)
        return {"mode": MODE, "count": len(docs), "signals": docs, "locked": False}

    @router.get("/performance")
    async def performance(index: str = None, strategy_id: str = None, user: dict | None = require_user_optional):
        if not is_owner(user):
            return {"mode": MODE, "count": 0, "daily": [], "locked": True}
        q = {"mode": MODE}
        if index:
            q["index"] = index.upper()
        if strategy_id:
            q["strategy_id"] = strategy_id
        docs = await db.blackbox_daily_performance.find(q, {"_id": 0}).sort("date", 1).to_list(5000)
        return {"mode": MODE, "count": len(docs), "daily": docs, "locked": False}

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

    return router
