"""
IPO Section — live tracker + AI-generated RHP short reports. Mounted (no
extra prefix beyond /api) by server.py via create_ipo_router(db,
get_current_admin, cron_secret) — same factory pattern as journal_routes.py/
quant_lab.py, avoids a circular import with server.py.

Data flow:
  - `POST /api/admin/ipos/nse-refresh` (cron-secret-gated, external scheduler)
    and `POST /api/admin/ipos/refresh-now` (admin-JWT-gated, "Refresh from
    NSE" button) both call the same _refresh_from_nse() — upserts company
    name / dates / price band / issue size from NSE's public (undocumented)
    IPO endpoints, keyed on nse_symbol. Never touches rhp_url/sector/
    lot_size/short_report on existing rows — those are admin-owned fields.
  - Admin adds/edits rhp_url (and sector/lot_size, which NSE's API doesn't
    expose) via POST/PUT /api/ipos. Saving a new-or-changed rhp_url schedules
    _generate_report() as a FastAPI BackgroundTask, so the save returns
    immediately rather than blocking on a ~15-30s PDF fetch + Claude call.
  - `status` is never admin input — it's computed from today vs. the three
    date fields on every read (_compute_status), so it can't go stale.
"""
import io
import logging
import os
import re
import uuid
from datetime import datetime, timezone, timedelta
from typing import List, Optional

import anthropic
import httpx
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from pypdf import PdfReader

logger = logging.getLogger(__name__)
IST = timezone(timedelta(hours=5, minutes=30))

BROWSER_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)
MAX_RHP_CHARS = 350_000  # generous cap so a pathological huge PDF can't blow up the request
MIN_EXTRACTED_CHARS = 500  # below this, treat as "couldn't extract" (e.g. scanned/image-only PDF)

NSE_UPCOMING_URL = "https://www.nseindia.com/api/all-upcoming-issues?category=ipo"
NSE_MONTHS = {m: i + 1 for i, m in enumerate(
    ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
)}

ANTHROPIC_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-6")
REPORT_SYSTEM_PROMPT = (
    "You are a neutral equity-research assistant summarizing an Indian IPO's Red "
    "Herring Prospectus (RHP) for retail investors. Write a short, plain-text report "
    "with exactly these five section headers, each in ALL CAPS on its own line, "
    "followed by 2-4 sentences of plain prose (no bullet points, no markdown, no bold):\n\n"
    "BUSINESS OVERVIEW\nFINANCIAL SNAPSHOT\nOBJECTS OF THE ISSUE\nKEY RISK FACTORS\nCLOSING NOTE\n\n"
    "The CLOSING NOTE must stay neutral and end with a reminder that this is not "
    "investment advice. Base every claim strictly on the provided RHP text — never "
    "invent numbers or facts that aren't in it."
)


class ReportGenerationError(Exception):
    pass


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------
class PriceBand(BaseModel):
    min: Optional[float] = None
    max: Optional[float] = None


class IpoRecord(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    company_name: str
    sector: Optional[str] = None
    issue_open_date: Optional[str] = None    # YYYY-MM-DD
    issue_close_date: Optional[str] = None
    listing_date: Optional[str] = None
    price_band: PriceBand = Field(default_factory=PriceBand)
    lot_size: Optional[int] = None
    issue_size: Optional[str] = None
    exchange: List[str] = Field(default_factory=lambda: ["NSE"])
    rhp_url: Optional[str] = None
    nse_symbol: Optional[str] = None         # NSE ticker — de-dup key for the auto-refresh job, admin-invisible
    short_report: Optional[str] = None
    report_generated_at: Optional[str] = None
    report_error: Optional[str] = None
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class IpoCreateRequest(BaseModel):
    company_name: str
    sector: Optional[str] = None
    issue_open_date: Optional[str] = None
    issue_close_date: Optional[str] = None
    listing_date: Optional[str] = None
    price_band: PriceBand = Field(default_factory=PriceBand)
    lot_size: Optional[int] = None
    issue_size: Optional[str] = None
    exchange: List[str] = Field(default_factory=lambda: ["NSE"])
    rhp_url: Optional[str] = None
    nse_symbol: Optional[str] = None


def _compute_status(ipo: dict) -> str:
    """upcoming / open / closed / listed, derived from today (IST) vs. the
    three date fields — never trusts a stored value, so it can't go stale."""
    today = datetime.now(IST).date().isoformat()
    open_d, close_d, listing_d = ipo.get("issue_open_date"), ipo.get("issue_close_date"), ipo.get("listing_date")
    if listing_d and today >= listing_d:
        return "listed"
    if close_d and today > close_d:
        return "closed"
    if open_d and today >= open_d:
        return "open"
    return "upcoming"


# ---------------------------------------------------------------------------
# RHP fetch + extract + summarize
# ---------------------------------------------------------------------------
async def _extract_rhp_text(rhp_url: str) -> str:
    async with httpx.AsyncClient(timeout=60, follow_redirects=True) as c:
        try:
            r = await c.get(rhp_url, headers={"User-Agent": BROWSER_USER_AGENT})
        except httpx.HTTPError as e:
            raise ReportGenerationError(f"Could not fetch the RHP PDF: {e}")
    if r.status_code != 200:
        raise ReportGenerationError(f"Could not fetch the RHP PDF (HTTP {r.status_code}).")

    content_type = r.headers.get("content-type", "").lower()
    if "pdf" not in content_type and not rhp_url.lower().split("?")[0].endswith(".pdf"):
        raise ReportGenerationError("The rhp_url does not appear to point to a PDF file.")

    try:
        reader = PdfReader(io.BytesIO(r.content))
        chunks, total = [], 0
        for page in reader.pages:
            t = page.extract_text() or ""
            chunks.append(t)
            total += len(t)
            if total >= MAX_RHP_CHARS:
                break
        text = "\n".join(chunks)[:MAX_RHP_CHARS]
    except Exception as e:  # noqa: BLE001 — pypdf can raise many internal exception types on malformed PDFs
        raise ReportGenerationError(f"Could not parse the PDF: {e}")

    if len(text.strip()) < MIN_EXTRACTED_CHARS:
        raise ReportGenerationError(
            "Could not extract text from the RHP PDF — it may be a scanned/image-only document."
        )
    return text


async def _call_anthropic(ipo: dict, rhp_text: str) -> str:
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise ReportGenerationError("ANTHROPIC_API_KEY is not configured on the server.")
    client = anthropic.AsyncAnthropic(api_key=api_key)
    try:
        resp = await client.messages.create(
            model=ANTHROPIC_MODEL,
            max_tokens=1500,
            system=REPORT_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": f"Company: {ipo.get('company_name')}\n\nRHP text:\n\n{rhp_text}"}],
        )
    except anthropic.APIError as e:
        raise ReportGenerationError(f"Anthropic API error: {e}")
    report = "\n".join(b.text for b in resp.content if getattr(b, "type", None) == "text").strip()
    if not report:
        raise ReportGenerationError("Anthropic returned an empty report.")
    return report


async def _generate_report(db, ipo_id: str):
    """Runs as a FastAPI BackgroundTask — must never raise into the event
    loop, and must never leave the IPO silently stuck in a "generating"
    state with no record of what happened."""
    now = lambda: datetime.now(timezone.utc).isoformat()  # noqa: E731
    ipo = await db.ipos.find_one({"id": ipo_id}, {"_id": 0})
    if not ipo or not ipo.get("rhp_url"):
        return
    try:
        text = await _extract_rhp_text(ipo["rhp_url"])
        report = await _call_anthropic(ipo, text)
    except ReportGenerationError as e:
        await db.ipos.update_one({"id": ipo_id}, {"$set": {"report_error": str(e), "updated_at": now()}})
        return
    except Exception as e:  # noqa: BLE001 — background task, last-resort catch-all
        logger.exception("Unexpected IPO report generation failure for %s", ipo_id)
        await db.ipos.update_one({"id": ipo_id}, {"$set": {"report_error": f"Unexpected error: {e}", "updated_at": now()}})
        return
    await db.ipos.update_one({"id": ipo_id}, {"$set": {
        "short_report": report, "report_generated_at": now(), "report_error": None, "updated_at": now(),
    }})


# ---------------------------------------------------------------------------
# NSE auto-refresh (undocumented public endpoint — see plan notes on risk)
# ---------------------------------------------------------------------------
def _parse_nse_date(s: str) -> Optional[str]:
    """"27-Jul-2026" -> "2026-07-27". Returns None on anything unexpected
    rather than raising — one bad row shouldn't break the whole refresh."""
    try:
        d, mon, y = s.split("-")
        return f"{y}-{NSE_MONTHS[mon]:02d}-{int(d):02d}"
    except Exception:  # noqa: BLE001
        return None


def _parse_price_band(s: str) -> dict:
    """"Rs.120 to Rs.127" -> {"min": 120.0, "max": 127.0}. Note: the regex
    must NOT be `[\\d.]+` — that greedily swallows the literal "." in "Rs."
    itself as a decimal point (turns "Rs.461" into 0.461, a real bug caught
    by testing against live NSE data)."""
    nums = re.findall(r"\d+(?:\.\d+)?", s or "")
    if len(nums) >= 2:
        return {"min": float(nums[0]), "max": float(nums[1])}
    if len(nums) == 1:
        return {"min": float(nums[0]), "max": float(nums[0])}
    return {"min": None, "max": None}


async def _fetch_nse_ipos() -> list:
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.get(NSE_UPCOMING_URL, headers={"User-Agent": BROWSER_USER_AGENT, "Accept": "application/json"})
    if r.status_code != 200:
        raise RuntimeError(f"NSE IPO list fetch failed (HTTP {r.status_code}).")
    return r.json()


async def _refresh_from_nse(db) -> dict:
    rows = await _fetch_nse_ipos()
    upserted = 0
    for row in rows:
        symbol, company = row.get("symbol"), row.get("companyName")
        if not symbol or not company:
            continue
        patch = {
            "company_name": company,
            "nse_symbol": symbol,
            "issue_open_date": _parse_nse_date(row.get("issueStartDate", "")),
            "issue_close_date": _parse_nse_date(row.get("issueEndDate", "")),
            "price_band": _parse_price_band(row.get("issuePrice", "")),
            "issue_size": row.get("issueSize"),
            "exchange": ["NSE"],
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        patch["status"] = _compute_status(patch)
        existing = await db.ipos.find_one({"nse_symbol": symbol}, {"_id": 0})
        if existing:
            await db.ipos.update_one({"nse_symbol": symbol}, {"$set": patch})
        else:
            doc = IpoRecord(**patch).model_dump()
            doc["status"] = patch["status"]
            await db.ipos.insert_one(doc)
        upserted += 1
    return {"upserted": upserted, "total_from_nse": len(rows)}


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------
def create_ipo_router(db, get_current_admin, cron_secret: str) -> APIRouter:
    router = APIRouter()

    @router.get("/ipos")
    async def list_ipos(status: Optional[str] = None):
        rows = await db.ipos.find({}, {"_id": 0}).sort("issue_open_date", -1).to_list(500)
        for r in rows:
            r["status"] = _compute_status(r)
        if status:
            rows = [r for r in rows if r["status"] == status]
        return rows

    @router.get("/ipos/{ipo_id}")
    async def get_ipo(ipo_id: str):
        row = await db.ipos.find_one({"id": ipo_id}, {"_id": 0})
        if not row:
            raise HTTPException(status_code=404, detail="IPO not found.")
        row["status"] = _compute_status(row)
        return row

    @router.post("/ipos")
    async def create_ipo(payload: IpoCreateRequest, background_tasks: BackgroundTasks, admin: dict = Depends(get_current_admin)):
        record = IpoRecord(**payload.model_dump())
        doc = record.model_dump()
        doc["status"] = _compute_status(doc)
        await db.ipos.insert_one(doc)
        doc.pop("_id", None)
        if doc.get("rhp_url"):
            background_tasks.add_task(_generate_report, db, doc["id"])
        return doc

    @router.put("/ipos/{ipo_id}")
    async def update_ipo(ipo_id: str, payload: IpoCreateRequest, background_tasks: BackgroundTasks, admin: dict = Depends(get_current_admin)):
        existing = await db.ipos.find_one({"id": ipo_id}, {"_id": 0})
        if not existing:
            raise HTTPException(status_code=404, detail="IPO not found.")
        updated = {**existing, **payload.model_dump(), "id": ipo_id, "updated_at": datetime.now(timezone.utc).isoformat()}
        updated["status"] = _compute_status(updated)
        rhp_changed = bool(payload.rhp_url) and payload.rhp_url != existing.get("rhp_url")
        await db.ipos.update_one({"id": ipo_id}, {"$set": updated})
        if rhp_changed:
            background_tasks.add_task(_generate_report, db, ipo_id)
        return updated

    @router.post("/admin/ipos/nse-refresh")
    async def nse_refresh_cron(request: Request):
        """Called by an external cron (same X-Cron-Key mechanism as the
        existing Definedge auto-refresh) rather than admin JWT, since this is
        a machine caller."""
        if not cron_secret or request.headers.get("X-Cron-Key") != cron_secret:
            raise HTTPException(status_code=401, detail="Invalid cron key")
        try:
            return await _refresh_from_nse(db)
        except Exception as e:  # noqa: BLE001
            raise HTTPException(status_code=502, detail=f"NSE refresh failed: {e}")

    @router.post("/admin/ipos/refresh-now")
    async def nse_refresh_admin(admin: dict = Depends(get_current_admin)):
        """Same refresh, triggered by the admin UI's "Refresh from NSE"
        button — admin-JWT-gated rather than cron-secret-gated so the secret
        never has to live in the browser."""
        try:
            return await _refresh_from_nse(db)
        except Exception as e:  # noqa: BLE001
            raise HTTPException(status_code=502, detail=f"NSE refresh failed: {e}")

    return router
