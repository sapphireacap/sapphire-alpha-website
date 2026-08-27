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
import asyncio
import logging
import time
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

import alpaca_client as ac
import dhan_history
import dhan_master
import binance_client as bn
import mt5_client as mt5c
import pnf_chart
import yahoo_finance_client as yf
from definedge_service import DefinedgeError
from exitline import list_expiries, list_strikes, list_symbols, resolve_instrument
from pnf_indicators import DEFAULT_XO_LOOKBACK

# Live-stream throttle: a tick fires on every real price change (both
# Dhan's and Definedge's feeds only send when LTP actually moves), which
# can be many times a second on a liquid instrument. build_chart() re-runs
# the full pattern/indicator/trend-line scan over the whole history on
# every call (see its own docstring) -- cheap once, wasteful dozens of
# times a second for no visible benefit. This caps actual recompute+send
# to once per window, coalescing any faster burst into the next window.
LIVE_RECOMPUTE_THROTTLE_SECONDS = 1.0

# Matches pnf_chart.aggregate_minutes's own bucketing (09:15 IST session
# anchor, ts strings already IST wall-clock with no tz suffix) -- the WS
# handler needs the exact same bucket math so a tick that crosses into a
# new minute rolls into a NEW bar instead of stretching the previous one.
_IST = timezone(timedelta(hours=5, minutes=30))


def _minute_bucket(now_ist: datetime, minutes: int) -> datetime:
    anchor = now_ist.replace(hour=9, minute=15, second=0, microsecond=0)
    if now_ist < anchor:
        anchor -= timedelta(days=1)
    offset = int((now_ist - anchor).total_seconds() // 60)
    return anchor + timedelta(minutes=(offset // minutes) * minutes)

logger = logging.getLogger(__name__)

VALID_SEGMENTS = ("NSE", "FUT", "OPT", "US", "COMMODITY", "CRYPTO")
# Yahoo's free chart endpoint has no real intraday index data, so daily/
# weekly/monthly is the ceiling for anything routed through _chart_yahoo.
# US Indices now has a second, intraday-only path via alpaca_client — see
# _chart_us_intraday below — so this no longer bounds the "US" segment as
# a whole, only what Yahoo itself can serve. COMMODITY (Gold) likewise got
# its own intraday path (mt5_client, _chart_commodity_intraday below), so
# this now bounds only the Yahoo-served daily/weekly/monthly charts.
US_INTERVALS = ("daily", "weekly", "monthly")
MAX_SCAN_SYMBOLS = 40


def _public_error(e: DefinedgeError) -> str:
    msg = str(e)
    if "definedge" in msg.lower():
        return "Chart data is temporarily unavailable — please try again shortly."
    return msg


def create_pnf_router(db, definedge, get_current_subscriber, get_current_subscriber_ws=None,
                      dhan_stream=None, definedge_stream=None) -> APIRouter:
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

    async def _resolve_bar_source(segment: str, symbol: str, expiry: Optional[str],
                                  strike: Optional[float], option_type: Optional[str]):
        """Dhan-first-then-Definedge resolution -- same logic as GET
        /chart's inline version above, factored out so the combo route
        below (which resolves TWO independent legs) doesn't need a third
        copy of it. Returns (source, found, bar_source)."""
        try:
            dhan_found = await dhan_master.resolve(segment, symbol, expiry, strike, option_type, db=db)
            if dhan_found:
                found = {"segment": dhan_found["exchange_segment"], "token": dhan_found["security_id"],
                          "tradingsymbol": dhan_found["tradingsymbol"]}
                return dhan_history.DhanBarSource(db, instrument=dhan_found["instrument"]), found, "dhan"
        except Exception as e:  # noqa: BLE001 — never fatal, Definedge still stands behind it
            logger.info("Dhan resolve failed for %s/%s (%s) — falling back to Definedge.", segment, symbol, e)
        found = await _resolve(segment, symbol, expiry, strike, option_type)
        return definedge, found, "definedge"

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
            syms = [k for k in yf.US_INDEX_SYMBOLS
                    if q in k or q in yf.US_INDEX_SYMBOLS[k]["label"].upper()]
            # Individual US equities (S&P 500 universe) alongside the two
            # index selectors above -- see us_stock_universe.py, the same
            # symbol master Peter Tingle's US toggle already uses.
            rows = await db.us_stock_symbol_master.find(
                {"$or": [{"symbol": {"$regex": q, "$options": "i"}},
                         {"company_name": {"$regex": q, "$options": "i"}}]},
                {"_id": 0, "symbol": 1},
            ).limit(20).to_list(20)
            syms += [r["symbol"] for r in rows if r["symbol"] not in syms]
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

    # -- the chart ---------------------------------------------------------

    async def _chart_yahoo(symbol: str, interval: str, box_pct: Optional[float],
                           box_value: Optional[float], cfg, xo_lookback: int,
                           ma_period: int, symbol_map: dict, selector_segment: str) -> dict:
        """Shared Yahoo-backed branch for both "US" (indices) and
        "COMMODITY" (currently just XAUUSD/GC=F) — same build_chart() as
        every other segment, only the bar-fetching differs (Yahoo
        Finance's free, keyless daily history — see
        yahoo_finance_client.py). No P&F construction rule changes."""
        sym = symbol.strip().upper()
        if sym not in symbol_map:
            raise HTTPException(status_code=404, detail=f"No instrument found for {symbol}.")
        if interval not in US_INTERVALS:
            raise HTTPException(status_code=400,
                                detail="This instrument is available at daily, weekly or monthly intervals only.")
        try:
            bars = await yf.daily_bars(db, sym, symbol_map=symbol_map)
            bars = pnf_chart.resample_daily(bars, interval)
            payload = pnf_chart.build_chart(
                bars, box_pct=box_pct, box_value=box_value,
                reversal=pnf_chart.DEFAULT_REVERSAL, cfg=cfg,
                xo_lookback=xo_lookback, ma_period=ma_period,
            )
        except pnf_chart.PnfError as e:
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
                                  box_value: Optional[float], cfg, xo_lookback: int,
                                  ma_period: int, days: int) -> dict:
        """US Indices, intraday only — real bars from each index's tracking
        ETF via Alpaca (see alpaca_client.py's module docstring for why
        this is a different underlying instrument from the daily/weekly/
        monthly chart of the same selector, and why that's disclosed
        rather than papered over)."""
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
            payload = pnf_chart.build_chart(
                bars, box_pct=box_pct, box_value=box_value,
                reversal=pnf_chart.DEFAULT_REVERSAL, cfg=cfg,
                xo_lookback=xo_lookback, ma_period=ma_period,
            )
        except pnf_chart.PnfError as e:
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

    async def _chart_commodity_intraday(symbol: str, interval: str, box_pct: Optional[float],
                                        box_value: Optional[float], cfg, xo_lookback: int,
                                        ma_period: int, days: int) -> dict:
        """Gold, intraday only — real spot XAUUSD bars pushed from a local
        MetaTrader 5 terminal (see mt5_client.py's module docstring). Note
        the instrument differs from this selector's own daily/weekly/monthly
        chart, which is still the COMEX futures proxy — surfaced in
        `tradingsymbol` so the UI can't present them as one series."""
        sym = symbol.strip().upper()
        if sym != mt5c.SYMBOL:
            raise HTTPException(status_code=404, detail=f"No instrument found for {symbol}.")
        if interval not in mt5c.TIMEFRAME_MAP:
            raise HTTPException(status_code=400,
                                detail=f"interval must be one of {', '.join(US_INTERVALS)} (daily+) "
                                       f"or {', '.join(mt5c.TIMEFRAME_MAP)} (intraday minutes) for Gold.")
        try:
            bars = await mt5c.intraday_bars(db, interval, days=days)
            payload = pnf_chart.build_chart(
                bars, box_pct=box_pct, box_value=box_value,
                reversal=pnf_chart.DEFAULT_REVERSAL, cfg=cfg,
                xo_lookback=xo_lookback, ma_period=ma_period,
            )
        except pnf_chart.PnfError as e:
            raise HTTPException(status_code=400, detail=str(e))
        except mt5c.Mt5DataError as e:
            logger.warning("MT5 intraday fetch failed for %s: %s", sym, e)
            raise HTTPException(status_code=502, detail=str(e))
        payload["params"]["interval"] = interval
        payload["instrument"] = {
            "symbol": sym,
            "selector_segment": "COMMODITY",
            "tradingsymbol": "Gold (Spot XAUUSD)",
        }
        return payload

    async def _chart_yahoo_equity(symbol: str, interval: str, box_pct: Optional[float],
                                  box_value: Optional[float], cfg, xo_lookback: int,
                                  ma_period: int) -> dict:
        """Individual US equities (S&P 500 universe, us_stock_symbol_master
        — same list Peter Tingle's US toggle syncs) — same Yahoo daily/
        weekly/monthly path as _chart_yahoo, but through
        yahoo_finance_client.equity_bars() (arbitrary ticker, no fixed
        map) since these are real securities, not the index/commodity
        proxies _chart_yahoo's symbol_map handles."""
        sym = symbol.strip().upper()
        master = await db.us_stock_symbol_master.find_one({"symbol": sym}, {"_id": 0})
        if not master:
            raise HTTPException(status_code=404, detail=f"No instrument found for {symbol}.")
        if interval not in US_INTERVALS:
            raise HTTPException(status_code=400,
                                detail="This instrument is available at daily, weekly or monthly intervals only.")
        try:
            bars = await yf.equity_bars(db, sym)
            bars = pnf_chart.resample_daily(bars, interval)
            payload = pnf_chart.build_chart(
                bars, box_pct=box_pct, box_value=box_value,
                reversal=pnf_chart.DEFAULT_REVERSAL, cfg=cfg,
                xo_lookback=xo_lookback, ma_period=ma_period,
            )
        except pnf_chart.PnfError as e:
            raise HTTPException(status_code=400, detail=str(e))
        except yf.YahooFinanceError as e:
            logger.warning("Yahoo Finance fetch failed for %s: %s", sym, e)
            raise HTTPException(status_code=502,
                                detail="Chart data is temporarily unavailable — please try again shortly.")
        payload["params"]["interval"] = interval
        payload["instrument"] = {
            "symbol": sym,
            "selector_segment": "US",
            "tradingsymbol": master.get("company_name") or sym,
        }
        return payload

    async def _chart_us_stock_intraday(symbol: str, interval: str, box_pct: Optional[float],
                                       box_value: Optional[float], cfg, xo_lookback: int,
                                       ma_period: int, days: int) -> dict:
        """Individual US equities, intraday — real bars straight from
        Alpaca for the actual ticker (no tracking-ETF proxy needed, unlike
        _chart_us_intraday's indices — see alpaca_client.py's module
        docstring)."""
        sym = symbol.strip().upper()
        master = await db.us_stock_symbol_master.find_one({"symbol": sym}, {"_id": 0})
        if not master:
            raise HTTPException(status_code=404, detail=f"No instrument found for {symbol}.")
        if interval not in ac.TIMEFRAME_MAP:
            raise HTTPException(status_code=400,
                                detail=f"interval must be one of {', '.join(US_INTERVALS)} (daily+) "
                                       f"or {', '.join(ac.TIMEFRAME_MAP)} (intraday minutes) for US Stocks.")
        try:
            bars = await ac.intraday_bars_for_ticker(sym, interval, days=days)
            payload = pnf_chart.build_chart(
                bars, box_pct=box_pct, box_value=box_value,
                reversal=pnf_chart.DEFAULT_REVERSAL, cfg=cfg,
                xo_lookback=xo_lookback, ma_period=ma_period,
            )
        except pnf_chart.PnfError as e:
            raise HTTPException(status_code=400, detail=str(e))
        except ac.AlpacaError as e:
            logger.warning("Alpaca fetch failed for %s: %s", sym, e)
            raise HTTPException(status_code=502,
                                detail="Live intraday data is temporarily unavailable — please try again shortly.")
        payload["params"]["interval"] = interval
        payload["instrument"] = {
            "symbol": sym,
            "selector_segment": "US",
            "tradingsymbol": master.get("company_name") or sym,
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
            is_index = symbol.strip().upper() in yf.US_INDEX_SYMBOLS
            if interval in US_INTERVALS:
                if is_index:
                    return await _chart_yahoo(symbol, interval, box_pct, box_value, cfg, xo_lookback, ma_period,
                                              yf.US_INDEX_SYMBOLS, "US")
                return await _chart_yahoo_equity(symbol, interval, box_pct, box_value, cfg, xo_lookback, ma_period)
            if is_index:
                return await _chart_us_intraday(symbol, interval, box_pct, box_value, cfg, xo_lookback, ma_period, days)
            return await _chart_us_stock_intraday(symbol, interval, box_pct, box_value, cfg, xo_lookback, ma_period, days)
        if segment == "COMMODITY":
            if interval in US_INTERVALS:
                return await _chart_yahoo(symbol, interval, box_pct, box_value, cfg, xo_lookback, ma_period,
                                          yf.COMMODITY_SYMBOLS, "COMMODITY")
            return await _chart_commodity_intraday(symbol, interval, box_pct, box_value, cfg,
                                                   xo_lookback, ma_period, days)
        if segment == "CRYPTO":
            raise HTTPException(status_code=400,
                                detail="Crypto charts are built from client-fetched bars — use POST /pnf/chart/crypto.")

        # India charting sources its BARS from Dhan, not Definedge. Measured
        # 2026-08-17: Dhan reaches 4+ years of 1-minute history and 20 years
        # of daily in a single request, where Definedge hard-400s past ~6
        # months of minute data. Charting is single-symbol and on-demand, so
        # Dhan's ~1 req/s ceiling -- which rules it out for the 500-symbol
        # universe walks Breadth and Relative Strength run -- costs nothing
        # here.
        #
        # DhanBarSource is duck-typed to the Definedge service's own
        # daily_history/minute_ohlc/equity_quote, so pnf_chart.fetch_bars
        # and every engine below it are untouched.
        #
        # Falls back to Definedge if Dhan cannot resolve or fetch, so a
        # chart never goes blank on a vendor hiccup. Which source served a
        # chart is reported on the payload as `bar_source`.
        found = None
        bar_source = "dhan"
        source = None
        try:
            dhan_found = await dhan_master.resolve(segment, symbol, expiry, strike, option_type, db=db)
            if dhan_found:
                found = {"segment": dhan_found["exchange_segment"], "token": dhan_found["security_id"],
                          "tradingsymbol": dhan_found["tradingsymbol"]}
                source = dhan_history.DhanBarSource(db, instrument=dhan_found["instrument"])
        except Exception as e:  # noqa: BLE001 — never fatal, Definedge still stands behind it
            logger.info("Dhan resolve failed for %s/%s (%s) — falling back to Definedge.", segment, symbol, e)

        if source is None:
            bar_source = "definedge"
            found = await _resolve(segment, symbol, expiry, strike, option_type)
            source = definedge

        try:
            payload = await pnf_chart.chart_for_instrument(
                source, found["segment"], found["token"], interval,
                box_pct=box_pct, box_value=box_value,
                reversal=pnf_chart.DEFAULT_REVERSAL,
                cfg=cfg, xo_lookback=xo_lookback, ma_period=ma_period,
                years=years, days=days,
            )
        except pnf_chart.PnfError as e:
            raise HTTPException(status_code=400, detail=str(e))
        except DefinedgeError as e:
            raise HTTPException(status_code=502, detail=_public_error(e))
        except dhan_history.DhanHistoryError as e:
            raise HTTPException(status_code=502, detail=str(e))
        payload["instrument"] = {
            "symbol": symbol.upper(),
            "selector_segment": segment,
            "tradingsymbol": found["tradingsymbol"],
        }
        payload["bar_source"] = bar_source
        return payload

    _COMBO_OPS = {"rs": "ratio", "straddle": "sum", "strangle": "sum"}
    _COMBO_SEGMENTS = ("NSE", "FUT", "OPT")

    @router.get("/chart/combo")
    async def chart_combo(op: str, interval: str = "daily",
                          box_pct: Optional[float] = pnf_chart.DEFAULT_BOX_PCT,
                          box_value: Optional[float] = None,
                          years: int = 10, days: int = 30,
                          leg_a_segment: str = "NSE", leg_a_symbol: str = "",
                          leg_a_expiry: Optional[str] = None, leg_a_strike: Optional[float] = None,
                          leg_a_option_type: Optional[str] = None,
                          leg_b_segment: str = "NSE", leg_b_symbol: str = "",
                          leg_b_expiry: Optional[str] = None, leg_b_strike: Optional[float] = None,
                          leg_b_option_type: Optional[str] = None,
                          user: dict = Depends(get_current_subscriber)):
        """RS / Straddle / Strangle charts: two independently resolved
        NSE/FUT/OPT instruments combined into one synthetic close-only
        price series (RS divides, Straddle/Strangle add), then plotted
        through the exact same box/pattern/indicator engine as any other
        P&F chart. Straddle and Strangle are the IDENTICAL combine
        (op="sum") -- same strike vs different is a labeling convention
        this route doesn't enforce, matching how Definedge's own terminal
        offers this feature."""
        op_key = _COMBO_OPS.get(op.strip().lower())
        if op_key is None:
            raise HTTPException(status_code=400, detail=f"op must be one of: {', '.join(_COMBO_OPS)}.")
        if not leg_a_symbol or not leg_b_symbol:
            raise HTTPException(status_code=400, detail="Both legs need a symbol.")
        for seg in (leg_a_segment, leg_b_segment):
            if seg.strip().upper() not in _COMBO_SEGMENTS:
                raise HTTPException(status_code=400,
                                    detail=f"Combo chart legs must be one of: {', '.join(_COMBO_SEGMENTS)}.")
        leg_a_segment = leg_a_segment.strip().upper()
        leg_b_segment = leg_b_segment.strip().upper()
        if box_value is not None:
            box_pct = None

        async def _leg(segment, symbol, expiry, strike, option_type):
            source, found, bar_source = await _resolve_bar_source(segment, symbol, expiry, strike, option_type)
            bars = await pnf_chart.fetch_bars(source, found["segment"], found["token"], interval, years=years, days=days)
            return bars, found, bar_source

        try:
            # Sequential, NOT asyncio.gather -- Dhan enforces roughly 1
            # request/second (see this file's own comment on GET /chart's
            # resolution above), and a daily+ interval's live-bar refresh
            # (pnf_chart._with_live_bar) fires a real LTP quote call per
            # leg. Firing both legs at once trips that ceiling: confirmed
            # live, the second leg's LTP call came back a real Dhan 429
            # while the first succeeded, turning into a 502 for the whole
            # chart. Two legs sequentially costs under a second either way.
            bars_a, found_a, source_a = await _leg(leg_a_segment, leg_a_symbol, leg_a_expiry, leg_a_strike, leg_a_option_type)
            bars_b, found_b, source_b = await _leg(leg_b_segment, leg_b_symbol, leg_b_expiry, leg_b_strike, leg_b_option_type)
        except DefinedgeError as e:
            raise HTTPException(status_code=502, detail=_public_error(e))
        except dhan_history.DhanHistoryError as e:
            raise HTTPException(status_code=502, detail=str(e))

        if not bars_a or not bars_b:
            raise HTTPException(status_code=404, detail="No price history available for one of the legs.")

        combined = pnf_chart.combine_bars(bars_a, bars_b, op_key)
        if not combined:
            raise HTTPException(status_code=400, detail="The two legs share no overlapping trading history.")

        try:
            chart = pnf_chart.build_chart(combined, box_pct=box_pct, box_value=box_value,
                                          reversal=pnf_chart.DEFAULT_REVERSAL)
        except pnf_chart.PnfError as e:
            raise HTTPException(status_code=400, detail=str(e))
        chart["params"]["interval"] = interval
        chart["bar_source"] = f"{source_a}+{source_b}"
        joiner = " / " if op_key == "ratio" else " + "
        chart["instrument"] = {
            "op": op.strip().lower(),
            # A plain "tradingsymbol" alongside the two legs so the
            # existing single-instrument stat-readout row (which reads
            # data.instrument.tradingsymbol unconditionally) needs no
            # combo-specific branching.
            "tradingsymbol": f"{found_a['tradingsymbol']}{joiner}{found_b['tradingsymbol']}",
            "leg_a": {"symbol": leg_a_symbol.upper(), "selector_segment": leg_a_segment,
                      "tradingsymbol": found_a["tradingsymbol"]},
            "leg_b": {"symbol": leg_b_symbol.upper(), "selector_segment": leg_b_segment,
                      "tradingsymbol": found_b["tradingsymbol"]},
        }
        return chart

    @router.websocket("/chart/stream")
    async def chart_stream(websocket: WebSocket, symbol: str, segment: str = "NSE",
                           interval: str = "daily",
                           box_pct: Optional[float] = pnf_chart.DEFAULT_BOX_PCT,
                           box_value: Optional[float] = None,
                           expiry: Optional[str] = None, strike: Optional[float] = None,
                           option_type: Optional[str] = None,
                           years: int = 10, days: int = 30, token: Optional[str] = None):
        """Live counterpart to GET /chart — same resolution (Dhan first,
        Definedge fallback), same box/pattern/indicator engine, just fed by
        a live tick instead of a poll. Sends one full chart payload on
        connect, then a full recompute (throttled, see
        LIVE_RECOMPUTE_THROTTLE_SECONDS) each time the underlying's LTP
        moves — see this module's docstring for why this stays a full
        recompute+send rather than a byte-minimal diff for v1.

        Auth: a browser's native WebSocket API can't set a custom
        Authorization header, so the JWT arrives as a query param instead
        (get_current_subscriber_ws) — same access rule as GET /chart's
        Depends(get_current_subscriber), just checked once at connect."""
        if get_current_subscriber_ws is None or dhan_stream is None or definedge_stream is None:
            await websocket.close(code=1011)
            return
        user = await get_current_subscriber_ws(token)
        if user is None:
            await websocket.close(code=1008)
            return

        segment = segment.strip().upper()
        if segment not in ("NSE", "FUT", "OPT"):
            # Every other segment (US/COMMODITY/CRYPTO) has its own
            # separate bar source (Yahoo/Alpaca/MT5/client-fetched) with
            # no live-tick integration in this pass — the frontend falls
            # back to its existing poll for those, same as if this
            # connection had simply failed to open.
            await websocket.close(code=1000)
            return
        if box_value is not None:
            box_pct = None
        cfg = pnf_chart.pf.PatternConfig()

        found = None
        bar_source = "dhan"
        source = None
        try:
            dhan_found = await dhan_master.resolve(segment, symbol, expiry, strike, option_type, db=db)
            if dhan_found:
                found = {"segment": dhan_found["exchange_segment"], "token": dhan_found["security_id"]}
                source = dhan_history.DhanBarSource(db, instrument=dhan_found["instrument"])
        except Exception as e:  # noqa: BLE001 — never fatal, Definedge still stands behind it
            logger.info("Dhan resolve failed for %s/%s (%s) — falling back to Definedge.", segment, symbol, e)
        if source is None:
            bar_source = "definedge"
            try:
                found = await _resolve(segment, symbol, expiry, strike, option_type)
            except HTTPException:
                await websocket.close(code=1000)
                return
            source = definedge

        try:
            bars = await pnf_chart.fetch_bars(source, found["segment"], found["token"], interval, years=years, days=days)
        except (pnf_chart.PnfError, DefinedgeError, dhan_history.DhanHistoryError):
            await websocket.close(code=1011)
            return
        if not bars:
            await websocket.close(code=1000)
            return

        await websocket.accept()

        state = {"bars": bars, "last_sent": 0.0, "flush_task": None}

        def _current_chart() -> dict:
            chart = pnf_chart.build_chart(state["bars"], box_pct=box_pct, box_value=box_value,
                                          reversal=pnf_chart.DEFAULT_REVERSAL, cfg=cfg)
            chart["params"]["interval"] = interval
            chart["bar_source"] = bar_source
            return chart

        await websocket.send_json({"type": "full", "chart": _current_chart()})

        async def _send_now() -> None:
            state["last_sent"] = time.monotonic()
            state["flush_task"] = None
            try:
                await websocket.send_json({"type": "full", "chart": _current_chart()})
            except Exception:  # noqa: BLE001 — a send on a closing socket is not worth logging loudly
                pass

        async def _on_tick(msg: dict) -> None:
            price = msg.get("ltp") if bar_source == "dhan" else None
            if bar_source == "definedge" and "lp" in msg:
                try:
                    price = float(msg["lp"])
                except (TypeError, ValueError):
                    price = None
            if price is None or price <= 0:
                return
            last = state["bars"][-1]
            # Minute charts: a tick belongs to whichever bucket "now" falls
            # in, and that bucket keeps advancing while the socket stays
            # open. Mutating `last` forever (the original version of this
            # handler) meant every tick after the first bucket kept
            # stretching that one bar's high/low indefinitely instead of
            # ever starting a new column -- a real bug, caught by a live
            # chart visibly diverging from the reference terminal's the
            # longer a connection stayed open. Daily+ charts have exactly
            # one bar for "today" regardless of tick count (see
            # pnf_chart._with_live_bar), so they always fall through to
            # the plain mutate-in-place branch below.
            if interval.isdigit() and "ts" in last:
                minutes = int(interval)
                bucket = _minute_bucket(datetime.now(_IST).replace(tzinfo=None), minutes)
                last_bucket = datetime.strptime(last["ts"], "%d%m%Y%H%M")
                if bucket > last_bucket:
                    last = {"ts": bucket.strftime("%d%m%Y%H%M"), "open": price, "high": price, "low": price, "close": price}
                    state["bars"].append(last)
            last["close"] = price
            last["high"] = max(last["high"], price)
            last["low"] = min(last["low"], price)

            elapsed = time.monotonic() - state["last_sent"]
            if elapsed >= LIVE_RECOMPUTE_THROTTLE_SECONDS:
                await _send_now()
                return
            # Throttled: a later tick within this window would otherwise
            # overwrite this price with no send ever happening for it if
            # ticks then stop arriving (a real, dropped-update bug in an
            # earlier version of this handler) -- schedule ONE delayed
            # flush for the remainder of the window instead, so the latest
            # price always gets sent even if this was the last tick for a
            # while. A second throttled tick before that flush fires just
            # mutates `state["bars"]` further; the flush always reads
            # whatever is current when it actually runs.
            if state["flush_task"] is None:
                remaining = LIVE_RECOMPUTE_THROTTLE_SECONDS - elapsed
                state["flush_task"] = asyncio.create_task(_delayed_flush(remaining))

        async def _delayed_flush(delay: float) -> None:
            await asyncio.sleep(max(delay, 0))
            await _send_now()

        def _tick_handler(msg: dict) -> None:
            asyncio.create_task(_on_tick(msg))

        if bar_source == "dhan":
            await dhan_stream.subscribe(found["segment"], found["token"], _tick_handler)
        else:
            await definedge_stream.subscribe(found["segment"], found["token"], _tick_handler)

        try:
            while True:
                await websocket.receive_text()  # never sent by this route's client; only used to detect disconnect
        except WebSocketDisconnect:
            pass
        finally:
            if state["flush_task"] is not None:
                state["flush_task"].cancel()
            if bar_source == "dhan":
                await dhan_stream.unsubscribe(found["segment"], found["token"], _tick_handler)
            else:
                await definedge_stream.unsubscribe(found["segment"], found["token"], _tick_handler)

    # -- crypto (bars fetched client-side, see module docstring in
    #    binance_client.py for why) -----------------------------------------

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
                           box_pct: Optional[float] = pnf_chart.DEFAULT_BOX_PCT,
                           box_value: Optional[float] = None,
                           xo_lookback: int = DEFAULT_XO_LOOKBACK, ma_period: int = 20,
                           pole_min_boxes: int = 5, turtle_columns: int = 10,
                           anchor_min_boxes: int = 15, triangle_50_rule: bool = False,
                           user: dict = Depends(get_current_subscriber)):
        """Same chart payload as GET /chart, built from OHLC bars the
        caller already fetched (from Binance, client-side) rather than
        this backend fetching them itself — Binance geo-blocks this
        backend's own server (see binance_client.py). Every other segment
        still uses the normal GET /chart flow; only Crypto works this way."""
        sym = req.symbol.strip().upper()
        if sym not in bn.CRYPTO_SYMBOLS:
            raise HTTPException(status_code=404, detail=f"No instrument found for {req.symbol}.")
        if not req.bars:
            raise HTTPException(status_code=400, detail="No bars provided.")
        if len(req.bars) > bn.MAX_BARS:
            raise HTTPException(status_code=400, detail=f"Too many bars (max {bn.MAX_BARS}).")
        if box_value is not None:
            box_pct = None
        cfg = pnf_chart.pf.PatternConfig(
            pole_min_boxes=pole_min_boxes,
            turtle_columns=turtle_columns,
            anchor_min_boxes=anchor_min_boxes,
            triangle_50_rule=triangle_50_rule,
        )
        bars = [b.model_dump(exclude_none=True) for b in req.bars]
        try:
            payload = pnf_chart.build_chart(
                bars, box_pct=box_pct, box_value=box_value,
                reversal=pnf_chart.DEFAULT_REVERSAL, cfg=cfg,
                xo_lookback=xo_lookback, ma_period=ma_period,
            )
        except pnf_chart.PnfError as e:
            raise HTTPException(status_code=400, detail=str(e))
        payload["params"]["interval"] = interval
        payload["instrument"] = {
            "symbol": sym,
            "selector_segment": "CRYPTO",
            "tradingsymbol": f"{bn.CRYPTO_SYMBOLS[sym]} ({sym})",
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
