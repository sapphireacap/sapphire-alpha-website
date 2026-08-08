import { useState, useEffect, useRef } from "react";
import axios from "axios";
import { motion } from "framer-motion";
import {
  Loader2, LineChart as LineChartIcon, Crosshair, Activity, Target, Radar, BarChart3, Sliders, TrendingUp, Lock,
} from "lucide-react";
import { createChart, CandlestickSeries, ColorType } from "lightweight-charts";
import { MomentumTable } from "../AlphaTerminal";

// Binance's public market-data REST API -- free, no API key, no backend
// involved at all (verified live: Binance sends
// "Access-Control-Allow-Origin: *" on these endpoints, so a direct browser
// call works). Called straight from the client on purpose: this is real,
// generic market data with no proprietary methodology attached, so citing
// the real source (Binance) is just honest, not a leak of anything.
const BINANCE_API = "https://api.binance.com/api/v3";
const POLL_MS = 5000;

const SYMBOLS = [
  { symbol: "BTCUSDT", short: "BTC", name: "Bitcoin" },
  { symbol: "ETHUSDT", short: "ETH", name: "Ethereum" },
  { symbol: "SOLUSDT", short: "SOL", name: "Solana" },
  { symbol: "BNBUSDT", short: "BNB", name: "BNB" },
  { symbol: "XRPUSDT", short: "XRP", name: "XRP" },
  { symbol: "DOGEUSDT", short: "DOGE", name: "Dogecoin" },
];

const INTERVALS = [
  { key: "1m", label: "1m" },
  { key: "5m", label: "5m" },
  { key: "15m", label: "15m" },
  { key: "1h", label: "1h" },
  { key: "4h", label: "4h" },
  { key: "1d", label: "1D" },
];

const fmtPrice = (v) => {
  if (v == null) return "—";
  const n = Number(v);
  const dp = n >= 100 ? 2 : n >= 1 ? 4 : 6;
  return n.toLocaleString("en-US", { minimumFractionDigits: dp, maximumFractionDigits: dp });
};

const fmtCompact = (v) => (v == null ? "—" : Number(v).toLocaleString("en-US", { notation: "compact", maximumFractionDigits: 2 }));

/* ------------------------------ Module registry ------------------------------ */
// Same 8-slot layout/order as the Indian Markets directory (modules.js) --
// only the 3 that have a genuine free, real-time crypto data source behind
// them (Live Chart, Exitline, Momentum Leaders) are live; the rest carry
// the same "Coming Soon" honesty the India tab already applies to modules
// with no real backend yet (Swing Picks / Relative Strength / Sharpe /
// EWMA / Breakout are placeholders there too, not just here).
const CRYPTO_MODULES = [
  { slug: "chart", no: "01", icon: LineChartIcon, title: "Live Chart", shortDescription: "Live candlestick charts across major USDT pairs.", category: "Market Intelligence", live: true },
  { slug: "exitline", no: "02", icon: Crosshair, title: "Crypto Exitline", shortDescription: "Intraday levels with a suggested SL and TP.", category: "", live: true },
  { slug: "momentum", no: "03", icon: Activity, title: "Crypto Momentum Leaders", shortDescription: "Ranks 24h momentum across major USDT pairs.", category: "Screening Engine", live: true },
  { slug: "swing-picks", no: "04", icon: Target, title: "Swing Picks", shortDescription: "Multi-day swing picks with a buy-at level.", category: "Screening Engine", live: false },
  { slug: "relative-strength", no: "05", icon: Radar, title: "Relative Strength Engine", shortDescription: "Ranks outperforming coins.", category: "Screening Engine", live: false },
  { slug: "sharpe-dashboard", no: "06", icon: BarChart3, title: "Sharpe Dashboard", shortDescription: "Risk-adjusted coin ranking engine.", category: "Risk Analytics", live: false },
  { slug: "ewma-scanner", no: "07", icon: Sliders, title: "EWMA Scanner", shortDescription: "Trend acceleration and crossover engine.", category: "Signal Engine", live: false },
  { slug: "breakout-candidates", no: "08", icon: TrendingUp, title: "Breakout Candidates", shortDescription: "Detects high-conviction breakout setups.", category: "Screening Engine", live: false },
];

const ModuleCard = ({ module, index, active, onSelect }) => {
  const Icon = module.icon;
  if (!module.live) {
    return (
      <motion.div initial={{ opacity: 0, y: 16 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.5, delay: index * 0.05 }}>
        <div className="relative h-full rounded-2xl border border-white/10 bg-[#0A0D18] p-5 opacity-70" data-testid={`crypto-module-${module.slug}`}>
          <div className="flex items-center justify-between mb-4">
            <span className="inline-flex h-8 w-8 items-center justify-center rounded-lg border border-white/10 bg-white/[0.03] text-slate-500">
              <Icon size={14} />
            </span>
            <span className="font-mono-ui text-[10px] text-slate-500">{module.no}</span>
          </div>
          <h3 className="text-base font-bold text-white tracking-tight mb-1">{module.title}</h3>
          <p className="text-xs font-light text-slate-500 leading-relaxed mb-4">{module.shortDescription}</p>
          <span className="inline-flex items-center gap-1.5 font-mono-ui text-[10px] uppercase tracking-wider text-slate-500">
            <Lock size={10} /> Coming Soon
          </span>
        </div>
      </motion.div>
    );
  }
  return (
    <motion.div initial={{ opacity: 0, y: 16 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.5, delay: index * 0.05 }}>
      <button
        type="button"
        onClick={() => onSelect(module.slug)}
        className={`w-full text-left h-full rounded-2xl border p-5 transition-all duration-300 ${
          active === module.slug
            ? "border-sapphire/50 bg-sapphire/[0.06] shadow-[0_0_36px_rgba(31,95,208,0.14)]"
            : "border-white/10 bg-[#0A0D18] hover:border-sapphire/30 hover:bg-white/[0.02]"
        }`}
        data-testid={`crypto-module-${module.slug}`}
      >
        <div className="flex items-center justify-between mb-4">
          <span className={`inline-flex h-8 w-8 items-center justify-center rounded-lg border border-white/10 bg-white/[0.03] ${active === module.slug ? "text-sapphire-light" : "text-sapphire-light"}`}>
            <Icon size={14} />
          </span>
          <span className="font-mono-ui text-[10px] text-sapphire-light">{module.no}</span>
        </div>
        <h3 className="text-base font-bold text-white tracking-tight mb-1">{module.title}</h3>
        <p className="text-xs font-light text-slate-500 leading-relaxed">{module.shortDescription}</p>
      </button>
    </motion.div>
  );
};

/* --------------------------------- Chart module --------------------------------- */
const CryptoChart = ({ candles, fetchKey }) => {
  const containerRef = useRef(null);
  const chartRef = useRef(null);
  const seriesRef = useRef(null);
  const fitKeyRef = useRef(null);

  useEffect(() => {
    if (!containerRef.current) return undefined;
    const chart = createChart(containerRef.current, {
      layout: { background: { type: ColorType.Solid, color: "transparent" }, textColor: "#94A3B8" },
      grid: { vertLines: { visible: false }, horzLines: { visible: false } },
      timeScale: { timeVisible: true, secondsVisible: false, borderColor: "rgba(255,255,255,0.1)" },
      rightPriceScale: { borderColor: "rgba(255,255,255,0.1)" },
      handleScale: { mouseWheel: true, pinch: true, axisPressedMouseMove: { time: true, price: true } },
      handleScroll: { mouseWheel: true, pressedMouseMove: true, horzTouchDrag: true, vertTouchDrag: true },
      autoSize: true,
    });
    const series = chart.addSeries(CandlestickSeries, {
      upColor: "#34D399", downColor: "#F87171", borderVisible: false,
      wickUpColor: "#34D399", wickDownColor: "#F87171",
    });
    chartRef.current = chart;
    seriesRef.current = series;
    return () => {
      chart.remove();
      chartRef.current = null;
      seriesRef.current = null;
    };
  }, []);

  useEffect(() => {
    const series = seriesRef.current;
    const chart = chartRef.current;
    if (!series || !chart || !candles || candles.length === 0) return;
    series.setData(candles);
    if (fetchKey != null && fitKeyRef.current !== fetchKey) {
      fitKeyRef.current = fetchKey;
      chart.timeScale().fitContent();
    }
  }, [candles, fetchKey]);

  return <div ref={containerRef} className="h-[380px] md:h-[440px]" data-testid="crypto-chart" />;
};

const ChartModule = () => {
  const [symbol, setSymbol] = useState("BTCUSDT");
  const [interval, setIntervalKey] = useState("15m");
  const [candles, setCandles] = useState([]);
  const [ticker, setTicker] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const fetchKeyRef = useRef(0);

  useEffect(() => {
    let cancelled = false;
    fetchKeyRef.current += 1;
    setLoading(true);
    setError(false);

    const load = () => {
      Promise.all([
        axios.get(`${BINANCE_API}/klines`, { params: { symbol, interval, limit: 300 } }),
        axios.get(`${BINANCE_API}/ticker/24hr`, { params: { symbol } }),
      ]).then(([klinesRes, tickerRes]) => {
        if (cancelled) return;
        setCandles(klinesRes.data.map((k) => ({
          time: Math.floor(k[0] / 1000),
          open: parseFloat(k[1]), high: parseFloat(k[2]), low: parseFloat(k[3]), close: parseFloat(k[4]),
        })));
        setTicker(tickerRes.data);
        setLoading(false);
      }).catch(() => { if (!cancelled) { setError(true); setLoading(false); } });
    };

    load();
    const id = setInterval(load, POLL_MS);
    return () => { cancelled = true; clearInterval(id); };
  }, [symbol, interval]);

  const active = SYMBOLS.find((s) => s.symbol === symbol);
  const changePct = ticker ? parseFloat(ticker.priceChangePercent) : null;
  const changeNegative = changePct != null && changePct < 0;

  return (
    <div data-testid="crypto-chart-module">
      <div className="flex flex-wrap items-center gap-2 mb-5" data-testid="crypto-symbol-selector">
        {SYMBOLS.map((s) => (
          <button
            key={s.symbol}
            type="button"
            onClick={() => setSymbol(s.symbol)}
            className={`px-3.5 py-1.5 rounded-full font-mono-ui text-[11px] uppercase tracking-[0.1em] whitespace-nowrap border transition-colors duration-300 ${
              symbol === s.symbol ? "border-sapphire-light/50 bg-sapphire/10 text-white" : "border-white/10 text-slate-500 hover:text-slate-300"
            }`}
            data-testid={`crypto-symbol-${s.short}`}
          >
            {s.short}
          </button>
        ))}
      </div>

      <div className="rounded-2xl border border-white/10 bg-[#0A0D18] p-4 md:p-6" data-testid="crypto-chart-card">
        <div className="flex flex-wrap items-start justify-between gap-4 mb-5">
          <div>
            <div className="flex items-center gap-2 mb-1.5">
              <span className="relative flex h-2 w-2">
                <span className="absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-60 animate-ping" />
                <span className="relative inline-flex h-2 w-2 rounded-full bg-emerald-400" />
              </span>
              <span className="text-xl md:text-2xl font-bold text-white tracking-tight">{active?.name}</span>
              <span className="font-mono-ui text-xs text-slate-500">{active?.short}/USDT</span>
            </div>
            <div className="flex items-baseline gap-3">
              <span className="font-mono-ui text-2xl md:text-3xl font-bold text-white">{ticker ? `$${fmtPrice(ticker.lastPrice)}` : "—"}</span>
              {changePct != null && (
                <span className={`font-mono-ui text-sm font-semibold ${changeNegative ? "text-red-400" : "text-emerald-400"}`}>
                  {changeNegative ? "" : "+"}{changePct.toFixed(2)}% (24h)
                </span>
              )}
            </div>
          </div>
          <div className="flex items-center gap-1 rounded-md border border-white/10 p-0.5" data-testid="crypto-interval-selector">
            {INTERVALS.map((iv) => (
              <button
                key={iv.key}
                type="button"
                onClick={() => setIntervalKey(iv.key)}
                data-testid={`crypto-interval-${iv.key}`}
                className={`font-mono-ui text-[10px] uppercase tracking-wider px-2.5 py-1 rounded transition-colors ${
                  interval === iv.key ? "bg-sapphire-light/20 text-sapphire-light" : "text-slate-500 hover:text-slate-300"
                }`}
              >
                {iv.label}
              </button>
            ))}
          </div>
        </div>

        {loading ? (
          <div className="h-[380px] md:h-[440px] flex items-center justify-center text-slate-500 font-mono-ui text-sm gap-3">
            <Loader2 className="animate-spin" size={16} /> Loading live data…
          </div>
        ) : error ? (
          <div className="h-[380px] md:h-[440px] flex items-center justify-center text-slate-500 text-sm">
            Could not load live data right now — try again shortly.
          </div>
        ) : (
          <CryptoChart candles={candles} fetchKey={fetchKeyRef.current} />
        )}

        {ticker && (
          <div className="grid grid-cols-3 gap-4 mt-5 pt-5 border-t border-white/[0.06]">
            <div>
              <p className="font-mono-ui text-[10px] uppercase tracking-wider text-slate-500 mb-1">24h High</p>
              <p className="font-mono-ui text-sm text-slate-200">${fmtPrice(ticker.highPrice)}</p>
            </div>
            <div>
              <p className="font-mono-ui text-[10px] uppercase tracking-wider text-slate-500 mb-1">24h Low</p>
              <p className="font-mono-ui text-sm text-slate-200">${fmtPrice(ticker.lowPrice)}</p>
            </div>
            <div>
              <p className="font-mono-ui text-[10px] uppercase tracking-wider text-slate-500 mb-1">24h Volume</p>
              <p className="font-mono-ui text-sm text-slate-200">{fmtCompact(ticker.quoteVolume)} USDT</p>
            </div>
          </div>
        )}
      </div>
    </div>
  );
};

/* -------------------------------- Exitline module -------------------------------- */
// Same real ladder formula as Intraday Exitline's backend
// (backend/exitline.py's compute_camarilla_levels / classify_and_suggest),
// ported to pure client-side JS -- crypto trades 24/7 so "previous day" is
// the last fully-closed daily candle rather than a market-hours session,
// but the math and zone rules are identical, computed from real Binance
// daily OHLC instead of Definedge's.
const DISPLAY_LABELS = { H5: "S5", H4: "S4", H3: "S3", Pivot: "PZ", L3: "V3", L4: "V4" };
const FULL_NAMES = { H5: "Sentinel 5", H4: "Sentinel 4", H3: "Sentinel 3", Pivot: "Pivot Zone", L3: "Vault 3", L4: "Vault 4" };
const VISIBLE_LEVELS = ["H5", "H4", "H3", "Pivot", "L3", "L4"];
const LEVEL_COLOR = { H5: "text-emerald-400/80", H4: "text-emerald-400/80", H3: "text-emerald-400/80", Pivot: "text-white", L3: "text-red-400/80", L4: "text-red-400/80" };

function computeCamarillaLevels(high, low, close) {
  const r = high - low;
  const h5 = (high / low) * close;
  return {
    H5: h5,
    H4: close + (r * 1.1) / 2,
    H3: close + (r * 1.1) / 4,
    H2: close + (r * 1.1) / 6,
    H1: close + (r * 1.1) / 12,
    Pivot: (high + low + close) / 3,
    L1: close - (r * 1.1) / 12,
    L2: close - (r * 1.1) / 6,
    L3: close - (r * 1.1) / 4,
    L4: close - (r * 1.1) / 2,
    L5: 2 * close - h5,
  };
}

function classifyAndSuggest(levels, ltp, prevClose) {
  const { H4, H3, H2, H1, L1, L2, L3, L4 } = levels;
  if (ltp > H4) {
    return { zoneLabel: "Breakout Zone (Upper)", bias: "Long", sl: H4, tp: null, tpAlt: null, trailStop: true,
      reason: `Broke above S4 (${fmtPrice(H4)}) — trend day, mean-reversion invalidated. Buy the breakout (or on retest of S4); no fixed target, trail the stop.` };
  }
  if (ltp < L4) {
    return { zoneLabel: "Breakout Zone (Lower)", bias: "Short", sl: L4, tp: null, tpAlt: null, trailStop: true,
      reason: `Broke below V4 (${fmtPrice(L4)}) — trend day, mean-reversion invalidated. Short the breakdown (or on retest of V4); no fixed target, trail the stop.` };
  }
  if (ltp >= H3 && ltp <= H4) {
    return { zoneLabel: "Trading Zone — At S3", bias: "Short", sl: H4 * 1.001, tp: H1, tpAlt: H2, trailStop: false,
      reason: `At S3 (${fmtPrice(H3)}) — short bias, TP toward S1/S2 or previous close (${fmtPrice(prevClose)}), SL just above S4.` };
  }
  if (ltp >= L4 && ltp <= L3) {
    return { zoneLabel: "Trading Zone — At V3", bias: "Long", sl: L4 * 0.999, tp: L1, tpAlt: L2, trailStop: false,
      reason: `At V3 (${fmtPrice(L3)}) — long bias, TP toward V1/V2 or previous close (${fmtPrice(prevClose)}), SL just below V4.` };
  }
  const checkpoints = [["S2", H2], ["S1", H1], ["V1", L1], ["V2", L2]];
  let closest = checkpoints[0];
  for (const cp of checkpoints) if (Math.abs(ltp - cp[1]) < Math.abs(ltp - closest[1])) closest = cp;
  const [label, val] = closest;
  const above = ltp >= val;
  const bullishLabel = label === "S1" || label === "S2";
  const commentary = bullishLabel
    ? (above ? `Holding above ${label} (${fmtPrice(val)}) — firm bullish momentum, not a standalone trigger.` : `Struggling near ${label} (${fmtPrice(val)}) — weak bullish momentum, not a standalone trigger.`)
    : (above ? `Holding above ${label} (${fmtPrice(val)}) — support test holding, not a standalone trigger.` : `Slipping below ${label} (${fmtPrice(val)}) — weak bearish momentum, not a standalone trigger.`);
  return { zoneLabel: "Trading Zone — Mid-Range", bias: "Neutral", sl: null, tp: null, tpAlt: null, trailStop: false,
    reason: "Inside V3/S3 — range-bound, no standalone entry trigger at current levels.", commentary };
}

const ExitlineModule = () => {
  const [symbol, setSymbol] = useState("BTCUSDT");
  const [levels, setLevels] = useState(null);
  const [prevClose, setPrevClose] = useState(null);
  const [ltp, setLtp] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(false);

    const load = () => {
      Promise.all([
        axios.get(`${BINANCE_API}/klines`, { params: { symbol, interval: "1d", limit: 2 } }),
        axios.get(`${BINANCE_API}/ticker/price`, { params: { symbol } }),
      ]).then(([klinesRes, priceRes]) => {
        if (cancelled) return;
        const days = klinesRes.data;
        const yesterday = days.length >= 2 ? days[days.length - 2] : days[0];
        const high = parseFloat(yesterday[2]), low = parseFloat(yesterday[3]), close = parseFloat(yesterday[4]);
        setLevels(computeCamarillaLevels(high, low, close));
        setPrevClose(close);
        setLtp(parseFloat(priceRes.data.price));
        setLoading(false);
      }).catch(() => { if (!cancelled) { setError(true); setLoading(false); } });
    };

    load();
    const id = setInterval(load, POLL_MS);
    return () => { cancelled = true; clearInterval(id); };
  }, [symbol]);

  const active = SYMBOLS.find((s) => s.symbol === symbol);
  const signal = levels && ltp != null && prevClose != null ? classifyAndSuggest(levels, ltp, prevClose) : null;
  const rows = levels ? [...VISIBLE_LEVELS.map((k) => ({ key: k, value: levels[k] })), { key: "LTP", value: ltp }].sort((a, b) => b.value - a.value) : [];

  return (
    <div data-testid="crypto-exitline-module">
      <div className="flex flex-wrap items-center gap-2 mb-5" data-testid="exitline-symbol-selector">
        {SYMBOLS.map((s) => (
          <button
            key={s.symbol}
            type="button"
            onClick={() => setSymbol(s.symbol)}
            className={`px-3.5 py-1.5 rounded-full font-mono-ui text-[11px] uppercase tracking-[0.1em] whitespace-nowrap border transition-colors duration-300 ${
              symbol === s.symbol ? "border-sapphire-light/50 bg-sapphire/10 text-white" : "border-white/10 text-slate-500 hover:text-slate-300"
            }`}
            data-testid={`exitline-symbol-${s.short}`}
          >
            {s.short}
          </button>
        ))}
      </div>

      {loading ? (
        <div className="h-64 flex items-center justify-center text-slate-500 font-mono-ui text-sm gap-3">
          <Loader2 className="animate-spin" size={16} /> Loading live levels…
        </div>
      ) : error || !signal ? (
        <div className="h-64 flex items-center justify-center text-slate-500 text-sm">Could not load live data right now — try again shortly.</div>
      ) : (
        <>
          <div className={`rounded-2xl border p-5 md:p-6 mb-5 ${signal.bias === "Long" ? "border-emerald-400/25 bg-emerald-400/[0.04]" : signal.bias === "Short" ? "border-red-400/25 bg-red-400/[0.04]" : "border-white/10 bg-[#0A0D18]"}`} data-testid="exitline-signal-card">
            <div className="flex flex-wrap items-center justify-between gap-3 mb-3">
              <span className="text-lg font-bold text-white">{active?.name} — {signal.zoneLabel}</span>
              <span className={`font-mono-ui text-xs font-bold uppercase tracking-wider px-3 py-1 rounded-full border ${
                signal.bias === "Long" ? "border-emerald-400/30 text-emerald-300" : signal.bias === "Short" ? "border-red-400/30 text-red-300" : "border-white/15 text-slate-400"
              }`}>
                {signal.bias}
              </span>
            </div>
            <p className="text-sm text-slate-300 leading-relaxed mb-4">{signal.reason}{signal.commentary ? ` ${signal.commentary}` : ""}</p>
            <div className="grid grid-cols-3 gap-4">
              <div>
                <p className="font-mono-ui text-[10px] uppercase tracking-wider text-slate-500 mb-1">Live Price</p>
                <p className="font-mono-ui text-sm text-white font-bold">${fmtPrice(ltp)}</p>
              </div>
              <div>
                <p className="font-mono-ui text-[10px] uppercase tracking-wider text-slate-500 mb-1">Suggested SL</p>
                <p className="font-mono-ui text-sm text-red-400">{signal.sl != null ? `$${fmtPrice(signal.sl)}` : "—"}</p>
              </div>
              <div>
                <p className="font-mono-ui text-[10px] uppercase tracking-wider text-slate-500 mb-1">{signal.trailStop ? "Target" : "Suggested TP"}</p>
                <p className="font-mono-ui text-sm text-emerald-400">{signal.trailStop ? "Trail Stop" : signal.tp != null ? `$${fmtPrice(signal.tp)}` : "—"}</p>
              </div>
            </div>
          </div>

          <div className="rounded-2xl border border-white/10 bg-[#0A0D18] overflow-hidden" data-testid="crypto-exitline-ladder">
            <div className="px-5 py-3 border-b border-white/10">
              <p className="font-mono-ui text-[10px] uppercase tracking-[0.24em] text-slate-400">Sapphire Levels™</p>
            </div>
            <div className="overflow-x-auto">
              <table className="w-full min-w-[420px]" style={{ fontVariantNumeric: "tabular-nums" }}>
                <tbody>
                  {rows.map((r) => {
                    const isLtp = r.key === "LTP";
                    return (
                      <tr key={r.key} className={`border-b border-white/[0.05] last:border-0 ${isLtp ? "bg-sapphire-light/15" : ""}`}>
                        <td className="px-5 py-3 whitespace-nowrap">
                          <span className={`block font-mono-ui text-xs uppercase tracking-[0.14em] ${isLtp ? "text-sapphire-light font-bold" : LEVEL_COLOR[r.key]}`}>
                            {isLtp ? "◆ PX (Live)" : (DISPLAY_LABELS[r.key] || r.key)}
                          </span>
                          <span className="block text-[11px] text-slate-500 mt-0.5">{isLtp ? "Price Nexus" : (FULL_NAMES[r.key] || "")}</span>
                        </td>
                        <td className={`px-5 py-3 text-right font-mono-ui text-sm whitespace-nowrap ${isLtp ? "text-white font-bold" : "text-slate-300"}`}>${fmtPrice(r.value)}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </div>
        </>
      )}
    </div>
  );
};

/* -------------------------------- Momentum module -------------------------------- */
const openBinanceChart = (r) => window.open(`https://www.binance.com/en/trade/${r.ticker}_USDT`, "_blank", "noopener,noreferrer");

const MomentumModule = () => {
  const [rows, setRows] = useState(null);
  const [error, setError] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setError(false);

    const load = () => {
      axios.get(`${BINANCE_API}/ticker/24hr`).then(({ data }) => {
        if (cancelled) return;
        const leaders = data
          .filter((t) => t.symbol.endsWith("USDT"))
          .filter((t) => !/(UP|DOWN|BULL|BEAR)USDT$/.test(t.symbol)) // leveraged tokens, not real spot momentum
          .filter((t) => !["USDCUSDT", "FDUSDUSDT", "TUSDUSDT", "USDPUSDT", "DAIUSDT"].includes(t.symbol)) // stablecoin pairs, no real momentum to rank
          .filter((t) => parseFloat(t.quoteVolume) > 5_000_000) // liquidity floor so the list isn't dominated by illiquid noise
          .sort((a, b) => parseFloat(b.priceChangePercent) - parseFloat(a.priceChangePercent))
          .slice(0, 15)
          .map((t) => ({
            id: t.symbol,
            ticker: t.symbol.replace(/USDT$/, ""),
            company: t.symbol.replace(/USDT$/, "") + "/USDT",
            momentum_score: `${parseFloat(t.priceChangePercent) >= 0 ? "+" : ""}${parseFloat(t.priceChangePercent).toFixed(2)}%`,
            volume: `${fmtCompact(t.quoteVolume)} USDT`,
            bias: parseFloat(t.priceChangePercent) >= 0 ? "Bullish" : "Bearish",
          }));
        setRows(leaders);
      }).catch(() => { if (!cancelled) setError(true); });
    };

    load();
    const id = setInterval(load, 15000);
    return () => { cancelled = true; clearInterval(id); };
  }, []);

  if (error) return <div className="h-64 flex items-center justify-center text-slate-500 text-sm">Could not load live data right now — try again shortly.</div>;
  if (rows === null) {
    return <div className="h-64 flex items-center justify-center text-slate-500 font-mono-ui text-sm gap-3"><Loader2 className="animate-spin" size={16} /> Loading live momentum…</div>;
  }
  return (
    <div data-testid="crypto-momentum-module">
      <MomentumTable
        rows={rows}
        onRowClick={openBinanceChart}
        disclaimer="Real 24h price-change data via Binance across major USDT pairs (leveraged tokens and stablecoin pairs excluded). Ranked mechanically by momentum, not a curated pick list. For informational purposes only — not investment advice."
      />
    </div>
  );
};

/* ---------------------------------- Dashboard ---------------------------------- */
export default function CryptoDashboard() {
  // No module pre-selected -- the default view is just the directory grid,
  // same as the Indian Markets tab (whose cards link out to a separate
  // page rather than expanding inline). A live module's content only shows
  // once its card is actually clicked.
  const [activeModule, setActiveModule] = useState(null);

  return (
    <div data-testid="crypto-dashboard">
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-8" data-testid="crypto-module-grid">
        {CRYPTO_MODULES.map((m, i) => (
          <ModuleCard key={m.slug} module={m} index={i} active={activeModule} onSelect={setActiveModule} />
        ))}
      </div>

      {activeModule === "chart" && <ChartModule />}
      {activeModule === "exitline" && <ExitlineModule />}
      {activeModule === "momentum" && <MomentumModule />}

      {activeModule && (
        <p className="text-xs font-light text-slate-500 leading-relaxed mt-6 max-w-2xl" data-testid="crypto-disclaimer">
          Live market data via Binance, refreshed every few seconds. For informational purposes only — not investment advice.
        </p>
      )}
    </div>
  );
}
