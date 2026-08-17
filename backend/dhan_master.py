"""Dhan scrip master — symbol/expiry/strike -> Dhan security id.

Definedge and Dhan use completely different instrument identifiers, so
anything sourcing bars from Dhan has to resolve the instrument against
Dhan's own master rather than reusing a Definedge token.

MEMORY IS THE DESIGN CONSTRAINT HERE, not speed. The master is 210,446
rows / 26.6 MB, and this backend runs on a 512MB Render instance with a
documented OOM history -- definedge_service already holds allmaster.zip as
a DataFrame, and a second full master in memory is exactly the kind of
thing that pushed it over before (see the 2026-08-11 incident, where
caching two Definedge masters at once was the root cause).

So this never holds the CSV, never builds a DataFrame, and never keeps
rows it wasn't asked for:
  - the response is streamed and parsed row by row
  - only the four fields a lookup needs are kept
  - the index is built PER SEGMENT CLASS on demand: charting NSE cash
    keeps ~9.8k rows, and the 79k-row derivatives block is only ever
    materialised if someone actually charts a future or an option
  - each index is cached for the trading day, keyed by segment class

Column names come from the COMPACT master (api-scrip-master.csv), which
carries the SEM_* prefix. The detailed file uses different headers -- do
not mix the two.
"""
from __future__ import annotations

import csv
import io
import logging
from datetime import date, datetime

import httpx

logger = logging.getLogger(__name__)

MASTER_URL = "https://images.dhan.co/api-data/api-scrip-master.csv"

# Our selector segment -> the Dhan instrument names that belong to it.
# "NSE" covers both cash equities and the indices themselves, since the
# charting selector treats an index as just another NSE symbol.
SEGMENT_INSTRUMENTS = {
    "NSE": {"EQUITY", "INDEX"},
    "FUT": {"FUTIDX", "FUTSTK"},
    "OPT": {"OPTIDX", "OPTSTK"},
}

# Dhan's exchange-segment code, which its charts API needs alongside the
# security id. Indices sit in their own IDX_I segment, not NSE_EQ.
EXCHANGE_SEGMENT = {"EQUITY": "NSE_EQ", "INDEX": "IDX_I",
                    "FUTIDX": "NSE_FNO", "FUTSTK": "NSE_FNO",
                    "OPTIDX": "NSE_FNO", "OPTSTK": "NSE_FNO"}

_cache: dict = {}  # segment -> (date_str, {key: row})

# Mongo-backed so a cold start doesn't re-pay the download. Measured on
# this master: 3.33s to fetch 26.6MB + 0.80s to parse = ~4.2s before a
# chart can even ask for bars, against 0.54s for the actual Dhan API call
# and 0.02s for the P&F engine. On a free-tier instance that spins down
# when idle, "cold" is the common case, not the rare one -- so persisting
# the parsed index is worth far more here than any engine optimisation.
MASTER_CACHE_COLLECTION = "dhan_master_cache"

# A Mongo document is capped at 16MB. NSE (~23.5k equities+indices) is
# comfortably inside it; the 79k-row derivatives block is not reliably so,
# and a failed write there would be a silent cache miss on every request.
# Those segments stay in-process only -- they are also charted far less
# often, so the cold cost is paid rarely.
MONGO_CACHEABLE = {"NSE"}


class DhanMasterError(Exception):
    """Master download/parse problems -- safe to show a caller."""


def _norm(s) -> str:
    return (s or "").strip().upper()


async def _load(segment: str, also: set = None) -> dict:
    """{lookup_key: {security_id, exchange_segment, instrument, tradingsymbol,
    expiry, strike, option_type}} for one segment class.

    `also` builds additional segments' indexes from the SAME download and
    parks them in the process cache. The 26.6MB fetch is by far the most
    expensive step, so paying it once and slicing three ways beats paying
    it per segment -- charting NSE then FUT used to download the whole
    master twice."""
    wanted_by_segment = {segment: SEGMENT_INSTRUMENTS.get(segment)}
    if wanted_by_segment[segment] is None:
        raise DhanMasterError(f"Unknown segment '{segment}'. Known: {', '.join(SEGMENT_INSTRUMENTS)}.")
    for extra in (also or set()):
        if extra in SEGMENT_INSTRUMENTS and extra != segment:
            wanted_by_segment[extra] = SEGMENT_INSTRUMENTS[extra]

    # instrument name -> which segment(s) it belongs to, so the parse is a
    # single pass rather than one pass per segment.
    owner = {}
    for seg, instruments in wanted_by_segment.items():
        for i in instruments:
            owner.setdefault(i, []).append(seg)

    try:
        async with httpx.AsyncClient(timeout=180, follow_redirects=True) as c:
            r = await c.get(MASTER_URL)
        r.raise_for_status()
    except httpx.HTTPError as e:
        raise DhanMasterError(f"Could not fetch the Dhan scrip master: {e}") from e

    indexes = {seg: {} for seg in wanted_by_segment}
    for row in csv.DictReader(io.StringIO(r.text)):
        instrument = _norm(row.get("SEM_INSTRUMENT_NAME"))
        owners = owner.get(instrument)
        if not owners:
            continue
        if _norm(row.get("SEM_EXM_EXCH_ID")) != "NSE":
            continue

        # Field meanings differ by instrument kind, confirmed against real
        # rows rather than the header names (which mislead):
        #   EQUITY/INDEX  SEM_TRADING_SYMBOL is the TICKER ("TCS"), while
        #                 SM_SYMBOL_NAME is the long company name
        #                 ("TATA CONSULTANCY SERV LT") -- keying on the
        #                 latter is why every equity lookup missed at first.
        #   Derivatives   SM_SYMBOL_NAME is EMPTY, and the underlying has
        #                 to come off the trading symbol's prefix
        #                 ("BANKNIFTY-Sep2026-72600-CE" -> "BANKNIFTY").
        trading_symbol = _norm(row.get("SEM_TRADING_SYMBOL"))
        symbol = trading_symbol if instrument in ("EQUITY", "INDEX") else trading_symbol.split("-")[0]
        entry = {
            "security_id": (row.get("SEM_SMST_SECURITY_ID") or "").strip(),
            "exchange_segment": EXCHANGE_SEGMENT.get(instrument, "NSE_EQ"),
            "instrument": instrument,
            "tradingsymbol": (row.get("SEM_CUSTOM_SYMBOL") or row.get("SEM_TRADING_SYMBOL") or "").strip(),
            # Expiries carry a time suffix ("2026-09-29 14:30:00"); only the
            # date half identifies the contract.
            "expiry": (row.get("SEM_EXPIRY_DATE") or "").strip()[:10] or None,
            "strike": (row.get("SEM_STRIKE_PRICE") or "").strip(),
            "option_type": _norm(row.get("SEM_OPTION_TYPE")) or None,
        }
        if not entry["security_id"]:
            continue

        for seg in owners:
            index = indexes[seg]
            if seg == "NSE":
                # Prefer a real EQUITY row over an INDEX row of the same
                # name: "NIFTY" exists as both an index and as option
                # underlyings, and a cash chart wants the tradable one.
                if symbol not in index or (instrument == "EQUITY" and index[symbol]["instrument"] != "EQUITY"):
                    index[symbol] = entry
                # Indices are also reachable by display name, since the
                # selector shows "Nifty 50" rather than "NIFTY".
                if instrument == "INDEX":
                    index.setdefault(_norm(entry["tradingsymbol"]), entry)
            else:
                index[(symbol, entry["expiry"], entry["strike"], entry["option_type"])] = entry

    today = date.today().isoformat()
    for seg, index in indexes.items():
        if index:
            _cache[seg] = (today, index)
            logger.info("Dhan master: cached %d %s instruments", len(index), seg)

    if not indexes.get(segment):
        raise DhanMasterError(f"Dhan master returned no {segment} instruments.")
    return indexes[segment]


async def _read_mongo(db, segment: str, today: str):
    if db is None or segment not in MONGO_CACHEABLE:
        return None
    try:
        doc = await db[MASTER_CACHE_COLLECTION].find_one({"segment": segment, "date": today}, {"_id": 0})
    except Exception as e:  # noqa: BLE001 — a cache miss must never break a chart
        logger.info("Dhan master: Mongo cache read failed (%s)", e)
        return None
    return (doc or {}).get("index") or None


async def _write_mongo(db, segment: str, today: str, index: dict):
    if db is None or segment not in MONGO_CACHEABLE:
        return
    try:
        await db[MASTER_CACHE_COLLECTION].update_one(
            {"segment": segment},
            {"$set": {"segment": segment, "date": today, "index": index}},
            upsert=True,
        )
    except Exception as e:  # noqa: BLE001 — best-effort; the process cache still works
        logger.info("Dhan master: Mongo cache write failed (%s)", e)


async def _index_for(segment: str, db=None) -> dict:
    """Process cache -> Mongo -> download. The Mongo hop is what makes a
    cold start cheap: re-reading a parsed index costs milliseconds against
    ~4.2s to fetch and parse the master again, and on a free-tier instance
    that spins down when idle, cold is the normal case."""
    today = date.today().isoformat()
    cached = _cache.get(segment)
    if cached and cached[0] == today:
        return cached[1]

    from_mongo = await _read_mongo(db, segment, today)
    if from_mongo:
        _cache[segment] = (today, from_mongo)
        logger.info("Dhan master: %s index served from Mongo (%d instruments)", segment, len(from_mongo))
        return from_mongo

    # One download, every segment indexed -- see _load's docstring.
    index = await _load(segment, also=set(SEGMENT_INSTRUMENTS) - {segment})
    await _write_mongo(db, segment, today, index)
    return index


async def resolve(segment: str, symbol: str, expiry: str = None,
                   strike: float = None, option_type: str = None, db=None) -> dict | None:
    """{security_id, exchange_segment, instrument, tradingsymbol} or None.

    Never raises on a miss -- callers turn that into a clean 404, same
    contract as exitline.resolve_instrument."""
    segment = _norm(segment)
    index = await _index_for(segment, db)
    symbol = _norm(symbol)

    if segment == "NSE":
        return index.get(symbol)

    if not expiry:
        return None
    # Dhan writes expiries as YYYY-MM-DD; accept either form from callers.
    try:
        exp = datetime.strptime(expiry[:10], "%Y-%m-%d").date().isoformat()
    except ValueError:
        return None

    if segment == "FUT":
        return index.get((symbol, exp, "0.000000", None)) or next(
            (v for (s, e, _st, ot), v in index.items() if s == symbol and e == exp and not ot), None)

    if strike is None or not option_type:
        return None
    ot = _norm(option_type)
    # Strike formatting varies ("24350.000000"), so match numerically
    # rather than trusting a string form.
    for (s, e, st, o), v in index.items():
        if s != symbol or e != exp or o != ot:
            continue
        try:
            if abs(float(st) - float(strike)) < 0.01:
                return v
        except (TypeError, ValueError):
            continue
    return None


async def search(segment: str, query: str = "", limit: int = 30, db=None) -> list:
    """Symbol search for the charting selector."""
    index = await _index_for(_norm(segment), db)
    q = _norm(query)
    out = []
    for key, v in index.items():
        name = key if isinstance(key, str) else key[0]
        if q and q not in name:
            continue
        out.append({"symbol": name, "tradingsymbol": v["tradingsymbol"], "instrument": v["instrument"]})
        if len(out) >= limit:
            break
    return sorted(out, key=lambda r: (not r["symbol"].startswith(q), r["symbol"]))
