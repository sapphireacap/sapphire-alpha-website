"""
Prism Alpha — historical backtest engine.

READ-ONLY, same constraint as the live module: no order placement anywhere.
Data sources are both official, publicly-published historical archives, not
live brokerage endpoints:
  - NSE's official F&O bhavcopy archive (nsearchives.nseindia.com) — daily
    OHLC for every NIFTY option (all strikes/expiries) plus the underlying's
    reference price, one file per trading day. Covers 2024-01-01 to present
    in this exact (UDiFF) format — verified live before building anything
    here; older dates 404. NSE's robots.txt permits general crawling.
  - Definedge's existing daily_history() (definedge_service.py, already
    used elsewhere) for the underlying's own daily OHLC — used ONLY to pick
    the ATM strike each day. The 60-point target is ₹60 of option premium
    from entry (confirmed with the user), not underlying points, so it's
    computed and checked entirely on the option's own chart like everything
    else here.

Why this window and not further back: NSE's *old* bhavcopy format (pre-2024)
uses a different, less consistent column layout and doesn't carry the
underlying's reference price at all. Handling both formats reliably was
judged more complexity than the marginal ~2 extra years were worth for a
first version — this is a known, documented scoping choice, not a discovered
limit like the live-API window was.

Mid-build correction, matching the live module: the P&F chart, patterns,
XO Zone, RSI and stop-loss all run on the OPTION'S OWN premium (a real
Definedge chart screenshot showed premium-scale price levels, not index-
scale), and both CE and PE watch for the identical bullish Low-Pole setup
on their own chart rather than a bearish mirror. This backtest reuses the
live module's exact pattern-detection functions (imported, not
reimplemented) so it can never drift out of sync with what's actually
trading live.

Second correction: every trade must exit the SAME session it's entered
("exit every trade at 3:10pm if target or stop isn't hit" — no overnight
holding). At daily-bar resolution this reshapes the whole walk: entry
conditions are checked using data through YESTERDAY's close only (today
isn't known yet at session open), entry executes at TODAY's open, and the
position resolves using TODAY's close — either because close crossed
stop/target, or because there's no more data left in the session and it's
forced flat there regardless (exit_reason "session_end"). This also fixes
a real bug the first version of this same-session logic had: a trade
tracked via a shared ATM-keyed accumulator silently stopped receiving
price updates the moment ATM drifted away from its strike, leaving it
"open" forever with stale data — single-session trades sidestep that
entirely since a trade never needs data beyond the day it was opened.

Caveat that must stay visible in the UI: this is DAILY (EOD) data, not the
1-minute data the live strategy uses. A 1%-box/3-box-reversal P&F chart
built from daily bars is coarser than one built from 1-minute bars, and the
live module's trailing stop (which needs days/hours of room to develop a
NEW Double Bottom Sell after entry) can't meaningfully operate within a
single EOD session — so stop_shift_history stays empty here even though
the live module does exercise it. Backtest results are the closest
approximation possible from data that genuinely exists, not a faithful
reproduction of what the live engine would have done on the same dates.
"""
import io
import logging
import uuid
import zipfile
from datetime import datetime, timezone

import httpx
import pandas as pd

from blackbox_prism_alpha import (
    IST, TARGET_POINTS, ENTRY_RSI_RANGE, POLE_SEARCH_WINDOW,
    build_pnf_columns, find_low_pole, find_aft_immediate,
    find_turtle_breakout, find_triple_top_buy,
    xo_zone_series, xo_zone_turned, column_close_prices, compute_rsi_snapshot,
)
from definedge_service import NIFTY_SPOT_TOKEN

logger = logging.getLogger(__name__)

NSE_BHAVCOPY_URL = "https://nsearchives.nseindia.com/content/fo/BhavCopy_NSE_FO_0_0_0_{date}_F_0000.csv.zip"
BROWSER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36",
}
DATA_START_DATE = datetime(2024, 1, 1).date()  # earliest date this archive format supports — verified live


def _eod_ts(d) -> str:
    """Same ddmmyyyyHHMM shape the live module's minute timestamps use (with
    a fixed end-of-day marker), so downstream helpers work unmodified on
    daily bars — one timestamp format for both engines, no parallel ones."""
    return f"{d.day:02d}{d.month:02d}{d.year}1530"


async def _download_bhavcopy_csv(date) -> "pd.DataFrame | None":
    """One day's full NSE F&O bhavcopy, NIFTY-index-options rows only.
    Returns None (never raises) for a non-trading day / not-yet-published
    date — a 404 here just means "no data for this date", not an error."""
    url = NSE_BHAVCOPY_URL.format(date=date.strftime("%Y%m%d"))
    async with httpx.AsyncClient(timeout=45) as c:
        r = await c.get(url, headers=BROWSER_HEADERS)
    if r.status_code == 404:
        return None
    if r.status_code != 200:
        raise RuntimeError(f"NSE bhavcopy fetch failed ({r.status_code}) for {date.isoformat()}.")
    with zipfile.ZipFile(io.BytesIO(r.content)) as z:
        name = z.namelist()[0]
        with z.open(name) as f:
            df = pd.read_csv(f)
    nifty = df[(df["TckrSymb"] == "NIFTY") & (df["FinInstrmTp"].isin(["IDO", "STO"])) & (df["OptnTp"].isin(["CE", "PE"]))].copy()
    if nifty.empty:
        return None
    nifty["_expiry"] = pd.to_datetime(nifty["XpryDt"]).dt.date
    return nifty


async def get_nifty_option_day(db, date) -> "pd.DataFrame | None":
    """Cached wrapper around _download_bhavcopy_csv — same day is reused
    across backtest runs without re-hitting NSE's servers every time."""
    date_iso = date.isoformat()
    cached = await db.blackbox_backtest_bhavcopy_cache.find_one({"date": date_iso}, {"_id": 0})
    if cached is not None:
        if not cached["rows"]:
            return None
        return pd.DataFrame(cached["rows"])

    df = await _download_bhavcopy_csv(date)
    rows = [] if df is None else df[["_expiry", "StrkPric", "OptnTp", "OpnPric", "HghPric", "LwPric", "ClsPric", "UndrlygPric"]].rename(
        columns={"_expiry": "expiry", "StrkPric": "strike", "OptnTp": "opt_type", "OpnPric": "open", "HghPric": "high", "LwPric": "low", "ClsPric": "close", "UndrlygPric": "underlying"}
    ).assign(expiry=lambda x: x["expiry"].astype(str)).to_dict("records")
    await db.blackbox_backtest_bhavcopy_cache.update_one({"date": date_iso}, {"$set": {"date": date_iso, "rows": rows}}, upsert=True)
    return None if not rows else pd.DataFrame(rows)


def _pick_weekly_expiry(expiries: list, as_of_date) -> "object | None":
    """Same Mon/Tue-roll rule as the live strategy's expiry resolution
    (DefinedgeService._pick_expiry), reimplemented here only because the
    live one is a staticmethod bound to Definedge's master-file data shape,
    not bhavcopy's — the RULE itself is identical, not reinvented.

    expiries may be `date` objects (fresh bhavcopy fetch) or ISO strings
    (cached rows, serialized for Mongo) — normalized to `date` here so a
    cache hit doesn't silently compare str >= date and crash. Caught live:
    a fresh 3-month backtest run worked, but the exact same range failed on
    any day whose bhavcopy came from cache instead of a live download."""
    def _as_date(e):
        return e if isinstance(e, type(as_of_date)) else datetime.strptime(str(e), "%Y-%m-%d").date()
    expiries = [_as_date(e) for e in expiries]
    fut = sorted(e for e in expiries if e >= as_of_date)
    if not fut:
        return None
    idx = 0
    if as_of_date.weekday() in (0, 1) and len(fut) > 1:
        idx = 1 if (fut[0] - as_of_date).days <= 3 else 0
    return fut[idx]


def _option_ohlc(day_df: "pd.DataFrame", expiry_iso: str, strike: float, opt_type: str):
    """Full OHLC dict for one contract on one day, or None if it didn't
    trade that day — a single missing contract-day shouldn't abort anything."""
    row = day_df[(day_df["expiry"] == expiry_iso) & (day_df["strike"] == strike) & (day_df["opt_type"] == opt_type)]
    if row.empty:
        return None
    r = row.iloc[0]
    close = float(r["close"])
    if close <= 0:
        return None
    # illiquid strikes often report 0 for open/high/low with only a real
    # close/settlement price — fall back to close so the bar is still usable
    # rather than dropping the day entirely.
    o, h, l = float(r["open"]), float(r["high"]), float(r["low"])
    return {"open": o or close, "high": h or close, "low": l or close, "close": close}


async def run_backtest(db, definedge, start_date=None, end_date=None) -> dict:
    """Walk-forward, no lookahead, ONE SESSION PER TRADE — see module
    docstring. Entry conditions are checked using contract_bars as they
    stand BEFORE today's bar is appended (i.e. through yesterday's close
    only); entry executes at today's open; the trade resolves same-day
    using today's close (stop/target breach, or forced "session_end" if
    neither hit) before moving to the next day.

    MAX_TRADES_PER_SESSION (3) isn't separately enforced here: only one
    entry decision is made per calendar day, so this walk can never
    produce more than one trade per day and the cap can't bind.
    """
    run_id = str(uuid.uuid4())
    start_date = start_date or DATA_START_DATE
    end_date = end_date or datetime.now(IST).date()

    underlying_bars_raw = await definedge.daily_history("NSE", NIFTY_SPOT_TOKEN, years=10)
    underlying_by_date = {b["date"]: b for b in underlying_bars_raw if start_date.isoformat() <= b["date"] <= end_date.isoformat()}
    trading_days = sorted(underlying_by_date.keys())

    contract_bars = {}     # (opt_type, strike, expiry) -> growing list of {ts, open, high, low, close}
    all_days_data = []     # [(date_iso, opt_day_df), ...] — every day's full option chain already fetched,
                            # kept in memory so a contract that JUST became ATM can be backfilled with its
                            # real prior trading history instead of starting from zero. Not lookahead (every
                            # day here is <= today) — mirrors the live module, which fetches up to 90 days
                            # of that SPECIFIC token's history regardless of how recently it became ATM (a
                            # strike that became ATM today may already have weeks of real trading behind
                            # it — verified live). Without this backfill, every contract's chart here
                            # started from nothing, which is why the very first version never traded.
    trades = []

    for date_iso in trading_days:
        d = datetime.strptime(date_iso, "%Y-%m-%d").date()
        ub = underlying_by_date[date_iso]

        opt_day = await get_nifty_option_day(db, d)
        if opt_day is None:
            continue  # no options data at all this day (holiday/gap) — nothing to evaluate

        atm = round(ub["open"] / 100) * 100  # today's OPEN — what's actually known at session start
        expiry_date = _pick_weekly_expiry(sorted(set(opt_day["expiry"].tolist())), d)
        if expiry_date is None:
            continue
        expiry = expiry_date.isoformat()  # back to string — day_df's expiry column is always string-typed

        # ---- entry check, using data through YESTERDAY only ----------------
        # (contract_bars hasn't had today's bar appended yet — that happens
        # further below, after this decision, so today's own close can never
        # influence whether we entered at today's open.)
        for direction in ("CE", "PE"):
            key = (direction, atm, expiry)
            columns = build_pnf_columns(contract_bars.get(key, []))
            if len(columns) < 4:
                continue

            # Search backward for the freshest (pole, follow-through) PAIR —
            # not "the single most recent pole ever paired with any later
            # follow-through," which surfaced a real bad trade in testing
            # (stale pole, price long since moved away — see the sanity
            # guard below). Same fix as the live module.
            pole_idx = None
            follow_through = None
            search_floor = max(2, len(columns) - 1 - POLE_SEARCH_WINDOW)
            for i in range(len(columns) - 1, search_floor, -1):
                if not find_low_pole(columns, i):
                    continue
                candidate_ft = None
                for j in range(i + 1, len(columns)):
                    if find_aft_immediate(columns, j, "X"):
                        candidate_ft = "aft_immediate"
                    elif find_turtle_breakout(columns, j, "X"):
                        candidate_ft = "turtle_breakout"
                    elif find_triple_top_buy(columns, j):
                        candidate_ft = "triple_top_bottom"
                if candidate_ft is not None:
                    pole_idx, follow_through = i, candidate_ft
                    break
            if pole_idx is None or follow_through is None:
                continue

            # XO Zone gate: zero-line crossover on the newest column, matching
            # blackbox_prism_alpha.py's xo_zone_turned() — confirmed against
            # Prashant Shah's P&F book (Ch. 4.5) as the correct textbook
            # reading, replacing an earlier self-invented "net positive since
            # the pole" condition that mechanically vetoed every real setup.
            xo_now = xo_zone_series(columns)[-1]
            xo_ok = xo_zone_turned(columns) == "positive"

            # RSI(7) on column closing-price-method values (X->high, O->low),
            # per the book's confirmation that P&F indicators run on one
            # price per column, not raw bars — matches the live module.
            col_closes = column_close_prices(columns)
            rsi_snapshot = compute_rsi_snapshot(col_closes)
            rsi_ok = rsi_snapshot["rsi7"] is not None and ENTRY_RSI_RANGE[0] < rsi_snapshot["rsi7"] < ENTRY_RSI_RANGE[1]

            if not (xo_ok and rsi_ok):
                continue

            todays_ohlc = _option_ohlc(opt_day, expiry, float(atm), direction)
            if todays_ohlc is None:
                continue
            entry_price = todays_ohlc["open"]
            pole_col = columns[pole_idx - 1]
            initial_stop = pole_col["low_price"] - 1

            # Sanity guard: a stop can never sit at/above entry on a long
            # position — see the matching note in the live module. The
            # "most recent pole anywhere in the window" can still be stale
            # relative to where price has since moved even when a later
            # follow-through + XO Zone + RSI still align.
            if initial_stop >= entry_price:
                continue

            target = entry_price + TARGET_POINTS  # ₹60 of option premium, not underlying points

            # ---- resolve same-day, using today's close (or forced) ---------
            exit_price = todays_ohlc["close"]
            if exit_price <= initial_stop:
                exit_reason = "stop"
            elif exit_price >= target:
                exit_reason = "target"
            else:
                exit_reason = "session_end"  # 15:10 cutoff — neither hit, forced flat same day

            trades.append({
                "id": str(uuid.uuid4()),
                "backtest_run_id": run_id,
                "data_source_granularity": "daily_eod",
                "date": date_iso,
                "direction": direction,
                "strike": atm,
                "expiry": expiry,
                "entry_time": _eod_ts(d),
                "entry_price": entry_price,
                "initial_stop": initial_stop,
                "current_stop": initial_stop,
                "stop_shift_history": [],  # needs multi-day room to develop a NEW Double Bottom Sell after
                                            # entry — structurally can't happen within a single EOD session
                                            # (see module docstring); the live module's intraday version
                                            # does exercise it.
                "target": target,
                "exit_time": _eod_ts(d),
                "exit_price": exit_price,
                "exit_reason": exit_reason,
                "pnl": exit_price - entry_price,
                "conditions_met": {"pole_column": pole_idx, "follow_through_pattern": follow_through,
                                   "xo_zone_now": xo_now, "rsi7": rsi_snapshot["rsi7"]},
                "status": "closed",
            })
            break  # only one direction enters per day

        # ---- accumulate today's bar for every contract we're tracking ------
        for opt_type in ("CE", "PE"):
            key = (opt_type, atm, expiry)
            if key not in contract_bars:
                backfill = []
                for prev_date_iso, prev_df in all_days_data:
                    prev_ohlc = _option_ohlc(prev_df, expiry, float(atm), opt_type)
                    if prev_ohlc is not None:
                        prev_d = datetime.strptime(prev_date_iso, "%Y-%m-%d").date()
                        backfill.append({"ts": _eod_ts(prev_d), **prev_ohlc})
                contract_bars[key] = backfill

            ohlc = _option_ohlc(opt_day, expiry, float(atm), opt_type)
            if ohlc is not None:
                contract_bars[key].append({"ts": _eod_ts(d), **ohlc})

        all_days_data.append((date_iso, opt_day))

    if trades:
        await db.blackbox_prism_alpha_backtest_trades.insert_many([dict(t) for t in trades])

    summary = {
        "backtest_run_id": run_id,
        "start_date": trading_days[0] if trading_days else start_date.isoformat(),
        "end_date": trading_days[-1] if trading_days else end_date.isoformat(),
        "data_source_granularity": "daily_eod",
        "trading_days_evaluated": len(trading_days),
        "trades_generated": len(trades),
        "run_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.blackbox_backtest_runs.insert_one(dict(summary))
    return summary
