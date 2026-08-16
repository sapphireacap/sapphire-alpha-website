import { useState, useEffect, useRef } from "react";
import axios from "axios";
import { toast } from "sonner";
import { Loader2, Crosshair } from "lucide-react";
import { createChart, CandlestickSeries, LineSeries, LineType, ColorType } from "lightweight-charts";
import SessionDividers from "./ChartSessionDividers";
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

// lightweight-charts reads UTC getters off the Date it builds from a time
// value (getUTCHours etc.) regardless of the browser's own timezone, so an
// IST-correct epoch (which is what the backend sends) would otherwise
// render as raw UTC on the axis/crosshair — 5.5h behind. Shift the display
// copy by the IST offset so the UTC getters read back IST wall-clock digits;
// the underlying series/range data (used for session-window math) is untouched.
const IST_OFFSET_MS = 5.5 * 60 * 60 * 1000;
const formatIstHm = (time) => {
  const d = new Date(time * 1000 + IST_OFFSET_MS);
  return `${String(d.getUTCHours()).padStart(2, "0")}:${String(d.getUTCMinutes()).padStart(2, "0")}`;
};

// Backend still computes all 11 levels (H1/H2/L1/L2 feed the mid-range
// commentary text used elsewhere) but only these seven are ever shown
// here — H1/H2/L1/L2 stay dropped from display, per original request; L5
// was re-added (2026-08-10) to match the reference chart, which shows the
// full H5-H4-H3-Pivot-L3-L4-L5 ladder.
const VISIBLE_LEVELS = ["H5", "H4", "H3", "Pivot", "L3", "L4", "L5"];

// The CHART draws every level except Pivot/PZ (2026-08-12, by request:
// "completely remove the pz name and line from the chart"). Scoped to the
// chart deliberately -- VISIBLE_LEVELS still drives the Sapphire Levels
// ladder table below it, which continues to list PZ and its price.
const CHART_LEVELS = VISIBLE_LEVELS.filter((k) => k !== "Pivot");

// Matches the reference: all H-levels red (resistance overhead), Pivot
// cyan, all L-levels green (support below) — not a per-level gradient.
const LEVEL_COLORS = {
  H5: "#F87171", H4: "#F87171", H3: "#F87171",
  Pivot: "#22D3EE",
  L3: "#34D399", L4: "#34D399", L5: "#34D399",
};

// "Sapphire Levels" branding — internal keys (H5/H4/H3/Pivot/L3/L4/L5/LTP)
// stay as-is everywhere else (backend field names, color/row-style
// lookups); only the DISPLAYED label changes, so a generic H/L/Pivot
// naming convention isn't shown to users.
const DISPLAY_LABELS = { H5: "S5", H4: "S4", H3: "S3", Pivot: "PZ", L3: "V3", L4: "V4", L5: "V5" };

// Full names paired with each code in the ladder table, matching the
// "Sapphire Levels" reference card (Sentinel/Vault/Pivot Zone/Price Nexus).
const FULL_NAMES = {
  H5: "Sentinel 5", H4: "Sentinel 4", H3: "Sentinel 3",
  Pivot: "Pivot Zone",
  L3: "Vault 3", L4: "Vault 4", L5: "Vault 5",
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
//
// Each session in `sessions` has its OWN level ladder (computed from THAT
// session's own previous-day H/L/C — never the same day to day), so a
// flat createPriceLine() spanning the whole 30-day chart would be wrong
// the moment a level actually changes between sessions. Each level is
// instead its own LineSeries with one point per candle (value = that
// candle's OWN session's level) and lineType: WithSteps — consecutive
// bars within a session share the same value (a flat segment); the jump
// at a session boundary renders as a clean vertical step instead of a
// diagonal interpolation, matching a real multi-session reference chart.
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

// No `ltp` prop: the chart no longer draws a live-price ("PX") line at
// all (2026-08-12, by request), so it has nothing to do with the live
// price. The Ladder below still takes `ltp` and still shows it.
const TVChart = ({ chart, sessions, interval, onIntervalChange, fetchGen }) => {
  const containerRef = useRef(null);
  const chartRef = useRef(null);
  const seriesRef = useRef(null);
  const levelSeriesRef = useRef({});
  const fitKeyRef = useRef(null); // re-fit the view on symbol/interval change, but not on a live-poll refresh (so a manual zoom/scroll sticks)

  useEffect(() => {
    if (!containerRef.current) return undefined;
    const tvChart = createChart(containerRef.current, {
      layout: { background: { type: ColorType.Solid, color: "transparent" }, textColor: "#94A3B8" },
      grid: { vertLines: { visible: false }, horzLines: { visible: false } },
      localization: { timeFormatter: formatIstHm },
      timeScale: {
        timeVisible: true, secondsVisible: false, borderColor: "rgba(255,255,255,0.1)",
        tickMarkFormatter: formatIstHm,
      },
      rightPriceScale: { borderColor: "rgba(255,255,255,0.1)" },
      handleScale: {
        mouseWheel: true, pinch: true,
        axisPressedMouseMove: { time: true, price: true },
      },
      // mouseWheel: false here (not true) -- handleScale.mouseWheel above
      // already claims the wheel for zoom, same as real TradingView.com
      // (scroll = zoom, drag = pan). Having both true fought over the same
      // wheel event, panning AND zooming on every tick, which read as
      // "zoom doesn't work" even though it was technically firing.
      handleScroll: { mouseWheel: false, pressedMouseMove: true, horzTouchDrag: true, vertTouchDrag: true },
      autoSize: true,
    });
    const series = tvChart.addSeries(CandlestickSeries, {
      upColor: "#34D399", downColor: "#F87171", borderVisible: false,
      wickUpColor: "#34D399", wickDownColor: "#F87171",
      // Both off so the chart carries NO live-price marker at all: the
      // explicit "PX" price line these originally deduplicated against was
      // removed 2026-08-12 by request, and re-enabling either of these
      // would just put an equivalent line/label straight back. The live
      // price is still shown in the Sapphire Levels ladder below.
      priceLineVisible: false,
      lastValueVisible: false,
    });
    chartRef.current = tvChart;
    seriesRef.current = series;

    // Belt-and-suspenders on top of data-lenis-prevent below: Lenis's own
    // wheel listener sits on window/document, an ancestor of this
    // container -- stopping propagation here (bubble phase, so it runs
    // AFTER the chart library's own listener on its inner canvas has
    // already handled the zoom) guarantees Lenis never sees the event at
    // all, regardless of whether its own data-attribute opt-out is being
    // respected correctly in whatever Lenis version is actually loaded.
    // passive:true is fine -- stopPropagation doesn't need preventDefault
    // rights, and the chart library's own listener still calls
    // preventDefault() itself, non-passively, on its own element.
    const container = containerRef.current;
    const stopWheelPropagation = (e) => e.stopPropagation();
    container.addEventListener("wheel", stopWheelPropagation, { passive: true });

    return () => {
      container.removeEventListener("wheel", stopWheelPropagation);
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

    const cleanChart = chart.filter((b) => b.time != null);
    series.setData(cleanChart.map((b) => ({
      time: b.time, open: b.open, high: b.high, low: b.low, close: b.close,
    })));

    // No autoscaleInfoProvider on the CANDLE series on purpose: the candles
    // alone define the price range, so they always fill the pane the way
    // tradingview.com's do. The level series opt OUT of autoscale instead
    // (see their own comment below) -- an older version did the reverse,
    // forcing the range to span every session's levels, which is why the
    // price axis never squeezed no matter how far the time axis was zoomed.

    // Each level is its own stepped LineSeries spanning the whole window --
    // its value changes at every session boundary (see buildLevelSeriesData)
    // instead of one flat line that would only ever be correct for a single
    // session.
    const sessionsByDate = Object.fromEntries((sessions || []).map((s) => [s.date, s]));
    CHART_LEVELS.forEach((k) => {
      let lineSeries = levelSeriesRef.current[k];
      if (!lineSeries) {
        lineSeries = tvChart.addSeries(LineSeries, {
          color: LEVEL_COLORS[k] || "#64748B", lineWidth: 1, lineType: LineType.WithSteps,
          // No `title` (2026-08-12, by request) -- the price-axis tag now
          // shows only the value, not the S5/S4/V3/... name. The ladder
          // table below still names every level, and the lines stay
          // colour-coded (red above / green below), so nothing is lost.
          lastValueVisible: true, priceLineVisible: false, crosshairMarkerVisible: false,
          // Levels are DRAWN but excluded from the price autoscale (that's
          // what returning null does) -- the candles alone decide the price
          // range, exactly like real tradingview.com, where a horizontal
          // level drawing never stretches the scale. Letting them
          // participate is what kept zoom feeling broken: the ladder spans
          // ~100 points (S5 down to V5, wider still across sessions) while
          // an intraday session's candles span ~25, so autoscale fitted the
          // ladder and the candles stayed a flat squashed band no matter
          // how far the time axis was zoomed. Trade-off, and the same one
          // TradingView makes: levels far from price now sit off-screen
          // until you zoom the price axis out (drag it) or scroll out.
          autoscaleInfoProvider: () => null,
        });
        levelSeriesRef.current[k] = lineSeries;
      }
      lineSeries.setData(buildLevelSeriesData(cleanChart, sessionsByDate, k));
    });

    // Only reset the view (time+price scale) when this data actually
    // belongs to a real user-initiated fetch (submit / interval change) —
    // a background live-poll refresh must never yank a user's manual
    // scroll/zoom back to "fit all". fetchGen (tagged onto `result` by the
    // parent, only on a real fetch) is the only reliable signal for that:
    // chart[0]'s own timestamp can't be used, since every interval's first
    // bucket aligns to the same session-open time regardless of interval
    // width, so it can't tell "new interval's data" apart from "old
    // interval's data" by timestamp alone.
    if (fetchGen != null && fitKeyRef.current !== fetchGen) {
      fitKeyRef.current = fetchGen;
      series.priceScale().applyOptions({ autoScale: true });
      // Default view is just the ACTIVE (most recent) session, same as
      // before this was a 30-day series -- fitContent()/showing the whole
      // window would squash every session into unreadably thin candles.
      // The other 29 sessions are still real data, just scrolled out of
      // view to the left (handleScroll is on) rather than absent.
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
  }, [chart, sessions, interval, fetchGen]);

  const isEmpty = !chart || chart.length === 0;

  return (
    <div className="glass rounded-2xl border border-white/10 p-4 md:p-6 mb-6" data-testid="exitline-chart">
      <div className="flex flex-wrap items-center justify-between gap-3 mb-3">
        <p className="font-mono-ui text-[10px] uppercase tracking-[0.18em] text-slate-500">
          Last {sessions?.length || 30} Sessions <span className="text-slate-600 normal-case tracking-normal">· scroll to view history</span>
        </p>
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
        {/* App-wide Lenis smooth-scroll (SmoothScroll.jsx) reads wheel deltas on its own listener and animates the page regardless of preventDefault() elsewhere — data-lenis-prevent-wheel/data-lenis-prevent are both real Lenis opt-out attributes (confirmed against Lenis's own source, 2026-08-10); using the general one here. */}
        <div ref={containerRef} className="h-96" style={{ touchAction: "none" }} data-lenis-prevent="true" data-testid="exitline-tv-chart" />
        <SessionDividers chartRef={chartRef} bars={chart} redrawKey={`${interval}-${fetchGen}`} />
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
      <div className="px-5 py-3 border-b border-white/10">
        <p className="font-mono-ui text-[10px] uppercase tracking-[0.24em] text-slate-400">Sapphire Levels™</p>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[520px]" style={{ fontVariantNumeric: "tabular-nums" }}>
          <thead>
            <tr className="border-b border-white/10">
              {[["Level", "left"], ["Price", "right"], ["Distance from PX", "right"], ["% Away", "right"]].map(([h, align]) => (
                <th key={h} className={`px-5 py-3 font-mono-ui text-[10px] uppercase tracking-[0.18em] text-slate-500 font-semibold whitespace-nowrap text-${align}`}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => {
              const distance = r.isLtp ? null : r.value - ltp;
              const distPct = r.isLtp ? null : (distance / ltp) * 100;
              const distTone = distance == null ? "text-slate-600" : distance > 0 ? "text-emerald-400" : "text-red-400";
              return (
                <tr
                  key={r.key}
                  data-testid={r.isLtp ? "exitline-ltp-row" : `exitline-level-${r.key}`}
                  className={`border-b border-white/[0.05] last:border-0 ${r.isLtp ? "bg-sapphire-light/15" : ""}`}
                >
                  <td className="px-5 py-3 whitespace-nowrap">
                    <span className={`block font-mono-ui text-xs uppercase tracking-[0.14em] ${r.isLtp ? "text-sapphire-light font-bold" : r.key.startsWith("H") ? "text-emerald-400/80" : r.key.startsWith("L") ? "text-red-400/80" : "text-white"}`}>
                      {r.isLtp ? "◆ PX (Live)" : (DISPLAY_LABELS[r.key] || r.key)}
                    </span>
                    <span className="block text-[11px] text-slate-500 mt-0.5">
                      {r.isLtp ? "Price Nexus" : (FULL_NAMES[r.key] || "")}
                    </span>
                  </td>
                  <td className={`px-5 py-3 text-right font-mono-ui text-sm whitespace-nowrap ${r.isLtp ? "text-white font-bold" : "text-slate-300"}`}>₹{fmtNum(r.value)}</td>
                  <td className={`px-5 py-3 text-right font-mono-ui text-sm whitespace-nowrap ${distTone}`}>
                    {distance == null ? "—" : `${distance >= 0 ? "+" : "−"}₹${fmtNum(Math.abs(distance))}`}
                  </td>
                  <td className={`px-5 py-3 text-right font-mono-ui text-sm whitespace-nowrap ${distTone}`}>
                    {distPct == null ? "—" : `${distPct >= 0 ? "+" : "−"}${Math.abs(distPct).toFixed(2)}%`}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
};

const ExitlineResults = ({ result, interval, onIntervalChange }) => (
  <div data-testid="exitline-results">
    <div className="mb-4">
      <p className="text-xl font-bold text-white">{result.tradingsymbol}</p>
    </div>

    <TVChart chart={result.chart} sessions={result.sessions} interval={interval} onIntervalChange={onIntervalChange} fetchGen={result.__fetchGen} />

    <div className="mb-6">
      <Ladder levels={result.levels} ltp={result.ltp} />
    </div>
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
  const genRef = useRef(0); // bumped on a real user-initiated fetch (submit/interval change), never on a silent poll — see TVChart's fitKey
  const paramsRef = useRef(null); // last-submitted query params, kept alive for the background poll

  // `gen` is only passed for a real user-initiated fetch (submit / interval
  // change) — a plain background poll omits it, so the tag on `result`
  // carries forward from whatever it already was rather than getting
  // clobbered. This is what lets TVChart tell "genuinely new view" apart
  // from "same view, fresher candles" reliably: chart[0]'s own timestamp
  // can't be used for that (every interval's first bucket aligns to the
  // same 09:15 market open, so it's identical across interval switches).
  const fetchLevels = async (params, { silent, gen } = {}) => {
    if (!silent) { setLoading(true); setResult(null); }
    try {
      const { data } = await axios.get(`${API}/exitline/levels`, { params });
      setResult((prev) => ({ ...data, __fetchGen: gen !== undefined ? gen : prev?.__fetchGen }));
    } catch (err) {
      if (!silent) {
        toast.error(err?.response?.data?.detail || "Could not fetch levels. Please try again.");
        setResult({ found: false, reason: err?.response?.data?.detail || "Could not fetch levels for this instrument.", __fetchGen: gen });
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
    genRef.current += 1;
    await fetchLevels(params, { gen: genRef.current });
  };

  const changeInterval = (iv) => {
    setChartInterval(iv);
    if (!paramsRef.current) return;
    const params = { ...paramsRef.current, interval: iv };
    paramsRef.current = params;
    genRef.current += 1;
    fetchLevels(params, { silent: true, gen: genRef.current }); // swap the chart in place, no full-page loading flash
  };

  return (
    <div data-testid="exitline-tool">
      <form onSubmit={submit} className="glass rounded-2xl border border-white/10 p-5 md:p-6 mb-6">
        <p className="font-mono-ui text-[10px] uppercase tracking-[0.24em] text-sapphire-light mb-4 pb-4 border-b border-white/10 flex items-center gap-2">
          <Crosshair size={13} /> Exitline Levels
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

      {loading && <LoadingParticles title="Computing Levels" subtitle="Fetching prior session H/L/C · Live PX · Level ladder" />}
      {!loading && result && result.found === false && <EmptyState reason={result.reason} />}
      {!loading && result && result.found !== false && (
        <ExitlineResults result={result} interval={chartInterval} onIntervalChange={changeInterval} />
      )}
    </div>
  );
};

export default ExitlineTool;
