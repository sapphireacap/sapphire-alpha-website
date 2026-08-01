"""
Thin, rate-limit-aware Dhan data-access layer for the Convexity Window /
Gamma Backspread backtest -- the ONLY place in this codebase that talks to
Dhan. Definedge remains the live/paper data source (blackbox_options_market.py);
this module exists purely because Dhan's expired_options_data() can return
real premium history for CONTRACTS THAT HAVE ALREADY EXPIRED, which
Definedge's symbol master structurally cannot (verified live, 2026-07-29 --
see blackbox_options_backtest.py's docstring). Definedge stays the source of
truth for anything live/paper; Dhan is backtest-only, historical-only.

Verified live (2026-07-31) against real Dhan responses, not assumed from
docs:
  - expired_options_data(): real dense 1-minute OHLCV for an actually-expired
    NIFTY weekly ATM call (timestamps ran 09:15-15:29 IST across real
    trading days). Depth is genuinely limited though: the SDK itself
    restricts expiry_code to [0,1,2,3] -- roughly the last 3-4 expiry
    cycles only (~1 month for weekly options), not deep history.
  - intraday_minute_data() on the INDEX itself (not an expiring
    derivative) reaches back well past "last 5 trading days" (confirmed
    real 15-min NIFTY bars from 3 weeks prior) -- that docstring phrase is
    about max SPAN per request, not a hard "only recent" wall. Chunked
    into <=5-trading-day requests here to respect that span cap.
  - Both charts endpoints enforce a 90-calendar-day max span per request
    (DH-905 "Data for Option Charts can be fetched for 90 days at a time").
  - Real rate limiting exists (DH-904) -- retried with backoff below.
"""
import asyncio
import logging
import os
from datetime import date, datetime, timedelta, timezone

logger = logging.getLogger(__name__)
IST = timezone(timedelta(hours=5, minutes=30))

NIFTY_INDEX_SECURITY_ID = "13"  # confirmed live against Dhan's real scrip master
BANKNIFTY_INDEX_SECURITY_ID = "25"  # SEM_TRADING_SYMBOL == "BANKNIFTY", same master, not yet independently re-verified per call site -- verify_index_security_ids() below re-checks both at runtime rather than trusting this hardcoded guess alone.

INDEX_SECURITY_ID = {"NIFTY": NIFTY_INDEX_SECURITY_ID, "BANKNIFTY": BANKNIFTY_INDEX_SECURITY_ID}

MAX_EXPIRY_CODE = 3  # SDK-enforced real ceiling, see module docstring
MIN_EXPIRY_CODE = 1  # verified live (2026-07-31): expiry_code=0 is rejected by Dhan's own
                      # API with "expiryCode is required" -- despite their docs listing
                      # 0 as a valid value, it behaves as falsy/missing server-side. 1-3
                      # work correctly (confirmed with real data). Not a client-side guess.
RATE_LIMIT_RETRY_DELAYS = [3, 8, 20]  # seconds, exponential-ish backoff on DH-904


class DhanClientError(Exception):
    pass


def _client():
    from dhanhq import DhanContext, dhanhq
    token = os.environ.get("DHAN_ACCESS_TOKEN")
    client_id = os.environ.get("DHAN_CLIENT_ID")
    if not token or not client_id:
        raise DhanClientError("DHAN_ACCESS_TOKEN / DHAN_CLIENT_ID not configured.")
    ctx = DhanContext(client_id, token)
    return dhanhq(ctx)


async def _call_with_retry(fn, *args, **kwargs) -> dict:
    """Every real Dhan SDK call is synchronous (blocking) HTTP under the
    hood -- run off the event loop thread so this never stalls the FastAPI
    process if this module is ever called from a live route. Retries on a
    real rate-limit response (DH-904) only; any other failure/error status
    is returned as-is for the caller to inspect (never silently retried
    into a different, potentially misleading, result)."""
    last = None
    for attempt, delay in enumerate([0] + RATE_LIMIT_RETRY_DELAYS):
        if delay:
            await asyncio.sleep(delay)
        resp = await asyncio.to_thread(fn, *args, **kwargs)
        last = resp
        remarks = resp.get("remarks")
        code = remarks.get("error_code") if isinstance(remarks, dict) else None
        if resp.get("status") == "success" or code != "DH-904":
            return resp
        logger.warning("Dhan rate limit hit (attempt %d), backing off %ds", attempt + 1, RATE_LIMIT_RETRY_DELAYS[min(attempt, len(RATE_LIMIT_RETRY_DELAYS) - 1)])
    return last


async def verify_index_security_ids() -> dict:
    """Re-checks NIFTY/BANKNIFTY's real security IDs against Dhan's live
    scrip master rather than trusting the hardcoded guesses above --
    BANKNIFTY's ID in particular was not independently confirmed the way
    NIFTY's was. Returns {"NIFTY": "13", "BANKNIFTY": "25"} from the REAL
    file, raising if either isn't found (never silently falls back to the
    unverified guess)."""
    import httpx, csv, io
    url = "https://images.dhan.co/api-data/api-scrip-master.csv"
    async with httpx.AsyncClient(timeout=60) as c:
        r = await c.get(url, follow_redirects=True)
    reader = csv.DictReader(io.StringIO(r.text))
    found = {}
    for row in reader:
        sym = row.get("SEM_TRADING_SYMBOL")
        if sym in ("NIFTY", "BANKNIFTY") and row.get("SEM_INSTRUMENT_NAME") == "INDEX":
            found[sym] = row["SEM_SMST_SECURITY_ID"]
        if len(found) == 2:
            break
    if "NIFTY" not in found or "BANKNIFTY" not in found:
        raise DhanClientError(f"Could not verify both index security IDs against live Dhan master; found: {found}")
    return found


async def index_daily_history(index_key: str, from_date: date, to_date: date) -> list:
    """Real daily OHLC for the underlying index -- no expiry_code (the
    index itself never expires). Chunked into <=90-day windows per the
    real DH-905 span cap observed live."""
    client = _client()
    sec_id = INDEX_SECURITY_ID[index_key]
    out = []
    cursor = from_date
    while cursor <= to_date:
        chunk_end = min(cursor + timedelta(days=89), to_date)
        resp = await _call_with_retry(
            client.historical_daily_data,
            security_id=sec_id, exchange_segment="IDX_I", instrument_type="INDEX",
            from_date=cursor.isoformat(), to_date=chunk_end.isoformat(),
        )
        if resp.get("status") != "success":
            logger.warning("Dhan index_daily_history failed for %s %s-%s: %s", index_key, cursor, chunk_end, resp.get("remarks"))
        else:
            d = resp.get("data") or {}
            ts = d.get("timestamp") or []
            for i, t in enumerate(ts):
                out.append({
                    "date": datetime.fromtimestamp(t, tz=IST).date().isoformat(),
                    "open": d["open"][i], "high": d["high"][i], "low": d["low"][i], "close": d["close"][i],
                })
        cursor = chunk_end + timedelta(days=1)
    out.sort(key=lambda b: b["date"])
    return out


async def index_intraday_bars(index_key: str, from_date: date, to_date: date, interval: int = 15) -> list:
    """Real intraday bars for the underlying index, chunked into <=5-real-
    trading-day windows (observed real span cap on /charts/intraday --
    distinct from the daily endpoint's 90-day cap). Used for the 20-period
    15-minute EMA direction filter, never fabricated/interpolated."""
    client = _client()
    sec_id = INDEX_SECURITY_ID[index_key]
    out = []
    cursor = from_date
    while cursor <= to_date:
        chunk_end = min(cursor + timedelta(days=6), to_date)  # 6 calendar days ~= <=5 trading days incl weekend
        resp = await _call_with_retry(
            client.intraday_minute_data,
            security_id=sec_id, exchange_segment="IDX_I", instrument_type="INDEX",
            from_date=cursor.isoformat(), to_date=chunk_end.isoformat(), interval=interval,
        )
        if resp.get("status") != "success":
            logger.warning("Dhan index_intraday_bars failed for %s %s-%s: %s", index_key, cursor, chunk_end, resp.get("remarks"))
        else:
            d = resp.get("data") or {}
            ts = d.get("timestamp") or []
            for i, t in enumerate(ts):
                out.append({
                    "dt": datetime.fromtimestamp(t, tz=IST),
                    "open": d["open"][i], "high": d["high"][i], "low": d["low"][i], "close": d["close"][i],
                })
        cursor = chunk_end + timedelta(days=1)
    out.sort(key=lambda b: b["dt"])
    return out


async def expired_option_bars(index_key: str, expiry_flag: str, expiry_code: int, strike: str,
                               option_type: str, from_date: date, to_date: date, interval: int = 1) -> dict:
    """One real, already-expired option contract's bars (CE or PE) for a
    given rolling expiry cycle. `strike`: 'ATM', 'ATM+1', 'ATM-1', etc.
    (Dhan resolves the actual strike day-by-day server-side -- this
    codebase never has to pre-resolve a specific strike/contract token the
    way it does for Definedge). Returns {"bars": [...], "raw": resp} --
    `bars` is [] (never fabricated) if the call fails or the cycle has no
    real data in this window."""
    if expiry_code > MAX_EXPIRY_CODE:
        raise DhanClientError(f"expiry_code {expiry_code} exceeds the real, SDK-enforced ceiling of {MAX_EXPIRY_CODE}.")
    client = _client()
    resp = await _call_with_retry(
        client.expired_options_data,
        security_id=INDEX_SECURITY_ID[index_key], exchange_segment="NSE_FNO", instrument_type="OPTIDX",
        expiry_flag=expiry_flag, expiry_code=expiry_code, strike=strike, drv_option_type=option_type,
        # 'strike' and 'spot' requested explicitly so callers use DHAN'S OWN
        # real per-bar resolved strike/spot rather than a locally-guessed
        # ATM +/- offset -- Dhan's day-by-day "what strike is ATM" reference
        # is not guaranteed to exactly match a value independently
        # recomputed from a different spot source, and Greeks computed
        # against the wrong strike would be silently wrong.
        required_data=["open", "high", "low", "close", "volume", "strike", "spot"],
        from_date=from_date.isoformat(), to_date=to_date.isoformat(), interval=interval,
    )
    if resp.get("status") != "success":
        logger.warning("Dhan expired_option_bars failed for %s %s %s cycle=%d strike=%s %s: %s",
                        index_key, expiry_flag, from_date, expiry_code, strike, option_type, resp.get("remarks"))
        return {"bars": [], "raw": resp}
    leg_key = "ce" if option_type == "CALL" else "pe"
    leg = ((resp.get("data") or {}).get("data") or {}).get(leg_key)
    if not leg or not leg.get("timestamp"):
        return {"bars": [], "raw": resp}
    n = len(leg["timestamp"])
    real_strikes = leg.get("strike") or [None] * n
    real_spots = leg.get("spot") or [None] * n
    bars = [
        {"dt": datetime.fromtimestamp(leg["timestamp"][i], tz=IST), "open": leg["open"][i],
         "high": leg["high"][i], "low": leg["low"][i], "close": leg["close"][i],
         "volume": (leg.get("volume") or [None] * n)[i],
         "strike": real_strikes[i], "spot": real_spots[i]}
        for i in range(n)
    ]
    bars.sort(key=lambda b: b["dt"])
    return {"bars": bars, "raw": resp}
