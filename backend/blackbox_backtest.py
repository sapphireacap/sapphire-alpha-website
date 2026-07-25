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
    used elsewhere) for the underlying's own daily OHLC — used only to pick
    the ATM strike and check the 60-point target, which per spec stays
    measured on the underlying even though everything else moved to the
    option's own chart (see below).

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
trading live — the same requirement is why this file had to be reworked
the moment the live logic changed, not left on the old underlying-based
design.

Structural consequence worth stating plainly: because the ATM strike (and
therefore which specific option contract is "the chart") changes as the
underlying moves and as weekly expiry rolls, a given contract's own P&F
chart in this backtest often only accumulates a handful of days before the
tracked strike/expiry changes and a fresh, near-empty chart starts for the
new one. Forming a 4-column Low Pole took roughly 30+ calendar days on
average even on the continuous, never-resetting Nifty index chart (see the
live module's dry-run notes). A per-contract chart that resets every few
days is structurally unlikely to accumulate that much history before
rolling — so a low (or zero) trade count from this backtest is an expected
consequence of matching the live logic faithfully, not a bug to chase.

Caveat that must stay visible in the UI: this is DAILY (EOD) data, not the
1-minute data the live strategy uses. A 1%-box/3-box-reversal P&F chart
built from daily bars is coarser than one built from 1-minute bars, so
backtest results are the closest approximation possible from data that
genuinely exists, not a faithful reproduction of what the live engine would
have done on the same dates.
"""
import io
import logging
import uuid
import zipfile
from datetime import datetime, timezone

import httpx
import pandas as pd

from blackbox_prism_alpha import (
    IST, TARGET_POINTS, ENTRY_RSI_RANGE,
    build_pnf_columns, find_low_pole, find_aft_immediate,
    find_turtle_breakout, find_triple_top_buy,
    is_double_bottom_sell, xo_zone_series, compute_rsi_snapshot,
    _parse_ts, _is_today,
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
    """Walk-forward, no lookahead: on each simulated day D, only bars up to
    and including D are ever used to build a P&F chart or evaluate
    conditions. Reuses the live module's exact pattern-detection functions.

    Each of CE/PE's P&F chart is built from that SPECIFIC (strike, expiry)
    contract's own accumulated daily bars — not the underlying — mirroring
    the live module. contract_bars carries that accumulation across days so
    a strike/expiry combination that stays ATM for several consecutive days
    keeps building real history, exactly as it would live.
    """
    run_id = str(uuid.uuid4())
    start_date = start_date or DATA_START_DATE
    end_date = end_date or datetime.now(IST).date()

    underlying_bars_raw = await definedge.daily_history("NSE", NIFTY_SPOT_TOKEN, years=10)
    underlying_by_date = {b["date"]: b for b in underlying_bars_raw if start_date.isoformat() <= b["date"] <= end_date.isoformat()}
    trading_days = sorted(underlying_by_date.keys())

    contract_bars = {}     # (opt_type, strike, expiry) -> growing list of {ts, open, high, low, close}
    open_trade = None      # at most one open simulated position at a time
    trades = []

    for date_iso in trading_days:
        d = datetime.strptime(date_iso, "%Y-%m-%d").date()
        ub = underlying_by_date[date_iso]

        opt_day = await get_nifty_option_day(db, d)
        if opt_day is None:
            continue  # no options data at all this day (holiday/gap) — nothing to evaluate

        atm = round(ub["close"] / 100) * 100
        expiry_date = _pick_weekly_expiry(sorted(set(opt_day["expiry"].tolist())), d)
        if expiry_date is None:
            continue
        expiry = expiry_date.isoformat()  # back to string — day_df's expiry column is always string-typed

        # Accumulate today's bar for whichever CE/PE contract is ATM today —
        # a strike that stays ATM across consecutive days keeps growing the
        # same series; a new strike starts a fresh, near-empty one.
        for opt_type in ("CE", "PE"):
            ohlc = _option_ohlc(opt_day, expiry, float(atm), opt_type)
            if ohlc is None:
                continue
            key = (opt_type, atm, expiry)
            contract_bars.setdefault(key, []).append({"ts": _eod_ts(d), **ohlc})

        # ---- exit check for an open position -------------------------------
        if open_trade is not None:
            key = (open_trade["direction"], open_trade["strike"], open_trade["expiry"])
            bars = contract_bars.get(key, [])
            columns = build_pnf_columns(bars)

            entry_idx = next((i for i, c in enumerate(columns) if _parse_ts(c["end_ts"]).date() >= open_trade["_entry_date"]), None)
            best_candidate = None
            if entry_idx is not None:
                for j in range(entry_idx, len(columns)):
                    if is_double_bottom_sell(columns, j):
                        cand = columns[j]["low_price"] - 1
                        if cand > open_trade["current_stop"] and (best_candidate is None or cand > best_candidate):
                            best_candidate = cand
            if best_candidate is not None:
                open_trade["stop_shift_history"].append({
                    "timestamp": _eod_ts(d), "old_stop": open_trade["current_stop"],
                    "new_stop": best_candidate, "pattern": "double_bottom_sell",
                })
                open_trade["current_stop"] = best_candidate

            is_ce = open_trade["direction"] == "CE"
            todays_bar = bars[-1] if bars else None
            # Uses the day's LOW (not just close) for the stop check — same
            # "trades through, not closes through" intent as the live
            # module, applied at daily-bar resolution.
            stop_hit = todays_bar is not None and todays_bar["low"] <= open_trade["current_stop"]
            target_hit = (ub["high"] >= open_trade["target"]) if is_ce else (ub["low"] <= open_trade["target"])

            if stop_hit or target_hit:
                exit_reason = "stop" if stop_hit else "target"
                exit_price = todays_bar["close"] if todays_bar is not None else open_trade["entry_price"]
                open_trade["status"] = "closed"
                open_trade["exit_time"] = _eod_ts(d)
                open_trade["exit_price"] = exit_price
                open_trade["exit_reason"] = exit_reason
                open_trade["pnl"] = exit_price - open_trade["entry_price"]
                open_trade.pop("_entry_date")
                trades.append(open_trade)
                open_trade = None
                continue  # no same-day re-entry, matches live strategy's rule

        # ---- entry check when flat ------------------------------------------
        if open_trade is None:
            for direction in ("CE", "PE"):
                key = (direction, atm, expiry)
                columns = build_pnf_columns(contract_bars.get(key, []))
                if len(columns) < 4:
                    continue

                pole_idx = None
                for i in range(3, len(columns)):
                    if find_low_pole(columns, i) and _is_today(columns[i]["end_ts"], date_iso):
                        pole_idx = i
                if pole_idx is None:
                    continue

                follow_through = None
                for j in range(pole_idx + 1, len(columns)):
                    if find_aft_immediate(columns, j, "X"):
                        follow_through = "aft_immediate"
                    elif find_turtle_breakout(columns, j, "X"):
                        follow_through = "turtle_breakout"
                    elif find_triple_top_buy(columns, j):
                        follow_through = "triple_top_bottom"
                if follow_through is None:
                    continue

                xo_series = xo_zone_series(columns)
                xo_ok = xo_series[pole_idx] <= 0 and xo_series[-1] > 0

                closes = [b["close"] for b in contract_bars[key]]
                rsi_snapshot = compute_rsi_snapshot(closes)
                rsi_ok = rsi_snapshot["rsi7"] is not None and ENTRY_RSI_RANGE[0] < rsi_snapshot["rsi7"] < ENTRY_RSI_RANGE[1]

                if not (xo_ok and rsi_ok):
                    continue

                entry_price = contract_bars[key][-1]["close"]
                pole_col = columns[pole_idx - 1]
                initial_stop = pole_col["low_price"] - 1
                target = (ub["close"] + TARGET_POINTS) if direction == "CE" else (ub["close"] - TARGET_POINTS)

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
                    "initial_stop": initial_stop,
                    "current_stop": initial_stop,
                    "stop_shift_history": [],
                    "target": target,
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
