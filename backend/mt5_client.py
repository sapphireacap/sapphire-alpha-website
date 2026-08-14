"""Storage and retrieval for MT5-sourced intraday XAUUSD bars — the
intraday data source for the COMMODITY segment of the P&F and Renko
charting platforms.

Daily/weekly/monthly Gold history still comes from yahoo_finance_client.py's
GC=F futures proxy — that's unchanged and deliberate (see that module's
COMMODITY_SYMBOLS note). What Yahoo's free endpoint cannot serve at all is
real intraday gold history, and MetaTrader 5 can: this module fills exactly
that gap, the same way alpaca_client.py fills it for US stocks.

The instrument is genuinely BETTER here than the daily chart's, not worse:
MT5 serves real spot XAUUSD, while the daily/weekly/monthly chart is still
the COMEX futures proxy. That's the inverse of the US Indices situation
(where intraday drops to a tracking ETF), but it's the same class of
disclosure obligation — an intraday and a daily chart of "Gold" on this
platform are two related-but-distinct instruments, and the UI must say so.

Why bars arrive by push rather than being fetched here: MT5's Python API
(`mt5.copy_rates_from_pos`) only talks to a MetaTrader 5 terminal running on
the SAME machine — there is no network mode, so this Render-hosted backend
cannot call it. A publisher script on the user's Windows box posts bars to
/terminal/xauusd-bars instead, and this module reads what has accumulated.
Same shape as the crypto segment's client-fetched bars, just pushed on a
schedule instead of per-request.

One Mongo document per bar (not one array-of-bars document per symbol):
1-minute bars on a 24x5 market accumulate ~7,200/week, which would blow
past the 16MB per-document ceiling inside a year.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

COLLECTION = "mt5_bars"
SYMBOL = "XAUUSD"

# Labelled in IST, matching this platform's default convention (NSE bars
# use it too). Gold is a 24x5 global market with no single "home" exchange
# session, so there is no local exchange time to prefer the way Alpaca's
# bars prefer US/Eastern -- the viewer's own timezone is the useful one.
IST = ZoneInfo("Asia/Kolkata")

# This platform's interval keys -> minutes per bar. Mirrors
# alpaca_client.TIMEFRAME_MAP's keys so the frontend's interval selector
# needs no per-segment special-casing.
TIMEFRAME_MAP = {"1": 1, "5": 5, "15": 15, "30": 30, "60": 60}

# Bounds Mongo growth on a free-tier cluster. 60 days of 1-minute bars is
# ~62k documents -- comfortably enough for any intraday chart window this
# platform offers, and the daily/weekly/monthly charts don't read this
# collection at all.
RETENTION_DAYS = 60

MAX_INGEST_BARS = 20000


class Mt5DataError(Exception):
    """No/insufficient stored data — safe to show a caller."""


async def ensure_indexes(db):
    await db[COLLECTION].create_index([("symbol", 1), ("ts", 1)], unique=True)


async def store_bars(db, bars: list) -> dict:
    """Upsert a batch of 1-minute bars. `ts` is a sortable UTC-based
    "YYYY-MM-DDTHH:MM" string produced by the publisher, which is also what
    makes the upsert idempotent — re-pushing an overlapping window (the
    publisher deliberately re-sends a rolling window so a brief outage
    self-heals) rewrites the same documents rather than duplicating them.
    The last bar of any window is usually still forming, so overwriting on
    re-push is the correct behaviour, not merely a tolerable one."""
    from pymongo import UpdateOne

    ops = [
        UpdateOne(
            {"symbol": SYMBOL, "ts": b["ts"]},
            {"$set": {
                "symbol": SYMBOL, "ts": b["ts"],
                "open": float(b["open"]), "high": float(b["high"]),
                "low": float(b["low"]), "close": float(b["close"]),
            }},
            upsert=True,
        )
        for b in bars
    ]
    if not ops:
        return {"written": 0}
    result = await db[COLLECTION].bulk_write(ops, ordered=False)

    cutoff = (datetime.now(timezone.utc) - timedelta(days=RETENTION_DAYS)).strftime("%Y-%m-%dT%H:%M")
    await db[COLLECTION].delete_many({"symbol": SYMBOL, "ts": {"$lt": cutoff}})

    return {"written": result.upserted_count + result.modified_count, "received": len(ops)}


def _aggregate(bars: list, minutes: int) -> list:
    """Roll 1-minute bars up into `minutes`-wide buckets, anchored to
    midnight. Deliberately NOT pnf_chart.aggregate_minutes, which anchors
    buckets to 09:15 because it was written for NSE's session open — gold
    trades around the clock and has no such open, so a session anchor would
    put bucket boundaries at arbitrary points in the day."""
    if minutes <= 1:
        return bars
    buckets: dict[datetime, list] = {}
    for b in bars:
        ts = datetime.strptime(b["ts"], "%d%m%Y%H%M")
        anchor = ts.replace(hour=0, minute=0, second=0, microsecond=0)
        offset = int((ts - anchor).total_seconds() // 60)
        key = anchor + timedelta(minutes=(offset // minutes) * minutes)
        buckets.setdefault(key, []).append(b)
    out = []
    for key in sorted(buckets):
        group = buckets[key]
        out.append({
            "ts": key.strftime("%d%m%Y%H%M"),
            "open": group[0]["open"],
            "high": max(g["high"] for g in group),
            "low": min(g["low"] for g in group),
            "close": group[-1]["close"],
        })
    return out


async def intraday_bars(db, interval: str, days: int = 30) -> list:
    """Stored MT5 bars at the requested interval, labelled IST in this
    platform's ddmmyyyyHHMM intraday shape (see pnf_chart._bar_label)."""
    minutes = TIMEFRAME_MAP.get(interval)
    if not minutes:
        raise Mt5DataError(f"Unsupported intraday interval {interval!r}.")

    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M")
    rows = await db[COLLECTION].find(
        {"symbol": SYMBOL, "ts": {"$gte": cutoff}},
        {"_id": 0, "ts": 1, "open": 1, "high": 1, "low": 1, "close": 1},
    ).sort("ts", 1).to_list(length=None)

    if not rows:
        raise Mt5DataError(
            "Live intraday gold data hasn't been received yet — the market feed may be offline."
        )

    bars = []
    for r in rows:
        ts_utc = datetime.strptime(r["ts"], "%Y-%m-%dT%H:%M").replace(tzinfo=timezone.utc)
        bars.append({
            "ts": ts_utc.astimezone(IST).strftime("%d%m%Y%H%M"),
            "open": r["open"], "high": r["high"], "low": r["low"], "close": r["close"],
        })
    return _aggregate(bars, minutes)


async def feed_status(db) -> dict:
    """How fresh the stored feed is — lets the UI say "live" vs "stale"
    honestly rather than silently drawing an hours-old chart as current."""
    latest = await db[COLLECTION].find_one(
        {"symbol": SYMBOL}, {"_id": 0, "ts": 1}, sort=[("ts", -1)]
    )
    if not latest:
        return {"has_data": False, "latest_ts": None, "age_minutes": None}
    ts_utc = datetime.strptime(latest["ts"], "%Y-%m-%dT%H:%M").replace(tzinfo=timezone.utc)
    age = (datetime.now(timezone.utc) - ts_utc).total_seconds() / 60
    return {
        "has_data": True,
        "latest_ts": ts_utc.astimezone(IST).isoformat(timespec="minutes"),
        "age_minutes": round(age, 1),
    }
