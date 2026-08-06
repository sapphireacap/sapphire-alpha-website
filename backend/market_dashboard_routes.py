"""API for the Market Dashboard — public, no auth, same tier as the other
Alpha Terminal live modules. Free/public data only (NSE's unofficial JSON
endpoints + Yahoo Finance) — deliberately independent of any Definedge
session, unlike the rest of this codebase's live modules, so it works even
when nobody's done the daily OTP login.

Three NSE sources (see market_dashboard_client.py) plus Yahoo global
indices are fetched INDEPENDENTLY, each wrapped so one failing never blocks
the others — the snapshot doc carries whichever sections succeeded plus an
`errors` map for whichever didn't, rather than the whole card grid going
blank because one upstream source hiccuped.
"""
import asyncio
import logging
from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request

import market_dashboard_client as mdc
import market_dashboard_engine as mde
import yahoo_finance_client as yf

logger = logging.getLogger(__name__)

IST = timezone(timedelta(hours=5, minutes=30))

SNAPSHOT_COLLECTION = "market_dashboard_snapshot"
AD_HISTORY_COLLECTION = "market_dashboard_ad_history"
FII_DII_HISTORY_COLLECTION = "market_dashboard_fii_dii_history"

# Yahoo tickers for the Global Indices card — verified live, 2026-08-06.
# GIFT Nifty deliberately excluded: no free Yahoo ticker resolves for it.
GLOBAL_INDICES = [
    {"key": "DJI", "label": "Dow Jones", "yahoo": "%5EDJI"},
    {"key": "DOW_FUT", "label": "Dow Futures", "yahoo": "YM=F"},
    {"key": "IXIC", "label": "Nasdaq", "yahoo": "%5EIXIC"},
    {"key": "GSPC", "label": "S&P 500", "yahoo": "%5EGSPC"},
    {"key": "AXJO", "label": "ASX 200", "yahoo": "%5EAXJO"},
]


def create_market_dashboard_router(db, get_current_admin, cron_secret: str) -> APIRouter:
    router = APIRouter(prefix="/terminal/market-dashboard", tags=["market-dashboard"])

    async def _fetch_indices_section() -> tuple:
        """(shaped_dict_or_None, error_str_or_None)."""
        try:
            payload = await mdc.fetch_all_indices()
            return mde.shape_all_indices(payload), None
        except mdc.MarketDashboardError as e:
            logger.warning("Market Dashboard allIndices fetch failed: %s", e)
            return None, str(e)

    async def _fetch_fii_dii_section() -> tuple:
        try:
            rows = await mdc.fetch_fii_dii()
            return mde.shape_fii_dii(rows), None
        except mdc.MarketDashboardError as e:
            logger.warning("Market Dashboard FII/DII fetch failed: %s", e)
            return None, str(e)

    async def _fetch_hilo_section() -> tuple:
        try:
            return await mdc.fetch_52week_hilo(), None
        except mdc.MarketDashboardError as e:
            logger.warning("Market Dashboard 52-week hi/lo fetch failed: %s", e)
            return None, str(e)

    async def _fetch_global_indices_section() -> tuple:
        """Each ticker resolved independently — one bad Yahoo symbol
        drops just that row, not the whole card (same discipline as the
        NSE sections, just at finer grain since this card has 5
        sub-sources)."""
        out = []
        errors = []
        for g in GLOBAL_INDICES:
            try:
                q = await yf.quote_snapshot(g["yahoo"])
                out.append({"key": g["key"], "label": g["label"], **q})
            except yf.YahooFinanceError as e:
                logger.warning("Market Dashboard global index fetch failed for %s: %s", g["key"], e)
                errors.append(f"{g['key']}: {e}")
        return out, ("; ".join(errors) if errors and not out else None)

    async def _refresh_snapshot():
        """Runs as a background task — fetches all four sections
        concurrently, stores whatever succeeded, and separately appends to
        the two accumulate-forever history collections (intraday A-D,
        daily FII/DII) so those cards have something to chart, not just a
        single latest point."""
        now_ist = datetime.now(IST)
        (indices, indices_err), (fii_dii, fii_dii_err), (hilo, hilo_err), (globals_, globals_err) = await asyncio.gather(
            _fetch_indices_section(), _fetch_fii_dii_section(), _fetch_hilo_section(), _fetch_global_indices_section(),
        )

        snapshot = {
            "id": "current",
            "indices": indices,
            "fii_dii": fii_dii,
            "week_hilo": hilo,
            "global_indices": globals_,
            "errors": {k: v for k, v in {
                "indices": indices_err, "fii_dii": fii_dii_err, "week_hilo": hilo_err, "global_indices": globals_err,
            }.items() if v},
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        await db[SNAPSHOT_COLLECTION].update_one({"id": "current"}, {"$set": snapshot}, upsert=True)

        if indices is not None:
            today = now_ist.date().isoformat()
            await db[AD_HISTORY_COLLECTION].insert_one({
                "date": today,
                "time": now_ist.strftime("%H:%M"),
                "advances": indices["market_advances"],
                "declines": indices["market_declines"],
                "unchanged": indices["market_unchanged"],
                "recorded_at": datetime.now(timezone.utc).isoformat(),
            })

        if fii_dii is not None and (fii_dii.get("fii") or fii_dii.get("dii")):
            date_key = (fii_dii.get("fii") or fii_dii.get("dii"))["date"]
            await db[FII_DII_HISTORY_COLLECTION].update_one(
                {"date": date_key},
                {"$set": {"date": date_key, "fii": fii_dii.get("fii"), "dii": fii_dii.get("dii")}},
                upsert=True,
            )

    @router.get("/snapshot")
    async def snapshot():
        doc = await db[SNAPSHOT_COLLECTION].find_one({"id": "current"}, {"_id": 0})
        if not doc:
            raise HTTPException(status_code=404, detail="Market Dashboard hasn't been computed yet — trigger a refresh.")
        return doc

    @router.get("/advance-decline-intraday")
    async def advance_decline_intraday():
        """Today's (IST) accumulated advances/declines readings — the
        Intraday Advance-Decline line chart. Only today's date, not the
        whole accumulate-forever history (that's for later trend cards,
        not this one)."""
        today = datetime.now(IST).date().isoformat()
        rows = await db[AD_HISTORY_COLLECTION].find({"date": today}, {"_id": 0}).sort("recorded_at", 1).to_list(length=500)
        return {"date": today, "points": rows}

    @router.get("/fii-dii-history")
    async def fii_dii_history(days: int = 15):
        rows = await db[FII_DII_HISTORY_COLLECTION].find({}, {"_id": 0}).sort("date", -1).to_list(length=days)
        return {"rows": rows}

    @router.post("/admin/refresh")
    async def refresh_cron(request: Request, background_tasks: BackgroundTasks):
        """External-cron entry point (same X-Cron-Key mechanism as every
        other scheduled job in this codebase)."""
        if not cron_secret or request.headers.get("X-Cron-Key") != cron_secret:
            raise HTTPException(status_code=401, detail="Invalid cron key")
        background_tasks.add_task(_refresh_snapshot)
        return {"status": "started"}

    @router.post("/admin/refresh-now")
    async def refresh_admin(background_tasks: BackgroundTasks, admin: dict = Depends(get_current_admin)):
        background_tasks.add_task(_refresh_snapshot)
        return {"status": "started"}

    return router
