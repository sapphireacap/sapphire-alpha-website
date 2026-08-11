"""
Prism Alpha — intraday backtest engine (v2, real 1-minute Definedge data only).

READ-ONLY. Same Definedge endpoints already used by the live module — no new
ones (minute history for NSE/NFO segments, symbol master). Rebuilt after the
original EOD/NSE-bhavcopy version was removed entirely (2026-07-26, "the
data is not reliable, we will keep the record from the next trading
session"); this version uses ONLY real Definedge 1-minute bars, the exact
same granularity and the exact same pattern/indicator/exit functions
(imported from blackbox_prism_alpha, not reimplemented) as the live engine —
no EOD approximation, no external archive.

Real constraint this design works around (verified live, 2026-07-26):
Definedge's symbol master only lists contracts that have NOT expired yet —
there is no way to resolve a token for a weekly option whose expiry has
already passed (confirmed: today's master's earliest listed expiry was two
days out, nothing before it at all). This means the backtest CANNOT roll
through a true week-by-week historical ATM the way live evaluation does
(live always resolves whatever the CURRENT nearest weekly is). Instead it
fixes on the one nearest expiry that's actually resolvable today and walks
back through whichever ATM strike (100-multiples, from real Nifty spot
1-minute bars) was closest to spot on each historical day/minute, resolving
every strike against that SAME fixed expiry. This works because NSE lists
weekly strikes many weeks ahead of their own expiry, so a strike that is
ATM today often already has real (if thin, far-OTM-era) 1-minute trading
history — verified live up to ~80 days back for the then-current ATM
strike, thinner and patchier further back / further from spot. This is the
closest genuinely real (non-approximated) proxy achievable given the
token-resolution constraint — NOT a faithful replay of what a true
live-rolling-expiry engine would have done on each of those historical
dates (which would have used a different, now-inaccessible, expiry each
week). This caveat is surfaced prominently in the UI, same as the old
backtest's "EOD, not intraday" caveat was.
"""
import io
import logging
import uuid
from datetime import datetime, timezone, timedelta

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd
from bson import Binary

from blackbox_prism_alpha import (
    IST, VARIANT_CONFIG, MAX_TRADES_PER_SESSION, ENTRY_START_TIME,
    ATM_STRIKE_INCREMENT, ATM_DRIFT_POINTS, TARGET_POINTS,
    fetch_minute_bars, _analyze_option_bars, _gate_entry, _evaluate_exit,
)
from definedge_service import DefinedgeService, DefinedgeError, NIFTY_SPOT_TOKEN

logger = logging.getLogger(__name__)

BACKTEST_LOOKBACK_DAYS = 14  # ~1-2 weeks, per explicit instruction — deliberately
                               # short, not just a data-availability cap. The live
                               # strategy rolls to a NEW weekly expiry contract every
                               # week (DefinedgeService._pick_expiry's Mon/Tue-roll
                               # rule), but this backtest is fixed on ONE expiry for
                               # its whole walk (expired contracts' tokens can't be
                               # resolved — see module docstring). A long window on
                               # that one fixed expiry would silently drift away from
                               # what live actually does the further back it goes
                               # (reusing one aging contract's strikes across many
                               # real weekly cycles it was never actually "current"
                               # for). Staying within ~1-2 weeks keeps the backtest
                               # inside (at most) a single real weekly cycle, the
                               # only window that's honestly comparable to live.
CHART_CONTEXT_BARS = 300      # bars of pre-entry context kept in each trade's PNG,
                               # so the chart shows the pattern forming into entry
                               # without plotting a whole multi-week history.

BACKTEST_COLLECTIONS = {
    "prism_alpha": "blackbox_prism_alpha_backtest_trades",
    "prism_alpha_2": "blackbox_prism_alpha2_backtest_trades",
}


async def _nearest_expiry_iso(df: pd.DataFrame) -> str:
    """The one nearest NIFTY weekly expiry currently resolvable at all (see
    module docstring) — every strike in the backtest is resolved against
    this SAME expiry."""
    SYMBOL, INSTR, EXPIRY = 2, 4, 5
    sub = df[(df[SYMBOL].astype(str) == "NIFTY") & (df[INSTR].astype(str) == "OPTIDX")]
    exps = pd.to_datetime(sub[EXPIRY].astype(str), format="%d%m%Y", errors="coerce").dt.date.dropna().unique()
    today = datetime.now(IST).date()
    expiry = DefinedgeService._pick_expiry(sorted(set(exps)), today)
    if expiry is None:
        raise DefinedgeError("No valid NIFTY expiry found in master.")
    return expiry.isoformat()


def _resolve_strike_tokens(df: pd.DataFrame, expiry_iso: str, strike: int):
    """CE/PE tokens for ONE strike at a FIXED, already-chosen expiry — unlike
    the live module's resolve_atm_option_tokens (which picks its own nearest
    expiry every call), the backtest fixes one expiry up front and walks
    many strikes against it. Returns None if either leg isn't listed."""
    SEG, TOKEN, SYMBOL, INSTR, EXPIRY, OPTTYPE, STRIKE = 0, 1, 2, 4, 5, 8, 9
    sub = df[(df[SYMBOL].astype(str) == "NIFTY")
             & (df[INSTR].astype(str) == "OPTIDX")
             & (df[OPTTYPE].astype(str).isin(["CE", "PE"]))].copy()
    sub["_strike"] = pd.to_numeric(sub[STRIKE], errors="coerce") / 100.0
    sub["_exp"] = pd.to_datetime(sub[EXPIRY].astype(str), format="%d%m%Y", errors="coerce").dt.date
    exp_date = datetime.strptime(expiry_iso, "%Y-%m-%d").date()

    out = {}
    for opt in ("CE", "PE"):
        row = sub[(sub["_strike"] == float(strike)) & (sub["_exp"] == exp_date) & (sub[OPTTYPE].astype(str) == opt)]
        if row.empty:
            return None
        out[opt] = str(row.iloc[0][TOKEN])
    return out


def _render_chart_png(bars: list, trade: dict) -> bytes:
    """PNG of the option's own 1-minute close price around the trade —
    CHART_CONTEXT_BARS before entry (so the pattern forming into entry is
    visible) through exit, with entry/stop/target lines and an exit marker.
    Dark theme to match the site. Returns raw PNG bytes (stored as Mongo
    Binary, never written to disk — Render's filesystem isn't persistent)."""
    entry_dt = datetime.fromisoformat(trade["entry_time"])
    before = [b for b in bars if b["dt"] < entry_dt][-CHART_CONTEXT_BARS:]
    after = [b for b in bars if b["dt"] >= entry_dt]
    plot_bars = before + after
    if not plot_bars:
        plot_bars = bars[-CHART_CONTEXT_BARS:]

    times = [b["dt"] for b in plot_bars]
    closes = [b["close"] for b in plot_bars]

    fig, ax = plt.subplots(figsize=(10, 5))
    fig.patch.set_facecolor("#0A0D18")
    ax.set_facecolor("#0A0D18")

    ax.plot(times, closes, color="#437EEB", linewidth=1.1, label=f"{trade['direction']} {trade['strike']} premium")
    ax.axvline(entry_dt, color="#94A3B8", linestyle="--", linewidth=1, label="Entry")
    ax.axhline(trade["entry_price"], color="#E2E8F0", linestyle=":", linewidth=1)
    ax.axhline(trade["initial_stop"], color="#EF4444", linestyle=":", linewidth=1, label="Initial stop")
    ax.axhline(trade["target"], color="#22C55E", linestyle=":", linewidth=1, label="Target")
    if trade.get("exit_price") is not None:
        exit_dt = datetime.fromisoformat(trade["exit_time"])
        ax.scatter([exit_dt], [trade["exit_price"]], color="#F59E0B", zorder=5, label=f"Exit ({trade['exit_reason']})")

    ax.set_title(f"{trade['date']}  {trade['direction']} {trade['strike']}  entry ₹{trade['entry_price']:.2f}", color="#E2E8F0", fontsize=11)
    ax.tick_params(colors="#94A3B8", labelsize=8)
    for spine in ax.spines.values():
        spine.set_color("#334155")
    ax.legend(fontsize=8, loc="best", facecolor="#0A0D18", labelcolor="#94A3B8", edgecolor="#334155")
    ax.grid(color="#1E293B", linewidth=0.5)
    fig.autofmt_xdate()

    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=100, bbox_inches="tight")
    plt.close(fig)
    return buf.getvalue()


async def run_backtest(db, definedge) -> dict:
    """Walk-forward, no-lookahead replay over REAL 1-minute Nifty spot +
    option bars, driven by the spot bar sequence (ATM/session-time gating)
    with per-tick, no-lookahead slices of whichever option contract is
    currently ATM for each variant. Reuses the live module's exact
    _analyze_option_bars / _gate_entry / _evaluate_exit — same functions,
    not reimplemented, so a backtest signal can never drift from what the
    live engine would have decided given the same bars. Runs BOTH variants
    (prism_alpha, prism_alpha_2) in one pass since they watch identical
    underlying data.
    """
    run_id = str(uuid.uuid4())
    now = datetime.now(IST)
    frm = (now - timedelta(days=BACKTEST_LOOKBACK_DAYS)).strftime("%d%m%Y0000")
    to = now.strftime("%d%m%Y%H%M")

    spot_bars = await fetch_minute_bars(definedge, "NSE", NIFTY_SPOT_TOKEN, frm=frm, to=to)
    if len(spot_bars) < 100:
        raise DefinedgeError("Not enough real Nifty spot 1-minute history to run a backtest.")

    df = await definedge._get_all_master()
    expiry_iso = await _nearest_expiry_iso(df)

    # Real historical strike range from the spot bars themselves (+1 step
    # buffer each side) — only strikes Nifty actually traded near get
    # resolved, not an arbitrary wide band.
    lo = int(min(b["close"] for b in spot_bars) // ATM_STRIKE_INCREMENT * ATM_STRIKE_INCREMENT) - ATM_STRIKE_INCREMENT
    hi = int(max(b["close"] for b in spot_bars) // ATM_STRIKE_INCREMENT * ATM_STRIKE_INCREMENT) + ATM_STRIKE_INCREMENT
    candidate_strikes = list(range(lo, hi + 1, ATM_STRIKE_INCREMENT))

    contract_bars = {}  # (strike, opt_type) -> chronological real bars (fetched once)
    for strike in candidate_strikes:
        tokens = _resolve_strike_tokens(df, expiry_iso, strike)
        if tokens is None:
            continue  # strike not listed at this expiry — skip, don't fake it
        for opt in ("CE", "PE"):
            bars = await fetch_minute_bars(definedge, "NFO", tokens[opt], frm=frm, to=to)
            if bars:
                contract_bars[(strike, opt)] = bars

    if not contract_bars:
        raise DefinedgeError("No option contracts with real historical 1-minute data were found for this expiry/strike range.")

    bar_pos = {}  # (strike, opt_type) -> next-unconsumed index, advanced monotonically as the walk proceeds

    def _bars_upto(key, now_sim):
        bars = contract_bars.get(key)
        if not bars:
            return []
        pos = bar_pos.get(key, 0)
        n = len(bars)
        while pos < n and bars[pos]["dt"] <= now_sim:
            pos += 1
        bar_pos[key] = pos
        return bars[:pos]

    variant_state = {v: {"open_trade": None, "closed_today": 0, "trades": []} for v in VARIANT_CONFIG}
    atm_anchor = None  # {"atm": int, "anchor_spot": float} — reset each new day
    current_date = None

    for bar in spot_bars:
        now_sim = bar["dt"]
        bar_date = now_sim.date().isoformat()
        if bar_date != current_date:
            current_date = bar_date
            atm_anchor = None
            for st in variant_state.values():
                st["closed_today"] = 0

        spot_ltp = bar["close"]

        # ---- exits for any open trades, per variant --------------------
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
                trade["chart_png"] = _render_chart_png(sliced, trade)
                st["trades"].append(trade)
                st["closed_today"] += 1
                st["open_trade"] = None

        # ---- which variants need a fresh entry check this tick? --------
        pending = []
        for variant, st in variant_state.items():
            if st["open_trade"] is not None:
                continue
            if st["closed_today"] >= MAX_TRADES_PER_SESSION:
                continue
            if now_sim.time() < ENTRY_START_TIME:
                continue
            pending.append(variant)

        if not pending:
            continue

        # ATM: fixed at 9:20, held while flat until spot drifts more than
        # ATM_DRIFT_POINTS from the anchor — same rule as the live module's
        # _resolve_atm, replayed here against real historical spot ticks.
        if atm_anchor is None or abs(spot_ltp - atm_anchor["anchor_spot"]) > ATM_DRIFT_POINTS:
            atm = round(spot_ltp / ATM_STRIKE_INCREMENT) * ATM_STRIKE_INCREMENT
            atm_anchor = {"atm": atm, "anchor_spot": spot_ltp}
        atm = atm_anchor["atm"]

        ce_bars = _bars_upto((atm, "CE"), now_sim)
        pe_bars = _bars_upto((atm, "PE"), now_sim)
        if not ce_bars and not pe_bars:
            continue  # no real data for this strike at this point in time — skip, never fabricate

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
                "date": bar_date,
                "direction": direction,
                "strike": atm,
                "expiry": expiry_iso,
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

    # Anything still open when real data runs out gets force-closed at the
    # last available bar — NOT a real 3:10pm exit, flagged as its own reason
    # so it's never mistaken for a genuine session-end signal.
    for variant, st in variant_state.items():
        trade = st["open_trade"]
        if trade is None:
            continue
        key = (trade["strike"], trade["direction"])
        bars = contract_bars.get(key, [])
        if bars:
            last_bar = bars[-1]
            trade["status"] = "closed"
            trade["exit_time"] = last_bar["dt"].isoformat()
            trade["exit_price"] = last_bar["close"]
            trade["exit_reason"] = "data_ended"
            trade["pnl"] = last_bar["close"] - trade["entry_price"]
            trade["chart_png"] = _render_chart_png(bars, trade)
        st["trades"].append(trade)

    trade_counts = {}
    for variant, st in variant_state.items():
        collection_name = BACKTEST_COLLECTIONS[variant]
        trades = st["trades"]
        trade_counts[variant] = len(trades)
        if trades:
            docs = []
            for t in trades:
                doc = dict(t)
                doc["chart_png"] = Binary(doc["chart_png"]) if doc.get("chart_png") else None
                docs.append(doc)
            await db[collection_name].insert_many(docs)

    summary = {
        "backtest_run_id": run_id,
        "data_source_granularity": "1_minute_real",
        "expiry_used": expiry_iso,
        "strikes_with_data": sorted(set(k[0] for k in contract_bars)),
        "start_date": spot_bars[0]["dt"].date().isoformat(),
        "end_date": spot_bars[-1]["dt"].date().isoformat(),
        "spot_ticks_evaluated": len(spot_bars),
        "prism_alpha_trades": trade_counts["prism_alpha"],
        "prism_alpha_2_trades": trade_counts["prism_alpha_2"],
        "run_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.blackbox_backtest_runs.insert_one(dict(summary))
    return summary
