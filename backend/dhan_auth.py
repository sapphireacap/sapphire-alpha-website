"""Dhan access-token auto-login via TOTP.

Dhan access tokens live exactly 24 hours (confirmed by decoding a real
token's JWT claims: iat 2026-08-17 09:07 UTC, exp 2026-08-18 09:07 UTC).
Anything on the site that reads IV / option chain / Greeks therefore needs
a fresh token daily, or it starts 401ing every morning -- the same class
of problem definedge_otp_email.py already solves for Definedge.

WHICH DHAN FLOW THIS USES, AND WHY NOT THE OTHER ONE
----------------------------------------------------
Dhan documents two ways to obtain a token programmatically:

  1. TOTP           POST https://auth.dhan.co/app/generateAccessToken
                    ?dhanClientId=..&pin=..&totp=..
                    Pure server-to-server. No browser. THIS is what the
                    module implements.

  2. API key/secret POST /app/generate-consent  -> consentAppId
                    then a BROWSER login at /login/consentApp-login
                    then POST /app/consumeApp-consent -> accessToken

Flow 2 is the one the API key and secret belong to, and it cannot be fully
automated: step 2 is an interactive browser login that returns a tokenId
via redirect. Flow 1 needs no key/secret at all -- only the client id, the
6-digit Dhan PIN, and a TOTP code. So the key/secret pair is not what
enables automation here; the TOTP seed is.

CREDENTIALS THIS NEEDS
----------------------
  DHAN_CLIENT_ID    already configured (also embedded in the token's
                    dhanClientId claim, which is how a mismatch gets
                    caught below)
  DHAN_PIN          the 6-digit Dhan login PIN
  DHAN_TOTP_SECRET  the base32 seed shown when TOTP was enrolled (NOT the
                    6-digit code, which rotates every 30s)

Storing the PIN and the TOTP seed together means this process can
authenticate as the account unattended -- that is inherent to unattended
broker auth, not something this module can design around, and it is the
same trade definedge_otp_email.py already makes by holding a mailbox
password. Keep both in the environment only; never in the repo.

The token is cached in Mongo so every caller in the process shares one
login rather than each triggering its own, and is refreshed when it is
within REFRESH_MARGIN of expiry.
"""
from __future__ import annotations

import base64
import json
import logging
import os
from datetime import datetime, timedelta, timezone

import httpx

logger = logging.getLogger(__name__)

AUTH_URL = "https://auth.dhan.co/app/generateAccessToken"
TOKEN_COLLECTION = "dhan_access_token"
# Refresh this far before expiry rather than at it -- a token that expires
# mid-request is a 401 the caller has to recover from.
REFRESH_MARGIN = timedelta(hours=2)


class DhanAuthError(Exception):
    """Login problems -- safe to show an admin, never a public caller."""


def _decode_expiry(token: str):
    """Read `exp` out of the token's own JWT claims rather than trusting
    the response's expiryTime string, whose format Dhan doesn't document
    precisely. Returns None if the token isn't a decodable JWT."""
    try:
        payload = token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        claims = json.loads(base64.urlsafe_b64decode(payload))
    except Exception:  # noqa: BLE001 — a non-JWT token is handled, not fatal
        return None
    exp = claims.get("exp")
    return datetime.fromtimestamp(exp, timezone.utc) if exp else None


def _decode_client_id(token: str):
    try:
        payload = token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        return str(json.loads(base64.urlsafe_b64decode(payload)).get("dhanClientId") or "") or None
    except Exception:  # noqa: BLE001
        return None


def configured() -> bool:
    return all(os.environ.get(k) for k in ("DHAN_CLIENT_ID", "DHAN_PIN", "DHAN_TOTP_SECRET"))


def _current_totp() -> str:
    import pyotp
    secret = (os.environ.get("DHAN_TOTP_SECRET") or "").strip().replace(" ", "")
    if not secret:
        raise DhanAuthError("DHAN_TOTP_SECRET is not configured.")
    try:
        return pyotp.TOTP(secret).now()
    except Exception as e:  # noqa: BLE001 — almost always a non-base32 seed
        raise DhanAuthError(
            "Could not generate a TOTP code — DHAN_TOTP_SECRET must be the base32 "
            "enrolment seed, not the rotating 6-digit code."
        ) from e


async def login() -> dict:
    """Fresh access token straight from Dhan. Returns
    {access_token, expires_at, client_id}. Raises DhanAuthError with the
    real upstream message rather than a generic failure -- the dhanhq SDK
    collapses auth errors into {"status": "failure"} with a null message,
    which cost real debugging time, so this module never goes through it."""
    if not configured():
        missing = [k for k in ("DHAN_CLIENT_ID", "DHAN_PIN", "DHAN_TOTP_SECRET") if not os.environ.get(k)]
        raise DhanAuthError(f"Dhan auto-login not configured — missing {', '.join(missing)}.")

    params = {
        "dhanClientId": os.environ["DHAN_CLIENT_ID"].strip(),
        "pin": os.environ["DHAN_PIN"].strip(),
        "totp": _current_totp(),
    }
    try:
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.post(AUTH_URL, params=params, headers={"Accept": "application/json"})
    except httpx.HTTPError as e:
        raise DhanAuthError(f"Dhan auth request failed: {e}") from e

    if r.status_code != 200:
        # Surface Dhan's own body -- its auth errors are specific (DH-901
        # invalid credentials, and a distinct code for a bad/expired TOTP)
        # and a generic message would hide which one it is.
        raise DhanAuthError(f"Dhan auth returned HTTP {r.status_code}: {r.text[:300]}")

    try:
        data = r.json()
    except ValueError as e:
        raise DhanAuthError(f"Dhan auth returned non-JSON: {r.text[:200]}") from e

    token = data.get("accessToken")
    if not token:
        raise DhanAuthError(f"Dhan auth returned no accessToken: {json.dumps(data)[:300]}")

    embedded = _decode_client_id(token)
    if embedded and embedded != params["dhanClientId"]:
        raise DhanAuthError("Dhan returned a token for a different client id than requested.")

    expires_at = _decode_expiry(token) or (datetime.now(timezone.utc) + timedelta(hours=23))
    return {"access_token": token, "expires_at": expires_at, "client_id": embedded or params["dhanClientId"]}


async def get_access_token(db, force: bool = False) -> str:
    """The token every Dhan caller should use.

    Order of preference:
      1. the cached token in Mongo, if it isn't near expiry
      2. a fresh TOTP login
      3. a static DHAN_ACCESS_TOKEN from the environment, if one is set and
         still valid -- the pre-automation path, kept as a fallback so a
         TOTP misconfiguration degrades to "yesterday's manual token" for
         its remaining life instead of taking the feature down outright.
    """
    now = datetime.now(timezone.utc)

    if not force:
        doc = await db[TOKEN_COLLECTION].find_one({"id": "current"}, {"_id": 0})
        if doc and doc.get("access_token") and doc.get("expires_at"):
            try:
                if datetime.fromisoformat(doc["expires_at"]) - REFRESH_MARGIN > now:
                    return doc["access_token"]
            except ValueError:
                pass  # unparseable cache entry -- fall through and re-login

    try:
        result = await login()
    except DhanAuthError as e:
        static = os.environ.get("DHAN_ACCESS_TOKEN")
        static_exp = _decode_expiry(static) if static else None
        if static and (static_exp is None or static_exp > now):
            logger.warning("Dhan TOTP login failed (%s) — falling back to the static DHAN_ACCESS_TOKEN.", e)
            return static
        raise

    await db[TOKEN_COLLECTION].update_one(
        {"id": "current"},
        {"$set": {"id": "current", "access_token": result["access_token"],
                   "expires_at": result["expires_at"].isoformat(),
                   "client_id": result["client_id"],
                   "refreshed_at": now.isoformat()}},
        upsert=True,
    )
    logger.info("Dhan access token refreshed, valid until %s", result["expires_at"].isoformat())
    return result["access_token"]


async def status(db) -> dict:
    """Health for the admin panel -- never returns the token itself."""
    doc = await db[TOKEN_COLLECTION].find_one({"id": "current"}, {"_id": 0})
    out = {"configured": configured(), "has_cached_token": bool(doc and doc.get("access_token"))}
    if doc:
        out["expires_at"] = doc.get("expires_at")
        out["refreshed_at"] = doc.get("refreshed_at")
        try:
            out["valid"] = datetime.fromisoformat(doc["expires_at"]) > datetime.now(timezone.utc)
        except (ValueError, KeyError, TypeError):
            out["valid"] = False
    return out
