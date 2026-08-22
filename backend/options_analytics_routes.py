"""
Options Analytics routes — Max Pain, PCR, and IV Rank/Percentile for
NIFTY/BANKNIFTY/FINNIFTY, mounted under /api by server.py via
create_options_analytics_router(db, definedge).

Fully automatic, no manual or scheduled step required: IV Rank/Percentile
ranks today's live ATM IV (from dhan_options_client.chain(), same
rate-limit/cache singleton already shared with index_vector_flip.py)
against the underlying's own realized-volatility history (computed live
from ordinary daily closes definedge.daily_history() already provides) —
see options_analytics.py's realized_vol_series() docstring for why that
proxy is used instead of real historical IV, which no vendor here exposes.
"""
from datetime import datetime, timezone, timedelta

from fastapi import APIRouter

import dhan_options_client as doc
from definedge_service import INDEX_CONFIG
from options_analytics import max_pain, put_call_ratio, atm_iv, realized_vol_series, iv_rank_and_percentile

IST = timezone(timedelta(hours=5, minutes=30))
INDICES = ("NIFTY", "BANKNIFTY", "FINNIFTY")
REALIZED_VOL_WINDOW = 20  # trading days per rolling vol reading
REALIZED_VOL_YEARS = 5    # how far back to build the historical distribution from


def create_options_analytics_router(db, definedge) -> APIRouter:
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
            cfg = INDEX_CONFIG[index]
            try:
                bars = await definedge.daily_history(cfg["spot_segment"], cfg["spot_token"], years=REALIZED_VOL_YEARS)
            except Exception:  # noqa: BLE001 — a failed history fetch degrades to "no rank yet", not a hard error
                bars = []
            closes = [b["close"] for b in bars if b.get("close")]
            history = realized_vol_series(closes, REALIZED_VOL_WINDOW)
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

    return router
