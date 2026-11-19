"""Exitline on FYERS data: instrument lookup, the level ladder, the session chart and the live price.

The level maths, zone logic and chart bucketing are the unchanged functions in exitline.py; this module
only supplies their inputs from FYERS instead of the old master file / broker session.

Instrument lookup (no login, not counted against the request budget): FYERS' public symbol files
  NSE_CM.csv  (~10,000 rows)  cash stocks (-EQ series) and indices
  NSE_FO.csv  (~93,000 rows)  index and stock futures and options
are STREAMED and boiled down once per IST day into small Mongo documents (`fyers_exitline_master`):
  cash            [[name, symbol], ...]
  index           {FUT: [underlying...], OPT: [underlying...]}
  fo:<UNDERLYING> {fut: {expiry: symbol}, opt: {expiry: [[strike, ce_symbol, pe_symbol], ...]}}
A request reads only the one document it needs, so nothing large stays in memory.

Request cost (free plan: 5,000 a day, 50 a minute; see fyers_budget). A first look at an instrument is
3 history requests (daily bars, past sessions' 1-minute bars, today's 1-minute bars). After that every
refresh is ONE request (today's bars): the daily bars are kept for the day and the past sessions' chart
is kept per (instrument, interval). Responses are shared for 20 s between viewers. The live price comes
from the shared live feed (zero extra requests) once an instrument has been looked at.

Public-facing text never names the data source (see proprietary naming): every upstream failure is
turned into one generic message by the routes.
"""
import asyncio
import csv
import logging
import time
from collections import OrderedDict
from datetime import datetime, timedelta, timezone

import httpx

import exitline as ex

logger = logging.getLogger(__name__)

IST = timezone(timedelta(hours=5, minutes=30))
CM_URL = "https://public.fyers.in/sym_details/NSE_CM.csv"
FO_URL = "https://public.fyers.in/sym_details/NSE_FO.csv"
COLLECTION = "fyers_exitline_master"
FUT_TYPES = {"11", "13"}                 # FUTIDX, FUTSTK (column 2 of the symbol file)
OPT_TYPES = {"14", "15"}                 # OPTIDX, OPTSTK
CASH_EQ, CASH_INDEX = "0", "10"

RESPONSE_TTL = 20.0                      # seconds identical requests share one answer
QUOTE_TTL = 15.0
LIVE_MAX_AGE = 90                        # a feed price older than this is not "live"
WATCH_MAX = 20                           # instruments the live feed follows on behalf of Exitline viewers
WATCH_IDLE = 300                         # seconds without a request before an instrument leaves the feed
CACHE_ENTRIES = 12                       # instruments' daily bars / chart histories kept in memory
SESSION_OPEN_MINUTES = 9 * 60 + 15
DAILY_DAYS = 120                         # ~80 sessions: the 30 shown plus the day before the oldest; ONE request


class ExitlineError(Exception):
    """A problem whose text is safe to show the public (e.g. instrument not found)."""


def _iso_expiry(epoch) -> str:
    return datetime.fromtimestamp(int(epoch), IST).date().isoformat()


# ---------------------------------------------------------------------------
# Symbol files -> compact documents
# ---------------------------------------------------------------------------
def parse_cash(lines, out: dict) -> None:
    """out: name -> symbol. Stocks (-EQ series) win over an index of the same name."""
    for rec in csv.reader(lines):
        if len(rec) < 14:
            continue
        kind, symbol, name = rec[2], rec[9], rec[13]
        if kind == CASH_EQ and symbol.endswith("-EQ"):
            out[name] = symbol
        elif kind == CASH_INDEX and name:
            out.setdefault(name, symbol)


def parse_fo(lines, out: dict) -> None:
    """out: underlying -> {"fut": {expiry: symbol}, "opt": {expiry: {strike: [ce, pe]}}}."""
    for rec in csv.reader(lines):
        if len(rec) < 17:
            continue
        kind, symbol, und, opt = rec[2], rec[9], rec[13], rec[16]
        try:
            if kind in FUT_TYPES:
                expiry = _iso_expiry(rec[8])
                out.setdefault(und, {"fut": {}, "opt": {}})["fut"][expiry] = symbol
            elif kind in OPT_TYPES and opt in ("CE", "PE"):
                expiry = _iso_expiry(rec[8])
                pair = out.setdefault(und, {"fut": {}, "opt": {}})["opt"].setdefault(expiry, {}).setdefault(float(rec[15]), [None, None])
                pair[0 if opt == "CE" else 1] = symbol
        except (ValueError, OverflowError):
            continue


async def _stream(url: str, handler) -> None:
    async with httpx.AsyncClient(timeout=180) as c:
        async with c.stream("GET", url) as r:
            if r.status_code != 200:
                raise RuntimeError(f"symbol file returned HTTP {r.status_code}")
            lines = []
            async for line in r.aiter_lines():
                lines.append(line)
                if len(lines) >= 5000:                # constant memory: parse in slices
                    handler(lines)
                    lines = []
            handler(lines)


async def fetch_master() -> tuple:
    cash, fo = {}, {}
    await _stream(CM_URL, lambda lines: parse_cash(lines, cash))
    await _stream(FO_URL, lambda lines: parse_fo(lines, fo))
    if not cash or not fo:
        raise RuntimeError("symbol files held no instruments")
    return cash, fo


class MasterStore:
    """Reads (and once a day rebuilds) the compact instrument documents."""

    def __init__(self, db, fetcher=fetch_master, today=None):
        self.db = db
        self._fetch = fetcher
        self._today = today or (lambda: datetime.now(IST).date().isoformat())
        self._lock = asyncio.Lock()
        self._cash = None                 # (date, {name: symbol})
        self._index = None                # (date, {"FUT": [...], "OPT": [...]})
        self._fo: OrderedDict = OrderedDict()   # underlying -> (date, doc)

    async def _fresh(self) -> str:
        today = self._today()
        if self._index and self._index[0] == today:
            return today
        doc = await self.db[COLLECTION].find_one({"id": "index"}, {"_id": 0})
        if doc and doc.get("date") == today:
            self._index = (today, {"FUT": doc["FUT"], "OPT": doc["OPT"]})
            return today
        async with self._lock:
            doc = await self.db[COLLECTION].find_one({"id": "index"}, {"_id": 0})
            if doc and doc.get("date") == today:
                self._index = (today, {"FUT": doc["FUT"], "OPT": doc["OPT"]})
                return today
            try:
                await self._rebuild(today)
            except Exception as e:  # noqa: BLE001 -- yesterday's list beats no list
                logger.warning("Exitline instrument list refresh failed (%s)", e)
                if doc:
                    self._index = (today, {"FUT": doc["FUT"], "OPT": doc["OPT"]})
                    return doc["date"]
                raise ExitlineError("Instrument list is temporarily unavailable — please try again shortly.") from e
        return today

    async def _rebuild(self, today: str) -> None:
        cash, fo = await self._fetch()
        col = self.db[COLLECTION]
        await col.update_one({"id": "cash"}, {"$set": {"id": "cash", "date": today, "names": sorted([n, s] for n, s in cash.items())}}, upsert=True)
        for und, d in fo.items():
            opt = {exp: sorted([k, v[0], v[1]] for k, v in strikes.items()) for exp, strikes in d["opt"].items()}
            await col.update_one({"id": f"fo:{und}"}, {"$set": {"id": f"fo:{und}", "date": today, "fut": d["fut"], "opt": opt}}, upsert=True)
        index = {"FUT": sorted(u for u, d in fo.items() if d["fut"]), "OPT": sorted(u for u, d in fo.items() if d["opt"])}
        await col.update_one({"id": "index"}, {"$set": {"id": "index", "date": today, **index}}, upsert=True)
        await col.delete_many({"id": {"$regex": "^fo:"}, "date": {"$ne": today}})   # underlyings that no longer trade
        self._index, self._cash, self._fo = (today, index), (today, dict(cash)), OrderedDict()
        logger.info("Exitline instrument list refreshed: %d cash, %d derivative underlyings", len(cash), len(fo))

    async def _cash_map(self) -> dict:
        await self._fresh()
        if self._cash is None or self._cash[0] != self._index[0]:
            doc = await self.db[COLLECTION].find_one({"id": "cash"}, {"_id": 0})
            self._cash = (self._index[0], {n: s for n, s in (doc or {}).get("names", [])})
        return self._cash[1]

    async def _fo_doc(self, underlying: str):
        await self._fresh()
        hit = self._fo.get(underlying)
        if hit and hit[0] == self._index[0]:
            self._fo.move_to_end(underlying)
            return hit[1]
        doc = await self.db[COLLECTION].find_one({"id": f"fo:{underlying}"}, {"_id": 0})
        if doc:
            self._fo[underlying] = (self._index[0], doc)
            while len(self._fo) > 8:
                self._fo.popitem(last=False)
        return doc

    # ---- the four lookups the routes need (same results as the old master-file versions) ----
    async def list_symbols(self, segment: str, query: str = "") -> list:
        segment = segment.upper()
        if segment == "NSE":
            names = list((await self._cash_map()).keys())
        else:
            await self._fresh()
            names = list(self._index[1]["FUT" if segment == "FUT" else "OPT"])
        query = query.strip().upper()
        names = sorted(n.upper() for n in names)
        return [n for n in names if query in n][:100] if query else names[:100]

    async def list_expiries(self, segment: str, symbol: str) -> list:
        doc = await self._fo_doc(symbol.strip().upper())
        if not doc:
            return []
        return sorted((doc["fut"] if segment.upper() == "FUT" else doc["opt"]).keys())

    async def list_strikes(self, symbol: str, expiry: str) -> list:
        doc = await self._fo_doc(symbol.strip().upper())
        return sorted(r[0] for r in (doc or {}).get("opt", {}).get(expiry, []))

    async def resolve(self, segment: str, symbol: str, expiry=None, strike=None, option_type=None):
        """{"symbol": "NSE:...", "tradingsymbol": "..."} or None."""
        symbol, segment = symbol.strip().upper(), segment.upper()
        found = None
        if segment == "NSE":
            found = {k.upper(): v for k, v in (await self._cash_map()).items()}.get(symbol)
        else:
            doc = await self._fo_doc(symbol)
            if doc and expiry:
                if segment == "FUT":
                    found = doc["fut"].get(expiry)
                elif strike is not None and option_type:
                    side = 1 if option_type.strip().upper() == "CE" else 2
                    for row in doc["opt"].get(expiry, []):
                        if row[0] == float(strike):
                            found = row[side]
                            break
        return {"symbol": found, "tradingsymbol": found.split(":", 1)[-1]} if found else None


# ---------------------------------------------------------------------------
# Prices and history
# ---------------------------------------------------------------------------
def _rows(bars: list, interval: int) -> list:
    """Candles in the shape the chart reads, bucketed from 09:15 IST like the original."""
    out = []
    for b in ex._aggregate_bars(bars, interval):
        dt = datetime.strptime(b["ts"], "%d%m%Y%H%M").replace(tzinfo=IST)
        out.append({"t": dt.strftime("%H:%M"), "time": int(dt.timestamp()), "date": b["date"],
                    "open": b["open"], "high": b["high"], "low": b["low"], "close": b["close"]})
    return out


class _Lru(OrderedDict):
    def put(self, key, value):
        self[key] = value
        self.move_to_end(key)
        while len(self) > CACHE_ENTRIES:
            self.popitem(last=False)


class ExitlineData:
    def __init__(self, client, feed, now=None, clock=time.monotonic):
        self.client, self.feed = client, feed
        self._now = now or (lambda: datetime.now(IST))
        self._clock = clock
        self._daily = _Lru()        # symbol -> (date, bars)
        self._past = _Lru()         # (symbol, interval) -> (date, first_session_date, rows)
        self._quote = {}            # symbol -> (clock, price)
        self._resp = _Lru()         # request key -> (clock, payload)
        self._watch = {}            # symbol -> last requested (clock)

    # ---- live price ---------------------------------------------------------------------
    def _touch(self, symbol: str) -> None:
        """Follow this instrument on the shared live feed (one request covers up to 50 symbols)."""
        if self.feed is None:
            return
        now = self._clock()
        self._watch[symbol] = now
        for s in [s for s, t in self._watch.items() if now - t > WATCH_IDLE]:
            del self._watch[s]
            self.feed.remove([s])
        self.feed.pinned = set(self._watch)
        if symbol not in self.feed.symbols and len(self._watch) <= WATCH_MAX and len(self.feed.symbols) < 50:
            self.feed.add([symbol])

    async def live_price(self, symbol: str):
        self._touch(symbol)
        v = self.feed.latest.get(symbol) if self.feed is not None else None
        if v is not None:
            try:
                age = (self._now() - datetime.fromisoformat(v["at"])).total_seconds()
            except (KeyError, ValueError):
                age = LIVE_MAX_AGE + 1
            if age <= LIVE_MAX_AGE:
                return float(v["ltp"])
        hit = self._quote.get(symbol)
        if hit and self._clock() - hit[0] < QUOTE_TTL:
            return hit[1]
        price = await self.client.ltp(symbol)
        self._quote[symbol] = (self._clock(), price)
        return price

    # ---- history -----------------------------------------------------------------------
    async def daily(self, symbol: str) -> list:
        today = self._now().date().isoformat()
        hit = self._daily.get(symbol)
        if hit and hit[0] == today:
            return hit[1]
        bars = await self.client.daily_history(symbol, days=DAILY_DAYS)
        self._daily.put(symbol, (today, bars))
        return bars

    async def chart(self, symbol: str, sessions: list, interval: int) -> list:
        """Past sessions (cached per instrument+interval for the day) + today's bars (one request)."""
        now = self._now()
        today = now.date().isoformat()
        first = sessions[0]["date"]
        key = (symbol, interval)
        hit = self._past.get(key)
        if hit is None or hit[0] != today or hit[1] > first:
            start = datetime.strptime(first, "%Y-%m-%d").replace(tzinfo=IST)
            end = datetime.strptime(today, "%Y-%m-%d").replace(tzinfo=IST) - timedelta(seconds=1)
            bars = await self.client.minute_ohlc(symbol, start, end) if start < end else []
            hit = (today, first, _rows(bars, interval))
            self._past.put(key, hit)
        rows = hit[2]
        if (now.hour, now.minute) >= (9, 15):
            frm = datetime.strptime(today, "%Y-%m-%d").replace(tzinfo=IST)
            rows = rows + _rows(await self.client.minute_ohlc(symbol, frm, now), interval)
        return rows

    # ---- the response ---------------------------------------------------------------------
    async def build(self, resolved: dict, meta: dict, interval: int) -> dict:
        symbol = resolved["symbol"]
        key = (symbol, interval)
        hit = self._resp.get(key)
        if hit and self._clock() - hit[0] < RESPONSE_TTL:
            return {**hit[1], **meta}
        now = self._now()
        sessions = ex.build_session_ladder(await self.daily(symbol), now, session_open_minutes=SESSION_OPEN_MINUTES)
        if not sessions:
            raise ExitlineError("No previous-day data for this instrument (illiquid or newly-listed contract?).")
        active = sessions[-1]
        ltp_or_exc, chart = await asyncio.gather(self.live_price(symbol), self.chart(symbol, sessions, interval), return_exceptions=True)
        chart_failed = isinstance(chart, BaseException)
        if chart_failed:
            logger.warning("Exitline: chart unavailable for %s: %s", symbol, chart)
            chart = []
        if isinstance(ltp_or_exc, BaseException):
            if isinstance(ltp_or_exc, asyncio.CancelledError):
                raise ltp_or_exc
            logger.warning("Exitline: live price unavailable for %s: %s", symbol, ltp_or_exc)
            ltp = None
            zone = {"zone": None, "zone_label": "Live Price Unavailable", "bias": "Neutral", "sl": None, "tp": None,
                    "tp_alt": None, "trail_stop": False,
                    "reason": "No live quote right now (market may be closed) — levels are still shown "
                              "against yesterday's close; zone/SL/TP need a live price.",
                    "commentary": None}
        else:
            ltp = ltp_or_exc
            zone = ex.classify_and_suggest(active["levels"], ltp, active["close"])
        payload = {"tradingsymbol": resolved["tradingsymbol"], "prev_date": active["prev_date"], "high": active["high"],
                   "low": active["low"], "close": active["close"], "levels": active["levels"], "active_date": active["date"],
                   "sessions": sessions, "ltp": ltp, "chart": chart, **zone}
        if not chart_failed:                      # a failed chart is retried on the next request, never shared
            self._resp.put(key, (self._clock(), payload))
        return {**payload, **meta}
