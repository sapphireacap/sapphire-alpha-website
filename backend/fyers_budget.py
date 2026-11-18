"""Request budget for FYERS' Data APIs, enforced BEFORE a call is made.

FYERS Standard (free) plan, Data APIs: 5 requests/second, 50/minute, 5,000/day.
Exceeding the per-minute limit more than 3 times in a day blocks the account for
the rest of that day (https://fyers.in/api-docs/v3/getting-started/plans-and-limits/).
A blocked day means no data at all, so this module refuses a call rather than let a
bug or a burst of visitors get that far. Limits are set below the real ceilings:

  per second  4   (limit 5)    -> a call WAITS a moment, never fails
  per minute  40  (limit 50)   -> raises FyersBudgetError at once (never wait on a request)
  per day     4500 (limit 5000) -> raises FyersBudgetError

Override with FYERS_MAX_PER_SECOND / FYERS_MAX_PER_MINUTE / FYERS_MAX_PER_DAY, but never
above the plan's real limits. The day's count is saved to Mongo every few calls and
restored on startup, so a restart cannot reset the counter mid-day (counted per IST day).

Only DATA REST calls count here. The live WebSocket has its own limit (100 symbols on
Standard), which fyers_client enforces separately.
"""
import asyncio
import os
import time
from collections import deque
from datetime import datetime, timedelta, timezone

IST = timezone(timedelta(hours=5, minutes=30))
PLAN_LIMITS = {"second": 5, "minute": 50, "day": 5000}


class FyersBudgetError(Exception):
    """The call was refused to protect the daily/minute allowance. Safe to show a caller."""


def _limit(env_name: str, default: int, plan: int) -> int:
    try:
        v = int(os.environ.get(env_name, default))
    except ValueError:
        v = default
    return max(1, min(v, plan))   # never above the plan's real ceiling


class Budget:
    def __init__(self, clock=time.monotonic, today=None, sleep=asyncio.sleep):
        self.per_second = _limit("FYERS_MAX_PER_SECOND", 4, PLAN_LIMITS["second"])
        self.per_minute = _limit("FYERS_MAX_PER_MINUTE", 40, PLAN_LIMITS["minute"])
        self.per_day = _limit("FYERS_MAX_PER_DAY", 4500, PLAN_LIMITS["day"])
        self._clock = clock
        self._today = today or (lambda: datetime.now(IST).date().isoformat())
        self._sleep = sleep
        self._sec: deque = deque()
        self._min: deque = deque()
        self.day = self._today()
        self.count = 0
        self._unsaved = 0
        self._loaded = False
        self._lock = asyncio.Lock()

    def _roll(self) -> None:
        today = self._today()
        if today != self.day:
            self.day, self.count, self._unsaved, self._loaded = today, 0, 0, False

    async def _restore(self, db) -> None:
        if db is None or self._loaded:
            return
        doc = await db.fyers_budget.find_one({"date": self.day}, {"_id": 0, "count": 1})
        if doc:
            self.count = max(self.count, int(doc.get("count", 0)))
        self._loaded = True

    async def _save(self, db) -> None:
        if db is None:
            return
        await db.fyers_budget.update_one({"date": self.day}, {"$set": {"date": self.day, "count": self.count}}, upsert=True)
        self._unsaved = 0

    async def acquire(self, db=None) -> None:
        """Reserves one call. Waits (briefly) for the per-second limit; raises
        FyersBudgetError for the per-minute and per-day limits."""
        async with self._lock:
            self._roll()
            await self._restore(db)
            if self.count >= self.per_day:
                raise FyersBudgetError(f"FYERS daily request budget used up ({self.count}/{self.per_day}); resumes tomorrow.")
            now = self._clock()
            while self._min and now - self._min[0] >= 60:
                self._min.popleft()
            if len(self._min) >= self.per_minute:
                raise FyersBudgetError(f"FYERS per-minute budget reached ({self.per_minute}/min); try again shortly.")
            while True:
                now = self._clock()
                while self._sec and now - self._sec[0] >= 1.0:
                    self._sec.popleft()
                if len(self._sec) < self.per_second:
                    break
                await self._sleep(max(0.01, 1.0 - (now - self._sec[0])))
            stamp = self._clock()
            self._sec.append(stamp)
            self._min.append(stamp)
            self.count += 1
            self._unsaved += 1
            if self._unsaved >= 10:
                await self._save(db)

    async def flush(self, db) -> None:
        await self._save(db)

    def snapshot(self) -> dict:
        self._roll()
        now = self._clock()
        return {"date": self.day, "used_today": self.count, "day_limit": self.per_day,
                "last_minute": sum(1 for t in self._min if now - t < 60), "minute_limit": self.per_minute}


budget = Budget()   # one per process
