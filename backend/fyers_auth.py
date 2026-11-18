"""FYERS access-token management: automatic, no human step.

FYERS access tokens expire EVERY DAY AT 06:30 IST
(https://fyers.in/api-docs/v3/api/authentication/individual-app/authentication-flow/).
This module keeps a working token in Mongo (`fyers_token`, id "current"), in this order:

  1. the stored access token, if it is still valid (not within MARGIN of 06:30 IST)
  2. REFRESH (official, documented): POST /api/v3/validate-refresh-token with the stored
     refresh token + the account PIN -> a new access token. The refresh token lasts about
     15 days, so this covers almost every morning with no browser and no TOTP.
  3. TOTP LOGIN (the fallback, and the very first login): log in from scratch with the
     FYERS id, PIN and a TOTP code, get an auth code, exchange it at
     /api/v3/validate-authcode -> access token + a new refresh token.

!! Step 3 is NOT an official, documented API: it is the flow of FYERS' own sample script
(`auto_login_totp`) and of many community projects. Its endpoints have changed and broken
before (users report 403s, "human verification", and TOTP errors). It was written from
those reports and has NOT been run against a live account yet, so the first real run is a
validation pass. The refresh path (2) is the official one and is tried first.

SAFETY
  * Disabled unless FYERS_ENABLED=1, so nothing here sends a request until you turn it on.
  * One login at a time (lock), and after ANY failed login attempt a cooldown
    (LOGIN_COOLDOWN seconds) before the next: failed TOTP attempts count against the
    account ("2 attempts left"), so a retry loop could lock you out.
  * Secrets are read from the environment only and never put in an error message.

ENV (Render + backend/.env):
  FYERS_ENABLED=1
  FYERS_APP_ID           the app id, with suffix, e.g. ABCD1234E5-100
  FYERS_SECRET_ID        the app secret
  FYERS_REDIRECT_URI     exactly the redirect URL set in the FYERS app
  FYERS_CLIENT_ID        your FYERS login id (e.g. XA12345)
  FYERS_PIN              your 4-digit FYERS PIN
  FYERS_TOTP_SECRET      base32 seed from enabling TOTP in your FYERS account
"""
import asyncio
import base64
import hashlib
import logging
import os
import re
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlparse

import httpx

logger = logging.getLogger(__name__)

IST = timezone(timedelta(hours=5, minutes=30))
API = "https://api-t1.fyers.in/api/v3"
VAGATOR = "https://api-t2.fyers.in/vagator/v2"
TOKEN_COLLECTION = "fyers_token"
EXPIRY_TIME = (6, 30)                     # tokens expire daily at 06:30 IST
MARGIN = timedelta(minutes=15)            # renew this long BEFORE expiry
REFRESH_TOKEN_DAYS = 14                   # FYERS says about 15; stop trusting one a day early
LOGIN_COOLDOWN = 300                      # seconds to wait after a failed login attempt
RATE_LIMIT_COOLDOWN = 3600                # after "Too many requests" (HTTP 429): hammering it only extends the block

_lock = asyncio.Lock()
_last_failure = {"at": 0.0, "message": ""}


class FyersAuthError(Exception):
    """Safe to show an admin; never contains a secret."""


def enabled() -> bool:
    return os.environ.get("FYERS_ENABLED", "").strip().lower() in ("1", "true", "yes", "on")


def _env(name: str) -> str:
    return (os.environ.get(name) or "").strip()


def missing_settings(for_totp: bool = True) -> list:
    names = ["FYERS_APP_ID", "FYERS_SECRET_ID"]
    if for_totp:
        names += ["FYERS_REDIRECT_URI", "FYERS_CLIENT_ID", "FYERS_PIN", "FYERS_TOTP_SECRET"]
    else:
        names += ["FYERS_PIN"]
    return [n for n in names if not _env(n)]


def app_id_hash() -> str:
    """SHA-256 of "app_id:app_secret" (the appIdHash both token endpoints require)."""
    return hashlib.sha256(f"{_env('FYERS_APP_ID')}:{_env('FYERS_SECRET_ID')}".encode()).hexdigest()


def next_expiry(now: datetime = None) -> datetime:
    """The next 06:30 IST strictly after `now`: when a token issued now stops working."""
    now = (now or datetime.now(IST)).astimezone(IST)
    nxt = now.replace(hour=EXPIRY_TIME[0], minute=EXPIRY_TIME[1], second=0, microsecond=0)
    return nxt if nxt > now else nxt + timedelta(days=1)


def _normalise_secret(raw: str) -> str:
    raw = (raw or "").strip()
    m = re.search(r"secret=([A-Za-z2-7=]+)", raw)       # accept a full otpauth:// URI too
    return re.sub(r"\s+", "", m.group(1) if m else raw).upper()


def _totp_now() -> str:
    import pyotp
    try:
        return pyotp.TOTP(_normalise_secret(_env("FYERS_TOTP_SECRET"))).now()
    except Exception as e:  # noqa: BLE001 -- almost always a non-base32 seed
        raise FyersAuthError("FYERS_TOTP_SECRET must be the base32 seed shown when TOTP was enabled, "
                             "not the rotating 6-digit code.") from e


def _b64(s: str) -> str:
    return base64.b64encode(s.encode()).decode()


def _http() -> httpx.AsyncClient:    # replaced in tests
    return httpx.AsyncClient(timeout=30)


def _short(r: httpx.Response) -> str:
    return f"HTTP {r.status_code} {r.text[:150]}".replace("\n", " ")


def _json(r: httpx.Response, step: str, ok_status=(200,)) -> dict:
    try:
        data = r.json()
    except ValueError as e:
        raise FyersAuthError(f"FYERS {step}: not JSON ({_short(r)})") from e
    if r.status_code not in ok_status or data.get("s") == "error":
        raise FyersAuthError(f"FYERS {step} failed: {_short(r)}")
    return data


# ---- the two ways to get a token ------------------------------------------------------
async def _refresh(http: httpx.AsyncClient, refresh_token: str) -> dict:
    r = await http.post(f"{API}/validate-refresh-token", json={
        "grant_type": "refresh_token", "appIdHash": app_id_hash(),
        "refresh_token": refresh_token, "pin": _env("FYERS_PIN")})
    data = _json(r, "refresh")
    if not data.get("access_token"):
        raise FyersAuthError(f"FYERS refresh returned no access_token: {_short(r)}")
    return {"access_token": data["access_token"], "refresh_token": data.get("refresh_token") or refresh_token,
            "new_refresh_token": bool(data.get("refresh_token"))}


async def _totp_login(http: httpx.AsyncClient) -> dict:
    """UNVERIFIED unofficial flow (see module docstring)."""
    fy_id, app_id = _env("FYERS_CLIENT_ID"), _env("FYERS_APP_ID")
    base_id, _, app_type = app_id.partition("-")
    d = _json(await http.post(f"{VAGATOR}/send_login_otp_v2", json={"fy_id": _b64(fy_id), "app_id": "2"}), "login step 1 (send otp)")
    d = _json(await http.post(f"{VAGATOR}/verify_otp", json={"request_key": d.get("request_key"), "otp": _totp_now()}),
              "login step 2 (verify totp)")
    d = _json(await http.post(f"{VAGATOR}/verify_pin_v2", json={
        "request_key": d.get("request_key"), "identity_type": "pin", "identifier": _b64(_env("FYERS_PIN"))}),
        "login step 3 (verify pin)")
    bearer = (d.get("data") or {}).get("access_token")
    if not bearer:
        raise FyersAuthError("FYERS login step 3 returned no session token.")
    r = await http.post(f"{API}/token", headers={"Authorization": f"Bearer {bearer}"}, json={
        "fyers_id": fy_id, "app_id": base_id, "redirect_uri": _env("FYERS_REDIRECT_URI"), "appType": app_type or "100",
        "code_challenge": "", "state": "sas", "scope": "", "nonce": "", "response_type": "code", "create_cookie": True})
    # FYERS answers this step with the redirect URL in the body, and some versions use HTTP 308 even on success.
    d = _json(r, "login step 4 (auth code)", ok_status=(200, 308))
    url = d.get("Url") or d.get("url") or ""
    code = (parse_qs(urlparse(url).query).get("auth_code") or [None])[0]
    if not code:
        raise FyersAuthError(f"FYERS login step 4 returned no auth code: {_short(r)}")
    r = await http.post(f"{API}/validate-authcode", json={"grant_type": "authorization_code", "appIdHash": app_id_hash(), "code": code})
    data = _json(r, "login step 5 (validate auth code)")
    if not data.get("access_token"):
        raise FyersAuthError(f"FYERS validate-authcode returned no access_token: {_short(r)}")
    return {"access_token": data["access_token"], "refresh_token": data.get("refresh_token"), "new_refresh_token": True}


# ---- orchestration --------------------------------------------------------------------
def _valid(doc: dict, now: datetime) -> bool:
    try:
        return bool(doc and doc.get("access_token")) and datetime.fromisoformat(doc["access_expires_at"]) - MARGIN > now
    except (KeyError, ValueError, TypeError):
        return False


def _refresh_usable(doc: dict, now: datetime) -> bool:
    try:
        got = datetime.fromisoformat(doc["refresh_obtained_at"])
    except (KeyError, ValueError, TypeError):
        return False
    return bool(doc.get("refresh_token")) and now - got < timedelta(days=REFRESH_TOKEN_DAYS)


async def get_access_token(db, force: bool = False) -> str:
    """A working access token, renewed automatically. Raises FyersAuthError with what to do."""
    if not enabled():
        raise FyersAuthError("FYERS is not enabled (set FYERS_ENABLED=1 once the credentials are in place).")
    now = datetime.now(IST)
    doc = await db[TOKEN_COLLECTION].find_one({"id": "current"}, {"_id": 0})
    if not force and _valid(doc, now):
        return doc["access_token"]

    async with _lock:
        doc = await db[TOKEN_COLLECTION].find_one({"id": "current"}, {"_id": 0})
        now = datetime.now(IST)
        if not force and _valid(doc, now):          # another caller renewed it while we waited
            return doc["access_token"]
        since = time.monotonic() - _last_failure["at"]
        wait = _last_failure.get("wait", LOGIN_COOLDOWN)
        if _last_failure["at"] and since < wait:
            raise FyersAuthError(f"FYERS login is cooling down after a failure ({int(wait - since)} s left): "
                                 f"{_last_failure['message']}")
        problems = missing_settings(for_totp=False)
        if problems:
            raise FyersAuthError(f"FYERS settings missing: {', '.join(problems)}.")

        result, how, errors = None, None, []
        async with _http() as http:
            if _refresh_usable(doc or {}, now):
                try:
                    result, how = await _refresh(http, doc["refresh_token"]), "refresh"
                except FyersAuthError as e:
                    errors.append(str(e))
            if result is None:
                gaps = missing_settings(for_totp=True)
                if gaps:
                    errors.append(f"cannot log in from scratch, missing: {', '.join(gaps)}")
                else:
                    try:
                        result, how = await _totp_login(http), "totp"
                    except FyersAuthError as e:
                        errors.append(str(e))
        if result is None:
            message = " | ".join(errors)[:400]
            limited = "HTTP 429" in message or "Too many requests" in message
            _last_failure.update(at=time.monotonic(), message=message, wait=RATE_LIMIT_COOLDOWN if limited else LOGIN_COOLDOWN)
            raise FyersAuthError(" | ".join(errors))

        _last_failure.update(at=0.0, message="", wait=LOGIN_COOLDOWN)
        saved = {"id": "current", "access_token": result["access_token"], "refresh_token": result["refresh_token"],
                 "access_expires_at": next_expiry(now).isoformat(), "refreshed_at": now.isoformat(), "method": how,
                 "refresh_obtained_at": now.isoformat() if result["new_refresh_token"] else (doc or {}).get("refresh_obtained_at", now.isoformat())}
        await db[TOKEN_COLLECTION].update_one({"id": "current"}, {"$set": saved}, upsert=True)
        logger.info("FYERS token renewed via %s; valid until %s", how, saved["access_expires_at"])
        return result["access_token"]


async def auth_header(db) -> dict:
    return {"Authorization": f"{_env('FYERS_APP_ID')}:{await get_access_token(db)}"}


async def status(db) -> dict:
    """Admin view: no token values, only timing and settings presence."""
    doc = await db[TOKEN_COLLECTION].find_one({"id": "current"}, {"_id": 0, "access_token": 0, "refresh_token": 0}) or {}
    now = datetime.now(IST)
    return {"enabled": enabled(), "missing_settings": missing_settings(for_totp=True),
            "token_valid": _valid({**doc, "access_token": "x"} if doc else {}, now),
            "valid_until": doc.get("access_expires_at"), "last_renewed": doc.get("refreshed_at"), "method": doc.get("method"),
            "refresh_token_usable": _refresh_usable({**doc, "refresh_token": "x"} if doc else {}, now),
            "login_cooldown_message": _last_failure["message"] or None}
