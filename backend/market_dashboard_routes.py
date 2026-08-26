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
import time
from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, WebSocket, WebSocketDisconnect

import market_dashboard_client as mdc
import market_dashboard_engine as mde
import market_dashboard_stream as mds
import yahoo_finance_client as yf

logger = logging.getLogger(__name__)

IST = timezone(timedelta(hours=5, minutes=30))

# Protects NSE's unofficial endpoint from being hit once per open browser
# tab -- every visitor polling /live-headline collapses onto one upstream
# call per this window (same pattern as exitline_routes.py's LTP_CACHE_TTL
# and definedge_service.py's SPOT_CACHE_TTL).
LIVE_HEADLINE_CACHE_TTL = 4.0  # seconds
_live_headline_cache = {"at": 0.0, "data": None}

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


def create_market_dashboard_router(db, get_current_admin, cron_secret: str, market_dashboard_stream=None) -> APIRouter:
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

        if indices is not None and market_dashboard_stream is not None:
            # Refreshes the previous-close reference every streamed index's
            # live ticks are computed against (see market_dashboard_stream's
            # module docstring for why LTP alone can't derive change/pct).
            for row in indices["headline"] + indices["sectors"] + indices["segments"]:
                market_dashboard_stream.set_reference(row["index"], row["last"], row["change"])

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

    @router.get("/live-headline")
    async def live_headline():
        """Just the 5 headline index rows (NIFTY 50/BANK/500/MIDCAP 150/
        SMALLCAP 250), fetched fresh from NSE on every call (short server
        cache below) rather than read from the periodically-refreshed
        snapshot doc -- that snapshot's own refresh cadence lives on an
        external cron (cron-job.org, see market-dashboard-refresh.yml),
        which the frontend has no visibility into and shouldn't have to
        trust for something as visible as the top ticker strip. This route
        gives that strip its own fast, independent polling loop.

        Falls back to the last good read on any NSE hiccup (never a 5xx
        for a transient upstream blip) so a flaky poll doesn't blank the
        strip -- same "keep the last known value" discipline as
        /terminal/spot."""
        now = time.monotonic()
        cached = _live_headline_cache["data"]
        if cached and now - _live_headline_cache["at"] < LIVE_HEADLINE_CACHE_TTL:
            return cached
        try:
            payload = await mdc.fetch_all_indices()
            shaped = mde.shape_all_indices(payload)
            out = {"headline": shaped["headline"], "as_of": shaped["as_of"]}
        except mdc.MarketDashboardError as e:
            if cached:
                return cached
            raise HTTPException(status_code=502, detail=f"Live index levels unavailable: {e}")
        _live_headline_cache["at"] = now
        _live_headline_cache["data"] = out
        return out

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

    @router.websocket("/stream")
    async def stream(websocket: WebSocket):
        """Public, no auth -- same tier as every other route on this
        router. Pushes a live tick for one index at a time as it arrives
        (not batched), so a browser client merges each message into
        whichever of headline/sectors/segments contains that index name.
        Falls back to the existing polls if this drops -- this is a pure
        addition, nothing about the snapshot/live-headline routes changed."""
        if market_dashboard_stream is None:
            await websocket.close(code=1011)
            return
        await websocket.accept()

        async def _push(payload: dict) -> None:
            await websocket.send_json(payload)

        mds.broadcaster.subscribe(_push)
        try:
            for entry in market_dashboard_stream.latest().values():
                await websocket.send_json(entry)
            while True:
                await websocket.receive_text()
        except WebSocketDisconnect:
            pass
        finally:
            mds.broadcaster.unsubscribe(_push)

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
