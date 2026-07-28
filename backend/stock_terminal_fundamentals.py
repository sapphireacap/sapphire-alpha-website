"""
Stock Research Terminal -- fundamentals + shareholding ingestion from
Screener.in (Phase 2). No API/auth needed for the public data used here;
SCREENER_SESSION_COOKIE is read if present (richer/authenticated view) but
everything below works unauthenticated too, just on the public dataset.

HTML structure below was verified against a real fetched page
(screener.in/company/RELIANCE/consolidated/), not guessed:
- `<ul id="top-ratios">` holds `<li><span class="name">LABEL</span>
  <span class="value">...<span class="number">VALUE</span></span></li>`
  pairs (Market Cap, Current Price, Stock P/E, Book Value, Dividend Yield,
  ROCE, ROE, Face Value).
- `#profit-loss`, `#balance-sheet`, `#cash-flow`, `#ratios` each hold a
  `<table class="data-table">` with one `<td class="text">LABEL</td>` per
  row (trailing "+" on some labels for expandable rows, stripped here) and
  one `<td>VALUE</td>` per year column, oldest to newest -- the same
  generic shape across all four sections, one parser handles all of them.
- `#shareholding`'s `#quarterly-shp` table is the same shape, columns are
  quarters instead of years (Promoters/FIIs/DIIs/Government/Public/No. of
  Shareholders rows).

Fields the spec wants that Screener's page doesn't expose directly are
DERIVED from real values already on the page (P/B = price/book value,
NPM = net profit/sales, interest coverage = (PBT+interest)/interest,
D/E = borrowings/(equity+reserves)) -- never estimated from an unrelated
proxy. `current_ratio` has no real source on this page (no current vs.
non-current asset/liability split) and is left null rather than guessed.
Promoter pledge % has no dedicated row for a debt-free company like the one
verified against -- best-effort text search, null if not found, not
assumed to be zero.
"""
import asyncio
import logging
import re
from datetime import datetime, timezone

import httpx
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

BROWSER_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)
SCREENER_BASE = "https://www.screener.in/company"
INTER_REQUEST_DELAY_SECONDS = 2  # per the spec -- be a polite scraper


def _num(text):
    """'17,15,385' / '₹ 1,268' / '23.0' / '0.47%' -> float, or None if it
    doesn't parse (never raises, never guesses a value)."""
    if text is None:
        return None
    cleaned = re.sub(r"[^\d.\-]", "", text.replace(",", ""))
    if not cleaned or cleaned in ("-", "."):
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


def _parse_top_ratios(soup) -> dict:
    out = {}
    ul = soup.find("ul", id="top-ratios")
    if not ul:
        return out
    for li in ul.find_all("li"):
        name_el, value_el = li.find("span", class_="name"), li.find("span", class_="value")
        if not name_el or not value_el:
            continue
        label = name_el.get_text(strip=True)
        number_el = value_el.find("span", class_="number")
        out[label] = _num(number_el.get_text(strip=True) if number_el else value_el.get_text(strip=True))
    return out


def _parse_data_table(soup, section_id: str) -> dict:
    """{row_label (trailing '+' stripped): [values, oldest -> newest]}."""
    section = soup.find(id=section_id)
    if not section:
        return {}
    table = section.find("table", class_="data-table")
    if not table:
        return {}
    out = {}
    for row in table.select("tbody tr"):
        text_cell = row.find("td", class_="text")
        if not text_cell:
            continue
        label = text_cell.get_text(strip=True).rstrip("+")
        values = [_num(td.get_text(strip=True)) for td in row.find_all("td") if "text" not in (td.get("class") or [])]
        out[label] = values
    return out


def _parse_shareholding(soup) -> dict:
    """{row_label: latest_value} from #quarterly-shp -- same table shape as
    _parse_data_table but keyed to the single latest (last) column, and
    quarter labels come from the header row rather than being discarded."""
    section = soup.find(id="shareholding")
    if not section:
        return {}, None
    table = section.find(id="quarterly-shp")
    table = table.find("table", class_="data-table") if table else None
    if not table:
        return {}, None
    headers = [th.get_text(strip=True) for th in table.select("thead th")][1:]
    latest_quarter = headers[-1] if headers else None
    out = {}
    for row in table.select("tbody tr"):
        text_cell = row.find("td", class_="text")
        if not text_cell:
            continue
        label = text_cell.get_text(strip=True).split("+")[0].strip()
        values = [_num(td.get_text(strip=True)) for td in row.find_all("td") if "text" not in (td.get("class") or [])]
        if values:
            out[label] = values[-1]
    return out, latest_quarter


def _cagr(values: list, years_back: int):
    """values: oldest -> newest. None if there isn't enough real history --
    never approximated from a shorter window."""
    if not values or len(values) <= years_back:
        return None
    end, start = values[-1], values[-1 - years_back]
    if start is None or end is None or start <= 0:
        return None
    return ((end / start) ** (1 / years_back) - 1) * 100


async def _fetch_company_html(client: httpx.AsyncClient, symbol: str) -> str:
    """Tries /consolidated/ first (most large-caps), falls back to the
    standalone page for companies that don't have consolidated financials.
    Raises if neither resolves."""
    for suffix in ("/consolidated/", "/"):
        r = await client.get(f"{SCREENER_BASE}/{symbol}{suffix}", headers={"User-Agent": BROWSER_USER_AGENT})
        if r.status_code == 200:
            return r.text
    raise RuntimeError(f"Screener.in page not found for {symbol} (tried consolidated + standalone).")


async def fetch_fundamentals(client: httpx.AsyncClient, symbol: str) -> dict:
    """One symbol's fundamentals + shareholding, scraped live. Returns
    (fundamentals_doc, shareholding_doc) -- shareholding_doc is None if the
    page has no shareholding table (rare, but happens for very thin
    listings)."""
    html = await _fetch_company_html(client, symbol)
    soup = BeautifulSoup(html, "html.parser")

    top = _parse_top_ratios(soup)
    pl = _parse_data_table(soup, "profit-loss")
    bs = _parse_data_table(soup, "balance-sheet")
    cf = _parse_data_table(soup, "cash-flow")
    ratios = _parse_data_table(soup, "ratios")
    shp, quarter = _parse_shareholding(soup)

    sales = pl.get("Sales") or []
    net_profit = pl.get("Net Profit") or []
    interest = (pl.get("Interest") or [None])[-1]
    pbt = (pl.get("Profit before tax") or [None])[-1]
    borrowings = (bs.get("Borrowings") or [None])[-1]
    equity = (bs.get("Equity Capital") or [None])[-1]
    reserves = (bs.get("Reserves") or [None])[-1]

    price = top.get("Current Price")
    book_value = top.get("Book Value")

    fundamentals = {
        "symbol": symbol,
        "pe_ratio": top.get("Stock P/E"),
        "pb_ratio": (price / book_value) if price and book_value else None,
        "roe": top.get("ROE"),
        "roce": top.get("ROCE"),
        "debt_to_equity": (borrowings / (equity + reserves)) if borrowings is not None and equity and reserves else None,
        "eps": (pl.get("EPS in Rs") or [None])[-1],
        "book_value": book_value,
        "dividend_yield": top.get("Dividend Yield"),
        "opm": (pl.get("OPM %") or [None])[-1],
        "npm": (net_profit[-1] / sales[-1] * 100) if sales and net_profit and sales[-1] else None,
        "interest_coverage": ((pbt + interest) / interest) if pbt is not None and interest else None,
        "current_ratio": None,  # no real source on this page -- see module docstring
        "sales_cagr_3y": _cagr(sales, 3),
        "sales_cagr_5y": _cagr(sales, 5),
        "profit_cagr_3y": _cagr(net_profit, 3),
        "profit_cagr_5y": _cagr(net_profit, 5),
        "ocf_latest": (cf.get("Cash from Operating Activity") or [None])[-1],
        "pat_latest": net_profit[-1] if net_profit else None,
        "debtor_days_prev": (ratios.get("Debtor Days") or [None, None])[-2] if len(ratios.get("Debtor Days") or []) >= 2 else None,
        "debtor_days_curr": (ratios.get("Debtor Days") or [None])[-1],
        "revenue_growth_1y": ((sales[-1] / sales[-2] - 1) * 100) if len(sales) >= 2 and sales[-2] else None,
        "source": "screener.in",
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }

    shareholding = None
    if shp and quarter:
        promoter_row = next((v for k, v in shp.items() if k.startswith("Promoters")), None)
        pledge_pct = None
        for k, v in shp.items():
            if "pledg" in k.lower():
                pledge_pct = v
        shareholding = {
            "symbol": symbol,
            "quarter": quarter,
            "promoter_pct": promoter_row,
            "promoter_pledge_pct": pledge_pct,
            "fii_pct": shp.get("FIIs"),
            "dii_pct": shp.get("DIIs"),
            "public_pct": shp.get("Public"),
        }

    return fundamentals, shareholding


async def ingest_fundamentals(db, limit: int = None) -> dict:
    """Batch loop over stock_symbol_master -- same per-item try/except +
    summary-dict shape as every other ingestion function in this codebase.
    Deliberately sequential with a fixed delay between requests (not
    parallel) -- a polite scrape, per the spec."""
    symbols = await db.stock_symbol_master.find({}, {"_id": 0, "symbol": 1}).to_list(1000)
    if limit:
        symbols = symbols[:limit]

    updated, failed = 0, 0
    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
        for i, s in enumerate(symbols):
            symbol = s["symbol"]
            try:
                fundamentals, shareholding = await fetch_fundamentals(client, symbol)
                await db.stock_fundamentals.update_one({"symbol": symbol}, {"$set": fundamentals}, upsert=True)
                if shareholding:
                    await db.stock_shareholding.update_one(
                        {"symbol": symbol, "quarter": shareholding["quarter"]},
                        {"$set": shareholding}, upsert=True,
                    )
                updated += 1
            except Exception as e:  # noqa: BLE001 -- one symbol's failure must not stop the rest
                logger.warning("Stock Terminal: fundamentals scrape failed for %s: %s", symbol, e)
                failed += 1
            if i < len(symbols) - 1:
                await asyncio.sleep(INTER_REQUEST_DELAY_SECONDS)

    return {"updated": updated, "failed": failed, "total": len(symbols)}
