"""Multi-market module engine — every Alpha Terminal module, run against
any market adapter.

There is exactly one implementation of each module here, and it is a thin
composition over functions that already existed and are already used by
the live India and US surfaces:

    Exitline              exitline.build_session_ladder / classify_and_suggest
                          (Camarilla H5..L5 -- exitline.compute_camarilla_levels)
    Market Breadth        breadth_engine.direction_by_date /
                          compute_breadth_series_from_directions (X-Percent,
                          1% box, 3-box reversal)
    Relative Strength     relative_strength_matrix.compute_matrix (pairwise
                          ratio P&F, x1000 scaling, 3-box reversal)
    Momentum Investing    quant_lab._compute_momentum_stats (12-1)
    Momentum Leaders      us_momentum.compute_leader_score (0.6*1w + 0.4*1m)
    Sharpe Dashboard      quant_lab._compute_risk_stats (Sharpe/Sortino/maxDD)
    EWMA Scanner          quant_lab._compute_backtest
    Gamma Pulse           options_trend_engine.three_pillar_verdict
    Index Vector          definedge_service.derive_bias_4 (the SAME 4-leg
                          confluence rule, imported, not restated)
    Peter Tingle          peter_tingle.compute_metrics_from_bars /
                          scan_technical_red_flags

None of those functions is copied, reimplemented, or parameterised
differently per market. Every box size, reversal count and threshold comes
from the module that already owned it. That is what makes the acceptance
criterion "same formula, different instrument" structurally true rather
than merely intended: there is only one copy to be right or wrong.

Two modules are NOT here, and that is a finding rather than an omission:
Swing Picks and Breakout Candidates have no formula anywhere in this
codebase. Both are curated `terminal_stocks` rows -- Swing Picks is synced
from a CSV export every 10 days and Breakout Candidates is ingested the
same way. There is no calculation to point at a different market, so they
are reported unavailable with that reason on every non-India tab (and
Breakout Candidates is already `live: false` on India itself).
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

import breadth_engine as be
import options_trend_engine as ote
import peter_tingle as pt
import quant_lab as ql
import relative_strength_matrix as rsm
import us_momentum as usm
from definedge_service import (
    ATM_LEG_BOX_PCT,
    ATM_LEG_REVERSAL_BOXES,
    BOX_PCT,
    REVERSAL_BOXES,
    derive_bias_4,
    pnf_trend,
)
from exitline import (
    HISTORY_SESSIONS,
    build_session_ladder,
    classify_and_suggest,
)
from market_adapters import AdapterError

logger = logging.getLogger(__name__)

MAX_CONCURRENT_FETCHES = 5

# Modules with no computable definition anywhere in this codebase -- see
# module docstring. Keyed by the frontend's own module slug.
NO_FORMULA = {
    "swing-picks": "Swing Picks is a curated pick list synced from a CSV export every 10 days, "
                   "not a computed scan — there is no formula in this codebase to run against "
                   "another market's instruments.",
    "breakout-candidates": "Breakout Candidates is served from curated ingested rows, not a "
                           "computed scan — there is no formula in this codebase to port.",
}


def _fail(module: str, reason: str) -> dict:
    return {"available": False, "module": module, "reason": reason}


# ---------------------------------------------------------------------------
# Exitline
# ---------------------------------------------------------------------------
async def exitline(adapter, db, symbol: str, interval_minutes: int = 5) -> dict:
    """Identical Camarilla ladder and zone/SL/TP classification as the
    India and US modules -- build_session_ladder and classify_and_suggest
    are imported from exitline.py, not restated.

    The only per-market input is the session boundary: a 24h market
    (crypto, forex) passes session_open_minutes=0, so the active session
    rolls at 00:00 UTC, which is the boundary its own daily bars use."""
    symbol = symbol.strip().upper()
    bars = await adapter.daily_bars(db, symbol)
    now_local = datetime.now(timezone.utc).astimezone(adapter.tz)
    sessions = build_session_ladder(bars, now_local, adapter.session_open_minutes)
    if not sessions:
        raise AdapterError(f"No price history for {symbol}.")
    active = sessions[-1]

    try:
        ltp = await adapter.latest_price(symbol)
    except AdapterError as e:
        logger.info("Exitline (%s): no live price for %s: %s", adapter.market_id, symbol, e)
        ltp = None

    try:
        chart = await adapter.intraday_bars(symbol, interval_minutes, HISTORY_SESSIONS + 15)
    except AdapterError as e:
        logger.info("Exitline (%s): no intraday chart for %s: %s", adapter.market_id, symbol, e)
        chart = []

    if ltp is None:
        zone = {
            "zone": None, "zone_label": "Live Price Unavailable", "bias": "Neutral",
            "sl": None, "tp": None, "tp_alt": None, "trail_stop": False,
            "reason": "No live quote right now — levels are still shown against the previous "
                      "session's close; zone/SL/TP need a live price.",
            "commentary": None,
        }
    else:
        zone = classify_and_suggest(active["levels"], ltp, active["close"])

    return {
        "market": adapter.market_id, "symbol": symbol,
        "prev_date": active["prev_date"],
        "high": active["high"], "low": active["low"], "close": active["close"],
        "levels": active["levels"], "active_date": active["date"],
        "sessions": sessions, "ltp": ltp, "chart": chart, **zone,
    }


# ---------------------------------------------------------------------------
# Market Breadth (X-Percent)
# ---------------------------------------------------------------------------
def _breadth_collection(market: str) -> str:
    return f"{market}_breadth_x_percent_cache"


def _breadth_status_collection(market: str) -> str:
    return f"{market}_breadth_refresh_status"


async def breadth_refresh(adapter, db, group: str) -> dict:
    """One full pass over a group, mirroring breadth_routes._refresh_group
    and us_breadth.refresh exactly: bounded concurrency, per-symbol guard,
    and each symbol's raw close history discarded as soon as its direction
    map is computed so the whole universe is never resident at once."""
    symbols = await adapter.group_members(db, group)
    if not symbols:
        raise AdapterError(f"No members in group '{group}'.")
    total = len(symbols)
    now_iso = datetime.now(timezone.utc).isoformat()
    status_key = {"market": adapter.market_id, "group": group}

    await db[_breadth_status_collection(adapter.market_id)].update_one(
        status_key,
        {"$set": {**status_key, "status": "running", "started_at": now_iso, "completed_at": None,
                  "total": total, "done": 0, "resolved": 0, "failed": 0}},
        upsert=True,
    )

    semaphore = asyncio.Semaphore(MAX_CONCURRENT_FETCHES)
    counters = {"done": 0, "resolved": 0, "failed": 0}
    lock = asyncio.Lock()
    directions_by_symbol: dict = {}

    async def worker(symbol):
        try:
            async with semaphore:
                closes = await adapter.daily_closes(db, symbol)
            directions = be.direction_by_date(closes) if closes else None
            async with lock:
                counters["done"] += 1
                if directions:
                    counters["resolved"] += 1
                    directions_by_symbol[symbol] = directions
                else:
                    counters["failed"] += 1
        except Exception:  # noqa: BLE001 — one bad symbol must not sink the pass
            async with lock:
                counters["done"] += 1
                counters["failed"] += 1

    await asyncio.gather(*(worker(s) for s in symbols))

    series = be.compute_breadth_series_from_directions(directions_by_symbol, total=total) if directions_by_symbol else []
    await db[_breadth_collection(adapter.market_id)].update_one(
        {"market": adapter.market_id, "group": group},
        {"$set": {
            "market": adapter.market_id, "group": group, "series": series,
            "universe_total": total, "universe_resolved": counters["resolved"],
            "box_pct": be.DEFAULT_BOX_PCT, "reversal_boxes": be.DEFAULT_REVERSAL,
            "computed_at": datetime.now(timezone.utc).isoformat(),
        }},
        upsert=True,
    )
    await db[_breadth_status_collection(adapter.market_id)].update_one(
        status_key, {"$set": {"status": "done", "completed_at": datetime.now(timezone.utc).isoformat(),
                              **{k: counters[k] for k in ("done", "resolved", "failed")}}},
    )
    return {"group": group, "resolved": counters["resolved"], "total": total, "points": len(series)}


async def breadth_read(adapter, db, group: str) -> dict:
    doc = await db[_breadth_collection(adapter.market_id)].find_one(
        {"market": adapter.market_id, "group": group}, {"_id": 0})
    status = await db[_breadth_status_collection(adapter.market_id)].find_one(
        {"market": adapter.market_id, "group": group}, {"_id": 0})
    if not doc:
        return {"has_data": False, "group": group, "status": (status or {}).get("status", "never_run"),
                "groups": adapter.groups()}
    return {"has_data": True, "groups": adapter.groups(), "status": (status or {}).get("status"), **doc}


# ---------------------------------------------------------------------------
# Relative Strength Engine
# ---------------------------------------------------------------------------
async def relative_strength(adapter, db, group: str, box_pct: float) -> dict:
    """Pairwise ratio P&F across a group -- compute_matrix imported from
    relative_strength_matrix.py unchanged, including its per-pair date
    alignment and x1000 ratio scaling."""
    symbols = await adapter.group_members(db, group)
    if len(symbols) < 2:
        raise AdapterError(f"Group '{group}' needs at least two members.")

    semaphore = asyncio.Semaphore(MAX_CONCURRENT_FETCHES)

    async def load(symbol):
        async with semaphore:
            return symbol, await adapter.daily_closes(db, symbol)

    loaded = await asyncio.gather(*(load(s) for s in symbols))
    closes_by_symbol = {s: c for s, c in loaded if c}
    resolved = sorted(closes_by_symbol)
    if len(resolved) < 2:
        raise AdapterError(f"Only {len(resolved)} of {len(symbols)} symbols in '{group}' returned data.")

    matrix = rsm.compute_matrix(resolved, closes_by_symbol, box_pct)
    return {
        "market": adapter.market_id, "group": group, "box_pct": box_pct,
        "reversal_boxes": rsm.DEFAULT_REVERSAL,
        "symbols": resolved, "universe_total": len(symbols), "universe_resolved": len(resolved),
        "computed_at": datetime.now(timezone.utc).isoformat(), **matrix,
    }


# ---------------------------------------------------------------------------
# Momentum Investing (12-1) and Momentum Leaders (1w/1m)
# ---------------------------------------------------------------------------
async def _rank_universe(adapter, db, compute, score_key: str, limit: int) -> list:
    universe = await adapter.universe(db)
    semaphore = asyncio.Semaphore(MAX_CONCURRENT_FETCHES)

    async def worker(entry):
        symbol = entry["symbol"]
        try:
            async with semaphore:
                bars = await adapter.daily_bars(db, symbol)
        except Exception:  # noqa: BLE001
            return None
        result = compute(bars)
        if result is None:
            return None
        return {"symbol": symbol, "name": entry.get("name"), "group": entry.get("group"), **result}

    rows = [r for r in await asyncio.gather(*(worker(e) for e in universe)) if r]
    rows.sort(key=lambda r: r[score_key], reverse=True)
    return rows[:limit]


def _momentum_investing_compute(bars: list):
    stats = ql._compute_momentum_stats(bars)
    if not stats or stats["stats"].get("momentum_score") is None:
        return None
    return {"momentum_score": stats["stats"]["momentum_score"],
            "return_12_1": stats["stats"]["return_12_1"],
            "volatility": stats["stats"]["volatility"],
            "bars_used": stats["bars_used"]}


def _momentum_leader_compute(bars: list):
    metrics = pt.compute_metrics_from_bars(bars)
    score = usm.compute_leader_score(metrics) if metrics else None
    if score is None:
        return None
    return {"score": score, "return_1w": metrics.get("return_1w"), "return_1m": metrics.get("return_1m")}


async def momentum_investing(adapter, db, limit: int = 20) -> dict:
    rows = await _rank_universe(adapter, db, _momentum_investing_compute, "momentum_score", limit)
    return {"market": adapter.market_id, "rows": rows,
            "methodology": "Trailing 12-month return excluding the most recent month, divided by "
                           "realized volatility over the same window.",
            "computed_at": datetime.now(timezone.utc).isoformat()}


async def momentum_leaders(adapter, db, limit: int = 20) -> dict:
    rows = await _rank_universe(adapter, db, _momentum_leader_compute, "score", limit)
    return {"market": adapter.market_id, "rows": rows,
            "methodology": "0.6 x 1-week return + 0.4 x 1-month return.",
            "computed_at": datetime.now(timezone.utc).isoformat()}


# ---------------------------------------------------------------------------
# Sharpe Dashboard
# ---------------------------------------------------------------------------
async def sharpe(adapter, db, symbols: list | None = None, limit: int = 20) -> dict:
    def compute(bars):
        stats = ql._compute_risk_stats(bars, risk_free_rate=adapter.risk_free_rate)
        if not stats or stats["stats"].get("sharpe") is None:
            return None
        return {**stats["stats"], "bars_used": stats["bars_used"],
                "history_from": stats["history_from"], "history_to": stats["history_to"]}

    if symbols:
        rows = []
        for symbol in symbols:
            try:
                bars = await adapter.daily_bars(db, symbol.strip().upper())
            except AdapterError:
                continue
            result = compute(bars)
            if result:
                rows.append({"symbol": symbol.strip().upper(), **result})
        rows.sort(key=lambda r: r["sharpe"], reverse=True)
    else:
        rows = await _rank_universe(adapter, db, compute, "sharpe", limit)

    return {"market": adapter.market_id, "rows": rows,
            "risk_free_rate": adapter.risk_free_rate,
            "computed_at": datetime.now(timezone.utc).isoformat()}


# ---------------------------------------------------------------------------
# EWMA Scanner
# ---------------------------------------------------------------------------
async def ewma(adapter, db, symbol: str, fast_span: int = 20, slow_span: int = 50) -> dict:
    symbol = symbol.strip().upper()
    bars = await adapter.daily_bars(db, symbol)
    result = ql._compute_backtest(bars, fast_span, slow_span)
    if result is None:
        raise AdapterError(
            f"{symbol} has {len(bars)} bars — not enough history for a {fast_span}/{slow_span} "
            f"crossover evaluation (needs at least {2 * slow_span + ql.MIN_EVALUATED_BARS})."
        )
    return {"market": adapter.market_id, "symbol": symbol,
            "fast_span": fast_span, "slow_span": slow_span, **result}


# ---------------------------------------------------------------------------
# Gamma Pulse (three-pillar)
# ---------------------------------------------------------------------------
async def gamma_pulse(adapter, db, symbol: str) -> dict:
    """Same three-pillar agreement rule and same box parameters as the
    India module -- leg_direction and three_pillar_verdict are imported
    from options_trend_engine.py.

    `leg_bars` is returned so the UI can distinguish "the legs disagreed"
    from "a leg had too little history to have a direction at all". Both
    read Neutral by design, but they mean different things, and a listed
    option's short lifespan makes the second case genuinely common outside
    India (see alpaca_options_client.py's docstring)."""
    if not adapter.supports_options:
        return _fail("options-trend-scanner",
                     adapter.unavailable.get("options-trend-scanner", "No options chain available."))

    symbol = symbol.strip().upper()
    legs = await adapter.atm_legs(db, symbol)
    future_closes = await adapter.future_closes(db, symbol)
    call_closes = await adapter.option_leg_closes(legs["call"])
    put_closes = await adapter.option_leg_closes(legs["put"])

    future_dir = ote.leg_direction(future_closes, ote.FUTURE_BOX_PCT, ote.FUTURE_REVERSAL)
    call_dir = ote.leg_direction(call_closes, ote.OPTION_BOX_PCT, ote.OPTION_REVERSAL)
    put_dir = ote.leg_direction(put_closes, ote.OPTION_BOX_PCT, ote.OPTION_REVERSAL)
    verdict = ote.three_pillar_verdict(future_dir, call_dir, put_dir)

    return {
        "available": True, "market": adapter.market_id, "symbol": symbol,
        "verdict": verdict,
        "spot": legs["spot"], "strike": legs["strike"], "expiry": legs["expiry_date"],
        "expiry_is_monthly": legs.get("expiry_is_monthly"),
        "is_proxy": legs.get("is_proxy"), "proxy_label": legs.get("proxy_label"),
        "legs": {
            "future": {"direction": future_dir, "bars": len(future_closes)},
            "call": {"direction": call_dir, "bars": len(call_closes)},
            "put": {"direction": put_dir, "bars": len(put_closes)},
        },
        "box": {"future_pct": ote.FUTURE_BOX_PCT, "option_pct": ote.OPTION_BOX_PCT,
                "reversal": ote.OPTION_REVERSAL},
        "computed_at": datetime.now(timezone.utc).isoformat(),
    }


# ---------------------------------------------------------------------------
# Index Vector (4-leg confluence)
# ---------------------------------------------------------------------------
# The India module reads two straddles (one strike above ATM, one below)
# plus the ATM call and ATM put individually, and requires ALL FOUR to
# agree. Straddle legs use 0.5% box / 3-box reversal; the ATM CE/PE legs
# use 3% / 3. Every one of those constants is imported from
# definedge_service, and the verdict comes from its own derive_bias_4.
#
# One parameter genuinely has to be generalised, and is flagged rather
# than hidden (same convention as options_trend_engine.FUTURE_BOX_PCT):
# India offsets the straddle strikes by a FIXED +/-200 index points. On
# NIFTY (~25,000) that is ~0.8% of spot. An absolute point offset is
# meaningless across instruments priced from 1.05 (EURUSD) to 63,000
# (BTC), so the offset is applied as that same ~0.8% of spot and then
# snapped to the nearest ACTUALLY LISTED strike -- preserving the
# moneyness relationship the rule is really about, and never inventing a
# strike that isn't listed.
STRADDLE_OFFSET_PCT = 0.008  # 200 / 25000, the India offset expressed as moneyness


def _nearest_strike(strikes: list, target: float) -> float | None:
    return min(strikes, key=lambda s: abs(s - target)) if strikes else None


async def _straddle_series(adapter, call_leg: dict, put_leg: dict) -> list:
    """Combined CE+PE premium per date, aligned by date (never by list
    position -- the two legs routinely have different bar counts)."""
    call_by_date = await adapter.leg_closes_by_date(call_leg)
    put_by_date = await adapter.leg_closes_by_date(put_leg)
    shared = sorted(set(call_by_date) & set(put_by_date))
    return [call_by_date[d] + put_by_date[d] for d in shared]


async def index_vector(adapter, db, symbol: str) -> dict:
    if not adapter.supports_options:
        return _fail("index-vector", adapter.unavailable.get("index-vector", "No options chain available."))

    symbol = symbol.strip().upper()
    snapshot = await adapter.options_snapshot(db, symbol)
    spot, by_strike = snapshot["spot"], snapshot["by_strike"]
    paired = sorted(s for s, sides in by_strike.items() if "call" in sides and "put" in sides)
    if len(paired) < 3:
        raise AdapterError(f"{symbol} has only {len(paired)} strikes with both a call and a put listed.")

    atm_strike = _nearest_strike(paired, spot)
    up_strike = _nearest_strike([s for s in paired if s > atm_strike], spot * (1 + STRADDLE_OFFSET_PCT)) \
        or _nearest_strike(paired, spot * (1 + STRADDLE_OFFSET_PCT))
    down_strike = _nearest_strike([s for s in paired if s < atm_strike], spot * (1 - STRADDLE_OFFSET_PCT)) \
        or _nearest_strike(paired, spot * (1 - STRADDLE_OFFSET_PCT))

    up_series, down_series, atm_ce, atm_pe = await asyncio.gather(
        _straddle_series(adapter, by_strike[up_strike]["call"], by_strike[up_strike]["put"]),
        _straddle_series(adapter, by_strike[down_strike]["call"], by_strike[down_strike]["put"]),
        adapter.option_leg_closes(by_strike[atm_strike]["call"]),
        adapter.option_leg_closes(by_strike[atm_strike]["put"]),
    )

    up_trend = pnf_trend(up_series, BOX_PCT, REVERSAL_BOXES)
    down_trend = pnf_trend(down_series, BOX_PCT, REVERSAL_BOXES)
    ce_trend = pnf_trend(atm_ce, ATM_LEG_BOX_PCT, ATM_LEG_REVERSAL_BOXES)
    pe_trend = pnf_trend(atm_pe, ATM_LEG_BOX_PCT, ATM_LEG_REVERSAL_BOXES)
    bias = derive_bias_4(up_trend, down_trend, ce_trend, pe_trend)

    return {
        "available": True, "market": adapter.market_id, "index": symbol, "bias": bias,
        "spot": spot, "atm": atm_strike, "up_strike": up_strike, "down_strike": down_strike,
        "expiry": snapshot["expiry"],
        "is_proxy": snapshot.get("is_proxy"), "proxy_label": snapshot.get("proxy_label"),
        "legs": {
            "up_straddle": {"trend": up_trend, "bars": len(up_series)},
            "down_straddle": {"trend": down_trend, "bars": len(down_series)},
            "atm_call": {"trend": ce_trend, "bars": len(atm_ce)},
            "atm_put": {"trend": pe_trend, "bars": len(atm_pe)},
        },
        "box_size": f"{BOX_PCT * 100:g}%", "reversal": f"{REVERSAL_BOXES} box",
        "atm_leg_box_size": f"{ATM_LEG_BOX_PCT * 100:g}%",
        "atm_leg_reversal": f"{ATM_LEG_REVERSAL_BOXES} box",
        "computed_at": datetime.now(timezone.utc).isoformat(),
    }


# ---------------------------------------------------------------------------
# Peter Tingle
# ---------------------------------------------------------------------------
async def peter_tingle(adapter, db, symbol: str) -> dict:
    """Technical scan is market-agnostic and runs unchanged. The
    fundamental scan is not: it reads a balance sheet, and a currency pair
    or a token does not have one. Rather than run half the module and
    present it as the whole thing, markets with no fundamentals available
    return unavailable with that reason (see each adapter's `unavailable`)."""
    reason = adapter.unavailable.get("peter-tingle")
    if reason:
        return _fail("peter-tingle", reason)

    symbol = symbol.strip().upper()
    bars = await adapter.daily_bars(db, symbol)
    metrics = pt.compute_metrics_from_bars(bars)
    if not metrics:
        raise AdapterError(f"Not enough price history for {symbol}.")
    technical_flags = pt.scan_technical_red_flags(metrics)

    fundamental_flags = []
    if adapter.market_id == "us":
        try:
            import us_stock_fundamentals as usf
            fundamentals = await usf.fetch_fundamentals(db, symbol)
            if fundamentals:
                fundamental_flags = pt.scan_us_fundamental_red_flags(fundamentals)
        except Exception as e:  # noqa: BLE001 — fundamentals are additive; never sink the technical scan
            logger.info("Peter Tingle (us): fundamentals unavailable for %s: %s", symbol, e)

    return {
        "available": True, "market": adapter.market_id, "symbol": symbol,
        "verdict": pt.combine_verdict(technical_flags, fundamental_flags),
        "technical_flags": technical_flags, "fundamental_flags": fundamental_flags,
        "metrics": metrics,
        "computed_at": datetime.now(timezone.utc).isoformat(),
    }
