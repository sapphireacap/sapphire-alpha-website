"""API for Intraday X% Breadth -- public, no auth, same tier as the other
Alpha Terminal live modules. See intraday_breadth.py for the computation.

Nifty 50 only for now (see that module's docstring) -- Nifty 500 is
accepted by /groups (so the frontend can show it as a real, named,
"coming soon" toggle rather than hiding it) but /refresh silently no-ops
for it rather than running the heavy 500-stock job.
"""
from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request

import intraday_breadth as ib

IST = timezone(timedelta(hours=5, minutes=30))

GROUPS = {
    "nifty-50": {"label": "Nifty 50", "live": True},
    "nifty-500": {"label": "Nifty 500", "live": False},
}


def create_intraday_breadth_router(db, definedge, get_current_admin, cron_secret: str) -> APIRouter:
    router = APIRouter(prefix="/terminal/intraday-breadth", tags=["intraday-breadth"])

    @router.get("/groups")
    async def groups():
        return {"groups": [{"key": k, "label": v["label"], "live": v["live"]} for k, v in GROUPS.items()]}

    @router.get("")
    async def series(group: str = "nifty-50"):
        if group not in GROUPS:
            raise HTTPException(status_code=404, detail=f"Unknown group '{group}'. Must be one of {', '.join(GROUPS)}.")
        if not GROUPS[group]["live"]:
            return {"has_data": False, "reason": f"{GROUPS[group]['label']} isn't available yet — coming soon."}
        trading_date = datetime.now(IST).strftime("%Y-%m-%d")
        doc = await db[ib.SERIES_CACHE_COLLECTION].find_one({"group": group, "trading_date": trading_date}, {"_id": 0})
        if not doc or not doc.get("series"):
            return {"has_data": False, "reason": "Today's intraday breadth hasn't been computed yet — check back shortly after market open."}
        return {"has_data": True, **doc}

    @router.get("/refresh-status")
    async def refresh_status(group: str = "nifty-50"):
        if group not in GROUPS:
            raise HTTPException(status_code=404, detail=f"Unknown group '{group}'. Must be one of {', '.join(GROUPS)}.")
        doc = await db[ib.REFRESH_STATUS_COLLECTION].find_one({"id": group}, {"_id": 0})
        return doc or {"status": "idle", "total": 0, "done": 0, "resolved": 0, "failed": 0}

    @router.post("/admin/refresh")
    async def refresh_cron(request: Request, background_tasks: BackgroundTasks, group: str = "nifty-50"):
        """External-cron entry point (same X-Cron-Key mechanism as every
        other scheduled job in this codebase). Returns immediately --
        the actual refresh runs as a background task, same reason
        breadth_routes.py's daily job does (a full-universe pass is a
        multi-minute job, not something a single request should block
        on)."""
        if not cron_secret or request.headers.get("X-Cron-Key") != cron_secret:
            raise HTTPException(status_code=401, detail="Invalid cron key")
        if group not in GROUPS:
            raise HTTPException(status_code=400, detail=f"Unknown group '{group}'. Must be one of {', '.join(GROUPS)}.")
        if not GROUPS[group]["live"]:
            return {"skipped": f"{group} not enabled yet"}
        background_tasks.add_task(ib.refresh, db, definedge, group)
        return {"status": "started"}

    @router.post("/admin/refresh-now")
    async def refresh_admin(background_tasks: BackgroundTasks, group: str = "nifty-50", admin: dict = Depends(get_current_admin)):
        if group not in GROUPS:
            raise HTTPException(status_code=400, detail=f"Unknown group '{group}'. Must be one of {', '.join(GROUPS)}.")
        if not GROUPS[group]["live"]:
            return {"skipped": f"{group} not enabled yet"}
        background_tasks.add_task(ib.refresh, db, definedge, group)
        return {"status": "started"}

    return router
