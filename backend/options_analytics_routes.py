"""
Options Analytics routes — Max Pain, PCR, and IV Rank/Percentile for
NIFTY/BANKNIFTY/FINNIFTY, mounted under /api by server.py via
create_options_analytics_router(db, get_current_admin, cron_secret).

Reuses dhan_options_client.chain() directly (same rate-limit/cache
singleton already shared with index_vector_flip.py — importing it here
does not add a second limiter, since the module-level lock/cache in
dhan_options_client.py is process-wide). No new external dependency.

IV Rank/Percentile needs a stored history, since a single day's IV
reading has nothing to be "ranked" against — a small daily snapshot job
(admin/cron-triggered, same X-Cron-Key pattern used elsewhere) writes
today's ATM IV per index into options_iv_history once per day.
"""
import logging
from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request

import dhan_options_client as doc
from options_analytics import max_pain, put_call_ratio, atm_iv, iv_rank_and_percentile

logger = logging.getLogger(__name__)
IST = timezone(timedelta(hours=5, minutes=30))
INDICES = ("NIFTY", "BANKNIFTY", "FINNIFTY")


def create_options_analytics_router(db, get_current_admin, cron_secret: str) -> APIRouter:
    router = APIRouter(prefix="/options-analytics")

    @router.get("/{index}")
    async def analytics(index: str):
        index = index.strip().upper()
        if index not in INDICES:
            return {"found": False, "reason": f"Unknown index '{index}'. Choose one of {', '.join(INDICES)}."}

        try:
            data = await doc.chain(db, index)
        except doc.DhanOptionsError as e:
            return {"found": False, "reason": str(e)}

        strikes = data["strikes"]
        if not strikes:
            return {"found": False, "reason": f"No option chain data available for {index} right now."}

        mp = max_pain(strikes)
        pcr = put_call_ratio(strikes)
        iv = atm_iv(strikes, data["spot"])

        rank_info = {"iv_rank": None, "iv_percentile": None, "history_days": 0}
        if iv is not None:
            today_ist = datetime.now(IST).strftime("%Y-%m-%d")
            history_docs = await db.options_iv_history.find(
                {"index": index, "date": {"$ne": today_ist}}, {"_id": 0, "atm_iv": 1}
            ).to_list(400)
            history = [d["atm_iv"] for d in history_docs if d.get("atm_iv") is not None]
            rank_info = iv_rank_and_percentile(iv, history)

        return {
            "found": True,
            "index": index,
            "expiry": data["expiry"],
            "spot": data["spot"],
            "fetched_at": data["fetched_at"],
            "max_pain": mp,
            "pcr": round(pcr, 3) if pcr is not None else None,
            "atm_iv": round(iv, 4) if iv is not None else None,
            **rank_info,
        }

    @router.post("/admin/snapshot-iv")
    async def snapshot_iv_cron(request: Request):
        """External-cron entry point, same X-Cron-Key mechanism used
        elsewhere — meant to run once daily (e.g. shortly after close) to
        build up the IV history that iv_rank/percentile needs."""
        if not cron_secret or request.headers.get("X-Cron-Key") != cron_secret:
            raise HTTPException(status_code=401, detail="Invalid cron key")
        return await _snapshot_iv(db)

    @router.post("/admin/snapshot-iv-now")
    async def snapshot_iv_admin(admin: dict = Depends(get_current_admin)):
        """Same snapshot, admin-JWT-gated for a manual trigger from the
        admin panel (useful the first few days, before the cron has run
        enough times to build a meaningful history)."""
        return await _snapshot_iv(db)

    return router


async def _snapshot_iv(db) -> dict:
    today_ist = datetime.now(IST).strftime("%Y-%m-%d")
    saved, failed = [], []
    for index in INDICES:
        try:
            data = await doc.chain(db, index)
            iv = atm_iv(data["strikes"], data["spot"])
            if iv is None:
                failed.append({"index": index, "reason": "No usable ATM IV in today's chain."})
                continue
            await db.options_iv_history.update_one(
                {"index": index, "date": today_ist},
                {"$set": {"index": index, "date": today_ist, "atm_iv": iv,
                          "recorded_at": datetime.now(timezone.utc).isoformat()}},
                upsert=True,
            )
            saved.append(index)
        except doc.DhanOptionsError as e:
            logger.warning("IV snapshot failed for %s: %s", index, e)
            failed.append({"index": index, "reason": str(e)})
    return {"date": today_ist, "saved": saved, "failed": failed}
