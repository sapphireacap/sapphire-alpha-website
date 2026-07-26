"""
Definedge Integrate — Sapphire Nifty Vector service.

Flow (per verified playbook):
  1. GET  signin.../login/{api_token}  (header api_secret)     -> otp_token  (OTP sent)
  2. POST signin.../token  {otp_token, otp}                    -> api_session_key
  3. GET  data.../sds/history/{seg}/{token}/minute/{from}/{to} (header Authorization: session)

Strategy (Sapphire Nifty Vector) — 6-chart confluence, confirmed 2026-07-27:
  - ATM = round(Nifty spot / 100) * 100
  - 4 straddle legs = ATM+200 and ATM-200 straddles (CE close + PE close,
    per minute), each run on BOTH the current WEEKLY expiry and the
    current MONTHLY expiry (see _pick_monthly_expiry for the "last week of
    the month" roll-forward rule that keeps the two timeframes on
    genuinely different contracts). P&F on each: 0.5% box, 3-box (~1.5%)
    reversal.
  - 2 more legs = the MONTHLY-expiry ATM strike's CE and PE, read
    INDIVIDUALLY (not summed into a straddle). P&F on each: 3% box, 3-box
    (~9%) reversal — confirmed against a real Definedge chart titled
    "(3% x 3)", 1-minute timeframe. Same ATM-selection rule as every other
    leg in this Vector.
  - BULLISH requires ALL SIX:
      +200 straddle falling (weekly AND monthly)
      -200 straddle rising  (weekly AND monthly)
      monthly ATM CE rising
      monthly ATM PE falling
  - BEARISH requires ALL SIX (mirror image):
      +200 straddle rising  (weekly AND monthly)
      -200 straddle falling (weekly AND monthly)
      monthly ATM CE falling
      monthly ATM PE rising
  - any other combination => NEUTRAL (no direction)

Live option data is only meaningful during market hours; the daily OTP must be
entered manually each morning (session key resets daily).
"""
import asyncio
import io
import math
import time
import uuid
import zipfile
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional

import httpx
import pandas as pd

logger = logging.getLogger(__name__)

AUTH_BASE = "https://signin.definedgesecurities.com/auth/realms/debroking/dsbpkc"
DATA_BASE = "https://data.definedgesecurities.com/sds"
QUOTES_BASE = "https://integrate.definedgesecurities.com/dart/v1"
MASTER_URL = "https://app.definedgesecurities.com/public/nsefno.zip"
ALL_MASTER_URL = "https://app.definedgesecurities.com/public/allmaster.zip"  # unified NSE/BSE/NFO/BFO/MCX/CDS master, used by Quant Lab's generic symbol lookup
NIFTY_SPOT_TOKEN = "26000"   # NIFTY 50 index token (NSE segment)
VIX_TOKEN = "26017"          # India VIX token (NSE segment) — lives in the nsecash
                              # master file, not the nsefno one the option legs use;
                              # verified live via the quotes endpoint during Phase 2 design.

SPOT_CACHE_TTL = 2.0   # seconds — protects against many concurrent visitors each triggering their own upstream call

IST = timezone(timedelta(hours=5, minutes=30))

BOX_PCT = 0.005          # 0.5% — the four ATM+/-200 straddle legs
REVERSAL_BOXES = 3       # 3 boxes ~= 1.5%

ATM_LEG_BOX_PCT = 0.03       # 3% — the two monthly-expiry ATM CE/PE legs (read individually, not a straddle)
ATM_LEG_REVERSAL_BOXES = 3   # 3 boxes ~= 9% — confirmed against a real Definedge chart titled "(3% x 3)"


# ---------------------------------------------------------------------------
# Point & Figure engine (pure, unit-testable) — percentage boxes via log grid
# ---------------------------------------------------------------------------
def pnf_trend(prices, box_pct: float = BOX_PCT, reversal_boxes: int = REVERSAL_BOXES) -> str:
    """Return 'Bullish' (last column is X/up), 'Bearish' (O/down) or 'Neutral'."""
    vals = [float(p) for p in prices if p is not None and float(p) > 0]
    if len(vals) < 5:
        return "Neutral"

    scale = math.log(1.0 + box_pct)
    level = lambda p: math.floor(math.log(p) / scale)

    direction = None          # 'up' | 'down'
    extreme = level(vals[0])

    for p in vals[1:]:
        lv = level(p)
        if direction is None:
            if lv >= extreme + 1:
                direction, extreme = "up", lv
            elif lv <= extreme - 1:
                direction, extreme = "down", lv
        elif direction == "up":
            if lv > extreme:
                extreme = lv
            elif lv <= extreme - reversal_boxes:
                direction, extreme = "down", lv
        else:  # down
            if lv < extreme:
                extreme = lv
            elif lv >= extreme + reversal_boxes:
                direction, extreme = "up", lv

    if direction == "up":
        return "Bullish"
    if direction == "down":
        return "Bearish"
    return "Neutral"


def derive_bias(weekly_up_trend: str, weekly_down_trend: str, monthly_up_trend: str, monthly_down_trend: str,
                 monthly_atm_ce_trend: str, monthly_atm_pe_trend: str) -> str:
    """6-chart confluence (see module docstring) — ALL SIX legs must agree
    before calling a direction. Any disagreement between the straddle
    timeframes, or between the ATM CE/PE pair, or a Neutral leg anywhere,
    falls through to Neutral."""
    if weekly_up_trend == "Bearish" and monthly_up_trend == "Bearish" \
            and weekly_down_trend == "Bullish" and monthly_down_trend == "Bullish" \
            and monthly_atm_ce_trend == "Bullish" and monthly_atm_pe_trend == "Bearish":
        return "Bullish"
    if weekly_up_trend == "Bullish" and monthly_up_trend == "Bullish" \
            and weekly_down_trend == "Bearish" and monthly_down_trend == "Bearish" \
            and monthly_atm_ce_trend == "Bearish" and monthly_atm_pe_trend == "Bullish":
        return "Bearish"
    return "Neutral"


class DefinedgeError(Exception):
    pass


class DefinedgeService:
    def __init__(self, db, api_token: str, api_secret: str):
        self.db = db
        self.api_token = api_token
        self.api_secret = api_secret
        self._otp_token = None
        self._master_cache = None       # (date_str, DataFrame)
        self._all_master_cache = None   # (date_str, DataFrame) — allmaster.zip, kept separate from _master_cache
        self._spot_cache = None         # (monotonic_time, {"spot": "..."})
        self._prev_close_cache = None   # (date_str, float)
        self._vix_cache = None          # (monotonic_time, float)

    # ---- auth ----------------------------------------------------------
    def configured(self) -> bool:
        return bool(self.api_token and self.api_secret)

    async def trigger_otp(self):
        if not self.configured():
            raise DefinedgeError("Definedge API credentials are not configured.")
        url = f"{AUTH_BASE}/login/{self.api_token}"
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.get(url, headers={"api_secret": self.api_secret})
        if r.status_code != 200:
            raise DefinedgeError(f"OTP init failed ({r.status_code}): {r.text[:200]}")
        data = r.json()
        self._otp_token = data.get("otp_token")
        return {"message": data.get("message", "OTP sent."), "otp_token": self._otp_token, "otp_token_present": bool(self._otp_token)}

    async def verify_otp(self, otp: str, otp_token: str = None):
        token = otp_token or self._otp_token
        if not token:
            raise DefinedgeError("No OTP session. Trigger OTP first.")
        url = f"{AUTH_BASE}/token"
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.post(url, json={"otp_token": token, "otp": otp})
        if r.status_code != 200:
            raise DefinedgeError(f"OTP verify failed ({r.status_code}): {r.text[:200]}")
        data = r.json()
        session_key = data.get("api_session_key") or data.get("access_token") or data.get("susertoken")
        if not session_key:
            raise DefinedgeError(f"No session key in response: {list(data.keys())}")
        await self.db.definedge_session.update_one(
            {"id": "current"},
            {"$set": {"id": "current", "api_session_key": session_key,
                      "updated_at": datetime.now(timezone.utc).isoformat()}},
            upsert=True,
        )
        return {"status": "connected"}

    async def _session_key(self):
        doc = await self.db.definedge_session.find_one({"id": "current"}, {"_id": 0})
        if not doc or not doc.get("api_session_key"):
            raise DefinedgeError("No active Definedge session. Please complete daily OTP login.")
        return doc["api_session_key"]

    async def status(self):
        doc = await self.db.definedge_session.find_one({"id": "current"}, {"_id": 0})
        return {
            "configured": self.configured(),
            "connected": bool(doc and doc.get("api_session_key")),
            "session_updated_at": doc.get("updated_at") if doc else None,
        }

    # ---- symbol master -------------------------------------------------
    async def _get_master(self) -> pd.DataFrame:
        today = datetime.now(IST).strftime("%Y-%m-%d")
        if self._master_cache and self._master_cache[0] == today:
            return self._master_cache[1]
        async with httpx.AsyncClient(timeout=60) as c:
            r = await c.get(MASTER_URL)
        if r.status_code != 200:
            raise DefinedgeError(f"Master download failed ({r.status_code}).")
        with zipfile.ZipFile(io.BytesIO(r.content)) as z:
            name = z.namelist()[0]
            with z.open(name) as f:
                df = pd.read_csv(f, header=None, dtype=str, low_memory=False)
        self._master_cache = (today, df)
        return df

    async def master_sample(self):
        """Diagnostic: first rows so the exact column layout can be confirmed live."""
        df = await self._get_master()
        return {"shape": list(df.shape), "head": df.head(4).fillna("").values.tolist()}

    async def _get_all_master(self) -> pd.DataFrame:
        """Unified NSE/BSE/NFO/BFO/MCX/CDS master (allmaster.zip). Same per-day
        caching pattern as _get_master(), kept as a separate cache so the Nifty
        Vector's existing option-token resolution stays untouched."""
        today = datetime.now(IST).strftime("%Y-%m-%d")
        if self._all_master_cache and self._all_master_cache[0] == today:
            return self._all_master_cache[1]
        async with httpx.AsyncClient(timeout=60) as c:
            r = await c.get(ALL_MASTER_URL)
        if r.status_code != 200:
            raise DefinedgeError(f"All-master download failed ({r.status_code}).")
        with zipfile.ZipFile(io.BytesIO(r.content)) as z:
            name = z.namelist()[0]
            with z.open(name) as f:
                df = pd.read_csv(f, header=None, dtype=str, low_memory=False)
        self._all_master_cache = (today, df)
        return df

    def resolve_symbol(self, df: pd.DataFrame, segment: str, symbol: str) -> Optional[dict]:
        """Resolve a (segment, symbol) pair to a tradeable token via allmaster.zip.
        Returns None (never raises) when nothing matches, so callers can turn
        that into a clean "no result found" response instead of a 500.
        Column layout matches nsefno's: 0=SEG 1=TOKEN 2=SYMBOL 3=TRADINGSYM
        4=INSTRUMENT 5=EXPIRY(ddmmyyyy). NSE prefers EQ/IDX instruments; BSE has
        no clean equity tag (trading-group codes instead) so any SYMBOL match
        within SEG=="BSE" is accepted. NFO/BFO resolve to the nearest-expiry
        futures contract only (FUTSTK/FUTIDX) — the input has no strike/type,
        so an options contract can't be identified unambiguously."""
        SEG, TOKEN, SYMBOL, INSTR, EXPIRY = 0, 1, 2, 4, 5
        symbol = symbol.strip().upper()
        segment = segment.strip().upper()

        sub = df[(df[SEG].astype(str) == segment) & (df[SYMBOL].astype(str).str.upper() == symbol)]
        if sub.empty:
            return None

        if segment == "NSE":
            eq = sub[sub[INSTR].astype(str).isin(["EQ", "IDX"])]
            row = eq.iloc[0] if not eq.empty else sub.iloc[0]
            return {"token": str(row[TOKEN]), "tradingsymbol": str(row[3])}

        if segment == "BSE":
            row = sub.iloc[0]
            return {"token": str(row[TOKEN]), "tradingsymbol": str(row[3])}

        if segment in ("NFO", "BFO"):
            fut = sub[sub[INSTR].astype(str).isin(["FUTSTK", "FUTIDX"])].copy()
            if fut.empty:
                return None
            fut["_exp"] = pd.to_datetime(fut[EXPIRY].astype(str), format="%d%m%Y", errors="coerce").dt.date
            fut = fut.dropna(subset=["_exp"])
            if fut.empty:
                return None
            today = datetime.now(IST).date()
            expiry = self._pick_expiry(sorted(set(fut["_exp"].tolist())), today)
            if expiry is None:
                return None
            row = fut[fut["_exp"] == expiry].iloc[0]
            return {"token": str(row[TOKEN]), "tradingsymbol": str(row[3]), "expiry": expiry.isoformat()}

        return None

    @staticmethod
    def _pick_expiry(expiries, today):
        """Nearest weekly expiry; on Monday(0)/Tuesday(1) roll to the NEXT expiry."""
        fut = sorted(e for e in expiries if e >= today)
        if not fut:
            return None
        idx = 0
        if today.weekday() in (0, 1) and len(fut) > 1:
            # if the nearest is this week's expiry, prefer next
            idx = 1 if (fut[0] - today).days <= 3 else 0
        return fut[idx]

    @staticmethod
    def _pick_monthly_expiry(expiries, today, avoid=None):
        """Nifty's monthly expiry = the last (maximum) listed expiry falling
        within a given calendar month — NSE only lists weekly-cadence OPTIDX
        contracts, the month's final one IS the monthly contract, no
        separate flag exists in the master to key off. Picks the CURRENT
        month's monthly expiry, rolling to next month's once today is past
        it (no expiries left this month).

        Confirmed rule: once we've entered the monthly contract's own
        expiry week, the monthly leg shifts to NEXT month's monthly — and
        that shift must trigger for the WHOLE week, not just the days
        weekly happens to still be pointing at it. `avoid` takes an
        iterable of expiries the monthly pick must not collide with; the
        caller passes BOTH:
          - the RAW nearest upcoming expiry (before _pick_expiry's Mon/Tue
            roll) — needed because on Monday/Tuesday OF the monthly's own
            expiry week, the weekly leg has already rolled PAST the
            monthly to next week's contract, so comparing only against the
            rolled weekly value would miss the collision entirely even
            though we're still sitting inside that same expiry week.
          - the resolved (possibly rolled) weekly expiry — needed because
            on Monday/Tuesday of the week TWO WEEKS before month-end, the
            roll can land weekly FORWARD onto the monthly contract itself.
        Confirmed against a real screenshot (Friday, no roll: weekly and
        monthly both landed on the same 28-Jul before the fix, correctly
        shifting monthly to 25-Aug) and against live master data for a
        Monday of the monthly's own expiry week (the case the raw-nearest
        check specifically exists for)."""
        fut = sorted(e for e in expiries if e >= today)
        if not fut:
            return None

        def last_in_month(year, month):
            same_month = [e for e in fut if e.year == year and e.month == month]
            return max(same_month) if same_month else None

        def next_month(year, month):
            return (year + 1, 1) if month == 12 else (year, month + 1)

        monthly = last_in_month(today.year, today.month)
        if monthly is None:
            monthly = last_in_month(*next_month(today.year, today.month))

        avoid_set = {e for e in (avoid or []) if e is not None}
        if monthly is not None and monthly in avoid_set:
            monthly = last_in_month(*next_month(monthly.year, monthly.month))

        return monthly

    def _resolve_tokens(self, df: pd.DataFrame, atm: int):
        """Locate NIFTY index-option tokens for ATM+/-200 at BOTH the current
        weekly and current monthly expiry (4 legs total). Master schema
        (nsefno): 0=SEG 1=TOKEN 2=SYMBOL 3=TRADINGSYM 4=INSTRUMENT
        5=EXPIRY(ddmmyyyy) 8=OPTIONTYPE(CE/PE) 9=STRIKE(x100)."""
        SEG, TOKEN, SYMBOL, INSTR, EXPIRY, OPTTYPE, STRIKE = 0, 1, 2, 4, 5, 8, 9
        sub = df[(df[SYMBOL].astype(str) == "NIFTY")
                 & (df[INSTR].astype(str) == "OPTIDX")
                 & (df[OPTTYPE].astype(str).isin(["CE", "PE"]))].copy()
        if sub.empty:
            raise DefinedgeError("No NIFTY index options (OPTIDX) found in master.")

        sub["_strike"] = pd.to_numeric(sub[STRIKE], errors="coerce") / 100.0
        sub["_exp"] = pd.to_datetime(sub[EXPIRY].astype(str), format="%d%m%Y", errors="coerce").dt.date
        sub = sub.dropna(subset=["_strike", "_exp"])

        today = datetime.now(IST).date()
        all_expiries = sorted(set(sub["_exp"].tolist()))
        future_expiries = sorted(e for e in all_expiries if e >= today)
        nearest_expiry = future_expiries[0] if future_expiries else None  # raw, BEFORE _pick_expiry's Mon/Tue roll
        weekly_expiry = self._pick_expiry(all_expiries, today)
        if weekly_expiry is None:
            raise DefinedgeError("No valid NIFTY weekly expiry found in master.")
        monthly_expiry = self._pick_monthly_expiry(all_expiries, today, avoid=(nearest_expiry, weekly_expiry))
        if monthly_expiry is None:
            raise DefinedgeError("No valid NIFTY monthly expiry found in master.")

        def resolve_leg(expiry, strike):
            leg = {}
            for opt in ("CE", "PE"):
                row = sub[(sub["_strike"] == float(strike)) & (sub["_exp"] == expiry) & (sub[OPTTYPE].astype(str) == opt)]
                if row.empty:
                    raise DefinedgeError(f"Missing {strike} {opt} for expiry {expiry.isoformat()}.")
                leg[opt] = str(row.iloc[0][TOKEN])
            return leg

        return {
            "up_strike": atm + 200,
            "down_strike": atm - 200,
            "weekly": {
                "expiry": weekly_expiry.isoformat(),
                "legs": {"up": resolve_leg(weekly_expiry, atm + 200), "down": resolve_leg(weekly_expiry, atm - 200)},
            },
            "monthly": {
                "expiry": monthly_expiry.isoformat(),
                "legs": {"up": resolve_leg(monthly_expiry, atm + 200), "down": resolve_leg(monthly_expiry, atm - 200)},
            },
            # ATM CE/PE read individually (not summed into a straddle) —
            # always the monthly expiry, same ATM-selection rule as every
            # other leg in this Vector.
            "monthly_atm": {
                "expiry": monthly_expiry.isoformat(),
                "leg": resolve_leg(monthly_expiry, atm),
            },
        }

    # ---- historical ----------------------------------------------------
    async def _closes(self, segment: str, token: str, frm: str = None, to: str = None):
        session = await self._session_key()
        now = datetime.now(IST)
        if frm is None:
            frm = now.replace(hour=9, minute=15, second=0).strftime("%d%m%Y%H%M")
        if to is None:
            to = now.strftime("%d%m%Y%H%M")
        url = f"{DATA_BASE}/history/{segment}/{token}/minute/{frm}/{to}"
        async with httpx.AsyncClient(timeout=45) as c:
            r = await c.get(url, headers={"Authorization": session})
        if r.status_code == 401:
            raise DefinedgeError("Definedge session expired. Please login again (OTP).")
        if r.status_code != 200:
            raise DefinedgeError(f"History failed ({r.status_code}) for {token}.")
        closes = {}
        for line in r.text.strip().splitlines():
            parts = line.split(",")
            if len(parts) < 5:
                continue
            try:
                closes[parts[0]] = float(parts[4])   # Dateandtime, O, H, L, Close, ...
            except ValueError:
                continue
        return closes

    async def daily_history(self, segment: str, token: str, years: int = 10):
        """Day-interval history for Quant Lab backtests — like _closes() but
        daily bars instead of minute. Requests a full `years`-back window
        unconditionally; Definedge simply returns whatever actually exists if
        the instrument is younger, which is what implements "since inception
        if shorter" with no extra branching."""
        session = await self._session_key()
        now = datetime.now(IST)
        frm = (now - timedelta(days=365 * years)).strftime("%d%m%Y0000")
        to = now.strftime("%d%m%Y%H%M")
        url = f"{DATA_BASE}/history/{segment}/{token}/day/{frm}/{to}"
        async with httpx.AsyncClient(timeout=45) as c:
            r = await c.get(url, headers={"Authorization": session})
        if r.status_code == 401:
            raise DefinedgeError("Definedge session expired. Please login again (OTP).")
        if r.status_code != 200:
            raise DefinedgeError(f"History failed ({r.status_code}) for {token}.")
        bars = []
        for line in r.text.strip().splitlines():
            parts = line.split(",")
            if len(parts) < 5:
                continue
            try:
                date_str = parts[0][:8]  # ddmmyyyy prefix, regardless of trailing time component
                bars.append({
                    "date": datetime.strptime(date_str, "%d%m%Y").date().isoformat(),
                    "open": float(parts[1]),
                    "high": float(parts[2]),
                    "low": float(parts[3]),
                    "close": float(parts[4]),
                })
            except (ValueError, IndexError):
                continue
        bars.sort(key=lambda b: b["date"])
        return bars

    async def _spot(self):
        closes = await self._closes("NSE", NIFTY_SPOT_TOKEN)
        if not closes:
            raise DefinedgeError("No Nifty spot data returned.")
        return list(closes.values())[-1]

    async def _prev_close(self):
        """Nifty's last close before today's session — cached per calendar day.
        Definedge's quotes endpoint doesn't return a previous-close field, so
        this pulls a wide history window ending just before today's open and
        takes the last bar. Naturally skips weekends/holidays since it just
        reads whatever data actually exists, rather than us guessing the
        prior trading day ourselves."""
        today_str = datetime.now(IST).strftime("%Y-%m-%d")
        if self._prev_close_cache and self._prev_close_cache[0] == today_str:
            return self._prev_close_cache[1]

        now = datetime.now(IST)
        frm = (now - timedelta(days=8)).strftime("%d%m%Y0000")
        to = now.replace(hour=9, minute=14, second=0).strftime("%d%m%Y%H%M")
        closes = await self._closes("NSE", NIFTY_SPOT_TOKEN, frm=frm, to=to)
        if not closes:
            raise DefinedgeError("No previous session close data.")
        value = list(closes.values())[-1]
        self._prev_close_cache = (today_str, value)
        return value

    async def spot_quote(self):
        """Lightweight, cached LTP lookup for the public fast-polling ticker —
        deliberately separate from _spot() (which pulls a full minute-bar
        history series for the P&F engine). Cached briefly so many concurrent
        site visitors polling at once don't each trigger their own upstream call."""
        now = time.monotonic()
        if self._spot_cache and now - self._spot_cache[0] < SPOT_CACHE_TTL:
            return self._spot_cache[1]

        prev_close = await self._prev_close()

        session = await self._session_key()
        url = f"{QUOTES_BASE}/quotes/NSE/{NIFTY_SPOT_TOKEN}"
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.get(url, headers={"Authorization": session})
        if r.status_code == 401:
            raise DefinedgeError("Definedge session expired. Please login again (OTP).")
        if r.status_code != 200:
            raise DefinedgeError(f"Quote failed ({r.status_code}).")
        ltp = r.json().get("ltp")
        if ltp is None:
            raise DefinedgeError("No LTP in quote response.")
        ltp = float(ltp)
        change = ltp - prev_close
        pct = (change / prev_close * 100) if prev_close else 0.0

        result = {
            "spot": f"{ltp:,.2f}",
            "change": f"{change:+,.2f}",
            "change_pct": f"{pct:+.2f}",
        }
        self._spot_cache = (now, result)
        return result

    async def vix_quote(self) -> Optional[float]:
        """Cached India VIX LTP — same caching rationale as spot_quote() (many
        concurrent journal trade-enrichment calls shouldn't each hit Definedge).
        Returns None rather than raising, since this only ever feeds a
        best-effort auto-fill field."""
        now = time.monotonic()
        if self._vix_cache and now - self._vix_cache[0] < SPOT_CACHE_TTL:
            return self._vix_cache[1]
        try:
            session = await self._session_key()
            url = f"{QUOTES_BASE}/quotes/NSE/{VIX_TOKEN}"
            async with httpx.AsyncClient(timeout=10) as c:
                r = await c.get(url, headers={"Authorization": session})
            if r.status_code != 200:
                return None
            ltp = r.json().get("ltp")
            if ltp is None:
                return None
            value = float(ltp)
        except Exception:  # noqa: BLE001 — best-effort field, never propagate
            return None
        self._vix_cache = (now, value)
        return value

    async def _straddle_series(self, ce_token: str, pe_token: str):
        """Per-minute straddle premium (CE close + PE close) for today's
        session, aligned on shared timestamps. Returns
        [{"t": "HH:MM", "v": premium}, ...] sorted chronologically — `v`
        alone feeds pnf_trend(); the full point list is what lets the
        frontend plot an actual chart instead of just the derived trend
        label (previously this returned a bare value list and the caller
        discarded everything except the derived trend — no chart data ever
        left this function)."""
        ce, pe = await asyncio.gather(
            self._closes("NFO", ce_token),
            self._closes("NFO", pe_token),
        )
        common = sorted(t for t in ce if t in pe)

        def label(raw_ts):
            try:
                return datetime.strptime(raw_ts, "%d%m%Y%H%M").strftime("%H:%M")
            except ValueError:
                return raw_ts

        return [{"t": label(t), "v": ce[t] + pe[t]} for t in common]

    async def _single_leg_series(self, token: str):
        """Per-minute close price for ONE option leg — not summed into a
        straddle. Used for the monthly ATM CE/PE confirmation legs, which
        are read independently rather than combined. Same point-list shape
        as _straddle_series so both feed pnf_trend()/charts identically."""
        closes = await self._closes("NFO", token)

        def label(raw_ts):
            try:
                return datetime.strptime(raw_ts, "%d%m%Y%H%M").strftime("%H:%M")
            except ValueError:
                return raw_ts

        return [{"t": label(t), "v": closes[t]} for t in sorted(closes)]

    # ---- orchestration -------------------------------------------------
    async def compute_vector(self):
        # Fetch spot and the (possibly cold-cache) master file concurrently —
        # neither depends on the other, only token resolution below does.
        spot, df = await asyncio.gather(self._spot(), self._get_master())
        atm = int(round(spot / 100.0) * 100)
        tokens = self._resolve_tokens(df, atm)

        weekly_up, weekly_down, monthly_up, monthly_down, monthly_atm_ce, monthly_atm_pe = await asyncio.gather(
            self._straddle_series(tokens["weekly"]["legs"]["up"]["CE"], tokens["weekly"]["legs"]["up"]["PE"]),
            self._straddle_series(tokens["weekly"]["legs"]["down"]["CE"], tokens["weekly"]["legs"]["down"]["PE"]),
            self._straddle_series(tokens["monthly"]["legs"]["up"]["CE"], tokens["monthly"]["legs"]["up"]["PE"]),
            self._straddle_series(tokens["monthly"]["legs"]["down"]["CE"], tokens["monthly"]["legs"]["down"]["PE"]),
            self._single_leg_series(tokens["monthly_atm"]["leg"]["CE"]),
            self._single_leg_series(tokens["monthly_atm"]["leg"]["PE"]),
        )
        weekly_up_trend = pnf_trend([p["v"] for p in weekly_up])
        weekly_down_trend = pnf_trend([p["v"] for p in weekly_down])
        monthly_up_trend = pnf_trend([p["v"] for p in monthly_up])
        monthly_down_trend = pnf_trend([p["v"] for p in monthly_down])
        monthly_atm_ce_trend = pnf_trend([p["v"] for p in monthly_atm_ce], box_pct=ATM_LEG_BOX_PCT, reversal_boxes=ATM_LEG_REVERSAL_BOXES)
        monthly_atm_pe_trend = pnf_trend([p["v"] for p in monthly_atm_pe], box_pct=ATM_LEG_BOX_PCT, reversal_boxes=ATM_LEG_REVERSAL_BOXES)
        bias = derive_bias(weekly_up_trend, weekly_down_trend, monthly_up_trend, monthly_down_trend,
                            monthly_atm_ce_trend, monthly_atm_pe_trend)

        now_ist = datetime.now(IST)
        signal = {
            "id": "current",
            "bias": bias,
            "spot": f"{spot:,.0f}",
            "atm": str(atm),
            "up_strike": str(tokens["up_strike"]),
            "down_strike": str(tokens["down_strike"]),
            "weekly_expiry": tokens["weekly"]["expiry"],
            "monthly_expiry": tokens["monthly"]["expiry"],
            "weekly_up_trend": weekly_up_trend,
            "weekly_down_trend": weekly_down_trend,
            "monthly_up_trend": monthly_up_trend,
            "monthly_down_trend": monthly_down_trend,
            "monthly_atm_ce_trend": monthly_atm_ce_trend,
            "monthly_atm_pe_trend": monthly_atm_pe_trend,
            "note": (
                f"Weekly: +200 {weekly_up_trend.lower()}, -200 {weekly_down_trend.lower()} (exp {tokens['weekly']['expiry']}). "
                f"Monthly: +200 {monthly_up_trend.lower()}, -200 {monthly_down_trend.lower()}, "
                f"ATM CE {monthly_atm_ce_trend.lower()}, ATM PE {monthly_atm_pe_trend.lower()} (exp {tokens['monthly']['expiry']})."
            ),
            "source": "definedge",
            "box_size": "0.5%",
            "reversal": "3 box",
            "atm_leg_box_size": "3%",
            "atm_leg_reversal": "3 box",
            "chart": {
                "weekly_up": weekly_up,
                "weekly_down": weekly_down,
                "monthly_up": monthly_up,
                "monthly_down": monthly_down,
                "monthly_atm_ce": monthly_atm_ce,
                "monthly_atm_pe": monthly_atm_pe,
            },
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "updated_label": now_ist.strftime("Today, %I:%M %p IST"),
        }
        await self.db.nifty_signal.update_one({"id": "current"}, {"$set": signal}, upsert=True)
        # nifty_signal only ever holds the current value (upserted in place
        # above) — the journal's straddle_regime_at_entry needs to ask "what
        # was the bias at time X", so keep an append-only history alongside it.
        # The per-minute chart payload is dropped from history (it's only
        # meaningful "live", and inserting it on every cron tick — as often
        # as once/minute during market hours — would otherwise blow up
        # nifty_signal_history's size for no benefit, since track-record
        # scoring only ever reads bias/spot/updated_at).
        history_doc = dict(signal)
        history_doc.pop("chart", None)
        history_doc["id"] = str(uuid.uuid4())
        await self.db.nifty_signal_history.insert_one(history_doc)
        return signal
