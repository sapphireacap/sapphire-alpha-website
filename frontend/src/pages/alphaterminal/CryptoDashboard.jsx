import { useState, useEffect, useRef } from "react";
import axios from "axios";
import { Loader2 } from "lucide-react";
import { createChart, CandlestickSeries, ColorType } from "lightweight-charts";
import LivePulseDot from "../../components/site/LivePulseDot";

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

const fmtCompact = (v) => {
  if (v == null) return "—";
  return Number(v).toLocaleString("en-US", { notation: "compact", maximumFractionDigits: 2 });
};

// Same lightweight-charts engine/conventions as Exitline.jsx's TVChart
// (transparent background, no gridlines, sapphire-institutional up/down
// colors) -- kept simpler here since crypto has no proprietary level
// overlays to draw, just the raw candles.
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
    // Only re-fit the view on a real symbol/interval change, not on a
    // background live-poll refresh -- otherwise a user's manual zoom/scroll
    // gets yanked back to "fit all" every 5 seconds.
    if (fetchKey != null && fitKeyRef.current !== fetchKey) {
      fitKeyRef.current = fetchKey;
      chart.timeScale().fitContent();
    }
  }, [candles, fetchKey]);

  return <div ref={containerRef} className="h-[380px] md:h-[460px]" data-testid="crypto-chart" />;
};

export default function CryptoDashboard() {
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
      }).catch(() => {
        if (!cancelled) { setError(true); setLoading(false); }
      });
    };

    load();
    const id = setInterval(load, POLL_MS);
    return () => { cancelled = true; clearInterval(id); };
  }, [symbol, interval]);

  const active = SYMBOLS.find((s) => s.symbol === symbol);
  const changePct = ticker ? parseFloat(ticker.priceChangePercent) : null;
  const changeNegative = changePct != null && changePct < 0;

  return (
    <div data-testid="crypto-dashboard">
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

      <div className={`rounded-2xl border border-white/10 bg-[#0A0D18] p-4 md:p-6`} data-testid="crypto-chart-card">
        <div className="flex flex-wrap items-start justify-between gap-4 mb-5">
          <div>
            <div className="flex items-center gap-2 mb-1.5">
              <LivePulseDot />
              <span className="font-display text-xl md:text-2xl font-bold text-white tracking-tight">{active?.name}</span>
              <span className="font-mono-ui text-xs text-slate-500">{active?.short}/USDT</span>
            </div>
            <div className="flex items-baseline gap-3">
              <span className="font-mono-ui text-2xl md:text-3xl font-bold text-white">
                {ticker ? `$${fmtPrice(ticker.lastPrice)}` : "—"}
              </span>
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
          <div className="h-[380px] md:h-[460px] flex items-center justify-center text-slate-500 font-mono-ui text-sm gap-3">
            <Loader2 className="animate-spin" size={16} /> Loading live data…
          </div>
        ) : error ? (
          <div className="h-[380px] md:h-[460px] flex items-center justify-center text-slate-500 text-sm">
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

      <p className="text-xs font-light text-slate-500 leading-relaxed mt-5 max-w-2xl" data-testid="crypto-disclaimer">
        Live market data via Binance, refreshed every few seconds. For informational purposes only — not investment advice.
      </p>
    </div>
  );
}
