"""
Shared REAL-DATA assembly layer for Premium Band Strangle -- the only place
that actually talks to Definedge for the futures/spot side of this
strategy (per-strike premiums are fetched directly in
blackbox_options_engine.py, since Premium Band Strangle needs no Greeks).

Never fabricates a price: every function here returns None and surfaces
WHY rather than guessing when real data isn't available -- matches this
codebase's established resilience discipline (RESILIENCE section of the
spec: "NEVER write a fabricated or interpolated fill price").

Convexity Window / Gamma Backspread's Greeks/IV/realized-vol/15m-EMA
assembly functions that used to live here were removed entirely on
2026-08-26, code and production data both, per explicit instruction --
see git history if either strategy is ever wanted back.
"""
from datetime import datetime

from blackbox_options_data import resolve_futures_token
from definedge_service import DefinedgeError, INDEX_CONFIG, IST

# Real, verified-live strike increments (NIFTY options list on 50-point
# strikes, BANKNIFTY on 100-point strikes -- confirmed against the real
# allmaster.zip listing, 2026-07-29). NOT guessed from the underlying's own
# spot-price scale.
STRIKE_INCREMENT = {"NIFTY": 50, "BANKNIFTY": 100}


def atm_strike(spot: float, index_key: str) -> int:
    inc = STRIKE_INCREMENT[index_key]
    return round(spot / inc) * inc


async def get_futures_price(df, definedge, index_key: str) -> dict | None:
    """{"F": float, "token": str, "expiry": date} for the nearest listed
    future, or None if nothing resolves."""
    fut = resolve_futures_token(df, INDEX_CONFIG[index_key]["option_symbol"], datetime.now(IST).date())
    if fut is None:
        return None
    try:
        ltp = await definedge.equity_quote(INDEX_CONFIG[index_key]["option_segment"], fut["token"])
    except DefinedgeError:
        return None
    return {"F": ltp, "token": fut["token"], "expiry": fut["expiry"]}
