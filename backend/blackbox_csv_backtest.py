"""
Prism Alpha -- long-horizon CSV backtest engine (2021-01-01 to 2026-05-21,
locally supplied ATM-relative options data).

Unlike blackbox_backtest.py (live Definedge API, capped at
BACKTEST_LOOKBACK_DAYS=14 by the expired-token constraint documented there),
this walks pre-supplied local CSV files -- sidestepping that constraint
entirely, since each day's ATM strikes are already labeled relative to that
day's own spot (ATM-10..ATM+10), not an absolute strike number tied to one
fixed, still-listed expiry. The CSV data lives only on the local machine that
ran this (not on Render), so this module is invoked as a one-off local
script (see __main__ below), writing its results straight into the same
production MongoDB collections the live/API-backtest already use.

Reuses the EXACT SAME pure entry/exit decision functions as live and the
API-based backtest (_analyze_option_bars, _gate_entry, _evaluate_exit,
imported from blackbox_prism_alpha, never reimplemented) -- a signal here can
never drift from what the live engine would decide given the same bars.

CSV schema (verified against all 1255 files in the provided dataset -- one
schema, zero column or label-set mismatches):
    datetime,strike_label,option_type,open,high,low,close,volume,oi,iv,strike_price,spot
    strike_label in {ATM-10..ATM-1, ATM, ATM+1..ATM+10} (21 labels)
    option_type in {CALL, PUT}
    ~375 one-minute bars/day (09:15-15:29 IST), matching live/API-backtest
    granularity. 40/1255 files had a handful of exact-duplicate rows (same
    values, not a real second observation) -- deduped on load. A small
    number of days have fewer distinct timestamps (early closes / special
    sessions) -- handled naturally, never assumed complete.

Known limitation, surfaced honestly (same spirit as blackbox_backtest.py's
own "not a faithful replay" caveat): the CSV has no expiry field, so there is
no way to safely verify that a strike_price recurring on a LATER day is
genuinely the same contract (vs. a same-numbered strike on a different
week's expiry -- NIFTY's weekly expiry day itself changed more than once
across this window, so guessing a historical expiry calendar to bridge that
gap isn't a safe assumption either). Rather than guess, each option's P&F
chart is built ONLY from bars within its own CALENDAR WEEK (reset at the
first trading day of every ISO week) -- safe specifically because these ARE
weekly options: a given dated contract only ever genuinely trades within its
own week before expiring. This gives the pattern search up to ~5 trading
days (~1,875 bars) of real history per setup -- short of live's 90-day
lookback, but far more than a single-session reset would allow, and it never
risks stitching two unrelated contracts together. Trades themselves never
span a session boundary regardless (EXIT_FORCE_TIME still forces flat by
15:10 IST every day, same as live/API-backtest) -- only the
PATTERN-DETECTION lookback window is affected by the week-reset choice.

No chart PNGs are rendered for this backtest (unlike blackbox_backtest.py)
-- the current admin UI (AdminStrategyReport.jsx / adapters.js) doesn't
consume per-trade chart images at all, and rendering + storing one per trade
across several thousand trades would be pure wasted compute/storage for a
run this size.
"""
from __future__ import annotations

import csv
import logging
import os
import uuid
from collections import defaultdict
from datetime import datetime, timezone

from blackbox_prism_alpha import (
    IST, VARIANT_CONFIG, MAX_TRADES_PER_SESSION, ENTRY_START_TIME, ATM_DRIFT_POINTS, TARGET_POINTS,
    _analyze_option_bars, _gate_entry, _evaluate_exit,
)

logger = logging.getLogger(__name__)

CSV_ROOT_DEFAULT = os.environ.get(
    "PRISM_ALPHA_CSV_ROOT",
    r"C:\Users\Prithviraj\OneDrive\Desktop\SAC CSVs\Nifty Options Backtest Data\Nifty_Options_1min\Week_1min",
)
OPT_TYPE_MAP = {"CALL": "CE", "PUT": "PE"}

CSV_BACKTEST_COLLECTIONS = {
    "prism_alpha": "blackbox_prism_alpha_backtest_trades",
    "prism_alpha_2": "blackbox_prism_alpha2_backtest_trades",
}


def _list_day_files(csv_root: str) -> list:
    """Every NIFTY_<date>_1m.csv across every year-range subfolder, sorted
    chronologically by the date in the filename (folder names are ranges,
    not sortable dates, so this doesn't rely on folder order)."""
    out = []
    for folder in sorted(os.listdir(csv_root)):
        fp = os.path.join(csv_root, folder)
        if not os.path.isdir(fp):
            continue
        for fn in os.listdir(fp):
            if fn.startswith("NIFTY_") and fn.endswith("_1m.csv"):
                date_str = fn[len("NIFTY_"):-len("_1m.csv")]
                out.append((date_str, os.path.join(fp, fn)))
    out.sort(key=lambda x: x[0])
    return out


def _load_day(path: str) -> dict:
    """One day's CSV -> {"times": sorted datetimes, "spot": {dt: float},
    "bars": {(strike_price:int, "CE"/"PE"): [bar,...] sorted by dt},
    "atm_strike": {dt: strike_price}}. Deduped on (datetime, strike_label,
    option_type) -- see module docstring for why a handful of files need
    this."""
    seen = set()
    bars = defaultdict(list)
    spot = {}
    atm_strike = {}
    with open(path, newline="") as f:
        r = csv.DictReader(f)
        for row in r:
            key = (row["datetime"], row["strike_label"], row["option_type"])
            if key in seen:
                continue
            seen.add(key)
            dt = datetime.strptime(row["datetime"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=IST)
            strike = int(round(float(row["strike_price"])))
            opt = OPT_TYPE_MAP[row["option_type"]]
            bars[(strike, opt)].append({
                "ts": dt.strftime("%d%m%Y%H%M"), "dt": dt, "open": float(row["open"]), "high": float(row["high"]),
                "low": float(row["low"]), "close": float(row["close"]),
            })
            spot[dt] = float(row["spot"])
            if row["strike_label"] == "ATM":
                atm_strike[dt] = strike
    for lst in bars.values():
        lst.sort(key=lambda b: b["dt"])
    return {"times": sorted(spot.keys()), "spot": spot, "bars": dict(bars), "atm_strike": atm_strike}


def _iso_week(d) -> tuple:
    iso = d.isocalendar()
    return (iso[0], iso[1])


def run_csv_backtest(csv_root: str = None, progress_every: int = 50) -> dict:
    """Pure, no-I/O walk-forward replay across every day file in csv_root, in
    chronological order. Returns {"summary": {...}, "trades": {variant:
    [trade dict, ...]}} -- persistence is a separate step (see
    save_csv_backtest_results) so this can be re-run/inspected without a live
    DB connection."""
    csv_root = csv_root or CSV_ROOT_DEFAULT
    day_files = _list_day_files(csv_root)
    if not day_files:
        raise RuntimeError(f"No CSV day files found under {csv_root}")

    run_id = str(uuid.uuid4())
    trades_by_variant = {v: [] for v in VARIANT_CONFIG}
    variant_state = {v: {"open_trade": None, "closed_today": 0} for v in VARIANT_CONFIG}

    week_bars = {}     # (strike, "CE"/"PE") -> accumulated bars, reset every ISO week
    bar_pos = {}       # same key -> next-unconsumed index into week_bars[key]
    current_week = None
    days_processed = 0

    for date_str, path in day_files:
        day = _load_day(path)
        if not day["times"]:
            continue

        wk = _iso_week(day["times"][0].date())
        if wk != current_week:
            current_week = wk
            week_bars = {}
            bar_pos = {}

        for key, bars in day["bars"].items():
            week_bars.setdefault(key, []).extend(bars)

        def _bars_upto(key, now_sim):
            bars = week_bars.get(key)
            if not bars:
                return []
            pos = bar_pos.get(key, 0)
            n = len(bars)
            while pos < n and bars[pos]["dt"] <= now_sim:
                pos += 1
            bar_pos[key] = pos
            return bars[:pos]

        atm_anchor = None
        for now_sim in day["times"]:
            spot_ltp = day["spot"][now_sim]

            # ---- exits for any open trades, per variant ------------------
            for variant, st in variant_state.items():
                trade = st["open_trade"]
                if trade is None:
                    continue
                key = (trade["strike"], trade["direction"])
                sliced = _bars_upto(key, now_sim)
                if not sliced:
                    continue
                result = _evaluate_exit(sliced, trade, now_sim)
                if result["shift_event"] is not None:
                    trade["current_stop"] = result["current_stop"]
                    trade["stop_shift_history"].append(result["shift_event"])
                if result["action"] == "exited":
                    trade["status"] = "closed"
                    trade["exit_time"] = now_sim.isoformat()
                    trade["exit_price"] = result["exit_price"]
                    trade["exit_reason"] = result["exit_reason"]
                    trade["pnl"] = result["pnl"]
                    trades_by_variant[variant].append(trade)
                    st["closed_today"] += 1
                    st["open_trade"] = None

            # ---- which variants need a fresh entry check this tick? ------
            pending = [v for v, st in variant_state.items()
                       if st["open_trade"] is None
                       and st["closed_today"] < MAX_TRADES_PER_SESSION
                       and now_sim.time() >= ENTRY_START_TIME]
            if not pending:
                continue

            if atm_anchor is None or abs(spot_ltp - atm_anchor["anchor_spot"]) > ATM_DRIFT_POINTS:
                atm_strike = day["atm_strike"].get(now_sim)
                if atm_strike is None:
                    continue  # no ATM-labeled row at this exact tick -- skip, never guess
                atm_anchor = {"atm": atm_strike, "anchor_spot": spot_ltp}
            atm = atm_anchor["atm"]

            ce_bars = _bars_upto((atm, "CE"), now_sim)
            pe_bars = _bars_upto((atm, "PE"), now_sim)
            if not ce_bars and not pe_bars:
                continue

            ce_analysis = _analyze_option_bars(ce_bars, "CE") if ce_bars else {"pattern_found": False, "reason": "no CE data"}
            pe_analysis = _analyze_option_bars(pe_bars, "PE") if pe_bars else {"pattern_found": False, "reason": "no PE data"}

            for variant in pending:
                cfg = VARIANT_CONFIG[variant]
                st = variant_state[variant]
                ce_check = _gate_entry(ce_analysis, cfg["require_indicators"])
                pe_check = _gate_entry(pe_analysis, cfg["require_indicators"])
                both_qualify = ce_check["qualifies"] and pe_check["qualifies"]

                direction, check = None, None
                if ce_check["qualifies"]:
                    direction, check = "CE", ce_check
                elif pe_check["qualifies"]:
                    direction, check = "PE", pe_check
                if direction is None:
                    continue

                conditions_met = dict(check["conditions_met"])
                if both_qualify:
                    conditions_met["simultaneous_signal_conflict"] = True
                    conditions_met["other_direction_also_qualified"] = "PE" if direction == "CE" else "CE"

                entry_price = check["entry_price"]
                st["open_trade"] = {
                    "id": str(uuid.uuid4()),
                    "backtest_run_id": run_id,
                    "date": date_str,
                    "direction": direction,
                    "strike": atm,
                    "expiry": None,  # not present in this CSV data -- see module docstring
                    "entry_time": now_sim.isoformat(),
                    "entry_price": entry_price,
                    "initial_stop": check["initial_stop"],
                    "current_stop": check["initial_stop"],
                    "stop_shift_history": [],
                    "target": entry_price + TARGET_POINTS,
                    "exit_time": None,
                    "exit_price": None,
                    "exit_reason": None,
                    "pnl": None,
                    "conditions_met": conditions_met,
                    "status": "open",
                }

        # End of day: force-close anything still open -- should only ever
        # happen for a trade entered on the day's very last tick(s), too
        # late for any further exit check that same day (EXIT_FORCE_TIME
        # would otherwise have already closed it naturally).
        for variant, st in variant_state.items():
            trade = st["open_trade"]
            if trade is not None:
                key = (trade["strike"], trade["direction"])
                bars = week_bars.get(key, [])
                if bars:
                    last_bar = bars[-1]
                    trade["status"] = "closed"
                    trade["exit_time"] = last_bar["dt"].isoformat()
                    trade["exit_price"] = last_bar["close"]
                    trade["exit_reason"] = "session_end"
                    trade["pnl"] = last_bar["close"] - trade["entry_price"]
                    trades_by_variant[variant].append(trade)
                st["open_trade"] = None
            # closed_today must reset every day regardless of whether there
            # was anything to force-close above -- the common case is a
            # variant already flat at day-end (trades already closed
            # normally via stop/target before EOD), and that must NOT skip
            # the reset. A real bug shipped exactly this way: gating the
            # reset behind "trade is not None" left closed_today accumulating
            # across days forever once a variant first hit
            # MAX_TRADES_PER_SESSION on some early day, permanently locking
            # it out of every subsequent day for the rest of the backtest
            # (caught because a 6-year run produced only 3 trades per
            # variant, all within the first two days).
            st["closed_today"] = 0

        days_processed += 1
        if progress_every and days_processed % progress_every == 0:
            logger.info("CSV backtest: %d/%d days processed (%s)", days_processed, len(day_files), date_str)

    summary = {
        "backtest_run_id": run_id,
        "data_source_granularity": "1_minute_csv_multi_year",
        "start_date": day_files[0][0],
        "end_date": day_files[-1][0],
        "days_processed": days_processed,
        "prism_alpha_trades": len(trades_by_variant["prism_alpha"]),
        "prism_alpha_2_trades": len(trades_by_variant["prism_alpha_2"]),
        "run_at": datetime.now(timezone.utc).isoformat(),
    }
    return {"summary": summary, "trades": trades_by_variant}


async def save_csv_backtest_results(db, result: dict) -> dict:
    """Persists a run_csv_backtest() result into the SAME collections the
    live-API backtest (blackbox_backtest.py) and its admin routes already
    read from (blackbox_backtest_runs, blackbox_prism_alpha_backtest_trades,
    blackbox_prism_alpha2_backtest_trades) -- the existing admin report UI
    (AdminStrategyReport.jsx via adapters.js) already picks whichever run has
    the newest run_at automatically, so no new route/UI is needed for this
    to show up. A later /admin/prism-alpha-backtest-run (the live-API,
    14-day version) will supersede this again if run afterward -- same
    'latest run wins' semantics as already existed."""
    summary = result["summary"]
    for variant, trades in result["trades"].items():
        if not trades:
            continue
        await db[CSV_BACKTEST_COLLECTIONS[variant]].insert_many([dict(t) for t in trades])
    await db.blackbox_backtest_runs.insert_one(dict(summary))
    return summary


if __name__ == "__main__":
    import asyncio
    import sys
    from pathlib import Path

    from dotenv import load_dotenv
    from motor.motor_asyncio import AsyncIOMotorClient

    load_dotenv(Path(__file__).parent / ".env")

    async def _main():
        root = sys.argv[1] if len(sys.argv) > 1 else None
        result = run_csv_backtest(root)
        print(result["summary"])
        client = AsyncIOMotorClient(os.environ["MONGO_URL"])
        db = client[os.environ["DB_NAME"]]
        saved = await save_csv_backtest_results(db, result)
        print("saved run:", saved["backtest_run_id"])

    asyncio.run(_main())
