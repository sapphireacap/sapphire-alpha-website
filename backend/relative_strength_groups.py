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

Each group carries a `source`: "NSE" (default, fetched via Definedge)
or "YAHOO" (fetched via yahoo_finance_client.py -- Definedge has no US
equity data at all, see pnf_routes.py's US Indices segment for the same
split). us-mega-cap's ten tickers were verified live against Yahoo's
chart endpoint (2026-08-05) the same way the NSE symbols were verified
against allmaster.zip -- real prices came back for every one.
"""
from __future__ import annotations

GROUPS = {
    "nifty-bank": {
        "label": "Nifty Bank",
        "source": "NSE",
        "symbols": [
            "HDFCBANK", "ICICIBANK", "SBIN", "KOTAKBANK", "AXISBANK",
            "INDUSINDBK", "BANKBARODA", "PNB", "AUBANK", "FEDERALBNK",
            "IDFCFIRSTB", "BANDHANBNK",
        ],
    },
    "nifty-it": {
        "label": "Nifty IT",
        "source": "NSE",
        "symbols": ["TCS", "INFY", "HCLTECH", "WIPRO", "TECHM", "PERSISTENT", "COFORGE", "MPHASIS"],
    },
    "nifty-auto": {
        "label": "Nifty Auto",
        "source": "NSE",
        "symbols": [
            "MARUTI", "M&M", "BAJAJ-AUTO", "EICHERMOT", "HEROMOTOCO",
            "TVSMOTOR", "ASHOKLEY", "BHARATFORG", "TMPV",
        ],
    },
    "nifty-pharma": {
        "label": "Nifty Pharma",
        "source": "NSE",
        "symbols": [
            "SUNPHARMA", "DRREDDY", "CIPLA", "DIVISLAB", "LUPIN",
            "AUROPHARMA", "TORNTPHARM", "ALKEM", "ZYDUSLIFE",
        ],
    },
    "nifty-fmcg": {
        "label": "Nifty FMCG",
        "source": "NSE",
        "symbols": [
            "HINDUNILVR", "ITC", "NESTLEIND", "BRITANNIA", "TATACONSUM",
            "DABUR", "GODREJCP", "MARICO", "COLPAL",
        ],
    },
    "nifty-metal": {
        "label": "Nifty Metal",
        "source": "NSE",
        "symbols": ["TATASTEEL", "JSWSTEEL", "HINDALCO", "VEDL", "JINDALSTEL", "SAIL", "NMDC", "NATIONALUM"],
    },
    "nifty-energy": {
        "label": "Nifty Energy",
        "source": "NSE",
        "symbols": ["RELIANCE", "ONGC", "NTPC", "POWERGRID", "COALINDIA", "BPCL", "IOC", "GAIL", "TATAPOWER"],
    },
    "us-mega-cap": {
        "label": "US Mega Cap",
        "source": "YAHOO",
        "symbols": ["AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA", "AVGO", "AMD", "NFLX"],
    },
    # GICS sector baskets for the US Markets section — same "hand-curated,
    # source: YAHOO" shape as us-mega-cap, tickers picked from the S&P 500
    # (us_stock_symbol_master, synced via us_stock_universe.py) as
    # well-known, liquid names per sector rather than every constituent,
    # matching the ~8-12-symbol size of the NSE sector groups above.
    "us-technology": {
        "label": "US Technology",
        "source": "YAHOO",
        "symbols": ["AAPL", "MSFT", "NVDA", "AVGO", "ORCL", "CRM", "ADBE", "AMD", "CSCO", "QCOM"],
    },
    "us-financials": {
        "label": "US Financials",
        "source": "YAHOO",
        "symbols": ["JPM", "BAC", "WFC", "GS", "MS", "SCHW", "BLK", "C", "AXP", "SPGI"],
    },
    "us-healthcare": {
        "label": "US Healthcare",
        "source": "YAHOO",
        "symbols": ["LLY", "UNH", "JNJ", "ABBV", "MRK", "TMO", "ABT", "PFE", "DHR", "AMGN"],
    },
    "us-energy": {
        "label": "US Energy",
        "source": "YAHOO",
        "symbols": ["XOM", "CVX", "COP", "EOG", "SLB", "WMB", "PSX", "MPC", "OKE", "KMI"],
    },
    "us-consumer": {
        "label": "US Consumer",
        "source": "YAHOO",
        "symbols": ["AMZN", "WMT", "HD", "MCD", "NKE", "SBUX", "TGT", "LOW", "COST", "PG"],
    },
    "us-industrials": {
        "label": "US Industrials",
        "source": "YAHOO",
        "symbols": ["GE", "CAT", "RTX", "HON", "UNP", "BA", "DE", "LMT", "UPS", "ADP"],
    },
}


def get_group(key: str) -> dict | None:
    return GROUPS.get(key)
