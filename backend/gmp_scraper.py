"""
GMP (Grey Market Premium) scraper — single-source, from IPO Watch.

Why single-source: the original spec asked for 3-5 sources aggregated into
a median consensus with outlier filtering. Live-tested all 5 named
candidates (Chittorgarh, InvestorGain, IPO Watch, IPO Central, LiveGMP)
before writing any code:
  - Chittorgarh and InvestorGain are both client-rendered (Next.js) apps —
    the raw HTML has no data (InvestorGain's table literally says "No data
    available" server-side); real values load via a client-side API call
    that wasn't discoverable without deep JS-bundle reverse-engineering for
    InvestorGain, and Chittorgarh needs a headless browser to render at all.
  - IPO Central isn't actually a dedicated GMP tracker — no structured
    table found, just an IPO news blog.
  - LiveGMP appears to be a dead site — its own sitemap links 404, and
    `/ipo/` is an empty directory listing.
  - IPO Watch is the only one that's genuinely real and scrapeable: plain
    server-rendered HTML with a clean table (company name, GMP, price band,
    status, and the source's own last-updated timestamp per row). Its
    robots.txt permits general crawling (only blocks AI-training bots and a
    few admin paths); no published Terms of Use found anywhere on the site.

With one real source there's nothing to compute a statistical consensus or
filter outliers against, so this ships as honest single-source GMP instead
of a faked multi-source aggregate — confirmed with the user before building.

Same fragility caveat as every other scrape in this codebase: unofficial,
can break if the site restructures.
"""
import logging
import re
from datetime import datetime, timezone

import httpx

logger = logging.getLogger(__name__)

IPOWATCH_GMP_URL = "https://ipowatch.in/ipo-grey-market-premium-latest-ipo-gmp/"
BROWSER_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)

ROW_RE = re.compile(r"<tr>(.*?)</tr>", re.S)
CELL_RE = re.compile(r"<td[^>]*>(.*?)</td>", re.S)
TAG_RE = re.compile(r"<[^>]+>")
NUMBER_RE = re.compile(r"-?\d+(?:\.\d+)?")


def _normalize_company_name(name: str) -> str:
    """Same normalization as ipo_routes.py's _normalize_company_name — kept
    as a local copy since this module is meant to stay independently
    testable/removable without pulling in the whole ipo_routes module."""
    return re.sub(r"[^A-Z0-9]", "", (name or "").upper())


def _parse_rupee_number(text: str):
    """"₹123" -> 123.0, "₹-15" -> -15.0 (negative GMP is real — some IPOs
    trade at a discount). Returns None (never raises) if nothing parses, so
    a single bad cell doesn't take down the whole row."""
    m = NUMBER_RE.search((text or "").replace(",", ""))
    return float(m.group()) if m else None


def _clean_cell(html: str) -> str:
    return TAG_RE.sub("", html).strip()


def parse_ipowatch_table(html: str) -> list:
    """[{company_name, gmp, price_band_text, status_text,
    source_last_updated}, ...]. Locates the table by its "IPO Name" header
    marker (avoids accidentally matching an unrelated <tr> elsewhere on the
    page). The header row is identified and skipped by its first cell's
    text ("IPO Name") rather than by position — an earlier version skipped
    "row index 0" instead, but slicing the HTML mid-cell (right at the
    "IPO Name" text) threw off which <tr> match actually came first,
    silently dropping the real first data row instead of the header
    (caught by testing against a real downloaded page, not assumed)."""
    start = html.find("IPO Name")
    if start == -1:
        return []
    table_html = html[start:]

    results = []
    for row_html in ROW_RE.findall(table_html):
        cells = [_clean_cell(c) for c in CELL_RE.findall(row_html)]
        if len(cells) < 9:
            continue
        name, gmp_text, _trend, price_band, _est_listing, _date, _type, status, last_updated = cells[:9]
        if name.strip().lower() == "ipo name":
            continue  # header row
        gmp = _parse_rupee_number(gmp_text)
        if gmp is None or not name.strip():
            continue
        results.append({
            "company_name": name.strip(),
            "gmp": gmp,
            "price_band_text": price_band.strip(),
            "status_text": status.strip(),
            "source_last_updated": last_updated.strip(),
        })
    return results


def match_ipo(scraped_name: str, our_ipos: list):
    """Returns the matching IPO's `id`, or None. IPO Watch's names often
    omit the "Limited"/"Ltd" suffix ours include (e.g. "Fusion Klassroom" vs
    "Fusion Klassroom Limited"), so this matches as a prefix/substring
    rather than requiring strict equality — most rows still won't match
    anything (IPO Watch lists far more issues than we track), which is
    expected and not an error."""
    norm_scraped = _normalize_company_name(scraped_name)
    if not norm_scraped:
        return None
    for ipo in our_ipos:
        norm_ours = _normalize_company_name(ipo.get("company_name", ""))
        if not norm_ours:
            continue
        if norm_scraped in norm_ours or norm_ours in norm_scraped:
            return ipo["id"]
    return None


async def fetch_ipowatch_html() -> str:
    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as c:
        r = await c.get(IPOWATCH_GMP_URL, headers={"User-Agent": BROWSER_USER_AGENT})
    if r.status_code != 200:
        raise RuntimeError(f"IPO Watch GMP page fetch failed (HTTP {r.status_code}).")
    return r.text


async def refresh_gmp(db) -> dict:
    """Fetches, parses, matches against our tracked IPOs, and upserts
    gmp_current + appends gmp_history for every match. Best-effort: a fetch
    failure raises (caller decides how to surface it), but a handful of
    unparseable or unmatched rows never block the ones that did work."""
    html = await fetch_ipowatch_html()
    rows = parse_ipowatch_table(html)

    our_ipos = await db.ipos.find({}, {"_id": 0, "id": 1, "company_name": 1}).to_list(1000)
    now_iso = datetime.now(timezone.utc).isoformat()

    matched = 0
    for row in rows:
        ipo_id = match_ipo(row["company_name"], our_ipos)
        if ipo_id is None:
            continue
        doc = {
            "ipo_id": ipo_id,
            "gmp": row["gmp"],
            "price_band_text": row["price_band_text"],
            "status_text": row["status_text"],
            "source": "ipowatch",
            "source_last_updated": row["source_last_updated"],
            "scraped_at": now_iso,
        }
        try:
            await db.gmp_current.update_one({"ipo_id": ipo_id}, {"$set": doc}, upsert=True)
            await db.gmp_history.insert_one({"ipo_id": ipo_id, "gmp": row["gmp"], "scraped_at": now_iso})
            matched += 1
        except Exception:  # noqa: BLE001 — one bad write shouldn't block the rest of the cycle
            logger.exception("Failed to store GMP for ipo_id=%s", ipo_id)

    return {"matched": matched, "total_rows": len(rows)}
