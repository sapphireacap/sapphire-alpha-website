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
YEARS_BACK = 3  # enough history for a meaningful column count even at a 3% box


def create_relative_strength_router(db, definedge) -> APIRouter:
    router = APIRouter(prefix="/terminal/relative-strength", tags=["relative-strength"])

    @router.get("/groups")
    async def groups():
        return {"groups": [
            {"key": k, "label": v["label"], "symbols": v["symbols"]} for k, v in GROUPS.items()
        ]}

    async def _closes_for(symbol: str, master) -> dict:
        """{date: close} for one symbol, cached in Mongo for the rest of
        the calendar day — a 8-12 symbol group means every matrix request
        costs that many live Definedge calls otherwise, and nothing about
        a day's already-closed daily bar changes intraday."""
        today = datetime.now(IST).date().isoformat()
        doc = await db[CACHE_COLLECTION].find_one({"symbol": symbol})
        if doc and doc.get("last_fetched_date") == today:
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
            {"$set": {"symbol": symbol, "last_fetched_date": today, "closes": closes}},
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

        # Align to dates every symbol in the group actually has a close
        # for — a ratio needs both sides priced the same day, so a date
        # missing for even one symbol (holiday mismatch, late listing) is
        # dropped for the whole group rather than silently comparing
        # mismatched days.
        common_dates = sorted(set.intersection(*(set(c.keys()) for c in closes_maps)))
        if len(common_dates) < 2:
            raise HTTPException(status_code=400, detail="Not enough overlapping price history for this group yet.")
        closes_by_symbol = {s: [per_symbol[s][d] for d in common_dates] for s in symbols}

        result = rsm.compute_ranking(symbols, closes_by_symbol, values)

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
