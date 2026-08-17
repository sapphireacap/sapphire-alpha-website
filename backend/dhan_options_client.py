"""Dhan option chain — the site's source for IV, option chain and Greeks.

Division of labour, set deliberately: Definedge supplies every PRICE
SERIES the charts and P&F engines are built from (straddle legs, ATM legs,
index history); Dhan supplies IV / chain / Greeks, which Definedge's API
does not expose at all (verified: /quotes carries no delta, gamma, theta,
vega or iv field). Neither vendor crosses into the other's job.

Verified live, 2026-08-17, against a real NIFTY chain -- not assumed from
docs:
  POST /v2/optionchain/expirylist  -> {"data": ["2026-08-18", ...]}
  POST /v2/optionchain             -> 231 strikes, each with ce/pe blocks
                                      carrying implied_volatility and a
                                      nested greeks{delta,theta,gamma,vega}

Two constraints worth knowing before calling this:

  RATE LIMIT   Dhan documents ~1 request per 3 seconds on the option
               chain. MIN_CHAIN_INTERVAL below enforces it process-wide,
               and the per-expiry cache exists so a page render never
               issues more than one upstream call.

  IV UNITS     implied_volatility comes back in PERCENT (14.61 for a real
               NIFTY ATM call), while Black-Scholes wants a decimal. iv()
               divides by 100 exactly once, here, so no caller has to
               remember -- getting this wrong silently produces flip
               levels that are wrong by orders of magnitude rather than
               failing loudly.

Auth is handled by dhan_auth.get_access_token(), which keeps a TOTP-issued
token fresh; Dhan tokens last only 24h.
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
from datetime import datetime, timezone

import httpx

import dhan_auth

logger = logging.getLogger(__name__)

BASE_URL = "https://api.dhan.co/v2"
# Dhan's documented option-chain limit is one call per 3s; a little margin
# on top since a 429 here costs more than the wait does.
MIN_CHAIN_INTERVAL = 3.2
CACHE_TTL_SECONDS = 60

# Underlying scrip ids, confirmed against Dhan's own scrip master -- the
# same two dhan_client.py already verifies at runtime.
UNDERLYINGS = {
    "NIFTY": {"scrip": 13, "segment": "IDX_I"},
    "BANKNIFTY": {"scrip": 25, "segment": "IDX_I"},
}

_last_chain_call = 0.0
_rate_lock = asyncio.Lock()
_cache: dict = {}  # (index, expiry) -> (fetched_at, payload)


class DhanOptionsError(Exception):
    """Upstream problems -- safe to show an admin, never a public caller."""


async def _post(db, path: str, payload: dict) -> dict:
    token = await dhan_auth.get_access_token(db)
    headers = {
        "access-token": token,
        "client-id": os.environ.get("DHAN_CLIENT_ID", ""),
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    try:
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.post(f"{BASE_URL}/{path}", headers=headers, json=payload)
    except httpx.HTTPError as e:
        raise DhanOptionsError(f"Dhan request failed: {e}") from e

    if r.status_code == 401:
        # The cached token may have been revoked before its own expiry
        # (generating a new token invalidates prior ones). One forced
        # re-login, then give up rather than loop.
        logger.info("Dhan returned 401 — forcing a token refresh and retrying once.")
        headers["access-token"] = await dhan_auth.get_access_token(db, force=True)
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.post(f"{BASE_URL}/{path}", headers=headers, json=payload)

    if r.status_code != 200:
        raise DhanOptionsError(f"Dhan {path} returned HTTP {r.status_code}: {r.text[:250]}")
    try:
        return r.json()
    except ValueError as e:
        raise DhanOptionsError(f"Dhan {path} returned non-JSON: {r.text[:200]}") from e


def _resolve(index: str) -> dict:
    meta = UNDERLYINGS.get((index or "").strip().upper())
    if not meta:
        raise DhanOptionsError(
            f"No Dhan option chain configured for {index}. Known: {', '.join(UNDERLYINGS)}."
        )
    return meta


async def expiry_list(db, index: str) -> list:
    """Expiry dates (ascending, 'YYYY-MM-DD') for one underlying."""
    meta = _resolve(index)
    data = await _post(db, "optionchain/expirylist",
                       {"UnderlyingScrip": meta["scrip"], "UnderlyingSeg": meta["segment"]})
    expiries = data.get("data") or []
    if not expiries:
        raise DhanOptionsError(f"Dhan returned no expiries for {index}.")
    return expiries


async def chain(db, index: str, expiry: str = None) -> dict:
    """{expiry, spot, strikes: {strike: {"ce": {...}, "pe": {...}}}} for one
    expiry, defaulting to the nearest.

    Each ce/pe block is normalised to {ltp, iv, oi, volume, delta, gamma,
    theta, vega} -- `iv` already converted from Dhan's percent to a decimal
    (see the module docstring). Cached for CACHE_TTL_SECONDS per expiry and
    rate-limited process-wide."""
    index = (index or "").strip().upper()
    meta = _resolve(index)
    expiry = expiry or (await expiry_list(db, index))[0]

    key = (index, expiry)
    hit = _cache.get(key)
    if hit and (time.monotonic() - hit[0]) < CACHE_TTL_SECONDS:
        return hit[1]

    async with _rate_lock:
        global _last_chain_call
        wait = MIN_CHAIN_INTERVAL - (time.monotonic() - _last_chain_call)
        if wait > 0:
            await asyncio.sleep(wait)
        raw = await _post(db, "optionchain", {
            "UnderlyingScrip": meta["scrip"], "UnderlyingSeg": meta["segment"], "Expiry": expiry,
        })
        _last_chain_call = time.monotonic()

    data = raw.get("data") or {}
    oc = data.get("oc") or {}
    if not oc:
        raise DhanOptionsError(f"Dhan returned an empty {index} chain for {expiry}.")

    def side(block: dict) -> dict | None:
        if not block:
            return None
        g = block.get("greeks") or {}
        raw_iv = block.get("implied_volatility")
        return {
            "ltp": block.get("last_price"),
            # Percent -> decimal, exactly once, here.
            "iv": (raw_iv / 100.0) if isinstance(raw_iv, (int, float)) and raw_iv else None,
            "iv_pct": raw_iv,
            "oi": block.get("oi"),
            "volume": block.get("volume"),
            "delta": g.get("delta"), "gamma": g.get("gamma"),
            "theta": g.get("theta"), "vega": g.get("vega"),
        }

    strikes = {}
    for raw_strike, sides in oc.items():
        try:
            strike = float(raw_strike)
        except (TypeError, ValueError):
            continue
        ce, pe = side(sides.get("ce")), side(sides.get("pe"))
        if ce or pe:
            strikes[strike] = {"ce": ce, "pe": pe}

    payload = {
        "index": index, "expiry": expiry,
        "spot": data.get("last_price"),
        "strikes": strikes,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
    }
    _cache[key] = (time.monotonic(), payload)
    return payload


async def iv_for_strike(db, index: str, strike: float, expiry: str = None) -> dict:
    """{"ce": iv, "pe": iv, "expiry": ..., "strike": ...} as DECIMALS, for
    the listed strike nearest `strike`.

    This is the call index_vector_flip.py wants: it replaces backing IV out
    of an LTP with Newton-Raphson, which had real failure modes at the
    extremes (near-zero vega on deep ITM/OTM, and a 1e-4 fallback whenever
    price sat at intrinsic). Snaps to the nearest LISTED strike rather than
    assuming the requested one exists."""
    data = await chain(db, index, expiry)
    if not data["strikes"]:
        raise DhanOptionsError(f"No strikes in the {index} chain.")
    nearest = min(data["strikes"], key=lambda s: abs(s - float(strike)))
    sides = data["strikes"][nearest]
    return {
        "index": index, "expiry": data["expiry"], "strike": nearest,
        "requested_strike": float(strike), "spot": data["spot"],
        "ce": (sides.get("ce") or {}).get("iv"),
        "pe": (sides.get("pe") or {}).get("iv"),
        "ce_greeks": sides.get("ce"), "pe_greeks": sides.get("pe"),
    }
