from fastapi import FastAPI, APIRouter, HTTPException, Depends, Request
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
import os
import logging
import asyncio
import httpx
import bcrypt
import jwt
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
# Auth (single admin, JWT Bearer)
# ---------------------------------------------------------------------------
def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except Exception:
        return False


def create_access_token(user_id: str, email: str) -> str:
    payload = {
        "sub": user_id,
        "email": email,
        "role": "admin",
        "type": "access",
        "exp": datetime.now(timezone.utc) + timedelta(hours=12),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


async def get_current_admin(request: Request) -> dict:
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
    if not user or user.get("role") != "admin":
        raise HTTPException(status_code=401, detail="Not authorized")
    return user


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


@api_router.post("/auth/login")
async def login(payload: LoginRequest, request: Request):
    email = payload.email.lower()
    ip = request.client.host if request.client else "unknown"
    identifier = f"{ip}:{email}"
    now = datetime.now(timezone.utc)

    attempt = await db.login_attempts.find_one({"identifier": identifier})
    if attempt and attempt.get("locked_until"):
        locked_until = datetime.fromisoformat(attempt["locked_until"])
        if locked_until > now:
            raise HTTPException(status_code=429, detail="Too many attempts. Try again in a few minutes.")

    user = await db.users.find_one({"email": email})
    if not user or not verify_password(payload.password, user["password_hash"]):
        count = (attempt.get("count", 0) if attempt else 0) + 1
        update = {"count": count}
        if count >= 5:
            update["locked_until"] = (now + timedelta(minutes=15)).isoformat()
        await db.login_attempts.update_one({"identifier": identifier}, {"$set": update}, upsert=True)
        raise HTTPException(status_code=401, detail="Invalid email or password.")

    await db.login_attempts.delete_one({"identifier": identifier})
    token = create_access_token(str(user.get("id", email)), email)
    return {"access_token": token, "token_type": "bearer", "user": {"email": email, "name": user.get("name", "Admin")}}


@api_router.get("/auth/me")
async def auth_me(admin: dict = Depends(get_current_admin)):
    return {"email": admin["email"], "name": admin.get("name", "Admin")}


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
            "created_at": datetime.now(timezone.utc).isoformat(),
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

    try:
        await db.users.create_index("email", unique=True)
        await db.terminal_stocks.create_index([("scanner", 1), ("order", 1)])
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
