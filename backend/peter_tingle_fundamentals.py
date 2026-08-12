"""
Peter Tingle -- fundamental snapshot ("Perks & Pitfalls"-style), India
only for now (see the module-level note in peter_tingle_routes.py on
why US fundamentals don't support this section yet).

DELIBERATELY NOT a scored "P&P Score" (0-100, bucketed Gamble/Middler/
Aces) or a binary Perk/Pitfall label on every ratio, unlike the
reference report this is modeled on. That report's own bullets make
clear its classification leans almost entirely on COMPARISONS this
codebase doesn't have real data for -- 5-year historical averages,
industry-average P/E, last year's same-quarter ROE/ROCE/NPM (see
stock_terminal_fundamentals.py: it scrapes CURRENT ratios and a few
real multi-year series, not a rolling average or an industry peer set).
Inventing a scoring formula or a threshold to call a bare "P/E is
17.68" good or bad would be presenting a fabricated methodology as if
it were Definedge's real one -- the same reasoning that kept an
unverified "counter trend ratio" out of pnf_observations.py.

What IS real and used here:
  - `key_ratios`: bare current-snapshot numbers (P/E, P/B, ROE, ROCE,
    OPM, NPM, Dividend Yield, Interest Coverage, D/E) -- shown
    unbucketed, because a number alone has no sign without a baseline.
  - `perks` / `pitfalls`: ONLY facts whose sign is meaningful without
    any external comparison -- sales/profit CAGR being positive or
    negative, FII/DII stake having genuinely risen or fallen quarter-
    over-quarter (real data: stock_shareholding is a per-quarter
    history, so this is an actual computed delta, not an assumption),
    and debt-to-equity being at or near zero.
"""

_KEY_RATIO_FIELDS = {
    "pe_ratio": "P/E Ratio", "pb_ratio": "P/B Ratio", "roe": "ROE", "roce": "ROCE",
    "opm": "Operating Profit Margin", "npm": "Net Profit Margin",
    "dividend_yield": "Dividend Yield", "interest_coverage": "Interest Coverage",
    "debt_to_equity": "Debt to Equity",
}

# Below this, D/E reads as "effectively no debt" -- matches
# stock_terminal_scoring.py's own LEVERAGE_FAIL_THRESHOLD=2 order of
# magnitude (an actual concern starts an order of magnitude higher),
# not an arbitrary new number.
LOW_DEBT_THRESHOLD = 0.1


def key_ratios(fundamentals: dict) -> dict:
    f = fundamentals or {}
    return {label: f.get(key) for key, label in _KEY_RATIO_FIELDS.items()}


def _cagr_line(value, label: str) -> tuple | None:
    if value is None:
        return None
    bucket = "perks" if value > 0 else "pitfalls" if value < 0 else None
    if bucket is None:
        return None
    return (bucket, f"{label} is {value:+.2f}%")


def fundamental_observations(fundamentals: dict, shareholding_history: list) -> dict:
    """shareholding_history: sorted oldest -> newest (same order the
    stock bundle route already returns it in -- see peter_tingle_routes.
    py's existing `shareholding` fetch, reused as-is)."""
    f = fundamentals or {}
    perks, pitfalls = [], []

    de = f.get("debt_to_equity")
    if de is not None and de <= LOW_DEBT_THRESHOLD:
        perks.append(f"D/E is {de:.2f} -- effectively debt-free.")

    for value, label in ((f.get("sales_cagr_3y"), "3-Year Sales CAGR"), (f.get("profit_cagr_3y"), "3-Year Profit CAGR"),
                          (f.get("revenue_growth_1y"), "YoY Sales Growth")):
        line = _cagr_line(value, label)
        if line:
            (perks if line[0] == "perks" else pitfalls).append(line[1])

    hist = shareholding_history or []
    if len(hist) >= 2:
        curr, prev = hist[-1], hist[-2]
        for key, label in (("fii_pct", "FII"), ("dii_pct", "DII")):
            c, p = curr.get(key), prev.get(key)
            if c is None or p is None:
                continue
            delta = c - p
            if abs(delta) < 0.01:
                continue
            text = f"{label} stake {'increased' if delta > 0 else 'decreased'} by {abs(delta):.2f}% this quarter (now {c:.2f}%)."
            (perks if delta > 0 else pitfalls).append(text)

    latest = hist[-1] if hist else {}
    total_holding = sum(v for v in (latest.get("promoter_pct"), latest.get("fii_pct"), latest.get("dii_pct")) if v is not None)
    if total_holding:
        perks.append(f"Promoters + FIIs + DIIs hold {total_holding:.2f}% of the company.")

    return {"key_ratios": key_ratios(f), "perks": perks, "pitfalls": pitfalls}
