"""
Quant Lab — EWMA Crossover backtester (first of several Quant Lab tools).
Mounted under /api by server.py via create_quant_lab_router(db, definedge),
same factory pattern as journal_routes.py/journal_analytics.py (avoids a
circular import with server.py). Public — no auth, like the other
/terminal/* endpoints Quant Lab sits alongside on the Alpha Terminal page.

Backtest design notes (a review pass caught real bugs in the first draft,
fixed here):
  - ewm(span=..., adjust=False) — matches how you'd compute this incrementally
    off a live feed, not just a backtest convenience.
  - position = signal.shift(1): yesterday's crossover state decides today's
    position, so today's return is never earned off information only known
    at today's close (no lookahead). Both signal and execution price are
    still the same day's close (no open-price execution modeling) — a stated
    simplification surfaced in the response, not hidden.
  - Warmup bias: EWMA carries no NaN after its seed bar (unlike SMA), so the
    first ~2*slow_span bars have a slow EWMA still pulled toward its seed
    value. Left in, they'd unfairly pad both the strategy and buy-and-hold
    comparison with a noisy window. Fixed by truncating the *return*
    comparison to start 2*slow_span bars in and rebasing both equity curves
    to 1.0 there; the full series (including warmup) still renders on the
    chart since seeing it is fine, it just isn't scored.
  - .diff() on the signal produces NaN on the first bar; dropna() before
    reading crossover points off it.
  - .cumprod() (not .prod()) so the total-return number comes with a real
    equity path, not just a discarded final scalar.
"""
import asyncio
import csv
import io
import logging
import math
from datetime import datetime, timezone, timedelta
from typing import List, Optional

import httpx
import pandas as pd
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from definedge_service import DefinedgeError
from pricing import RISK_FREE_RATE

logger = logging.getLogger(__name__)
IST = timezone(timedelta(hours=5, minutes=30))
MIN_EVALUATED_BARS = 30  # minimum post-warmup bars required for a meaningful return comparison

BROWSER_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)


class EwmaCrossoverRequest(BaseModel):
    segment: str
    symbol: str
    fast_span: int = Field(default=20, ge=2, le=500)
    slow_span: int = Field(default=50, ge=3, le=1000)


def _clean(v):
    """NaN/Infinity don't survive JSON encoding cleanly — collapse them to
    None rather than letting FastAPI's default encoder trip over them."""
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def _compute_backtest(bars: list, fast_span: int, slow_span: int):
    """Pure function, no I/O — returns None if there isn't enough data for a
    meaningful evaluation, otherwise the full response payload minus the
    resolved-symbol/segment/caching metadata the route adds."""
    df = pd.DataFrame(bars)
    if len(df) < 2 * slow_span + MIN_EVALUATED_BARS:
        return None

    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date").reset_index(drop=True)
    close = df["close"]

    fast = close.ewm(span=fast_span, adjust=False).mean()
    slow = close.ewm(span=slow_span, adjust=False).mean()
    signal = fast > slow
    position = signal.shift(1).fillna(False)

    daily_return = close.pct_change()
    strategy_return = daily_return * position.astype(float)

    warmup = 2 * slow_span
    eval_daily = daily_return.iloc[warmup:].fillna(0.0)
    eval_strategy = strategy_return.iloc[warmup:].fillna(0.0)

    equity_buyhold = (1 + eval_daily).cumprod()
    equity_strategy = (1 + eval_strategy).cumprod()

    buyhold_return = float(equity_buyhold.iloc[-1] - 1) if len(equity_buyhold) else 0.0
    strategy_total_return = float(equity_strategy.iloc[-1] - 1) if len(equity_strategy) else 0.0

    position_changes = position.diff().dropna()
    markers = []
    for idx in position_changes[position_changes != 0].index:
        markers.append({
            "date": df["date"].iloc[idx].date().isoformat(),
            "type": "buy" if position_changes.loc[idx] > 0 else "sell",
            "price": _clean(close.iloc[idx]),
        })

    series = []
    for i in range(len(df)):
        series.append({
            "date": df["date"].iloc[i].date().isoformat(),
            "close": _clean(close.iloc[i]),
            "ewma_fast": _clean(fast.iloc[i]),
            "ewma_slow": _clean(slow.iloc[i]),
        })

    return {
        "series": series,
        "markers": markers,
        "evaluated_from": df["date"].iloc[warmup].date().isoformat(),
        "evaluated_to": df["date"].iloc[-1].date().isoformat(),
        "evaluated_bars": len(eval_daily),
        "history_from": df["date"].iloc[0].date().isoformat(),
        "history_to": df["date"].iloc[-1].date().isoformat(),
        "stats": {
            "strategy_return": _clean(strategy_total_return),
            "buy_and_hold_return": _clean(buyhold_return),
        },
    }


# ---------------------------------------------------------------------------
# Sharpe Ratio Dashboard (second Quant Lab tool) — Nifty 500 universe
# ---------------------------------------------------------------------------
NIFTY500_CSV_URL = "https://nsearchives.nseindia.com/content/indices/ind_nifty500list.csv"
TRADING_DAYS_PER_YEAR = 252
MIN_BARS_FOR_STATS = 252  # ~1 year — below this, Sharpe/Sortino aren't meaningful
MIN_UNIVERSE_COVERAGE = 400  # of ~500 — below this, "Top Ranked" refuses to rank off too small a sample

_nifty500_cache = None  # (date_str, list[dict]) — module-level, same per-day TTL pattern as definedge_service.py's master caches


async def _fetch_nifty500_list() -> list:
    """[{symbol, company_name, industry}, ...] from NSE's public index-
    constituent CSV — verified live, no auth needed. Same fragility caveat
    as the other unofficial NSE endpoints already relied on in ipo_routes.py:
    an archive path, not a published API, can change without notice."""
    global _nifty500_cache
    today = datetime.now(IST).strftime("%Y-%m-%d")
    if _nifty500_cache and _nifty500_cache[0] == today:
        return _nifty500_cache[1]
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.get(NIFTY500_CSV_URL, headers={"User-Agent": BROWSER_USER_AGENT})
    if r.status_code != 200:
        raise DefinedgeError(f"Nifty 500 list fetch failed (HTTP {r.status_code}).")
    rows = []
    for row in csv.DictReader(io.StringIO(r.text)):
        symbol = (row.get("Symbol") or "").strip()
        if not symbol:
            continue
        rows.append({
            "symbol": symbol,
            "company_name": (row.get("Company Name") or "").strip(),
            "industry": (row.get("Industry") or "").strip(),
        })
    _nifty500_cache = (today, rows)
    return rows


def _compute_risk_stats(bars: list, risk_free_rate: float = None) -> Optional[dict]:
    """Pure function, no I/O — mirrors _compute_backtest's contract: None
    when there isn't enough history for a meaningful read. Annualized Sharpe
    and Sortino use pricing.py's existing RISK_FREE_RATE (not reinvented),
    max drawdown from the peak-to-trough of the cumulative-return curve. A
    zero-volatility edge case (division by zero) isn't special-cased — it
    naturally produces inf/NaN, which _clean() already collapses to None.

    `risk_free_rate` defaults to pricing.RISK_FREE_RATE, which is an
    approximate INDIAN short-term rate — correct for the Nifty 500 universe
    this function was written for, and wrong for a USD-denominated one. The
    Sharpe/Sortino FORMULA is identical either way; the risk-free rate is a
    market input, like the instrument universe. Non-India callers pass their
    own (see market_adapters.MarketAdapter.risk_free_rate). Every existing
    India caller omits the argument and is therefore byte-identical to
    before this parameter existed."""
    df = pd.DataFrame(bars)
    if len(df) < MIN_BARS_FOR_STATS:
        return None

    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date").reset_index(drop=True)
    daily_return = df["close"].pct_change().dropna()
    if daily_return.empty:
        return None

    rf = RISK_FREE_RATE if risk_free_rate is None else risk_free_rate
    rf_daily = rf / TRADING_DAYS_PER_YEAR
    excess_mean = (daily_return - rf_daily).mean()
    sharpe = (excess_mean / daily_return.std()) * math.sqrt(TRADING_DAYS_PER_YEAR)

    downside = daily_return[daily_return < 0]
    sortino = (
        (excess_mean / downside.std()) * math.sqrt(TRADING_DAYS_PER_YEAR)
        if len(downside) > 1 else float("nan")
    )

    equity = (1 + daily_return).cumprod()
    max_drawdown = (equity / equity.cummax() - 1).min()

    return {
        "stats": {
            "sharpe": _clean(sharpe),
            "sortino": _clean(sortino),
            "max_drawdown": _clean(max_drawdown),
        },
        "bars_used": len(daily_return),
        "history_from": df["date"].iloc[0].date().isoformat(),
        "history_to": df["date"].iloc[-1].date().isoformat(),
    }


async def _get_or_compute_sharpe(db, definedge, master_df, symbol: str) -> Optional[dict]:
    """Cache-or-compute for one symbol — shared by both the "compare" mode
    route and the full-universe batch refresh. Returns None (never raises)
    when the symbol can't be resolved or lacks enough history, so callers
    can report it per-item rather than failing the whole request."""
    today_ist = datetime.now(IST).strftime("%Y-%m-%d")
    cached = await db.quant_lab_sharpe_cache.find_one({"symbol": symbol}, {"_id": 0})
    if cached and cached.get("computed_date") == today_ist:
        cached["cached"] = True
        return cached

    resolved = definedge.resolve_symbol(master_df, "NSE", symbol)
    if resolved is None:
        return None
    try:
        bars = await definedge.daily_history("NSE", resolved["token"], years=10)
    except DefinedgeError:
        return None
    if not bars:
        return None
    risk = _compute_risk_stats(bars)
    if risk is None:
        return None

    doc = {
        "symbol": symbol,
        "resolved_symbol": resolved.get("tradingsymbol", symbol),
        **risk,
        "computed_date": today_ist,
        "computed_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.quant_lab_sharpe_cache.update_one({"symbol": symbol}, {"$set": doc}, upsert=True)
    doc["cached"] = False
    return doc


async def _refresh_nifty500_cache(db, definedge):
    """Runs as a FastAPI BackgroundTask — refreshes every Nifty 500
    constituent's Sharpe/Sortino/max-drawdown, bounded to 5 concurrent
    Definedge requests (courteous, not hammering the broker API 500-at-once;
    a single request measured at 0.4s live, so 500 at concurrency 5 is a
    few minutes). Progress is written to quant_lab_sharpe_refresh_status as
    it goes, so the admin UI isn't staring at a black box for that long."""
    now_iso = lambda: datetime.now(timezone.utc).isoformat()  # noqa: E731
    try:
        universe = await _fetch_nifty500_list()
    except Exception as e:  # noqa: BLE001
        logger.exception("Nifty 500 list fetch failed during refresh")
        await db.quant_lab_sharpe_refresh_status.update_one(
            {"id": "current"},
            {"$set": {"id": "current", "status": "done", "completed_at": now_iso(), "error": str(e)}},
            upsert=True,
        )
        return

    total = len(universe)
    await db.quant_lab_sharpe_refresh_status.update_one(
        {"id": "current"},
        {"$set": {
            "id": "current", "status": "running", "started_at": now_iso(), "completed_at": None,
            "total": total, "done": 0, "cached": 0, "failed": 0, "error": None,
        }},
        upsert=True,
    )

    try:
        master = await definedge._get_all_master()
    except Exception as e:  # noqa: BLE001
        logger.exception("Master file fetch failed during Sharpe refresh")
        await db.quant_lab_sharpe_refresh_status.update_one(
            {"id": "current"}, {"$set": {"status": "done", "completed_at": now_iso(), "error": str(e)}}
        )
        return

    semaphore = asyncio.Semaphore(5)
    counters = {"done": 0, "cached": 0, "failed": 0}
    counters_lock = asyncio.Lock()

    async def worker(row):
        symbol = row["symbol"]
        async with semaphore:
            try:
                doc = await _get_or_compute_sharpe(db, definedge, master, symbol)
            except Exception:  # noqa: BLE001
                logger.exception("Sharpe refresh failed for %s", symbol)
                doc = None
        async with counters_lock:
            counters["done"] += 1
            counters["cached" if doc is not None else "failed"] += 1
            await db.quant_lab_sharpe_refresh_status.update_one(
                {"id": "current"},
                {"$set": {"done": counters["done"], "cached": counters["cached"], "failed": counters["failed"]}},
            )

    await asyncio.gather(*(worker(row) for row in universe))

    await db.quant_lab_sharpe_refresh_status.update_one(
        {"id": "current"}, {"$set": {"status": "done", "completed_at": now_iso()}}
    )


class SharpeDashboardRequest(BaseModel):
    mode: str  # "compare" | "top"
    symbols: Optional[List[str]] = None
    top_n: int = Field(default=10, ge=1, le=20)


# ---------------------------------------------------------------------------
# Risk-Adjusted Momentum Dashboard (Nifty 500 universe) — mirrors the Sharpe
# section above exactly (same universe fetch, cache-or-compute shape, admin
# refresh, "compare"/"top" request modes). Only _compute_momentum_stats and
# its cache/refresh wrappers differ.
#
# Methodology (standard academic momentum factor, e.g. Jegadeesh & Titman
# 1993 "12-1 momentum", used industry-wide — not tied to any one source):
#   - raw_return = trailing 12-month return, skipping the most recent 1
#     month (the "12-1" convention: the most recent month is excluded
#     because short-term price moves tend to mean-revert rather than
#     continue, which would otherwise work against a momentum read).
#   - volatility = annualized stdev of daily returns over that same
#     12-1-month window.
#   - momentum_score = raw_return / volatility — a risk-adjusted momentum
#     score, so a stock that grinds steadily higher ranks above one that
#     produced the same return through wild, choppy swings.
# ---------------------------------------------------------------------------
MOMENTUM_LOOKBACK_DAYS = 252  # ~12 months of trading days
MOMENTUM_SKIP_DAYS = 21  # ~1 month, excluded from the lookback (the "-1" in "12-1")
MIN_BARS_FOR_MOMENTUM = MOMENTUM_LOOKBACK_DAYS + MOMENTUM_SKIP_DAYS


def _compute_momentum_stats(bars: list) -> Optional[dict]:
    """Pure function, no I/O — same None-when-insufficient-history contract
    as _compute_risk_stats. The 12-1 window is [t - 252, t - 21] trading
    days back from the latest bar; daily returns within that same window
    (not the full skip-adjusted range) feed the volatility figure, since
    that's the window the return figure itself was earned over."""
    df = pd.DataFrame(bars)
    if len(df) < MIN_BARS_FOR_MOMENTUM:
        return None

    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date").reset_index(drop=True)
    close = df["close"]

    window = close.iloc[-MOMENTUM_LOOKBACK_DAYS:-MOMENTUM_SKIP_DAYS]
    if len(window) < 2:
        return None

    raw_return = float(window.iloc[-1] / window.iloc[0] - 1)
    daily_return = window.pct_change().dropna()
    if daily_return.empty:
        return None
    volatility = daily_return.std() * math.sqrt(TRADING_DAYS_PER_YEAR)
    momentum_score = raw_return / volatility if volatility else float("nan")

    return {
        "stats": {
            "momentum_score": _clean(momentum_score),
            "return_12_1": _clean(raw_return),
            "volatility": _clean(volatility),
        },
        "bars_used": len(df),
        "history_from": df["date"].iloc[0].date().isoformat(),
        "history_to": df["date"].iloc[-1].date().isoformat(),
    }


async def _get_or_compute_momentum(db, definedge, master_df, symbol: str) -> Optional[dict]:
    today_ist = datetime.now(IST).strftime("%Y-%m-%d")
    cached = await db.quant_lab_momentum_cache.find_one({"symbol": symbol}, {"_id": 0})
    if cached and cached.get("computed_date") == today_ist:
        cached["cached"] = True
        return cached

    resolved = definedge.resolve_symbol(master_df, "NSE", symbol)
    if resolved is None:
        return None
    try:
        bars = await definedge.daily_history("NSE", resolved["token"], years=10)
    except DefinedgeError:
        return None
    if not bars:
        return None
    momentum = _compute_momentum_stats(bars)
    if momentum is None:
        return None

    doc = {
        "symbol": symbol,
        "resolved_symbol": resolved.get("tradingsymbol", symbol),
        **momentum,
        "computed_date": today_ist,
        "computed_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.quant_lab_momentum_cache.update_one({"symbol": symbol}, {"$set": doc}, upsert=True)
    doc["cached"] = False
    return doc


async def _refresh_momentum_cache(db, definedge):
    """Runs as a FastAPI BackgroundTask — same shape as _refresh_nifty500_cache,
    just scoring momentum instead of Sharpe/Sortino."""
    now_iso = lambda: datetime.now(timezone.utc).isoformat()  # noqa: E731
    try:
        universe = await _fetch_nifty500_list()
    except Exception as e:  # noqa: BLE001
        logger.exception("Nifty 500 list fetch failed during momentum refresh")
        await db.quant_lab_momentum_refresh_status.update_one(
            {"id": "current"},
            {"$set": {"id": "current", "status": "done", "completed_at": now_iso(), "error": str(e)}},
            upsert=True,
        )
        return

    total = len(universe)
    await db.quant_lab_momentum_refresh_status.update_one(
        {"id": "current"},
        {"$set": {
            "id": "current", "status": "running", "started_at": now_iso(), "completed_at": None,
            "total": total, "done": 0, "cached": 0, "failed": 0, "error": None,
        }},
        upsert=True,
    )

    try:
        master = await definedge._get_all_master()
    except Exception as e:  # noqa: BLE001
        logger.exception("Master file fetch failed during momentum refresh")
        await db.quant_lab_momentum_refresh_status.update_one(
            {"id": "current"}, {"$set": {"status": "done", "completed_at": now_iso(), "error": str(e)}}
        )
        return

    semaphore = asyncio.Semaphore(5)
    counters = {"done": 0, "cached": 0, "failed": 0}
    counters_lock = asyncio.Lock()

    async def worker(row):
        symbol = row["symbol"]
        async with semaphore:
            try:
                doc = await _get_or_compute_momentum(db, definedge, master, symbol)
            except Exception:  # noqa: BLE001
                logger.exception("Momentum refresh failed for %s", symbol)
                doc = None
        async with counters_lock:
            counters["done"] += 1
            counters["cached" if doc is not None else "failed"] += 1
            await db.quant_lab_momentum_refresh_status.update_one(
                {"id": "current"},
                {"$set": {"done": counters["done"], "cached": counters["cached"], "failed": counters["failed"]}},
            )

    await asyncio.gather(*(worker(row) for row in universe))

    await db.quant_lab_momentum_refresh_status.update_one(
        {"id": "current"}, {"$set": {"status": "done", "completed_at": now_iso()}}
    )


class MomentumDashboardRequest(BaseModel):
    mode: str  # "compare" | "top"
    symbols: Optional[List[str]] = None
    top_n: int = Field(default=10, ge=1, le=20)


def create_quant_lab_router(db, definedge, get_current_admin, cron_secret: str) -> APIRouter:
    router = APIRouter(prefix="/quant-lab")

    @router.post("/ewma-crossover")
    async def ewma_crossover(payload: EwmaCrossoverRequest):
        segment = payload.segment.strip().upper()
        symbol = payload.symbol.strip().upper()
        fast_span, slow_span = payload.fast_span, payload.slow_span

        if segment not in ("NSE", "BSE", "NFO", "BFO"):
            return {"found": False, "reason": "Segment must be one of NSE, BSE, NFO, BFO."}
        if fast_span >= slow_span:
            return {"found": False, "reason": "Fast span must be smaller than slow span."}

        cache_key = {"segment": segment, "symbol": symbol, "fast_span": fast_span, "slow_span": slow_span}
        today_ist = datetime.now(IST).strftime("%Y-%m-%d")
        cached = await db.quant_lab_ewma_cache.find_one(cache_key, {"_id": 0})
        if cached and cached.get("computed_date") == today_ist:
            result = dict(cached["result"])
            result["found"] = True
            result["cached"] = True
            return result

        try:
            master = await definedge._get_all_master()
        except DefinedgeError as e:
            return {"found": False, "reason": str(e)}

        resolved = definedge.resolve_symbol(master, segment, symbol)
        if resolved is None:
            return {"found": False, "reason": f"No {segment} symbol matching '{symbol}' was found."}

        try:
            bars = await definedge.daily_history(segment, resolved["token"], years=10)
        except DefinedgeError as e:
            return {"found": False, "reason": str(e)}

        if not bars:
            return {"found": False, "reason": "No historical price data is available for this symbol."}

        backtest = _compute_backtest(bars, fast_span, slow_span)
        if backtest is None:
            return {
                "found": False,
                "reason": f"Only {len(bars)} daily bars available — not enough history for a {slow_span}-span EWMA comparison.",
            }

        result = {
            "segment": segment,
            "symbol": symbol,
            "resolved_symbol": resolved.get("tradingsymbol", symbol),
            "resolved_expiry": resolved.get("expiry"),
            "fast_span": fast_span,
            "slow_span": slow_span,
            **backtest,
        }

        await db.quant_lab_ewma_cache.update_one(
            cache_key,
            {"$set": {**cache_key, "result": result, "computed_date": today_ist,
                      "computed_at": datetime.now(timezone.utc).isoformat()}},
            upsert=True,
        )

        result["found"] = True
        result["cached"] = False
        return result

    @router.get("/nifty500-symbols")
    async def nifty500_symbols():
        try:
            return await _fetch_nifty500_list()
        except DefinedgeError as e:
            raise HTTPException(status_code=502, detail=str(e))

    @router.post("/sharpe-dashboard")
    async def sharpe_dashboard(payload: SharpeDashboardRequest):
        if payload.mode not in ("compare", "top"):
            return {"found": False, "reason": "mode must be 'compare' or 'top'."}

        if payload.mode == "compare":
            symbols = list(dict.fromkeys(s.strip().upper() for s in (payload.symbols or []) if s.strip()))
            if not (2 <= len(symbols) <= 10):
                return {"found": False, "reason": "Select between 2 and 10 symbols to compare."}

            try:
                universe = await _fetch_nifty500_list()
            except DefinedgeError as e:
                return {"found": False, "reason": str(e)}
            universe_symbols = {row["symbol"] for row in universe}

            try:
                master = await definedge._get_all_master()
            except DefinedgeError as e:
                return {"found": False, "reason": str(e)}

            results, skipped = [], []
            for sym in symbols:
                if sym not in universe_symbols:
                    skipped.append({"symbol": sym, "reason": "Not a current Nifty 500 constituent."})
                    continue
                doc = await _get_or_compute_sharpe(db, definedge, master, sym)
                if doc is None:
                    skipped.append({"symbol": sym, "reason": "Insufficient price history."})
                    continue
                results.append(doc)

            if not results:
                return {"found": False, "reason": "None of the requested symbols could be evaluated."}
            return {"found": True, "results": results, "skipped": skipped}

        # mode == "top" — ranks strictly off the pre-computed cache; 500
        # symbols is a multi-minute job, not something a request can compute inline.
        today_ist = datetime.now(IST).strftime("%Y-%m-%d")
        docs = await db.quant_lab_sharpe_cache.find({}, {"_id": 0}).to_list(600)
        fresh = [d for d in docs if d.get("computed_date") == today_ist and d.get("stats", {}).get("sharpe") is not None]
        if len(fresh) < MIN_UNIVERSE_COVERAGE:
            return {
                "found": False,
                "reason": (
                    f"Nifty 500 ranking isn't ready yet — only {len(fresh)} of ~500 constituents are cached "
                    "for today. Trigger a refresh from the admin panel, or wait for the next scheduled refresh."
                ),
            }
        ranked = sorted(fresh, key=lambda d: d["stats"]["sharpe"], reverse=True)[: payload.top_n]
        for d in ranked:
            d["cached"] = True
        return {"found": True, "results": ranked, "universe_coverage": {"cached": len(fresh), "total": len(docs)}}

    @router.get("/sharpe-refresh-status")
    async def sharpe_refresh_status():
        doc = await db.quant_lab_sharpe_refresh_status.find_one({"id": "current"}, {"_id": 0})
        return doc or {"status": "idle", "total": 0, "done": 0, "cached": 0, "failed": 0}

    @router.post("/admin/sharpe-refresh")
    async def sharpe_refresh_cron(request: Request, background_tasks: BackgroundTasks):
        """External-cron entry point (same X-Cron-Key mechanism as the
        Definedge and IPO-section cron endpoints) for the once-daily
        full-universe refresh."""
        if not cron_secret or request.headers.get("X-Cron-Key") != cron_secret:
            raise HTTPException(status_code=401, detail="Invalid cron key")
        background_tasks.add_task(_refresh_nifty500_cache, db, definedge)
        return {"status": "started"}

    @router.post("/admin/sharpe-refresh-now")
    async def sharpe_refresh_admin(background_tasks: BackgroundTasks, admin: dict = Depends(get_current_admin)):
        """Same refresh, admin-JWT-gated for the admin panel's manual button."""
        background_tasks.add_task(_refresh_nifty500_cache, db, definedge)
        return {"status": "started"}

    @router.post("/momentum-dashboard")
    async def momentum_dashboard(payload: MomentumDashboardRequest):
        if payload.mode not in ("compare", "top"):
            return {"found": False, "reason": "mode must be 'compare' or 'top'."}

        if payload.mode == "compare":
            symbols = list(dict.fromkeys(s.strip().upper() for s in (payload.symbols or []) if s.strip()))
            if not (2 <= len(symbols) <= 10):
                return {"found": False, "reason": "Select between 2 and 10 symbols to compare."}

            try:
                universe = await _fetch_nifty500_list()
            except DefinedgeError as e:
                return {"found": False, "reason": str(e)}
            universe_symbols = {row["symbol"] for row in universe}

            try:
                master = await definedge._get_all_master()
            except DefinedgeError as e:
                return {"found": False, "reason": str(e)}

            results, skipped = [], []
            for sym in symbols:
                if sym not in universe_symbols:
                    skipped.append({"symbol": sym, "reason": "Not a current Nifty 500 constituent."})
                    continue
                doc = await _get_or_compute_momentum(db, definedge, master, sym)
                if doc is None:
                    skipped.append({"symbol": sym, "reason": "Insufficient price history."})
                    continue
                results.append(doc)

            if not results:
                return {"found": False, "reason": "None of the requested symbols could be evaluated."}
            return {"found": True, "results": results, "skipped": skipped}

        # mode == "top" — ranks strictly off the pre-computed cache; 500
        # symbols is a multi-minute job, not something a request can compute inline.
        today_ist = datetime.now(IST).strftime("%Y-%m-%d")
        docs = await db.quant_lab_momentum_cache.find({}, {"_id": 0}).to_list(600)
        fresh = [d for d in docs if d.get("computed_date") == today_ist and d.get("stats", {}).get("momentum_score") is not None]
        if len(fresh) < MIN_UNIVERSE_COVERAGE:
            return {
                "found": False,
                "reason": (
                    f"Nifty 500 ranking isn't ready yet — only {len(fresh)} of ~500 constituents are cached "
                    "for today. Trigger a refresh from the admin panel, or wait for the next scheduled refresh."
                ),
            }
        ranked = sorted(fresh, key=lambda d: d["stats"]["momentum_score"], reverse=True)[: payload.top_n]
        for d in ranked:
            d["cached"] = True
        return {"found": True, "results": ranked, "universe_coverage": {"cached": len(fresh), "total": len(docs)}}

    @router.get("/momentum-refresh-status")
    async def momentum_refresh_status():
        doc = await db.quant_lab_momentum_refresh_status.find_one({"id": "current"}, {"_id": 0})
        return doc or {"status": "idle", "total": 0, "done": 0, "cached": 0, "failed": 0}

    @router.post("/admin/momentum-refresh")
    async def momentum_refresh_cron(request: Request, background_tasks: BackgroundTasks):
        """External-cron entry point, same X-Cron-Key mechanism as the Sharpe refresh."""
        if not cron_secret or request.headers.get("X-Cron-Key") != cron_secret:
            raise HTTPException(status_code=401, detail="Invalid cron key")
        background_tasks.add_task(_refresh_momentum_cache, db, definedge)
        return {"status": "started"}

    @router.post("/admin/momentum-refresh-now")
    async def momentum_refresh_admin(background_tasks: BackgroundTasks, admin: dict = Depends(get_current_admin)):
        """Same refresh, admin-JWT-gated for the admin panel's manual button."""
        background_tasks.add_task(_refresh_momentum_cache, db, definedge)
        return {"status": "started"}

    return router
