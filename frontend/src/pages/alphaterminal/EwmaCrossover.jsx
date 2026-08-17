import { useState } from "react";
import axios from "axios";
import { toast } from "sonner";
import { authHeaders } from "../../lib/auth";
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, ReferenceDot,
} from "recharts";
import { Loader2, TrendingUp, TrendingDown, Percent, LineChart as LineChartIcon } from "lucide-react";
import { field, selectCls, label, StatCard, fmtPct, LoadingParticles, EmptyState } from "./QuantLab";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;

const SEGMENTS = ["NSE", "BSE", "NFO", "BFO"];

const fmtDate = (iso) => {
  if (!iso) return "—";
  const [y, m, d] = iso.split("-");
  return `${d}/${m}/${y}`;
};

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
        <p className="text-xl font-bold text-white">{result.resolved_symbol}</p>
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

// `scanPath`/`defaultSymbol` point this same tool at another market's EWMA
// endpoint, which speaks the identical request/response contract (see
// multi_market_routes' /markets/{market}/ewma-crossover).
const EwmaCrossoverTool = ({ scanPath = "/quant-lab/ewma-crossover", defaultSymbol = "" }) => {
  const [form, setForm] = useState({ segment: "NSE", symbol: defaultSymbol, fast_span: 20, slow_span: 50 });
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState(null); // { found: true, ... } | { found: false, reason } | null

  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }));

  const submit = async (e) => {
    e.preventDefault();
    if (!form.symbol.trim()) return;
    setLoading(true);
    setResult(null);
    try {
      const { data } = await axios.post(`${API}${scanPath}`, {
        segment: form.segment,
        symbol: form.symbol.trim(),
        fast_span: Number(form.fast_span),
        slow_span: Number(form.slow_span),
      }, { headers: authHeaders() });
      setResult(data);
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Backtest failed. Please try again.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div data-testid="ewma-tool">
      <form onSubmit={submit} className="glass rounded-2xl border border-white/10 p-5 md:p-6 mb-6">
        <p className="font-mono-ui text-[10px] uppercase tracking-[0.24em] text-sapphire-light mb-4 pb-4 border-b border-white/10">
          Custom Backtest
        </p>
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

export default EwmaCrossoverTool;
