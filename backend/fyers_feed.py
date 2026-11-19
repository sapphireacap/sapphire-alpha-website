"""Live prices from FYERS by polling the quotes endpoint, plus 1-minute bars built from them.

WHY POLLING, NOT THE WEBSOCKET (decided 2026-11-19, on purpose): the free plan's REST allowance is
5,000 data calls a day and one quotes call returns up to 50 symbols. Polling every 15 s through
the 6.25 h NSE session is ~1,500 calls (about 30% of the day, 4 per minute against a limit of 50),
and the strategies here sample ONE CLOSE PER MINUTE anyway, so a 15 s sample loses nothing they
use. FYERS' WebSocket is a custom binary protocol (the official package that implements it pins
old library versions that clash with this backend) and can only be verified while the market is
open. If tick-level data is ever needed, add it as a separate feed; this one stays as the fallback.

Budget behaviour (see fyers_budget): the poll interval stretches by itself as the day's allowance is
used (60 s past 3,500 calls) and stops polling past 4,200, so history and option-chain calls always
have room. Nothing here ever raises into the caller: errors are counted, logged once in a while,
and the loop backs off.

Ticks are handed to callbacks as {"t": "tf", "e": "FYERS", "tk": "<symbol>", "lp": "<price>"},
and finished 1-minute bars as {"ts": "ddmmyyyyHHMM", "dt": aware-IST datetime, open, high, low,
close}, the same shapes the rest of the backend already consumes.
"""
import asyncio
import logging
import os
import time
from collections import deque
from datetime import datetime, timedelta, timezone

import fyers_auth
from fyers_budget import FyersBudgetError, budget as default_budget
from fyers_client import FyersError, FyersRateLimited

logger = logging.getLogger(__name__)

IST = timezone(timedelta(hours=5, minutes=30))
MAX_SYMBOLS = 50              # one quotes request
BARS_KEPT = 400               # about one session of 1-minute bars per symbol
SLOW_AFTER = 3500             # calls used today: stretch the interval
STOP_AFTER = 4200             # calls used today: stop polling
SLOW_INTERVAL = 60


def _base_interval() -> float:
    try:
        return max(5.0, float(os.environ.get("FYERS_FEED_INTERVAL", 15)))
    except ValueError:
        return 15.0


class FyersFeed:
    def __init__(self, client, is_open, budget=None, interval: float = None, now=None, sleep=asyncio.sleep,
                 slow_after: int = SLOW_AFTER, stop_after: int = STOP_AFTER):
        self.client = client
        self.slow_after, self.stop_after = slow_after, stop_after     # a lower-priority feed gives up sooner than the core one
        self.is_open = is_open                    # callable(datetime_ist) -> bool
        self.budget = budget or default_budget
        self.base_interval = interval or _base_interval()
        self._now = now or (lambda: datetime.now(IST))
        self._sleep = sleep
        self.symbols: list = []
        self.pinned: set = set()                  # symbols other modules (Exitline) follow; the Index Vector runner must not evict them
        self.latest: dict = {}                    # symbol -> {"ltp", "at"}
        self.bars: dict = {}                      # symbol -> deque of completed 1-minute bars
        self._open_bar: dict = {}                 # symbol -> in-progress bar
        self._tick_cbs: list = []
        self._bar_cbs: list = []
        self._task = None
        self._stopping = False
        self._was_open = False
        self.polls = 0
        self.errors = 0
        self.last_error = None
        self.last_poll_at = None

    # ---- registration ------------------------------------------------------------------
    def add(self, symbols) -> list:
        """Registers symbols; returns the ones newly added. Refuses to exceed MAX_SYMBOLS (one request)."""
        fresh = [s for s in dict.fromkeys(symbols) if s not in self.symbols]
        if len(self.symbols) + len(fresh) > MAX_SYMBOLS:
            raise ValueError(f"FYERS feed is limited to {MAX_SYMBOLS} symbols (one quotes request); "
                             f"have {len(self.symbols)}, tried to add {len(fresh)}.")
        self.symbols.extend(fresh)
        return fresh

    def remove(self, symbols) -> None:
        self.symbols = [s for s in self.symbols if s not in set(symbols)]

    def on_tick(self, cb) -> None:
        self._tick_cbs.append(cb)

    def on_bar(self, cb) -> None:
        self._bar_cbs.append(cb)

    # ---- one poll ----------------------------------------------------------------------
    async def poll_once(self) -> int:
        """One quotes request for every registered symbol. Returns how many prices were updated."""
        if not self.symbols:
            return 0
        quotes = await self.client.quotes(list(self.symbols))
        now = self._now()
        self.polls += 1
        self.last_poll_at = now.isoformat()
        updated = 0
        for symbol in self.symbols:
            q = quotes.get(symbol)
            if not q or q.get("ltp") is None:
                continue
            price = float(q["ltp"])
            self.latest[symbol] = {"ltp": price, "at": now.isoformat(), "open": q.get("open"), "high": q.get("high"),
                                   "low": q.get("low"), "prev_close": q.get("prev_close")}
            self._sample(symbol, price, now)
            self._emit(self._tick_cbs, {"t": "tf", "e": "FYERS", "tk": symbol, "lp": f"{price:.2f}"})
            updated += 1
        return updated

    # ---- 1-minute bars from samples --------------------------------------------------------
    def _sample(self, symbol: str, price: float, now: datetime) -> None:
        minute = now.replace(second=0, microsecond=0)
        cur = self._open_bar.get(symbol)
        if cur is not None and cur["dt"] == minute:
            cur["high"], cur["low"], cur["close"] = max(cur["high"], price), min(cur["low"], price), price
            return
        if cur is not None:
            self._finish(symbol, cur)
        self._open_bar[symbol] = {"ts": minute.strftime("%d%m%Y%H%M"), "dt": minute,
                                  "open": price, "high": price, "low": price, "close": price}

    def _finish(self, symbol: str, bar: dict) -> None:
        self.bars.setdefault(symbol, deque(maxlen=BARS_KEPT)).append(bar)
        self._emit(self._bar_cbs, symbol, dict(bar))

    def flush(self) -> None:
        """Finish every in-progress bar (at the close of the session, or on shutdown)."""
        for symbol, bar in list(self._open_bar.items()):
            self._finish(symbol, bar)
        self._open_bar.clear()

    @staticmethod
    def _emit(callbacks, *args) -> None:
        for cb in list(callbacks):
            try:
                cb(*args)
            except Exception:  # noqa: BLE001 -- one bad subscriber must never stop the feed
                logger.exception("FYERS feed callback failed")

    # ---- scheduling --------------------------------------------------------------------
    def effective_interval(self) -> float:
        used = self.budget.snapshot()["used_today"]
        return max(self.base_interval, SLOW_INTERVAL) if used >= self.slow_after else self.base_interval

    def budget_exhausted(self) -> bool:
        return self.budget.snapshot()["used_today"] >= self.stop_after

    async def _run(self) -> None:
        while not self._stopping:
            now = self._now()
            open_now = bool(self.is_open(now)) and fyers_auth.enabled()
            if self._was_open and not open_now:
                self.flush()                                  # the session just ended: close the last minute
            self._was_open = open_now
            if not open_now or not self.symbols or self.budget_exhausted():
                await self._sleep(30)
                continue
            try:
                await self.poll_once()
                wait = self.effective_interval()
            except FyersRateLimited as e:
                self._note(e)
                wait = 60
            except FyersBudgetError as e:
                self._note(e)
                wait = 60
            except fyers_auth.FyersAuthError as e:
                self._note(e)
                wait = 120                                    # the login code has its own cooldown; don't add to it
            except FyersError as e:
                self._note(e)
                wait = 30
            except Exception as e:  # noqa: BLE001 -- keep the feed alive through anything unexpected
                self._note(e)
                wait = 30
            await self._sleep(wait)

    def _note(self, e: Exception) -> None:
        self.errors += 1
        self.last_error = f"{type(e).__name__}: {e}"[:300]
        if self.errors == 1 or self.errors % 20 == 0:        # not on every failed poll
            logger.warning("FYERS feed: %s (error #%d)", self.last_error, self.errors)

    def start(self) -> None:
        if self._task is None or self._task.done():
            self._stopping = False
            self._task = asyncio.ensure_future(self._run())

    async def stop(self) -> None:
        self._stopping = True
        self.flush()
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass

    # ---- admin view --------------------------------------------------------------------
    def snapshot(self) -> dict:
        return {"running": bool(self._task and not self._task.done()), "symbols": list(self.symbols),
                "interval_seconds": self.effective_interval(), "polls": self.polls, "errors": self.errors,
                "last_error": self.last_error, "last_poll_at": self.last_poll_at,
                "prices": {s: v["ltp"] for s, v in self.latest.items()},
                "bars_kept": {s: len(b) for s, b in self.bars.items()}, "budget": self.budget.snapshot()}
