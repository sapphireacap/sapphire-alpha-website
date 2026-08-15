"""Deribit options client — the Crypto segment's options-chain source.

Deribit is the only venue with genuinely liquid, standardized listed
crypto options (BTC and ETH), and its public market-data API is free and
keyless. Verified live, 2026-08-16: instrument listing, index price,
per-instrument book summary (with mark price and mark IV), and historical
OHLC via get_tradingview_chart_data all answer without credentials.

This is what makes Gamma Pulse and Index Vector real for Crypto rather
than approximated. The three-pillar rule needs a future leg, an ATM call
and an ATM put, each with its own price history:

    future leg -> BTC-PERPETUAL / ETH-PERPETUAL (the perpetual swap, the
                  most liquid non-option instrument on the venue and the
                  natural stand-in for the India side's index future)
    call/put   -> the ATM strike on the nearest non-expired expiry

Coverage is deliberately BTC and ETH only. Deribit lists options on a few
other assets, but liquidity outside BTC/ETH is thin enough that a P&F
column built on it would be reading noise -- this codebase's standing
rule is to return nothing rather than something hollow (see
breadth_engine.py / relative_strength_matrix.py on unresolved legs).

An option contract's own history is short by nature (a contract only
exists between listing and expiry). When a leg has too few bars to print
a P&F column, options_trend_engine.leg_direction() already returns None
and the verdict falls through to Neutral -- that path is exercised here
far more often than on the India side, and is correct, not a bug.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone

import httpx

logger = logging.getLogger(__name__)

BASE_URL = "https://www.deribit.com/api/v2/public"
CURRENCIES = {"BTC": "Bitcoin", "ETH": "Ethereum"}
INDEX_NAMES = {"BTC": "btc_usd", "ETH": "eth_usd"}

# BTC-30OCT26-76000-C
_INSTRUMENT_RE = re.compile(r"^(?P<cur>[A-Z]+)-(?P<expiry>\d{1,2}[A-Z]{3}\d{2})-(?P<strike>\d+)-(?P<kind>[CP])$")


class DeribitError(Exception):
    """Upstream problems -- safe to show a caller."""


async def _get(path: str, params: dict) -> dict:
    try:
        async with httpx.AsyncClient(timeout=20) as c:
            r = await c.get(f"{BASE_URL}/{path}", params=params)
        r.raise_for_status()
        payload = r.json()
    except httpx.HTTPError as e:
        raise DeribitError(f"Deribit request failed: {e}") from e
    if "error" in payload:
        raise DeribitError(f"Deribit: {payload['error']}")
    return payload.get("result")


def parse_instrument(name: str) -> dict | None:
    """{currency, expiry_date, strike, kind} or None if `name` isn't an
    option instrument (perpetuals and futures deliberately don't match)."""
    m = _INSTRUMENT_RE.match(name)
    if not m:
        return None
    try:
        expiry = datetime.strptime(m.group("expiry"), "%d%b%y").replace(tzinfo=timezone.utc).date()
    except ValueError:
        return None
    return {
        "currency": m.group("cur"),
        "expiry_date": expiry.isoformat(),
        "strike": float(m.group("strike")),
        "kind": "call" if m.group("kind") == "C" else "put",
        "instrument_name": name,
    }


async def index_price(currency: str) -> float:
    currency = currency.strip().upper()
    if currency not in INDEX_NAMES:
        raise DeribitError(f"No Deribit index for {currency}.")
    result = await _get("get_index_price", {"index_name": INDEX_NAMES[currency]})
    price = (result or {}).get("index_price")
    if price is None:
        raise DeribitError(f"Deribit returned no index price for {currency}.")
    return float(price)


async def option_chain(currency: str) -> list:
    """Every live option contract on `currency`, parsed. Uses the book
    summary endpoint (not the plain instrument list) so mark price / mark
    IV / open interest come back in the same call -- the chain view needs
    them and a second round-trip per contract would be absurd."""
    currency = currency.strip().upper()
    if currency not in CURRENCIES:
        raise DeribitError(f"Deribit options cover {', '.join(CURRENCIES)} only.")

    rows = await _get("get_book_summary_by_currency", {"currency": currency, "kind": "option"}) or []
    chain = []
    for row in rows:
        parsed = parse_instrument(row.get("instrument_name") or "")
        if not parsed:
            continue
        chain.append({
            **parsed,
            "mark_price": row.get("mark_price"),
            "mark_iv": row.get("mark_iv"),
            "open_interest": row.get("open_interest"),
            "underlying_price": row.get("underlying_price"),
            "volume": row.get("volume"),
        })
    if not chain:
        raise DeribitError(f"Deribit returned an empty {currency} option chain.")
    return chain


def is_monthly_expiry(iso_date: str) -> bool:
    """Deribit's monthly contracts expire on the LAST FRIDAY of the month
    (its dailies/weeklies land on every other date)."""
    try:
        d = datetime.strptime(iso_date, "%Y-%m-%d").date()
    except ValueError:
        return False
    if d.weekday() != 4:  # Friday
        return False
    return (d + timedelta(days=7)).month != d.month


async def atm_legs(currency: str, prefer_monthly: bool = True) -> dict:
    """{expiry_date, strike, spot, call, put, expiry_is_monthly} for the
    at-the-money strike of the nearest MONTHLY expiry -- the exact pair of
    legs Gamma Pulse reads.

    Why monthly rather than literally the soonest listed expiry, and why
    this is the faithful choice rather than a deviation: the India-side
    rule (options_trend_data.resolve_stock_atm_tokens) is "nearest listed
    expiry still in the future", but that module documents that Indian
    STOCK options list monthly expiries only -- NSE's own fo_mktlots.csv
    carries exactly three monthly columns per stock and no weekly ones. So
    on the India side "nearest listed expiry" already resolves to a
    monthly contract every time.

    Deribit additionally lists dailies and weeklies. Applying the literal
    words of the rule there picks a contract that has existed for a day or
    two, and a P&F column simply cannot print off that. Measured live,
    2026-08-16, BTC ATM call bar counts by expiry:

        16AUG(daily)   4 bars      21AUG(weekly)   17 bars
        17AUG(daily)   3 bars      28AUG(MONTHLY)  74 bars
        18AUG(daily)   2 bars      25SEP(MONTHLY) 179 bars
        19AUG(daily)   0 bars

    Selecting the nearest monthly reproduces the same KIND of instrument
    the India rule lands on, and is what makes the module readable at all
    here. `prefer_monthly=False` restores the literal nearest-expiry rule;
    if no monthly is listed, this falls back to it automatically and
    reports which happened via `expiry_is_monthly`.

    ATM is the listed strike closest to the live index price -- resolved
    off real listed contracts, never rounded to a round number that might
    not actually be listed (same discipline as the India resolver)."""
    chain = await option_chain(currency)
    spot = await index_price(currency)

    today = datetime.now(timezone.utc).date().isoformat()
    future_expiries = sorted({c["expiry_date"] for c in chain if c["expiry_date"] >= today})
    if not future_expiries:
        raise DeribitError(f"No unexpired {currency} option expiries on Deribit.")

    monthlies = [e for e in future_expiries if is_monthly_expiry(e)]
    expiry = monthlies[0] if (prefer_monthly and monthlies) else future_expiries[0]

    near = [c for c in chain if c["expiry_date"] == expiry]
    strikes = sorted({c["strike"] for c in near})
    atm_strike = min(strikes, key=lambda s: abs(s - spot))

    call = next((c for c in near if c["strike"] == atm_strike and c["kind"] == "call"), None)
    put = next((c for c in near if c["strike"] == atm_strike and c["kind"] == "put"), None)
    if not call or not put:
        raise DeribitError(f"{currency} {expiry} has no complete ATM call/put pair at {atm_strike:g}.")

    return {
        "expiry_date": expiry, "strike": atm_strike, "spot": spot,
        "call": call, "put": put, "expiry_is_monthly": is_monthly_expiry(expiry),
    }


async def instrument_closes(instrument_name: str, days: int = 120, resolution: str = "1D") -> list:
    """Real historical closes for any Deribit instrument (option leg or
    perpetual), oldest first. Returns [] when Deribit has no data for the
    window rather than raising -- callers feed this straight into
    options_trend_engine.leg_direction(), which treats a too-short series
    as an unresolved leg."""
    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    start_ms = now_ms - days * 86_400_000
    try:
        result = await _get("get_tradingview_chart_data", {
            "instrument_name": instrument_name,
            "start_timestamp": start_ms,
            "end_timestamp": now_ms,
            "resolution": resolution,
        })
    except DeribitError as e:
        logger.info("Deribit chart data unavailable for %s: %s", instrument_name, e)
        return []
    if not result or result.get("status") == "no_data":
        return []
    return [float(c) for c in (result.get("close") or []) if c is not None]


async def instrument_closes_by_date(instrument_name: str, days: int = 200, resolution: str = "1D") -> dict:
    """{date: close} for one instrument. Needed because a straddle series
    is the SUM of a call and a put's premium on the SAME day -- summing two
    bare lists positionally would silently pair mismatched dates whenever
    the two legs have different bar counts (they routinely do, since a leg
    with no trades that day simply has no bar)."""
    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    start_ms = now_ms - days * 86_400_000
    try:
        result = await _get("get_tradingview_chart_data", {
            "instrument_name": instrument_name,
            "start_timestamp": start_ms,
            "end_timestamp": now_ms,
            "resolution": resolution,
        })
    except DeribitError as e:
        logger.info("Deribit chart data unavailable for %s: %s", instrument_name, e)
        return {}
    if not result or result.get("status") == "no_data":
        return {}
    ticks = result.get("ticks") or []
    closes = result.get("close") or []
    out = {}
    for i, tick in enumerate(ticks):
        if i >= len(closes) or closes[i] is None:
            continue
        out[datetime.fromtimestamp(tick / 1000, tz=timezone.utc).date().isoformat()] = float(closes[i])
    return out


async def perpetual_closes(currency: str, days: int = 120) -> list:
    """The future-leg price series -- the perpetual swap."""
    return await instrument_closes(f"{currency.strip().upper()}-PERPETUAL", days=days)
