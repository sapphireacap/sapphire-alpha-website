import { useState, useEffect, useRef } from "react";
import axios from "axios";
import { toast } from "sonner";
import { Loader2, Crosshair } from "lucide-react";
import {
  ComposedChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, ReferenceLine,
} from "recharts";
import { field, selectCls, label, LoadingParticles, EmptyState } from "./QuantLab";

const POLL_MS = 30000; // keep the intraday chart/LTP live while results are showing

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

const ZONE_TONE = {
  breakout_upper: "text-emerald-400 border-emerald-400/30 bg-emerald-400/10",
  breakout_lower: "text-red-400 border-red-400/30 bg-red-400/10",
  trading_upper: "text-orange-300 border-orange-300/30 bg-orange-300/10",
  trading_lower: "text-sky-300 border-sky-300/30 bg-sky-300/10",
  trading_mid: "text-slate-300 border-white/15 bg-white/5",
};

const BIAS_TONE = {
  Long: "text-emerald-400",
  Short: "text-red-400",
  Neutral: "text-slate-400",
};

const LEVEL_COLORS = {
  H5: "#34D399", H4: "#34D399", H3: "#34D399", H2: "#6EE7B7", H1: "#A7F3D0",
  Pivot: "#94A3B8",
  L1: "#FECACA", L2: "#FCA5A5", L3: "#F87171", L4: "#F87171", L5: "#F87171",
};

// H1/H2/H5/L1/L2/L5 sit close together and to Pivot on most instruments —
// labeling all 11 lines collides on the chart. The signal-relevant ones
// (H4/H3/L3/L4 boundaries + Pivot) get a text label; the rest still draw as
// dashed reference lines, just unlabeled — full values are in the ladder.
const LABELED_LEVELS = new Set(["H4", "H3", "Pivot", "L3", "L4"]);

const Candle = (props) => {
  const { x, y, width, height, payload } = props;
  const { open, close, high, low } = payload;
  if (high === low || height <= 0) return null;
  const isUp = close >= open;
  const color = isUp ? "#34D399" : "#F87171";
  const scale = height / (high - low);
  const bodyTop = y + (high - Math.max(open, close)) * scale;
  const bodyHeight = Math.max(1, Math.abs(open - close) * scale);
  return (
    <g>
      <line x1={x + width / 2} y1={y} x2={x + width / 2} y2={y + height} stroke={color} strokeWidth={1} />
      <rect x={x + width * 0.2} y={bodyTop} width={width * 0.6} height={bodyHeight} fill={color} />
    </g>
  );
};

const ChartTooltip = ({ active, payload, label: t }) => {
  if (!active || !payload || !payload.length) return null;
  const p = payload[0].payload;
  return (
    <div className="glass rounded-md border border-white/10 px-3 py-2 text-xs">
      <p className="text-slate-500 mb-1 font-mono-ui">{t}</p>
      <p className="text-slate-200 font-mono-ui">O {fmtNum(p.open)} · H {fmtNum(p.high)} · L {fmtNum(p.low)} · C {fmtNum(p.close)}</p>
    </div>
  );
};

const ExitlineChart = ({ chart, levels, ltp }) => {
  if (!chart || chart.length === 0) {
    return (
      <div className="glass rounded-2xl border border-white/10 p-6 mb-6 text-center" data-testid="exitline-chart-empty">
        <p className="text-xs text-slate-500">No intraday bars yet for this session.</p>
      </div>
    );
  }
  const allValues = [...chart.flatMap((b) => [b.high, b.low]), ...Object.values(levels), ltp];
  const domain = [Math.min(...allValues) * 0.998, Math.max(...allValues) * 1.002];

  return (
    <div className="glass rounded-2xl border border-white/10 p-4 md:p-6 mb-6" data-testid="exitline-chart">
      <p className="font-mono-ui text-[10px] uppercase tracking-[0.18em] text-slate-500 mb-3">Today's Session — 5 Min · Live</p>
      <div className="h-96">
        <ResponsiveContainer width="100%" height="100%">
          <ComposedChart data={chart} margin={{ top: 5, right: 44, left: 0, bottom: 0 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.06)" vertical={false} />
            <XAxis dataKey="t" tick={{ fill: "#64748B", fontSize: 10 }} axisLine={{ stroke: "rgba(255,255,255,0.1)" }} tickLine={false} minTickGap={40} />
            <YAxis
              domain={domain}
              tick={{ fill: "#64748B", fontSize: 11 }}
              axisLine={false}
              tickLine={false}
              width={64}
              orientation="right"
              tickFormatter={(v) => Number(v).toFixed(2)}
            />
            <Tooltip content={<ChartTooltip />} />
            <Bar dataKey={(d) => [d.low, d.high]} shape={<Candle />} isAnimationActive={false} />
            {Object.entries(levels).map(([k, v]) => (
              <ReferenceLine
                key={k} y={v} stroke={LEVEL_COLORS[k] || "#64748B"} strokeDasharray="3 3" strokeOpacity={0.65}
                label={LABELED_LEVELS.has(k) ? { value: k, position: "right", fill: LEVEL_COLORS[k] || "#64748B", fontSize: 10 } : undefined}
              />
            ))}
            <ReferenceLine
              y={ltp} stroke="#437EEB" strokeWidth={1.5}
              label={{ value: "LTP", position: "right", fill: "#437EEB", fontSize: 10, fontWeight: 700 }}
            />
          </ComposedChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
};

const Ladder = ({ levels, ltp }) => {
  const rows = [
    ...Object.entries(levels).map(([k, v]) => ({ key: k, value: v, isLtp: false })),
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

const ExitlineResults = ({ result }) => (
  <div data-testid="exitline-results">
    <div className="flex flex-wrap items-center justify-between gap-3 mb-4">
      <div>
        <p className="font-display text-xl font-bold text-white">{result.tradingsymbol}</p>
        <p className="font-mono-ui text-[10px] uppercase tracking-[0.18em] text-slate-500 mt-1">
          Prev session ({fmtDate(result.prev_date)}) — H ₹{fmtNum(result.high)} · L ₹{fmtNum(result.low)} · C ₹{fmtNum(result.close)}
        </p>
      </div>
      <span className={`inline-flex rounded-full border px-3 py-1 font-mono-ui text-[10px] uppercase tracking-wider ${ZONE_TONE[result.zone] || "text-slate-300 border-white/15"}`}>
        {result.zone_label}
      </span>
    </div>

    <ExitlineChart chart={result.chart} levels={result.levels} ltp={result.ltp} />

    <div className="grid md:grid-cols-[1fr,1.2fr] gap-4 mb-6">
      <Ladder levels={result.levels} ltp={result.ltp} />

      <div className="glass rounded-2xl border border-white/10 p-5 md:p-6 flex flex-col gap-4">
        <div>
          <p className={`font-mono-ui text-[10px] uppercase tracking-[0.18em] mb-1 ${BIAS_TONE[result.bias] || "text-slate-400"}`}>Bias</p>
          <p className={`font-display text-2xl font-bold ${BIAS_TONE[result.bias] || "text-white"}`}>{result.bias}</p>
        </div>
        <div className="grid grid-cols-2 gap-4">
          <div>
            <p className="font-mono-ui text-[10px] uppercase tracking-[0.18em] text-slate-500 mb-1">Stop Loss</p>
            <p className="font-mono-ui text-lg font-bold text-red-400">
              {result.sl != null ? `₹${fmtNum(result.sl)}` : result.trail_stop ? "Trail" : "—"}
            </p>
          </div>
          <div>
            <p className="font-mono-ui text-[10px] uppercase tracking-[0.18em] text-slate-500 mb-1">Take Profit</p>
            <p className="font-mono-ui text-lg font-bold text-emerald-400">
              {result.tp != null ? `₹${fmtNum(result.tp)}` : "—"}
              {result.tp_alt != null && <span className="text-slate-500 text-sm font-normal"> (ext. ₹{fmtNum(result.tp_alt)})</span>}
            </p>
          </div>
        </div>
        {result.trail_stop && (
          <p className="font-mono-ui text-[10px] uppercase tracking-[0.14em] text-amber-300">Breakout — no fixed target, trail the stop</p>
        )}
        <p className="text-sm text-slate-300 leading-relaxed border-t border-white/10 pt-4">{result.reason}</p>
        {result.commentary && (
          <p className="text-xs text-slate-500 leading-relaxed">{result.commentary}</p>
        )}
      </div>
    </div>

    <p className="text-[11px] font-light text-slate-600 max-w-2xl">
      These levels are fixed for the trading day, computed from the previous session's H/L/C. SL/TP are rule-based suggestions, not guaranteed outcomes — always size and manage risk independently. Not investment advice.
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
    const interval = setInterval(() => {
      if (paramsRef.current) fetchLevels(paramsRef.current, { silent: true });
    }, POLL_MS);
    return () => clearInterval(interval);
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
    };
    paramsRef.current = params;
    await fetchLevels(params);
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
      {!loading && result && result.found !== false && <ExitlineResults result={result} />}
    </div>
  );
};

export default ExitlineTool;
