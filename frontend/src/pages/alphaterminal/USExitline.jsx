import { useState, useEffect, useRef } from "react";
import axios from "axios";
import { Loader2, Search } from "lucide-react";
import { createChart, CandlestickSeries, LineSeries, LineType, ColorType, LineStyle } from "lightweight-charts";
import { field, label as fieldLabel, EmptyState } from "./QuantLab";

const POLL_MS = 30000; // keep the LTP/chart live while results are showing, same as NSE Exitline

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;
const SURFACE = "rounded-2xl border border-white/10 bg-[#0A0D18]";

const fmtNum = (v, dp = 2) => (v == null ? "—" : Number(v).toFixed(dp));

// alpaca_client labels each bar's "ts" in real US/Eastern wall-clock time,
// then us_exitline.py's _label_bars encodes those digits directly as a
// fake-UTC epoch (dt.replace(tzinfo=utc).timestamp()) rather than doing a
// real timezone conversion -- verified live, 2026-08-10 (AAPL 5m chart: a
// bar's server-computed "t":"08:05" label matches getUTCHours/Min() of its
// own "time" epoch exactly, zero offset). That's the opposite of NSE
// Exitline's real IST->UTC conversion, which is why that file's formatter
// adds an IST offset before reading UTC getters and this one must not --
// doing so here would shift every US session time by 5.5h.
const formatEtHm = (time) => {
  const d = new Date(time * 1000);
  return `${String(d.getUTCHours()).padStart(2, "0")}:${String(d.getUTCMinutes()).padStart(2, "0")}`;
};

// Backend computes the full Camarilla-style level set (H1-H5/Pivot/L1-L5)
// but only these are shown -- same "Sapphire Levels" abstraction and
// visible subset as NSE Exitline, just keeping L5 (already shown in this
// module's ladder before charts existed) instead of dropping it.
const VISIBLE_LEVELS = ["H5", "H4", "H3", "Pivot", "L3", "L4", "L5"];
const LEVEL_COLORS = {
  H5: "#F87171", H4: "#F87171", H3: "#F87171",
  Pivot: "#22D3EE",
  L3: "#34D399", L4: "#34D399", L5: "#34D399",
};
const DISPLAY_LABELS = { H5: "S5", H4: "S4", H3: "S3", Pivot: "PZ", L3: "V3", L4: "V4", L5: "V5" };

const INTERVALS = [
  { key: 1, label: "1m" },
  { key: 5, label: "5m" },
  { key: 15, label: "15m" },
  { key: 30, label: "30m" },
  { key: 60, label: "1h" },
];

// Each session has its OWN level ladder (computed from THAT session's own
// previous-day H/L/C) -- see Exitline.jsx's TVChart for the fuller
// commentary on why each level is its own stepped LineSeries (not a flat
// createPriceLine spanning the whole 30-session window) and why the
// autoscale range is extended across every session's levels, not just the
// active one.
const buildLevelSeriesData = (chart, sessionsByDate, key) => {
  const out = [];
  for (const b of chart) {
    if (b.time == null) continue;
    const session = sessionsByDate[b.date];
    const value = session?.levels?.[key];
    if (value == null) continue;
    out.push({ time: b.time, value });
  }
  return out;
};

const TVChart = ({ chart, sessions, ltp, interval, onIntervalChange, fetchGen }) => {
  const containerRef = useRef(null);
  const chartRef = useRef(null);
  const seriesRef = useRef(null);
  const priceLinesRef = useRef([]);
  const levelSeriesRef = useRef({});
  const fitKeyRef = useRef(null);

  useEffect(() => {
    if (!containerRef.current) return undefined;
    const tvChart = createChart(containerRef.current, {
      layout: { background: { type: ColorType.Solid, color: "transparent" }, textColor: "#94A3B8" },
      grid: { vertLines: { visible: false }, horzLines: { visible: false } },
      localization: { timeFormatter: formatEtHm },
      timeScale: {
        timeVisible: true, secondsVisible: false, borderColor: "rgba(255,255,255,0.1)",
        tickMarkFormatter: formatEtHm,
      },
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
      priceLineVisible: false,
      lastValueVisible: false,
    });
    chartRef.current = tvChart;
    seriesRef.current = series;

    return () => {
      Object.values(levelSeriesRef.current).forEach((s) => { try { tvChart.removeSeries(s); } catch { /* already gone with the chart */ } });
      levelSeriesRef.current = {};
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

    const cleanChart = chart.filter((b) => b.time != null);
    series.setData(cleanChart.map((b) => ({
      time: b.time, open: b.open, high: b.high, low: b.low, close: b.close,
    })));

    series.applyOptions({
      autoscaleInfoProvider: (original) => {
        const res = original();
        const values = (sessions || []).flatMap((s) => VISIBLE_LEVELS.map((k) => s.levels?.[k])).filter((v) => v != null);
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

    const sessionsByDate = Object.fromEntries((sessions || []).map((s) => [s.date, s]));
    VISIBLE_LEVELS.forEach((k) => {
      let lineSeries = levelSeriesRef.current[k];
      if (!lineSeries) {
        lineSeries = tvChart.addSeries(LineSeries, {
          color: LEVEL_COLORS[k] || "#64748B", lineWidth: 1, lineType: LineType.WithSteps,
          lastValueVisible: true, priceLineVisible: false, crosshairMarkerVisible: false,
          title: DISPLAY_LABELS[k] || k,
        });
        levelSeriesRef.current[k] = lineSeries;
      }
      lineSeries.setData(buildLevelSeriesData(cleanChart, sessionsByDate, k));
    });

    if (ltp != null) {
      priceLinesRef.current.push(series.createPriceLine({
        price: ltp, color: "#437EEB", lineWidth: 2,
        lineStyle: LineStyle.Solid, axisLabelVisible: true, title: "PX",
      }));
    }

    if (fetchGen != null && fitKeyRef.current !== fetchGen) {
      fitKeyRef.current = fetchGen;
      series.priceScale().applyOptions({ autoScale: true });
      // Default view is just the ACTIVE (most recent) session -- the other
      // 29 are real data, scrolled out of view to the left (handleScroll
      // is on) rather than absent, same as NSE Exitline.
      const activeDate = sessions?.[sessions.length - 1]?.date;
      const activeBars = activeDate ? cleanChart.filter((b) => b.date === activeDate) : cleanChart;
      const sessionStart = activeBars[0]?.time;
      const lastBar = activeBars[activeBars.length - 1]?.time;
      if (sessionStart != null && lastBar != null) {
        const nowTs = Math.floor(Date.now() / 1000);
        tvChart.timeScale().setVisibleRange({ from: sessionStart, to: Math.max(lastBar + interval * 60, nowTs) });
      } else {
        tvChart.timeScale().fitContent();
      }
    }
  }, [chart, sessions, ltp, interval, fetchGen]);

  const isEmpty = !chart || chart.length === 0;

  return (
    <div className={`${SURFACE} p-4 md:p-6 mb-5`} data-testid="us-exitline-chart">
      <div className="flex flex-wrap items-center justify-between gap-3 mb-3">
        <p className="font-mono-ui text-[10px] uppercase tracking-[0.18em] text-slate-500">
          Last {sessions?.length || 30} Sessions <span className="text-slate-600 normal-case tracking-normal">· scroll to view history</span>
        </p>
        <div className="flex items-center gap-1 rounded-md border border-white/10 p-0.5" data-testid="us-exitline-interval-selector">
          {INTERVALS.map((iv) => (
            <button
              key={iv.key}
              type="button"
              onClick={() => onIntervalChange(iv.key)}
              data-testid={`us-exitline-interval-${iv.key}`}
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
          <div className="absolute inset-0 flex items-center justify-center z-10" data-testid="us-exitline-chart-empty">
            <p className="text-xs text-slate-500">No intraday bars available right now.</p>
          </div>
        )}
        <div ref={containerRef} className="h-96" style={{ touchAction: "none" }} data-lenis-prevent-wheel="true" data-testid="us-exitline-tv-chart" />
      </div>
    </div>
  );
};

const SymbolPicker = ({ onSelect, placeholder = "Search symbol… e.g. AAPL" }) => {
  const [query, setQuery] = useState("");
  const [options, setOptions] = useState([]);
  const [open, setOpen] = useState(false);
  const debounceRef = useRef(null);

  const onChange = (e) => {
    const v = e.target.value;
    setQuery(v);
    if (debounceRef.current) clearTimeout(debounceRef.current);
    if (v.trim().length < 1) { setOptions([]); setOpen(false); return; }
    debounceRef.current = setTimeout(async () => {
      try {
        const { data } = await axios.get(`${API}/us-markets/symbols/search`, { params: { q: v.trim() } });
        setOptions(data || []);
        setOpen(true);
      } catch { setOptions([]); }
    }, 250);
  };

  const pick = (s) => { setQuery(s.symbol); setOpen(false); onSelect(s.symbol); };

  return (
    <div className="relative max-w-md">
      <label className={fieldLabel}>Symbol</label>
      <div className="relative">
        <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-slate-500" />
        <input
          value={query} onChange={onChange}
          onFocus={() => options.length > 0 && setOpen(true)}
          onBlur={() => setTimeout(() => setOpen(false), 150)}
          className={field + " pl-9"} placeholder={placeholder} autoComplete="off"
          data-testid="us-markets-symbol-input"
        />
      </div>
      {open && options.length > 0 && (
        <div className="absolute z-20 mt-1 w-full max-h-56 overflow-y-auto glass rounded-md border border-white/10 shadow-xl" data-testid="us-markets-symbol-dropdown">
          {options.map((s) => (
            <button type="button" key={s.symbol} onClick={() => pick(s)} className="block w-full text-left px-3 py-2 text-sm text-slate-200 hover:bg-white/10 transition-colors">
              <span className="font-mono-ui">{s.symbol}</span>
              {s.company_name && <span className="text-slate-500"> — {s.company_name}</span>}
            </button>
          ))}
        </div>
      )}
    </div>
  );
};

const USExitlineTool = () => {
  const [symbol, setSymbol] = useState("");
  const [result, setResult] = useState(null);
  const [loading, setLoading] = useState(false);
  const [interval, setInterval_] = useState(5);
  const genRef = useRef(0);
  const paramsRef = useRef(null);

  const fetchLevels = async (params, { silent, gen } = {}) => {
    if (!silent) { setLoading(true); setResult(null); }
    try {
      const { data } = await axios.get(`${API}/us-markets/exitline`, { params });
      setResult((prev) => ({ ...data, __fetchGen: gen !== undefined ? gen : prev?.__fetchGen }));
    } catch {
      if (!silent) setResult({ error: true });
      // a silent background refresh failing just keeps showing the last good result
    } finally {
      if (!silent) setLoading(false);
    }
  };

  // Keeps the chart/LTP live while a result is on screen, same as NSE Exitline.
  useEffect(() => {
    const pollId = window.setInterval(() => {
      if (paramsRef.current) fetchLevels(paramsRef.current, { silent: true });
    }, POLL_MS);
    return () => window.clearInterval(pollId);
  }, []);

  const runScan = async (sym) => {
    setSymbol(sym);
    const params = { symbol: sym, interval };
    paramsRef.current = params;
    genRef.current += 1;
    await fetchLevels(params, { gen: genRef.current });
  };

  const changeInterval = (iv) => {
    setInterval_(iv);
    if (!paramsRef.current) return;
    const params = { ...paramsRef.current, interval: iv };
    paramsRef.current = params;
    genRef.current += 1;
    fetchLevels(params, { silent: true, gen: genRef.current }); // swap the chart in place, no full-page loading flash
  };

  return (
    <div data-testid="us-exitline-module">
      <div className="mb-6"><SymbolPicker onSelect={runScan} /></div>

      {!symbol && !loading && <EmptyState reason="Search for a US stock above to run its Exitline levels." />}
      {loading && (
        <div className="h-48 flex items-center justify-center text-slate-500 font-mono-ui text-sm gap-3"><Loader2 className="animate-spin" size={16} /> Loading levels…</div>
      )}
      {!loading && result?.error && <EmptyState reason={`Could not load levels for ${symbol} right now.`} />}

      {!loading && result && !result.error && (
        <>
          <div className={`${SURFACE} p-5 md:p-6 mb-5 ${result.bias === "Long" ? "border-emerald-400/25 bg-emerald-400/[0.04]" : result.bias === "Short" ? "border-red-400/25 bg-red-400/[0.04]" : ""}`} data-testid="us-exitline-signal-card">
            <div className="flex flex-wrap items-center justify-between gap-3 mb-3">
              <span className="text-lg font-bold text-white">{result.symbol} — {result.zone_label}</span>
              <span className={`font-mono-ui text-xs font-bold uppercase tracking-wider px-3 py-1 rounded-full border ${
                result.bias === "Long" ? "border-emerald-400/30 text-emerald-300" : result.bias === "Short" ? "border-red-400/30 text-red-300" : "border-white/15 text-slate-400"
              }`}>{result.bias}</span>
            </div>
            <p className="text-sm text-slate-300 leading-relaxed mb-4">{result.reason}{result.commentary ? ` ${result.commentary}` : ""}</p>
            <div className="grid grid-cols-3 gap-4">
              <div><p className="font-mono-ui text-[10px] uppercase tracking-wider text-slate-500 mb-1">Live Price</p><p className="font-mono-ui text-sm text-white font-bold">{result.ltp != null ? `$${fmtNum(result.ltp)}` : "—"}</p></div>
              <div><p className="font-mono-ui text-[10px] uppercase tracking-wider text-slate-500 mb-1">Suggested SL</p><p className="font-mono-ui text-sm text-red-400">{result.sl != null ? `$${fmtNum(result.sl)}` : "—"}</p></div>
              <div><p className="font-mono-ui text-[10px] uppercase tracking-wider text-slate-500 mb-1">{result.trail_stop ? "Target" : "Suggested TP"}</p><p className="font-mono-ui text-sm text-emerald-400">{result.trail_stop ? "Trail Stop" : result.tp != null ? `$${fmtNum(result.tp)}` : "—"}</p></div>
            </div>
          </div>

          <TVChart chart={result.chart} sessions={result.sessions} ltp={result.ltp} interval={interval} onIntervalChange={changeInterval} fetchGen={result.__fetchGen} />

          <div className={`${SURFACE} overflow-hidden`} data-testid="us-exitline-ladder">
            <div className="px-5 py-3 border-b border-white/10"><p className="font-mono-ui text-[10px] uppercase tracking-[0.24em] text-slate-400">Level Ladder</p></div>
            <div className="overflow-x-auto">
              <table className="w-full min-w-[360px]" style={{ fontVariantNumeric: "tabular-nums" }}>
                <tbody>
                  {[...Object.entries(result.levels || {}).filter(([k]) => VISIBLE_LEVELS.includes(k)), ["LTP", result.ltp]]
                    .sort((a, b) => (b[1] ?? -Infinity) - (a[1] ?? -Infinity))
                    .map(([k, v]) => (
                      <tr key={k} className={`border-b border-white/[0.05] last:border-0 ${k === "LTP" ? "bg-sapphire-light/15" : ""}`}>
                        <td className="px-5 py-3 font-mono-ui text-xs uppercase tracking-[0.14em] text-slate-400">{k === "LTP" ? "◆ Live Price" : (DISPLAY_LABELS[k] || k)}</td>
                        <td className="px-5 py-3 text-right font-mono-ui text-sm text-slate-200">{v != null ? `$${fmtNum(v)}` : "—"}</td>
                      </tr>
                    ))}
                </tbody>
              </table>
            </div>
          </div>

        </>
      )}
    </div>
  );
};

export default USExitlineTool;
