"""Fixed comparison groups for the Relative Strength Matrix.

Manually curated NSE sector baskets. Definedge's own master data has no
sector/industry classification field (confirmed -- see
stock_terminal_ingestion.py's own note that this field is stored null,
no reliable source was ever found for it), so there's no live feed to
derive these from automatically; this is a hand-maintained registry,
same convention as CRYPTO_SYMBOLS/US_INDEX_SYMBOLS/MODULES elsewhere.

Every symbol below was verified live against allmaster.zip (2026-08-04)
via DefinedgeService.resolve_symbol before being added. Two corporate
actions surfaced during that check and are handled by omission/
substitution rather than a guess:
  - Tata Motors demerged its passenger-vehicle business in 2025; the
    original TATAMOTORS symbol no longer resolves at all. TMPV (Tata
    Motors Passenger Vehicles) stands in for it in the Auto group.
  - LTIMindtree does not appear anywhere in the current master data
    under any symbol or company-name variant tried (LTIM, MINDTREE,
    LTI, "L&T INFO...") -- left out of the IT group rather than guessed.
If any symbol here ever stops resolving (another corporate action,
delisting), fix it here rather than letting it silently drop out of its
group's matrix.
"""
from __future__ import annotations

GROUPS = {
    "nifty-bank": {
        "label": "Nifty Bank",
        "symbols": [
            "HDFCBANK", "ICICIBANK", "SBIN", "KOTAKBANK", "AXISBANK",
            "INDUSINDBK", "BANKBARODA", "PNB", "AUBANK", "FEDERALBNK",
            "IDFCFIRSTB", "BANDHANBNK",
        ],
    },
    "nifty-it": {
        "label": "Nifty IT",
        "symbols": ["TCS", "INFY", "HCLTECH", "WIPRO", "TECHM", "PERSISTENT", "COFORGE", "MPHASIS"],
    },
    "nifty-auto": {
        "label": "Nifty Auto",
        "symbols": [
            "MARUTI", "M&M", "BAJAJ-AUTO", "EICHERMOT", "HEROMOTOCO",
            "TVSMOTOR", "ASHOKLEY", "BHARATFORG", "TMPV",
        ],
    },
    "nifty-pharma": {
        "label": "Nifty Pharma",
        "symbols": [
            "SUNPHARMA", "DRREDDY", "CIPLA", "DIVISLAB", "LUPIN",
            "AUROPHARMA", "TORNTPHARM", "ALKEM", "ZYDUSLIFE",
        ],
    },
    "nifty-fmcg": {
        "label": "Nifty FMCG",
        "symbols": [
            "HINDUNILVR", "ITC", "NESTLEIND", "BRITANNIA", "TATACONSUM",
            "DABUR", "GODREJCP", "MARICO", "COLPAL",
        ],
    },
    "nifty-metal": {
        "label": "Nifty Metal",
        "symbols": ["TATASTEEL", "JSWSTEEL", "HINDALCO", "VEDL", "JINDALSTEL", "SAIL", "NMDC", "NATIONALUM"],
    },
    "nifty-energy": {
        "label": "Nifty Energy",
        "symbols": ["RELIANCE", "ONGC", "NTPC", "POWERGRID", "COALINDIA", "BPCL", "IOC", "GAIL", "TATAPOWER"],
    },
}


def get_group(key: str) -> dict | None:
    return GROUPS.get(key)
