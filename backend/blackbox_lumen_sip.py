"""
Lumen SIP — long-term Renko + MAST-cloud trend-following SIP allocation
across NIFTYBEES and GOLDBEES (Black Box).

READ-ONLY, SIGNAL-LOGGING + SIMULATION ONLY. This module never places,
modifies, or cancels an order. It only calls Definedge's existing read-only
market-data methods already used elsewhere in this codebase
(definedge_service.py):
  - resolve_symbol(master_df, segment, symbol)   (via DefinedgeService._get_all_master())
  - DefinedgeService.daily_history(segment, token, years)
No order-placement, modification, or cancellation endpoint is referenced
anywhere in this module.

Unlike Prism Alpha, this strategy's phase (Buy/Cash) is intentionally NOT
concealed in the UI — the underlying mechanics come from a public Definedge
video/education source, not a proprietary pattern engine.

LIVE vs BACKTEST — same distinction Prism Alpha draws between its live
trades and backtest trades collections, applied here:
  - evaluate_lumen_sip_live() -> blackbox_lumen_sip_signals /
    blackbox_lumen_sip_portfolio: a REAL, forward-only portfolio that
    resumes from its last recorded state each call. On its very first call
    ever there's nothing to resume, so it starts fresh from the most
    recent trading day ("the SIP starts today"), not from 10 years ago.
  - run_lumen_sip_backtest() -> blackbox_lumen_sip_backtest_signals /
    blackbox_lumen_sip_backtest_portfolio: an illustrative "what if this
    had started at inception" replay over the full available history,
    always rebuilt from a zero starting portfolio on every call.
Both share the same signal logic (evaluate_instrument_series) and the same
monthly-SIP/full-exit/full-re-entry bookkeeping (_walk_portfolio) — they
only differ in which dates they walk and what starting state they resume
from.

Chart type: Renko (see blackbox_renko.py — NOT the P&F engine in
blackbox_prism_alpha.py; the two chart types have genuinely different
construction rules and are not interchangeable).

MAST indicator — CONFIRMED, not guessed, via Definedge's own published
writeup (Prashant Shah, "MAST Indicator", shelf.definedgesecurities.com;
same author as the Renko pattern library used for blackbox_renko.py). Two
prior implementation attempts in this module (a static SMA+/-ATR channel,
then a single fused Supertrend-style trailing band) were both wrong and
replaced once this source was read — see git history if curious why they
failed on real data. The actual formula is much simpler:

MAST = a plain MA(Period1, Close) line AND a classic, textbook
Supertrend(Period2, Multiplier) line, plotted as two INDEPENDENT,
unmodified standard indicators (not fused into one hybrid band). The
shaded "cloud" is just the region between these two lines at each point.
Band color: green while price is above the Supertrend line, red while
price is below it (this is the ONLY thing that decides color — nothing to
do with the MA line).

PARAMETERS — two different confirmed sources, do not conflate them:
tradepoint.definedge.com's indicator dialog shows the platform's generic
OUT-OF-BOX default (Period1=10, Period2=10, Multiplier=3, Average Type=SMA)
when the indicator is freshly added with no configuration. Lumen SIP does
NOT use that default — the user provided a screenshot of the actual "Mast
Settings" configured for THIS strategy: Period1=40, Period2=40,
Multiplier=10, Average Type=EMA (not SMA). Use these strategy-specific
values (MAST_PERIOD1/2/MULTIPLIER below), not the platform default.

Per the source doc, MAST plotted on a Renko chart runs on the RENKO BRICK
SEQUENCE itself (each brick treated as a synthetic OHLC bar), not the
underlying daily bars — explicitly called out as "a potent force in Renko
charts" because of the brick's diagonal plotting. That's what this module
does: build_renko_bricks() first, then compute_mast() runs on the bricks.

Lumen SIP's binary buy/cash signal (see evaluate_instrument_series) uses
the source doc's simplest zone pair — "above the MAST band: bullish
continuation" / "below the band: bearish continuation" — i.e. a brick
closing fully above BOTH lines is a buy, fully below BOTH lines is a sell.
The two zones BETWEEN the lines (green band = below MA/above ST, red band
= above MA/below ST) are documented as reversal-PATTERN lookup zones for
combining with objective price patterns (Prism-Alpha-style), not relevant
to Lumen SIP's simpler always-in/always-out design, so phase just holds
while price is inside the band.
"""
from datetime import date

from blackbox_renko import build_renko_bricks

# ---------------------------------------------------------------------------
# Strategy parameters (from the approved spec + live-verified MAST params)
# ---------------------------------------------------------------------------
BRICK_PCT = 0.0025        # 0.25% of each day's own opening price — confirmed with user
MAST_PERIOD1 = 40        # EMA basis period — confirmed via user's "Mast Settings" screenshot for THIS strategy
MAST_PERIOD2 = 40        # ATR period — confirmed via user's "Mast Settings" screenshot for THIS strategy
MAST_MULTIPLIER = 10     # ATR multiplier — confirmed via user's "Mast Settings" screenshot for THIS strategy

MONTHLY_SIP_TOTAL = 5000      # Rs 5,000/month total — confirmed with user
NIFTYBEES_ALLOCATION = 0.75
GOLDBEES_ALLOCATION = 0.25

INSTRUMENTS = {
    "NIFTYBEES": {"segment": "NSE", "allocation": NIFTYBEES_ALLOCATION},
    "GOLDBEES": {"segment": "NSE", "allocation": GOLDBEES_ALLOCATION},
}


# ---------------------------------------------------------------------------
# MAST — a plain SMA(Period1) line + a classic Supertrend(Period2,
# Multiplier) line, independently computed, overlaid on the Renko brick
# sequence (see module docstring — confirmed via Definedge's own writeup).
# ---------------------------------------------------------------------------
def _synthetic_ohlc_from_bricks(bricks: list) -> list:
    """Each Renko brick becomes one synthetic OHLC bar for indicator
    purposes — standard practice for running bar-based indicators (SMA,
    ATR/Supertrend) on a Renko brick series, and consistent with the source
    doc's description of MAST following the brick's own diagonal plot."""
    return [{
        "date": b["ts"],
        "open": b["open_price"],
        "high": max(b["open_price"], b["close_price"]),
        "low": min(b["open_price"], b["close_price"]),
        "close": b["close_price"],
    } for b in bricks]


def _true_range(bar: dict, prev_close: float) -> float:
    return max(
        bar["high"] - bar["low"],
        abs(bar["high"] - prev_close),
        abs(bar["low"] - prev_close),
    )


def _wilder_atr_series(bars: list, period: int) -> list:
    """Wilder-smoothed ATR, aligned to `bars` (leading Nones until the first
    full-period average exists) — same smoothing convention already used for
    RSI in blackbox_prism_alpha.py's compute_rsi_series()."""
    if len(bars) < period + 1:
        return [None] * len(bars)
    trs = [_true_range(bars[i], bars[i - 1]["close"]) for i in range(1, len(bars))]
    atrs = [None] * period
    atr = sum(trs[:period]) / period
    atrs.append(atr)
    for tr in trs[period:]:
        atr = (atr * (period - 1) + tr) / period
        atrs.append(atr)
    return atrs


def _ema_series(closes: list, period: int) -> list:
    """Standard EMA, seeded with a plain average of the first `period`
    values (same seeding convention as the RSI-overlay `_ema` helper in
    blackbox_prism_alpha.py) — Lumen SIP's MAST uses EMA, not SMA, per the
    user's confirmed "Mast Settings" screenshot (Average Type: EMA)."""
    out = [None] * len(closes)
    if len(closes) < period:
        return out
    seed = sum(closes[:period]) / period
    out[period - 1] = seed
    k = 2.0 / (period + 1)
    e = seed
    for i in range(period, len(closes)):
        e = closes[i] * k + e * (1 - k)
        out[i] = e
    return out


def compute_mast(brick_bars: list, period1: int = MAST_PERIOD1, period2: int = MAST_PERIOD2,
                  multiplier: int = MAST_MULTIPLIER) -> list:
    """brick_bars: synthetic OHLC per Renko brick (see
    _synthetic_ohlc_from_bricks). Returns a list aligned to `brick_bars`:
    {date, ma, supertrend} or None entries while there isn't enough history
    yet for both the EMA and ATR.

    `ma` = EMA(period1, Close) — confirmed "Average Type: EMA" for this
    strategy, NOT the platform's generic SMA default (see module
    docstring). `supertrend` = classic HL2-basis, Wilder-ATR
    Supertrend(period2, multiplier) — the standard textbook formula,
    unmodified; MAST is these two independent lines, not a fused band."""
    closes = [b["close"] for b in brick_bars]
    ma = _ema_series(closes, period1)
    atr = _wilder_atr_series(brick_bars, period2)

    out = [None] * len(brick_bars)
    final_upper = final_lower = None
    trend = None

    for i, bar in enumerate(brick_bars):
        if ma[i] is None or atr[i] is None:
            continue

        hl2 = (bar["high"] + bar["low"]) / 2.0
        basic_upper = hl2 + multiplier * atr[i]
        basic_lower = hl2 - multiplier * atr[i]
        price = bar["close"]
        prev = out[i - 1] if i > 0 else None

        if prev is None:
            final_upper, final_lower = basic_upper, basic_lower
            trend = "up" if price >= hl2 else "down"
        else:
            prev_price = brick_bars[i - 1]["close"]
            final_upper = basic_upper if (basic_upper < final_upper or prev_price > final_upper) else final_upper
            final_lower = basic_lower if (basic_lower > final_lower or prev_price < final_lower) else final_lower

            if trend == "up" and price < final_lower:
                trend = "down"
            elif trend == "down" and price > final_upper:
                trend = "up"

        out[i] = {
            "date": bar["date"],
            "ma": ma[i],
            "supertrend": final_lower if trend == "up" else final_upper,
        }

    return out


# ---------------------------------------------------------------------------
# Per-instrument phase evaluation
# ---------------------------------------------------------------------------
def evaluate_instrument_series(bars: list) -> list:
    """Builds the Renko brick series once, computes MAST on it, and walks
    the bricks forward (NOT the raw daily bars — see module docstring)
    producing one row per brick: {date, price, phase, signal_type|None,
    pattern|None, box_level}. Phase starts 'cash' and only changes on an
    explicit BUY/SELL trigger — the source doc's "above/below the band"
    continuation zones (the simplest, least ambiguous of MAST's documented
    zones — see module docstring for why the two intermediate reversal
    zones aren't used here):
      BUY:  a brick closes fully above BOTH the MA and Supertrend lines.
      SELL: a brick closes fully below BOTH the MA and Supertrend lines.
    While a brick closes between the two lines, phase persists unchanged.
    """
    bricks = build_renko_bricks(bars, BRICK_PCT)
    if not bricks:
        return []

    brick_bars = _synthetic_ohlc_from_bricks(bricks)
    mast_series = compute_mast(brick_bars)

    out = []
    phase = "cash"

    for i, brick in enumerate(bricks):
        mast = mast_series[i]
        if mast is None:
            continue

        price = brick["close_price"]
        band_top = max(mast["ma"], mast["supertrend"])
        band_bottom = min(mast["ma"], mast["supertrend"])
        signal_type = None
        pattern = None

        if phase != "buy" and price > band_top:
            phase, signal_type, pattern = "buy", "buy", "mast_cloud_flip"
        elif phase == "buy" and price < band_bottom:
            phase, signal_type, pattern = "cash", "sell", "mast_cloud_flip"

        out.append({
            "date": brick["ts"],
            "price": price,
            "phase": phase,
            "signal_type": signal_type,
            "pattern": pattern,
            "box_level": brick["level"],
        })

    return out


# ---------------------------------------------------------------------------
# Definedge data access — READ-ONLY.
# ---------------------------------------------------------------------------
async def _fetch_daily_bars(definedge, symbol: str, segment: str) -> list:
    master = await definedge._get_all_master()
    token = definedge.resolve_symbol(master, segment, symbol)["token"]
    return await definedge.daily_history(segment, token, years=10)


async def _fetch_all_bars(definedge) -> dict:
    """Raw daily OHLC bars per instrument — the shared source both the
    signal engine (evaluate_instrument_series) and the vanilla-SIP
    benchmark (_simulate_vanilla_sip) derive from, fetched once per
    backtest run rather than duplicating the Definedge calls."""
    return {
        symbol: await _fetch_daily_bars(definedge, symbol, cfg["segment"])
        for symbol, cfg in INSTRUMENTS.items()
    }


async def _fetch_per_instrument_series(definedge) -> dict:
    all_bars = await _fetch_all_bars(definedge)
    return {symbol: evaluate_instrument_series(bars) for symbol, bars in all_bars.items()}


# ---------------------------------------------------------------------------
# Portfolio walk-forward — shared by both the backtest (full since-inception
# replay, always rebuilt from zero) and live tracking (resumes from
# wherever it last left off, only walks NEW dates). Same monthly-SIP-
# deployment / full-exit / full-re-entry rules either way.
# ---------------------------------------------------------------------------
def _walk_portfolio(per_instrument_series: dict, dates: list, units: dict, cash: dict, last_month: str = None,
                     last_phase: dict = None) -> tuple:
    """Returns (portfolio_snapshots, signals, final_units, final_cash,
    final_month, final_phase) for exactly the given `dates`, starting from
    the given `units`/`cash`/`last_month`/`last_phase` state (all zero/
    'cash' for a fresh backtest; the last live snapshot's state for an
    incremental live run).

    The monthly SIP contribution and cash deployment both apply on EVERY
    date in the combined timeline, not just dates where this specific
    symbol has a fresh brick — a brick only forms sparsely (e.g. GOLDBEES
    can go weeks between bricks while sitting in cash), and gating the
    monthly deposit on "this symbol has a row today" silently dropped whole
    months of contributions whenever the other symbol's brick happened to
    land on the 1st of a new month instead. Caught live: GOLDBEES cash
    stayed flat at one month's contribution for 3+ calendar months in a
    row during a cash-phase stretch, instead of accumulating monthly as
    the spec requires ("collect the money and keep it aside" until the
    next buy signal)."""
    by_symbol_by_date = {
        symbol: {row["date"]: row for row in series}
        for symbol, series in per_instrument_series.items()
    }
    last_phase = dict(last_phase) if last_phase else {symbol: "cash" for symbol in INSTRUMENTS}
    last_price = {symbol: None for symbol in INSTRUMENTS}
    portfolio_snapshots = []
    signals = []

    for date in dates:
        month_key = date[:7]  # "YYYY-MM"
        is_new_month = month_key != last_month
        last_month = month_key

        for symbol, cfg in INSTRUMENTS.items():
            row = by_symbol_by_date[symbol].get(date)

            if is_new_month:
                cash[symbol] += MONTHLY_SIP_TOTAL * cfg["allocation"]

            if row is not None:
                price = row["price"]
                last_price[symbol] = price

                if row["signal_type"] is not None:
                    signals.append({
                        "instrument": symbol,
                        "date": row["date"],
                        "signal_type": row["signal_type"],
                        "price": row["price"],
                        "box_level": row["box_level"],
                        "pattern": row["pattern"],
                    })

                # Full exit to cash on a sell signal.
                if row["signal_type"] == "sell":
                    cash[symbol] += units[symbol] * price
                    units[symbol] = 0.0

                last_phase[symbol] = row["phase"]

            # Full re-entry: deploy any idle cash (a fresh buy signal, or
            # monthly contributions that arrived while already in a buy
            # phase) at the most recently known price for this leg — its
            # own fresh price today if a brick just printed, otherwise the
            # last brick's price, so cash doesn't sit undeployed for lack
            # of a brand-new brick on this exact date.
            if last_phase[symbol] == "buy" and cash[symbol] > 0 and last_price[symbol] is not None:
                units[symbol] += cash[symbol] / last_price[symbol]
                cash[symbol] = 0.0

        leg_value = {
            symbol: units[symbol] * (last_price[symbol] or 0.0) + cash[symbol]
            for symbol in INSTRUMENTS
        }
        total_value = sum(leg_value.values())
        portfolio_snapshots.append({
            "date": date,
            "niftybees_units": units["NIFTYBEES"],
            "niftybees_cash": cash["NIFTYBEES"],
            "niftybees_phase": last_phase["NIFTYBEES"],
            "niftybees_value": leg_value["NIFTYBEES"],
            "goldbees_units": units["GOLDBEES"],
            "goldbees_cash": cash["GOLDBEES"],
            "goldbees_phase": last_phase["GOLDBEES"],
            "goldbees_value": leg_value["GOLDBEES"],
            "total_value": total_value,
        })

    return portfolio_snapshots, signals, units, cash, last_month, last_phase


# ---------------------------------------------------------------------------
# Institutional-grade metrics — XIRR, max drawdown, round-trip trade stats,
# and a vanilla (no-signal) monthly-SIP benchmark over the identical period/
# amount/split. Computed once per backtest run and persisted, not
# recomputed on every page view (the vanilla benchmark needs the full raw
# price history, not just the signal series).
# ---------------------------------------------------------------------------
def _months_between(start_iso: str, end_iso: str) -> list:
    start_d, end_d = date.fromisoformat(start_iso), date.fromisoformat(end_iso)
    months = []
    cur = date(start_d.year, start_d.month, 1)
    while cur <= end_d:
        months.append(cur)
        cur = date(cur.year + 1, 1, 1) if cur.month == 12 else date(cur.year, cur.month + 1, 1)
    return months


def _xirr(cash_flows: list) -> float:
    """cash_flows: [(date_iso, amount)] — negative = outflow, positive =
    inflow. Newton-Raphson solve for the annualized rate where NPV=0 — the
    correct return metric for a periodic-contribution SIP (unlike CAGR,
    which assumes a single lump-sum entry)."""
    parsed = [(date.fromisoformat(d), amt) for d, amt in cash_flows]
    d0 = parsed[0][0]

    def npv(rate):
        return sum(amt / (1 + rate) ** ((d - d0).days / 365.0) for d, amt in parsed)

    def dnpv(rate):
        return sum(-((d - d0).days / 365.0) * amt / (1 + rate) ** ((d - d0).days / 365.0 + 1) for d, amt in parsed)

    rate = 0.1
    for _ in range(200):
        f, fp = npv(rate), dnpv(rate)
        if abs(fp) < 1e-12:
            break
        new_rate = rate - f / fp
        if abs(new_rate - rate) < 1e-8:
            rate = new_rate
            break
        rate = new_rate
    return rate


def _max_drawdown(values: list) -> dict:
    """values: [(date_iso, value)]. Peak-to-trough decline of the running
    high-water mark."""
    peak, peak_date = values[0][1], values[0][0]
    max_dd = 0.0
    worst_peak_date = worst_trough_date = values[0][0]
    for d, v in values:
        if v > peak:
            peak, peak_date = v, d
        dd = (peak - v) / peak if peak > 0 else 0.0
        if dd > max_dd:
            max_dd = dd
            worst_peak_date, worst_trough_date = peak_date, d
    return {"max_drawdown_pct": max_dd * 100, "dd_peak_date": worst_peak_date, "dd_trough_date": worst_trough_date}


def _round_trip_stats(signals: list, symbol: str) -> dict:
    sigs = [s for s in signals if s["instrument"] == symbol]
    trips, buy = [], None
    for s in sigs:
        if s["signal_type"] == "buy":
            buy = s
        elif s["signal_type"] == "sell" and buy is not None:
            trips.append((buy, s))
            buy = None
    if not trips:
        return {"count": 0, "win_rate_pct": None, "avg_return_pct": None, "best_pct": None, "worst_pct": None, "avg_hold_days": None}
    rets = [(s["price"] - b["price"]) / b["price"] for b, s in trips]
    holds = [(date.fromisoformat(s["date"]) - date.fromisoformat(b["date"])).days for b, s in trips]
    wins = sum(1 for r in rets if r > 0)
    return {
        "count": len(trips),
        "win_rate_pct": wins / len(trips) * 100,
        "avg_return_pct": sum(rets) / len(rets) * 100,
        "best_pct": max(rets) * 100,
        "worst_pct": min(rets) * 100,
        "avg_hold_days": sum(holds) / len(holds),
    }


def _simulate_vanilla_sip(all_bars: dict, start_iso: str, end_iso: str) -> dict:
    """The benchmark: identical ₹/month, identical 75/25 split, identical
    period — but no signal at all. Every month's contribution buys units
    immediately and is simply held. Isolates exactly what the Renko+MAST
    timing adds (or costs) versus doing nothing but showing up monthly."""
    start_d, end_d = date.fromisoformat(start_iso), date.fromisoformat(end_iso)
    months = _months_between(start_iso, end_iso)

    px, ordered_dates = {}, {}
    for symbol, bars in all_bars.items():
        filtered = {date.fromisoformat(b["date"]): b["close"] for b in bars if date.fromisoformat(b["date"]) >= start_d}
        px[symbol] = filtered
        ordered_dates[symbol] = sorted(filtered.keys())

    def price_on_or_after(symbol, target):
        for d in ordered_dates[symbol]:
            if d >= target:
                return d, px[symbol][d]
        return None, None

    units = {symbol: 0.0 for symbol in INSTRUMENTS}
    cash_flows = {symbol: [] for symbol in INSTRUMENTS}
    combined_flows = []

    for m in months:
        month_total = 0.0
        for symbol, cfg in INSTRUMENTS.items():
            d, p = price_on_or_after(symbol, m)
            if d is None:
                continue
            contrib = MONTHLY_SIP_TOTAL * cfg["allocation"]
            units[symbol] += contrib / p
            cash_flows[symbol].append((d.isoformat(), -contrib))
            month_total += contrib
        combined_flows.append((m.isoformat(), -month_total))

    # daily mark-to-market curve, only over dates both instruments have prices
    common_dates = sorted(set(ordered_dates["NIFTYBEES"]) & set(ordered_dates["GOLDBEES"]))
    u = {symbol: 0.0 for symbol in INSTRUMENTS}
    month_idx = 0
    curve = []
    for d in common_dates:
        while month_idx < len(months) and months[month_idx] <= d:
            for symbol, cfg in INSTRUMENTS.items():
                md, mp = price_on_or_after(symbol, months[month_idx])
                if md is not None and d >= md:
                    u[symbol] += (MONTHLY_SIP_TOTAL * cfg["allocation"]) / mp
            month_idx += 1
        total = sum(u[s] * px[s][d] for s in INSTRUMENTS if d in px[s])
        curve.append((d.isoformat(), total))

    final_price = {symbol: px[symbol][ordered_dates[symbol][-1]] for symbol in INSTRUMENTS}
    final_value = {symbol: units[symbol] * final_price[symbol] for symbol in INSTRUMENTS}
    total_final = sum(final_value.values())

    for symbol in INSTRUMENTS:
        cash_flows[symbol].append((end_iso, final_value[symbol]))
    combined_flows.append((end_iso, total_final))

    total_invested = len(months) * MONTHLY_SIP_TOTAL
    dd = _max_drawdown(curve)

    result = {
        "total_invested": total_invested,
        "final_value": total_final,
        "absolute_return_pct": (total_final / total_invested - 1) * 100 if total_invested else 0.0,
        "xirr_pct": _xirr(combined_flows) * 100,
        **dd,
    }
    for symbol, cfg in INSTRUMENTS.items():
        inv = len(months) * MONTHLY_SIP_TOTAL * cfg["allocation"]
        result[symbol.lower()] = {
            "total_invested": inv,
            "final_value": final_value[symbol],
            "absolute_return_pct": (final_value[symbol] / inv - 1) * 100 if inv else 0.0,
            "xirr_pct": _xirr(cash_flows[symbol]) * 100,
        }

    step = max(1, len(curve) // 300)
    sampled = [curve[i] for i in range(0, len(curve), step)]
    if sampled[-1] != curve[-1]:
        sampled.append(curve[-1])
    result["curve"] = [{"date": d, "value": round(v, 2)} for d, v in sampled]

    return result


def _compute_backtest_metrics(portfolio_snapshots: list, signals: list, all_bars: dict) -> dict:
    if not portfolio_snapshots:
        return {"has_data": False}

    start_iso, end_iso = portfolio_snapshots[0]["date"], portfolio_snapshots[-1]["date"]
    months = _months_between(start_iso, end_iso)
    final = portfolio_snapshots[-1]
    total_days = len(portfolio_snapshots)

    total_values = [(p["date"], p["total_value"]) for p in portfolio_snapshots]
    nifty_values = [(p["date"], p["niftybees_value"]) for p in portfolio_snapshots]
    gold_values = [(p["date"], p["goldbees_value"]) for p in portfolio_snapshots]

    combined_flows = [(m.isoformat(), -MONTHLY_SIP_TOTAL) for m in months]
    combined_flows.append((end_iso, final["total_value"]))
    nifty_flows = [(m.isoformat(), -MONTHLY_SIP_TOTAL * NIFTYBEES_ALLOCATION) for m in months]
    nifty_flows.append((end_iso, final["niftybees_value"]))
    gold_flows = [(m.isoformat(), -MONTHLY_SIP_TOTAL * GOLDBEES_ALLOCATION) for m in months]
    gold_flows.append((end_iso, final["goldbees_value"]))

    total_invested = len(months) * MONTHLY_SIP_TOTAL
    total_invested_n = len(months) * MONTHLY_SIP_TOTAL * NIFTYBEES_ALLOCATION
    total_invested_g = len(months) * MONTHLY_SIP_TOTAL * GOLDBEES_ALLOCATION

    n_buy_days = sum(1 for p in portfolio_snapshots if p["niftybees_phase"] == "buy")
    g_buy_days = sum(1 for p in portfolio_snapshots if p["goldbees_phase"] == "buy")

    return {
        "has_data": True,
        "period": {"start": start_iso, "end": end_iso, "months": len(months)},
        "current_phase": {"NIFTYBEES": final["niftybees_phase"], "GOLDBEES": final["goldbees_phase"]},
        "portfolio": {
            "total_invested": total_invested,
            "final_value": final["total_value"],
            "absolute_return_pct": (final["total_value"] / total_invested - 1) * 100,
            "xirr_pct": _xirr(combined_flows) * 100,
            **_max_drawdown(total_values),
        },
        "niftybees": {
            "allocation_pct": NIFTYBEES_ALLOCATION * 100,
            "total_invested": total_invested_n,
            "final_value": final["niftybees_value"],
            "absolute_return_pct": (final["niftybees_value"] / total_invested_n - 1) * 100,
            "xirr_pct": _xirr(nifty_flows) * 100,
            "time_in_market_pct": n_buy_days / total_days * 100,
            **_max_drawdown(nifty_values),
            "trade_stats": _round_trip_stats(signals, "NIFTYBEES"),
        },
        "goldbees": {
            "allocation_pct": GOLDBEES_ALLOCATION * 100,
            "total_invested": total_invested_g,
            "final_value": final["goldbees_value"],
            "absolute_return_pct": (final["goldbees_value"] / total_invested_g - 1) * 100,
            "xirr_pct": _xirr(gold_flows) * 100,
            "time_in_market_pct": g_buy_days / total_days * 100,
            **_max_drawdown(gold_values),
            "trade_stats": _round_trip_stats(signals, "GOLDBEES"),
        },
        "vanilla_sip": _simulate_vanilla_sip(all_bars, start_iso, end_iso),
    }


# ---------------------------------------------------------------------------
# Backtest — full since-inception (up to 10y) hypothetical replay, always
# rebuilt from a zero starting portfolio. Illustrative track record, NOT
# the live account (see evaluate_lumen_sip_live) — exactly the same
# distinction Prism Alpha draws between its live trades and its backtest
# trades collections.
# ---------------------------------------------------------------------------
async def run_lumen_sip_backtest(db, definedge) -> dict:
    """Re-fetches full history for every enabled instrument and replays the
    whole thing from a zero starting portfolio, rewriting
    blackbox_lumen_sip_backtest_signals / blackbox_lumen_sip_backtest_portfolio
    / blackbox_lumen_sip_backtest_metrics from scratch each time (idempotent
    — always the same hypothetical "SIP had started at inception" replay,
    not tied to any real elapsed time)."""
    all_bars = await _fetch_all_bars(definedge)
    per_instrument_series = {symbol: evaluate_instrument_series(bars) for symbol, bars in all_bars.items()}

    all_dates = sorted(set().union(*[
        {row["date"] for row in series} for series in per_instrument_series.values()
    ])) if per_instrument_series else []

    units = {symbol: 0.0 for symbol in INSTRUMENTS}
    cash = {symbol: 0.0 for symbol in INSTRUMENTS}
    portfolio_snapshots, signals, _, _, _, last_phase = _walk_portfolio(per_instrument_series, all_dates, units, cash)

    await db.blackbox_lumen_sip_backtest_signals.delete_many({})
    await db.blackbox_lumen_sip_backtest_portfolio.delete_many({})
    await db.blackbox_lumen_sip_backtest_metrics.delete_many({})
    if signals:
        await db.blackbox_lumen_sip_backtest_signals.insert_many(signals)
    if portfolio_snapshots:
        await db.blackbox_lumen_sip_backtest_portfolio.insert_many(portfolio_snapshots)

    metrics = _compute_backtest_metrics(portfolio_snapshots, signals, all_bars)
    if metrics.get("has_data"):
        await db.blackbox_lumen_sip_backtest_metrics.insert_one({"id": "current", **metrics})

    return {
        "instruments_evaluated": list(INSTRUMENTS.keys()),
        "signals_logged": len(signals),
        "portfolio_snapshots": len(portfolio_snapshots),
        "current_phase": last_phase,
    }


# ---------------------------------------------------------------------------
# Live tracking — a REAL, forward-only portfolio. Resumes from the last
# recorded live snapshot (persisted units/cash/phase); on its very first
# ever call there's no prior state to resume, so it seeds a fresh zero
# portfolio starting from the most recent available trading day ("the SIP
# starts today"), NOT from 10 years ago — that's what the backtest is for.
# Safe to call daily via cron (only walks dates after the last snapshot) or
# on-demand (catches up any gap since the last call).
# ---------------------------------------------------------------------------
async def evaluate_lumen_sip_live(db, definedge) -> dict:
    per_instrument_series = await _fetch_per_instrument_series(definedge)

    all_dates = sorted(set().union(*[
        {row["date"] for row in series} for series in per_instrument_series.values()
    ])) if per_instrument_series else []

    last_snapshot = await db.blackbox_lumen_sip_portfolio.find_one({}, {"_id": 0}, sort=[("date", -1)])

    if last_snapshot is None:
        # First ever live run: nothing to resume, and the full historical
        # range belongs to the backtest, not here — start today.
        new_dates = all_dates[-1:]
        units = {symbol: 0.0 for symbol in INSTRUMENTS}
        cash = {symbol: 0.0 for symbol in INSTRUMENTS}
        last_month = None
        seed_phase = None
    else:
        new_dates = [d for d in all_dates if d > last_snapshot["date"]]
        units = {"NIFTYBEES": last_snapshot["niftybees_units"], "GOLDBEES": last_snapshot["goldbees_units"]}
        cash = {"NIFTYBEES": last_snapshot["niftybees_cash"], "GOLDBEES": last_snapshot["goldbees_cash"]}
        last_month = last_snapshot["date"][:7]
        seed_phase = {"NIFTYBEES": last_snapshot["niftybees_phase"], "GOLDBEES": last_snapshot["goldbees_phase"]}

    if not new_dates:
        return {
            "instruments_evaluated": list(INSTRUMENTS.keys()),
            "signals_logged": 0,
            "portfolio_snapshots": 0,
            "current_phase": {
                "NIFTYBEES": last_snapshot["niftybees_phase"] if last_snapshot else "cash",
                "GOLDBEES": last_snapshot["goldbees_phase"] if last_snapshot else "cash",
            },
        }

    portfolio_snapshots, signals, _, _, _, last_phase = _walk_portfolio(
        per_instrument_series, new_dates, units, cash, last_month, seed_phase)

    if signals:
        await db.blackbox_lumen_sip_signals.insert_many(signals)
    if portfolio_snapshots:
        await db.blackbox_lumen_sip_portfolio.insert_many(portfolio_snapshots)

    return {
        "instruments_evaluated": list(INSTRUMENTS.keys()),
        "signals_logged": len(signals),
        "portfolio_snapshots": len(portfolio_snapshots),
        "current_phase": last_phase,
    }
