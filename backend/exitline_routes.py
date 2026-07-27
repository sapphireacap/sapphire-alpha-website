"""Exitline routes — public Alpha Terminal tool (segment -> scrip -> level
ladder + SL/TP). Same "public compute endpoint, backed by the site's own
shared broker session" pattern as Quant Lab's EWMA/Sharpe tools — no
per-visitor login needed. See exitline.py for the calculation/lookup logic.

Error messages surfaced to callers are sanitized (_public_error) — internal
DefinedgeError text sometimes names the upstream vendor/session mechanics
directly (e.g. "Definedge session expired..."), which must never reach a
public response; everything here is presented as Sapphire's own proprietary
model, not attributed to any external source."""
from typing import Optional

from fastapi import APIRouter, HTTPException

from definedge_service import DefinedgeError
from exitline import build_exitline_response, list_symbols, list_expiries, list_strikes

VALID_SEGMENTS = ("NSE", "FUT", "OPT")


def _public_error(e: DefinedgeError) -> str:
    msg = str(e)
    if "definedge" in msg.lower():
        return "Levels are temporarily unavailable — please try again shortly."
    return msg  # instrument-specific messages (not found / no prior-day data) don't name any source


def create_exitline_router(db, definedge) -> APIRouter:
    router = APIRouter(prefix="/exitline", tags=["exitline"])

    def _check_segment(segment: str) -> str:
        segment = segment.strip().upper()
        if segment not in VALID_SEGMENTS:
            raise HTTPException(status_code=400, detail="segment must be one of NSE, FUT, OPT")
        return segment

    @router.get("/instruments")
    async def instruments(segment: str, query: str = "", symbol: Optional[str] = None, expiry: Optional[str] = None):
        """Populates the scrip selector, and — once a symbol (and, for OPT,
        an expiry) is chosen — the expiry/strike lists. One endpoint for all
        three so the frontend doesn't need three separate calls wired to
        subtly different loading states."""
        segment = _check_segment(segment)
        try:
            master = await definedge._get_all_master()
        except DefinedgeError as e:
            raise HTTPException(status_code=502, detail=_public_error(e))

        if symbol and segment in ("FUT", "OPT"):
            expiries = list_expiries(master, segment, symbol)
            strikes = list_strikes(master, symbol, expiry) if (segment == "OPT" and expiry) else []
            return {"symbols": [], "expiries": expiries, "strikes": strikes}

        return {"symbols": list_symbols(master, segment, query), "expiries": [], "strikes": []}

    @router.get("/levels")
    async def levels(segment: str, symbol: str, expiry: Optional[str] = None,
                      strike: Optional[float] = None, option_type: Optional[str] = None):
        segment = _check_segment(segment)
        if segment == "FUT" and not expiry:
            raise HTTPException(status_code=400, detail="expiry is required for FUT")
        if segment == "OPT" and not (expiry and strike is not None and option_type):
            raise HTTPException(status_code=400, detail="expiry, strike, and option_type are required for OPT")

        try:
            return await build_exitline_response(db, definedge, segment, symbol, expiry, strike, option_type)
        except DefinedgeError as e:
            raise HTTPException(status_code=502, detail=_public_error(e))

    return router
