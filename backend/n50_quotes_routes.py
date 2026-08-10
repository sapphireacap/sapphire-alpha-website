"""API for the N50 live quote board -- public, no auth, same tier as the
other Alpha Terminal live modules. See n50_quotes.py for the refresh job.
"""
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request

import n50_quotes as nq


def create_n50_quotes_router(db, definedge, get_current_admin, cron_secret: str) -> APIRouter:
    router = APIRouter(prefix="/terminal/n50-quotes", tags=["n50-quotes"])

    @router.get("")
    async def quotes():
        doc = await db[nq.QUOTES_COLLECTION].find_one({"id": "current"}, {"_id": 0})
        if not doc:
            raise HTTPException(status_code=404, detail="N50 quote board hasn't been computed yet — trigger a refresh.")
        return doc

    @router.get("/refresh-status")
    async def refresh_status():
        doc = await db[nq.REFRESH_STATUS_COLLECTION].find_one({"id": nq.GROUP}, {"_id": 0})
        return doc or {"status": "idle", "total": 0, "done": 0, "resolved": 0, "failed": 0}

    @router.post("/admin/refresh")
    async def refresh_cron(request: Request, background_tasks: BackgroundTasks):
        if not cron_secret or request.headers.get("X-Cron-Key") != cron_secret:
            raise HTTPException(status_code=401, detail="Invalid cron key")
        background_tasks.add_task(nq.refresh, db, definedge)
        return {"status": "started"}

    @router.post("/admin/refresh-now")
    async def refresh_admin(background_tasks: BackgroundTasks, admin: dict = Depends(get_current_admin)):
        background_tasks.add_task(nq.refresh, db, definedge)
        return {"status": "started"}

    return router
