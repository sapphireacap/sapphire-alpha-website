import { useState } from "react";
import axios from "axios";
import { toast } from "sonner";
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, ReferenceDot,
} from "recharts";
import { Loader2, TrendingUp, TrendingDown, Percent, LineChart as LineChartIcon } from "lucide-react";
import ParticleField from "../../components/site/ParticleField";
import { ComingSoonCard } from "../AlphaTerminal";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;

const SEGMENTS = ["NSE", "BSE", "NFO", "BFO"];

const TOOLS = [
  { key: "ewma", title: "EWMA Crossover", description: "Fast/slow EWMA crossover backtest vs. buy-and-hold, on any NSE/BSE/NFO/BFO symbol.", active: true },
  { key: "sharpe", title: "Sharpe Dashboard", description: "Risk-adjusted return comparison across instruments and lookback windows.", active: false },
  { key: "montecarlo", title: "Monte Carlo Simulator", description: "Forward-simulate equity paths from a strategy's historical return distribution.", active: false },
  { key: "pairs", title: "Pairs Bot", description: "Cointegration-based pairs trading scanner with spread z-score signals.", active: false },
  { key: "frontier", title: "Efficient Frontier", description: "Mean-variance optimal portfolio construction across a chosen basket.", active: false },
];

const field = "w-full bg-white/5 border border-white/10 rounded-md px-3 py-2 text-sm text-white outline-none focus:border-sapphire-light transition-colors";
const selectCls = field + " [color-scheme:dark]";
const label = "font-mono-ui text-[10px] uppercase tracking-[0.18em] text-slate-500 block mb-1.5";

const StatCard = ({ label: l, value, Icon, tone = "text-white" }) => (
  <div className="glass rounded-2xl p-5">
    <div className="flex items-center gap-2 mb-2">
      <Icon size={14} className="text-sapphire-light" />
      <p className="font-mono-ui text-[10px] uppercase tracking-[0.18em] text-slate-500">{l}</p>
    </div>
    <p className={`font-display text-3xl font-black tracking-tight ${tone}`}>{value}</p>
  </div>
);

const fmtPct = (v) => `${Number(v) >= 0 ? "+" : ""}${(Number(v) * 100).toFixed(2)}%`;
const fmtDate = (iso) => {
  if (!iso) return "—";
  const [y, m, d] = iso.split("-");
  return `${d}/${m}/${y}`;
};

const ToolCard = ({ tool, isActiveTool, onClick }) => {
  if (!tool.active) return <ComingSoonCard scannerKey={tool.key} />;
  return (
    <button
      type="button"
      onClick={onClick}
      className={`group relative text-left glass rounded-2xl border p-6 transition-colors duration-300 hover:border-sapphire/40 hover:bg-sapphire/[0.03] ${isActiveTool ? "border-sapphire/40 bg-sapphire/[0.04]" : "border-white/10"}`}
      data-testid={`quant-tool-${tool.key}`}
    >
      <span className="font-mono-ui text-[10px] uppercase tracking-[0.24em] text-sapphire-light mb-3 block">Available</span>
      <h4 className="font-display text-lg font-bold text-white mb-2">{tool.title}</h4>
      <p className="text-sm font-light text-slate-500 leading-relaxed">{tool.description}</p>
    </button>
  );
};

const LoadingParticles = () => (
  <div className="relative glass rounded-2xl border border-white/10 h-64 overflow-hidden flex flex-col items-center justify-center" data-testid="ewma-loading">
    <ParticleField density={0.00012} />
    <div className="absolute inset-0 radial-glow pointer-events-none" />
    <div className="relative z-10 flex flex-col items-center gap-3">
      <span className="relative flex h-3 w-3">
        <span className="absolute inline-flex h-full w-full rounded-full bg-sapphire-light opacity-75 animate-ping" />
        <span className="relative inline-flex h-3 w-3 rounded-full bg-sapphire-light" />
      </span>
      <p className="font-mono-ui text-xs uppercase tracking-[0.24em] text-slate-300">Running Backtest</p>
      <p className="font-mono-ui text-[10px] uppercase tracking-[0.18em] text-slate-600">Fetching history · Computing signals · Scoring returns</p>
    </div>
  </div>
);

const EmptyState = ({ reason }) => (
  <div className="glass rounded-2xl border border-white/10 p-10 text-center" data-testid="ewma-empty">
    <p className="font-mono-ui text-[10px] uppercase tracking-[0.24em] text-slate-500 mb-3">No Result Found</p>
    <p className="text-sm text-slate-400 leading-relaxed max-w-md mx-auto">{reason}</p>
  </div>
);

const EwmaChart = ({ series, markers }) => {
  const buys = markers.filter((m) => m.type === "buy");
  const sells = markers.filter((m) => m.type === "sell");
  return (
    <div className="h-80" data-testid="ewma-chart">
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={series} margin={{ top: 10, right: 10, left: 0, bottom: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.06)" vertical={false} />
          <XAxis dataKey="date" tick={{ fill: "#64748B", fontSize: 10 }} axisLine={{ stroke: "rgba(255,255,255,0.1)" }} tickLine={false} minTickGap={60} />
          <YAxis tick={{ fill: "#64748B", fontSize: 11 }} axisLine={false} tickLine={false} domain={["auto", "auto"]} width={56} />
          <Tooltip
            contentStyle={{ background: "#0A0D18", border: "1px solid rgba(255,255,255,0.1)", borderRadius: 8, fontSize: 12 }}
            labelStyle={{ color: "#94A3B8" }}
            itemStyle={{ color: "#E2E8F0" }}
          />
          <Line type="monotone" dataKey="close" name="Close" stroke="#94A3B8" strokeWidth={1.25} dot={false} isAnimationActive={false} />
          <Line type="monotone" dataKey="ewma_fast" name="Fast EWMA" stroke="#437EEB" strokeWidth={1.5} dot={false} isAnimationActive={false} />
          <Line type="monotone" dataKey="ewma_slow" name="Slow EWMA" stroke="#F59E0B" strokeWidth={1.5} dot={false} isAnimationActive={false} />
          {buys.map((m, i) => (
            <ReferenceDot key={`buy-${i}`} x={m.date} y={m.price} r={4} fill="#34D399" stroke="none" />
          ))}
          {sells.map((m, i) => (
            <ReferenceDot key={`sell-${i}`} x={m.date} y={m.price} r={4} fill="#F87171" stroke="none" />
          ))}
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
};

const EwmaResults = ({ result }) => (
  <div data-testid="ewma-results">
    <div className="flex flex-wrap items-center justify-between gap-3 mb-4">
      <div>
        <p className="font-display text-xl font-bold text-white">{result.resolved_symbol}</p>
        <p className="font-mono-ui text-[10px] uppercase tracking-[0.18em] text-slate-500 mt-1">
          {result.segment} · History {fmtDate(result.history_from)} – {fmtDate(result.history_to)}
          {result.resolved_expiry && <> · Expiry {fmtDate(result.resolved_expiry)}</>}
        </p>
      </div>
      {result.cached && (
        <span className="inline-flex rounded-full border border-white/15 px-2.5 py-0.5 font-mono-ui text-[10px] uppercase tracking-wider text-slate-500">
          Cached
        </span>
      )}
    </div>

    <div className="glass rounded-2xl p-4 md:p-6 mb-6">
      <EwmaChart series={result.series} markers={result.markers} />
      <div className="flex flex-wrap gap-4 mt-4 px-1">
        <span className="inline-flex items-center gap-1.5 text-[11px] text-slate-500"><span className="h-0.5 w-4 bg-[#94A3B8] inline-block" /> Close</span>
        <span className="inline-flex items-center gap-1.5 text-[11px] text-slate-500"><span className="h-0.5 w-4 bg-[#437EEB] inline-block" /> Fast EWMA ({result.fast_span})</span>
        <span className="inline-flex items-center gap-1.5 text-[11px] text-slate-500"><span className="h-0.5 w-4 bg-[#F59E0B] inline-block" /> Slow EWMA ({result.slow_span})</span>
        <span className="inline-flex items-center gap-1.5 text-[11px] text-slate-500"><span className="h-1.5 w-1.5 rounded-full bg-emerald-400 inline-block" /> Buy</span>
        <span className="inline-flex items-center gap-1.5 text-[11px] text-slate-500"><span className="h-1.5 w-1.5 rounded-full bg-red-400 inline-block" /> Sell</span>
      </div>
    </div>

    <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
      <StatCard label="Strategy Return" value={fmtPct(result.stats.strategy_return)} Icon={result.stats.strategy_return >= 0 ? TrendingUp : TrendingDown} tone={result.stats.strategy_return >= 0 ? "text-emerald-300" : "text-red-300"} />
      <StatCard label="Buy & Hold Return" value={fmtPct(result.stats.buy_and_hold_return)} Icon={result.stats.buy_and_hold_return >= 0 ? TrendingUp : TrendingDown} tone={result.stats.buy_and_hold_return >= 0 ? "text-emerald-300" : "text-red-300"} />
      <StatCard label="Evaluated Bars" value={result.evaluated_bars} Icon={LineChartIcon} />
      <StatCard label="Trades" value={result.markers.length} Icon={Percent} />
    </div>
    <p className="text-[11px] font-light text-slate-600 mt-4 max-w-2xl">
      Evaluated {fmtDate(result.evaluated_from)} – {fmtDate(result.evaluated_to)} — the first {result.slow_span * 2} bars of history are excluded from the return comparison to avoid warmup bias in the slow EWMA. Signal and execution both use the same day's close (no open-price modeling). Past performance doesn't guarantee future results — not investment advice.
    </p>
  </div>
);

const EwmaCrossoverTool = () => {
  const [form, setForm] = useState({ segment: "NSE", symbol: "", fast_span: 20, slow_span: 50 });
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState(null); // { found: true, ... } | { found: false, reason } | null

  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }));

  const submit = async (e) => {
    e.preventDefault();
    if (!form.symbol.trim()) return;
    setLoading(true);
    setResult(null);
    try {
      const { data } = await axios.post(`${API}/quant-lab/ewma-crossover`, {
        segment: form.segment,
        symbol: form.symbol.trim(),
        fast_span: Number(form.fast_span),
        slow_span: Number(form.slow_span),
      });
      setResult(data);
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Backtest failed. Please try again.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="mt-6" data-testid="ewma-tool">
      <form onSubmit={submit} className="glass rounded-2xl p-6 md:p-8 mb-6">
        <div className="grid grid-cols-2 md:grid-cols-5 gap-4 items-end">
          <div>
            <label className={label}>Segment</label>
            <select value={form.segment} onChange={set("segment")} style={{ colorScheme: "dark" }} className={selectCls} data-testid="ewma-segment">
              {SEGMENTS.map((s) => <option key={s} value={s} className="bg-surface">{s}</option>)}
            </select>
          </div>
          <div>
            <label className={label}>Symbol</label>
            <input value={form.symbol} onChange={set("symbol")} className={field} placeholder="RELIANCE" data-testid="ewma-symbol" required />
          </div>
          <div>
            <label className={label}>Fast Span</label>
            <input type="number" min={2} max={500} value={form.fast_span} onChange={set("fast_span")} className={field} data-testid="ewma-fast" required />
          </div>
          <div>
            <label className={label}>Slow Span</label>
            <input type="number" min={3} max={1000} value={form.slow_span} onChange={set("slow_span")} className={field} data-testid="ewma-slow" required />
          </div>
          <button type="submit" disabled={loading} className="btn-sapphire disabled:opacity-70 h-[42px]" data-testid="ewma-submit">
            {loading ? <><Loader2 size={16} className="animate-spin" /> Running</> : "Run Backtest"}
          </button>
        </div>
      </form>

      {loading && <LoadingParticles />}
      {!loading && result && !result.found && <EmptyState reason={result.reason || "No data found for this symbol and segment."} />}
      {!loading && result && result.found && <EwmaResults result={result} />}
    </div>
  );
};

export default function QuantLab() {
  const [activeTool, setActiveTool] = useState("ewma");

  return (
    <div data-testid="quant-lab">
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        {TOOLS.map((tool) => (
          <ToolCard
            key={tool.key}
            tool={tool}
            isActiveTool={activeTool === tool.key}
            onClick={() => setActiveTool(tool.key)}
          />
        ))}
      </div>

      {activeTool === "ewma" && <EwmaCrossoverTool />}
    </div>
  );
}
