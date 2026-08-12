from fastapi import FastAPI, APIRouter, BackgroundTasks, HTTPException, Depends, Request, Response
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
import os
import logging
import asyncio
import bisect
import hashlib
import hmac
import secrets
import time
import httpx
import bcrypt
import jwt
import zxcvbn

# ---------------------------------------------------------------------------
# Temporary cost-control measure (2026-07-29): the Render free-tier instance
# (512 MB) has been crash-restarting from hitting its memory limit multiple
# times a day, unrelated to any one feature (confirmed: crashes happened on
# commits both before and after that day's feature work). Rather than
# upgrade the plan, the least-essential features are paused here -- their
# IMPORTS are skipped entirely (not just their routes hidden), so heavy
# optional dependencies (matplotlib for Prism Alpha's backtest PNGs,
# quant_lab's Nifty500-wide Sharpe/EWMA computations, stock_terminal's
# scraping/agent stack) never load into the process at all. This is the
# only way a "pause" actually reduces steady-state memory -- hiding a route
# while still importing its module saves nothing.
# NOTHING IS DELETED. Every paused module's code and data are untouched;
# set DISABLED_FEATURES="" (or remove the env var and change the default
# below back to "") to fully restore everything with no other changes.
# Kept running: Index Vector, Exitline, Momentum Leaders (core `api_router`
# routes + swing-picks/relative-strength/breakout share the same generic
# `/terminal/stocks` endpoint so aren't separately gate-able here -- their
# own cron refreshes are paused instead, see the .github/workflows/ files),
# IPO/GMP, the new Convexity Window / Gamma Backspread options strategies.
# Quant Lab RE-ENABLED 2026-08-07 per explicit instruction ("yes live it") --
# Momentum Dashboard (module 09) is now live; Sharpe Dashboard/EWMA Scanner's
# backend routes come back too since they share this one router, but their
# own modules.js `live` flag stays false so they still show as paused on the
# public site -- only their admin-panel refresh buttons are now functional.
# Paused: Journal (+ its analytics router), Stock Terminal / Research (Aurora/Facet View).
# `blackbox_legacy` (Prism Alpha, Prism Alpha II, Lumen SIP module/router)
# RE-ENABLED 2026-08-04 per explicit instruction ("prism alpha 2 on") --
# only Prism Alpha 2 actually evaluates live though, see
# blackbox_prism_alpha.py's ACTIVE_LIVE_VARIANTS; Prism Alpha (variant 1)
# and Lumen SIP stay dormant (their own cron triggers are separately
# commented out in .github/workflows/), but the module import itself (and
# its matplotlib dependency) is back, so the original Render free-tier
# memory-crash risk this pause existed for is back too -- re-add
# "blackbox_legacy" here if crash-restarts resume.
DISABLED_FEATURES = set(
    f.strip() for f in os.environ.get(
        "DISABLED_FEATURES", "journal"
    ).split(",") if f.strip()
)

from definedge_service import DefinedgeService, DefinedgeError, derive_bias, derive_bias_4, INDEX_CONFIG
import definedge_otp_email
if "journal" not in DISABLED_FEATURES:
    from journal_routes import create_journal_router
    from journal_analytics import create_analytics_router
if "quant_lab" not in DISABLED_FEATURES:
    from quant_lab import create_quant_lab_router
from ipo_routes import create_ipo_router
if "blackbox_legacy" not in DISABLED_FEATURES:
    from blackbox_routes import create_blackbox_router
from blackbox_options_routes import create_blackbox_options_router
from exitline_routes import create_exitline_router
from pnf_routes import create_pnf_router
from renko_routes import create_renko_router
from relative_strength_routes import create_relative_strength_router
from breadth_routes import create_breadth_router
from intraday_breadth_routes import create_intraday_breadth_router
from n50_quotes_routes import create_n50_quotes_router
from oi_buildup_routes import create_oi_buildup_router
from multi_asset_returns_routes import create_multi_asset_returns_router
from options_trend_routes import create_options_trend_router
from market_dashboard_routes import create_market_dashboard_router
if "stock_terminal" not in DISABLED_FEATURES:
    from stock_terminal_routes import create_stock_terminal_router
    from lattice_routes import create_lattice_router
    from peter_tingle_routes import create_peter_tingle_router
from us_markets_routes import create_us_markets_router
from swing_picks_lcp import update_swing_picks_lcp
from momentum_track_record import (
    capture_entries as capture_track_record_entries,
    evaluate_pending as evaluate_track_record,
    reevaluate_all as reevaluate_track_record,
    get_track_record_summary,
)
from journal_models import DEFAULT_SETUP_TAGS, DEFAULT_EMOTION_TAGS
from pathlib import Path
from pydantic import BaseModel, Field, EmailStr, ConfigDict
from typing import List, Optional
import uuid
from datetime import datetime, timezone, timedelta


ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

# MongoDB connection
mongo_url = os.environ['MONGO_URL']
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ['DB_NAME']]

# Email (Resend, called directly) — base URL is a constant, never from env.
RESEND_BASE_URL = "https://api.resend.com"
RESEND_API_KEY = os.environ.get("RESEND_API_KEY")
EMAIL_FROM_NAME = os.environ.get("EMAIL_FROM_NAME", "Sapphire Alpha Capital")
EMAIL_FROM_ADDRESS = "no-reply@sapphirealpha.com"
NOTIFY_EMAIL = os.environ.get("NOTIFY_EMAIL", "sapphirealphacapital@gmail.com")

# Auth config
JWT_SECRET = os.environ.get("JWT_SECRET", "dev-secret-change-me")
JWT_ALGORITHM = "HS256"
ACCESS_TOKEN_TTL_MINUTES = 15
REFRESH_TOKEN_TTL_DAYS = 30
REFRESH_COOKIE_NAME = "refresh_token"
FRONTEND_BASE_URL = os.environ.get("FRONTEND_BASE_URL", "https://www.sapphirealphacapital.com")

# Shared secret for the external (GitHub Actions) Definedge auto-refresh cron —
# independent of admin login so the interactive admin credential never has to
# live in CI.
CRON_SECRET = os.environ.get("CRON_SECRET")

# P&F Studio checkout (Razorpay Orders — one-time payment per billing cycle,
# not a recurring Subscription: the Razorpay account's Subscriptions product
# isn't activated, and Orders needs zero extra setup. See
# get_current_pnf_subscriber / /pnf-access/* below.
RAZORPAY_KEY_ID = os.environ.get("RAZORPAY_KEY_ID")
RAZORPAY_KEY_SECRET = os.environ.get("RAZORPAY_KEY_SECRET")
# USD cents, mirrors Pricing.jsx's P&F Studio plan and PnfStudio.jsx's cycle
# cards -- keep all three in sync manually if the price ever changes. Live
# mode will additionally require Razorpay's international payments to be
# enabled on the account (test mode accepts USD with no extra setup).
PNF_CYCLE_AMOUNTS_USD_CENTS = {"monthly": 4900, "quarterly": 12900, "yearly": 44400}
PNF_CYCLE_MONTHS = {"monthly": 1, "quarterly": 3, "yearly": 12}

IST = timezone(timedelta(hours=5, minutes=30))

# NSE full-day trading holidays (equity/derivatives segment). Mirrors
# NSE_HOLIDAYS in frontend/src/pages/AlphaTerminal.jsx — no shared config
# layer between the two languages, so both need a fresh entry set added each
# calendar year.
NSE_HOLIDAYS = {
    # 2026
    "2026-01-26", "2026-03-03", "2026-03-26", "2026-03-31", "2026-04-03",
    "2026-04-14", "2026-05-01", "2026-05-28", "2026-06-26", "2026-09-14",
    "2026-10-02", "2026-10-20", "2026-11-10", "2026-11-24", "2026-12-25",
}


def _is_market_open(now_ist: datetime) -> bool:
    if now_ist.weekday() >= 5:
        return False
    if now_ist.strftime("%Y-%m-%d") in NSE_HOLIDAYS:
        return False
    return (9, 15) <= (now_ist.hour, now_ist.minute) <= (15, 30)
ADMIN_EMAIL = os.environ.get("ADMIN_EMAIL", "admin@example.com").lower()
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "admin123")

# Alpha Terminal scanners. 'active' is the default; a scanner is shown as a
# table on the public page whenever it has rows OR is flagged active — new
# scanners activate simply by adding data via the admin panel.
SCANNERS = [
    {"key": "momentum", "label": "Momentum Leaders", "active": True},
    {"key": "relative_strength", "label": "Relative Strength Leaders", "active": False},
    {"key": "breakout", "label": "Breakout Candidates", "active": False},
    {"key": "swing_picks", "label": "Swing Picks", "active": False},
]
SCANNER_KEYS = [s["key"] for s in SCANNERS]

# Definedge (Sapphire Nifty Vector)
definedge = DefinedgeService(
    db,
    os.environ.get("DEFINEDGE_API_TOKEN", ""),
    os.environ.get("DEFINEDGE_API_SECRET", ""),
)

app = FastAPI()
api_router = APIRouter(prefix="/api")

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------
class WaitlistCreate(BaseModel):
    email: EmailStr
    name: Optional[str] = None


class Waitlist(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    email: EmailStr
    name: Optional[str] = None
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class ContactCreate(BaseModel):
    name: str
    email: EmailStr
    message: str
    company: Optional[str] = None


class Contact(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str
    email: EmailStr
    message: str
    company: Optional[str] = None
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


# ---------------------------------------------------------------------------
# Email helper
# ---------------------------------------------------------------------------
async def send_email(recipient: str, subject: str, html: str, reply_to: Optional[str] = None):
    if not RESEND_API_KEY:
        logger.warning("RESEND_API_KEY not set — skipping email send.")
        return
    payload = {
        "from": f"{EMAIL_FROM_NAME} <{EMAIL_FROM_ADDRESS}>",
        "to": [recipient],
        "subject": subject,
        "html": html,
    }
    if reply_to:
        payload["reply_to"] = reply_to
    try:
        async with httpx.AsyncClient(timeout=30) as http_client:
            resp = await http_client.post(
                f"{RESEND_BASE_URL}/emails",
                headers={"Authorization": f"Bearer {RESEND_API_KEY}"},
                json=payload,
            )
        resp.raise_for_status()
    except Exception as e:  # noqa: BLE001 — email must never break the main flow
        logger.error(f"Email send error: {str(e)}")


def _wrap_email(title: str, body: str) -> str:
    return f"""
    <table width="100%" cellpadding="0" cellspacing="0" style="background:#030408;padding:32px 0;font-family:Arial,Helvetica,sans-serif;">
      <tr><td align="center">
        <table width="560" cellpadding="0" cellspacing="0" style="background:#0A0D18;border:1px solid rgba(255,255,255,0.08);border-radius:16px;overflow:hidden;">
          <tr><td style="padding:32px 40px;border-bottom:1px solid rgba(255,255,255,0.06);">
            <span style="color:#437EEB;font-size:13px;letter-spacing:3px;text-transform:uppercase;font-weight:bold;">Sapphire Alpha Capital</span>
          </td></tr>
          <tr><td style="padding:36px 40px;">
            <h1 style="color:#ffffff;font-size:22px;margin:0 0 18px;">{title}</h1>
            <div style="color:#94A3B8;font-size:15px;line-height:1.7;">{body}</div>
          </td></tr>
          <tr><td style="padding:24px 40px;border-top:1px solid rgba(255,255,255,0.06);color:#64748B;font-size:12px;">
            Built on Research. Driven by Alpha. &copy; 2026 Sapphire Alpha Capital.
          </td></tr>
        </table>
      </td></tr>
    </table>
    """


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
@api_router.get("/")
async def root():
    return {"message": "Sapphire Alpha Capital API"}


@api_router.post("/waitlist", response_model=Waitlist)
async def join_waitlist(payload: WaitlistCreate):
    existing = await db.waitlist.find_one({"email": payload.email}, {"_id": 0})
    if existing:
        raise HTTPException(status_code=409, detail="This email is already on the waitlist.")

    entry = Waitlist(email=payload.email, name=payload.name)
    await db.waitlist.insert_one(entry.model_dump())

    # Confirmation to subscriber + internal notification (non-blocking-ish)
    asyncio.create_task(send_email(
        recipient=payload.email,
        subject="You're on the list — Sapphire Alpha Capital",
        html=_wrap_email(
            "You're on the waitlist.",
            "Thank you for your interest in Sapphire Alpha Capital. You'll be among the first "
            "to gain early access when our quantitative research platform launches.<br/><br/>"
            "We build on research and let evidence lead."
        ),
    ))
    asyncio.create_task(send_email(
        recipient=NOTIFY_EMAIL,
        subject="New waitlist signup",
        html=_wrap_email("New waitlist signup", f"<strong>{payload.email}</strong> just joined the waitlist."),
    ))
    return entry


WAITLIST_COUNT_OFFSET = 158


@api_router.get("/waitlist/count")
async def waitlist_count():
    count = await db.waitlist.count_documents({})
    return {"count": count + WAITLIST_COUNT_OFFSET}


@api_router.post("/contact", response_model=Contact)
async def create_contact(payload: ContactCreate):
    entry = Contact(**payload.model_dump())
    await db.contacts.insert_one(entry.model_dump())

    asyncio.create_task(send_email(
        recipient=NOTIFY_EMAIL,
        subject=f"New enquiry from {payload.name}",
        html=_wrap_email(
            "New contact enquiry",
            f"<strong>Name:</strong> {payload.name}<br/>"
            f"<strong>Email:</strong> {payload.email}<br/>"
            f"<strong>Company:</strong> {payload.company or '—'}<br/><br/>"
            f"<strong>Message:</strong><br/>{payload.message}"
        ),
        reply_to=payload.email,
    ))
    asyncio.create_task(send_email(
        recipient=payload.email,
        subject="We received your message — Sapphire Alpha Capital",
        html=_wrap_email(
            "Thank you for reaching out.",
            f"Hi {payload.name},<br/><br/>We've received your message and will respond shortly. "
            "We appreciate your interest in Sapphire Alpha Capital."
        ),
    ))
    return entry


# ---------------------------------------------------------------------------
# Auth (multi-tenant: admin + trader roles, JWT access + rotating refresh)
# ---------------------------------------------------------------------------
def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except Exception:
        return False


def _check_password_strength(password: str, email: str = None):
    result = zxcvbn.zxcvbn(password, user_inputs=[email] if email else None)
    if result["score"] < 3:
        raise HTTPException(status_code=400, detail="Password is too weak. Try a longer, less predictable passphrase.")


def create_access_token(user_id: str, email: str, role: str) -> str:
    payload = {
        "sub": user_id,
        "email": email,
        "role": role,
        "type": "access",
        "exp": datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_TTL_MINUTES),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


async def get_current_user(request: Request) -> dict:
    auth_header = request.headers.get("Authorization", "")
    token = auth_header[7:] if auth_header.startswith("Bearer ") else None
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        if payload.get("type") != "access":
            raise HTTPException(status_code=401, detail="Invalid token type")
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Session expired. Please sign in again.")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")
    user = await db.users.find_one({"email": payload.get("email")}, {"_id": 0, "password_hash": 0})
    if not user:
        raise HTTPException(status_code=401, detail="Not authorized")
    return user


async def get_current_admin(request: Request) -> dict:
    user = await get_current_user(request)
    if user.get("role") != "admin":
        raise HTTPException(status_code=401, detail="Not authorized")
    return user


async def get_current_pnf_subscriber(request: Request) -> dict:
    """P&F Studio is paid-access: any authenticated user with an active
    pnf_access_until in the future, or an admin (admins are never gated
    behind their own paid tiers). Access is granted by an admin from
    /admin33 (manual, since no payment processor is wired up yet) and
    expires naturally once pnf_access_until passes -- no separate revoke
    path is needed for the common case of a subscription simply lapsing."""
    user = await get_current_user(request)
    if user.get("role") == "admin":
        return user
    until = user.get("pnf_access_until")
    if not until or datetime.fromisoformat(until) <= datetime.now(timezone.utc):
        raise HTTPException(status_code=402, detail="An active P&F Studio subscription is required.")
    return user


# ---- rate limiting (shared across login/signup/password-reset) -----------
async def _check_rate_limit(request: Request, email: str, scope: str) -> list:
    """Keys on IP+email (stops one attacker hammering one target) AND
    email-only (defense-in-depth against an attacker rotating source IPs
    against one target email). Returns the identifiers for the caller to
    pass to _record_rate_limit_failure/_clear_rate_limit."""
    ip = request.client.host if request.client else "unknown"
    now = datetime.now(timezone.utc)
    identifiers = [f"{scope}:{ip}:{email}", f"{scope}:email:{email}"]
    for identifier in identifiers:
        attempt = await db.rate_limits.find_one({"identifier": identifier})
        if attempt and attempt.get("locked_until"):
            locked_until = datetime.fromisoformat(attempt["locked_until"])
            if locked_until > now:
                raise HTTPException(status_code=429, detail="Too many attempts. Try again in a few minutes.")
    return identifiers


async def _record_rate_limit_failure(identifiers: list, max_attempts: int = 5, lock_minutes: int = 15):
    now = datetime.now(timezone.utc)
    for identifier in identifiers:
        attempt = await db.rate_limits.find_one({"identifier": identifier})
        count = (attempt.get("count", 0) if attempt else 0) + 1
        update = {"count": count}
        if count >= max_attempts:
            update["locked_until"] = (now + timedelta(minutes=lock_minutes)).isoformat()
        await db.rate_limits.update_one({"identifier": identifier}, {"$set": update}, upsert=True)


async def _clear_rate_limit(identifiers: list):
    for identifier in identifiers:
        await db.rate_limits.delete_one({"identifier": identifier})


# ---- audit log --------------------------------------------------------
async def log_audit_event(request: Request, user_id: Optional[str], event_type: str, **metadata):
    ip = request.client.host if request.client else "unknown"
    await db.audit_log.insert_one({
        "id": str(uuid.uuid4()),
        "user_id": user_id,
        "event_type": event_type,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "ip_address": ip,
        "user_agent": request.headers.get("user-agent", ""),
        "metadata": metadata,
    })


# ---- refresh tokens (rotation + reuse detection) -----------------------
def _hash_refresh_token(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


async def _issue_refresh_token(user_id: str, family_id: str = None, token_id: str = None) -> str:
    """Inserts a new refresh_tokens row and returns the raw (unhashed) token
    to hand to the client. Pass family_id when rotating an existing session
    (see /auth/refresh); omit to start a fresh session (login)."""
    raw = secrets.token_urlsafe(32)
    now = datetime.now(timezone.utc)
    await db.refresh_tokens.insert_one({
        "id": token_id or str(uuid.uuid4()),
        "user_id": user_id,
        "family_id": family_id or str(uuid.uuid4()),
        "token_hash": _hash_refresh_token(raw),
        "created_at": now.isoformat(),
        "expires_at": (now + timedelta(days=REFRESH_TOKEN_TTL_DAYS)).isoformat(),
        "revoked_at": None,
        "replaced_by": None,
    })
    return raw


def _set_refresh_cookie(response: Response, raw_token: str):
    response.set_cookie(
        key=REFRESH_COOKIE_NAME,
        value=raw_token,
        httponly=True,
        secure=True,
        samesite="none",  # frontend (Vercel) and backend (Render) are on different registrable domains
        max_age=REFRESH_TOKEN_TTL_DAYS * 24 * 3600,
        path="/api/auth",
    )


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


@api_router.post("/auth/login")
async def login(payload: LoginRequest, request: Request, response: Response):
    email = payload.email.lower()
    identifiers = await _check_rate_limit(request, email, scope="login")

    user = await db.users.find_one({"email": email})
    if not user or not verify_password(payload.password, user["password_hash"]):
        await _record_rate_limit_failure(identifiers)
        await log_audit_event(request, user.get("id") if user else None, "login_failed", email=email)
        raise HTTPException(status_code=401, detail="Invalid email or password.")

    await _clear_rate_limit(identifiers)
    user_id = str(user.get("id", email))
    now = datetime.now(timezone.utc)
    await db.users.update_one({"email": email}, {"$set": {"last_login_at": now.isoformat()}})

    role = user.get("role", "trader")
    access_token = create_access_token(user_id, email, role)
    raw_refresh = await _issue_refresh_token(user_id)
    _set_refresh_cookie(response, raw_refresh)

    await log_audit_event(request, user_id, "login_success")
    return {
        "access_token": access_token,
        "token_type": "bearer",
        "user": {"email": email, "name": user.get("name", "Admin"), "role": role},
    }


@api_router.post("/auth/refresh")
async def refresh_token_endpoint(request: Request, response: Response):
    raw = request.cookies.get(REFRESH_COOKIE_NAME)
    if not raw:
        raise HTTPException(status_code=401, detail="No refresh token.")
    token_hash = _hash_refresh_token(raw)
    now = datetime.now(timezone.utc)
    new_token_id = str(uuid.uuid4())

    # Atomic claim: only succeeds if this token hasn't already been rotated
    # or revoked. Doing this as a single find_one_and_update (rather than a
    # separate read-then-write) closes a race where two concurrent refreshes
    # with the same token could otherwise both succeed, silently defeating
    # reuse detection.
    record = await db.refresh_tokens.find_one_and_update(
        {"token_hash": token_hash, "revoked_at": None, "replaced_by": None},
        {"$set": {"replaced_by": new_token_id}},
    )

    if record is None:
        # Token unknown, already revoked, or already rotated. If it's a
        # known, already-rotated token being replayed, that's theft — kill
        # the whole session family.
        stolen = await db.refresh_tokens.find_one({"token_hash": token_hash})
        if stolen and stolen.get("replaced_by") and not stolen.get("revoked_at"):
            await db.refresh_tokens.update_many(
                {"family_id": stolen["family_id"], "revoked_at": None},
                {"$set": {"revoked_at": now.isoformat()}},
            )
            await log_audit_event(request, stolen["user_id"], "refresh_reuse_detected")
        response.delete_cookie(REFRESH_COOKIE_NAME, path="/api/auth")
        raise HTTPException(status_code=401, detail="Session invalid. Please sign in again.")

    if datetime.fromisoformat(record["expires_at"]) < now:
        response.delete_cookie(REFRESH_COOKIE_NAME, path="/api/auth")
        raise HTTPException(status_code=401, detail="Session expired. Please sign in again.")

    user = await db.users.find_one({"id": record["user_id"]}, {"_id": 0, "password_hash": 0})
    if not user:
        raise HTTPException(status_code=401, detail="Session invalid. Please sign in again.")

    new_raw = await _issue_refresh_token(record["user_id"], family_id=record["family_id"], token_id=new_token_id)
    _set_refresh_cookie(response, new_raw)

    role = user.get("role", "trader")
    access_token = create_access_token(record["user_id"], user["email"], role)
    return {"access_token": access_token, "token_type": "bearer", "user": {"email": user["email"], "name": user.get("name", "Admin"), "role": role}}


@api_router.post("/auth/logout")
async def logout(request: Request, response: Response):
    raw = request.cookies.get(REFRESH_COOKIE_NAME)
    if raw:
        record = await db.refresh_tokens.find_one({"token_hash": _hash_refresh_token(raw)})
        if record:
            await db.refresh_tokens.update_many(
                {"family_id": record["family_id"], "revoked_at": None},
                {"$set": {"revoked_at": datetime.now(timezone.utc).isoformat()}},
            )
            await log_audit_event(request, record["user_id"], "logout")
    response.delete_cookie(REFRESH_COOKIE_NAME, path="/api/auth")
    return {"status": "logged_out"}


@api_router.get("/auth/me")
async def auth_me(user: dict = Depends(get_current_user)):
    return {
        "email": user["email"],
        "name": user.get("name", "Admin"),
        "role": user.get("role", "trader"),
        "setup_tags": user.get("setup_tags", []),
        "emotion_tags": user.get("emotion_tags", []),
        "pnf_access_until": user.get("pnf_access_until"),
    }


class SignupRequest(BaseModel):
    email: EmailStr
    password: str
    name: str


@api_router.post("/auth/signup")
async def signup(payload: SignupRequest, request: Request):
    email = payload.email.lower()
    identifiers = await _check_rate_limit(request, email, scope="signup")

    if await db.users.find_one({"email": email}):
        await _record_rate_limit_failure(identifiers)
        raise HTTPException(status_code=409, detail="An account with this email already exists.")

    _check_password_strength(payload.password, email)

    now = datetime.now(timezone.utc)
    user_id = str(uuid.uuid4())
    await db.users.insert_one({
        "id": user_id,
        "email": email,
        "password_hash": hash_password(payload.password),
        "name": payload.name,
        "role": "trader",
        "email_verified": False,
        "created_at": now.isoformat(),
        "last_login_at": None,
        "last_password_reset_at": None,
        "setup_tags": list(DEFAULT_SETUP_TAGS),
        "emotion_tags": list(DEFAULT_EMOTION_TAGS),
    })
    await _clear_rate_limit(identifiers)

    verify_token = jwt.encode(
        {"sub": user_id, "email": email, "type": "email_verify", "exp": now + timedelta(hours=24)},
        JWT_SECRET, algorithm=JWT_ALGORITHM,
    )
    verify_url = f"{FRONTEND_BASE_URL}/verify-email?token={verify_token}"
    asyncio.create_task(send_email(
        recipient=email,
        subject="Verify your email — Sapphire Alpha Capital",
        html=_wrap_email(
            "Confirm your email address",
            f"Hi {payload.name},<br/><br/>Click the link below to verify your email and activate your account.<br/><br/>"
            f'<a href="{verify_url}" style="color:#437EEB;">Verify Email</a><br/><br/>This link expires in 24 hours.'
        ),
    ))
    await log_audit_event(request, user_id, "signup")
    return {"message": "Account created. Check your email to verify your address."}


@api_router.get("/auth/verify-email")
async def verify_email(token: str):
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        if payload.get("type") != "email_verify":
            raise HTTPException(status_code=400, detail="Invalid verification link.")
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=400, detail="This verification link has expired.")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=400, detail="Invalid verification link.")
    await db.users.update_one({"id": payload["sub"]}, {"$set": {"email_verified": True}})
    return {"message": "Email verified. You can now log in."}


class PasswordResetRequest(BaseModel):
    email: EmailStr


@api_router.post("/auth/request-password-reset")
async def request_password_reset(payload: PasswordResetRequest, request: Request):
    email = payload.email.lower()
    identifiers = await _check_rate_limit(request, email, scope="password_reset")
    user = await db.users.find_one({"email": email})
    if user:
        now = datetime.now(timezone.utc)
        reset_token = jwt.encode(
            {"sub": user["id"], "email": email, "type": "password_reset", "iat": now, "exp": now + timedelta(hours=1)},
            JWT_SECRET, algorithm=JWT_ALGORITHM,
        )
        reset_url = f"{FRONTEND_BASE_URL}/reset-password?token={reset_token}"
        asyncio.create_task(send_email(
            recipient=email,
            subject="Reset your password — Sapphire Alpha Capital",
            html=_wrap_email(
                "Reset your password",
                "Click the link below to choose a new password. This link expires in 1 hour and can only be used once.<br/><br/>"
                f'<a href="{reset_url}" style="color:#437EEB;">Reset Password</a>'
            ),
        ))
        await log_audit_event(request, user["id"], "password_reset_requested")
    await _record_rate_limit_failure(identifiers)
    # Always the same response, whether or not the account exists — avoids account enumeration.
    return {"message": "If an account exists for that email, a reset link has been sent."}


class PasswordResetConfirm(BaseModel):
    token: str
    new_password: str


@api_router.post("/auth/reset-password")
async def reset_password(payload: PasswordResetConfirm, request: Request):
    try:
        claims = jwt.decode(payload.token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        if claims.get("type") != "password_reset":
            raise HTTPException(status_code=400, detail="Invalid reset link.")
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=400, detail="This reset link has expired.")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=400, detail="Invalid reset link.")

    user = await db.users.find_one({"id": claims["sub"]})
    if not user:
        raise HTTPException(status_code=400, detail="Invalid reset link.")

    # Single-use enforcement without a separate token-store: reject if this
    # token was issued before the account's most recent successful reset,
    # i.e. it's already been used once.
    last_reset = user.get("last_password_reset_at")
    if last_reset:
        issued_at = datetime.fromtimestamp(claims["iat"], tz=timezone.utc)
        if issued_at <= datetime.fromisoformat(last_reset):
            raise HTTPException(status_code=400, detail="This reset link has already been used.")

    _check_password_strength(payload.new_password, user["email"])

    now = datetime.now(timezone.utc)
    await db.users.update_one(
        {"id": user["id"]},
        {"$set": {"password_hash": hash_password(payload.new_password), "last_password_reset_at": now.isoformat()}},
    )
    # A stolen refresh token shouldn't survive a password change.
    await db.refresh_tokens.update_many(
        {"user_id": user["id"], "revoked_at": None},
        {"$set": {"revoked_at": now.isoformat()}},
    )
    await log_audit_event(request, user["id"], "password_reset_completed")
    return {"message": "Password updated. Please sign in with your new password."}


# ---------------------------------------------------------------------------
# P&F Studio access (paid tier). Two ways in: self-serve Razorpay checkout
# below (/pnf-access/checkout + /verify -- one-time payment per billing
# cycle via Razorpay Orders, not a recurring Subscription, since the
# Razorpay account's Subscriptions product isn't activated), or an admin
# granting/extending access by hand (/admin/pnf-access/*) for cases outside
# self-serve (refunds, manual bank transfers, etc). See
# get_current_pnf_subscriber for how access is actually checked.
# ---------------------------------------------------------------------------
class PnfAccessGrant(BaseModel):
    email: EmailStr
    months: int  # 1 (monthly), 3 (quarterly), or 12 (yearly) — mirrors Pricing.jsx's cycles


class PnfAccessRevoke(BaseModel):
    email: EmailStr


@api_router.get("/admin/pnf-access")
async def lookup_pnf_access(email: EmailStr, admin: dict = Depends(get_current_admin)):
    user = await db.users.find_one({"email": email.lower()}, {"_id": 0, "email": 1, "name": 1, "pnf_access_until": 1})
    if not user:
        raise HTTPException(status_code=404, detail="No account with this email.")
    return user


@api_router.post("/admin/pnf-access/grant")
async def grant_pnf_access(payload: PnfAccessGrant, admin: dict = Depends(get_current_admin)):
    if payload.months not in (1, 3, 12):
        raise HTTPException(status_code=400, detail="months must be 1, 3, or 12.")
    email = payload.email.lower()
    user = await db.users.find_one({"email": email})
    if not user:
        raise HTTPException(status_code=404, detail="No account with this email.")
    # Extends from the existing expiry if still active, otherwise from now —
    # a renewal before lapse doesn't lose the remaining paid time.
    new_until = _extend_access_until(user.get("pnf_access_until"), payload.months)
    await db.users.update_one({"email": email}, {"$set": {"pnf_access_until": new_until}})
    return {"email": email, "pnf_access_until": new_until}


@api_router.post("/admin/pnf-access/revoke")
async def revoke_pnf_access(payload: PnfAccessRevoke, admin: dict = Depends(get_current_admin)):
    email = payload.email.lower()
    user = await db.users.find_one({"email": email})
    if not user:
        raise HTTPException(status_code=404, detail="No account with this email.")
    await db.users.update_one({"email": email}, {"$set": {"pnf_access_until": None}})
    return {"email": email, "pnf_access_until": None}


def _extend_access_until(current_until: Optional[str], months: int) -> str:
    now = datetime.now(timezone.utc)
    base = datetime.fromisoformat(current_until) if current_until and datetime.fromisoformat(current_until) > now else now
    return (base + timedelta(days=30 * months)).isoformat()


class PnfCheckoutRequest(BaseModel):
    cycle: str  # monthly | quarterly | yearly


@api_router.post("/pnf-access/checkout")
async def pnf_checkout(payload: PnfCheckoutRequest, user: dict = Depends(get_current_user)):
    if payload.cycle not in PNF_CYCLE_AMOUNTS_USD_CENTS:
        raise HTTPException(status_code=400, detail="cycle must be monthly, quarterly, or yearly.")
    if not RAZORPAY_KEY_ID or not RAZORPAY_KEY_SECRET:
        raise HTTPException(status_code=503, detail="Checkout is not configured yet.")

    amount = PNF_CYCLE_AMOUNTS_USD_CENTS[payload.cycle]
    receipt = f"pnf_{uuid.uuid4().hex[:24]}"  # Razorpay caps receipt at 40 chars
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(
            "https://api.razorpay.com/v1/orders",
            auth=(RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET),
            json={
                "amount": amount, "currency": "USD", "receipt": receipt,
                "notes": {"email": user["email"], "cycle": payload.cycle, "product": "pnf_studio"},
            },
        )
    if resp.status_code != 200:
        logger.warning("Razorpay order creation failed: %s %s", resp.status_code, resp.text)
        raise HTTPException(status_code=502, detail="Could not start checkout. Please try again shortly.")

    order = resp.json()
    await db.pnf_orders.insert_one({
        "order_id": order["id"],
        "email": user["email"],
        "cycle": payload.cycle,
        "amount": amount,
        "status": "created",
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    return {"order_id": order["id"], "amount": amount, "currency": "USD", "key_id": RAZORPAY_KEY_ID}


class PnfVerifyRequest(BaseModel):
    razorpay_order_id: str
    razorpay_payment_id: str
    razorpay_signature: str


@api_router.post("/pnf-access/verify")
async def pnf_verify(payload: PnfVerifyRequest, user: dict = Depends(get_current_user)):
    order = await db.pnf_orders.find_one({"order_id": payload.razorpay_order_id})
    if not order or order["email"] != user["email"]:
        raise HTTPException(status_code=404, detail="Order not found.")

    if order["status"] == "paid":
        # Already verified (e.g. a retried client callback) -- idempotent, no
        # second grant, just report the current expiry.
        fresh = await db.users.find_one({"email": user["email"]}, {"pnf_access_until": 1})
        return {"pnf_access_until": fresh.get("pnf_access_until")}

    expected_signature = hmac.new(
        RAZORPAY_KEY_SECRET.encode(),
        f"{payload.razorpay_order_id}|{payload.razorpay_payment_id}".encode(),
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(expected_signature, payload.razorpay_signature):
        raise HTTPException(status_code=400, detail="Payment verification failed.")

    now = datetime.now(timezone.utc)
    new_until = _extend_access_until(user.get("pnf_access_until"), PNF_CYCLE_MONTHS[order["cycle"]])
    await db.users.update_one({"email": user["email"]}, {"$set": {"pnf_access_until": new_until}})
    await db.pnf_orders.update_one(
        {"order_id": payload.razorpay_order_id},
        {"$set": {"status": "paid", "payment_id": payload.razorpay_payment_id, "paid_at": now.isoformat()}},
    )
    return {"pnf_access_until": new_until}


# ---------------------------------------------------------------------------
# Alpha Terminal
# ---------------------------------------------------------------------------
class StockCreate(BaseModel):
    scanner: str = "momentum"
    ticker: str
    company: str = ""
    momentum_score: str = ""
    volume: str = ""
    bias: str = "Neutral"
    lcp: str = ""      # last close price — Swing Picks
    buy_at: str = ""   # suggested buy-at level — Swing Picks


class Stock(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    scanner: str = "momentum"
    ticker: str
    company: str = ""
    momentum_score: str = ""
    volume: str = ""
    bias: str = "Neutral"
    lcp: str = ""
    buy_at: str = ""
    order: int = 0
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


def _validate_scanner(scanner: str):
    if scanner not in SCANNER_KEYS:
        raise HTTPException(status_code=400, detail="Unknown scanner")


@api_router.get("/terminal/scanners")
async def get_scanners():
    result = []
    for s in SCANNERS:
        count = await db.terminal_stocks.count_documents({"scanner": s["key"]})
        result.append({**s, "count": count, "has_data": count > 0})
    return {"scanners": result, "updated_label": "Today, 09:30 AM IST"}


@api_router.get("/terminal/stocks")
async def get_stocks(scanner: Optional[str] = None):
    query = {}
    if scanner:
        _validate_scanner(scanner)
        query["scanner"] = scanner
    rows = await db.terminal_stocks.find(query, {"_id": 0}).sort("order", 1).to_list(1000)
    return rows


@api_router.post("/terminal/stocks", response_model=Stock)
async def create_stock(payload: StockCreate, admin: dict = Depends(get_current_admin)):
    _validate_scanner(payload.scanner)
    last = await db.terminal_stocks.find({"scanner": payload.scanner}).sort("order", -1).to_list(1)
    next_order = (last[0]["order"] + 1) if last else 0
    stock = Stock(**payload.model_dump(), order=next_order)
    await db.terminal_stocks.insert_one(stock.model_dump())
    return stock


@api_router.put("/terminal/stocks/{stock_id}", response_model=Stock)
async def update_stock(stock_id: str, payload: StockCreate, admin: dict = Depends(get_current_admin)):
    _validate_scanner(payload.scanner)
    existing = await db.terminal_stocks.find_one({"id": stock_id}, {"_id": 0})
    if not existing:
        raise HTTPException(status_code=404, detail="Stock not found")
    updated = {**existing, **payload.model_dump()}
    await db.terminal_stocks.update_one({"id": stock_id}, {"$set": updated})
    return Stock(**updated)


@api_router.delete("/terminal/stocks/{stock_id}")
async def delete_stock(stock_id: str, admin: dict = Depends(get_current_admin)):
    res = await db.terminal_stocks.delete_one({"id": stock_id})
    if res.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Stock not found")
    return {"status": "deleted"}


class ReorderRequest(BaseModel):
    scanner: str
    ordered_ids: List[str]


@api_router.put("/terminal/stocks/reorder/apply")
async def reorder_stocks(payload: ReorderRequest, admin: dict = Depends(get_current_admin)):
    _validate_scanner(payload.scanner)
    for index, sid in enumerate(payload.ordered_ids):
        await db.terminal_stocks.update_one(
            {"id": sid, "scanner": payload.scanner}, {"$set": {"order": index}}
        )
    return {"status": "ok"}


class ScannerReplaceRequest(BaseModel):
    scanner: str = "momentum"
    stocks: List[StockCreate]


async def _fill_missing_company_names(stocks_data: list):
    """Best-effort: any row missing a `company` (e.g. Swing Picks' CSV,
    which has no company-name column at all) gets it looked up from
    Definedge's own master file — see DefinedgeService.company_name()."""
    if not definedge.configured() or not any(not s.get("company") for s in stocks_data):
        return
    master = await definedge._get_all_master()
    for s in stocks_data:
        if not s.get("company"):
            name = definedge.company_name(master, s["ticker"])
            if name:
                s["company"] = name


@api_router.post("/admin/terminal/scanner/replace")
async def replace_scanner_stocks(payload: ScannerReplaceRequest, admin: dict = Depends(get_current_admin)):
    """Atomic full replace of one scanner's rows — for automation (e.g. the
    daily momentum CSV sync) that recomputes a fresh top-N each run rather
    than diffing against what's already there. One request instead of a
    GET + several DELETEs + several POSTs, which is safer over a flaky
    connection: either this succeeds and the scanner is fully replaced, or
    it fails and nothing was touched."""
    _validate_scanner(payload.scanner)
    stocks_data = [s.model_dump() for s in payload.stocks]
    try:
        await _fill_missing_company_names(stocks_data)
    except Exception as e:  # noqa: BLE001 — best-effort, never block the actual scanner replace
        logger.warning("Company-name auto-fill failed for scanner=%s: %s", payload.scanner, e)

    await db.terminal_stocks.delete_many({"scanner": payload.scanner})
    docs = [
        Stock(**{**s, "scanner": payload.scanner}, order=i).model_dump()
        for i, s in enumerate(stocks_data)
    ]
    if docs:
        await db.terminal_stocks.insert_many(docs)
    try:
        await capture_track_record_entries(db, definedge, payload.scanner, docs)
    except Exception as e:  # noqa: BLE001 — never let track-record capture break the actual scanner replace
        logger.warning("Track record entry capture failed for scanner=%s: %s", payload.scanner, e)
    return {"status": "ok", "count": len(docs)}


# ---------------------------------------------------------------------------
# Scanner track record — how a scanner's Bullish/Bearish calls actually
# performed. Entry prices are captured automatically inside
# replace_scanner_stocks() above (best-effort, non-blocking); evaluation
# (fetching each call's day OHLC once its trading session has closed) is a
# separate step, same cron+admin-manual split as every other scheduled job
# in this codebase — see momentum_track_record.py for the actual logic.
# ---------------------------------------------------------------------------
@api_router.post("/admin/terminal/momentum-track-evaluate")
async def momentum_track_evaluate_cron(request: Request):
    """External-cron entry point — recommend once/day shortly after 15:30
    IST market close. X-Cron-Key gated like every other scheduled job here,
    not an admin login (machine caller)."""
    if not CRON_SECRET or request.headers.get("X-Cron-Key") != CRON_SECRET:
        raise HTTPException(status_code=401, detail="Invalid cron key")
    return await evaluate_track_record(db, definedge, scanner="momentum")


@api_router.post("/admin/terminal/momentum-track-evaluate-now")
async def momentum_track_evaluate_admin(admin: dict = Depends(get_current_admin)):
    """Same evaluation, for manual testing from the admin panel."""
    return await evaluate_track_record(db, definedge, scanner="momentum")


@api_router.post("/admin/terminal/momentum-track-reevaluate-all")
async def momentum_track_reevaluate_all_admin(admin: dict = Depends(get_current_admin)):
    """One-off migration trigger: re-scores every already-evaluated momentum
    record with the current post-entry-only high/low methodology (see
    reevaluate_all()'s docstring in momentum_track_record.py). Not meant to
    be called routinely — only after a change to the scoring logic."""
    return await reevaluate_track_record(db, definedge, scanner="momentum")


@api_router.get("/terminal/scanner-track-record")
async def scanner_track_record(scanner: str = "momentum"):
    _validate_scanner(scanner)
    return await get_track_record_summary(db, scanner)


# ---------------------------------------------------------------------------
# Swing Picks LCP refresh — once/day after 15:30 IST close, updates every
# swing_picks row's `lcp` from Definedge's real EOD close. Same cron+
# admin-manual split as momentum-track-evaluate above; see
# swing_picks_lcp.py for the actual logic. The pick list itself (ticker/
# company/buy_at) is refreshed separately, every 10 days, by the external
# swing_picks_sync.py script — this only ever touches `lcp`.
# ---------------------------------------------------------------------------
@api_router.post("/admin/terminal/swing-picks-update-lcp")
async def swing_picks_update_lcp_cron(request: Request):
    """External-cron entry point — recommend once/day shortly after 15:30
    IST market close. X-Cron-Key gated like every other scheduled job here,
    not an admin login (machine caller)."""
    if not CRON_SECRET or request.headers.get("X-Cron-Key") != CRON_SECRET:
        raise HTTPException(status_code=401, detail="Invalid cron key")
    return await update_swing_picks_lcp(db, definedge)


@api_router.post("/admin/terminal/swing-picks-update-lcp-now")
async def swing_picks_update_lcp_admin(admin: dict = Depends(get_current_admin)):
    """Same LCP refresh, for manual testing from the admin panel or a
    locally-triggered script authenticated via admin login."""
    return await update_swing_picks_lcp(db, definedge)


# ---------------------------------------------------------------------------
# Index Vector — multi-index directional bias indicator (formerly the
# NIFTY-only "Straddle Compass"; extended 2026-07-27 to also run BANKNIFTY,
# SENSEX, and BANKEX, then 2026-08-03 swapped SENSEX/BANKEX out for FINNIFTY
# — see definedge_service.py's INDEX_CONFIG/compute_vector for the actual
# computation. This section is just the storage/API layer:
# one doc per index in db.index_signal (id = f"current_{index}"), one
# append-only db.index_signal_history collection tagged with an `index`
# field. NIFTY is additionally write-mirrored into the legacy db.nifty_signal
# / db.nifty_signal_history collections by compute_vector() itself, so
# journal_routes.py's straddle_regime_at_entry auto-fill (which reads those
# two collection names directly) needed no changes.
# ---------------------------------------------------------------------------
VALID_INDICES = tuple(INDEX_CONFIG.keys())  # ("NIFTY", "BANKNIFTY", "FINNIFTY")


def _validate_index(index: str):
    if index not in VALID_INDICES:
        raise HTTPException(status_code=400, detail=f"Unknown index. Must be one of {VALID_INDICES}.")


class SignalUpdate(BaseModel):
    index: str = "NIFTY"
    bias: str = "Neutral"          # Bullish | Bearish | Neutral
    spot: str = ""                 # e.g. "24,000"
    atm: str = ""                  # e.g. "24000"
    up_strike: str = ""            # ATM + 200
    down_strike: str = ""          # ATM - 200
    weekly_expiry: str = ""        # chart_mode "4" indices (BANKNIFTY/FINNIFTY) leave this blank
    monthly_expiry: str = ""
    weekly_up_trend: str = "Neutral"      # Bullish (rising) | Bearish (falling) | Neutral — chart_mode "6" only
    weekly_down_trend: str = "Neutral"
    monthly_up_trend: str = "Neutral"
    monthly_down_trend: str = "Neutral"
    monthly_atm_ce_trend: str = "Neutral"  # monthly ATM CE, read individually (not a straddle)
    monthly_atm_pe_trend: str = "Neutral"  # monthly ATM PE, read individually
    note: str = ""
    source: str = "manual"         # manual | definedge


def _default_signal(index: str) -> dict:
    return {
        "id": f"current_{index}",
        "index": index,
        "bias": "Neutral",
        "spot": "",
        "atm": "",
        "up_strike": "",
        "down_strike": "",
        "weekly_expiry": "",
        "monthly_expiry": "",
        "weekly_up_trend": "Neutral",
        "weekly_down_trend": "Neutral",
        "monthly_up_trend": "Neutral",
        "monthly_down_trend": "Neutral",
        "monthly_atm_ce_trend": "Neutral",
        "monthly_atm_pe_trend": "Neutral",
        "note": "Awaiting live data.",
        "source": "manual",
        "box_size": "0.5%",
        "reversal": "3 box",
        "atm_leg_box_size": "3%",
        "atm_leg_reversal": "3 box",
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "updated_label": "Today, 09:30 AM IST",
    }


# Kept for the startup-seed / legacy-mirror call sites below.
DEFAULT_SIGNAL = _default_signal("NIFTY")


PUBLIC_SIGNAL_FIELDS = ("bias", "spot", "note", "updated_at", "updated_label")


def _public_flip_side(side: dict) -> dict:
    if not side:
        return {"reachable": False, "reason": "not yet available"}
    return {
        "reachable": side.get("reachable", False),
        "flip_level": side.get("flip_level"),
        "already_aligned": side.get("already_aligned", False),
        "reason": side.get("reason"),
    }


def _public_flip(flip: dict) -> Optional[dict]:
    """Public flip summary keeps only the two headline numbers (or the
    honest reason one isn't reachable) — the full doc's per-leg "legs"
    breakdown (which legs, their individual thresholds) stays admin-only,
    same proprietary-methodology line _public_signal already draws."""
    if not flip:
        return None
    return {"bullish": _public_flip_side(flip.get("bullish")), "bearish": _public_flip_side(flip.get("bearish"))}


def _public_signal(doc: dict) -> dict:
    """Strips an Index Vector doc down to what's safe to show site visitors.
    The full doc also carries strikes, expiries, per-leg trend/chart data, and
    P&F box parameters -- exactly the proprietary tracking methodology this is
    not supposed to reveal. Only the admin-authenticated endpoint below (and
    the admin panel that edits this doc) ever sees the rest."""
    public = {field: doc.get(field, DEFAULT_SIGNAL.get(field, "")) for field in PUBLIC_SIGNAL_FIELDS}
    public["flip"] = _public_flip(doc.get("flip"))
    return public


@api_router.get("/terminal/signal")
async def get_signal(index: str = "NIFTY"):
    _validate_index(index)
    doc = await db.index_signal.find_one({"id": f"current_{index}"}, {"_id": 0})
    return _public_signal(doc or _default_signal(index))


@api_router.get("/admin/terminal/signal")
async def get_signal_admin(index: str = "NIFTY", admin: dict = Depends(get_current_admin)):
    _validate_index(index)
    doc = await db.index_signal.find_one({"id": f"current_{index}"}, {"_id": 0})
    return doc or _default_signal(index)


@api_router.get("/terminal/spot")
async def get_live_spot(index: str = "NIFTY"):
    """Public, fast-pollable ticker value — falls back to a null spot on any
    upstream hiccup (not connected, outside hours, rate limited) rather than
    surfacing an error to site visitors; the frontend just keeps showing the
    last known signal.spot in that case."""
    _validate_index(index)
    try:
        return await definedge.spot_quote(index)
    except DefinedgeError:
        return {"spot": None}


# ---------------------------------------------------------------------------
# External quote proxy — SPX / XAUUSD have no CORS-accessible free public
# API (verified live, 2026-08-04: Yahoo Finance's chart endpoint has real
# data but sends no Access-Control-Allow-Origin header, so a direct browser
# call to it fails silently). Proxied server-side instead, with a short
# in-memory cache shared across every visitor so this never hammers Yahoo's
# unofficial endpoint once per client poll cycle. Crypto (Binance) needs no
# such proxy — Binance itself sends a wildcard CORS header and is called
# directly from the frontend.
# ---------------------------------------------------------------------------
EXTERNAL_QUOTE_SYMBOLS = {"SPX": "%5EGSPC", "GOLD": "GC=F"}  # GOLD is COMEX gold
# futures (GC=F), not true spot XAUUSD -- verified live: Yahoo's XAUUSD=X
# and XAU=X forex-style symbols both 404, GC=F is the closest real, freely-
# available USD gold price. Labeled "Gold" on the frontend, never "XAUUSD",
# so the instrument shown always matches what it actually is.
_external_quote_cache = {}  # symbol -> {"data": {...}, "fetched_at": float}
EXTERNAL_QUOTE_CACHE_TTL = 20  # seconds


@api_router.get("/terminal/external-spot")
async def get_external_spot(symbol: str):
    """SPX / XAUUSD spot via a server-side Yahoo Finance proxy (see module
    note above). Fails open (null spot), same convention as /terminal/spot
    — never surfaces an error to site visitors, and falls back to the last
    real cached value (rather than null) if a refresh attempt fails."""
    if symbol not in EXTERNAL_QUOTE_SYMBOLS:
        raise HTTPException(status_code=400, detail=f"Unknown symbol. Must be one of {list(EXTERNAL_QUOTE_SYMBOLS)}.")

    cached = _external_quote_cache.get(symbol)
    now = time.monotonic()
    if cached and (now - cached["fetched_at"]) < EXTERNAL_QUOTE_CACHE_TTL:
        return cached["data"]

    yahoo_symbol = EXTERNAL_QUOTE_SYMBOLS[symbol]
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{yahoo_symbol}"
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.get(url, params={"range": "1d", "interval": "5m"}, headers={
                # Yahoo's unofficial endpoint blocks curl/bare-client user
                # agents outright (verified live: 429 with the default UA,
                # 200 with a real browser UA) -- not spoofing identity, just
                # matching what any real browser already sends automatically.
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
            })
        r.raise_for_status()
        result = r.json()["chart"]["result"][0]
        meta = result["meta"]
        price = meta.get("regularMarketPrice")
        prev_close = meta.get("previousClose") or meta.get("chartPreviousClose")
        data = {"spot": None, "change": None, "change_pct": None}
        if price is not None and prev_close:
            change = price - prev_close
            change_pct = (change / prev_close) * 100
            data = {
                "spot": f"{price:,.2f}",
                "change": f"{'+' if change >= 0 else ''}{change:.2f}",
                "change_pct": f"{'+' if change_pct >= 0 else ''}{change_pct:.2f}",
            }
        _external_quote_cache[symbol] = {"data": data, "fetched_at": now}
        return data
    except Exception as e:  # noqa: BLE001 — best-effort external proxy, never break the homepage
        logger.warning("External quote proxy failed for %s: %s", symbol, e)
        if cached:
            return cached["data"]  # stale-but-real beats nothing
        return {"spot": None, "change": None, "change_pct": None}


@api_router.get("/admin/terminal/track-record")
async def get_track_record(index: str = "NIFTY", admin: dict = Depends(get_current_admin)):
    """Accuracy of one index's directional calls, evaluated at 15/30/60
    minute horizons after each Bullish/Bearish reading (Neutral isn't a call).
    Correct = spot moved in the predicted direction by the time the horizon
    elapses. The nearest history doc at/after T+H stands in for "spot at
    T+H" since data is only ~1/minute; if nothing exists near T+H (e.g. the
    horizon runs past market close, or into the next session) that reading
    is skipped, not scored either way.

    Admin-only for now (2026-07-28) — public site shows zero Index Vector
    historical performance until the user is satisfied enough to make it
    public again, same pattern as the Black Box redesign. No public route
    for this exists at all anymore, not just hidden in the frontend."""
    _validate_index(index)
    docs = await db.index_signal_history.find({"index": index}, {"_id": 0}).sort("updated_at", 1).limit(5000).to_list(length=5000)

    parsed = []
    for d in docs:
        try:
            spot = float(str(d.get("spot", "")).replace(",", ""))
            ts = datetime.fromisoformat(d["updated_at"])
        except (ValueError, TypeError, KeyError):
            continue
        parsed.append({"ts": ts, "spot": spot, "bias": d.get("bias")})

    if not parsed:
        return {"since": None, "trading_sessions": 0, "total_readings": 0, "low_data": True, "horizons": []}

    timestamps = [p["ts"] for p in parsed]
    horizon_minutes = [15, 30, 60]
    results = {h: {"evaluated": 0, "correct": 0} for h in horizon_minutes}

    for p in parsed:
        if p["bias"] not in ("Bullish", "Bearish"):
            continue
        for h in horizon_minutes:
            target = p["ts"] + timedelta(minutes=h)
            idx = bisect.bisect_left(timestamps, target)
            if idx >= len(parsed):
                continue  # horizon runs past the data we have
            future = parsed[idx]
            # Guard against matching a reading from the next trading session
            # when the horizon runs past today's close (overnight/weekend gap).
            if (future["ts"] - p["ts"]) > timedelta(minutes=h + 15):
                continue
            results[h]["evaluated"] += 1
            moved_up = future["spot"] > p["spot"]
            correct = (p["bias"] == "Bullish" and moved_up) or (p["bias"] == "Bearish" and not moved_up)
            if correct:
                results[h]["correct"] += 1

    since = parsed[0]["ts"].date().isoformat()
    trading_sessions = len({p["ts"].date() for p in parsed})
    max_evaluated = max((r["evaluated"] for r in results.values()), default=0)

    return {
        "since": since,
        "trading_sessions": trading_sessions,
        "total_readings": len(parsed),
        "low_data": max_evaluated < 100,
        "horizons": [
            {
                "minutes": h,
                "evaluated": results[h]["evaluated"],
                "correct": results[h]["correct"],
                "accuracy": (results[h]["correct"] / results[h]["evaluated"]) if results[h]["evaluated"] else 0,
            }
            for h in horizon_minutes
        ],
    }


@api_router.put("/terminal/signal")
async def update_signal(payload: SignalUpdate, admin: dict = Depends(get_current_admin)):
    _validate_index(payload.index)
    data = payload.model_dump()
    chart_mode = INDEX_CONFIG[payload.index]["chart_mode"]
    # If admin leaves bias on Neutral but the legs imply a direction, derive
    # it via the same confluence rule compute_vector() uses for this index's
    # chart_mode (6-leg for NIFTY, 4-leg for BANKNIFTY/FINNIFTY — see
    # INDEX_CONFIG).
    if data["bias"] == "Neutral":
        if chart_mode == "6":
            data["bias"] = derive_bias(
                data["weekly_up_trend"], data["weekly_down_trend"],
                data["monthly_up_trend"], data["monthly_down_trend"],
                data["monthly_atm_ce_trend"], data["monthly_atm_pe_trend"],
            )
        else:
            data["bias"] = derive_bias_4(
                data["monthly_up_trend"], data["monthly_down_trend"],
                data["monthly_atm_ce_trend"], data["monthly_atm_pe_trend"],
            )
    data.update({
        "id": f"current_{payload.index}",
        "box_size": "0.5%",
        "reversal": "3 box",
        "atm_leg_box_size": "3%",
        "atm_leg_reversal": "3 box",
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "updated_label": "Today, 09:30 AM IST",
    })
    await db.index_signal.update_one({"id": data["id"]}, {"$set": data}, upsert=True)
    if payload.index == "NIFTY":
        legacy = dict(data)
        legacy["id"] = "current"
        await db.nifty_signal.update_one({"id": "current"}, {"$set": legacy}, upsert=True)
    return data


# ---------------------------------------------------------------------------
# Definedge live automation (admin) — Sapphire Nifty Vector
# ---------------------------------------------------------------------------
class OtpVerify(BaseModel):
    otp: str
    otp_token: Optional[str] = None


@api_router.get("/admin/definedge/status")
async def definedge_status(admin: dict = Depends(get_current_admin)):
    """`connected` is the real health signal. `last_auto_login` carries the
    outcome of the most recent scheduled OTP login, which the cron itself
    can't report -- that route returns as soon as the work is queued (see
    _run_otp_auto_login) so it can outlive any external cron's timeout."""
    status = await definedge.status()
    status["last_auto_login"] = await db[OTP_AUTO_LOGIN_COLLECTION].find_one({"id": "last"}, {"_id": 0})
    return status


@api_router.post("/admin/definedge/otp-init")
async def definedge_otp_init(admin: dict = Depends(get_current_admin)):
    try:
        return await definedge.trigger_otp()
    except DefinedgeError as e:
        raise HTTPException(status_code=400, detail=str(e))


@api_router.post("/admin/definedge/otp-verify")
async def definedge_otp_verify(payload: OtpVerify, admin: dict = Depends(get_current_admin)):
    try:
        return await definedge.verify_otp(payload.otp, payload.otp_token)
    except DefinedgeError as e:
        raise HTTPException(status_code=400, detail=str(e))


@api_router.get("/admin/definedge/master-sample")
async def definedge_master_sample(admin: dict = Depends(get_current_admin)):
    try:
        return await definedge.master_sample()
    except DefinedgeError as e:
        raise HTTPException(status_code=400, detail=str(e))


@api_router.post("/admin/definedge/refresh")
async def definedge_refresh(index: str = "NIFTY", admin: dict = Depends(get_current_admin)):
    _validate_index(index)
    try:
        return await definedge.compute_vector(index)
    except DefinedgeError as e:
        raise HTTPException(status_code=400, detail=str(e))


@api_router.post("/admin/definedge/auto-refresh")
async def definedge_auto_refresh(request: Request):
    """Called by the external (cron-job.org) cron on a schedule during NSE
    hours. Authenticated with a static shared secret rather than an admin
    login, since this is a machine caller, not the interactive admin. Runs
    every Index Vector index CONCURRENTLY (not sequentially, despite the
    original "conservative about hammering Definedge" reasoning) -- the
    external cron pinging this route (cron-job.org's free tier) has a hard
    30s execution cap, confirmed live 2026-08-10: 3 indices sequentially
    took ~27-30s and intermittently timed out right at that ceiling.
    Concurrent (gather) cuts total wall time to roughly the slowest single
    index (~9-10s) instead of their sum, comfortably under any external
    cron's timeout, and 3 simultaneous Definedge calls is not the kind of
    burst that reasoning was actually guarding against. One index failing
    (e.g. a transient history-fetch error) doesn't block the others —
    each result is still reported individually."""
    if not CRON_SECRET or request.headers.get("X-Cron-Key") != CRON_SECRET:
        raise HTTPException(status_code=401, detail="Invalid cron key")

    now = datetime.now(IST)
    # Outside market hours there is genuinely nothing to do -- a plain 200,
    # so a weekend/evening tick isn't noise.
    if not _is_market_open(now):
        return {"skipped": "outside market hours"}

    # These two are NOT "nothing to do", they're "this should be working
    # and isn't" -- during market hours a missing session means the whole
    # module is serving stale data. Answered 503 so the external cron marks
    # the run failed and it's actually visible. This used to be a 200 whose
    # body the GitHub Actions workflow grepped for "skipped"; that check
    # went inert when the schedule moved to cron-job.org, which only looks
    # at the HTTP status (2026-08-11 -- a full day of stale Index Vector
    # data hid behind exactly this).
    if not definedge.configured():
        raise HTTPException(status_code=503, detail="Definedge not configured")
    status = await definedge.status()
    if not status.get("connected"):
        raise HTTPException(status_code=503, detail="No Definedge session -- the daily OTP login has not succeeded today")

    async def _refresh_one(idx):
        try:
            signal = await definedge.compute_vector(idx)
            return idx, {"bias": signal["bias"]}
        except DefinedgeError as e:
            return idx, {"error": str(e)}

    pairs = await asyncio.gather(*(_refresh_one(idx) for idx in VALID_INDICES))
    return dict(pairs)


OTP_AUTO_LOGIN_COLLECTION = "definedge_otp_auto_login"


async def _record_otp_auto_login(outcome: str, detail: str = None, started_at: datetime = None):
    """One doc (id="last") holding the most recent attempt's result. The
    route below returns before the work finishes, so this doc -- surfaced
    by GET /admin/definedge/status -- is the ONLY place a failure shows
    up. Without it a broken login would look identical to a working one
    from outside (the cron just sees its instant 200), which is the exact
    "silently green" trap that let a whole day of stale Index Vector data
    go unnoticed on 2026-08-11."""
    await db[OTP_AUTO_LOGIN_COLLECTION].update_one(
        {"id": "last"},
        {"$set": {
            "id": "last", "outcome": outcome, "detail": detail,
            "started_at": (started_at or datetime.now(timezone.utc)).isoformat(),
            "finished_at": datetime.now(timezone.utc).isoformat(),
        }},
        upsert=True,
    )


async def _run_otp_auto_login():
    """trigger -> read the OTP off the dedicated Gmail inbox
    (definedge_otp_email.py) -> verify. Runs as a BackgroundTask, NOT
    inline in the request, because it can legitimately take ~90s+: the
    mailbox is polled up to POLL_TIMEOUT_SECONDS waiting for Definedge's
    mail to actually land, on top of the trigger/verify round-trips and
    per-poll IMAP overhead. No external cron will hold a connection open
    that long -- cron-job.org's free tier caps execution at 30s and
    killed this every morning while it still blocked (confirmed live
    2026-08-12: status=TIMEOUT at exactly 30000ms, having fired
    perfectly on time at 09:00:12 IST). Returning immediately and doing
    the work here decouples "did the cron fire" from "how long the login
    takes", so the cap stops mattering at all."""
    # Captured BEFORE the trigger call, not after -- Definedge stamps the
    # email's own Date header at send time, which can land a few seconds
    # earlier than when our client finishes the round-trip and would
    # otherwise mark "after". Confirmed live: a post-trigger timestamp
    # wrongly filtered out the real OTP email as "too old" by a handful
    # of seconds. A SMALL buffer on top absorbs the rest of any clock
    # skew -- deliberately not generous (confirmed live: a 2-minute
    # buffer picked up a stale OTP from an earlier trigger still sitting
    # in the inbox, whose otp_token no longer matched THIS trigger's,
    # and Definedge correctly rejected the mismatched verify).
    started_at = datetime.now(timezone.utc)
    triggered_at = started_at - timedelta(seconds=15)

    try:
        trigger = await definedge.trigger_otp()
    except DefinedgeError as e:
        logger.error("OTP auto-login: trigger failed: %s", e)
        await _record_otp_auto_login("error", f"OTP trigger failed: {e}", started_at)
        return

    try:
        otp = await definedge_otp_email.fetch_otp(after=triggered_at)
    except definedge_otp_email.DefinedgeOtpEmailError as e:
        logger.error("OTP auto-login: could not read the OTP email: %s", e)
        await _record_otp_auto_login("error", f"Could not read the OTP email: {e}", started_at)
        return

    try:
        await definedge.verify_otp(otp, trigger.get("otp_token"))
    except DefinedgeError as e:
        logger.error("OTP auto-login: verify failed: %s", e)
        await _record_otp_auto_login("error", f"OTP verify failed: {e}", started_at)
        return

    logger.info("OTP auto-login: connected.")
    await _record_otp_auto_login("ok", None, started_at)


@api_router.post("/admin/definedge/otp-auto-login")
async def definedge_otp_auto_login(request: Request, background_tasks: BackgroundTasks):
    """External-cron entry point for the daily OTP login, so nobody has to
    open the admin panel and paste a code in by hand each morning. Returns
    as soon as the work is QUEUED (same fire-and-forget shape as
    market_dashboard_routes.py's /admin/refresh) -- see
    _run_otp_auto_login() for why it must not block the request. Same
    X-Cron-Key gate as every other scheduled job; the manual
    otp-init/otp-verify routes above still work unchanged as a fallback.

    A 200 here means "queued", NOT "logged in" -- the outcome lands in
    GET /admin/definedge/status's `last_auto_login`, and `connected` is
    still the real signal."""
    if not CRON_SECRET or request.headers.get("X-Cron-Key") != CRON_SECRET:
        raise HTTPException(status_code=401, detail="Invalid cron key")
    if not definedge.configured():
        return {"skipped": "Definedge not configured"}
    status = await definedge.status()
    if status.get("connected"):
        return {"skipped": "already connected today"}

    background_tasks.add_task(_run_otp_auto_login)
    return {"status": "started"}


# ---------------------------------------------------------------------------
# Startup: seed admin, momentum data, indexes
# ---------------------------------------------------------------------------
@app.on_event("startup")
async def on_startup():
    # Admin seeding (idempotent)
    existing = await db.users.find_one({"email": ADMIN_EMAIL})
    if existing is None:
        await db.users.insert_one({
            "id": str(uuid.uuid4()),
            "email": ADMIN_EMAIL,
            "password_hash": hash_password(ADMIN_PASSWORD),
            "name": "Admin",
            "role": "admin",
            "email_verified": True,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "last_login_at": None,
            "last_password_reset_at": None,
        })
        logger.info("Seeded admin user.")
    elif not verify_password(ADMIN_PASSWORD, existing["password_hash"]):
        await db.users.update_one(
            {"email": ADMIN_EMAIL}, {"$set": {"password_hash": hash_password(ADMIN_PASSWORD)}}
        )
        logger.info("Updated admin password hash.")

    # Seed Momentum Leaders once (won't overwrite admin edits)
    if await db.terminal_stocks.count_documents({"scanner": "momentum"}) == 0:
        seed = [
            {"ticker": "NVDA", "company": "NVIDIA Corp.", "momentum_score": "98.4", "volume": "3.2x avg", "bias": "Bullish"},
            {"ticker": "CRWD", "company": "CrowdStrike", "momentum_score": "94.2", "volume": "2.8x avg", "bias": "Bullish"},
            {"ticker": "PLTR", "company": "Palantir Technologies", "momentum_score": "91.7", "volume": "4.1x avg", "bias": "Bullish"},
        ]
        for i, row in enumerate(seed):
            stock = Stock(scanner="momentum", order=i, **row)
            await db.terminal_stocks.insert_one(stock.model_dump())
        logger.info("Seeded momentum leaders.")

    # Seed default Index Vector signal once, per index (idempotent)
    for _idx in VALID_INDICES:
        if await db.index_signal.find_one({"id": f"current_{_idx}"}) is None:
            await db.index_signal.insert_one(_default_signal(_idx))
    # Legacy mirror, only ever read by journal_routes.py's straddle_regime_at_entry
    if await db.nifty_signal.find_one({"id": "current"}) is None:
        await db.nifty_signal.insert_one(dict(DEFAULT_SIGNAL))
        logger.info("Seeded default index signal(s).")

    try:
        await db.users.create_index("email", unique=True)
        await db.pnf_orders.create_index("order_id", unique=True)
        await db.terminal_stocks.create_index([("scanner", 1), ("order", 1)])
        await db.refresh_tokens.create_index("token_hash", unique=True)
        await db.refresh_tokens.create_index("family_id")
        await db.audit_log.create_index([("user_id", 1), ("timestamp", -1)])
        await db.audit_log.create_index("event_type")

        await db.trades.create_index("user_id")
        await db.trades.create_index("entry_time")
        await db.trades.create_index("setup_tag")
        await db.trades.create_index("strategy_family")
        await db.trades.create_index([("user_id", 1), ("entry_time", -1)])
        await db.trades.create_index("status")
        await db.reviews.create_index([("user_id", 1), ("period_start", -1)])
        await db.reviews.create_index("period_type")
        await db.playbooks.create_index("user_id")
        await db.nifty_signal_history.create_index([("updated_at", -1)])
        await db.index_signal_history.create_index([("index", 1), ("updated_at", -1)])
        await db.scanner_track_record.create_index([("scanner", 1), ("date", -1)])
        await db.scanner_track_record.create_index([("scanner", 1), ("date", 1), ("ticker", 1)], unique=True)
        await db.quant_lab_ewma_cache.create_index(
            [("segment", 1), ("symbol", 1), ("fast_span", 1), ("slow_span", 1)], unique=True
        )
        await db.quant_lab_sharpe_cache.create_index("symbol", unique=True)
        await db.quant_lab_momentum_cache.create_index("symbol", unique=True)
        await db.ipos.create_index("id", unique=True)
        # partialFilterExpression, not sparse=True: every IPO doc stores
        # nse_symbol explicitly (None for manual entries), and a sparse index
        # only skips documents missing the field entirely, not ones with it
        # set to null — sparse still enforced uniqueness across all the
        # nulls and 500'd on the second manually-added IPO (caught live).
        await db.ipos.create_index(
            "nse_symbol", unique=True, partialFilterExpression={"nse_symbol": {"$type": "string"}}
        )
        await db.ipos.create_index("issue_open_date")
        # gmp_current used to be one doc per IPO (ipo_id unique); now it's one
        # doc per IPO per source, so the old single-field unique index has to
        # go or every second source's upsert 11000s against the first's doc.
        try:
            await db.gmp_current.drop_index("ipo_id_1")
        except Exception:  # noqa: BLE001 — already dropped / never existed on a fresh DB
            pass
        await db.gmp_current.create_index([("ipo_id", 1), ("source", 1)], unique=True)
        await db.gmp_history.create_index([("ipo_id", 1), ("source", 1)])
        await db.blackbox_prism_alpha_trades.create_index("date")
        await db.blackbox_prism_alpha_trades.create_index("status")
        await db.blackbox_prism_alpha2_trades.create_index("date")
        await db.blackbox_prism_alpha2_trades.create_index("status")
        await db.blackbox_prism_alpha_atm_state.create_index("date", unique=True)
        await db.blackbox_prism_alpha_backtest_trades.create_index("backtest_run_id")
        await db.blackbox_prism_alpha2_backtest_trades.create_index("backtest_run_id")
        await db.blackbox_backtest_runs.create_index("run_at")
        await db.blackbox_lumen_sip_signals.create_index([("instrument", 1), ("date", 1)])
        await db.blackbox_lumen_sip_portfolio.create_index("date", unique=True)
        await db.blackbox_lumen_sip_backtest_signals.create_index([("instrument", 1), ("date", 1)])
        await db.blackbox_lumen_sip_backtest_portfolio.create_index("date", unique=True)
        await db.blackbox_lumen_sip_backtest_metrics.create_index("id", unique=True)
        await db.exitline_levels.create_index([("date", 1), ("segment", 1), ("token", 1)], unique=True)
        await db.stock_symbol_master.create_index("symbol", unique=True)
        await db.stock_symbol_master.create_index("company_name")
        await db.stock_prices_daily.create_index([("symbol", 1), ("date", 1)], unique=True)
        await db.stock_fundamentals.create_index("symbol", unique=True)
        await db.stock_shareholding.create_index([("symbol", 1), ("quarter", 1)], unique=True)
        await db.stock_computed_metrics.create_index("symbol", unique=True)
        await db.stock_agent_cache.create_index("symbol", unique=True)
        await db.stock_agent_cache.create_index("expires_at", expireAfterSeconds=0)
        await db.blackbox_signals.create_index([("index", 1), ("strategy_id", 1), ("mode", 1), ("status", 1)])
        await db.blackbox_signals.create_index([("mode", 1), ("timestamp", -1)])
        await db.blackbox_daily_performance.create_index(
            [("date", 1), ("index", 1), ("strategy_id", 1), ("mode", 1)], unique=True
        )
        await db.blackbox_strategy_status.create_index([("index", 1), ("strategy_id", 1), ("mode", 1)], unique=True)
        await db.blackbox_iv_history.create_index([("index", 1), ("strategy_id", 1), ("date", 1)], unique=True)
        await db.blackbox_config.create_index("index", unique=True)
        await db.rs_daily_closes.create_index("symbol", unique=True)
        await db.breadth_daily_closes.create_index("symbol", unique=True)
        await db.options_trend_scan.create_index("symbol", unique=True)
        await db.market_dashboard_fii_dii_history.create_index("date", unique=True)
        await db.market_dashboard_ad_history.create_index("date")
        await db.lattice_positions.create_index([("symbol", 1), ("status", 1)])
        await db.lattice_positions.create_index("status")
        await db.lattice_decisions.create_index([("symbol", 1), ("run_at", -1)])
        await db.lattice_portfolio_state.create_index("id", unique=True)
    except Exception as e:  # noqa: BLE001
        logger.warning(f"Index creation: {e}")


ipo_router = create_ipo_router(db, get_current_admin, CRON_SECRET)
blackbox_options_router = create_blackbox_options_router(db, definedge, get_current_admin, CRON_SECRET)
exitline_router = create_exitline_router(db, definedge)
pnf_router = create_pnf_router(db, definedge, get_current_pnf_subscriber)
renko_router = create_renko_router(db, definedge, get_current_pnf_subscriber)
relative_strength_router = create_relative_strength_router(db, definedge)
breadth_router = create_breadth_router(db, definedge, get_current_admin, CRON_SECRET)
intraday_breadth_router = create_intraday_breadth_router(db, definedge, get_current_admin, CRON_SECRET)
n50_quotes_router = create_n50_quotes_router(db, definedge, get_current_admin, CRON_SECRET)
oi_buildup_router = create_oi_buildup_router(db, definedge, get_current_admin, CRON_SECRET)
multi_asset_returns_router = create_multi_asset_returns_router()
options_trend_router = create_options_trend_router(db, definedge, get_current_admin, CRON_SECRET)
market_dashboard_router = create_market_dashboard_router(db, get_current_admin, CRON_SECRET)

app.include_router(api_router)
app.include_router(ipo_router, prefix="/api")
app.include_router(blackbox_options_router, prefix="/api")
app.include_router(exitline_router, prefix="/api")
app.include_router(pnf_router, prefix="/api")
app.include_router(renko_router, prefix="/api")
app.include_router(relative_strength_router, prefix="/api")
app.include_router(breadth_router, prefix="/api")
app.include_router(intraday_breadth_router, prefix="/api")
app.include_router(n50_quotes_router, prefix="/api")
app.include_router(oi_buildup_router, prefix="/api")
app.include_router(multi_asset_returns_router, prefix="/api")
app.include_router(options_trend_router, prefix="/api")
app.include_router(market_dashboard_router, prefix="/api")

# Paused features (see DISABLED_FEATURES above) -- router creation/mounting
# skipped entirely, not just hidden, matching the skipped imports above.
if "journal" not in DISABLED_FEATURES:
    journal_router = create_journal_router(db, get_current_user, log_audit_event, definedge)
    analytics_router = create_analytics_router(db, get_current_user)
    app.include_router(journal_router, prefix="/api")
    app.include_router(analytics_router, prefix="/api")
if "quant_lab" not in DISABLED_FEATURES:
    quant_lab_router = create_quant_lab_router(db, definedge, get_current_admin, CRON_SECRET)
    app.include_router(quant_lab_router, prefix="/api")
if "blackbox_legacy" not in DISABLED_FEATURES:
    blackbox_router = create_blackbox_router(db, definedge, get_current_admin, CRON_SECRET)
    app.include_router(blackbox_router, prefix="/api")
if "stock_terminal" not in DISABLED_FEATURES:
    stock_terminal_router = create_stock_terminal_router(db, definedge, get_current_admin, CRON_SECRET)
    app.include_router(stock_terminal_router, prefix="/api")
    lattice_router = create_lattice_router(db, definedge, get_current_admin, CRON_SECRET)
    app.include_router(lattice_router, prefix="/api")
    peter_tingle_router = create_peter_tingle_router(db, get_current_admin, CRON_SECRET)
    app.include_router(peter_tingle_router, prefix="/api")
us_markets_router = create_us_markets_router(db, get_current_admin, CRON_SECRET)
app.include_router(us_markets_router, prefix="/api")

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=os.environ.get('CORS_ORIGINS', '*').split(','),
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("shutdown")
async def shutdown_db_client():
    client.close()
