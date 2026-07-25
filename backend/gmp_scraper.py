"""
GMP (Grey Market Premium) scraper — two sources, IPO Watch + InvestorGain.

The original spec asked for 3-5 sources aggregated into a median consensus
with outlier filtering. Live-tested all 5 named candidates (Chittorgarh,
InvestorGain, IPO Watch, IPO Central, LiveGMP) before writing any code:
  - Chittorgarh is a client-rendered (Next.js) app that needs a headless
    browser to render at all — not viable without new infrastructure.
  - IPO Central isn't actually a dedicated GMP tracker — no structured
    table found, just an IPO news blog.
  - LiveGMP appears to be a dead site — its own sitemap links 404, and
    `/ipo/` is an empty directory listing.
  - IPO Watch is plain server-rendered HTML with a clean table (company
    name, GMP, price band, status, source's own last-updated timestamp per
    row).
  - InvestorGain's HTML table is an empty client-rendered shell ("No data
    available" server-side), but the JS bundle that populates it calls a
    plain JSON REST endpoint (`webnodejs.investorgain.com/cloud/v2/report/
    data-read/...`) — no headless browser needed, just an httpx GET with the
    right path params, found by downloading and grepping the page's Next.js
    chunks for the actual fetch call.
  Both IPO Watch and InvestorGain: robots.txt permits general crawling
  (only blocks AI-training/SEO bots), and no published Terms of Use
  prohibits scraping either site.

With exactly 2 real sources, a "median consensus with outlier filtering" is
statistically meaningless (median of 2 = average, nothing to call an
outlier against), so this shows both figures side by side instead of
faking a consensus — confirmed with the user before adding the second
source. IPO Watch is treated as primary (e.g. for the list-page column);
InvestorGain is a labeled secondary figure shown alongside it.

Same fragility caveat as every other scrape in this codebase: unofficial,
can break if either site restructures.
"""
import logging
import re
from datetime import datetime, timezone

import httpx

logger = logging.getLogger(__name__)

IPOWATCH_GMP_URL = "https://ipowatch.in/ipo-grey-market-premium-latest-ipo-gmp/"

# InvestorGain's page is a Next.js app; report id 331 is "IPO GMP Live"
# (found via its own cloud/v2/report/info-read/331 metadata endpoint).
INVESTORGAIN_REFERER = "https://www.investorgain.com/report/ipo-gmp-live/331/"
INVESTORGAIN_DATA_URL = (
    "https://webnodejs.investorgain.com/cloud/v2/report/data-read/331/1/{month}/{year}/{fy}/0/all?search="
)

BROWSER_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)

ROW_RE = re.compile(r"<tr>(.*?)</tr>", re.S)
CELL_RE = re.compile(r"<td[^>]*>(.*?)</td>", re.S)
TAG_RE = re.compile(r"<[^>]+>")
NUMBER_RE = re.compile(r"-?\d+(?:\.\d+)?")
IG_GMP_RE = re.compile(r"&#8377;<b>([^<]+)</b>")
IG_BOLD_RE = re.compile(r"<b>([^<]+)</b>")


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


def _investorgain_financial_year(now: datetime) -> str:
    """"2026-27" style string the API expects — April-March FY, same
    convention InvestorGain's own JS uses to compute it client-side."""
    y = now.year
    return f"{y}-{str(y + 1)[-2:]}" if now.month >= 4 else f"{y - 1}-{str(y)[-2:]}"


def _parse_investorgain_rupee(gmp_html: str):
    """The GMP cell is HTML like "&#8377;<b>184</b> (32.9%)..."; "--" means
    no GMP is trading yet for that IPO, not zero — treated as unparseable
    (skipped) rather than coerced to 0, so it can't be confused with a real
    zero-GMP row."""
    m = IG_GMP_RE.search(gmp_html or "")
    if not m:
        return None
    text = m.group(1).strip()
    if text in ("--", "-", ""):
        return None
    try:
        return float(text.replace(",", ""))
    except ValueError:
        return None


def parse_investorgain_rows(data: dict) -> list:
    """[{company_name, gmp, price_band_text, status_text,
    source_last_updated}, ...] from the data-read JSON. Rows with no GMP yet
    ("--") are skipped, same as an unparseable IPO Watch cell."""
    results = []
    for row in data.get("reportTableData", []):
        name = (row.get("~ipo_name") or "").strip()
        gmp = _parse_investorgain_rupee(row.get("GMP", ""))
        if not name or gmp is None:
            continue
        price = (row.get("Price (₹)") or "").strip()
        updated_m = IG_BOLD_RE.search(row.get("Updated-On", "") or "")
        results.append({
            "company_name": name,
            "gmp": gmp,
            "price_band_text": f"₹{price}" if price else "",
            "status_text": (row.get("~IPO_Category") or "").strip(),
            "source_last_updated": updated_m.group(1).strip() if updated_m else "",
        })
    return results


async def fetch_investorgain_data() -> dict:
    now = datetime.now(timezone.utc)
    url = INVESTORGAIN_DATA_URL.format(month=now.month, year=now.year, fy=_investorgain_financial_year(now))
    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as c:
        r = await c.get(url, headers={"User-Agent": BROWSER_USER_AGENT, "Referer": INVESTORGAIN_REFERER})
    if r.status_code != 200:
        raise RuntimeError(f"InvestorGain GMP fetch failed (HTTP {r.status_code}).")
    data = r.json()
    if data.get("msg") != 1:
        raise RuntimeError(f"InvestorGain GMP fetch returned error: {data.get('error', 'unknown')}")
    return data


async def _store_rows(db, source: str, rows: list, our_ipos: list, scraped_at: str) -> int:
    """Upserts gmp_current (keyed on ipo_id+source) and appends gmp_history
    for every matched row. One bad write is logged and skipped rather than
    aborting the rest of the cycle."""
    matched = 0
    for row in rows:
        ipo_id = match_ipo(row["company_name"], our_ipos)
        if ipo_id is None:
            continue
        doc = {
            "ipo_id": ipo_id,
            "source": source,
            "gmp": row["gmp"],
            "price_band_text": row["price_band_text"],
            "status_text": row["status_text"],
            "source_last_updated": row["source_last_updated"],
            "scraped_at": scraped_at,
        }
        try:
            await db.gmp_current.update_one({"ipo_id": ipo_id, "source": source}, {"$set": doc}, upsert=True)
            await db.gmp_history.insert_one({"ipo_id": ipo_id, "source": source, "gmp": row["gmp"], "scraped_at": scraped_at})
            matched += 1
        except Exception:  # noqa: BLE001 — one bad write shouldn't block the rest of the cycle
            logger.exception("Failed to store GMP for ipo_id=%s source=%s", ipo_id, source)
    return matched


async def refresh_gmp(db) -> dict:
    """Refreshes both sources independently — one source's fetch failure is
    logged and reported per-source, never blocks the other. Both sources
    share a single scraped_at timestamp so gmp_history rows line up on the
    same x-axis point for the two-line trend chart on the frontend.
    Returns {"ipowatch": {"matched", "total_rows"} | {"error"}, "investorgain": {...}}."""
    our_ipos = await db.ipos.find({}, {"_id": 0, "id": 1, "company_name": 1}).to_list(1000)
    scraped_at = datetime.now(timezone.utc).isoformat()
    results = {}

    try:
        rows = parse_ipowatch_table(await fetch_ipowatch_html())
        results["ipowatch"] = {"matched": await _store_rows(db, "ipowatch", rows, our_ipos, scraped_at), "total_rows": len(rows)}
    except Exception as e:  # noqa: BLE001
        logger.exception("IPO Watch GMP refresh failed")
        results["ipowatch"] = {"error": str(e)}

    try:
        rows = parse_investorgain_rows(await fetch_investorgain_data())
        results["investorgain"] = {"matched": await _store_rows(db, "investorgain", rows, our_ipos, scraped_at), "total_rows": len(rows)}
    except Exception as e:  # noqa: BLE001
        logger.exception("InvestorGain GMP refresh failed")
        results["investorgain"] = {"error": str(e)}

    return results
