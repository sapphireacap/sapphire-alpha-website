"""
US Exitline — same Camarilla level ladder + SL/TP as exitline.py, for an
individual US equity (S&P 500 universe) instead of an NSE instrument.
Reuses exitline.py's pure `compute_camarilla_levels`/`classify_and_suggest`
functions unchanged (they take plain high/low/close/ltp floats, no
Definedge coupling at all) -- only the data source differs: previous-day
OHLC from yahoo_finance_client.equity_bars(), live price and intraday
chart from alpaca_client (see that module's docstring for the IEX feed
and, for indices, the ETF-proxy caveat -- individual stocks have none of
that, the ticker IS the real instrument).
"""
import logging
from datetime import datetime, timezone

import alpaca_client as ac
import yahoo_finance_client as yf
from exitline import compute_camarilla_levels, classify_and_suggest

logger = logging.getLogger(__name__)

# alpaca_client bars are already { "ts": "DDMMYYYYHHMM", open, high, low, close }
# -- same shape exitline._aggregate_bars produces, so the chart needs no
# reshaping, only a label/epoch pass matching exitline.intraday_chart's output.


def _label_bars(bars: list) -> list:
    out = []
    for b in bars:
        try:
            dt = datetime.strptime(b["ts"], "%d%m%Y%H%M")
        except ValueError:
            continue
        out.append({
            "t": dt.strftime("%H:%M"), "time": int(dt.replace(tzinfo=timezone.utc).timestamp()),
            "open": b["open"], "high": b["high"], "low": b["low"], "close": b["close"],
        })
    return out


async def get_or_compute_levels(db, symbol: str) -> dict:
    """Camarilla levels are fixed for the day -- computed once from the
    previous day's H/L/C and cached per (date, symbol), same shape as
    exitline.get_or_compute_levels."""
    today = datetime.now(timezone.utc).date().isoformat()
    key = {"date": today, "symbol": symbol}
    cached = await db.us_exitline_levels.find_one(key, {"_id": 0})
    if cached:
        return cached

    bars = await yf.equity_bars(db, symbol)
    if not bars:
        raise yf.YahooFinanceError(f"No price history for {symbol}.")
    prev = bars[-1]  # equity_bars only ever has completed daily bars (Yahoo drops today's in-progress one)
    levels = compute_camarilla_levels(prev["high"], prev["low"], prev["close"])
    doc = {
        **key,
        "prev_date": prev["date"],
        "high": prev["high"], "low": prev["low"], "close": prev["close"],
        "levels": levels,
        "computed_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.us_exitline_levels.update_one(key, {"$set": doc}, upsert=True)
    return doc


async def build_exitline_response(db, symbol: str, interval_minutes: int = 5) -> dict:
    symbol = symbol.strip().upper()
    levels_doc = await get_or_compute_levels(db, symbol)

    try:
        ltp = await ac.latest_trade(symbol)
    except ac.AlpacaError as e:
        logger.warning("US Exitline: live quote unavailable for %s: %s", symbol, e)
        ltp = None

    try:
        # 5 calendar days (not 1) -- unlike NSE Exitline's session-aware
        # intraday_chart(), this doesn't clip to a single trading day
        # boundary; a short buffer keeps the chart populated across
        # weekends/holidays instead of intermittently returning nothing.
        raw_bars = await ac.intraday_bars_for_ticker(symbol, str(interval_minutes), days=5)
        chart = _label_bars(raw_bars)
    except ac.AlpacaError as e:
        logger.warning("US Exitline: intraday chart unavailable for %s: %s", symbol, e)
        chart = []

    if ltp is None:
        zone = {
            "zone": None, "zone_label": "Live Price Unavailable", "bias": "Neutral",
            "sl": None, "tp": None, "tp_alt": None, "trail_stop": False,
            "reason": "No live quote right now (market may be closed) — levels are still shown "
                      "against yesterday's close; zone/SL/TP need a live price.",
            "commentary": None,
        }
    else:
        zone = classify_and_suggest(levels_doc["levels"], ltp, levels_doc["close"])

    return {
        "symbol": symbol,
        "prev_date": levels_doc["prev_date"],
        "high": levels_doc["high"], "low": levels_doc["low"], "close": levels_doc["close"],
        "levels": levels_doc["levels"],
        "ltp": ltp,
        "chart": chart,
        **zone,
    }
