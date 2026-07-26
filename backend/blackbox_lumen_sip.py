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


async def _fetch_per_instrument_series(definedge) -> dict:
    per_instrument_series = {}
    for symbol, cfg in INSTRUMENTS.items():
        bars = await _fetch_daily_bars(definedge, symbol, cfg["segment"])
        per_instrument_series[symbol] = evaluate_instrument_series(bars)
    return per_instrument_series


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
    from scratch each time (idempotent — always the same hypothetical
    "SIP had started at inception" replay, not tied to any real elapsed
    time)."""
    per_instrument_series = await _fetch_per_instrument_series(definedge)

    all_dates = sorted(set().union(*[
        {row["date"] for row in series} for series in per_instrument_series.values()
    ])) if per_instrument_series else []

    units = {symbol: 0.0 for symbol in INSTRUMENTS}
    cash = {symbol: 0.0 for symbol in INSTRUMENTS}
    portfolio_snapshots, signals, _, _, _, last_phase = _walk_portfolio(per_instrument_series, all_dates, units, cash)

    await db.blackbox_lumen_sip_backtest_signals.delete_many({})
    await db.blackbox_lumen_sip_backtest_portfolio.delete_many({})
    if signals:
        await db.blackbox_lumen_sip_backtest_signals.insert_many(signals)
    if portfolio_snapshots:
        await db.blackbox_lumen_sip_backtest_portfolio.insert_many(portfolio_snapshots)

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
