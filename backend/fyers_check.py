"""First-run check for the FYERS integration. Run from backend/ after the FYERS_* settings
are in backend/.env:

    python fyers_check.py

Uses a THROWAWAY in-memory token store (never the production database), so it cannot
disturb the live site's token. A FYERS login probably replaces the previous token, so run
this BEFORE turning FYERS_ENABLED on in Render, not alongside it. About 7 of the day's
5,000 data requests are used. Prints summaries only, never tokens or secrets.

Steps: settings -> login (refresh/TOTP) -> index price -> daily history -> 1-minute history
(and how far back it reaches) -> option chain (are greeks and IV present, and in what unit).
"""
import asyncio
import os
import sys
from datetime import datetime, timedelta

from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))
os.environ["FYERS_ENABLED"] = "1"   # this test runs regardless of the site switch in .env

import fyers_auth  # noqa: E402
import fyers_client  # noqa: E402
from fyers_budget import budget  # noqa: E402

IST = fyers_auth.IST


class MemColl:
    def __init__(self):
        self.doc = None

    async def find_one(self, flt, proj=None):
        return dict(self.doc) if self.doc else None

    async def update_one(self, flt, upd, upsert=False):
        self.doc = {**(self.doc or {}), **flt, **upd["$set"]}


class MemDb:
    def __init__(self):
        self.c = {}

    def __getitem__(self, k):
        return self.c.setdefault(k, MemColl())

    def __getattr__(self, k):
        return self[k]


FAILS = []


async def step(name, coro):
    try:
        out = await coro
        print(f"[ OK ] {name}: {out}")
        return out
    except Exception as e:  # noqa: BLE001 -- show every failure
        FAILS.append(name)
        print(f"[FAIL] {name}: {type(e).__name__}: {e}")
        return None


async def main() -> int:
    missing = fyers_auth.missing_settings(for_totp=True)
    print("settings missing:", missing or "none")
    if missing:
        print("Add them to backend/.env (names only listed above), then run again.")
        return 1
    db = MemDb()
    token = await step("login", fyers_auth.get_access_token(db))
    if token is None:
        print("\nLogin failed. Send me the FAIL line (it contains no secrets). Do not retry more than once or twice: "
              "failed TOTP attempts count against the account.")
        return 1
    st = await fyers_auth.status(db)
    print("   token valid until", st["valid_until"], "| obtained via", st["method"])
    c = fyers_client.FyersClient(db)
    sym = fyers_client.INDEX_SYMBOLS["NIFTY"]
    await step("index price", c.ltp(sym))
    now = datetime.now(IST)

    async def daily():
        d = await c.daily_history(sym, years=1)
        return f"{len(d)} days, last {d[-1]['date']} close {d[-1]['close']}" if d else "no bars"
    await step("daily history", daily())

    async def minute():
        bars = await c.minute_ohlc(sym, now - timedelta(days=5), now)
        return f"{len(bars)} bars, {bars[0]['ts']} -> {bars[-1]['ts']}" if bars else "no bars (market closed days only?)"
    await step("1-minute history (5 days)", minute())

    async def reach():
        bars = await c.minute_ohlc(sym, now - timedelta(days=330), now - timedelta(days=325))
        return f"{len(bars)} bars from ~11 months back" if bars else "none that far back"
    await step("history reach (~11 months)", reach())

    async def chain():
        ch = await c.option_chain(sym, strikecount=6, greeks=True)
        k = min(ch["strikes"], key=lambda s: abs(s - (ch["spot"] or 0)))
        ce = ch["strikes"][k]["ce"] or {}
        have = {x: ce.get(x) is not None for x in ("delta", "gamma", "theta", "vega", "iv_raw")}
        return (f"spot {ch['spot']}, {len(ch['strikes'])} strikes, ATM {k:.0f} CE ltp {ce.get('ltp')} | present: {have} | "
                f"iv_raw {ce.get('iv_raw')} (a value like 14 means percent, like 0.14 means decimal)")
    await step("option chain (greeks + IV)", chain())
    print("\nbudget:", budget.snapshot())
    print("All steps passed." if not FAILS else f"{len(FAILS)} step(s) failed: {', '.join(FAILS)}")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
