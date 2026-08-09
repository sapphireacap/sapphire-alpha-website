"""
Peter Tingle -- combined technical + fundamental caution scan for a single
stock. Deterministic, no LLM involvement, same spirit as Fracture Scan
(stock_terminal_scoring.py) -- this module supplies the technical-side
rules and reuses that module's `scan_red_flags` for the fundamental side,
so there is exactly one fundamental red-flag ruleset in the codebase.
"""

DEATH_CROSS_MARGIN_PCT = 1  # DMA-50 must sit >=1% below DMA-200 to count, not just noise
DRAWDOWN_WARN_PCT = -15
DRAWDOWN_FAIL_PCT = -30
WEEKLY_SHOCK_WARN_PCT = -4
WEEKLY_SHOCK_FAIL_PCT = -8

# US fundamental thresholds (Yahoo quoteSummary field conventions -- see
# us_stock_fundamentals.py). debtToEquity/shortPercentOfFloat/profitMargins
# all arrive already scaled to percent, matching how they're stored here.
US_LEVERAGE_FAIL_THRESHOLD = 200  # debt-to-equity > 200% (i.e. > 2x)
US_SHORT_INTEREST_WARN_THRESHOLD = 10  # % of float sold short
DMA_WINDOWS = {"dma_50": 50, "dma_200": 200}
RETURN_WINDOWS = {"return_1d": 1, "return_1w": 5, "return_1m": 21, "return_3m": 63, "return_6m": 126, "return_1y": 252}


def _rule(name, status, value, threshold, detail):
    return {"rule": name, "status": status, "value": value, "threshold": threshold, "detail": detail}


def scan_technical_red_flags(metrics: dict) -> list:
    """Pure function, no I/O -- takes the already-fetched stock_computed_metrics
    doc. Returns a fixed-order rule table, same shape as
    stock_terminal_scoring.scan_red_flags."""
    flags = []
    m = metrics or {}

    dma50, dma200 = m.get("dma_50"), m.get("dma_200")
    if dma50 is None or dma200 is None:
        flags.append(_rule("Trend Structure", "NA", None, f"50-DMA > {DEATH_CROSS_MARGIN_PCT}% below 200-DMA", "Not enough price history to compute both moving averages."))
    else:
        gap_pct = (dma50 - dma200) / dma200 * 100
        bad = gap_pct < -DEATH_CROSS_MARGIN_PCT
        flags.append(_rule("Trend Structure", "FAIL" if bad else "PASS", gap_pct, f"50-DMA > {DEATH_CROSS_MARGIN_PCT}% below 200-DMA",
                            "50-day average has crossed meaningfully below the 200-day average -- a death-cross structure." if bad else "50-day average is at or above the 200-day average."))

    pct_from_ath = m.get("pct_from_ath")
    if pct_from_ath is None:
        flags.append(_rule("Distance From Peak", "NA", None, f"< {DRAWDOWN_FAIL_PCT}%", "All-time-high reference unavailable."))
    else:
        status = "FAIL" if pct_from_ath <= DRAWDOWN_FAIL_PCT else "WARN" if pct_from_ath <= DRAWDOWN_WARN_PCT else "PASS"
        flags.append(_rule("Distance From Peak", status, pct_from_ath, f"< {DRAWDOWN_FAIL_PCT}%", f"Currently {abs(pct_from_ath):.1f}% below its all-time high."))

    r1w = m.get("return_1w")
    if r1w is None:
        flags.append(_rule("Short-Term Shock", "NA", None, f"< {WEEKLY_SHOCK_FAIL_PCT}% in a week", "1-week return unavailable."))
    else:
        status = "FAIL" if r1w <= WEEKLY_SHOCK_FAIL_PCT else "WARN" if r1w <= WEEKLY_SHOCK_WARN_PCT else "PASS"
        flags.append(_rule("Short-Term Shock", status, r1w, f"< {WEEKLY_SHOCK_FAIL_PCT}% in a week", f"1-week return is {r1w:.1f}%."))

    r1m, r3m, r6m = m.get("return_1m"), m.get("return_3m"), m.get("return_6m")
    if r1m is None or r3m is None or r6m is None:
        flags.append(_rule("Momentum Decay", "NA", None, "1m, 3m, and 6m returns all negative", "Not enough return-window history yet."))
    else:
        bad = r1m < 0 and r3m < 0 and r6m < 0
        flags.append(_rule("Momentum Decay", "FAIL" if bad else "PASS", {"return_1m": r1m, "return_3m": r3m, "return_6m": r6m}, "1m, 3m, and 6m returns all negative",
                            "Every trailing window (1m/3m/6m) is negative -- a sustained downtrend, not a single bad week." if bad else "Trailing returns are not uniformly negative."))

    return flags


def compute_metrics_from_bars(bars: list) -> dict:
    """Same derived-metrics shape stock_terminal_ingestion.compute_derived_metrics
    writes to stock_computed_metrics (dma_50/dma_200/pct_from_ath/return_*),
    computed on the fly instead of via a nightly batch job -- US bars come
    from yahoo_finance_client.equity_bars(), which already caches per
    ticker, so there's no separate US computed-metrics collection to keep
    in sync. `bars` must be sorted oldest -> newest with a `close` field
    (yahoo_finance_client's bar shape)."""
    if not bars or len(bars) < 2:
        return {}
    closes = [b["close"] for b in bars if b.get("close") is not None]
    if len(closes) < 2:
        return {}
    ath = max(closes)

    def _pct_return(days_back):
        if len(closes) <= days_back:
            return None
        prior = closes[-1 - days_back]
        return (closes[-1] / prior - 1) * 100 if prior else None

    metrics = {k: (sum(closes[-n:]) / len(closes[-n:])) for k, n in DMA_WINDOWS.items()}
    metrics.update({k: _pct_return(n) for k, n in RETURN_WINDOWS.items()})
    metrics["pct_from_ath"] = ((closes[-1] / ath) - 1) * 100 if ath else None
    return metrics


def scan_us_fundamental_red_flags(fundamentals: dict) -> list:
    """US-appropriate fundamental ruleset -- deliberately not the same six
    rules as scan_red_flags: promoter pledge/erosion have no US equivalent
    (US large-caps are widely held, not promoter-controlled), so this
    substitutes leverage, profitability, liquidity, short interest, and
    sell-side sentiment -- all sourced from us_stock_fundamentals.py's
    Yahoo quoteSummary fetch."""
    flags = []
    f = fundamentals or {}

    de = f.get("debt_to_equity")
    if de is None:
        flags.append(_rule("Leverage", "NA", None, f"> {US_LEVERAGE_FAIL_THRESHOLD}%", "Debt-to-equity unavailable."))
    else:
        flags.append(_rule("Leverage", "FAIL" if de > US_LEVERAGE_FAIL_THRESHOLD else "PASS", de, f"> {US_LEVERAGE_FAIL_THRESHOLD}%", f"Debt-to-equity is {de:.0f}%."))

    pm = f.get("profit_margin_pct")
    if pm is None:
        flags.append(_rule("Profitability", "NA", None, "< 0%", "Profit margin unavailable."))
    else:
        flags.append(_rule("Profitability", "FAIL" if pm < 0 else "PASS", pm, "< 0%", f"Profit margin is {pm:.1f}%." if pm >= 0 else f"Operating at a net loss ({pm:.1f}% margin)."))

    cr = f.get("current_ratio")
    if cr is None:
        flags.append(_rule("Liquidity", "NA", None, "< 1.0", "Current ratio unavailable."))
    else:
        bad = cr < 1
        flags.append(_rule("Liquidity", "WARN" if bad else "PASS", cr, "< 1.0", "Current liabilities exceed current assets." if bad else f"Current ratio is {cr:.2f}."))

    short_pct = f.get("short_pct_float")
    if short_pct is None:
        flags.append(_rule("Short Interest", "NA", None, f"> {US_SHORT_INTEREST_WARN_THRESHOLD}% of float", "Short-interest data unavailable."))
    else:
        bad = short_pct > US_SHORT_INTEREST_WARN_THRESHOLD
        flags.append(_rule("Short Interest", "WARN" if bad else "PASS", short_pct, f"> {US_SHORT_INTEREST_WARN_THRESHOLD}% of float",
                            f"{short_pct:.1f}% of float is sold short -- a crowded short position." if bad else f"{short_pct:.1f}% of float is sold short."))

    upside = f.get("target_upside_pct")
    if upside is None:
        flags.append(_rule("Analyst Outlook", "NA", None, "< 0% to consensus target", "Analyst target price unavailable."))
    else:
        bad = upside < 0
        flags.append(_rule("Analyst Outlook", "WARN" if bad else "PASS", upside, "< 0% to consensus target",
                            f"Consensus target price implies {upside:.1f}% downside from here." if bad else f"Consensus target price implies {upside:.1f}% upside from here."))

    return flags


def combine_verdict(technical_flags: list, fundamental_flags: list) -> str:
    """Danger if the scan turned up multiple hard fails, Caution for a single
    fail or a cluster of warns, Clear otherwise. Same FAIL/WARN vocabulary
    as both rule sets so this stays a plain tally, not a re-scoring."""
    all_flags = (technical_flags or []) + (fundamental_flags or [])
    fails = sum(1 for f in all_flags if f["status"] == "FAIL")
    warns = sum(1 for f in all_flags if f["status"] == "WARN")
    if fails >= 2:
        return "Danger"
    if fails == 1 or warns >= 2:
        return "Caution"
    return "Clear"
