import { useState, useEffect, useMemo } from "react";
import axios from "axios";
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, ReferenceLine,
} from "recharts";
import { Loader2 } from "lucide-react";
import { EmptyState } from "./QuantLab";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;
const SURFACE = "rounded-2xl border border-white/10 bg-[#0A0D18]";

// Matches Definedge's own "Average Value" stat on its Breadth tool — a
// 5-period simple moving average of the breadth line itself, confirmed
// live (2026-08-05): Nifty 50's last 5 daily values averaged to exactly
// 72.40%, matching their displayed Average Value for that date to the cent.
const AVERAGE_PERIOD = 5;

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

// Adds a trailing AVERAGE_PERIOD-point average to every point — computed
// over the FULL series (before any zoom slicing) so the average at the
// start of a zoomed-in window still reflects real prior history, not a
// truncated one.
const withAverage = (series) => series.map((p, i) => {
  const window = series.slice(Math.max(0, i - AVERAGE_PERIOD + 1), i + 1);
  const avg = window.reduce((sum, w) => sum + w.value, 0) / window.length;
  return { ...p, avg: Math.round(avg * 100) / 100 };
});

const StatChip = ({ label, value }) => (
  <div className="flex flex-col">
    <span className="font-mono-ui text-[10px] uppercase tracking-[0.16em] text-slate-500">{label}</span>
    <span className="font-display text-lg font-bold text-white">{value}</span>
  </div>
);

const ZoomTabs = ({ zoom, setZoom }) => (
  <div className="flex items-center gap-1 rounded-md border border-white/10 p-0.5 w-full overflow-x-auto sm:w-fit" data-testid="breadth-zoom-tabs">
    {ZOOMS.map((z) => (
      <button
        key={z.key}
        type="button"
        onClick={() => setZoom(z.key)}
        data-testid={`breadth-zoom-${z.key}`}
        className={`font-mono-ui text-[10px] uppercase tracking-wider px-3 py-1.5 rounded transition-colors whitespace-nowrap shrink-0 ${
          zoom === z.key ? "bg-sapphire-light/20 text-sapphire-light" : "text-slate-500 hover:text-slate-300"
        }`}
      >
        {z.label}
      </button>
    ))}
  </div>
);

const BreadthChart = ({ series }) => (
  <div className={`${SURFACE} p-3 sm:p-4 h-[280px] sm:h-[380px]`} data-testid="breadth-chart">
    <ResponsiveContainer width="100%" height="100%">
      <LineChart data={series} margin={{ top: 10, right: 4, left: 0, bottom: 0 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.06)" vertical={false} />
        <XAxis dataKey="date" tick={{ fill: "#64748B", fontSize: 10 }} axisLine={{ stroke: "rgba(255,255,255,0.1)" }} tickLine={false} minTickGap={45} tickFormatter={fmtDate} />
        <YAxis domain={[0, 100]} tick={{ fill: "#64748B", fontSize: 11 }} axisLine={false} tickLine={false} width={32} />
        <ReferenceLine y={75} stroke="#F59E0B" strokeDasharray="4 4" strokeOpacity={0.5} />
        <ReferenceLine y={50} stroke="rgba(255,255,255,0.15)" strokeDasharray="2 2" />
        <ReferenceLine y={25} stroke="#F59E0B" strokeDasharray="4 4" strokeOpacity={0.5} />
        <Tooltip
          labelFormatter={fmtDate}
          formatter={(v, name) => [`${v}%`, name === "avg" ? "Average" : "Bullish"]}
          contentStyle={{ background: "#0A0D18", border: "1px solid rgba(255,255,255,0.1)", borderRadius: 8, fontSize: 12 }}
          labelStyle={{ color: "#94A3B8" }}
        />
        <Line type="monotone" dataKey="value" stroke="#3ED598" strokeWidth={1.5} dot={false} isAnimationActive={false} />
        <Line type="monotone" dataKey="avg" stroke="#F87171" strokeWidth={1.5} dot={false} isAnimationActive={false} />
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

  const seriesWithAvg = useMemo(() => (data?.series?.length ? withAverage(data.series) : []), [data]);
  const latest = seriesWithAvg.length ? seriesWithAvg[seriesWithAvg.length - 1] : null;

  const visibleSeries = useMemo(() => {
    if (!seriesWithAvg.length) return [];
    const dates = seriesWithAvg.map((p) => p.date);
    const cutoff = cutoffDate(zoom, dates);
    return cutoff ? seriesWithAvg.filter((p) => p.date >= cutoff) : seriesWithAvg;
  }, [seriesWithAvg, zoom]);

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
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
            <StatChip label="Bullish" value={`${latest.value}%`} />
            <StatChip label="5-Day Average" value={`${latest.avg}%`} />
            <StatChip label="Coverage" value={`${latest.resolved} / ${latest.total}`} />
            <StatChip label="As Of" value={fmtDate(latest.date)} />
          </div>

          <div className="flex justify-end mb-3">
            <ZoomTabs zoom={zoom} setZoom={setZoom} />
          </div>
          <BreadthChart series={visibleSeries} />
        </>
      )}
    </div>
  );
};

export default BreadthTool;
