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
    used elsewhere) for the underlying's own daily OHLC — the bhavcopy only
    carries a single reference price per day (UndrlygPric), not a full O/H/L,
    and the P&F engine needs real daily highs/lows.

Why this window and not further back: NSE's *old* bhavcopy format (pre-2024)
uses a different, less consistent column layout and doesn't carry the
underlying's reference price at all. Handling both formats reliably was
judged more complexity than the marginal ~2 extra years were worth for a
first version — this is a known, documented scoping choice, not a discovered
limit like the live-API window was.

This is why it matters: real historical option premiums genuinely exist for
this whole window (unlike the live Definedge API, which only retains ~4-8
weeks and can't even discover tokens for already-expired weekly contracts —
see blackbox_prism_alpha.py's module docstring). The backtest deliberately
reuses the exact same pattern-detection and RSI/XO-Zone functions the live
strategy uses (imported, not reimplemented) so it can never drift out of
sync with what's actually trading live.

Caveat that must stay visible in the UI: this is DAILY (EOD) data, not the
1-minute data the live strategy uses. A 1%-box/3-box-reversal P&F chart
built from daily bars is coarser — it can miss intraday reversals a 1-minute
chart would catch, so backtest results are not a faithful reproduction of
what the live minute-based engine would have done on the same dates, only
the closest approximation possible from data that genuinely exists.
"""
import io
import logging
import uuid
import zipfile
from datetime import datetime, timezone

import httpx
import pandas as pd

from blackbox_prism_alpha import (
    IST, TARGET_POINTS, CE_RSI_RANGE, PE_RSI_RANGE,
    build_pnf_columns, find_low_pole, find_high_pole, find_aft_immediate,
    find_turtle_breakout, find_triple_top_buy, find_triple_bottom_sell,
    is_double_bottom_sell, is_double_top_buy, xo_zone_series,
    compute_rsi_snapshot, _parse_ts, _is_today,
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
    a fixed end-of-day marker), so _parse_ts/_is_today work unmodified on
    daily bars — one timestamp format for both engines, no parallel helpers."""
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
    not bhavcopy's — the RULE itself is identical, not reinvented."""
    fut = sorted(e for e in expiries if e >= as_of_date)
    if not fut:
        return None
    idx = 0
    if as_of_date.weekday() in (0, 1) and len(fut) > 1:
        idx = 1 if (fut[0] - as_of_date).days <= 3 else 0
    return fut[idx]


def _option_price(day_df: "pd.DataFrame", expiry_iso: str, strike: float, opt_type: str, field: str):
    """field: 'open'|'high'|'low'|'close'. Falls back gracefully (None) if
    that exact strike/expiry/type didn't trade that day rather than raising
    — a single missing contract shouldn't abort the whole backtest."""
    row = day_df[(day_df["expiry"] == expiry_iso) & (day_df["strike"] == strike) & (day_df["opt_type"] == opt_type)]
    if row.empty:
        return None
    val = row.iloc[0][field]
    return float(val) if val not in (None, 0) or field == "close" else None


async def run_backtest(db, definedge, start_date=None, end_date=None) -> dict:
    """Walk-forward, no lookahead: on each simulated day D, only bars up to
    and including D are ever used to build the P&F chart or evaluate
    conditions. Reuses the live module's exact pattern-detection functions.
    """
    run_id = str(uuid.uuid4())
    start_date = start_date or DATA_START_DATE
    end_date = end_date or datetime.now(IST).date()

    underlying_bars_raw = await definedge.daily_history("NSE", NIFTY_SPOT_TOKEN, years=10)
    underlying_by_date = {b["date"]: b for b in underlying_bars_raw if start_date.isoformat() <= b["date"] <= end_date.isoformat()}
    trading_days = sorted(underlying_by_date.keys())

    daily_bars = []       # growing, walk-forward-safe underlying OHLC series
    open_trade = None     # at most one open simulated position at a time
    trades = []

    for date_iso in trading_days:
        d = datetime.strptime(date_iso, "%Y-%m-%d").date()
        ub = underlying_by_date[date_iso]
        daily_bars.append({"ts": _eod_ts(d), "open": ub["open"], "high": ub["high"], "low": ub["low"], "close": ub["close"]})
        columns = build_pnf_columns(daily_bars)

        opt_day = None  # fetched lazily, only if actually needed this day

        # ---- exit check for an open position -------------------------------
        if open_trade is not None:
            is_ce = open_trade["direction"] == "CE"

            entry_idx = next((i for i, c in enumerate(columns) if _parse_ts(c["end_ts"]).date() >= open_trade["_entry_date"]), None)
            best_candidate = None
            if entry_idx is not None:
                for j in range(entry_idx, len(columns)):
                    if is_ce and is_double_bottom_sell(columns, j):
                        cand = columns[j]["low_price"] - 1
                        if cand > open_trade["current_stop"] and (best_candidate is None or cand > best_candidate):
                            best_candidate = cand
                    elif not is_ce and is_double_top_buy(columns, j):
                        cand = columns[j]["high_price"] + 1
                        if cand < open_trade["current_stop"] and (best_candidate is None or cand < best_candidate):
                            best_candidate = cand
            if best_candidate is not None:
                open_trade["stop_shift_history"].append({
                    "timestamp": _eod_ts(d), "old_stop": open_trade["current_stop"],
                    "new_stop": best_candidate, "pattern": "double_bottom_sell" if is_ce else "double_top_buy",
                })
                open_trade["current_stop"] = best_candidate

            breach = None
            if is_ce:
                if ub["low"] <= open_trade["current_stop"]:
                    breach = "stop"
                elif ub["high"] >= open_trade["target"]:
                    breach = "target"
            else:
                if ub["high"] >= open_trade["current_stop"]:
                    breach = "stop"
                elif ub["low"] <= open_trade["target"]:
                    breach = "target"

            if breach:
                opt_day = await get_nifty_option_day(db, d)
                exit_price = None
                if opt_day is not None:
                    exit_price = _option_price(opt_day, open_trade["expiry"], open_trade["strike"], open_trade["direction"], "close")
                if exit_price is None:
                    exit_price = open_trade["entry_price"]  # best-effort — no trade that day for this exact contract
                open_trade["status"] = "closed"
                open_trade["exit_time"] = _eod_ts(d)
                open_trade["exit_price"] = exit_price
                open_trade["exit_reason"] = breach
                open_trade["pnl"] = exit_price - open_trade["entry_price"]
                open_trade.pop("_entry_date")
                trades.append(open_trade)
                open_trade = None
                continue  # no same-day re-entry, matches live strategy's rule

        # ---- entry check when flat ------------------------------------------
        if open_trade is None and len(columns) >= 4:
            for direction in ("CE", "PE"):
                is_ce = direction == "CE"
                find_pole = find_low_pole if is_ce else find_high_pole
                col_dir = "X" if is_ce else "O"

                pole_idx = None
                for i in range(3, len(columns)):
                    pole = find_pole(columns, i)
                    if pole and _is_today(columns[i]["end_ts"], date_iso):
                        pole_idx = i
                if pole_idx is None:
                    continue

                follow_through = None
                for j in range(pole_idx + 1, len(columns)):
                    if find_aft_immediate(columns, j, col_dir):
                        follow_through = "aft_immediate"
                    elif find_turtle_breakout(columns, j, col_dir):
                        follow_through = "turtle_breakout"
                    elif (find_triple_top_buy if is_ce else find_triple_bottom_sell)(columns, j):
                        follow_through = "triple_top_bottom"
                if follow_through is None:
                    continue

                xo_series = xo_zone_series(columns)
                xo_ok = (xo_series[pole_idx] <= 0 and xo_series[-1] > 0) if is_ce else (xo_series[pole_idx] >= 0 and xo_series[-1] < 0)

                closes = [b["close"] for b in daily_bars]
                rsi_snapshot = compute_rsi_snapshot(closes)
                lo, hi = CE_RSI_RANGE if is_ce else PE_RSI_RANGE
                rsi_ok = rsi_snapshot["rsi7"] is not None and lo < rsi_snapshot["rsi7"] < hi

                if not (xo_ok and rsi_ok):
                    continue

                opt_day = opt_day if opt_day is not None else await get_nifty_option_day(db, d)
                if opt_day is None:
                    continue
                atm = round(ub["close"] / 100) * 100
                expiry = _pick_weekly_expiry(sorted(set(opt_day["expiry"].tolist())), d)
                if expiry is None:
                    continue
                entry_price = _option_price(opt_day, expiry, float(atm), direction, "close")
                if entry_price is None:
                    continue

                pole_col = columns[pole_idx - 1]
                open_trade = {
                    "id": str(uuid.uuid4()),
                    "backtest_run_id": run_id,
                    "data_source_granularity": "daily_eod",
                    "date": date_iso,
                    "direction": direction,
                    "strike": atm,
                    "expiry": expiry,
                    "entry_time": _eod_ts(d),
                    "entry_price": entry_price,
                    "initial_stop": (pole_col["low_price"] - 1) if is_ce else (pole_col["high_price"] + 1),
                    "current_stop": (pole_col["low_price"] - 1) if is_ce else (pole_col["high_price"] + 1),
                    "stop_shift_history": [],
                    "target": (ub["close"] + TARGET_POINTS) if is_ce else (ub["close"] - TARGET_POINTS),
                    "exit_time": None, "exit_price": None, "exit_reason": None, "pnl": None,
                    "conditions_met": {"pole_column": pole_idx, "follow_through_pattern": follow_through,
                                       "xo_zone_now": xo_series[-1], "rsi7": rsi_snapshot["rsi7"]},
                    "status": "open",
                    "_entry_date": d,
                }
                break  # only one direction can enter per day

    if open_trade is not None:
        open_trade.pop("_entry_date")
        trades.append(open_trade)  # still-open at the end of the window — reported as-is

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
