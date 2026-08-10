"""API for the Multi Asset Returns chart (Market Assessment) -- public,
no auth. Each asset's daily closes over the requested window, normalized
to 100 at its own first point in that window (not a shared calendar
start) so every line begins level and the chart reads as cumulative %
return, not raw price level.

Nifty GS Composite (government securities index) is NOT wired up --
NSE's historical-index endpoint (unlike the live /api/allIndices
snapshot market_dashboard_client.py already uses successfully) sits
behind real bot-detection (confirmed live, 2026-08-10: 503 with an
obfuscated JS challenge script, cookie warm-up included, not just a
missing-header issue). Reported as unavailable rather than fabricated
or silently dropped.
"""
import logging

from fastapi import APIRouter, HTTPException

import yahoo_finance_client as yf

logger = logging.getLogger(__name__)

ASSETS = {
    "NIFTY50": {"yahoo": "%5ENSEI", "label": "Nifty 50"},
    "USDINR": {"yahoo": "USDINR=X", "label": "USDINR-I"},
    "GOLD": {"yahoo": "GC=F", "label": "GOLD-I"},
    "GSEC": {"yahoo": None, "label": "Nifty GS Composite"},
}


def create_multi_asset_returns_router() -> APIRouter:
    router = APIRouter(prefix="/terminal/multi-asset-returns", tags=["multi-asset-returns"])

    @router.get("")
    async def multi_asset_returns(days: int = 90):
        range_ = f"{max(30, min(days, 365))}d"
        assets, unavailable = [], []

        for key, cfg in ASSETS.items():
            if not cfg["yahoo"]:
                unavailable.append({"key": key, "label": cfg["label"], "reason": "No working data source yet."})
                continue
            try:
                bars = await yf.daily_bars_for_ticker(cfg["yahoo"], range_=range_)
            except yf.YahooFinanceError as e:
                logger.warning("Multi asset returns: fetch failed for %s: %s", key, e)
                unavailable.append({"key": key, "label": cfg["label"], "reason": "Temporarily unavailable."})
                continue
            if not bars:
                unavailable.append({"key": key, "label": cfg["label"], "reason": "No data returned."})
                continue
            base = bars[0]["close"]
            points = [{"date": b["date"], "value": round((b["close"] / base) * 100, 3)} for b in bars if base]
            assets.append({
                "key": key, "label": cfg["label"],
                "change_pct": round(points[-1]["value"] - 100, 2) if points else None,
                "points": points,
            })

        if not assets:
            raise HTTPException(status_code=502, detail="No asset data available right now.")
        return {"assets": assets, "unavailable": unavailable}

    return router
