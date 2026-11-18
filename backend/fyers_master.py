"""FYERS option-contract list for the three index underlyings, turned into the layout the Index Vector
already reads.

Source: FYERS' public symbol file https://public.fyers.in/sym_details/NSE_FO.csv (no login, not
counted against the API budget). It is ~17 MB / 93,000 rows with NO header, so it is STREAMED line by
line and only the ~8,300 index-option rows are kept (never the whole file in memory; the backend has a
512 MB ceiling). The kept rows are cached in Mongo once per IST day (`fyers_symbol_master`), so a restart
does not re-download it.

Columns used (0-based, verified against the live file 2026-11-19):
  1 description   3 lot size   8 expiry (epoch seconds)   9 symbol ticker (e.g. NSE:NIFTY26NOV25250CE)
  13 underlying   15 strike    16 option type (CE / PE / XX for futures)

as_definedge_frame() mirrors the old Definedge master's column positions, so the unchanged
DefinedgeService._resolve_tokens() works: 0 SEG ("NFO"), 1 TOKEN (here the FYERS symbol),
2 SYMBOL (underlying), 4 INSTRUMENT ("OPTIDX"), 5 EXPIRY (ddmmyyyy), 7 LOT, 8 OPTIONTYPE, 9 STRIKE (x100).
"""
import csv
import logging
from datetime import datetime, timedelta, timezone

import httpx
import pandas as pd

logger = logging.getLogger(__name__)

IST = timezone(timedelta(hours=5, minutes=30))
MASTER_URL = "https://public.fyers.in/sym_details/NSE_FO.csv"
UNDERLYINGS = {"NIFTY", "BANKNIFTY", "FINNIFTY"}
COLLECTION = "fyers_symbol_master"


def parse_lines(lines) -> list:
    """[[underlying, expiry_iso, strike, "CE"/"PE", symbol, lot], ...] from raw CSV lines (streaming-safe)."""
    out = []
    for rec in csv.reader(lines):
        if len(rec) < 17 or rec[13] not in UNDERLYINGS or rec[16] not in ("CE", "PE"):
            continue
        try:
            expiry = datetime.fromtimestamp(int(rec[8]), IST).date().isoformat()
            out.append([rec[13], expiry, float(rec[15]), rec[16], rec[9], int(float(rec[3]))])
        except (ValueError, OverflowError):
            continue
    return out


async def fetch_rows() -> list:
    async with httpx.AsyncClient(timeout=180) as c:
        async with c.stream("GET", MASTER_URL) as r:
            if r.status_code != 200:
                raise RuntimeError(f"FYERS symbol file returned HTTP {r.status_code}")
            lines = []
            rows = []
            async for line in r.aiter_lines():
                lines.append(line)
                if len(lines) >= 5000:            # parse in slices: constant memory
                    rows.extend(parse_lines(lines))
                    lines = []
            rows.extend(parse_lines(lines))
    if not rows:
        raise RuntimeError("FYERS symbol file held no index options.")
    return rows


async def get_rows(db, today_iso: str = None, fetcher=fetch_rows) -> list:
    """Today's rows: from Mongo if already downloaded today, else downloaded and cached."""
    today_iso = today_iso or datetime.now(IST).date().isoformat()
    doc = await db[COLLECTION].find_one({"id": "nse_fo"}, {"_id": 0})
    if doc and doc.get("date") == today_iso and doc.get("rows"):
        return doc["rows"]
    rows = await fetcher()
    await db[COLLECTION].update_one({"id": "nse_fo"}, {"$set": {"id": "nse_fo", "date": today_iso, "rows": rows}}, upsert=True)
    logger.info("FYERS symbol list refreshed: %d index-option contracts", len(rows))
    return rows


def as_definedge_frame(rows: list) -> pd.DataFrame:
    data = {i: [] for i in range(15)}
    for und, expiry_iso, strike, opt, symbol, lot in rows:
        y, m, d = expiry_iso.split("-")
        values = ["NFO", symbol, und, symbol, "OPTIDX", f"{d}{m}{y}", "", str(lot), opt, str(int(round(strike * 100))),
                  "", "", "", "", ""]
        for i, v in enumerate(values):
            data[i].append(v)
    return pd.DataFrame(data, dtype=str)
