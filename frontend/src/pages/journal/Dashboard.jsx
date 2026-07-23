import { useEffect, useState, useCallback } from "react";
import axios from "axios";
import { toast } from "sonner";
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, ReferenceLine } from "recharts";
import { Loader2, TrendingUp, Percent, Scale, TrendingDown } from "lucide-react";
import { TRADER_TOKEN_KEY } from "../Auth";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;
const authHeaders = () => ({ headers: { Authorization: `Bearer ${localStorage.getItem(TRADER_TOKEN_KEY)}` } });

const StatCard = ({ label, value, Icon, tone = "text-white" }) => (
  <div className="glass rounded-2xl p-5">
    <div className="flex items-center gap-2 mb-2">
      <Icon size={14} className="text-sapphire-light" />
      <p className="font-mono-ui text-[10px] uppercase tracking-[0.18em] text-slate-500">{label}</p>
    </div>
    <p className={`font-display text-3xl font-black tracking-tight ${tone}`}>{value}</p>
  </div>
);

const fmtR = (v) => `${Number(v) >= 0 ? "+" : ""}${Number(v).toFixed(2)}R`;

const EquityCurve = ({ points }) => (
  <div className="h-64" data-testid="equity-curve">
    <ResponsiveContainer width="100%" height="100%">
      <LineChart data={points} margin={{ top: 10, right: 10, left: 0, bottom: 0 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.06)" vertical={false} />
        <XAxis dataKey="label" tick={{ fill: "#64748B", fontSize: 11 }} axisLine={{ stroke: "rgba(255,255,255,0.1)" }} tickLine={false} />
        <YAxis tick={{ fill: "#64748B", fontSize: 11 }} axisLine={false} tickLine={false} tickFormatter={(v) => `${v}R`} width={40} />
        <ReferenceLine y={0} stroke="rgba(255,255,255,0.15)" />
        <Tooltip
          contentStyle={{ background: "#0A0D18", border: "1px solid rgba(255,255,255,0.1)", borderRadius: 8, fontSize: 12 }}
          labelStyle={{ color: "#94A3B8" }}
          itemStyle={{ color: "#E2E8F0" }}
          formatter={(value) => [`${Number(value).toFixed(2)}R`, "Cumulative"]}
        />
        <Line type="monotone" dataKey="cumR" stroke="#437EEB" strokeWidth={2} dot={{ r: 3, fill: "#437EEB", strokeWidth: 0 }} activeDot={{ r: 5 }} />
      </LineChart>
    </ResponsiveContainer>
  </div>
);

const Dashboard = () => {
  const [analytics, setAnalytics] = useState(null);
  const [closedTrades, setClosedTrades] = useState([]);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [a, t] = await Promise.all([
        axios.get(`${API}/journal/analytics`, authHeaders()),
        axios.get(`${API}/journal/trades`, { ...authHeaders(), params: { status: "closed", limit: 200 } }),
      ]);
      setAnalytics(a.data);
      setClosedTrades(t.data.trades);
    } catch {
      toast.error("Failed to load dashboard.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  if (loading) {
    return <div className="flex items-center justify-center py-24 text-slate-500 gap-3"><Loader2 className="animate-spin" size={18} /> Loading…</div>;
  }

  // Same ordering as the backend's own drawdown computation — exit_time, id tiebreak.
  const ordered = [...closedTrades].sort((a, b) => {
    const t = (a.exit_time || "").localeCompare(b.exit_time || "");
    return t !== 0 ? t : (a.id || "").localeCompare(b.id || "");
  });
  let cum = 0;
  const equityPoints = ordered.map((t, i) => {
    cum += Number(t.r_multiple || 0);
    return { label: `#${i + 1}`, cumR: Number(cum.toFixed(3)) };
  });

  const emotionCounts = {};
  closedTrades.forEach((t) => {
    if (t.pre_trade_emotion) emotionCounts[t.pre_trade_emotion] = (emotionCounts[t.pre_trade_emotion] || 0) + 1;
  });
  const emotionEntries = Object.entries(emotionCounts).sort((a, b) => b[1] - a[1]);
  const maxEmotionCount = Math.max(1, ...emotionEntries.map(([, c]) => c));

  return (
    <div data-testid="journal-dashboard">
      <div className="flex items-center justify-between mb-6">
        <h1 className="font-display text-2xl font-bold text-white">Dashboard</h1>
        {analytics.low_sample_size && (
          <span className="inline-flex items-center rounded-full border border-amber-400/25 bg-amber-400/10 px-3 py-1 font-mono-ui text-[10px] uppercase tracking-wider text-amber-300" data-testid="low-sample-badge">
            Low sample size — {analytics.trade_count} closed trades
          </span>
        )}
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
        <StatCard label="Expectancy" value={fmtR(analytics.expectancy_r)} Icon={TrendingUp} tone={Number(analytics.expectancy_r) >= 0 ? "text-emerald-300" : "text-red-300"} />
        <StatCard label="Win Rate" value={`${(Number(analytics.win_rate) * 100).toFixed(0)}%`} Icon={Percent} />
        <StatCard label="Profit Factor" value={Number(analytics.profit_factor).toFixed(2)} Icon={Scale} />
        <StatCard label="Max Drawdown" value={fmtR(analytics.max_drawdown_r)} Icon={TrendingDown} tone="text-red-300" />
      </div>

      <div className="glass rounded-2xl p-6 mb-6">
        <p className="font-mono-ui text-[10px] uppercase tracking-[0.18em] text-slate-500 mb-4">Equity Curve (R)</p>
        {equityPoints.length > 0 ? (
          <EquityCurve points={equityPoints} />
        ) : (
          <p className="text-sm text-slate-500 py-16 text-center">No closed trades yet — close a trade to see your equity curve.</p>
        )}
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <div className="glass rounded-2xl p-6">
          <p className="font-mono-ui text-[10px] uppercase tracking-[0.18em] text-slate-500 mb-3">Rule Adherence</p>
          <p className="font-display text-3xl font-black text-white">{(Number(analytics.rule_adherence_rate) * 100).toFixed(0)}%</p>
        </div>
        <div className="glass rounded-2xl p-6">
          <p className="font-mono-ui text-[10px] uppercase tracking-[0.18em] text-slate-500 mb-3">Emotion Breakdown</p>
          {emotionEntries.length === 0 ? (
            <p className="text-sm text-slate-500">No emotion tags recorded yet.</p>
          ) : (
            <div className="space-y-2">
              {emotionEntries.map(([tag, count]) => (
                <div key={tag} className="flex items-center gap-3">
                  <span className="text-xs text-slate-400 w-20 shrink-0">{tag}</span>
                  <div className="flex-1 h-2 rounded-full bg-white/5 overflow-hidden">
                    <div className="h-full bg-sapphire-light/60 rounded-full" style={{ width: `${(count / maxEmotionCount) * 100}%` }} />
                  </div>
                  <span className="text-xs text-slate-500 w-6 text-right">{count}</span>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
};

export default Dashboard;
