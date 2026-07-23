from fastapi import FastAPI, APIRouter, HTTPException, Depends, Request, Response
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
import os
import logging
import asyncio
import hashlib
import secrets
import httpx
import bcrypt
import jwt
import zxcvbn
from definedge_service import DefinedgeService, DefinedgeError
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

# Email (Emergent managed Resend) — base URL is a constant, never from env.
EMAIL_BASE_URL = "https://integrations.emergentagent.com"
EMAIL_KEY = os.environ.get("EMERGENT_EMAIL_KEY")
EMAIL_FROM_NAME = os.environ.get("EMAIL_FROM_NAME", "Sapphire Alpha Capital")
NOTIFY_EMAIL = os.environ.get("NOTIFY_EMAIL", "contact@sapphirealphacapital.com")

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
    {"key": "positional", "label": "Positional Opportunities", "active": False},
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
    if not EMAIL_KEY:
        logger.warning("EMERGENT_EMAIL_KEY not set — skipping email send.")
        return
    payload = {
        "to": [recipient],
        "subject": subject,
        "html": html,
        "from_name": EMAIL_FROM_NAME,
    }
    if reply_to:
        payload["contact_email"] = reply_to
    try:
        async with httpx.AsyncClient(timeout=30) as http_client:
            resp = await http_client.post(
                f"{EMAIL_BASE_URL}/api/v1/email/send",
                headers={"X-Email-Key": EMAIL_KEY},
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


@api_router.get("/waitlist/count")
async def waitlist_count():
    count = await db.waitlist.count_documents({})
    return {"count": count}


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
    return {"email": user["email"], "name": user.get("name", "Admin"), "role": user.get("role", "trader")}


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
# Alpha Terminal
# ---------------------------------------------------------------------------
class StockCreate(BaseModel):
    scanner: str = "momentum"
    ticker: str
    company: str = ""
    momentum_score: str = ""
    volume: str = ""
    bias: str = "Neutral"


class Stock(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    scanner: str = "momentum"
    ticker: str
    company: str = ""
    momentum_score: str = ""
    volume: str = ""
    bias: str = "Neutral"
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


# ---------------------------------------------------------------------------
# Straddle Compass — Nifty directional bias indicator
# ---------------------------------------------------------------------------
class SignalUpdate(BaseModel):
    bias: str = "Neutral"          # Bullish | Bearish | Neutral
    spot: str = ""                 # e.g. "24,000"
    atm: str = ""                  # e.g. "24000"
    up_strike: str = ""            # ATM + 200
    up_trend: str = "Neutral"      # Bullish (rising) | Bearish (falling) | Neutral
    down_strike: str = ""          # ATM - 200
    down_trend: str = "Neutral"
    note: str = ""
    source: str = "manual"         # manual | definedge


DEFAULT_SIGNAL = {
    "id": "current",
    "bias": "Neutral",
    "spot": "",
    "atm": "",
    "up_strike": "",
    "up_trend": "Neutral",
    "down_strike": "",
    "down_trend": "Neutral",
    "note": "Awaiting live straddle data.",
    "source": "manual",
    "box_size": "0.5%",
    "reversal": "3 box",
    "updated_at": datetime.now(timezone.utc).isoformat(),
    "updated_label": "Today, 09:30 AM IST",
}


def _derive_bias(up_trend: str, down_trend: str) -> str:
    # Per strategy: falling straddle marks the direction Nifty is heading.
    if up_trend == "Bearish" and down_trend == "Bullish":
        return "Bullish"
    if up_trend == "Bullish" and down_trend == "Bearish":
        return "Bearish"
    return "Neutral"


@api_router.get("/terminal/signal")
async def get_signal():
    doc = await db.nifty_signal.find_one({"id": "current"}, {"_id": 0})
    return doc or DEFAULT_SIGNAL


@api_router.get("/terminal/spot")
async def get_live_spot():
    """Public, fast-pollable ticker value — falls back to a null spot on any
    upstream hiccup (not connected, outside hours, rate limited) rather than
    surfacing an error to site visitors; the frontend just keeps showing the
    last known signal.spot in that case."""
    try:
        return await definedge.spot_quote()
    except DefinedgeError:
        return {"spot": None}


@api_router.put("/terminal/signal")
async def update_signal(payload: SignalUpdate, admin: dict = Depends(get_current_admin)):
    data = payload.model_dump()
    # If admin leaves bias on Neutral but legs imply a direction, derive it.
    if data["bias"] == "Neutral":
        data["bias"] = _derive_bias(data["up_trend"], data["down_trend"])
    data.update({
        "id": "current",
        "box_size": "0.5%",
        "reversal": "3 box",
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "updated_label": "Today, 09:30 AM IST",
    })
    await db.nifty_signal.update_one({"id": "current"}, {"$set": data}, upsert=True)
    return data


# ---------------------------------------------------------------------------
# Definedge live automation (admin) — Sapphire Nifty Vector
# ---------------------------------------------------------------------------
class OtpVerify(BaseModel):
    otp: str
    otp_token: Optional[str] = None


@api_router.get("/admin/definedge/status")
async def definedge_status(admin: dict = Depends(get_current_admin)):
    return await definedge.status()


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
async def definedge_refresh(admin: dict = Depends(get_current_admin)):
    try:
        return await definedge.compute_vector()
    except DefinedgeError as e:
        raise HTTPException(status_code=400, detail=str(e))


@api_router.post("/admin/definedge/auto-refresh")
async def definedge_auto_refresh(request: Request):
    """Called by the external (GitHub Actions) cron on a schedule during NSE
    hours. Authenticated with a static shared secret rather than an admin
    login, since this is a machine caller, not the interactive admin."""
    if not CRON_SECRET or request.headers.get("X-Cron-Key") != CRON_SECRET:
        raise HTTPException(status_code=401, detail="Invalid cron key")

    now = datetime.now(IST)
    if not _is_market_open(now):
        return {"skipped": "outside market hours"}
    if not definedge.configured():
        return {"skipped": "not configured"}
    status = await definedge.status()
    if not status.get("connected"):
        return {"skipped": "not connected"}

    try:
        return await definedge.compute_vector()
    except DefinedgeError as e:
        raise HTTPException(status_code=400, detail=str(e))


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

    # Seed default Nifty signal once
    if await db.nifty_signal.find_one({"id": "current"}) is None:
        await db.nifty_signal.insert_one(dict(DEFAULT_SIGNAL))
        logger.info("Seeded default nifty signal.")

    try:
        await db.users.create_index("email", unique=True)
        await db.terminal_stocks.create_index([("scanner", 1), ("order", 1)])
        await db.refresh_tokens.create_index("token_hash", unique=True)
        await db.refresh_tokens.create_index("family_id")
        await db.audit_log.create_index([("user_id", 1), ("timestamp", -1)])
        await db.audit_log.create_index("event_type")
    except Exception as e:  # noqa: BLE001
        logger.warning(f"Index creation: {e}")


app.include_router(api_router)

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
