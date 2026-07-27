import { useState, useEffect, useRef } from "react";
import axios from "axios";
import { toast } from "sonner";
import { Loader2, Crosshair } from "lucide-react";
import { createChart, CandlestickSeries, ColorType, LineStyle } from "lightweight-charts";
import { field, selectCls, label, LoadingParticles, EmptyState } from "./QuantLab";

const POLL_MS = 30000; // keep the LTP marker live while results are showing

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;

const SEGMENTS = [
  { key: "NSE", label: "NSE (Cash)" },
  { key: "FUT", label: "Futures" },
  { key: "OPT", label: "Options" },
];

const fmtDate = (iso) => {
  if (!iso) return "—";
  const [y, m, d] = iso.split("-");
  return `${d}/${m}/${y}`;
};

const fmtNum = (v) => (v == null ? "—" : Number(v).toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 }));

// Backend still computes all 11 levels (H1/H2/L1/L2 feed the mid-range
// commentary text used elsewhere) but only these six are ever shown here —
// H1/H2/L1/L2/L5 are dropped entirely from display, per request.
const VISIBLE_LEVELS = ["H5", "H4", "H3", "Pivot", "L3", "L4"];

// Matches the reference: all H-levels red (resistance overhead), Pivot
// cyan, all L-levels green (support below) — not a per-level gradient.
const LEVEL_COLORS = {
  H5: "#F87171", H4: "#F87171", H3: "#F87171",
  Pivot: "#22D3EE",
  L3: "#34D399", L4: "#34D399",
};

const INTERVALS = [
  { key: 1, label: "1m" },
  { key: 5, label: "5m" },
  { key: 15, label: "15m" },
  { key: 30, label: "30m" },
  { key: 60, label: "1h" },
];

// TradingView's own open-source charting engine (not their embeddable
// tradingview.com widget — that only supports custom price-line overlays
// via the paid Charting Library). Renders our real Definedge candles with
// native price lines for the levels, fully under our control.
const TVChart = ({ chart, levels, ltp, interval, onIntervalChange }) => {
  const containerRef = useRef(null);
  const chartRef = useRef(null);
  const seriesRef = useRef(null);
  const priceLinesRef = useRef([]);
  const fitKeyRef = useRef(null); // re-fit the view on symbol/interval change, but not on a live-poll refresh (so a manual zoom/scroll sticks)

  useEffect(() => {
    if (!containerRef.current) return undefined;
    const tvChart = createChart(containerRef.current, {
      layout: { background: { type: ColorType.Solid, color: "transparent" }, textColor: "#94A3B8" },
      grid: { vertLines: { visible: false }, horzLines: { visible: false } },
      timeScale: { timeVisible: true, secondsVisible: false, borderColor: "rgba(255,255,255,0.1)" },
      rightPriceScale: { borderColor: "rgba(255,255,255,0.1)" },
      handleScale: {
        mouseWheel: true, pinch: true,
        axisPressedMouseMove: { time: true, price: true },
      },
      handleScroll: { mouseWheel: true, pressedMouseMove: true, horzTouchDrag: true, vertTouchDrag: true },
      autoSize: true,
    });
    const series = tvChart.addSeries(CandlestickSeries, {
      upColor: "#34D399", downColor: "#F87171", borderVisible: false,
      wickUpColor: "#34D399", wickDownColor: "#F87171",
    });
    chartRef.current = tvChart;
    seriesRef.current = series;
    return () => {
      tvChart.remove();
      chartRef.current = null;
      seriesRef.current = null;
    };
  }, []);

  useEffect(() => {
    const series = seriesRef.current;
    const tvChart = chartRef.current;
    if (!series || !tvChart || !chart || chart.length === 0) return;

    priceLinesRef.current.forEach((pl) => series.removePriceLine(pl));
    priceLinesRef.current = [];

    series.setData(chart.filter((b) => b.time != null).map((b) => ({
      time: b.time, open: b.open, high: b.high, low: b.low, close: b.close,
    })));

    // Levels routinely sit outside the candles' own price range (e.g. Pivot/
    // L3/L4 well below today's trading band) — the default autoscale only
    // fits the visible candle data, which would clip those lines off-screen.
    // Extend the price range to always include every visible level + LTP.
    series.applyOptions({
      autoscaleInfoProvider: (original) => {
        const res = original();
        const values = VISIBLE_LEVELS.map((k) => levels[k]).filter((v) => v != null);
        if (ltp != null) values.push(ltp);
        if (!values.length) return res;
        const min = Math.min(...values);
        const max = Math.max(...values);
        if (!res || !res.priceRange) return { priceRange: { minValue: min, maxValue: max } };
        return {
          priceRange: {
            minValue: Math.min(res.priceRange.minValue, min),
            maxValue: Math.max(res.priceRange.maxValue, max),
          },
          margins: res.margins,
        };
      },
    });

    VISIBLE_LEVELS.forEach((k) => {
      const v = levels[k];
      if (v == null) return;
      priceLinesRef.current.push(series.createPriceLine({
        price: v, color: LEVEL_COLORS[k] || "#64748B", lineWidth: 2,
        lineStyle: LineStyle.Solid, axisLabelVisible: true, title: k,
      }));
    });
    if (ltp != null) {
      priceLinesRef.current.push(series.createPriceLine({
        price: ltp, color: "#437EEB", lineWidth: 2,
        lineStyle: LineStyle.Solid, axisLabelVisible: true, title: "LTP",
      }));
    }

    // Only reset the view (time+price scale) when the symbol or timeframe
    // actually changes — a background live-poll refresh (same key) must
    // never yank a user's manual scroll/zoom back to "fit all".
    const fitKey = `${chart[0]?.time}-${interval}`;
    if (fitKeyRef.current !== fitKey) {
      fitKeyRef.current = fitKey;
      tvChart.timeScale().fitContent();
    }
  }, [chart, levels, ltp, interval]);

  const isEmpty = !chart || chart.length === 0;

  return (
    <div className="glass rounded-2xl border border-white/10 p-4 md:p-6 mb-6" data-testid="exitline-chart">
      <div className="flex flex-wrap items-center justify-between gap-3 mb-3">
        <p className="font-mono-ui text-[10px] uppercase tracking-[0.18em] text-slate-500">Today's Session · Live</p>
        <div className="flex items-center gap-1 rounded-md border border-white/10 p-0.5" data-testid="exitline-interval-selector">
          {INTERVALS.map((iv) => (
            <button
              key={iv.key}
              type="button"
              onClick={() => onIntervalChange(iv.key)}
              data-testid={`exitline-interval-${iv.key}`}
              className={`font-mono-ui text-[10px] uppercase tracking-wider px-2.5 py-1 rounded transition-colors ${
                interval === iv.key ? "bg-sapphire-light/20 text-sapphire-light" : "text-slate-500 hover:text-slate-300"
              }`}
            >
              {iv.label}
            </button>
          ))}
        </div>
      </div>
      <div className="relative h-96">
        {isEmpty && (
          <div className="absolute inset-0 flex items-center justify-center z-10" data-testid="exitline-chart-empty">
            <p className="text-xs text-slate-500">No intraday bars yet for this session.</p>
          </div>
        )}
        <div ref={containerRef} className="h-96" data-testid="exitline-tv-chart" />
      </div>
    </div>
  );
};

const Ladder = ({ levels, ltp }) => {
  const rows = [
    ...VISIBLE_LEVELS.map((k) => ({ key: k, value: levels[k], isLtp: false })),
    { key: "LTP", value: ltp, isLtp: true },
  ].sort((a, b) => b.value - a.value);

  return (
    <div className="glass rounded-2xl border border-white/10 overflow-hidden" data-testid="exitline-ladder">
      {rows.map((r) => (
        <div
          key={r.key}
          data-testid={r.isLtp ? "exitline-ltp-row" : `exitline-level-${r.key}`}
          className={`flex items-center justify-between px-5 py-3 border-b border-white/[0.05] last:border-0 ${
            r.isLtp ? "bg-sapphire-light/15 border-y border-sapphire-light/40" : ""
          }`}
        >
          <span className={`font-mono-ui text-xs uppercase tracking-[0.14em] ${r.isLtp ? "text-sapphire-light font-bold" : r.key.startsWith("H") ? "text-emerald-400/80" : r.key.startsWith("L") ? "text-red-400/80" : "text-white"}`}>
            {r.isLtp ? "◆ LTP (Current)" : r.key}
          </span>
          <span className={`font-mono-ui text-sm ${r.isLtp ? "text-white font-bold" : "text-slate-300"}`}>₹{fmtNum(r.value)}</span>
        </div>
      ))}
    </div>
  );
};

const ExitlineResults = ({ result, interval, onIntervalChange }) => (
  <div data-testid="exitline-results">
    <div className="mb-4">
      <p className="font-display text-xl font-bold text-white">{result.tradingsymbol}</p>
      <p className="font-mono-ui text-[10px] uppercase tracking-[0.18em] text-slate-500 mt-1">
        Prev session ({fmtDate(result.prev_date)}) — H ₹{fmtNum(result.high)} · L ₹{fmtNum(result.low)} · C ₹{fmtNum(result.close)}
      </p>
    </div>

    <TVChart chart={result.chart} levels={result.levels} ltp={result.ltp} interval={interval} onIntervalChange={onIntervalChange} />

    <div className="max-w-md mb-6">
      <Ladder levels={result.levels} ltp={result.ltp} />
    </div>

    <p className="text-[11px] font-light text-slate-600 max-w-2xl">
      These levels are fixed for the trading day, computed from the previous session's H/L/C. Not investment advice.
    </p>
  </div>
);

const SymbolPicker = ({ segment, symbol, onSelect }) => {
  const [query, setQuery] = useState(symbol || "");
  const [options, setOptions] = useState([]);
  const [open, setOpen] = useState(false);
  const debounceRef = useRef(null);

  useEffect(() => { setQuery(symbol || ""); }, [symbol]);

  const onChange = (e) => {
    const v = e.target.value;
    setQuery(v);
    onSelect(""); // clear confirmed selection until a real pick is made
    if (debounceRef.current) clearTimeout(debounceRef.current);
    if (v.trim().length < 1) { setOptions([]); setOpen(false); return; }
    debounceRef.current = setTimeout(async () => {
      try {
        const { data } = await axios.get(`${API}/exitline/instruments`, { params: { segment, query: v.trim() } });
        setOptions(data.symbols || []);
        setOpen(true);
      } catch {
        setOptions([]);
      }
    }, 250);
  };

  const pick = (s) => {
    setQuery(s);
    setOpen(false);
    onSelect(s);
  };

  return (
    <div className="relative">
      <label className={label}>Scrip</label>
      <input
        value={query}
        onChange={onChange}
        onFocus={() => options.length > 0 && setOpen(true)}
        onBlur={() => setTimeout(() => setOpen(false), 150)}
        className={field}
        placeholder="Search symbol… e.g. RELIANCE"
        data-testid="exitline-symbol-input"
        autoComplete="off"
      />
      {open && options.length > 0 && (
        <div className="absolute z-20 mt-1 w-full max-h-56 overflow-y-auto glass rounded-md border border-white/10 shadow-xl" data-testid="exitline-symbol-dropdown">
          {options.map((s) => (
            <button
              type="button"
              key={s}
              onClick={() => pick(s)}
              className="block w-full text-left px-3 py-2 text-sm text-slate-200 hover:bg-white/10 transition-colors font-mono-ui"
            >
              {s}
            </button>
          ))}
        </div>
      )}
    </div>
  );
};

const ExitlineTool = () => {
  const [segment, setSegment] = useState("NSE");
  const [symbol, setSymbol] = useState("");
  const [expiryOptions, setExpiryOptions] = useState([]);
  const [expiry, setExpiry] = useState("");
  const [strikeOptions, setStrikeOptions] = useState([]);
  const [strike, setStrike] = useState("");
  const [optionType, setOptionType] = useState("CE");
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState(null);
  const [chartInterval, setChartInterval] = useState(5);
  const paramsRef = useRef(null); // last-submitted query params, kept alive for the background poll

  const fetchLevels = async (params, { silent } = {}) => {
    if (!silent) { setLoading(true); setResult(null); }
    try {
      const { data } = await axios.get(`${API}/exitline/levels`, { params });
      setResult(data);
    } catch (err) {
      if (!silent) {
        toast.error(err?.response?.data?.detail || "Could not fetch levels. Please try again.");
        setResult({ found: false, reason: err?.response?.data?.detail || "Could not fetch levels for this instrument." });
      }
      // a silent background refresh failing (e.g. a transient Definedge hiccup) just keeps showing the last good result
    } finally {
      if (!silent) setLoading(false);
    }
  };

  // Keeps the chart/LTP live while a result is on screen — matches the
  // "live chart of that trading session" ask, without turning this into a
  // constantly-polling dashboard when nothing has been submitted yet.
  useEffect(() => {
    const pollId = setInterval(() => {
      if (paramsRef.current) fetchLevels(paramsRef.current, { silent: true });
    }, POLL_MS);
    return () => clearInterval(pollId);
  }, []);

  const changeSegment = (e) => {
    setSegment(e.target.value);
    setSymbol(""); setExpiry(""); setStrike(""); setExpiryOptions([]); setStrikeOptions([]); setResult(null);
    paramsRef.current = null;
  };

  const selectSymbol = async (s) => {
    setSymbol(s);
    setExpiry(""); setStrike(""); setExpiryOptions([]); setStrikeOptions([]); setResult(null);
    paramsRef.current = null;
    if (!s || segment === "NSE") return;
    try {
      const { data } = await axios.get(`${API}/exitline/instruments`, { params: { segment, symbol: s } });
      setExpiryOptions(data.expiries || []);
    } catch {
      setExpiryOptions([]);
    }
  };

  const changeExpiry = async (e) => {
    const exp = e.target.value;
    setExpiry(exp);
    setStrike(""); setStrikeOptions([]); setResult(null);
    paramsRef.current = null;
    if (!exp || segment !== "OPT") return;
    try {
      const { data } = await axios.get(`${API}/exitline/instruments`, { params: { segment, symbol, expiry: exp } });
      setStrikeOptions(data.strikes || []);
    } catch {
      setStrikeOptions([]);
    }
  };

  const canSubmit =
    symbol.trim() &&
    (segment === "NSE" || (segment === "FUT" && expiry) || (segment === "OPT" && expiry && strike && optionType));

  const submit = async (e) => {
    e.preventDefault();
    if (!canSubmit) return;
    const params = {
      segment,
      symbol: symbol.trim(),
      ...(segment !== "NSE" ? { expiry } : {}),
      ...(segment === "OPT" ? { strike, option_type: optionType } : {}),
      interval: chartInterval,
    };
    paramsRef.current = params;
    await fetchLevels(params);
  };

  const changeInterval = (iv) => {
    setChartInterval(iv);
    if (!paramsRef.current) return;
    const params = { ...paramsRef.current, interval: iv };
    paramsRef.current = params;
    fetchLevels(params, { silent: true }); // swap the chart in place, no full-page loading flash
  };

  return (
    <div data-testid="exitline-tool">
      <form onSubmit={submit} className="glass rounded-2xl border border-white/10 p-5 md:p-6 mb-6">
        <p className="font-mono-ui text-[10px] uppercase tracking-[0.24em] text-sapphire-light mb-4 pb-4 border-b border-white/10 flex items-center gap-2">
          <Crosshair size={13} /> Exitline Levels + SL/TP
        </p>
        <div className="grid grid-cols-2 md:grid-cols-5 gap-4 items-end">
          <div>
            <label className={label}>Segment</label>
            <select value={segment} onChange={changeSegment} style={{ colorScheme: "dark" }} className={selectCls} data-testid="exitline-segment">
              {SEGMENTS.map((s) => <option key={s.key} value={s.key} className="bg-surface">{s.label}</option>)}
            </select>
          </div>

          <SymbolPicker segment={segment} symbol={symbol} onSelect={selectSymbol} />

          {segment !== "NSE" && (
            <div>
              <label className={label}>Expiry</label>
              <select value={expiry} onChange={changeExpiry} style={{ colorScheme: "dark" }} className={selectCls} data-testid="exitline-expiry" disabled={!symbol}>
                <option value="" className="bg-surface">Select…</option>
                {expiryOptions.map((e) => <option key={e} value={e} className="bg-surface">{fmtDate(e)}</option>)}
              </select>
            </div>
          )}

          {segment === "OPT" && (
            <>
              <div>
                <label className={label}>Strike</label>
                <select value={strike} onChange={(e) => { setStrike(e.target.value); setResult(null); paramsRef.current = null; }} style={{ colorScheme: "dark" }} className={selectCls} data-testid="exitline-strike" disabled={!expiry}>
                  <option value="" className="bg-surface">Select…</option>
                  {strikeOptions.map((s) => <option key={s} value={s} className="bg-surface">{s}</option>)}
                </select>
              </div>
              <div>
                <label className={label}>Type</label>
                <select value={optionType} onChange={(e) => { setOptionType(e.target.value); setResult(null); paramsRef.current = null; }} style={{ colorScheme: "dark" }} className={selectCls} data-testid="exitline-option-type">
                  <option value="CE" className="bg-surface">CE</option>
                  <option value="PE" className="bg-surface">PE</option>
                </select>
              </div>
            </>
          )}

          <button type="submit" disabled={loading || !canSubmit} className="btn-sapphire disabled:opacity-50 h-[42px]" data-testid="exitline-submit">
            {loading ? <><Loader2 size={16} className="animate-spin" /> Fetching</> : "Get Levels"}
          </button>
        </div>
      </form>

      {loading && <LoadingParticles title="Computing Levels" subtitle="Fetching prior session H/L/C · Live LTP · Level ladder" />}
      {!loading && result && result.found === false && <EmptyState reason={result.reason} />}
      {!loading && result && result.found !== false && (
        <ExitlineResults result={result} interval={chartInterval} onIntervalChange={changeInterval} />
      )}
    </div>
  );
};

export default ExitlineTool;
