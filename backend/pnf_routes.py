"""API for the Point & Figure charting platform.

PAID-ACCESS GATED. Every route here is behind Depends(get_current_pnf_subscriber)
(server.py) -- any authenticated user with an active pnf_access_until, or an
admin. Was admin-only until 2026-08-04; P&F Studio is now a paid product
(login + subscription, granted manually by an admin from /admin33 until a
payment processor is wired up), not an internal tool, but the same
"nothing here should be public by accident" posture applies as it did under
the old admin-only gate.

Error text is sanitized through _public_error for the same reason
exitline_routes does it — upstream data-provider errors name the vendor
and its session mechanics directly, and that attribution must never
reach a response body.
"""
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException

import alpha_vantage_client as av
import binance_client as bn
import pnf_chart
from definedge_service import DefinedgeError
from exitline import list_expiries, list_strikes, list_symbols, resolve_instrument
from pnf_indicators import DEFAULT_XO_LOOKBACK

logger = logging.getLogger(__name__)

VALID_SEGMENTS = ("NSE", "FUT", "OPT", "US", "CRYPTO")
US_INTERVALS = ("daily", "weekly", "monthly")  # no real intraday index data on the free AV tier
MAX_SCAN_SYMBOLS = 40


def _public_error(e: DefinedgeError) -> str:
    msg = str(e)
    if "definedge" in msg.lower():
        return "Chart data is temporarily unavailable — please try again shortly."
    return msg


def create_pnf_router(db, definedge, get_current_subscriber) -> APIRouter:
    router = APIRouter(prefix="/pnf", tags=["pnf"])

    def _check_segment(segment: str) -> str:
        segment = segment.strip().upper()
        if segment not in VALID_SEGMENTS:
            raise HTTPException(status_code=400, detail=f"segment must be one of {', '.join(VALID_SEGMENTS)}")
        return segment

    async def _resolve(segment: str, symbol: str, expiry: Optional[str],
                       strike: Optional[float], option_type: Optional[str]) -> dict:
        master = await definedge._get_all_master()
        found = resolve_instrument(master, segment, symbol, expiry, strike, option_type)
        if not found:
            raise HTTPException(status_code=404, detail=f"No instrument found for {symbol}.")
        return found

    # -- instrument pickers ------------------------------------------------

    @router.get("/instruments")
    async def instruments(segment: str, query: str = "", symbol: Optional[str] = None,
                          expiry: Optional[str] = None,
                          user: dict = Depends(get_current_subscriber)):
        """Populates the scrip selector and, for derivatives, the
        expiry/strike lists — same shape as Exitline's picker so the
        frontend selector logic is identical."""
        segment = _check_segment(segment)
        if segment == "US":
            q = (query or "").strip().upper()
            syms = [k for k in av.US_INDEX_PROXIES
                    if q in k or q in av.US_INDEX_PROXIES[k]["label"].upper()]
            return {"symbols": syms}
        if segment == "CRYPTO":
            q = (query or "").strip().upper()
            syms = [k for k in bn.CRYPTO_SYMBOLS
                    if q in k or q in bn.CRYPTO_SYMBOLS[k].upper()]
            return {"symbols": syms}
        try:
            master = await definedge._get_all_master()
        except DefinedgeError as e:
            raise HTTPException(status_code=502, detail=_public_error(e))
        if symbol and expiry and segment == "OPT":
            return {"strikes": list_strikes(master, symbol, expiry)}
        if symbol and segment in ("FUT", "OPT"):
            return {"expiries": list_expiries(master, segment, symbol)}
        return {"symbols": list_symbols(master, segment, query)}

    # -- the chart ---------------------------------------------------------

    async def _chart_us(symbol: str, interval: str, box_pct: Optional[float],
                        box_value: Optional[float], cfg, xo_lookback: int,
                        ma_period: int) -> dict:
        """US index branch: same build_chart() as every other segment —
        only the bar-fetching differs (Alpha Vantage's cached ETF-proxy
        history instead of Definedge). No P&F construction rule changes."""
        sym = symbol.strip().upper()
        if sym not in av.US_INDEX_PROXIES:
            raise HTTPException(status_code=404, detail=f"No instrument found for {symbol}.")
        if interval not in US_INTERVALS:
            raise HTTPException(status_code=400,
                                detail="US indices are available at daily, weekly or monthly intervals only.")
        try:
            bars = await av.daily_bars(db, sym)
            bars = pnf_chart.resample_daily(bars, interval)
            payload = pnf_chart.build_chart(
                bars, box_pct=box_pct, box_value=box_value,
                reversal=pnf_chart.DEFAULT_REVERSAL, cfg=cfg,
                xo_lookback=xo_lookback, ma_period=ma_period,
            )
        except pnf_chart.PnfError as e:
            raise HTTPException(status_code=400, detail=str(e))
        except av.AlphaVantageError as e:
            logger.warning("Alpha Vantage fetch failed for %s: %s", sym, e)
            raise HTTPException(status_code=502,
                                detail="Chart data is temporarily unavailable — please try again shortly.")
        payload["params"]["interval"] = interval
        info = av.US_INDEX_PROXIES[sym]
        payload["instrument"] = {
            "symbol": sym,
            "selector_segment": "US",
            "tradingsymbol": f"{info['label']} (tracked via {info['proxy']})",
        }
        return payload

    async def _chart_crypto(symbol: str, interval: str, box_pct: Optional[float],
                            box_value: Optional[float], cfg, xo_lookback: int,
                            ma_period: int) -> dict:
        """Crypto branch: same build_chart() as every other segment — only
        the bar-fetching differs (Binance's public klines instead of
        Definedge). No P&F construction rule changes. Unlike the US branch,
        every interval the platform offers is real native exchange data
        here, intraday included."""
        sym = symbol.strip().upper()
        if sym not in bn.CRYPTO_SYMBOLS:
            raise HTTPException(status_code=404, detail=f"No instrument found for {symbol}.")
        try:
            raw_bars = await bn.bars(sym, interval)
            payload = pnf_chart.build_chart(
                raw_bars, box_pct=box_pct, box_value=box_value,
                reversal=pnf_chart.DEFAULT_REVERSAL, cfg=cfg,
                xo_lookback=xo_lookback, ma_period=ma_period,
            )
        except pnf_chart.PnfError as e:
            raise HTTPException(status_code=400, detail=str(e))
        except bn.BinanceError as e:
            logger.warning("Binance fetch failed for %s: %s", sym, e)
            raise HTTPException(status_code=502,
                                detail="Chart data is temporarily unavailable — please try again shortly.")
        payload["params"]["interval"] = interval
        payload["instrument"] = {
            "symbol": sym,
            "selector_segment": "CRYPTO",
            "tradingsymbol": f"{bn.CRYPTO_SYMBOLS[sym]} ({sym})",
        }
        return payload

    @router.get("/chart")
    async def chart(symbol: str, segment: str = "NSE", interval: str = "daily",
                    box_pct: Optional[float] = pnf_chart.DEFAULT_BOX_PCT,
                    box_value: Optional[float] = None,
                    expiry: Optional[str] = None, strike: Optional[float] = None,
                    option_type: Optional[str] = None,
                    years: int = 10, days: int = 30,
                    xo_lookback: int = DEFAULT_XO_LOOKBACK, ma_period: int = 20,
                    pole_min_boxes: int = 5, turtle_columns: int = 10,
                    anchor_min_boxes: int = 15, triangle_50_rule: bool = False,
                    user: dict = Depends(get_current_subscriber)):
        """A full P&F chart: grid, columns, every detected pattern with its
        failure level, indicators, 45-degree trend lines and counts.

        box_pct is a PERCENT (0.25 means a 0.25% box). Pass box_value
        instead for an absolute-box chart; passing both is an error.

        Reversal and plotting method are NOT parameters: this platform is
        fixed at close-only, 3-box reversal by standing instruction, so
        box size is the only construction dial callers can turn.
        """
        segment = _check_segment(segment)
        if box_value is not None:
            box_pct = None
        cfg = pnf_chart.pf.PatternConfig(
            pole_min_boxes=pole_min_boxes,
            turtle_columns=turtle_columns,
            anchor_min_boxes=anchor_min_boxes,
            triangle_50_rule=triangle_50_rule,
        )

        if segment == "US":
            return await _chart_us(symbol, interval, box_pct, box_value, cfg, xo_lookback, ma_period)
        if segment == "CRYPTO":
            return await _chart_crypto(symbol, interval, box_pct, box_value, cfg, xo_lookback, ma_period)

        found = await _resolve(segment, symbol, expiry, strike, option_type)
        try:
            payload = await pnf_chart.chart_for_instrument(
                definedge, found["segment"], found["token"], interval,
                box_pct=box_pct, box_value=box_value,
                reversal=pnf_chart.DEFAULT_REVERSAL,
                cfg=cfg, xo_lookback=xo_lookback, ma_period=ma_period,
                years=years, days=days,
            )
        except pnf_chart.PnfError as e:
            raise HTTPException(status_code=400, detail=str(e))
        except DefinedgeError as e:
            raise HTTPException(status_code=502, detail=_public_error(e))
        payload["instrument"] = {
            "symbol": symbol.upper(),
            "selector_segment": segment,
            "tradingsymbol": found["tradingsymbol"],
        }
        return payload

    # -- scanner -----------------------------------------------------------

    @router.get("/scan")
    async def scan(symbols: str, segment: str = "NSE", interval: str = "daily",
                   box_pct: float = pnf_chart.DEFAULT_BOX_PCT,
                   patterns: Optional[str] = None, bias: Optional[str] = None,
                   within_columns: int = 3, years: int = 5,
                   user: dict = Depends(get_current_subscriber)):
        """Run the pattern library across a list of symbols and return the
        ones showing a live setup.

        `symbols` is a comma-separated list (capped at MAX_SCAN_SYMBOLS) —
        each one costs an upstream history request, so this is deliberately
        a targeted scan of a watchlist rather than a whole-market sweep.
        `within_columns` limits results to patterns that completed in the
        last N columns, i.e. setups that are actually current.

        Results carry `errors` alongside `results`: a symbol whose history
        fails is reported as such, never silently dropped, so an empty
        scan can't be mistaken for "no setups".
        """
        segment = _check_segment(segment)
        wanted = {p.strip() for p in patterns.split(",")} if patterns else None
        names = [s.strip().upper() for s in symbols.split(",") if s.strip()][:MAX_SCAN_SYMBOLS]
        if not names:
            raise HTTPException(status_code=400, detail="Provide at least one symbol.")

        try:
            master = await definedge._get_all_master()
        except DefinedgeError as e:
            raise HTTPException(status_code=502, detail=_public_error(e))

        results, errors = [], []
        for name in names:
            found = resolve_instrument(master, segment, name)
            if not found:
                errors.append({"symbol": name, "error": "not found"})
                continue
            try:
                payload = await pnf_chart.chart_for_instrument(
                    definedge, found["segment"], found["token"], interval,
                    box_pct=box_pct, reversal=pnf_chart.DEFAULT_REVERSAL,
                    xo_lookback=DEFAULT_XO_LOOKBACK, years=years,
                )
            except (pnf_chart.PnfError, DefinedgeError) as e:
                errors.append({"symbol": name, "error": _public_error(e)
                               if isinstance(e, DefinedgeError) else str(e)})
                continue

            total = payload["meta"]["total_columns"]
            hits = [
                p for p in payload["patterns"]
                if p["active"]
                and p["index"] >= total - within_columns
                and (wanted is None or p["name"] in wanted)
                and (bias is None or p["bias"] == bias)
            ]
            if hits:
                results.append({
                    "symbol": name,
                    "tradingsymbol": found["tradingsymbol"],
                    "last_price": payload["meta"]["last_price"],
                    "summary": payload["summary"],
                    "indicators": {k: v for k, v in payload["indicators"].items()
                                   if not isinstance(v, list)},
                    "patterns": hits,
                })

        return {
            "params": {"segment": segment, "interval": interval, "box_pct": box_pct,
                       "reversal": pnf_chart.DEFAULT_REVERSAL,
                       "within_columns": within_columns},
            "scanned": len(names),
            "results": results,
            "errors": errors,
        }

    @router.get("/patterns")
    async def pattern_catalogue(user: dict = Depends(get_current_subscriber)):
        """The full library, for the UI's filter list — name, display
        label and whether the book classes it as a major formation."""
        from pnf_patterns import DETECTORS, MAJOR_PATTERNS
        return {
            "detectors": sorted(DETECTORS.keys()),
            "major": sorted(MAJOR_PATTERNS),
        }

    return router
