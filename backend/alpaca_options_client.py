"""Alpaca options client — the US Markets options-chain source.

Kept separate from alpaca_client.py on purpose: that module is the
equity/intraday bars client and documents its own IEX-feed and
index-ETF-proxy caveats. This one only touches the options endpoints,
which live under a different API version (/v1beta1) and have their own
distinct constraints.

Verified live, 2026-08-16 (real credentials, this repo's existing
ALPACA_API_KEY_ID/ALPACA_API_SECRET_KEY):
  - GET /v1beta1/options/snapshots/{underlying} -> 200, real chain with
    per-contract dailyBar, latestQuote and latestTrade
  - GET /v1beta1/options/bars?symbols=... -> 200, real daily OHLC per
    contract
  - GET /v2/options/contracts (the TRADING API) -> 401. Not used here,
    and not needed: strike, expiry and right are all encoded in the OSI
    symbol the market-data endpoints already return, so the chain is
    fully derivable without any trading entitlement.

The honest constraint, and why it is not hidden: a listed option only
exists between listing and expiry, and non-front-month strikes trade
thinly. Daily bar history for one contract is therefore often just a
handful of bars -- far short of what a P&F column needs. When that
happens options_trend_engine.leg_direction() returns None and the verdict
falls through to Neutral. That is the designed behaviour for an
unresolved leg (same discipline as breadth_engine.py), not a failure, but
it does mean US Gamma Pulse will read Neutral more often than the India
side does. Surfaced in the response as `leg_bars` so the UI can say why.
"""
from __future__ import annotations

import logging
import os
import re
from datetime import datetime, timedelta, timezone

import httpx

logger = logging.getLogger(__name__)

DATA_BASE = "https://data.alpaca.markets/v1beta1/options"

# OSI: AAPL260817C00210000 = root + YYMMDD + C|P + strike x 1000, 8 digits
_OSI_RE = re.compile(r"^(?P<root>[A-Z]+)(?P<y>\d{2})(?P<m>\d{2})(?P<d>\d{2})(?P<kind>[CP])(?P<strike>\d{8})$")

# S&P 500 / Nasdaq 100 have no directly optionable index product on a
# retail market-data feed; their most liquid tracking ETFs do, and are
# what actually carries the options volume. Same proxy relationship
# alpaca_client.py already documents for intraday index bars.
INDEX_OPTION_PROXIES = {
    "SPX": {"ticker": "SPY", "label": "S&P 500", "proxy_label": "SPY ETF"},
    "NDX": {"ticker": "QQQ", "label": "Nasdaq 100", "proxy_label": "QQQ ETF"},
}


class AlpacaOptionsError(Exception):
    """Upstream problems -- safe to show a caller."""


def _auth_headers() -> dict:
    key = os.environ.get("ALPACA_API_KEY_ID")
    secret = os.environ.get("ALPACA_API_SECRET_KEY")
    if not key or not secret:
        raise AlpacaOptionsError("Alpaca API credentials are not configured.")
    return {"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": secret}


def parse_osi(symbol: str) -> dict | None:
    """{underlying, expiry_date, strike, kind} from an OSI contract
    symbol, or None if it doesn't parse."""
    m = _OSI_RE.match(symbol.strip().upper())
    if not m:
        return None
    try:
        expiry = datetime(2000 + int(m.group("y")), int(m.group("m")), int(m.group("d")), tzinfo=timezone.utc).date()
    except ValueError:
        return None
    return {
        "underlying": m.group("root"),
        "expiry_date": expiry.isoformat(),
        "strike": int(m.group("strike")) / 1000.0,
        "kind": "call" if m.group("kind") == "C" else "put",
        "contract_symbol": symbol.strip().upper(),
    }


async def _get(path: str, params: dict) -> dict:
    try:
        async with httpx.AsyncClient(timeout=25) as c:
            r = await c.get(f"{DATA_BASE}/{path}", headers=_auth_headers(), params=params)
        r.raise_for_status()
        return r.json()
    except httpx.HTTPStatusError as e:
        raise AlpacaOptionsError(f"Alpaca options request failed ({e.response.status_code}).") from e
    except httpx.HTTPError as e:
        raise AlpacaOptionsError(f"Alpaca options request failed: {e}") from e


async def option_chain(underlying: str, limit: int = 500, expiration_date: str | None = None,
                        strike_low: float | None = None, strike_high: float | None = None) -> list:
    """Live chain for one underlying, parsed off the snapshots endpoint.

    The optional filters are applied SERVER-SIDE by Alpaca
    (expiration_date / strike_price_gte / strike_price_lte -- all verified
    live, 2026-08-16). Using them is not an optimisation detail, it is a
    correctness requirement for liquid names: SPY lists thousands of
    contracts, so an unfiltered bounded walk exhausts `limit` inside the
    first few daily expiries and never sees the monthly one at all. That
    exact bug produced a wrong (non-monthly) leg for SPY before this was
    added."""
    underlying = underlying.strip().upper()
    contracts, token, pulled = [], None, 0

    while pulled < limit:
        params = {"limit": min(100, limit - pulled)}
        if expiration_date:
            params["expiration_date"] = expiration_date
        if strike_low is not None:
            params["strike_price_gte"] = strike_low
        if strike_high is not None:
            params["strike_price_lte"] = strike_high
        if token:
            params["page_token"] = token
        payload = await _get(f"snapshots/{underlying}", params)
        snapshots = payload.get("snapshots") or {}
        if not snapshots:
            break
        for sym, snap in snapshots.items():
            parsed = parse_osi(sym)
            if not parsed:
                continue
            bar = snap.get("dailyBar") or {}
            quote = snap.get("latestQuote") or {}
            trade = snap.get("latestTrade") or {}
            contracts.append({
                **parsed,
                "close": bar.get("c"),
                "bid": quote.get("bp"),
                "ask": quote.get("ap"),
                "last": trade.get("p"),
                "volume": bar.get("v"),
            })
        pulled += len(snapshots)
        token = payload.get("next_page_token")
        if not token:
            break

    if not contracts:
        raise AlpacaOptionsError(f"Alpaca returned an empty option chain for {underlying}.")
    return contracts


def is_monthly_expiry(iso_date: str) -> bool:
    """Standard OCC monthly contracts expire on the THIRD FRIDAY of the
    month; weeklies land on every other Friday (and, for the most liquid
    names, most weekdays)."""
    try:
        d = datetime.strptime(iso_date, "%Y-%m-%d").date()
    except ValueError:
        return False
    return d.weekday() == 4 and 15 <= d.day <= 21


def _upcoming_monthly_expiries(from_date, count: int = 3) -> list:
    """The next `count` standard OCC monthly expiry dates (third Friday),
    starting with this month's if it hasn't passed yet."""
    out = []
    year, month = from_date.year, from_date.month
    while len(out) < count:
        first = datetime(year, month, 1, tzinfo=timezone.utc).date()
        # weekday(): Mon=0 .. Fri=4 -- days until the month's first Friday
        third_friday = first + timedelta(days=(4 - first.weekday()) % 7 + 14)
        if third_friday >= from_date:
            out.append(third_friday.isoformat())
        month = 1 if month == 12 else month + 1
        year = year + 1 if month == 1 else year
    return out


async def atm_legs(underlying: str, spot: float, prefer_monthly: bool = True) -> dict:
    """{expiry_date, strike, call, put, expiry_is_monthly} for the ATM
    strike of the nearest MONTHLY expiry.

    Monthly rather than literally-soonest for the same reason
    deribit_client.atm_legs documents at length: the India-side rule
    resolves to a monthly contract every time, because Indian stock
    options list monthly expiries only. US names list weeklies (and dailies
    on the most liquid tickers), so the literal rule would pick a contract
    days old, which cannot print a P&F column. Selecting the nearest
    monthly reproduces the same kind of instrument the India rule lands on.

    `spot` is passed in rather than fetched so the caller controls which
    price source defines "the money" (alpaca_client.latest_trade for a
    stock, the tracking ETF's own last for an index proxy)."""
    today = datetime.now(timezone.utc).date()

    chain = []
    if prefer_monthly:
        # Ask Alpaca for the specific monthly dates rather than walking the
        # whole chain -- see option_chain's docstring for the SPY bug this
        # avoids. A monthly can be absent (holiday shift, or the underlying
        # simply has none listed that far out), so the next few are tried
        # in turn before falling back to the literal nearest expiry.
        window = max(spot * 0.15, 1.0)
        for candidate in _upcoming_monthly_expiries(today, count=3):
            try:
                chain = await option_chain(
                    underlying, expiration_date=candidate,
                    strike_low=spot - window, strike_high=spot + window,
                )
                break
            except AlpacaOptionsError:
                continue
    if not chain:
        chain = await option_chain(underlying)

    today_iso = today.isoformat()
    expiries = sorted({c["expiry_date"] for c in chain if c["expiry_date"] >= today_iso})
    if not expiries:
        raise AlpacaOptionsError(f"No unexpired {underlying} option expiries.")

    monthlies = [e for e in expiries if is_monthly_expiry(e)]
    expiry = monthlies[0] if (prefer_monthly and monthlies) else expiries[0]

    near = [c for c in chain if c["expiry_date"] == expiry]
    strikes = sorted({c["strike"] for c in near})
    if not strikes:
        raise AlpacaOptionsError(f"No listed strikes for {underlying} {expiry}.")
    atm_strike = min(strikes, key=lambda s: abs(s - spot))

    call = next((c for c in near if c["strike"] == atm_strike and c["kind"] == "call"), None)
    put = next((c for c in near if c["strike"] == atm_strike and c["kind"] == "put"), None)
    if not call or not put:
        raise AlpacaOptionsError(f"{underlying} {expiry} has no complete ATM pair at {atm_strike:g}.")

    return {
        "expiry_date": expiry, "strike": atm_strike, "spot": spot,
        "call": call, "put": put, "expiry_is_monthly": is_monthly_expiry(expiry),
    }


async def contract_closes(contract_symbol: str, days: int = 120) -> list:
    """Real daily closes for one option contract, oldest first. Returns []
    (never raises) when Alpaca has no bars -- see the module docstring on
    why an empty/short series is expected here and handled downstream as
    an unresolved leg."""
    start = (datetime.now(timezone.utc) - timedelta(days=days)).date().isoformat()
    try:
        payload = await _get("bars", {"symbols": contract_symbol, "timeframe": "1Day", "start": start, "limit": 1000})
    except AlpacaOptionsError as e:
        logger.info("Alpaca option bars unavailable for %s: %s", contract_symbol, e)
        return []
    rows = (payload.get("bars") or {}).get(contract_symbol) or []
    return [float(r["c"]) for r in rows if r.get("c") is not None]


async def contract_closes_by_date(contract_symbol: str, days: int = 200) -> dict:
    """{date: close} for one contract -- see
    deribit_client.instrument_closes_by_date for why a straddle sum needs
    dated closes rather than two bare lists."""
    start = (datetime.now(timezone.utc) - timedelta(days=days)).date().isoformat()
    try:
        payload = await _get("bars", {"symbols": contract_symbol, "timeframe": "1Day", "start": start, "limit": 1000})
    except AlpacaOptionsError as e:
        logger.info("Alpaca option bars unavailable for %s: %s", contract_symbol, e)
        return {}
    rows = (payload.get("bars") or {}).get(contract_symbol) or []
    out = {}
    for r in rows:
        if r.get("c") is None or not r.get("t"):
            continue
        out[str(r["t"])[:10]] = float(r["c"])
    return out
