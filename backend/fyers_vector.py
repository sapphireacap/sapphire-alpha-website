"""Index Vector on FYERS data.

DefinedgeService.compute_vector() holds ALL of Index Vector's logic (the P&F legs, the confluence rule,
the flip levels, what gets saved). It reads its inputs through a handful of methods; this subclass
answers those from FYERS instead and changes nothing else, so Definedge's behaviour and every rule stay
exactly as they were:

  _spot                      latest index price from the live feed (REST quote only as a fallback)
  _get_all_master            the FYERS option-contract list in the old master's column layout
  _straddle_series / _single_leg_series
                             lazy views over the compact in-memory 1-minute series (fyers_series)
  equity_quote               a leg's live price from the feed
  _market_iv_strikes         REAL implied volatility from FYERS' option chain (per expiry), so the flip
                             levels use the market's IV instead of an estimate

FyersVectorRunner keeps it current: once a minute during the NSE session it makes sure every needed
contract has its series and is on the live feed, recomputes the three indices, and writes the history row
only when the bias changes or every 5th minute (so the database grows as it always did, not 5x faster).
Spend per day (free plan, 5,000 requests): feed ~1,500 + option chains ~600 + history ~60.
"""
import asyncio
import logging
import time
from datetime import datetime, timedelta, timezone

import fyers_master
import fyers_series
from definedge_service import DefinedgeService, INDEX_CONFIG
from fyers_client import FyersError, INDEX_SYMBOLS

logger = logging.getLogger(__name__)

IST = timezone(timedelta(hours=5, minutes=30))
CHAIN_TTL = 120                    # seconds a chain's IVs are reused
CHAIN_STRIKES = 8                  # strikes each side of the money: covers ATM +/- 200 on all three indices
LIVE_MAX_AGE = 180                 # a feed price older than this is not trusted as "live"
HISTORY_EVERY_MINUTES = 5


class FyersVectorService(DefinedgeService):
    SOURCE = "fyers"

    def __init__(self, db, client, feed, store):
        super().__init__(db, "", "")             # no Definedge credentials: every data method is overridden below
        self.client, self.feed, self.store = client, feed, store
        self._frame = None                        # (iso date, DataFrame)
        self._chains: dict = {}                   # (index, expiry iso) -> (monotonic, strikes)
        self._expiry_ts: dict = {}                # index -> {expiry iso: epoch}

    # ---- the inputs compute_vector() reads ---------------------------------------------------
    async def _spot(self, index_key: str = "NIFTY") -> float:
        sym = INDEX_SYMBOLS[index_key]
        v = self.feed.latest.get(sym)
        if v is not None:
            return float(v["ltp"])
        return await self.client.ltp(sym)

    async def _get_all_master(self):
        today = datetime.now(IST).date().isoformat()
        if self._frame and self._frame[0] == today:
            return self._frame[1]
        frame = fyers_master.as_definedge_frame(await fyers_master.get_rows(self.db, today))
        self._frame = (today, frame)
        return frame

    def _series_for(self, symbol: str):
        s = self.store.series.get(symbol)
        if s is None or not len(s):
            raise FyersError(f"No price history loaded for {symbol} yet.")
        return s

    async def _straddle_series(self, ce_token: str, pe_token: str, segment: str = "NFO"):
        return fyers_series.straddle(self._series_for(ce_token), self._series_for(pe_token))

    async def _single_leg_series(self, token: str, segment: str = "NFO"):
        return fyers_series.single(self._series_for(token))

    async def equity_quote(self, segment: str, token: str) -> float:
        """A leg's current premium: the live feed's price, else the newest 1-minute close we hold."""
        v = self.feed.latest.get(token)
        if v is not None:
            return float(v["ltp"])
        s = self.store.series.get(token)
        if s is not None and len(s):
            return float(s.px[-1])
        return await self.client.ltp(token)

    # ---- real IV from the option chain -----------------------------------------------------------
    async def _expiry_epoch(self, index_key: str, expiry_iso: str):
        known = self._expiry_ts.get(index_key)
        if known is None or expiry_iso not in known:
            base = await self.client.option_chain(INDEX_SYMBOLS[index_key], strikecount=1, greeks=False)
            known = {}
            for e in base.get("expiries") or []:
                try:
                    d, m, y = e["date"].split("-")
                    known[f"{y}-{m}-{d}"] = e["expiry"]
                except (KeyError, ValueError):
                    continue
            self._expiry_ts[index_key] = known
        return known.get(expiry_iso)

    async def _market_iv_strikes(self, index_key: str, expiry_iso: str) -> dict:
        key = (index_key, expiry_iso)
        hit = self._chains.get(key)
        if hit and time.monotonic() - hit[0] < CHAIN_TTL:
            return hit[1]
        try:
            ts = await self._expiry_epoch(index_key, expiry_iso)
            if ts is None:
                return {}
            chain = await self.client.option_chain(INDEX_SYMBOLS[index_key], strikecount=CHAIN_STRIKES, greeks=True, expiry_ts=ts)
            strikes = chain["strikes"]
        except Exception as e:  # noqa: BLE001 -- IV is an upgrade, never a dependency (legs fall back to their own solve)
            logger.info("Index Vector: market IV unavailable for %s %s (%s)", index_key, expiry_iso, e)
            return {}
        self._chains[key] = (time.monotonic(), strikes)
        return strikes

    # ---- preparation: make sure every leg has its series ------------------------------------------
    @staticmethod
    def leg_symbols(tokens: dict) -> list:
        out = []
        for legs in (tokens["monthly"]["legs"]["up"], tokens["monthly"]["legs"]["down"], tokens["monthly_atm"]["leg"]):
            out += [legs["CE"], legs["PE"]]
        if "weekly" in tokens:
            for side in ("up", "down"):
                out += [tokens["weekly"]["legs"][side]["CE"], tokens["weekly"]["legs"][side]["PE"]]
        return out

    async def prepare(self, index_key: str) -> list:
        """The contract symbols this index needs RIGHT NOW (they follow the ATM), each with its series loaded."""
        spot, df = await self._spot(index_key), await self._get_all_master()
        tokens = self._resolve_tokens(df, int(round(spot / 100.0) * 100), index_key)
        symbols = self.leg_symbols(tokens)
        for s in symbols:
            await self.store.ensure(s)
        return symbols


class FyersVectorRunner:
    CYCLE_SECOND = 20             # run this many seconds into each minute, after the previous minute's bar has closed
    PERSIST_EVERY = 5             # cycles between saves of the series cache

    def __init__(self, service, feed, store, is_open, indices=("NIFTY", "BANKNIFTY", "FINNIFTY"), now=None, sleep=asyncio.sleep):
        self.service, self.feed, self.store, self.is_open = service, feed, store, is_open
        self.indices = tuple(indices)
        self._now = now or (lambda: datetime.now(IST))
        self._sleep = sleep
        self.last_bias: dict = {}
        self.last_ok: dict = {}
        self.errors: dict = {}
        self.last_error = None
        self.cycles = 0
        self._needed: dict = {}                       # index -> symbols needed at the last cycle
        self._task = None
        self._stopping = False

    # ---- live-feed registration with a hard cap -------------------------------------------------------
    def _register(self) -> None:
        keep = set(INDEX_SYMBOLS.values())
        needed = set(keep)
        for syms in self._needed.values():
            needed.update(syms)
        missing = [s for s in sorted(needed) if s not in self.feed.symbols]
        room = 50 - len(self.feed.symbols)
        if len(missing) > room:                       # make room by dropping symbols no longer needed
            stale = [s for s in self.feed.symbols if s not in needed]
            self.feed.remove(stale[: len(missing) - room])
        room = 50 - len(self.feed.symbols)
        if missing:
            self.feed.add(missing[:max(room, 0)])

    def _history_due(self, index_key: str, bias, now: datetime) -> bool:
        return bias != self.last_bias.get(index_key) or now.minute % HISTORY_EVERY_MINUTES == 0

    async def cycle(self) -> None:
        now = self._now()
        for index_key in self.indices:
            try:
                self._needed[index_key] = await self.service.prepare(index_key)
                self._register()
                # bias is known only after computing; write history when it changes OR on the 5-minute beat
                signal = await self.service.compute_vector(index_key, write_history=(now.minute % HISTORY_EVERY_MINUTES == 0))
                bias = signal.get("bias")
                if bias != self.last_bias.get(index_key) and now.minute % HISTORY_EVERY_MINUTES != 0:
                    await self._write_history_row(signal)         # a change must not wait for the next 5-minute beat
                self.last_bias[index_key] = bias
                self.last_ok[index_key] = now.isoformat()
                self.errors.pop(index_key, None)
            except Exception as e:  # noqa: BLE001 -- one index failing must not stop the others
                self.errors[index_key] = f"{type(e).__name__}: {e}"[:300]
                self.last_error = self.errors[index_key]
                logger.warning("Index Vector (FYERS) %s: %s", index_key, self.last_error)
        self.cycles += 1
        if self.cycles % self.PERSIST_EVERY == 0:
            await self.store.persist()
            self.store.prune()

    async def _write_history_row(self, signal: dict) -> None:
        import uuid
        row = dict(signal)
        row.pop("chart", None)
        row["id"] = str(uuid.uuid4())
        db = self.service.db
        await db.index_signal_history.insert_one(row)
        if signal.get("index") == "NIFTY":
            legacy = dict(row)
            legacy["id"] = str(uuid.uuid4())
            await db.nifty_signal_history.insert_one(legacy)

    async def _run(self) -> None:
        await self.store.prune_cache()
        while not self._stopping:
            now = self._now()
            wait = (60 - now.second) + self.CYCLE_SECOND if now.second >= self.CYCLE_SECOND else self.CYCLE_SECOND - now.second
            await self._sleep(wait)
            if self._stopping:
                break
            if not self.is_open(self._now()):
                continue
            try:
                await self.cycle()
            except Exception as e:  # noqa: BLE001
                self.last_error = f"{type(e).__name__}: {e}"[:300]
                logger.exception("Index Vector (FYERS) cycle failed")

    def start(self) -> None:
        if self._task is None or self._task.done():
            self._stopping = False
            self.feed.on_bar(self.store.on_bar)
            self._task = asyncio.ensure_future(self._run())

    async def stop(self) -> None:
        self._stopping = True
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
        try:
            await self.store.persist()
        except Exception:  # noqa: BLE001
            logger.exception("Could not save the FYERS series cache on shutdown")

    def snapshot(self) -> dict:
        return {"running": bool(self._task and not self._task.done()), "cycles": self.cycles, "last_bias": dict(self.last_bias),
                "last_ok": dict(self.last_ok), "errors": dict(self.errors), "series_in_memory": len(self.store.series),
                "series_requests": self.store.requests, "feed_symbols": len(self.feed.symbols)}


__all__ = ["FyersVectorService", "FyersVectorRunner", "INDEX_CONFIG"]
