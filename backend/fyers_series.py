"""1-minute close history for the option contracts Index Vector reads, held compactly.

A P&F chart runs on a contract's WHOLE life (a monthly contract is ~90 days, ~25,000 one-minute
bars), and Index Vector reads ~22 contracts. As Python dicts that is tens of MB and a lot of garbage per
recompute, on a server with a 512 MB ceiling. So each contract is two flat arrays (epoch-minutes as
int64, close as float64, 16 bytes a bar, ~400 KB a contract), and the series the unchanged P&F code
iterates are LAZY views that only build the few dicts actually asked for.

How a series is kept current while spending as little of the 5,000-calls-a-day free allowance as possible:
  * first sight of a contract: ONE history request (the last 94 days: one request returns up to ~100 days)
  * after that: the live feed's finished minute bars are appended (no requests at all)
  * a series that falls >3 minutes behind during the session (a feed gap, a restart) is topped up with one
    request, at most once per 10 minutes per contract
  * saved to Mongo (`fyers_series_cache`, zlib) every few minutes, so a restart or a deploy costs one
    small tail request per contract instead of a full download
"""
import logging
import zlib
from array import array
from datetime import datetime, timedelta, timezone

from bson import Binary

logger = logging.getLogger(__name__)

IST = timezone(timedelta(hours=5, minutes=30))
CACHE_COLLECTION = "fyers_series_cache"
WINDOW_DAYS = 94                       # one history request returns up to ~100 days (130 was refused, -50)
GAP_MINUTES = 3
TOPUP_EVERY = timedelta(minutes=10)
UNUSED_DROP = timedelta(hours=2)       # series nobody asked for in this long are dropped from memory


def minute_of(dt: datetime) -> int:
    return int(dt.timestamp() // 60)


def minute_of_ts(ts: str) -> int:
    """From the 'ddmmyyyyHHMM' stamps the history bars carry (day-first: never sort these as strings)."""
    return minute_of(datetime.strptime(ts, "%d%m%Y%H%M").replace(tzinfo=IST))


class Series:
    __slots__ = ("ts", "px", "dirty", "topup_at", "used_at")

    def __init__(self):
        self.ts = array("q")
        self.px = array("d")
        self.dirty = False
        self.topup_at = None
        self.used_at = None

    def __len__(self) -> int:
        return len(self.ts)

    def last_minute(self):
        return self.ts[-1] if self.ts else None

    def set_bar(self, minute: int, close: float) -> bool:
        """Append a finished minute (or refresh the newest one). Older minutes are ignored."""
        if self.ts and minute == self.ts[-1]:
            if self.px[-1] != close:
                self.px[-1] = close
                self.dirty = True
            return True
        if self.ts and minute < self.ts[-1]:
            return False
        self.ts.append(minute)
        self.px.append(float(close))
        self.dirty = True
        return True

    def pack(self) -> dict:
        return {"n": len(self.ts), "ts_z": Binary(zlib.compress(self.ts.tobytes())), "px_z": Binary(zlib.compress(self.px.tobytes()))}

    @classmethod
    def from_doc(cls, doc: dict) -> "Series":
        s = cls()
        s.ts.frombytes(zlib.decompress(bytes(doc["ts_z"])))
        s.px.frombytes(zlib.decompress(bytes(doc["px_z"])))
        if len(s.ts) != len(s.px):
            raise ValueError("cached series is corrupt (length mismatch)")
        return s


class LazySeries:
    """The list-of-{"t","v"} the P&F code expects, without building it: iterating yields dicts one at a
    time, slicing builds only the slice, len() is free."""

    def __init__(self, ts: array, px: array):
        self._ts, self._px = ts, px
        same_day = (not ts) or (datetime.fromtimestamp(ts[0] * 60, IST).date() == datetime.fromtimestamp(ts[-1] * 60, IST).date())
        self._fmt = "%H:%M" if same_day else "%d/%m %H:%M"      # a multi-day chart needs the date

    def _item(self, i: int) -> dict:
        return {"t": datetime.fromtimestamp(self._ts[i] * 60, IST).strftime(self._fmt), "v": self._px[i]}

    def __len__(self) -> int:
        return len(self._ts)

    def __iter__(self):
        for i in range(len(self._ts)):
            yield self._item(i)

    def __getitem__(self, k):
        if isinstance(k, slice):
            return [self._item(i) for i in range(*k.indices(len(self._ts)))]
        return self._item(k if k >= 0 else len(self._ts) + k)


def single(s: Series) -> LazySeries:
    return LazySeries(s.ts[:], s.px[:])             # a copy: the feed may append while a compute is in flight


def straddle(a: Series, b: Series) -> LazySeries:
    """Per-minute CE close + PE close over the minutes BOTH traded (a two-pointer merge of two sorted arrays)."""
    ts, px = array("q"), array("d")
    i = j = 0
    ats, bts, apx, bpx = a.ts, b.ts, a.px, b.px
    na, nb = len(ats), len(bts)
    while i < na and j < nb:
        x, y = ats[i], bts[j]
        if x == y:
            ts.append(x)
            px.append(apx[i] + bpx[j])
            i += 1
            j += 1
        elif x < y:
            i += 1
        else:
            j += 1
    return LazySeries(ts, px)


class SeriesStore:
    def __init__(self, db, client, now=None):
        self.db = db
        self.client = client
        self._now = now or (lambda: datetime.now(IST))
        self.series: dict = {}
        self.requests = 0

    async def _load_cache(self, symbol: str):
        doc = await self.db[CACHE_COLLECTION].find_one({"symbol": symbol}, {"_id": 0})
        if not doc:
            return None
        try:
            return Series.from_doc(doc)
        except Exception as e:  # noqa: BLE001 -- a bad cache entry just means one fresh download
            logger.warning("FYERS series cache for %s unusable (%s); refetching.", symbol, e)
            return None

    async def ensure(self, symbol: str) -> Series:
        """The series for a contract, topped up if it is empty or has fallen behind. At most one history
        request, and only when needed."""
        now = self._now()
        cur_min = minute_of(now)
        s = self.series.get(symbol)
        if s is None:
            s = await self._load_cache(symbol) or Series()
            self.series[symbol] = s
        s.used_at = now
        last = s.last_minute()
        behind = last is None or (cur_min - last > GAP_MINUTES and (s.topup_at is None or now - s.topup_at >= TOPUP_EVERY))
        if behind:
            s.topup_at = now
            frm = now - timedelta(days=WINDOW_DAYS) if last is None else datetime.fromtimestamp((last + 1) * 60, IST)
            self.requests += 1
            for bar in await self.client.minute_ohlc(symbol, frm, now):
                m = minute_of_ts(bar["ts"])
                if m < cur_min:                          # never the in-progress minute: the feed finishes that one
                    s.set_bar(m, bar["close"])
        return s

    def on_bar(self, symbol: str, bar: dict) -> None:
        """Feed callback: a finished minute for a watched symbol."""
        s = self.series.get(symbol)
        if s is not None:
            s.set_bar(minute_of(bar["dt"]), bar["close"])

    def prune(self) -> int:
        """Drop series nobody has asked for in UNUSED_DROP (they stay in the Mongo cache)."""
        now = self._now()
        gone = [k for k, s in self.series.items() if s.used_at and now - s.used_at > UNUSED_DROP and not s.dirty]
        for k in gone:
            del self.series[k]
        return len(gone)

    async def persist(self) -> int:
        saved = 0
        for symbol, s in list(self.series.items()):
            if s.dirty and len(s):
                await self.db[CACHE_COLLECTION].update_one(
                    {"symbol": symbol}, {"$set": {"symbol": symbol, **s.pack(), "updated_at": self._now().isoformat()}}, upsert=True)
                s.dirty = False
                saved += 1
        return saved

    async def prune_cache(self, days: int = 14) -> None:
        """Contracts expire; their cached history is useless after a while."""
        cutoff = (self._now() - timedelta(days=days)).isoformat()
        await self.db[CACHE_COLLECTION].delete_many({"updated_at": {"$lt": cutoff}})
