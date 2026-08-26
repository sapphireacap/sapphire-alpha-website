"""Market Dashboard — pure shaping of NSE's allIndices payload into the
dashboard's card sections. No I/O (see market_dashboard_client.py for
that) — just picks which of the 139 index rows back which card and
reshapes them.
"""
from __future__ import annotations

# Matches the reference "Zone" dashboard's own top ticker row.
HEADLINE_INDICES = ["NIFTY 50", "NIFTY BANK", "NIFTY 500", "NIFTY MIDCAP 150", "NIFTY SMALLCAP 250"]

# Classic NSE sector indices — matches the reference dashboard's "Sector
# Performance" list (their own "Definedge Sectors" grouping is proprietary
# and excluded; this is the plain NSE sector index family only).
SECTOR_INDICES = [
    "NIFTY AUTO", "NIFTY FMCG", "NIFTY IT", "NIFTY MEDIA", "NIFTY METAL",
    "NIFTY PHARMA", "NIFTY PSU BANK", "NIFTY PRIVATE BANK", "NIFTY REALTY",
    "NIFTY HEALTHCARE INDEX", "NIFTY CONSUMER DURABLES", "NIFTY OIL & GAS",
]

# Matches the reference dashboard's "NSE Major Segment Performance" bars.
SEGMENT_INDICES = ["NIFTY TOTAL MARKET", "NIFTY 50", "NIFTY 500", "NIFTY 200", "NIFTY MIDSMALLCAP 400", "NIFTY MIDCAP 150"]

# This dashboard's display names follow NSE's `allIndices` spelling. Dhan's
# own scrip master carries the same indices under slightly different
# strings (confirmed live against the real master, 2026-08-26) -- this maps
# our name to Dhan's so the streaming layer can resolve a security id
# without the display name changing anywhere else in this file.
DHAN_INDEX_ALIAS = {
    "NIFTY HEALTHCARE INDEX": "NIFTY HEALTHCARE",
    "NIFTY OIL & GAS": "NIFTY OIL AND GAS",
    "NIFTY TOTAL MARKET": "NIFTY TOTAL MKT",
}

# "NIFTY CONSUMER DURABLES" has no equivalent in Dhan's master under any
# name tried (checked: NIFTY CONSUMPTION and NIFTY NEW CONSUMP are
# different indices) -- excluded here rather than guessed, so it just
# stays on the existing NSE poll like every index was before this file
# existed.
STREAMABLE_INDICES = sorted(
    (set(HEADLINE_INDICES) | set(SECTOR_INDICES) | set(SEGMENT_INDICES) | {"INDIA VIX"})
    - {"NIFTY CONSUMER DURABLES"}
)


def _pick(rows_by_name: dict, names: list) -> list:
    """Only the rows that actually resolved — never fabricates a missing
    index's numbers. Order follows `names`, not whatever order NSE
    returned them in."""
    out = []
    for name in names:
        row = rows_by_name.get(name)
        if row is not None:
            out.append(row)
    return out


def _shape_index_row(row: dict) -> dict:
    return {
        "index": row.get("index"),
        "last": row.get("last"),
        "change": row.get("variation"),
        "change_pct": row.get("percentChange"),
        "year_high": row.get("yearHigh"),
        "year_low": row.get("yearLow"),
        "advances": row.get("advances"),
        "declines": row.get("declines"),
        "unchanged": row.get("unchanged"),
    }


def shape_all_indices(payload: dict) -> dict:
    """{"headline", "sectors", "segments", "vix", "market_advances",
    "market_declines", "market_unchanged", "as_of"} from one raw
    allIndices response."""
    rows = payload.get("data") or []
    rows_by_name = {r.get("index"): r for r in rows if r.get("index")}

    vix_row = rows_by_name.get("INDIA VIX")

    return {
        "headline": [_shape_index_row(r) for r in _pick(rows_by_name, HEADLINE_INDICES)],
        "sectors": [_shape_index_row(r) for r in _pick(rows_by_name, SECTOR_INDICES)],
        "segments": [_shape_index_row(r) for r in _pick(rows_by_name, SEGMENT_INDICES)],
        "vix": {"last": vix_row.get("last"), "change_pct": vix_row.get("percentChange")} if vix_row else None,
        "market_advances": payload.get("advances"),
        "market_declines": payload.get("declines"),
        "market_unchanged": payload.get("unchanged"),
        "as_of": payload.get("timestamp"),
    }


def shape_fii_dii(rows: list) -> dict:
    """{"fii": {buy, sell, net, date}, "dii": {...}} — floats the string
    values NSE returns, keyed by category rather than left as a raw list
    so the frontend doesn't need to know NSE's exact category label
    spelling ("FII/FPI")."""
    out = {"fii": None, "dii": None}
    for row in rows:
        category = (row.get("category") or "").upper()
        shaped = {
            "buy": float(row["buyValue"]) if row.get("buyValue") not in (None, "") else None,
            "sell": float(row["sellValue"]) if row.get("sellValue") not in (None, "") else None,
            "net": float(row["netValue"]) if row.get("netValue") not in (None, "") else None,
            "date": row.get("date"),
        }
        if "FII" in category or "FPI" in category:
            out["fii"] = shaped
        elif "DII" in category:
            out["dii"] = shaped
    return out
