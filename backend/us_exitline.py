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

Same 30-session (~calendar 6-week) multi-session history as NSE Exitline
(see exitline.py's build_session_ladder docstring for why "today's"
levels must not show before the US cash session has actually opened,
09:30 America/New_York) -- reuses that module's build_session_ladder and
_aggregate_bars unchanged, just with the US exchange's own open time
(09:30, not NSE's 09:15) and America/New_York as the local calendar
instead of IST.
"""
import logging
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import alpaca_client as ac
import yahoo_finance_client as yf
from exitline import compute_camarilla_levels, classify_and_suggest, build_session_ladder, _aggregate_bars, HISTORY_SESSIONS

logger = logging.getLogger(__name__)
NY_TZ = ZoneInfo("America/New_York")
US_SESSION_OPEN_MINUTES = 9 * 60 + 30

# alpaca_client bars are already { "ts": "DDMMYYYYHHMM", open, high, low, close }
# in US/Eastern local wall-clock time (same convention NSE bars use IST) --
# encoded here as a fake-UTC epoch (tzinfo=utc, not NY_TZ) to match this
# module's existing frontend contract: USExitline.jsx's formatEtHm()
# deliberately reads the epoch back with UTC getters and expects zero
# offset (verified live, 2026-08-10) -- a real NY_TZ conversion here would
# silently break that pairing by introducing the ET/UTC offset on one side
# only. `time` is therefore NOT a real Unix timestamp, by design, same as
# it always has been -- only the label ever mattered.
def _label_bars(bars: list) -> list:
    out = []
    for b in bars:
        try:
            dt = datetime.strptime(b["ts"], "%d%m%Y%H%M")
        except ValueError:
            continue
        out.append({
            "t": dt.strftime("%H:%M"), "time": int(dt.replace(tzinfo=timezone.utc).timestamp()),
            "date": dt.date().isoformat(),
            "open": b["open"], "high": b["high"], "low": b["low"], "close": b["close"],
        })
    return out


async def build_exitline_response(db, symbol: str, interval_minutes: int = 5) -> dict:
    symbol = symbol.strip().upper()

    daily_bars = await yf.equity_bars(db, symbol)
    now_ny = datetime.now(NY_TZ)
    sessions = build_session_ladder(daily_bars, now_ny, US_SESSION_OPEN_MINUTES)
    if not sessions:
        raise yf.YahooFinanceError(f"No price history for {symbol}.")
    active = sessions[-1]

    try:
        ltp = await ac.latest_trade(symbol)
    except ac.AlpacaError as e:
        logger.warning("US Exitline: live quote unavailable for %s: %s", symbol, e)
        ltp = None

    try:
        # ~45 calendar days comfortably covers HISTORY_SESSIONS (30) real
        # trading days even across a long weekend/holiday cluster.
        raw_bars = await ac.intraday_bars_for_ticker(symbol, str(interval_minutes), days=HISTORY_SESSIONS + 15)
        agg = _aggregate_bars(raw_bars, interval_minutes, open_hour=9, open_minute=30)
        chart = _label_bars(agg)
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
        zone = classify_and_suggest(active["levels"], ltp, active["close"])

    return {
        "symbol": symbol,
        "prev_date": active["prev_date"],
        "high": active["high"], "low": active["low"], "close": active["close"],
        "levels": active["levels"],
        "active_date": active["date"],
        "sessions": sessions,
        "ltp": ltp,
        "chart": chart,
        **zone,
    }
