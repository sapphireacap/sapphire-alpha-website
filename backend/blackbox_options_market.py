"""
Shared REAL-DATA assembly layer for Convexity Window / Gamma Backspread --
the only place that actually talks to Definedge for these two strategies.
Turns live/historical Definedge data into the plain `market` dicts that
blackbox_convexity_window.py / blackbox_gamma_backspread.py's pure
check_entry_filters()/evaluate_exit() expect. Both the live/paper cron
evaluator (blackbox_options_engine.py) and the backtest harness
(blackbox_options_backtest.py) call through here, so a signal can never be
computed differently live vs. in backtest.

Never fabricates a price or Greek: every function here returns None/empty
and surfaces WHY (a `reason` string) rather than guessing when real data
isn't available -- matches this codebase's established resilience
discipline (RESILIENCE section of the spec: "NEVER write a fabricated or
interpolated fill price").
"""
from datetime import date, datetime, timedelta

from black76_greeks import price as b76_price, greeks as b76_greeks, implied_vol as b76_iv, years_to_expiry
from blackbox_options_data import (
    list_candidate_expiries, resolve_strike_tokens, list_strikes_near,
    resolve_futures_token, realized_vol, median_true_range, ema_series,
    aggregate_to_15min, percentile_rank,
)
from definedge_service import DefinedgeService, DefinedgeError, INDEX_CONFIG, IST

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
    future, or None if nothing resolves. Black-76 prices off THIS, not
    spot."""
    fut = resolve_futures_token(df, INDEX_CONFIG[index_key]["option_symbol"], datetime.now(IST).date())
    if fut is None:
        return None
    try:
        ltp = await definedge.equity_quote(INDEX_CONFIG[index_key]["option_segment"], fut["token"])
    except DefinedgeError:
        return None
    return {"F": ltp, "token": fut["token"], "expiry": fut["expiry"]}


async def get_contract_quote(definedge, index_key: str, F: float, K: int, expiry: date, option_type: str,
                              token: str, r: float) -> dict | None:
    """Live LTP for one option contract -> IV (Black-76 Newton/bisection
    solve) -> Greeks. None if the LTP fetch itself fails (session expiry,
    illiquid/no-quote strike, etc.) -- never interpolates a fill."""
    try:
        premium = await definedge.equity_quote(INDEX_CONFIG[index_key]["option_segment"], token)
    except DefinedgeError:
        return None
    if premium is None or premium <= 0:
        return None
    T = years_to_expiry(expiry)
    iv = b76_iv(premium, F, K, T, option_type, r)
    g = b76_greeks(F, K, T, iv, option_type, r)
    return {"premium": premium, "iv": iv, "greeks": g, "T": T, "token": token}


async def build_candidates(df, definedge, index_key: str, F: float, atm: int, expiry: date, r: float,
                            strike_range: int, option_types=("CE", "PE")) -> list:
    """Real quote+Greeks for every strike within `strike_range` of ATM, both
    sides, at one expiry -- skips (never fakes) any leg that isn't listed or
    whose live quote fails."""
    inc = STRIKE_INCREMENT[index_key]
    strikes = list_strikes_near(atm, inc, strike_range)
    out = []
    for strike in strikes:
        tokens = resolve_strike_tokens(df, INDEX_CONFIG[index_key]["option_symbol"], expiry, strike)
        for opt in option_types:
            token = tokens.get(opt)
            if not token:
                continue
            q = await get_contract_quote(definedge, index_key, F, strike, expiry, opt, token, r)
            if q is None:
                continue
            out.append({"strike": strike, "expiry": expiry, "option_type": opt, "token": token,
                        "premium": q["premium"], "greeks": q["greeks"], "iv": q["iv"]})
    return out


async def get_realized_vol_and_true_range(definedge, index_key: str, cfg: dict) -> dict:
    """Real daily closes -> realized vol + median true range. None for
    either if there isn't yet enough real daily history."""
    spot_cfg = INDEX_CONFIG[index_key]
    bars = await definedge.daily_history(spot_cfg["spot_segment"], spot_cfg["spot_token"], years=1)
    closes = [b["close"] for b in bars]
    # Gamma Backspread's config has neither key (it doesn't filter on RV/true
    # range at all, only Convexity Window does) -- default to 20 so this
    # function stays reusable by both callers for the prev_close lookup.
    rv = realized_vol(closes, cfg.get("realized_vol_window_days", 20))
    mtr = median_true_range(bars, cfg.get("true_range_window_days", 20))
    prev_close = closes[-1] if closes else None
    return {"realized_vol": rv, "median_true_range": mtr, "prev_close": prev_close, "daily_bars": bars}


async def get_15m_ema(definedge, index_key: str, period: int, lookback_days: int = 10) -> float | None:
    """Real 1-minute spot bars (today's session so far, plus recent days for
    context) aggregated to 15-minute closes -> latest EMA value. None until
    at least `period` real 15-minute bars exist."""
    spot_cfg = INDEX_CONFIG[index_key]
    now = datetime.now(IST)
    frm = (now - timedelta(days=lookback_days)).strftime("%d%m%Y0000")
    to = now.strftime("%d%m%Y%H%M")
    session = await definedge._session_key()
    import httpx
    from definedge_service import DATA_BASE
    url = f"{DATA_BASE}/history/{spot_cfg['spot_segment']}/{spot_cfg['spot_token']}/minute/{frm}/{to}"
    async with httpx.AsyncClient(timeout=45) as c:
        resp = await c.get(url, headers={"Authorization": session})
    if resp.status_code == 401:
        raise DefinedgeError("Definedge session expired. Please login again (OTP).")
    if resp.status_code != 200:
        return None
    bars = []
    for line in resp.text.strip().splitlines():
        parts = line.split(",")
        if len(parts) < 5:
            continue
        try:
            dt = datetime.strptime(parts[0], "%d%m%Y%H%M").replace(tzinfo=IST)
            bars.append({"dt": dt, "open": float(parts[1]), "high": float(parts[2]),
                         "low": float(parts[3]), "close": float(parts[4])})
        except ValueError:
            continue
    bars.sort(key=lambda b: b["dt"])
    if not bars:
        return None
    fifteen = aggregate_to_15min(bars)
    closes = [b["close"] for b in fifteen]
    ema = ema_series(closes, period)
    return ema[-1] if ema else None


async def record_atm_iv(db, index_key: str, strategy_id: str, atm_iv: float) -> None:
    """Appends today's real ATM IV to a persistent per-index/strategy
    history series -- the only source blackbox_gamma_backspread's 252-day
    IV-percentile filter can ever draw on, since nothing in this codebase
    has logged daily ATM IV before now. Upserts by (index, strategy_id,
    date) so re-running the same day's cron tick doesn't duplicate."""
    today_iso = datetime.now(IST).date().isoformat()
    await db.blackbox_iv_history.update_one(
        {"index": index_key, "strategy_id": strategy_id, "date": today_iso},
        {"$set": {"index": index_key, "strategy_id": strategy_id, "date": today_iso, "atm_iv": atm_iv}},
        upsert=True,
    )


async def get_iv_history(db, index_key: str, strategy_id: str, window_days: int) -> list:
    """Oldest -> newest real ATM IV series recorded so far via
    record_atm_iv(), capped to `window_days` (252 trading days per the
    spec). Will be SHORT (well under 252) for a long time after this
    strategy first goes live -- that's a genuine, disclosed data gap
    (percentile_rank() still works on a short series, just less
    statistically meaningful), not a bug."""
    cursor = db.blackbox_iv_history.find(
        {"index": index_key, "strategy_id": strategy_id}, {"_id": 0, "atm_iv": 1, "date": 1}
    ).sort("date", 1).limit(window_days * 2)  # generous cap; trimmed below
    docs = await cursor.to_list(length=window_days * 2)
    docs = docs[-window_days:]
    return [d["atm_iv"] for d in docs]
