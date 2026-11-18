"""FYERS Data API client (REST), read-only.

Every call: (1) reserves a slot in fyers_budget (refuses rather than risk the daily/minute
block), (2) gets a token from fyers_auth (renewed automatically), (3) sends the request,
(4) on a rate-limit reply pauses ALL calls for a minute, because more than 3 per-minute
violations in a day block the account until tomorrow.

FREE (Standard) plan facts this is built around
  REST data: 5/s, 50/min, 5,000/day     quotes: 50 symbols per request
  history: daily 5 years, intraday 1 year, 10 requests/day for EXPIRED F&O intraday
  live WebSocket: 100 symbols in total (enforced in the live-feed module, not here)
So: fetch history ONCE a day and cache it, take live prices from the WebSocket, and cache
the option chain for 30-60 s. Do not call this per visitor request.

UNVERIFIED until the first live run (scripts/fyers_check.py): the REST paths below follow
FYERS' v3 docs and SDK; the per-request history windows (INTRADAY_CHUNK_DAYS /
DAILY_CHUNK_DAYS) are the commonly reported limits; and the unit of the option-chain `iv`
(percent vs decimal) is not documented, so it is returned raw as `iv_raw`.
"""
import logging
import time
from datetime import datetime, timedelta, timezone

import httpx

import fyers_auth
from fyers_budget import FyersBudgetError, budget as default_budget

logger = logging.getLogger(__name__)

IST = timezone(timedelta(hours=5, minutes=30))
DATA = "https://api-t1.fyers.in/data"
INTRADAY_CHUNK_DAYS = 95      # 1-minute history is commonly limited to ~100 days per request
DAILY_CHUNK_DAYS = 360
RATE_LIMIT_PAUSE = 70         # seconds all calls stop after a -429
EXPIRED_TOKEN_CODES = {-8, -15, -16, -17}
INDEX_SYMBOLS = {"NIFTY": "NSE:NIFTY50-INDEX", "BANKNIFTY": "NSE:NIFTYBANK-INDEX",
                 "FINNIFTY": "NSE:FINNIFTY-INDEX", "VIX": "NSE:INDIAVIX-INDEX"}


class FyersError(Exception):
    """Upstream or request problem. Safe to show an admin."""


class FyersRateLimited(FyersError):
    pass


_paused_until = 0.0


def _http() -> httpx.AsyncClient:   # replaced in tests
    return httpx.AsyncClient(timeout=60)


class FyersClient:
    def __init__(self, db, budget=None):
        self.db = db
        self.budget = budget or default_budget

    async def _get(self, path: str, params: dict) -> dict:
        global _paused_until
        if time.monotonic() < _paused_until:
            raise FyersRateLimited(f"FYERS calls paused for {int(_paused_until - time.monotonic())} s after a rate-limit reply.")
        for attempt in (1, 2):
            await self.budget.acquire(self.db)
            headers = {"Authorization": f"{fyers_auth._env('FYERS_APP_ID')}:{await fyers_auth.get_access_token(self.db, force=(attempt == 2))}"}
            async with _http() as c:
                r = await c.get(f"{DATA}/{path}", params=params, headers=headers)
            try:
                body = r.json()
            except ValueError:
                body = {}
            code = body.get("code")
            if r.status_code == 429 or code == -429:
                _paused_until = time.monotonic() + RATE_LIMIT_PAUSE
                raise FyersRateLimited("FYERS rate limit hit (-429); all calls paused for a minute.")
            if attempt == 1 and (r.status_code == 401 or code in EXPIRED_TOKEN_CODES):
                continue                      # token went stale mid-day: renew once and retry
            if r.status_code != 200 or body.get("s") == "error":
                raise FyersError(f"FYERS {path} failed: HTTP {r.status_code} code {code} {str(body.get('message') or r.text)[:150]}")
            return body
        raise FyersError(f"FYERS {path}: token rejected even after renewal.")

    # ---- history ---------------------------------------------------------------------
    async def history(self, symbol: str, resolution: str, frm: datetime, to: datetime) -> list:
        """Raw candles [[epoch, o, h, l, c, v], ...] oldest first, split into request-sized windows."""
        daily = resolution in ("D", "1D")
        span = timedelta(days=DAILY_CHUNK_DAYS if daily else INTRADAY_CHUNK_DAYS)
        out, cursor = [], frm
        while cursor <= to:
            end = min(cursor + span, to)
            body = await self._get("history", {"symbol": symbol, "resolution": resolution, "date_format": 0,
                                               "range_from": int(cursor.timestamp()), "range_to": int(end.timestamp()), "cont_flag": 1})
            out.extend(body.get("candles") or [])
            cursor = end + timedelta(seconds=1)
        seen = {}
        for c in out:
            seen[c[0]] = c
        return [seen[k] for k in sorted(seen)]

    async def minute_ohlc(self, symbol: str, frm: datetime, to: datetime) -> list:
        """1-minute bars in the shape SAC's chart code uses: {ts "ddmmyyyyHHMM", open, high, low, close, volume}."""
        out = []
        for t, o, h, l, c, v in await self.history(symbol, "1", frm, to):
            dt = datetime.fromtimestamp(t, tz=IST)
            out.append({"ts": dt.strftime("%d%m%Y%H%M"), "open": float(o), "high": float(h), "low": float(l), "close": float(c),
                        "volume": float(v or 0)})
        return out

    async def daily_history(self, symbol: str, years: int = 5) -> list:
        """Daily bars {date 'YYYY-MM-DD', open, high, low, close, volume}. The free plan holds 5 years."""
        to = datetime.now(IST)
        out = []
        for t, o, h, l, c, v in await self.history(symbol, "D", to - timedelta(days=int(365.25 * min(years, 5))), to):
            out.append({"date": datetime.fromtimestamp(t, tz=IST).date().isoformat(), "open": float(o), "high": float(h),
                        "low": float(l), "close": float(c), "volume": float(v or 0)})
        return out

    # ---- quotes ----------------------------------------------------------------------
    async def quotes(self, symbols: list) -> dict:
        """{symbol: {ltp, open, high, low, prev_close, volume}} (50 symbols per request on the free plan)."""
        out = {}
        for i in range(0, len(symbols), 50):
            body = await self._get("quotes", {"symbols": ",".join(symbols[i:i + 50])})
            for item in body.get("d") or []:
                v = item.get("v") or {}
                if item.get("s") == "ok" or v.get("lp") is not None:
                    out[item.get("n")] = {"ltp": v.get("lp"), "open": v.get("open_price"), "high": v.get("high_price"),
                                          "low": v.get("low_price"), "prev_close": v.get("prev_close_price"), "volume": v.get("volume")}
        return out

    async def ltp(self, symbol: str) -> float:
        q = (await self.quotes([symbol])).get(symbol)
        if not q or q["ltp"] is None:
            raise FyersError(f"No price for {symbol}.")
        return float(q["ltp"])

    # ---- option chain with greeks and IV ---------------------------------------------------
    async def option_chain(self, symbol: str, strikecount: int = 10, greeks: bool = True) -> dict:
        """{spot, expiries, strikes: {strike: {"ce": side, "pe": side}}} where side holds ltp, oi, volume,
        delta, gamma, theta, vega and `iv_raw` (UNIT UNVERIFIED: print it with fyers_check before
        converting). `symbol` is the underlying, e.g. NSE:NIFTY50-INDEX. One call covers every strike,
        so cache the result 30-60 s. Whether free accounts receive greeks is confirmed on the first run."""
        params = {"symbol": symbol, "strikecount": min(int(strikecount), 50)}
        if greeks:
            params["greeks"] = "1"
        body = await self._get("options-chain-v3", params)
        data = body.get("data") or {}
        spot, strikes = None, {}
        for row in data.get("optionsChain") or []:
            kind = (row.get("option_type") or "").upper()
            if kind not in ("CE", "PE"):
                spot = row.get("ltp", spot)            # the underlying's own row
                continue
            strike = row.get("strike_price")
            if strike is None or float(strike) <= 0:
                continue
            strikes.setdefault(float(strike), {"ce": None, "pe": None})[kind.lower()] = {
                "symbol": row.get("symbol"), "ltp": row.get("ltp"), "oi": row.get("oi"), "volume": row.get("volume"),
                "delta": row.get("delta"), "gamma": row.get("gamma"), "theta": row.get("theta"), "vega": row.get("vega"),
                "iv_raw": row.get("iv")}
        if not strikes:
            raise FyersError(f"FYERS returned an empty option chain for {symbol}.")
        return {"spot": spot, "expiries": data.get("expiryData") or [], "strikes": strikes,
                "fetched_at": datetime.now(timezone.utc).isoformat()}


__all__ = ["FyersClient", "FyersError", "FyersRateLimited", "FyersBudgetError", "INDEX_SYMBOLS"]
