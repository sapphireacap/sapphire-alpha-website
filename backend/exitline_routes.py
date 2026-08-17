"""Exitline routes — public Alpha Terminal tool (segment -> scrip -> level
ladder + SL/TP). Same "public compute endpoint, backed by the site's own
shared broker session" pattern as Quant Lab's EWMA/Sharpe tools — no
per-visitor login needed. See exitline.py for the calculation/lookup logic.

Error messages surfaced to callers are sanitized (_public_error) — internal
DefinedgeError text sometimes names the upstream vendor/session mechanics
directly (e.g. "Definedge session expired..."), which must never reach a
public response; everything here is presented as Sapphire's own proprietary
model, not attributed to any external source."""
import time
from typing import Optional

from fastapi import APIRouter, HTTPException

from definedge_service import DefinedgeError
from exitline import (
    build_exitline_response, list_symbols, list_expiries, list_strikes,
    resolve_instrument, VALID_INTERVALS,
)

VALID_SEGMENTS = ("NSE", "FUT", "OPT")

# The quote route below is polled every couple of seconds by every open
# chart, so identical instruments collapse into one upstream call. Matches
# definedge_service.SPOT_CACHE_TTL, which exists for the same reason.
LTP_CACHE_TTL = 2.0
_ltp_cache: dict = {}


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
                      strike: Optional[float] = None, option_type: Optional[str] = None,
                      interval: int = 5):
        segment = _check_segment(segment)
        if segment == "FUT" and not expiry:
            raise HTTPException(status_code=400, detail="expiry is required for FUT")
        if segment == "OPT" and not (expiry and strike is not None and option_type):
            raise HTTPException(status_code=400, detail="expiry, strike, and option_type are required for OPT")
        if interval not in VALID_INTERVALS:
            raise HTTPException(status_code=400, detail=f"interval must be one of {VALID_INTERVALS}")

        try:
            return await build_exitline_response(db, definedge, segment, symbol, expiry, strike, option_type, interval)
        except DefinedgeError as e:
            raise HTTPException(status_code=502, detail=_public_error(e))

    @router.get("/quote")
    async def quote(segment: str, symbol: str, expiry: Optional[str] = None,
                     strike: Optional[float] = None, option_type: Optional[str] = None):
        """Just the LTP for the same instrument /levels resolves — a tiny,
        fast-pollable payload so the chart's forming candle can move without
        refetching the whole 30-session series on every tick.

        /terminal/spot cannot serve this: it only knows the three index
        keys, while Exitline covers arbitrary NSE cash, futures and option
        contracts.

        Cached for LTP_CACHE_TTL so many concurrent viewers of the same
        instrument collapse into one upstream call, and returns
        {"ltp": null} rather than an error on any hiccup — the caller keeps
        showing its last known price instead of blanking."""
        segment = _check_segment(segment)
        try:
            master = await definedge._get_all_master()
        except DefinedgeError as e:
            raise HTTPException(status_code=502, detail=_public_error(e))
        resolved = resolve_instrument(master, segment, symbol, expiry, strike, option_type)
        if not resolved:
            raise HTTPException(status_code=404, detail="Instrument not found.")

        key = (resolved["segment"], resolved["token"])
        now = time.monotonic()
        cached = _ltp_cache.get(key)
        if cached and now - cached[0] < LTP_CACHE_TTL:
            return {"ltp": cached[1]}
        try:
            ltp = await definedge.equity_quote(resolved["segment"], resolved["token"])
        except DefinedgeError:
            return {"ltp": None}
        _ltp_cache[key] = (now, ltp)
        return {"ltp": ltp}

    return router
