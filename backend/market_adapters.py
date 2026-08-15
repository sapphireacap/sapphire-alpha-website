"""Market adapters — one uniform data interface per market segment.

The point of this module is that NO module's maths lives here. Every
calculation the Alpha Terminal runs already exists as a pure function with
no data-source coupling:

    exitline.compute_camarilla_levels / classify_and_suggest / build_session_ladder
    breadth_engine.direction_by_date / compute_breadth_series_from_directions
    relative_strength_matrix.compute_matrix
    options_trend_engine.leg_direction / three_pillar_verdict
    quant_lab._compute_risk_stats / _compute_momentum_stats / _compute_backtest
    peter_tingle.compute_metrics_from_bars / scan_technical_red_flags

Those functions take plain floats, lists and {date: close} dicts. So
"replicate the module for another market" does not mean reimplementing
anything -- it means handing the SAME function a different price series.
An adapter is exactly that: the thing that produces the series.

This is why the calculations cannot drift apart between markets. There is
one Camarilla implementation, one X-Percent implementation, one 12-1
momentum implementation, and every market tab calls it. A change to a
formula changes every market at once, by construction, because there is
only ever one copy. See multi_market_engine.py for the callers.

India is deliberately NOT adapted here. It already has a complete, live,
Definedge-backed implementation across its own dedicated route modules,
and rerouting a working production surface through a new abstraction
would be risk with no user-visible benefit. The India tab keeps its
existing code paths untouched.

Session model per market, which the Exitline ladder depends on:
    US     regular cash session, opens 09:30 America/New_York
    Forex  effectively 24x5; Yahoo's daily FX bar is a UTC calendar day,
           so the day boundary used here is 00:00 UTC to match the very
           bars the levels are computed from. Using a 17:00 New York FX
           rollover instead would put the ladder on a different day
           boundary than its own source data -- wrong, not merely
           different.
    Crypto 24x7, 00:00 UTC -- the boundary Binance/Coinbase/Kraken daily
           candles themselves use.
"""
from __future__ import annotations

from zoneinfo import ZoneInfo

import alpaca_client as ac
import alpaca_options_client as ao
import crypto_data_client as cd
import deribit_client as dc
import forex_client as fx
import yahoo_finance_client as yf


class AdapterError(Exception):
    """Any market-data failure, normalized so routes can return one shape."""


def _index_by_strike(contracts: list) -> dict:
    """{strike: {"call": leg, "put": leg}} -- strikes with only one side
    listed are kept, and the engine skips them when it needs a pair."""
    by_strike: dict = {}
    for c in contracts:
        by_strike.setdefault(c["strike"], {})[c["kind"]] = c
    return by_strike


class MarketAdapter:
    """Interface every market implements. Methods raise AdapterError (or
    return an empty/None result where documented) -- never fabricate."""

    market_id: str = ""
    label: str = ""
    # Minute-of-day the session opens in `tz`; 0 for a 24h market.
    session_open_minutes: int = 0
    tz = ZoneInfo("UTC")
    is_24h: bool = True
    supports_options: bool = False
    # Annualized risk-free rate used by the Sharpe Dashboard. The Sharpe
    # FORMULA is identical across markets; the rate is a market input, in
    # the same category as the instrument universe. pricing.RISK_FREE_RATE
    # (6.5%) is an approximate Indian short-term rate and is correct for
    # the India tab -- reusing it for a USD-denominated universe would
    # understate every US/FX/crypto Sharpe by roughly (6.5% - 4.3%) / vol,
    # which is a real error, not a rounding difference. USD markets
    # therefore use an approximate USD short-term rate, flagged here the
    # same way pricing.py flags its own: not live-fetched.
    risk_free_rate: float = 0.043  # approximate USD short-term rate; not live-fetched
    # Why a module is unavailable here, keyed by module slug. Surfaced to
    # the UI verbatim so a "Coming Soon" card can say what is actually
    # missing rather than implying the work merely isn't done yet.
    unavailable: dict = {}

    async def universe(self, db) -> list:
        raise NotImplementedError

    def groups(self) -> list:
        raise NotImplementedError

    async def group_members(self, db, group: str) -> list:
        raise NotImplementedError

    async def daily_bars(self, db, symbol: str) -> list:
        raise NotImplementedError

    async def daily_closes(self, db, symbol: str) -> dict:
        raise NotImplementedError

    async def latest_price(self, symbol: str) -> float:
        raise NotImplementedError

    async def intraday_bars(self, symbol: str, interval_minutes: int, days: int) -> list:
        raise NotImplementedError

    async def search(self, db, query: str, limit: int = 25) -> list:
        raise NotImplementedError

    # --- options; only meaningful when supports_options is True ---
    def option_underlyings(self) -> list:
        return []

    async def atm_legs(self, db, symbol: str) -> dict:
        raise AdapterError(f"{self.label} has no options chain available.")

    async def option_leg_closes(self, leg: dict) -> list:
        raise AdapterError(f"{self.label} has no options chain available.")

    async def leg_closes_by_date(self, leg: dict) -> dict:
        """{date: close} for one option leg -- required for straddle sums,
        which must align two legs by date, not by list position."""
        raise AdapterError(f"{self.label} has no options chain available.")

    async def options_snapshot(self, db, symbol: str) -> dict:
        """{spot, expiry, by_strike: {strike: {"call": leg, "put": leg}}}
        for the nearest monthly expiry -- the strike ladder Index Vector
        walks to find its ATM and its up/down straddle strikes."""
        raise AdapterError(f"{self.label} has no options chain available.")

    async def future_closes(self, db, symbol: str, days: int = 200) -> list:
        """The Gamma Pulse 'future' leg. Defaults to the underlying's own
        daily closes where no distinct futures instrument exists."""
        closes = await self.daily_closes(db, symbol)
        return [closes[d] for d in sorted(closes)][-days:]


# ---------------------------------------------------------------------------
# US Markets
# ---------------------------------------------------------------------------
class USAdapter(MarketAdapter):
    market_id = "us"
    label = "US Markets"
    session_open_minutes = 9 * 60 + 30
    tz = ZoneInfo("America/New_York")
    is_24h = False
    supports_options = True
    unavailable = {
        "swing-picks": "Swing Picks is a hand-curated pick list synced from a CSV on the "
                       "India side, not a computed scan — there is no formula to run against "
                       "US equities.",
    }

    async def universe(self, db) -> list:
        rows = await db.us_stock_symbol_master.find({}, {"_id": 0}).to_list(1000)
        return [{"symbol": r["symbol"], "name": r.get("company_name") or r["symbol"],
                 "group": r.get("sector") or "Unclassified"} for r in rows]

    def groups(self) -> list:
        # GICS sectors — the US analogue of the India side's sector baskets.
        return ["Information Technology", "Health Care", "Financials", "Consumer Discretionary",
                "Communication Services", "Industrials", "Consumer Staples", "Energy",
                "Utilities", "Real Estate", "Materials"]

    async def group_members(self, db, group: str) -> list:
        rows = await db.us_stock_symbol_master.find({"sector": group}, {"_id": 0, "symbol": 1}).to_list(1000)
        return [r["symbol"] for r in rows]

    async def daily_bars(self, db, symbol: str) -> list:
        try:
            return await yf.equity_bars(db, symbol)
        except yf.YahooFinanceError as e:
            raise AdapterError(str(e)) from e

    async def daily_closes(self, db, symbol: str) -> dict:
        try:
            bars = await yf.equity_bars(db, symbol)
        except yf.YahooFinanceError:
            return {}
        return {b["date"]: b["close"] for b in bars}

    async def latest_price(self, symbol: str) -> float:
        try:
            return await ac.latest_trade(symbol)
        except ac.AlpacaError as e:
            raise AdapterError(str(e)) from e

    async def intraday_bars(self, symbol: str, interval_minutes: int, days: int) -> list:
        try:
            return await ac.intraday_bars_for_ticker(symbol, str(interval_minutes), days=days)
        except ac.AlpacaError as e:
            raise AdapterError(str(e)) from e

    async def search(self, db, query: str, limit: int = 25) -> list:
        q = (query or "").strip().upper()
        filt = {"$or": [{"symbol": {"$regex": q}}, {"company_name": {"$regex": q, "$options": "i"}}]} if q else {}
        rows = await db.us_stock_symbol_master.find(filt, {"_id": 0}).limit(limit).to_list(limit)
        return [{"symbol": r["symbol"], "label": r.get("company_name") or r["symbol"],
                 "group": r.get("sector") or "Unclassified"} for r in rows]

    def option_underlyings(self) -> list:
        return ["SPY", "QQQ", "AAPL", "MSFT", "NVDA", "AMZN", "TSLA", "META", "GOOGL"]

    async def atm_legs(self, db, symbol: str) -> dict:
        symbol = symbol.strip().upper()
        proxy = ao.INDEX_OPTION_PROXIES.get(symbol)
        ticker = proxy["ticker"] if proxy else symbol
        try:
            spot = await ac.latest_trade(ticker)
        except ac.AlpacaError:
            closes = await self.daily_closes(db, ticker)
            if not closes:
                raise AdapterError(f"No price available for {ticker}.")
            spot = closes[sorted(closes)[-1]]
        try:
            legs = await ao.atm_legs(ticker, spot)
        except ao.AlpacaOptionsError as e:
            raise AdapterError(str(e)) from e
        legs["underlying_ticker"] = ticker
        legs["is_proxy"] = bool(proxy)
        legs["proxy_label"] = proxy["proxy_label"] if proxy else None
        return legs

    async def option_leg_closes(self, leg: dict) -> list:
        return await ao.contract_closes(leg["contract_symbol"])

    async def leg_closes_by_date(self, leg: dict) -> dict:
        return await ao.contract_closes_by_date(leg["contract_symbol"])

    async def options_snapshot(self, db, symbol: str) -> dict:
        legs = await self.atm_legs(db, symbol)
        ticker = legs["underlying_ticker"]
        spot = legs["spot"]
        window = max(spot * 0.15, 1.0)
        try:
            chain = await ao.option_chain(
                ticker, expiration_date=legs["expiry_date"],
                strike_low=spot - window, strike_high=spot + window,
            )
        except ao.AlpacaOptionsError as e:
            raise AdapterError(str(e)) from e
        return {
            "spot": spot, "expiry": legs["expiry_date"], "underlying_ticker": ticker,
            "is_proxy": legs["is_proxy"], "proxy_label": legs["proxy_label"],
            "by_strike": _index_by_strike(chain),
        }


# ---------------------------------------------------------------------------
# Forex
# ---------------------------------------------------------------------------
class ForexAdapter(MarketAdapter):
    market_id = "forex"
    label = "Forex"
    session_open_minutes = 0
    tz = ZoneInfo("UTC")
    is_24h = True
    supports_options = False
    unavailable = {
        "index-vector": "Index Vector reads options-market structure. No free, standardized "
                        "listed FX options chain exists — retail FX options trade OTC, with no "
                        "public chain to read.",
        "options-trend-scanner": "Gamma Pulse needs a future, an ATM call and an ATM put on the "
                                 "same instrument. FX options are OTC with no public listed "
                                 "chain, so two of the three legs cannot be read at all.",
        "peter-tingle": "The technical half of Peter Tingle runs on any price series, but the "
                        "fundamental half (leverage, cash flow, interest cover) has no meaning "
                        "for a currency pair — there is no balance sheet behind EURUSD.",
        "swing-picks": "Swing Picks is a hand-curated pick list synced from a CSV, not a "
                       "computed scan — there is no formula to run against FX pairs.",
    }

    async def universe(self, db) -> list:
        return [{"symbol": s, "name": m["label"], "group": m["group"]} for s, m in fx.FOREX_SYMBOLS.items()]

    def groups(self) -> list:
        return fx.GROUPS

    async def group_members(self, db, group: str) -> list:
        return fx.group_members(group)

    async def daily_bars(self, db, symbol: str) -> list:
        try:
            return await fx.daily_bars(db, symbol)
        except yf.YahooFinanceError as e:
            raise AdapterError(str(e)) from e

    async def daily_closes(self, db, symbol: str) -> dict:
        return await fx.daily_closes(db, symbol)

    async def latest_price(self, symbol: str) -> float:
        try:
            return await fx.latest_price(symbol)
        except yf.YahooFinanceError as e:
            raise AdapterError(str(e)) from e

    async def intraday_bars(self, symbol: str, interval_minutes: int, days: int) -> list:
        try:
            return await fx.intraday_bars(symbol, interval_minutes, days)
        except yf.YahooFinanceError as e:
            raise AdapterError(str(e)) from e

    async def search(self, db, query: str, limit: int = 25) -> list:
        return fx.search(query, limit)


# ---------------------------------------------------------------------------
# Crypto
# ---------------------------------------------------------------------------
class CryptoAdapter(MarketAdapter):
    market_id = "crypto"
    label = "Crypto"
    session_open_minutes = 0
    tz = ZoneInfo("UTC")
    is_24h = True
    supports_options = True
    unavailable = {
        "peter-tingle": "The technical half of Peter Tingle runs on any price series, but the "
                        "fundamental half (promoter pledge, cash flow quality, interest cover) "
                        "has no equivalent for a token — there is no balance sheet to scan.",
        "swing-picks": "Swing Picks is a hand-curated pick list synced from a CSV, not a "
                       "computed scan — there is no formula to run against crypto pairs.",
    }

    async def universe(self, db) -> list:
        return [{"symbol": s, "name": m["label"], "group": m["group"]} for s, m in cd.CRYPTO_SYMBOLS.items()]

    def groups(self) -> list:
        return cd.GROUPS

    async def group_members(self, db, group: str) -> list:
        return cd.group_members(group)

    async def daily_bars(self, db, symbol: str) -> list:
        try:
            return await cd.daily_bars(db, symbol)
        except cd.CryptoDataError as e:
            raise AdapterError(str(e)) from e

    async def daily_closes(self, db, symbol: str) -> dict:
        return await cd.daily_closes(db, symbol)

    async def latest_price(self, symbol: str) -> float:
        try:
            return await cd.latest_price(symbol)
        except cd.CryptoDataError as e:
            raise AdapterError(str(e)) from e

    async def intraday_bars(self, symbol: str, interval_minutes: int, days: int) -> list:
        try:
            return await cd.intraday_bars(symbol, interval_minutes, days)
        except cd.CryptoDataError as e:
            raise AdapterError(str(e)) from e

    async def search(self, db, query: str, limit: int = 25) -> list:
        return cd.search(query, limit)

    def option_underlyings(self) -> list:
        # Deribit lists options on a few more assets, but liquidity outside
        # BTC/ETH is too thin for a P&F column to mean anything.
        return ["BTCUSDT", "ETHUSDT"]

    @staticmethod
    def _currency(symbol: str) -> str:
        return symbol.strip().upper().replace("USDT", "").replace("USD", "")

    async def atm_legs(self, db, symbol: str) -> dict:
        currency = self._currency(symbol)
        if currency not in dc.CURRENCIES:
            raise AdapterError(f"Deribit lists options on {', '.join(dc.CURRENCIES)} only.")
        try:
            legs = await dc.atm_legs(currency)
        except dc.DeribitError as e:
            raise AdapterError(str(e)) from e
        legs["underlying_ticker"] = f"{currency}-PERPETUAL"
        legs["is_proxy"] = False
        legs["proxy_label"] = None
        return legs

    async def option_leg_closes(self, leg: dict) -> list:
        return await dc.instrument_closes(leg["instrument_name"])

    async def leg_closes_by_date(self, leg: dict) -> dict:
        return await dc.instrument_closes_by_date(leg["instrument_name"])

    async def options_snapshot(self, db, symbol: str) -> dict:
        currency = self._currency(symbol)
        if currency not in dc.CURRENCIES:
            raise AdapterError(f"Deribit lists options on {', '.join(dc.CURRENCIES)} only.")
        try:
            legs = await dc.atm_legs(currency)
            chain = await dc.option_chain(currency)
        except dc.DeribitError as e:
            raise AdapterError(str(e)) from e
        at_expiry = [c for c in chain if c["expiry_date"] == legs["expiry_date"]]
        return {
            "spot": legs["spot"], "expiry": legs["expiry_date"],
            "underlying_ticker": f"{currency}-PERPETUAL", "is_proxy": False, "proxy_label": None,
            "by_strike": _index_by_strike(at_expiry),
        }

    async def future_closes(self, db, symbol: str, days: int = 200) -> list:
        """Deribit's perpetual swap is the real, liquid non-option
        instrument here — the natural counterpart to the India side's
        index/stock future, and far better than reusing spot."""
        currency = self._currency(symbol)
        closes = await dc.perpetual_closes(currency, days=days)
        if closes:
            return closes
        return await super().future_closes(db, symbol, days)


ADAPTERS = {a.market_id: a for a in (USAdapter(), ForexAdapter(), CryptoAdapter())}


def get_adapter(market: str) -> MarketAdapter:
    adapter = ADAPTERS.get((market or "").strip().lower())
    if not adapter:
        raise AdapterError(f"Unknown market '{market}'. Known: {', '.join(ADAPTERS)}.")
    return adapter
