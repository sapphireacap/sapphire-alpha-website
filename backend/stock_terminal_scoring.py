"""
Fracture Scan (red-flag scanner) and Clarity Score (scorecard) -- Phase 3.
Both deterministic, no LLM involvement anywhere in this module, matching
the spec's own design: "intentionally excluded from LLM inference... pure-
Python rules engine with no stochastic components, ensuring identical
outputs for identical inputs."

**Disclosed adaptation on Clarity Score's Valuation sub-score**: the spec
blends "inverse percentile of current P/E within its own 5-year
distribution" with "P/E vs. peer median." This codebase only ingests
CURRENT fundamentals (Phase 2), not a historical P/E time series, so the
5-year-percentile half has no real data behind it. Rather than fabricate
one, Valuation is scored 100% on the peer-comparison half (the half that
IS backed by real, ingested data) -- if historical fundamentals are ever
ingested, the blend can be restored.
"""
import statistics

PLEDGE_FAIL_THRESHOLD = 20
LEVERAGE_FAIL_THRESHOLD = 2
INTEREST_COVERAGE_WARN_THRESHOLD = 2
RECEIVABLES_WARN_MULTIPLIER = 1.5

SCORE_WEIGHTS = {"valuation": 0.25, "growth": 0.25, "financial_health": 0.20, "momentum": 0.15, "sector_tailwind": 0.15}
WARN_PENALTY, FAIL_PENALTY = 0.5, 1.0


def _rule(name, status, value, threshold, detail):
    return {"rule": name, "status": status, "value": value, "threshold": threshold, "detail": detail}


def scan_red_flags(fundamentals: dict, symbol_master: dict, shareholding_history: list) -> list:
    """Pure function, no I/O -- takes already-fetched documents. Returns the
    spec's 6-rule table in order. `shareholding_history` must be sorted
    oldest -> newest (same order the stock bundle route already returns
    it in)."""
    flags = []
    f = fundamentals or {}
    is_bfsi = "financial" in (symbol_master or {}).get("industry", "").lower()

    pledge = f.get("promoter_pledge_pct")
    flags.append(
        _rule("Promoter Pledge", "NA", pledge, f"> {PLEDGE_FAIL_THRESHOLD}%", "No pledge data disclosed for this symbol.")
        if pledge is None else
        _rule("Promoter Pledge", "FAIL" if pledge > PLEDGE_FAIL_THRESHOLD else "PASS", pledge, f"> {PLEDGE_FAIL_THRESHOLD}%", f"{pledge}% of promoter holding is pledged.")
    )

    ocf, pat = f.get("ocf_latest"), f.get("pat_latest")
    if ocf is None or pat is None:
        flags.append(_rule("Cash Flow Quality", "NA", None, "OCF < 0 and PAT > 0", "Cash flow or profit figures unavailable."))
    else:
        bad = ocf < 0 and pat > 0
        flags.append(_rule("Cash Flow Quality", "FAIL" if bad else "PASS", {"ocf": ocf, "pat": pat}, "OCF < 0 and PAT > 0",
                            "Reporting a profit while operating cash flow is negative." if bad else "Operating cash flow is consistent with reported profit."))

    dd_curr, dd_prev, rev_growth = f.get("debtor_days_curr"), f.get("debtor_days_prev"), f.get("revenue_growth_1y")
    if dd_curr is None or dd_prev is None or not dd_prev or rev_growth is None:
        flags.append(_rule("Receivables Growth", "NA", None, f"debtor-day growth > {RECEIVABLES_WARN_MULTIPLIER}x revenue growth", "Insufficient debtor-days or revenue-growth history."))
    else:
        dd_growth_pct = (dd_curr - dd_prev) / dd_prev * 100
        bad = dd_growth_pct > rev_growth * RECEIVABLES_WARN_MULTIPLIER
        flags.append(_rule("Receivables Growth", "WARN" if bad else "PASS", {"debtor_days_growth_pct": dd_growth_pct, "revenue_growth_pct": rev_growth},
                            f"> {RECEIVABLES_WARN_MULTIPLIER}x revenue growth",
                            "Receivables are growing much faster than revenue -- possible collection/channel-stuffing risk." if bad else "Receivables growth is in line with revenue growth."))

    de = f.get("debt_to_equity")
    if is_bfsi:
        flags.append(_rule("Leverage", "NA", de, f"> {LEVERAGE_FAIL_THRESHOLD}", "Leverage check doesn't apply to BFSI companies (high D/E is normal for their business model)."))
    elif de is None:
        flags.append(_rule("Leverage", "NA", None, f"> {LEVERAGE_FAIL_THRESHOLD}", "Debt-to-equity unavailable."))
    else:
        flags.append(_rule("Leverage", "FAIL" if de > LEVERAGE_FAIL_THRESHOLD else "PASS", de, f"> {LEVERAGE_FAIL_THRESHOLD}", f"Debt-to-equity is {de:.2f}."))

    ic = f.get("interest_coverage")
    if ic is None:
        flags.append(_rule("Interest Coverage", "NA", None, f"< {INTEREST_COVERAGE_WARN_THRESHOLD}", "Interest coverage unavailable."))
    else:
        bad = ic < INTEREST_COVERAGE_WARN_THRESHOLD
        flags.append(_rule("Interest Coverage", "WARN" if bad else "PASS", ic, f"< {INTEREST_COVERAGE_WARN_THRESHOLD}",
                            "Profit before interest & tax barely covers interest expense." if bad else "Comfortable interest coverage."))

    promoter_series = [q.get("promoter_pct") for q in (shareholding_history or []) if q.get("promoter_pct") is not None]
    if len(promoter_series) < 4:
        flags.append(_rule("Promoter Erosion", "NA", promoter_series, "declining >= 3 consecutive quarters", "Not enough shareholding history yet."))
    else:
        last4 = promoter_series[-4:]
        declining = all(last4[i] > last4[i + 1] for i in range(3))
        flags.append(_rule("Promoter Erosion", "WARN" if declining else "PASS", last4, "declining >= 3 consecutive quarters",
                            "Promoter holding has declined every quarter for the last 3 quarters." if declining else "No sustained promoter-holding decline."))

    return flags


def _clamp(v, lo=0, hi=10):
    return max(lo, min(hi, v))


def _scale(value, low, high, invert=False):
    """Linear-map value from [low, high] -> [0, 10], clamped. invert=True
    means lower raw values score higher (e.g. leverage)."""
    if value is None:
        return None
    span = high - low
    if span == 0:
        return None
    raw = (value - low) / span * 10
    return _clamp(10 - raw if invert else raw)


async def compute_scorecard(db, symbol: str, fundamentals: dict, computed_metrics: dict, symbol_master: dict, red_flags: list) -> dict:
    """Async because Valuation/Momentum/Sector Tailwind need real
    peer-/universe-level queries (peer median P/E, 6M-return percentile
    vs. the whole ingested universe) -- everything here reads
    already-ingested Mongo data, no LLM, no external calls."""
    f, cm = fundamentals or {}, computed_metrics or {}
    industry = (symbol_master or {}).get("industry")

    peers = []
    if industry:
        peers = await db.stock_symbol_master.find({"industry": industry, "symbol": {"$ne": symbol}}, {"_id": 0, "symbol": 1}).to_list(200)
    peer_symbols = [p["symbol"] for p in peers]

    # --- Valuation: peer P/E comparison only -- see module docstring for why
    valuation_sub = {"peer_pe_comparison": None}
    own_pe = f.get("pe_ratio")
    if own_pe and own_pe > 0 and peer_symbols:
        peer_fund = await db.stock_fundamentals.find({"symbol": {"$in": peer_symbols}, "pe_ratio": {"$gt": 0}}, {"_id": 0, "pe_ratio": 1}).to_list(200)
        peer_pes = [p["pe_ratio"] for p in peer_fund]
        if peer_pes:
            median_pe = statistics.median(peer_pes)
            ratio = own_pe / median_pe if median_pe else None
            valuation_sub["peer_pe_comparison"] = _scale(ratio, 0.5, 1.5, invert=True) if ratio is not None else None
            valuation_sub["peer_median_pe"] = median_pe
    valuation_score = valuation_sub["peer_pe_comparison"]

    # --- Growth: blended sales+profit CAGR, 0%->0, 30%+->10
    cagrs = [f.get(k) for k in ("sales_cagr_3y", "sales_cagr_5y", "profit_cagr_3y", "profit_cagr_5y")]
    cagrs = [c for c in cagrs if c is not None]
    growth_score = _clamp(statistics.mean(cagrs) / 30 * 10) if cagrs else None

    # --- Financial Health: ROE, D/E (inverted), interest coverage, OCF positivity
    fh_components = []
    if f.get("roe") is not None:
        fh_components.append(_scale(f["roe"], 0, 30))
    if f.get("debt_to_equity") is not None:
        fh_components.append(_scale(f["debt_to_equity"], 0, 2, invert=True))
    if f.get("interest_coverage") is not None:
        fh_components.append(_scale(f["interest_coverage"], 0, 10))
    if f.get("ocf_latest") is not None:
        fh_components.append(10 if f["ocf_latest"] > 0 else 0)
    fh_components = [c for c in fh_components if c is not None]
    financial_health_score = _clamp(statistics.mean(fh_components)) if fh_components else None

    # --- Momentum: price vs 200 DMA + 6M return percentile vs the whole ingested universe
    momentum_components = []
    latest_close_doc = await db.stock_prices_daily.find_one({"symbol": symbol}, sort=[("date", -1)], projection={"_id": 0, "close": 1})
    latest_close = latest_close_doc["close"] if latest_close_doc else None
    if latest_close and cm.get("dma_200"):
        momentum_components.append(_scale((latest_close / cm["dma_200"] - 1) * 100, -20, 20))
    r6m = cm.get("return_6m")
    if r6m is not None:
        universe_r6m = await db.stock_computed_metrics.find({"return_6m": {"$ne": None}}, {"_id": 0, "return_6m": 1}).to_list(1000)
        values = [u["return_6m"] for u in universe_r6m]
        if values:
            percentile = sum(1 for v in values if v < r6m) / len(values)
            momentum_components.append(_clamp(percentile * 10))
    momentum_score = _clamp(statistics.mean(momentum_components)) if momentum_components else None

    # --- Sector Tailwind: peer median 6M return, -10%->0, +10%->10
    sector_score = None
    if peer_symbols and r6m is not None:
        peer_metrics = await db.stock_computed_metrics.find({"symbol": {"$in": peer_symbols}, "return_6m": {"$ne": None}}, {"_id": 0, "return_6m": 1}).to_list(200)
        peer_returns = [p["return_6m"] for p in peer_metrics]
        if peer_returns:
            sector_score = _scale(statistics.median(peer_returns), -10, 10)

    sub_scores = {"valuation": valuation_score, "growth": growth_score, "financial_health": financial_health_score,
                  "momentum": momentum_score, "sector_tailwind": sector_score}

    weighted_sum = sum((sub_scores[k] or 0) * w for k, w in SCORE_WEIGHTS.items())
    penalty = sum(WARN_PENALTY if r["status"] == "WARN" else FAIL_PENALTY if r["status"] == "FAIL" else 0 for r in (red_flags or []))
    final_score = _clamp(weighted_sum - penalty)

    return {
        "final_score": final_score,
        "sub_scores": sub_scores,
        "weights": SCORE_WEIGHTS,
        "red_flag_penalty": penalty,
        "valuation_detail": valuation_sub,
    }
