"""API for the Renko charting platform.

PAID-ACCESS GATED, same posture and same gate as pnf_routes.py: every
route here is behind Depends(get_current_pnf_subscriber) — P&F Studio's
paid tier covers Renko Studio too, one subscription for both charting
products (mirrors how both share the same underlying Definedge access).

Error text is sanitized through the same `_public_error` pattern as
pnf_routes.py — upstream data-provider errors must never name the
vendor in a response body.
"""
import logging
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

import alpaca_client as ac
import binance_client as bn
import renko_chart
import yahoo_finance_client as yf
from definedge_service import DefinedgeError
from exitline import list_expiries, list_strikes, list_symbols, resolve_instrument

logger = logging.getLogger(__name__)

VALID_SEGMENTS = ("NSE", "FUT", "OPT", "US", "COMMODITY", "CRYPTO")
# See pnf_routes.py's identical constant for the full reasoning — Yahoo's
# ceiling, not the "US" segment's; intraday now runs through
# alpaca_client.py instead (_chart_us_intraday below).
US_INTERVALS = ("daily", "weekly", "monthly")
MAX_SCAN_SYMBOLS = 40


def _public_error(e: DefinedgeError) -> str:
    msg = str(e)
    if "definedge" in msg.lower():
        return "Chart data is temporarily unavailable — please try again shortly."
    return msg


def create_renko_router(db, definedge, get_current_subscriber) -> APIRouter:
    router = APIRouter(prefix="/renko", tags=["renko"])

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

    # -- instrument pickers (identical shape to /pnf/instruments) ----------

    @router.get("/instruments")
    async def instruments(segment: str, query: str = "", symbol: Optional[str] = None,
                           expiry: Optional[str] = None,
                           user: dict = Depends(get_current_subscriber)):
        segment = _check_segment(segment)
        if segment == "US":
            q = (query or "").strip().upper()
            syms = [k for k in yf.US_INDEX_SYMBOLS
                    if q in k or q in yf.US_INDEX_SYMBOLS[k]["label"].upper()]
            return {"symbols": syms}
        if segment == "COMMODITY":
            q = (query or "").strip().upper()
            syms = [k for k in yf.COMMODITY_SYMBOLS
                    if q in k or q in yf.COMMODITY_SYMBOLS[k]["label"].upper()]
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

    # -- the chart -----------------------------------------------------------

    async def _chart_yahoo(symbol: str, interval: str, box_pct: Optional[float],
                            box_value: Optional[float], cfg, ma_period: int,
                            symbol_map: dict, selector_segment: str) -> dict:
        sym = symbol.strip().upper()
        if sym not in symbol_map:
            raise HTTPException(status_code=404, detail=f"No instrument found for {symbol}.")
        if interval not in US_INTERVALS:
            raise HTTPException(status_code=400,
                                 detail="This instrument is available at daily, weekly or monthly intervals only.")
        try:
            bars = await yf.daily_bars(db, sym, symbol_map=symbol_map)
            bars = renko_chart.resample_daily(bars, interval)
            payload = renko_chart.build_chart(
                bars, box_pct=box_pct, box_value=box_value, cfg=cfg, ma_period=ma_period,
            )
        except renko_chart.RenkoError as e:
            raise HTTPException(status_code=400, detail=str(e))
        except yf.YahooFinanceError as e:
            logger.warning("Yahoo Finance fetch failed for %s: %s", sym, e)
            raise HTTPException(status_code=502,
                                 detail="Chart data is temporarily unavailable — please try again shortly.")
        payload["params"]["interval"] = interval
        info = symbol_map[sym]
        payload["instrument"] = {
            "symbol": sym,
            "selector_segment": selector_segment,
            "tradingsymbol": info["label"],
        }
        return payload

    async def _chart_us_intraday(symbol: str, interval: str, box_pct: Optional[float],
                                  box_value: Optional[float], cfg, ma_period: int, days: int) -> dict:
        """US Indices, intraday only, via each index's tracking ETF —
        see pnf_routes.py's identical function and alpaca_client.py's
        module docstring for the full reasoning."""
        sym = symbol.strip().upper()
        proxy = ac.US_INDEX_PROXY.get(sym)
        if not proxy:
            raise HTTPException(status_code=404, detail=f"No instrument found for {symbol}.")
        if interval not in ac.TIMEFRAME_MAP:
            raise HTTPException(status_code=400,
                                 detail=f"interval must be one of {', '.join(US_INTERVALS)} (daily+) "
                                        f"or {', '.join(ac.TIMEFRAME_MAP)} (intraday minutes) for US Indices.")
        try:
            bars = await ac.intraday_bars(sym, interval, days=days)
            payload = renko_chart.build_chart(
                bars, box_pct=box_pct, box_value=box_value, cfg=cfg, ma_period=ma_period,
            )
        except renko_chart.RenkoError as e:
            raise HTTPException(status_code=400, detail=str(e))
        except ac.AlpacaError as e:
            logger.warning("Alpaca fetch failed for %s (%s): %s", sym, proxy["ticker"], e)
            raise HTTPException(status_code=502,
                                 detail="Live intraday data is temporarily unavailable — please try again shortly.")
        payload["params"]["interval"] = interval
        payload["instrument"] = {
            "symbol": sym,
            "selector_segment": "US",
            "tradingsymbol": proxy["label"],
        }
        return payload

    @router.get("/chart")
    async def chart(symbol: str, segment: str = "NSE", interval: str = "daily",
                     box_pct: Optional[float] = renko_chart.DEFAULT_BOX_PCT,
                     box_value: Optional[float] = None,
                     expiry: Optional[str] = None, strike: Optional[float] = None,
                     option_type: Optional[str] = None,
                     years: int = 10, days: int = 30, ma_period: int = 40,
                     one_back_max_boxes: int = 1, two_back_max_boxes: int = 2,
                     anchor_min_boxes: int = 8, weak_breakout_max_boxes: int = 2,
                     user: dict = Depends(get_current_subscriber)):
        """A full Renko chart: grid, swings, every detected pattern with
        its failure level, and indicators.

        box_pct is a PERCENT (0.25 means a 0.25% brick). Pass box_value
        instead for an absolute-brick chart; passing both is an error.
        Brick reversal distance is NOT a parameter — Renko is fixed at
        close-only, 2-box reversal (see renko_engine.py); brick size is
        the only construction dial callers can turn.
        """
        segment = _check_segment(segment)
        if box_value is not None:
            box_pct = None
        from renko_patterns import PatternConfig
        cfg = PatternConfig(
            one_back_max_boxes=one_back_max_boxes,
            two_back_max_boxes=two_back_max_boxes,
            anchor_min_boxes=anchor_min_boxes,
            weak_breakout_max_boxes=weak_breakout_max_boxes,
        )

        if segment == "US":
            if interval in US_INTERVALS:
                return await _chart_yahoo(symbol, interval, box_pct, box_value, cfg, ma_period,
                                           yf.US_INDEX_SYMBOLS, "US")
            return await _chart_us_intraday(symbol, interval, box_pct, box_value, cfg, ma_period, days)
        if segment == "COMMODITY":
            return await _chart_yahoo(symbol, interval, box_pct, box_value, cfg, ma_period,
                                       yf.COMMODITY_SYMBOLS, "COMMODITY")
        if segment == "CRYPTO":
            raise HTTPException(status_code=400,
                                 detail="Crypto charts are built from client-fetched bars — use POST /renko/chart/crypto.")

        found = await _resolve(segment, symbol, expiry, strike, option_type)
        try:
            payload = await renko_chart.chart_for_instrument(
                definedge, found["segment"], found["token"], interval,
                box_pct=box_pct, box_value=box_value, cfg=cfg, ma_period=ma_period,
                years=years, days=days,
            )
        except renko_chart.RenkoError as e:
            raise HTTPException(status_code=400, detail=str(e))
        except DefinedgeError as e:
            raise HTTPException(status_code=502, detail=_public_error(e))
        payload["instrument"] = {
            "symbol": symbol.upper(),
            "selector_segment": segment,
            "tradingsymbol": found["tradingsymbol"],
        }
        return payload

    # -- crypto (bars fetched client-side, same reason as pnf_routes.py) ---

    class CryptoBar(BaseModel):
        date: Optional[str] = None
        ts: Optional[str] = None
        open: float
        high: float
        low: float
        close: float

    class CryptoChartRequest(BaseModel):
        symbol: str
        bars: List[CryptoBar]

    @router.post("/chart/crypto")
    async def chart_crypto(req: CryptoChartRequest, interval: str = "daily",
                            box_pct: Optional[float] = renko_chart.DEFAULT_BOX_PCT,
                            box_value: Optional[float] = None, ma_period: int = 40,
                            user: dict = Depends(get_current_subscriber)):
        sym = req.symbol.strip().upper()
        if sym not in bn.CRYPTO_SYMBOLS:
            raise HTTPException(status_code=404, detail=f"No instrument found for {req.symbol}.")
        if not req.bars:
            raise HTTPException(status_code=400, detail="No bars provided.")
        if len(req.bars) > bn.MAX_BARS:
            raise HTTPException(status_code=400, detail=f"Too many bars (max {bn.MAX_BARS}).")
        if box_value is not None:
            box_pct = None
        bars = [b.model_dump(exclude_none=True) for b in req.bars]
        try:
            payload = renko_chart.build_chart(bars, box_pct=box_pct, box_value=box_value, ma_period=ma_period)
        except renko_chart.RenkoError as e:
            raise HTTPException(status_code=400, detail=str(e))
        payload["params"]["interval"] = interval
        payload["instrument"] = {
            "symbol": sym,
            "selector_segment": "CRYPTO",
            "tradingsymbol": f"{bn.CRYPTO_SYMBOLS[sym]} ({sym})",
        }
        return payload

    # -- scanner -------------------------------------------------------------

    @router.get("/scan")
    async def scan(symbols: str, segment: str = "NSE", interval: str = "daily",
                    box_pct: float = renko_chart.DEFAULT_BOX_PCT,
                    patterns: Optional[str] = None, bias: Optional[str] = None,
                    within_swings: int = 3, years: int = 5,
                    user: dict = Depends(get_current_subscriber)):
        """Runs the pattern library across a watchlist and returns symbols
        showing a live setup — same shape and same reasoning as /pnf/scan
        (errors reported per-symbol, never silently dropped)."""
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
                payload = await renko_chart.chart_for_instrument(
                    definedge, found["segment"], found["token"], interval,
                    box_pct=box_pct, years=years,
                )
            except (renko_chart.RenkoError, DefinedgeError) as e:
                errors.append({"symbol": name, "error": _public_error(e)
                               if isinstance(e, DefinedgeError) else str(e)})
                continue

            total = payload["meta"]["total_swings"]
            hits = [
                p for p in payload["patterns"]
                if p["active"]
                and p["index"] >= total - within_swings
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
                       "reversal_boxes": renko_chart.DEFAULT_REVERSAL,
                       "within_swings": within_swings},
            "scanned": len(names),
            "results": results,
            "errors": errors,
        }

    @router.get("/patterns")
    async def pattern_catalogue(user: dict = Depends(get_current_subscriber)):
        from renko_patterns import DETECTORS, MAJOR_PATTERNS
        return {
            "detectors": sorted(DETECTORS.keys()),
            "major": sorted(MAJOR_PATTERNS),
        }

    # -- relative strength ----------------------------------------------------

    class RSMatrixRequest(BaseModel):
        symbols: List[str]
        closes_by_symbol: dict  # {symbol: {date: close}}
        box_pcts: List[float] = [0.25, 1.0, 3.0]

    @router.post("/relative-strength/matrix")
    async def relative_strength_matrix(req: RSMatrixRequest,
                                        user: dict = Depends(get_current_subscriber)):
        """Ch.9 Renko Relative Strength Matrix — bars are supplied by the
        caller (already-fetched closes per symbol), same reasoning as the
        crypto chart route: this is a pure computation over data the
        client already has, not another Definedge fetch."""
        from renko_relative_strength import compute_ranking
        if not req.symbols or not req.box_pcts:
            raise HTTPException(status_code=400, detail="Provide symbols and at least one box_pct.")
        missing = [s for s in req.symbols if s not in req.closes_by_symbol]
        if missing:
            raise HTTPException(status_code=400, detail=f"Missing closes for: {', '.join(missing)}")
        return compute_ranking(req.symbols, req.closes_by_symbol, req.box_pcts)

    return router
