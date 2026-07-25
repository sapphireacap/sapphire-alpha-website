import { useEffect, useState } from "react";
import axios from "axios";
import { motion } from "framer-motion";
import { Clock, Loader2 } from "lucide-react";
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from "recharts";
import Navbar from "../components/site/Navbar";
import Footer from "../components/site/Footer";
import ParticleField from "../components/site/ParticleField";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;
const EASE = [0.16, 1, 0.3, 1];
const STATUS_POLL_MS = 60000;

const STRATEGIES = [
  { no: "02", title: "Strategy 02" },
  { no: "03", title: "Strategy 03" },
  { no: "04", title: "Strategy 04" },
];

const StrategyCard = ({ strategy }) => (
  <div
    className="relative glass rounded-2xl border border-dashed border-white/10 opacity-40 px-6 py-14 flex flex-col items-center justify-center text-center"
    data-testid={`black-box-strategy-${strategy.no}`}
  >
    <Clock size={16} className="absolute top-4 right-4 text-slate-600" />
    <span className="font-mono-ui text-xs text-sapphire-light mb-3">{strategy.no}</span>
    <h4 className="font-display text-2xl font-bold text-slate-300">{strategy.title}</h4>
    <p className="mt-3 text-sm font-light text-slate-500 max-w-xs">Coming Soon</p>
  </div>
);

const fmtDateTime = (iso) => {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  return d.toLocaleString("en-IN", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" });
};

const fmtDuration = (entryIso, exitIso) => {
  if (!entryIso || !exitIso) return "—";
  const mins = Math.round((new Date(exitIso) - new Date(entryIso)) / 60000);
  if (mins < 60) return `${mins}m`;
  return `${Math.floor(mins / 60)}h ${mins % 60}m`;
};

const fmtPnl = (v) => {
  if (v == null) return "—";
  const sign = v > 0 ? "+" : "";
  return `${sign}₹${v.toFixed(2)}`;
};

const StatBlock = ({ label, value, valueClass = "text-white" }) => (
  <div>
    <p className="font-mono-ui text-[10px] uppercase tracking-[0.18em] text-slate-500 mb-1">{label}</p>
    <p className={`font-display text-2xl font-black tracking-tight ${valueClass}`}>{value}</p>
  </div>
);

const EquityChart = ({ equityCurve }) => {
  const series = equityCurve.map((p, i) => ({ ...p, label: `#${i + 1}` }));
  return (
    <div className="h-56" data-testid="prism-alpha-equity-chart">
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={series} margin={{ top: 10, right: 10, left: 0, bottom: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.06)" vertical={false} />
          <XAxis dataKey="label" tick={{ fill: "#64748B", fontSize: 10 }} axisLine={{ stroke: "rgba(255,255,255,0.1)" }} tickLine={false} minTickGap={40} />
          <YAxis tick={{ fill: "#64748B", fontSize: 11 }} axisLine={false} tickLine={false} domain={["auto", "auto"]} width={56} />
          <Tooltip
            contentStyle={{ background: "#0A0D18", border: "1px solid rgba(255,255,255,0.1)", borderRadius: 8, fontSize: 12 }}
            labelStyle={{ color: "#94A3B8" }}
            itemStyle={{ color: "#E2E8F0" }}
            formatter={(v) => [`₹${v.toFixed(2)}`, "Cumulative P&L"]}
          />
          <Line type="monotone" dataKey="cumulative_pnl" name="Equity" stroke="#437EEB" strokeWidth={1.5} dot={false} isAnimationActive={false} />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
};

const TradeLogTable = ({ trades }) => (
  <div className="overflow-x-auto" data-testid="prism-alpha-trade-log">
    <table className="w-full text-left min-w-[600px]">
      <thead>
        <tr className="border-b border-white/10">
          {["Date", "Dir", "Entry", "Exit", "P&L", "Duration"].map((h) => (
            <th key={h} className="px-4 py-3 font-mono-ui text-[10px] uppercase tracking-[0.16em] text-slate-500 font-semibold whitespace-nowrap">
              {h}
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        {trades.map((t) => (
          <tr key={t.id} className="border-b border-white/[0.05] last:border-0">
            <td className="px-4 py-3 text-sm text-slate-300 whitespace-nowrap">{t.date}</td>
            <td className="px-4 py-3 text-sm whitespace-nowrap">
              <span className={t.direction === "CE" ? "text-emerald-400" : "text-red-400"}>{t.direction}</span>
            </td>
            <td className="px-4 py-3 font-mono-ui text-sm text-slate-300 whitespace-nowrap">₹{t.entry_price?.toFixed(2)}</td>
            <td className="px-4 py-3 font-mono-ui text-sm text-slate-300 whitespace-nowrap">{t.exit_price != null ? `₹${t.exit_price.toFixed(2)}` : "—"}</td>
            <td className={`px-4 py-3 font-mono-ui text-sm whitespace-nowrap ${t.pnl > 0 ? "text-emerald-400" : t.pnl < 0 ? "text-red-400" : "text-slate-300"}`}>
              {fmtPnl(t.pnl)}
            </td>
            <td className="px-4 py-3 text-sm text-slate-400 whitespace-nowrap">{fmtDuration(t.entry_time, t.exit_time)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  </div>
);

const fmtDate = (iso) => {
  if (!iso) return "—";
  const [y, m, d] = iso.split("-");
  const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  return `${d} ${MONTHS[Number(m) - 1]} ${y}`;
};

const TrackRecord = ({ stats, trades, emptyMessage }) => (
  <>
    <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
      <StatBlock label="Win Rate" value={stats.win_rate != null ? `${(stats.win_rate * 100).toFixed(0)}%` : "—"} />
      <StatBlock
        label="Avg P&L"
        value={fmtPnl(stats.avg_pnl)}
        valueClass={stats.avg_pnl > 0 ? "text-emerald-400" : stats.avg_pnl < 0 ? "text-red-400" : "text-white"}
      />
      <StatBlock label="Max Drawdown" value={stats.max_drawdown != null ? `₹${stats.max_drawdown.toFixed(2)}` : "—"} />
      <StatBlock label="Total Trades" value={stats.total_trades} />
    </div>

    {stats.equity_curve.length > 1 ? (
      <EquityChart equityCurve={stats.equity_curve} />
    ) : (
      <p className="text-sm text-slate-500 py-6 text-center" data-testid="prism-alpha-empty">{emptyMessage}</p>
    )}

    {trades.length > 0 && (
      <div className="mt-6">
        <p className="font-mono-ui text-[10px] uppercase tracking-[0.18em] text-slate-500 mb-3">Trade Log</p>
        <TradeLogTable trades={trades} />
      </div>
    )}
  </>
);

const PrismAlphaCard = () => {
  const [tab, setTab] = useState("live");
  const [status, setStatus] = useState(null);
  const [stats, setStats] = useState(null);
  const [trades, setTrades] = useState([]);
  const [backtestRun, setBacktestRun] = useState(null);
  const [backtestStats, setBacktestStats] = useState(null);
  const [backtestTrades, setBacktestTrades] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    const load = () => {
      Promise.all([
        axios.get(`${API}/blackbox/prism-alpha/status`),
        axios.get(`${API}/blackbox/prism-alpha/stats`),
        axios.get(`${API}/blackbox/prism-alpha/trades`),
        axios.get(`${API}/blackbox/prism-alpha/backtest/summary`),
        axios.get(`${API}/blackbox/prism-alpha/backtest/trades`),
      ])
        .then(([s, st, tr, bs, bt]) => {
          if (cancelled) return;
          setStatus(s.data);
          setStats(st.data);
          setTrades(tr.data);
          setBacktestRun(bs.data.run);
          setBacktestStats(bs.data.stats);
          setBacktestTrades(bt.data);
        })
        .catch(() => {})
        .finally(() => { if (!cancelled) setLoading(false); });
    };
    load();
    const interval = setInterval(load, STATUS_POLL_MS);
    return () => { cancelled = true; clearInterval(interval); };
  }, []);

  const inPosition = status?.position === "in_position";
  const direction = status?.today_signal?.direction;

  return (
    <div className="glass rounded-2xl p-6 md:p-8 mb-4" data-testid="prism-alpha-card">
      <div className="flex flex-wrap items-center justify-between gap-3 mb-6">
        <div>
          <span className="font-mono-ui text-xs text-sapphire-light mb-1 block">01</span>
          <h4 className="font-display text-2xl font-bold text-white">Prism Alpha</h4>
          <p className="text-sm font-light text-slate-500 mt-1">Systematic P&F pattern-based Nifty options signals</p>
        </div>
        {loading ? (
          <div className="flex items-center gap-2 text-slate-500 text-sm"><Loader2 className="animate-spin" size={14} /> Loading</div>
        ) : (
          <span
            className={`inline-flex items-center gap-2 rounded-full border px-3 py-1.5 text-xs font-medium ${
              inPosition
                ? (direction === "CE" ? "border-emerald-400/30 bg-emerald-400/10 text-emerald-300" : "border-red-400/30 bg-red-400/10 text-red-300")
                : "border-slate-400/25 bg-slate-400/10 text-slate-300"
            }`}
            data-testid="prism-alpha-status-badge"
          >
            <span className={`h-1.5 w-1.5 rounded-full ${inPosition ? (direction === "CE" ? "bg-emerald-400" : "bg-red-400") : "bg-slate-400"}`} />
            {inPosition ? `In Position — ${direction}` : "Flat"}
          </span>
        )}
      </div>

      <div className="flex gap-2 mb-6 border-b border-white/10" data-testid="prism-alpha-tabs">
        {[{ key: "live", label: "Live" }, { key: "backtest", label: "Backtest" }].map((t) => (
          <button
            key={t.key}
            onClick={() => setTab(t.key)}
            className={`px-4 py-2 font-mono-ui text-xs uppercase tracking-[0.14em] border-b-2 transition-colors duration-200 ${
              tab === t.key ? "border-sapphire-light text-sapphire-light" : "border-transparent text-slate-500 hover:text-slate-300"
            }`}
            data-testid={`prism-alpha-tab-${t.key}`}
          >
            {t.label}
          </button>
        ))}
      </div>

      {!loading && tab === "live" && stats && (
        <TrackRecord stats={stats} trades={trades} emptyMessage="No closed trades yet — track record will appear here once Prism Alpha has completed live trades." />
      )}

      {!loading && tab === "backtest" && (
        <>
          {backtestRun ? (
            <div className="mb-6 rounded-xl border border-white/10 bg-white/[0.03] px-4 py-3" data-testid="prism-alpha-backtest-meta">
              <p className="text-xs text-slate-400">
                Backtest window: <span className="text-white font-medium">{fmtDate(backtestRun.start_date)} – {fmtDate(backtestRun.end_date)}</span>
                {" · "}Data: <span className="text-white font-medium">daily (end-of-day) real option prices</span>
                {" · "}{backtestRun.trading_days_evaluated} trading days evaluated
              </p>
            </div>
          ) : (
            <p className="text-sm text-slate-500 py-6 text-center" data-testid="prism-alpha-backtest-none">
              No backtest has been run yet.
            </p>
          )}
          {backtestStats && (
            <TrackRecord
              stats={backtestStats}
              trades={backtestTrades}
              emptyMessage="No trades were generated in this backtest window — Prism Alpha's entry conditions are strict and didn't align on any simulated day, which is a real result, not an error."
            />
          )}
          <p className="text-[11px] font-light text-amber-400/70 mt-6" data-testid="prism-alpha-backtest-disclaimer">
            Backtested results are hypothetical and computed from daily end-of-day data with real historical option prices — they do not reflect intraday execution the way the live 1-minute strategy runs, are subject to the data limitations noted above, and do not guarantee live performance.
          </p>
        </>
      )}

      <p className="text-[11px] font-light text-slate-600 mt-6 pt-4 border-t border-white/10" data-testid="prism-alpha-disclaimer">
        Performance shown is for research/educational purposes only, not investment advice. Past performance does not guarantee future results.
      </p>
    </div>
  );
};

export default function BlackBox() {
  useEffect(() => { window.scrollTo(0, 0); }, []);

  return (
    <>
      <Navbar />
      <main className="relative bg-void min-h-screen">
        <section className="relative pt-28 pb-10 md:pt-32 md:pb-14 overflow-hidden" data-testid="black-box-hero">
          <ParticleField density={0.00006} />
          <div className="absolute inset-0 radial-glow" />
          <div className="absolute inset-0 bg-gradient-to-b from-void/0 to-void pointer-events-none" />
          <div className="container-x relative z-10">
            <motion.h1
              initial={{ opacity: 0, y: 24 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.9, ease: EASE }}
              className="font-display font-black tracking-tighter text-white text-5xl md:text-7xl leading-[0.95]"
            >
              The Black Box
            </motion.h1>
            <motion.p
              initial={{ opacity: 0, y: 24 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.9, ease: EASE, delay: 0.1 }}
              className="mt-6 text-base md:text-lg font-light text-slate-400 leading-relaxed max-w-2xl"
              data-testid="black-box-subtitle"
            >
              Systematic strategies, built and tested in-house.
            </motion.p>
          </div>
        </section>

        <section className="relative pb-20 md:pb-28">
          <div className="container-x">
            <PrismAlphaCard />
            <div className="grid grid-cols-1 md:grid-cols-3 gap-4" data-testid="black-box-strategies">
              {STRATEGIES.map((s) => <StrategyCard key={s.no} strategy={s} />)}
            </div>
          </div>
        </section>
      </main>
      <Footer />
    </>
  );
}
