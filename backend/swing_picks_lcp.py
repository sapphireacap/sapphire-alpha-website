"""
Swing Picks LCP refresh — once/day, after market close (15:30 IST), updates
every "swing_picks" scanner row's `lcp` field with that day's real EOD close
from Definedge. The pick list itself (ticker/company/buy_at) is refreshed
separately, every 10 days, by the local swing_picks_sync.py script reading
the CSV export — this only touches `lcp`.

Reads the closing print from daily_history() rather than a live LTP quote:
daily_history's EOD bar is the authoritative settled close, immune to any
lag/staleness a quote endpoint might have right at/after the 15:30 cutoff —
same reasoning momentum_track_record.py's evaluate_pending() already uses
for exactly this kind of "read today's real close" step.
"""
import logging
from datetime import datetime, timezone, timedelta

logger = logging.getLogger(__name__)
IST = timezone(timedelta(hours=5, minutes=30))


async def update_swing_picks_lcp(db, definedge) -> dict:
    stocks = await db.terminal_stocks.find({"scanner": "swing_picks"}, {"_id": 0}).to_list(500)
    if not stocks:
        return {"updated": 0, "failed": 0, "total": 0}

    today = datetime.now(IST).date().isoformat()
    updated, failed = 0, 0
    try:
        master = await definedge._get_all_master()
    except Exception as e:  # noqa: BLE001
        logger.warning("Swing Picks LCP update: could not load master file: %s", e)
        return {"updated": 0, "failed": len(stocks), "total": len(stocks)}

    for stock in stocks:
        try:
            resolved = definedge.resolve_symbol(master, "NSE", stock["ticker"])
            if not resolved:
                logger.warning("Swing Picks LCP update: could not resolve %s on NSE, skipping.", stock["ticker"])
                failed += 1
                continue
            bars = await definedge.daily_history("NSE", resolved["token"], years=1)
            bar = next((b for b in bars if b["date"] == today), None)
            if not bar:
                logger.warning("Swing Picks LCP update: no EOD bar for %s today (%s) yet.", stock["ticker"], today)
                failed += 1
                continue
            await db.terminal_stocks.update_one({"id": stock["id"]}, {"$set": {"lcp": str(bar["close"])}})
            updated += 1
        except Exception as e:  # noqa: BLE001 — one stock's failure must not stop the rest
            logger.warning("Swing Picks LCP update: failed for %s: %s", stock.get("ticker"), e)
            failed += 1

    return {"updated": updated, "failed": failed, "total": len(stocks)}
