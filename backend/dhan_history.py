"""Dhan OHLC history, shaped exactly like Definedge's.

DhanBarSource is deliberately DUCK-TYPED to the two methods
pnf_chart.fetch_bars() calls on the Definedge service --
daily_history(segment, token, years) and minute_ohlc(segment, token, frm,
to). That means the P&F and Renko engines, the resampling, the live-bar
logic and every pattern/indicator run unchanged; only where the numbers
come from differs. Nothing downstream knows or cares.

Why move charting here at all, measured 2026-08-17 rather than assumed:

  1-min history depth   Definedge ~6 months, then a hard 400
                        Dhan      4+ years (verified back to 2022-08-18)
  daily depth           Dhan      20 years in ONE request (4,952 bars)
  5-min span/request    Dhan      90 days in one call (4,692 bars)

Charting is single-symbol and on-demand, so Dhan's ~1 req/s rate ceiling
-- the thing that rules it out for the 500-symbol universe walks Breadth
and Relative Strength do -- is irrelevant here. This is the one feature
where its depth advantage is decisive and its throughput limit costs
nothing.

THE KNOWN RISK, stated rather than buried: two vendors' closes are not
guaranteed identical (settlement close vs last tick, corporate-action
handling, session boundaries). P&F is a THRESHOLDING transform, so a
sub-rupee difference does not produce a sub-rupee difference in the
output -- it either changes nothing or flips a whole column. Bar
equivalence between the two vendors has NOT been verified. Charting was
moved here by explicit decision, accepting that, with discrepancies to be
watched for in practice.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone

import httpx

import dhan_auth

logger = logging.getLogger(__name__)

BASE_URL = "https://api.dhan.co/v2"
IST = timezone(timedelta(hours=5, minutes=30))

# Dhan's intraday endpoint takes an interval in MINUTES as a string. Its
# daily/weekly/monthly rollups are done locally by the existing
# pnf_chart.resample_daily, exactly as they were for Definedge.
SUPPORTED_MINUTES = {"1", "5", "15", "25", "60"}


class DhanHistoryError(Exception):
    """Upstream problems -- safe to show a caller."""


class DhanBarSource:
    """Stands in for the Definedge service wherever bars are fetched.

    `segment` here is Dhan's exchange segment (NSE_EQ / IDX_I / NSE_FNO)
    and `token` its security id -- both come from dhan_master.resolve().
    The parameter NAMES match Definedge's so the call sites don't change.
    """

    def __init__(self, db, instrument: str = "EQUITY"):
        self.db = db
        # Dhan requires the instrument kind on every charts request, and it
        # is not derivable from the security id alone.
        self.instrument = instrument

    async def _post(self, path: str, payload: dict) -> dict:
        token = await dhan_auth.get_access_token(self.db)
        import os
        headers = {
            "access-token": token,
            "client-id": os.environ.get("DHAN_CLIENT_ID", ""),
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        try:
            async with httpx.AsyncClient(timeout=60) as c:
                r = await c.post(f"{BASE_URL}/{path}", headers=headers, json=payload)
        except httpx.HTTPError as e:
            raise DhanHistoryError(f"Dhan request failed: {e}") from e

        if r.status_code == 401:
            headers["access-token"] = await dhan_auth.get_access_token(self.db, force=True)
            async with httpx.AsyncClient(timeout=60) as c:
                r = await c.post(f"{BASE_URL}/{path}", headers=headers, json=payload)
        if r.status_code == 429:
            raise DhanHistoryError("Chart data is rate-limited right now — please try again in a moment.")
        if r.status_code != 200:
            raise DhanHistoryError(f"Dhan {path} returned HTTP {r.status_code}: {r.text[:200]}")
        try:
            return r.json()
        except ValueError as e:
            raise DhanHistoryError(f"Dhan {path} returned non-JSON: {r.text[:150]}") from e

    @staticmethod
    def _rows(data: dict, intraday: bool) -> list:
        """Dhan returns parallel arrays, not row objects. Zipped into the
        same bar dicts Definedge produces, so downstream code is identical.

        `ts` mirrors Definedge's DDMMYYYYHHMM string because
        pnf_chart.aggregate_minutes parses exactly that format."""
        stamps = data.get("timestamp") or []
        o, h, l, c = (data.get(k) or [] for k in ("open", "high", "low", "close"))
        v = data.get("volume") or []
        out = []
        for i, t in enumerate(stamps):
            if i >= len(c) or c[i] is None:
                continue
            dt = datetime.fromtimestamp(t, tz=IST)
            bar = {
                "date": dt.date().isoformat(),
                "open": float(o[i]), "high": float(h[i]),
                "low": float(l[i]), "close": float(c[i]),
                "volume": float(v[i]) if i < len(v) and v[i] is not None else 0.0,
            }
            if intraday:
                bar["ts"] = dt.strftime("%d%m%Y%H%M")
            out.append(bar)
        return out

    async def daily_history(self, segment: str, token: str, years: int = 10) -> list:
        """Daily bars, oldest first — same shape and same argument order as
        DefinedgeService.daily_history. One request covers 20 years."""
        to = date.today()
        frm = to - timedelta(days=int(365.25 * max(1, years)) + 5)
        data = await self._post("charts/historical", {
            "securityId": str(token), "exchangeSegment": segment,
            "instrument": self.instrument,
            "fromDate": frm.isoformat(), "toDate": to.isoformat(),
        })
        return self._rows(data, intraday=False)

    async def minute_ohlc(self, segment: str, token: str, frm: str, to: str) -> list:
        """Minute bars for a DDMMYYYYHHMM window — Definedge's own argument
        format, kept so pnf_chart.fetch_bars needs no branch.

        Requests 1-minute bars and lets the existing aggregate_minutes()
        bucket them, rather than asking Dhan for a pre-aggregated interval:
        that keeps bucket alignment identical to the Definedge path, so a
        5-minute candle starts where it always did."""
        try:
            frm_dt = datetime.strptime(frm, "%d%m%Y%H%M")
            to_dt = datetime.strptime(to, "%d%m%Y%H%M")
        except ValueError as e:
            raise DhanHistoryError(f"Bad time window {frm}..{to}") from e

        data = await self._post("charts/intraday", {
            "securityId": str(token), "exchangeSegment": segment,
            "instrument": self.instrument, "interval": "1",
            "fromDate": frm_dt.date().isoformat(), "toDate": to_dt.date().isoformat(),
        })
        return self._rows(data, intraday=True)

    async def equity_quote(self, segment: str, token: str) -> float:
        """Live LTP. pnf_chart._with_live_bar calls this to append today's
        forming bar; it swallows failures, so raising here is safe."""
        data = await self._post("marketfeed/ltp", {segment: [int(token)]})
        block = ((data.get("data") or {}).get(segment) or {}).get(str(token)) or {}
        ltp = block.get("last_price")
        if ltp is None:
            raise DhanHistoryError(f"No LTP for {segment}/{token}.")
        return float(ltp)
