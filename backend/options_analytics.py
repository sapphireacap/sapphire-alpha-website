"""
Options Analytics — Max Pain, Put-Call Ratio, and IV Rank/Percentile.
Pure, unit-testable compute functions; no I/O. Fed by dhan_options_client's
already-live chain data (real OI and real IV per strike, not backed out
here — see that module's docstring for why Definedge can't supply this).

Sourced from "Everything about Trading Options" (Prashant Shah), read in
full earlier this session — three well-established, objective option-chain
concepts, none requiring anything beyond OI and IV already available:

  Max Pain: the strike at which option WRITERS collectively owe the least
  at expiry (equivalently, where option BUYERS collectively hold the least
  value) — computed by testing every listed strike as a hypothetical
  expiry price and summing each side's OI-weighted intrinsic payout.
  Price is often observed drifting toward this level as expiry nears,
  though it is a gravitational tendency, not a guarantee.

  Put-Call Ratio (PCR): total put OI divided by total call OI across the
  whole chain. A classic sentiment/contrarian gauge — extremes in either
  direction are read as exhaustion, the same "extreme zone" logic already
  used for breadth indicators elsewhere on this site.

  IV Rank / Percentile: where today's ATM implied volatility sits versus
  its own trailing history. Rank is today's value's position between the
  historical min and max (0-100 scale); percentile is the fraction of
  historical days below today's value. Needs a stored history to be
  meaningful — see options_analytics_routes.py's daily snapshot job.
"""
from __future__ import annotations

from typing import Optional


def max_pain(strikes: dict) -> Optional[dict]:
    """strikes: {strike: {"ce": {"oi":...}, "pe": {"oi":...}}, ...} (the
    exact shape dhan_options_client.chain() returns). Returns
    {"strike": float, "total_payout": float} for the strike with the
    lowest aggregate option-writer payout, or None if there's no usable OI
    at all (e.g. an illiquid or just-listed expiry)."""
    levels = sorted(strikes.keys())
    oi_pairs = []
    for k in levels:
        ce_oi = ((strikes[k].get("ce") or {}).get("oi")) or 0
        pe_oi = ((strikes[k].get("pe") or {}).get("oi")) or 0
        oi_pairs.append((k, ce_oi, pe_oi))
    if not levels or not any(ce or pe for _, ce, pe in oi_pairs):
        return None

    best_strike, best_payout = None, None
    for candidate in levels:
        payout = 0.0
        for k, ce_oi, pe_oi in oi_pairs:
            if candidate > k:
                payout += ce_oi * (candidate - k)  # calls struck below candidate are ITM
            elif candidate < k:
                payout += pe_oi * (k - candidate)  # puts struck above candidate are ITM
        if best_payout is None or payout < best_payout:
            best_strike, best_payout = candidate, payout
    return {"strike": best_strike, "total_payout": best_payout}


def put_call_ratio(strikes: dict, by: str = "oi") -> Optional[float]:
    """by: "oi" or "volume". None if the denominator (total calls) is zero
    — an all-zero or missing chain, not a real 0/0 ratio to report."""
    field = "oi" if by == "oi" else "volume"
    total_ce = sum(((s.get("ce") or {}).get(field)) or 0 for s in strikes.values())
    total_pe = sum(((s.get("pe") or {}).get(field)) or 0 for s in strikes.values())
    if not total_ce:
        return None
    return total_pe / total_ce


def atm_iv(strikes: dict, spot: float) -> Optional[float]:
    """Average of the nearest-strike CE and PE implied vol (both decimals,
    e.g. 0.146), whichever side(s) have a real reading — the standard
    "ATM IV" reference figure. None if neither side has an IV at the
    nearest strike (illiquid contract)."""
    if not strikes or spot is None:
        return None
    nearest = min(strikes.keys(), key=lambda k: abs(k - spot))
    side = strikes[nearest]
    ivs = [v for v in ((side.get("ce") or {}).get("iv"), (side.get("pe") or {}).get("iv")) if v]
    if not ivs:
        return None
    return sum(ivs) / len(ivs)


def iv_rank_and_percentile(current_iv: float, history: list) -> dict:
    """history: a list of past ATM IV decimals (not including today).
    Rank: today's position between the historical min/max, 0-100.
    Percentile: fraction of historical days strictly below today's value,
    0-100. Both None (not 0) when there's no usable history yet — a rank
    of 0 would misleadingly read as "at the low extreme" rather than
    "not enough data"."""
    if not history:
        return {"iv_rank": None, "iv_percentile": None, "history_days": 0}
    lo, hi = min(history), max(history)
    rank = 50.0 if hi == lo else (current_iv - lo) / (hi - lo) * 100.0
    below = sum(1 for h in history if h < current_iv)
    percentile = below / len(history) * 100.0
    return {
        "iv_rank": round(max(0.0, min(100.0, rank)), 1),
        "iv_percentile": round(percentile, 1),
        "history_days": len(history),
    }
