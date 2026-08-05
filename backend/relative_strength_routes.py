"""API for the Relative Strength Matrix — public, no auth, same tier as
Alpha Terminal's other live modules (Index Vector, Exitline, Momentum
Leaders). See relative_strength_matrix.py for the actual computation and
relative_strength_groups.py for the fixed sector baskets.
"""
import asyncio
import logging
from datetime import datetime

from fastapi import APIRouter, HTTPException

import relative_strength_matrix as rsm
from definedge_service import IST, DefinedgeError
from relative_strength_groups import GROUPS, get_group

logger = logging.getLogger(__name__)

CACHE_COLLECTION = "rs_daily_closes"
# The box grid is an ABSOLUTE grid (pnf_engine.py rule 8) so the current
# LEVEL never depends on how much history is loaded, but the current
# DIRECTION does - it's whatever direction the last reversal set, and a 3%
# (or even 1%) box on a ratio chart can go years between reversals. A
# truncated window that starts mid-swing locks in a fabricated "first
# column" (rule 4: only 1 box needed to open a column, not a full reversal)
# that may never get corrected before "today", producing a direction that
# diverges from Definedge's own chart (which uses full available history).
# 20y comfortably covers a 3-box reversal at 3% for these liquid bank
# stocks and costs nothing extra - daily_history() just returns whatever
# actually exists if the instrument is younger.
YEARS_BACK = 20


def create_relative_strength_router(db, definedge) -> APIRouter:
    router = APIRouter(prefix="/terminal/relative-strength", tags=["relative-strength"])

    @router.get("/groups")
    async def groups():
        return {"groups": [
            {"key": k, "label": v["label"], "symbols": v["symbols"]} for k, v in GROUPS.items()
        ]}

    async def _closes_for(symbol: str, master) -> dict:
        """{date: close} for one symbol, cached in Mongo once today's own
        close is actually in it — a 8-12 symbol group means every matrix
        request costs that many live Definedge calls otherwise, and
        nothing about a day's already-closed daily bar changes intraday.

        Freshness is keyed on whether TODAY's date is actually a key in
        the cached closes, not on when the cache was last written —
        Definedge's day-history only grows a TODAY row once that day's
        candle is finalised (same gap pnf_chart.py's _with_live_bar works
        around for the single-symbol chart), so a request made before
        market close would otherwise lock in a version missing today's
        close for the rest of the day, even after the market closes.

        Also keyed on YEARS_BACK itself (stored as `years_back` on the
        doc) — a cache written under an older, shorter window would
        otherwise look "fresh" forever (today's close doesn't stop being
        in it) and never pick up the wider history a YEARS_BACK bump
        requires. Docs from before this field existed (`years_back`
        missing) are treated as stale too."""
        today = datetime.now(IST).date().isoformat()
        doc = await db[CACHE_COLLECTION].find_one({"symbol": symbol})
        if doc and today in doc.get("closes", {}) and doc.get("years_back") == YEARS_BACK:
            return doc["closes"]

        found = definedge.resolve_symbol(master, "NSE", symbol)
        if not found:
            raise HTTPException(status_code=502, detail=f"Could not resolve {symbol}.")
        try:
            bars = await definedge.daily_history("NSE", found["token"], years=YEARS_BACK)
        except DefinedgeError as e:
            logger.warning("Daily history fetch failed for %s: %s", symbol, e)
            raise HTTPException(status_code=502,
                                detail="Chart data is temporarily unavailable — please try again shortly.")
        closes = {b["date"]: b["close"] for b in bars}
        await db[CACHE_COLLECTION].update_one(
            {"symbol": symbol},
            {"$set": {"symbol": symbol, "last_fetched_date": today, "years_back": YEARS_BACK, "closes": closes}},
            upsert=True,
        )
        return closes

    @router.get("/matrix")
    async def matrix(group: str, box_pcts: str = "0.25,1,3"):
        """Full multi-box-size matrix + ranking for one fixed group. Box
        sizes default to the book's own short/medium/long-term convention
        (0.25% / 1% / 3%) — pass a different comma-separated list to
        override."""
        cfg = get_group(group)
        if not cfg:
            raise HTTPException(status_code=404,
                                detail=f"Unknown group '{group}'. Must be one of {', '.join(GROUPS)}.")
        tokens = [t.strip() for t in box_pcts.split(",") if t.strip()]
        try:
            values = [float(t) for t in tokens]
        except ValueError:
            raise HTTPException(status_code=400, detail="box_pcts must be comma-separated numbers.")
        if not values:
            raise HTTPException(status_code=400, detail="Provide at least one box_pct.")
        label_by_value = dict(zip(values, tokens))

        symbols = cfg["symbols"]
        try:
            master = await definedge._get_all_master()
        except DefinedgeError:
            raise HTTPException(status_code=502,
                                detail="Chart data is temporarily unavailable — please try again shortly.")

        closes_maps = await asyncio.gather(*[_closes_for(s, master) for s in symbols])
        per_symbol = dict(zip(symbols, closes_maps))

        # NOT truncated to a group-wide date intersection — rsm.compute_matrix
        # aligns each PAIR to its own common dates. A group-wide intersection
        # here would clip every pair's history down to the group's youngest
        # listing (e.g. BANDHANBNK, 2018), starving pairs of two long-listed
        # stocks (e.g. HDFCBANK vs PNB) of history they actually have for no
        # reason connected to that pair — confirmed live (2026-08-05) as
        # exactly what was producing scores off by 1-2 vs Definedge's real
        # scanner for symbols involved with a newer-listed peer.
        common_dates = sorted(set.intersection(*(set(c.keys()) for c in closes_maps)))
        if len(common_dates) < 2:
            raise HTTPException(status_code=400, detail="Not enough overlapping price history for this group yet.")

        result = rsm.compute_ranking(symbols, per_symbol, values)

        return {
            "group": group,
            "label": cfg["label"],
            "symbols": symbols,
            "as_of": common_dates[-1],
            "history_from": common_dates[0],
            "box_pcts": tokens,
            "matrices": {
                label_by_value[bp]: {"grid": m["grid"], "scores": m["scores"]}
                for bp, m in result["matrices"].items()
            },
            "ranking": [
                {"symbol": r["symbol"],
                 "scores": {label_by_value[bp]: sc for bp, sc in r["scores"].items()},
                 "total": r["total"]}
                for r in result["ranking"]
            ],
        }

    return router
