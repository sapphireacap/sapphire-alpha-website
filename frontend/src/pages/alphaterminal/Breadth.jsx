import { useState, useEffect } from "react";
import axios from "axios";
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, ReferenceLine,
} from "recharts";
import { Loader2 } from "lucide-react";
import { EmptyState } from "./QuantLab";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;
const SURFACE = "rounded-2xl border border-white/10 bg-[#0A0D18]";

const fmtDate = (iso) => {
  if (!iso) return "—";
  const [y, m, d] = iso.split("-");
  return `${d}/${m}/${y}`;
};

const StatChip = ({ label, value }) => (
  <div className="flex flex-col">
    <span className="font-mono-ui text-[10px] uppercase tracking-[0.16em] text-slate-500">{label}</span>
    <span className="font-display text-lg font-bold text-white">{value}</span>
  </div>
);

const BreadthChart = ({ series }) => (
  <div className={`${SURFACE} p-4`} style={{ height: 360 }} data-testid="breadth-chart">
    <ResponsiveContainer width="100%" height="100%">
      <LineChart data={series} margin={{ top: 10, right: 10, left: 0, bottom: 0 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.06)" vertical={false} />
        <XAxis dataKey="date" tick={{ fill: "#64748B", fontSize: 10 }} axisLine={{ stroke: "rgba(255,255,255,0.1)" }} tickLine={false} minTickGap={60} tickFormatter={fmtDate} />
        <YAxis domain={[0, 100]} tick={{ fill: "#64748B", fontSize: 11 }} axisLine={false} tickLine={false} width={40} />
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

          <BreadthChart series={data.series} />

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
