import { useState, useEffect, useMemo } from "react";
import axios from "axios";
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, ReferenceLine,
  ComposedChart, Bar,
} from "recharts";
import { Loader2 } from "lucide-react";
import { EmptyState } from "./QuantLab";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;
const SURFACE = "rounded-2xl border border-white/10 bg-[#0A0D18]";

const ZOOMS = [
  { key: "3m", label: "3M", days: 90 },
  { key: "6m", label: "6M", days: 182 },
  { key: "ytd", label: "YTD", days: null },
  { key: "1y", label: "1Y", days: 365 },
  { key: "all", label: "All", days: null },
];

const fmtDate = (iso) => {
  if (!iso) return "—";
  const [y, m, d] = iso.split("-");
  return `${d}/${m}/${y}`;
};

const cutoffDate = (zoomKey, dates) => {
  if (!dates.length) return null;
  const lastDate = new Date(dates[dates.length - 1]);
  if (zoomKey === "all") return null;
  if (zoomKey === "ytd") return `${lastDate.getFullYear()}-01-01`;
  const zoom = ZOOMS.find((z) => z.key === zoomKey);
  const cutoff = new Date(lastDate);
  cutoff.setDate(cutoff.getDate() - zoom.days);
  return cutoff.toISOString().slice(0, 10);
};

const StatChip = ({ label, value }) => (
  <div className="flex flex-col">
    <span className="font-mono-ui text-[10px] uppercase tracking-[0.16em] text-slate-500">{label}</span>
    <span className="font-display text-lg font-bold text-white">{value}</span>
  </div>
);

const ZoomTabs = ({ zoom, setZoom }) => (
  <div className="flex items-center gap-1 rounded-md border border-white/10 p-0.5 w-fit" data-testid="breadth-zoom-tabs">
    {ZOOMS.map((z) => (
      <button
        key={z.key}
        type="button"
        onClick={() => setZoom(z.key)}
        data-testid={`breadth-zoom-${z.key}`}
        className={`font-mono-ui text-[10px] uppercase tracking-wider px-3 py-1.5 rounded transition-colors ${
          zoom === z.key ? "bg-sapphire-light/20 text-sapphire-light" : "text-slate-500 hover:text-slate-300"
        }`}
      >
        {z.label}
      </button>
    ))}
  </div>
);

// Recharts has no built-in candlestick — this plots an invisible range Bar
// (dataKey=[low, high], so its own y/height already map the full high-low
// span in pixels) and draws the wick + body ourselves in `shape`, using that
// same y/height to linearly interpolate open/close pixel positions. Standard
// recharts candlestick pattern, not a stock component.
const Candle = ({ x, y, width, height, payload }) => {
  const { open, high, low, close } = payload;
  const bullish = close >= open;
  const color = bullish ? "#3ED598" : "#F87171";
  const range = high - low || 1;
  const bodyTop = y + height * (high - Math.max(open, close)) / range;
  const bodyBottom = y + height * (high - Math.min(open, close)) / range;
  const bodyHeight = Math.max(bodyBottom - bodyTop, 1);
  const wickX = x + width / 2;
  return (
    <g>
      <line x1={wickX} x2={wickX} y1={y} y2={y + height} stroke={color} strokeWidth={1} />
      <rect x={x} y={bodyTop} width={width} height={bodyHeight} fill={color} />
    </g>
  );
};

const IndexChart = ({ candles }) => {
  const domain = useMemo(() => {
    if (!candles.length) return [0, 1];
    const lows = candles.map((c) => c.low);
    const highs = candles.map((c) => c.high);
    const pad = (Math.max(...highs) - Math.min(...lows)) * 0.05;
    return [Math.min(...lows) - pad, Math.max(...highs) + pad];
  }, [candles]);

  return (
    <div className={`${SURFACE} p-4`} style={{ height: 260 }} data-testid="breadth-index-chart">
      <ResponsiveContainer width="100%" height="100%">
        <ComposedChart data={candles} margin={{ top: 10, right: 10, left: 0, bottom: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.06)" vertical={false} />
          <XAxis dataKey="date" tick={{ fill: "#64748B", fontSize: 10 }} axisLine={{ stroke: "rgba(255,255,255,0.1)" }} tickLine={false} minTickGap={60} tickFormatter={fmtDate} />
          <YAxis domain={domain} tick={{ fill: "#64748B", fontSize: 11 }} axisLine={false} tickLine={false} width={52} />
          <Tooltip
            labelFormatter={fmtDate}
            formatter={(v, name) => [v, name]}
            contentStyle={{ background: "#0A0D18", border: "1px solid rgba(255,255,255,0.1)", borderRadius: 8, fontSize: 12 }}
            labelStyle={{ color: "#94A3B8" }}
          />
          <Bar dataKey={(d) => [d.low, d.high]} shape={Candle} isAnimationActive={false} />
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  );
};

const BreadthChart = ({ series }) => (
  <div className={`${SURFACE} p-4`} style={{ height: 260 }} data-testid="breadth-chart">
    <ResponsiveContainer width="100%" height="100%">
      <LineChart data={series} margin={{ top: 10, right: 10, left: 0, bottom: 0 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.06)" vertical={false} />
        <XAxis dataKey="date" tick={{ fill: "#64748B", fontSize: 10 }} axisLine={{ stroke: "rgba(255,255,255,0.1)" }} tickLine={false} minTickGap={60} tickFormatter={fmtDate} />
        <YAxis domain={[0, 100]} tick={{ fill: "#64748B", fontSize: 11 }} axisLine={false} tickLine={false} width={52} />
        <ReferenceLine y={75} stroke="#F59E0B" strokeDasharray="4 4" strokeOpacity={0.5} />
        <ReferenceLine y={50} stroke="rgba(255,255,255,0.15)" strokeDasharray="2 2" />
        <ReferenceLine y={25} stroke="#F59E0B" strokeDasharray="4 4" strokeOpacity={0.5} />
        <Tooltip
          labelFormatter={fmtDate}
          formatter={(v) => [`${v}%`, "Bullish"]}
          contentStyle={{ background: "#0A0D18", border: "1px solid rgba(255,255,255,0.1)", borderRadius: 8, fontSize: 12 }}
          labelStyle={{ color: "#94A3B8" }}
        />
        <Line type="monotone" dataKey="value" stroke="#3ED598" strokeWidth={1.5} dot={false} isAnimationActive={false} />
      </LineChart>
    </ResponsiveContainer>
  </div>
);

const BreadthTool = () => {
  const [groups, setGroups] = useState([]);
  const [group, setGroup] = useState("nifty-50");
  const [zoom, setZoom] = useState("3m");
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);

  useEffect(() => {
    axios.get(`${API}/terminal/breadth/groups`)
      .then(({ data: d }) => setGroups(d.groups))
      .catch(() => {});
  }, []);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(false);
    axios.get(`${API}/terminal/breadth/x-percent`, { params: { group } })
      .then(({ data: d }) => { if (!cancelled) setData(d); })
      .catch(() => { if (!cancelled) setError(true); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [group]);

  const latest = data?.series?.length ? data.series[data.series.length - 1] : null;

  const { visibleSeries, visibleCandles } = useMemo(() => {
    if (!data?.series?.length) return { visibleSeries: [], visibleCandles: [] };
    const dates = data.series.map((p) => p.date);
    const cutoff = cutoffDate(zoom, dates);
    return {
      visibleSeries: cutoff ? data.series.filter((p) => p.date >= cutoff) : data.series,
      visibleCandles: cutoff ? (data.index_candles || []).filter((c) => c.date >= cutoff) : (data.index_candles || []),
    };
  }, [data, zoom]);

  return (
    <div data-testid="breadth-tool">
      <div className="flex flex-wrap items-center gap-2 mb-6" data-testid="breadth-group-selector">
        {groups.map((g) => (
          <button
            key={g.key}
            type="button"
            onClick={() => setGroup(g.key)}
            className={`px-3.5 py-1.5 rounded-full font-mono-ui text-[11px] uppercase tracking-[0.1em] whitespace-nowrap border transition-colors duration-300 ${
              group === g.key ? "border-sapphire-light/50 bg-sapphire/10 text-white" : "border-white/10 text-slate-500 hover:text-slate-300"
            }`}
            data-testid={`breadth-group-${g.key}`}
          >
            {g.label}
          </button>
        ))}
      </div>

      {loading ? (
        <div className="flex items-center justify-center py-20 text-slate-500 font-mono-ui text-sm gap-3">
          <Loader2 className="animate-spin" size={16} /> Loading breadth…
        </div>
      ) : error || !data || !latest ? (
        <EmptyState reason="Breadth hasn't been computed for this group yet — check back shortly." />
      ) : (
        <>
          <div className="flex flex-wrap items-center justify-between gap-6 mb-6">
            <StatChip label="Bullish" value={`${latest.value}%`} />
            <StatChip label="Coverage" value={`${latest.resolved} / ${latest.total}`} />
            <StatChip label="As Of" value={fmtDate(latest.date)} />
          </div>

          <div className="flex items-center justify-between mb-3">
            <p className="font-mono-ui text-[10px] uppercase tracking-[0.16em] text-slate-500">Nifty 50</p>
            <ZoomTabs zoom={zoom} setZoom={setZoom} />
          </div>
          <IndexChart candles={visibleCandles} />

          <p className="font-mono-ui text-[10px] uppercase tracking-[0.16em] text-slate-500 mt-6 mb-3">Breadth</p>
          <BreadthChart series={visibleSeries} />

          <p className="text-[11px] font-light text-slate-600 mt-6 max-w-2xl leading-relaxed">
            Percentage of the group currently trading in a bullish swing, using each stock's own
            chart independently. Above 75% or below 25% is an extreme zone — a strong trend can stay
            there for a long stretch, so treat it as a caution flag on fresh entries, not a standalone
            reversal signal. For research and educational purposes only — not investment advice.
          </p>
        </>
      )}
    </div>
  );
};

export default BreadthTool;
