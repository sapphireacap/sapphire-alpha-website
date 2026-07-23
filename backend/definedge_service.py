"""
Definedge Integrate — Sapphire Nifty Vector service.

Flow (per verified playbook):
  1. GET  signin.../login/{api_token}  (header api_secret)     -> otp_token  (OTP sent)
  2. POST signin.../token  {otp_token, otp}                    -> api_session_key
  3. GET  data.../sds/history/{seg}/{token}/minute/{from}/{to} (header Authorization: session)

Strategy (Sapphire Nifty Vector):
  - ATM = round(Nifty spot / 100) * 100
  - Legs = ATM+200 and ATM-200 straddles (CE close + PE close, per minute)
  - Point & Figure on each straddle: 0.5% box, 3-box (~1.5%) reversal
  - up (ATM+200) falling & down (ATM-200) rising  => Nifty BULLISH
    up rising & down falling                       => Nifty BEARISH
    else                                           => NEUTRAL

Live option data is only meaningful during market hours; the daily OTP must be
entered manually each morning (session key resets daily).
"""
import asyncio
import io
import math
import time
import zipfile
import logging
from datetime import datetime, timezone, timedelta

import httpx
import pandas as pd

logger = logging.getLogger(__name__)

AUTH_BASE = "https://signin.definedgesecurities.com/auth/realms/debroking/dsbpkc"
DATA_BASE = "https://data.definedgesecurities.com/sds"
QUOTES_BASE = "https://integrate.definedgesecurities.com/dart/v1"
MASTER_URL = "https://app.definedgesecurities.com/public/nsefno.zip"
NIFTY_SPOT_TOKEN = "26000"   # NIFTY 50 index token (NSE segment)

SPOT_CACHE_TTL = 2.0   # seconds — protects against many concurrent visitors each triggering their own upstream call

IST = timezone(timedelta(hours=5, minutes=30))

BOX_PCT = 0.005          # 0.5%
REVERSAL_BOXES = 3       # 3 boxes ~= 1.5%


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


def derive_bias(up_trend: str, down_trend: str) -> str:
    if up_trend == "Bearish" and down_trend == "Bullish":
        return "Bullish"
    if up_trend == "Bullish" and down_trend == "Bearish":
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
        self._spot_cache = None         # (monotonic_time, {"spot": "..."})

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

    def _resolve_tokens(self, df: pd.DataFrame, atm: int):
        """Locate NIFTY index-option tokens for ATM+/-200 at the chosen expiry.
        Master schema (nsefno): 0=SEG 1=TOKEN 2=SYMBOL 3=TRADINGSYM 4=INSTRUMENT
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
        expiry = self._pick_expiry(sorted(set(sub["_exp"].tolist())), today)
        if expiry is None:
            raise DefinedgeError("No valid NIFTY expiry found in master.")

        out = {"expiry": expiry.isoformat(), "up_strike": atm + 200, "down_strike": atm - 200, "legs": {}}
        for label, strike in (("up", atm + 200), ("down", atm - 200)):
            leg = {}
            for opt in ("CE", "PE"):
                row = sub[(sub["_strike"] == float(strike)) & (sub["_exp"] == expiry) & (sub[OPTTYPE].astype(str) == opt)]
                if row.empty:
                    raise DefinedgeError(f"Missing {strike} {opt} for expiry {expiry.isoformat()}.")
                leg[opt] = str(row.iloc[0][TOKEN])
            out["legs"][label] = leg
        return out

    # ---- historical ----------------------------------------------------
    async def _closes(self, segment: str, token: str):
        session = await self._session_key()
        now = datetime.now(IST)
        frm = now.replace(hour=9, minute=15, second=0).strftime("%d%m%Y%H%M")
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

    async def _spot(self):
        closes = await self._closes("NSE", NIFTY_SPOT_TOKEN)
        if not closes:
            raise DefinedgeError("No Nifty spot data returned.")
        return list(closes.values())[-1]

    async def spot_quote(self):
        """Lightweight, cached LTP lookup for the public fast-polling ticker —
        deliberately separate from _spot() (which pulls a full minute-bar
        history series for the P&F engine). Cached briefly so many concurrent
        site visitors polling at once don't each trigger their own upstream call."""
        now = time.monotonic()
        if self._spot_cache and now - self._spot_cache[0] < SPOT_CACHE_TTL:
            return self._spot_cache[1]

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

        result = {"spot": f"{float(ltp):,.2f}"}
        self._spot_cache = (now, result)
        return result

    async def _straddle_series(self, ce_token: str, pe_token: str):
        ce, pe = await asyncio.gather(
            self._closes("NFO", ce_token),
            self._closes("NFO", pe_token),
        )
        common = [t for t in ce if t in pe]
        return [ce[t] + pe[t] for t in sorted(common)]

    # ---- orchestration -------------------------------------------------
    async def compute_vector(self):
        # Fetch spot and the (possibly cold-cache) master file concurrently —
        # neither depends on the other, only token resolution below does.
        spot, df = await asyncio.gather(self._spot(), self._get_master())
        atm = int(round(spot / 100.0) * 100)
        tokens = self._resolve_tokens(df, atm)

        up, down = await asyncio.gather(
            self._straddle_series(tokens["legs"]["up"]["CE"], tokens["legs"]["up"]["PE"]),
            self._straddle_series(tokens["legs"]["down"]["CE"], tokens["legs"]["down"]["PE"]),
        )
        up_trend = pnf_trend(up)
        down_trend = pnf_trend(down)
        bias = derive_bias(up_trend, down_trend)

        now_ist = datetime.now(IST)
        signal = {
            "id": "current",
            "bias": bias,
            "spot": f"{spot:,.0f}",
            "atm": str(atm),
            "up_strike": str(tokens["up_strike"]),
            "up_trend": up_trend,
            "down_strike": str(tokens["down_strike"]),
            "down_trend": down_trend,
            "note": f"Auto: +200 {up_trend.lower()}, -200 {down_trend.lower()} (expiry {tokens['expiry']}).",
            "source": "definedge",
            "box_size": "0.5%",
            "reversal": "3 box",
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "updated_label": now_ist.strftime("Today, %I:%M %p IST"),
        }
        await self.db.nifty_signal.update_one({"id": "current"}, {"$set": signal}, upsert=True)
        return signal
