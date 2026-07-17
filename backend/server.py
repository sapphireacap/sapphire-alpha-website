from fastapi import FastAPI, APIRouter, HTTPException
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
import os
import logging
import asyncio
import httpx
from pathlib import Path
from pydantic import BaseModel, Field, EmailStr, ConfigDict
from typing import List, Optional
import uuid
from datetime import datetime, timezone


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
