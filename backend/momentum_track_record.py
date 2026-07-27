"""
Historical performance tracking for scanner recommendations — currently only
"momentum" (Intraday Momentum Leaders), the one scanner with a real live
feed (see the `momentum_sync_script` memory note: the others have no data
source yet).

Flow:
  1. Whenever the scanner's stock list is replaced (POST
     /admin/terminal/scanner/replace, called once/day by the external sync
     script — see momentum_sync_script memory), capture_entries() records
     each stock's live price at that exact moment as its entry price,
     tagged with the bias the scanner gave it (Bullish/Bearish) and today's
     date. That moment IS "9:40am" for all practical purposes, since that's
     when the daily sync runs — no separate timing logic needed.
  2. Once that trading day has closed (15:30 IST), evaluate_pending() fetches
     the day's real OHLC bar for each pending stock and computes how the
     call actually performed, via compute_performance() below.

Bullish/Bearish scoring — the actual "logic for bullish and bearish scrips":
  - A Bullish call profits if price rises: performance_pct = (close-entry)/entry*100.
  - A Bearish call profits if price falls: performance_pct = (entry-close)/entry*100
    — mirrored, so a decline shows as a POSITIVE performance number, the
    same convention as scoring a short position (this is deliberate: a
    single "performance_pct > 0 = correct" rule then works for both
    directions without a second branch anywhere else in the codebase).
  - best_case/worst_case mirror the same way using the day's high/low: a
    Bullish call's best case is the day's high (how far it could have run),
    worst case is the day's low; a Bearish call's best case is the day's
    low (how far it could have fallen), worst case is the day's high.
  - "correct" = performance_pct > 0, i.e. the call resolved in the
    predicted direction by that day's close.
"""
import logging
import uuid
from datetime import datetime, timezone, timedelta

logger = logging.getLogger(__name__)
IST = timezone(timedelta(hours=5, minutes=30))
MARKET_CLOSE_MINUTES = 15 * 60 + 30  # 15:30 IST


def compute_performance(bias: str, entry: float, close: float, low: float, high: float) -> dict:
    """Pure, unit-testable — see module docstring for the actual rule."""
    if bias == "Bullish":
        performance_pct = (close - entry) / entry * 100
        best_case_pct = (high - entry) / entry * 100
        worst_case_pct = (low - entry) / entry * 100
    else:  # Bearish
        performance_pct = (entry - close) / entry * 100
        best_case_pct = (entry - low) / entry * 100
        worst_case_pct = (entry - high) / entry * 100
    return {
        "performance_pct": performance_pct,
        "best_case_pct": best_case_pct,
        "worst_case_pct": worst_case_pct,
        "correct": performance_pct > 0,
    }


def _market_closed(date_iso: str) -> bool:
    """Whether the trading session for `date_iso` has already ended — past
    dates are always closed; today is closed only once it's actually past
    15:30 IST. (Doesn't check whether `date_iso` was itself a trading day —
    a weekend/holiday date would just never resolve a real OHLC bar in
    evaluate_pending() and stay pending harmlessly, rather than needing a
    holiday calendar here too.)"""
    today = datetime.now(IST).date()
    target = datetime.strptime(date_iso, "%Y-%m-%d").date()
    if target < today:
        return True
    if target > today:
        return False
    now = datetime.now(IST)
    return (now.hour * 60 + now.minute) >= MARKET_CLOSE_MINUTES


async def capture_entries(db, definedge, scanner: str, stocks: list):
    """Best-effort — called right after a scanner's rows are replaced. Never
    raises: a Definedge hiccup here must not break the actual scanner
    update, which is the primary purpose of that request. Idempotent per
    (scanner, date, ticker) — a second replace call the same day never
    overwrites a real already-captured entry price with a later one."""
    if not definedge.configured():
        return
    today = datetime.now(IST).date().isoformat()
    try:
        master = await definedge._get_all_master()
    except Exception as e:  # noqa: BLE001
        logger.warning("Track record: could not load master file, skipping entry capture: %s", e)
        return

    for s in stocks:
        ticker = (s.get("ticker") or "").strip().upper()
        bias = s.get("bias")
        if not ticker or bias not in ("Bullish", "Bearish"):
            continue  # Neutral calls aren't scored -- there's no direction to grade

        key = {"scanner": scanner, "date": today, "ticker": ticker}
        if await db.scanner_track_record.find_one(key):
            continue

        try:
            resolved = definedge.resolve_symbol(master, "NSE", ticker)
            if not resolved:
                logger.warning("Track record: could not resolve %s on NSE, skipping.", ticker)
                continue
            entry_price = await definedge.equity_quote("NSE", resolved["token"])
        except Exception as e:  # noqa: BLE001
            logger.warning("Track record: could not fetch entry price for %s: %s", ticker, e)
            continue

        await db.scanner_track_record.update_one(
            key,
            {"$set": {
                "id": str(uuid.uuid4()),
                "scanner": scanner,
                "date": today,
                "ticker": ticker,
                "company": s.get("company", ""),
                "bias": bias,
                "entry_price": entry_price,
                "entry_time": datetime.now(timezone.utc).isoformat(),
                "status": "pending",
            }},
            upsert=True,
        )


async def evaluate_pending(db, definedge, scanner: str = None) -> dict:
    """Fills in close/low/high + performance for every 'pending' record
    whose trading day has already closed. Safe to call repeatedly (already-
    evaluated records are untouched) and safe to call mid-day (records for
    a day still in session are simply left pending, counted separately)."""
    query = {"status": "pending"}
    if scanner:
        query["scanner"] = scanner
    pending = await db.scanner_track_record.find(query, {"_id": 0}).to_list(2000)

    master = None
    evaluated, not_closed, failed = 0, 0, 0
    for rec in pending:
        if not _market_closed(rec["date"]):
            not_closed += 1
            continue
        try:
            if master is None:
                master = await definedge._get_all_master()
            resolved = definedge.resolve_symbol(master, "NSE", rec["ticker"])
            if not resolved:
                failed += 1
                continue
            bars = await definedge.daily_history("NSE", resolved["token"], years=1)
            bar = next((b for b in bars if b["date"] == rec["date"]), None)
            if not bar:
                failed += 1
                continue
            perf = compute_performance(rec["bias"], rec["entry_price"], bar["close"], bar["low"], bar["high"])
            await db.scanner_track_record.update_one(
                {"id": rec["id"]},
                {"$set": {
                    "close_price": bar["close"], "low_price": bar["low"], "high_price": bar["high"],
                    **perf,
                    "status": "evaluated",
                    "evaluated_at": datetime.now(timezone.utc).isoformat(),
                }},
            )
            evaluated += 1
        except Exception as e:  # noqa: BLE001
            logger.warning("Track record: failed to evaluate %s %s: %s", rec.get("ticker"), rec.get("date"), e)
            failed += 1

    return {"evaluated": evaluated, "not_yet_closed": not_closed, "failed": failed, "total_pending": len(pending)}


def _stats_for(rows: list) -> dict:
    if not rows:
        return {"count": 0, "win_rate": None, "avg_performance_pct": None}
    wins = sum(1 for r in rows if r["correct"])
    return {
        "count": len(rows),
        "win_rate": wins / len(rows),
        "avg_performance_pct": sum(r["performance_pct"] for r in rows) / len(rows),
    }


async def get_track_record_summary(db, scanner: str) -> dict:
    """Aggregate win-rate/performance stats plus the most recent evaluated
    calls, date-wise — feeds the public Historical Performance display."""
    docs = await db.scanner_track_record.find(
        {"scanner": scanner, "status": "evaluated"}, {"_id": 0}
    ).sort("date", -1).limit(500).to_list(500)

    if not docs:
        return {"has_data": False}

    bullish = [d for d in docs if d["bias"] == "Bullish"]
    bearish = [d for d in docs if d["bias"] == "Bearish"]

    return {
        "has_data": True,
        "since": docs[-1]["date"],
        "overall": _stats_for(docs),
        "bullish": _stats_for(bullish),
        "bearish": _stats_for(bearish),
        "recent": docs[:60],
    }
