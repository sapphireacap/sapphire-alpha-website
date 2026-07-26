import { useEffect, useState } from "react";
import axios from "axios";
import { motion } from "framer-motion";
import { Clock, Loader2, Bell } from "lucide-react";
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from "recharts";
import Navbar from "../components/site/Navbar";
import Footer from "../components/site/Footer";
import ParticleField from "../components/site/ParticleField";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;
const EASE = [0.16, 1, 0.3, 1];
const STATUS_POLL_MS = 60000;

const STRATEGIES = [
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

const TradeLogTable = ({ trades, showCharts = false }) => (
  <div className="overflow-x-auto" data-testid="prism-alpha-trade-log">
    <table className="w-full text-left min-w-[600px]">
      <thead>
        <tr className="border-b border-white/10">
          {["Date", "Dir", "Entry", "Exit", "P&L", "Duration", ...(showCharts ? ["Chart"] : [])].map((h) => (
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
            {showCharts && (
              <td className="px-4 py-3 text-sm whitespace-nowrap">
                {t.chart_url ? (
                  <a href={`${API}${t.chart_url}`} target="_blank" rel="noreferrer" className="text-sapphire-light hover:underline" data-testid={`backtest-chart-link-${t.id}`}>
                    View
                  </a>
                ) : "—"}
              </td>
            )}
          </tr>
        ))}
      </tbody>
    </table>
  </div>
);

const TrackRecord = ({ stats, trades, emptyMessage, showCharts = false }) => (
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
        <TradeLogTable trades={trades} showCharts={showCharts} />
      </div>
    )}
  </>
);

const fmtDate = (iso) => {
  if (!iso) return "—";
  const [y, m, d] = iso.split("-");
  const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  return `${d} ${MONTHS[Number(m) - 1]} ${y}`;
};

const PrismAlphaCard = ({ no, apiPath, title, subtitle, testId }) => {
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
        axios.get(`${API}/blackbox/${apiPath}/status`),
        axios.get(`${API}/blackbox/${apiPath}/stats`),
        axios.get(`${API}/blackbox/${apiPath}/trades`),
        axios.get(`${API}/blackbox/${apiPath}/backtest/summary`),
        axios.get(`${API}/blackbox/${apiPath}/backtest/trades`),
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
  }, [apiPath]);

  const inPosition = status?.position === "in_position";
  const direction = status?.today_signal?.direction;

  return (
    <div className="glass rounded-2xl p-6 md:p-8 mb-4" data-testid={testId}>
      <div className="flex flex-wrap items-center justify-between gap-3 mb-6">
        <div>
          <span className="font-mono-ui text-xs text-sapphire-light mb-1 block">{no}</span>
          <h4 className="font-display text-2xl font-bold text-white">{title}</h4>
          <p className="text-sm font-light text-slate-500 mt-1">{subtitle}</p>
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
            data-testid={`${testId}-status-badge`}
          >
            <span className={`h-1.5 w-1.5 rounded-full ${inPosition ? (direction === "CE" ? "bg-emerald-400" : "bg-red-400") : "bg-slate-400"}`} />
            {inPosition ? `In Position — ${direction}` : "Flat"}
          </span>
        )}
      </div>

      <div className="flex gap-2 mb-6 border-b border-white/10" data-testid={`${testId}-tabs`}>
        {[{ key: "live", label: "Live" }, { key: "backtest", label: "Backtest", disabled: true }].map((t) => (
          <button
            key={t.key}
            onClick={() => !t.disabled && setTab(t.key)}
            disabled={t.disabled}
            title={t.disabled ? "Coming soon" : undefined}
            className={`px-4 py-2 font-mono-ui text-xs uppercase tracking-[0.14em] border-b-2 transition-colors duration-200 ${
              t.disabled
                ? "border-transparent text-slate-600 cursor-not-allowed opacity-50"
                : tab === t.key ? "border-sapphire-light text-sapphire-light" : "border-transparent text-slate-500 hover:text-slate-300"
            }`}
            data-testid={`${testId}-tab-${t.key}`}
          >
            {t.label}
          </button>
        ))}
      </div>

      {!loading && tab === "live" && stats && (
        <TrackRecord stats={stats} trades={trades} emptyMessage={`No closed trades yet — track record will appear here once ${title} has completed live trades.`} />
      )}

      {!loading && tab === "backtest" && (
        <>
          {backtestRun ? (
            <div className="mb-6 rounded-xl border border-white/10 bg-white/[0.03] px-4 py-3" data-testid={`${testId}-backtest-meta`}>
              <p className="text-xs text-slate-400">
                Backtest window: <span className="text-white font-medium">{fmtDate(backtestRun.start_date)} – {fmtDate(backtestRun.end_date)}</span>
                {" · "}Data: <span className="text-white font-medium">real 1-minute premium data</span>
                {" · "}{backtestRun.spot_ticks_evaluated} minute ticks evaluated
              </p>
            </div>
          ) : (
            <p className="text-sm text-slate-500 py-6 text-center" data-testid={`${testId}-backtest-none`}>
              No backtest has been run yet.
            </p>
          )}
          {backtestStats && (
            <TrackRecord
              stats={backtestStats}
              trades={backtestTrades}
              showCharts
              emptyMessage="No trades were generated in this backtest window — entry conditions are strict and didn't align, which is a real result, not an error."
            />
          )}
          <p className="text-[11px] font-light text-amber-400/70 mt-6" data-testid={`${testId}-backtest-disclaimer`}>
            Backtested results are hypothetical, computed from real intraday option premium data over roughly the last 1-2 weeks — kept short
            so it stays within a single real weekly expiry cycle, matching how the live strategy actually rolls contracts — and do not
            guarantee live performance.
          </p>
        </>
      )}

      <p className="text-[11px] font-light text-slate-600 mt-6 pt-4 border-t border-white/10" data-testid={`${testId}-disclaimer`}>
        Performance shown is for research/educational purposes only, not investment advice. Past performance does not guarantee future results.
      </p>
    </div>
  );
};

const PhaseBadge = ({ label, phase }) => (
  <span
    className={`inline-flex items-center gap-2 rounded-full border px-3 py-1.5 text-xs font-medium ${
      phase === "buy"
        ? "border-emerald-400/30 bg-emerald-400/10 text-emerald-300"
        : "border-slate-400/25 bg-slate-400/10 text-slate-300"
    }`}
    data-testid={`lumen-sip-phase-${label.toLowerCase()}`}
  >
    <span className={`h-1.5 w-1.5 rounded-full ${phase === "buy" ? "bg-emerald-400" : "bg-slate-400"}`} />
    {label} — {phase === "buy" ? "SIP Active" : "Cash"}
  </span>
);

const fmtINR = (n, decimals = 0) =>
  n == null ? "—" : `₹${n.toLocaleString("en-IN", { minimumFractionDigits: decimals, maximumFractionDigits: decimals })}`;

const fmtSignedPct = (n, decimals = 1) => {
  if (n == null) return "—";
  const sign = n > 0 ? "+" : "";
  return `${sign}${n.toFixed(decimals)}%`;
};

// Merges the strategy's own (brick-event-dated) equity curve with the
// vanilla-SIP benchmark's (daily-dated) curve onto one shared timeline —
// the two have different date samplings, so this looks up the closest
// vanilla point at-or-before each strategy point rather than assuming
// matching indices/dates.
const mergeWithVanilla = (portfolio, vanillaCurve) => {
  if (!vanillaCurve?.length) return portfolio.map((p) => ({ ...p, vanilla_value: null }));
  let vi = 0;
  return portfolio.map((p) => {
    while (vi + 1 < vanillaCurve.length && vanillaCurve[vi + 1].date <= p.date) vi++;
    return { ...p, vanilla_value: vanillaCurve[vi].date <= p.date ? vanillaCurve[vi].value : null };
  });
};

const LumenSipEquityChart = ({ portfolio, vanillaCurve }) => {
  // ~2400 daily/brick snapshots is more resolution than the chart needs —
  // sample down, always keeping the most recent point.
  const step = Math.max(1, Math.floor(portfolio.length / 350));
  const sampled = portfolio.filter((_, i) => i % step === 0 || i === portfolio.length - 1);
  const merged = mergeWithVanilla(sampled, vanillaCurve).map((p) => ({
    date: fmtDate(p.date),
    total_value: p.total_value,
    vanilla_value: p.vanilla_value,
  }));

  return (
    <div className="h-72" data-testid="lumen-sip-equity-chart">
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={merged} margin={{ top: 10, right: 10, left: 0, bottom: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.06)" vertical={false} />
          <XAxis dataKey="date" tick={{ fill: "#64748B", fontSize: 10 }} axisLine={{ stroke: "rgba(255,255,255,0.1)" }} tickLine={false} minTickGap={50} />
          <YAxis tick={{ fill: "#64748B", fontSize: 11 }} axisLine={false} tickLine={false} domain={["auto", "auto"]} width={64}
            tickFormatter={(v) => `₹${(v / 1000).toFixed(0)}k`} />
          <Tooltip
            contentStyle={{ background: "#0A0D18", border: "1px solid rgba(255,255,255,0.1)", borderRadius: 8, fontSize: 12 }}
            labelStyle={{ color: "#94A3B8" }}
            itemStyle={{ color: "#E2E8F0" }}
            formatter={(v, name) => [v == null ? "—" : `₹${v.toLocaleString("en-IN", { maximumFractionDigits: 0 })}`, name]}
          />
          <Line type="monotone" dataKey="total_value" name="Lumen SIP" stroke="#437EEB" strokeWidth={2} dot={false} isAnimationActive={false} />
          <Line type="monotone" dataKey="vanilla_value" name="Vanilla SIP" stroke="#D9A441" strokeWidth={1.5} strokeDasharray="5 4" dot={false} isAnimationActive={false} />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
};

const LumenSipTradeTable = ({ signals, instrument }) => {
  const sigs = signals.filter((s) => s.instrument === instrument);
  const trips = [];
  let buy = null;
  for (const s of sigs) {
    if (s.signal_type === "buy") buy = s;
    else if (s.signal_type === "sell" && buy) { trips.push([buy, s]); buy = null; }
  }
  trips.reverse();

  if (trips.length === 0) return <p className="text-sm text-slate-500 py-4 text-center">No completed round-trips yet.</p>;

  return (
    <div className="overflow-x-auto" data-testid={`lumen-sip-trades-${instrument.toLowerCase()}`}>
      <table className="w-full text-left min-w-[420px]">
        <thead>
          <tr className="border-b border-white/10">
            {["Buy", "Sell", "Hold", "Return"].map((h) => (
              <th key={h} className="px-3 py-2.5 font-mono-ui text-[10px] uppercase tracking-[0.14em] text-slate-500 font-semibold whitespace-nowrap">
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {trips.map(([b, s], i) => {
            const ret = ((s.price - b.price) / b.price) * 100;
            const days = Math.round((new Date(s.date) - new Date(b.date)) / 86400000);
            return (
              <tr key={i} className="border-b border-white/[0.05] last:border-0">
                <td className="px-3 py-2 font-mono-ui text-xs text-slate-300 whitespace-nowrap">{fmtDate(b.date)} · ₹{b.price.toFixed(2)}</td>
                <td className="px-3 py-2 font-mono-ui text-xs text-slate-300 whitespace-nowrap">{fmtDate(s.date)} · ₹{s.price.toFixed(2)}</td>
                <td className="px-3 py-2 font-mono-ui text-xs text-slate-400 whitespace-nowrap">{days}d</td>
                <td className={`px-3 py-2 font-mono-ui text-xs whitespace-nowrap ${ret >= 0 ? "text-emerald-400" : "text-red-400"}`}>
                  {fmtSignedPct(ret, 2)}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
};

const LumenSipInstrumentCard = ({ label, m, signals, accentClass }) => {
  const ts = m.trade_stats;
  return (
    <div className="rounded-xl border border-white/10 bg-white/[0.02] p-5" data-testid={`lumen-sip-instrument-${label.toLowerCase()}`}>
      <div className="flex items-center justify-between mb-1">
        <span className={`font-mono-ui font-bold text-sm tracking-wide ${accentClass}`}>{label}</span>
        <span className="font-mono-ui text-xs text-slate-500">{m.allocation_pct.toFixed(0)}% allocation</span>
      </div>
      <p className="text-xs text-slate-500 mb-4">{fmtINR(m.total_invested)} invested → {fmtINR(m.final_value)} today</p>

      <div className="grid grid-cols-2 gap-3 mb-4">
        <StatBlock label="XIRR" value={fmtSignedPct(m.xirr_pct)} valueClass="text-emerald-400" />
        <StatBlock label="Max Drawdown" value={`-${m.max_drawdown_pct.toFixed(1)}%`} valueClass="text-red-400" />
        <StatBlock label="Time in Market" value={`${m.time_in_market_pct.toFixed(0)}%`} />
        <StatBlock label="Trades / Win Rate" value={ts.count ? `${ts.count} · ${ts.win_rate_pct.toFixed(0)}%` : "—"} />
      </div>

      <div className="h-1.5 rounded-full bg-white/5 overflow-hidden mb-5">
        <div className={`h-full rounded-full ${accentClass.replace("text-", "bg-")}`} style={{ width: `${m.time_in_market_pct}%` }} />
      </div>

      <p className="font-mono-ui text-[10px] uppercase tracking-[0.16em] text-slate-500 mb-2">Round-Trip Trade Log ({ts.count})</p>
      <LumenSipTradeTable signals={signals} instrument={label} />
    </div>
  );
};

const LumenSIPCard = () => {
  const [metrics, setMetrics] = useState(null);
  const [portfolio, setPortfolio] = useState([]);
  const [signals, setSignals] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    const load = () => {
      Promise.all([
        axios.get(`${API}/blackbox/lumen-sip/backtest/metrics`),
        axios.get(`${API}/blackbox/lumen-sip/backtest/portfolio`),
        axios.get(`${API}/blackbox/lumen-sip/backtest/signals`),
      ])
        .then(([m, p, sg]) => {
          if (cancelled) return;
          setMetrics(m.data);
          setPortfolio(p.data);
          setSignals(sg.data);
        })
        .catch(() => {})
        .finally(() => { if (!cancelled) setLoading(false); });
    };
    load();
    const interval = setInterval(load, STATUS_POLL_MS);
    return () => { cancelled = true; clearInterval(interval); };
  }, []);

  const hasData = metrics?.has_data;

  return (
    <div className="glass rounded-2xl p-6 md:p-8 mb-4" data-testid="lumen-sip-card">
      <div className="flex flex-wrap items-start justify-between gap-4 mb-6">
        <div>
          <span className="font-mono-ui text-xs text-sapphire-light mb-1 block">03</span>
          <h4 className="font-display text-2xl font-bold text-white">Lumen SIP</h4>
          <p className="text-sm font-light text-slate-500 mt-1">Long-term ETF trend-following allocation — NIFTYBEES &amp; GOLDBEES</p>
        </div>
        <button
          type="button"
          disabled
          title="Coming soon"
          className="inline-flex items-center gap-2 rounded-full border border-white/10 bg-white/[0.03] px-4 py-2 text-xs font-medium text-slate-500 cursor-not-allowed whitespace-nowrap"
          data-testid="lumen-sip-alerts-btn"
        >
          <Bell size={14} />
          Get Alerts — Coming Soon
        </button>
      </div>

      {loading && (
        <div className="flex items-center gap-2 text-slate-500 text-sm py-10 justify-center">
          <Loader2 className="animate-spin" size={14} /> Loading
        </div>
      )}

      {!loading && hasData && (
        <>
          <div className="flex flex-wrap gap-2 mb-6">
            <PhaseBadge label="NIFTYBEES" phase={metrics.current_phase.NIFTYBEES} />
            <PhaseBadge label="GOLDBEES" phase={metrics.current_phase.GOLDBEES} />
            <span className="font-mono-ui text-[11px] text-slate-500 self-center ml-1">
              {metrics.period.months} months · {fmtDate(metrics.period.start)} → {fmtDate(metrics.period.end)}
            </span>
          </div>

          <div className="grid grid-cols-2 md:grid-cols-5 gap-4 mb-6">
            <StatBlock label="Total Invested" value={fmtINR(metrics.portfolio.total_invested)} />
            <StatBlock label="Final Value" value={fmtINR(metrics.portfolio.final_value)} valueClass="text-emerald-400" />
            <StatBlock label="Absolute Return" value={fmtSignedPct(metrics.portfolio.absolute_return_pct)} valueClass="text-emerald-400" />
            <StatBlock label="XIRR" value={fmtSignedPct(metrics.portfolio.xirr_pct)} valueClass="text-emerald-400" />
            <StatBlock label="Max Drawdown" value={`-${metrics.portfolio.max_drawdown_pct.toFixed(1)}%`} valueClass="text-red-400" />
          </div>

          {portfolio.length > 1 && (
            <LumenSipEquityChart portfolio={portfolio} vanillaCurve={metrics.vanilla_sip.curve} />
          )}
          <div className="flex flex-wrap gap-4 mt-3 mb-8 font-mono-ui text-[11px] text-slate-500">
            <span className="inline-flex items-center gap-1.5"><i className="h-2.5 w-2.5 rounded-sm inline-block bg-[#437EEB]" />Lumen SIP</span>
            <span className="inline-flex items-center gap-1.5"><i className="h-2.5 w-2.5 rounded-sm inline-block bg-[#D9A441]" />Vanilla SIP (no signal, dashed)</span>
          </div>

          <div className="mb-8">
            <p className="font-mono-ui text-[10px] uppercase tracking-[0.18em] text-slate-500 mb-3">Strategy vs. Vanilla SIP</p>
            <p className="text-xs text-slate-500 mb-3">Same ₹5,000/month, same 75/25 split, same period — vanilla just buys every month with no signal at all.</p>
            <div className="overflow-x-auto">
              <table className="w-full text-left min-w-[560px]">
                <thead>
                  <tr className="border-b border-white/10">
                    {["", "Invested", "Final Value", "Return", "XIRR", "Max Drawdown"].map((h) => (
                      <th key={h} className="px-3 py-2.5 font-mono-ui text-[10px] uppercase tracking-[0.14em] text-slate-500 font-semibold whitespace-nowrap">{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  <tr className="border-b border-white/[0.05]">
                    <td className="px-3 py-2.5 text-sm text-white whitespace-nowrap">Lumen SIP (this strategy)</td>
                    <td className="px-3 py-2.5 font-mono-ui text-xs text-slate-300 whitespace-nowrap">{fmtINR(metrics.portfolio.total_invested)}</td>
                    <td className="px-3 py-2.5 font-mono-ui text-xs text-emerald-400 whitespace-nowrap">{fmtINR(metrics.portfolio.final_value)}</td>
                    <td className="px-3 py-2.5 font-mono-ui text-xs text-emerald-400 whitespace-nowrap">{fmtSignedPct(metrics.portfolio.absolute_return_pct)}</td>
                    <td className="px-3 py-2.5 font-mono-ui text-xs text-emerald-400 whitespace-nowrap">{fmtSignedPct(metrics.portfolio.xirr_pct)}</td>
                    <td className="px-3 py-2.5 font-mono-ui text-xs text-red-400 whitespace-nowrap">-{metrics.portfolio.max_drawdown_pct.toFixed(1)}%</td>
                  </tr>
                  <tr>
                    <td className="px-3 py-2.5 text-sm text-slate-300 whitespace-nowrap">Vanilla monthly SIP</td>
                    <td className="px-3 py-2.5 font-mono-ui text-xs text-slate-300 whitespace-nowrap">{fmtINR(metrics.vanilla_sip.total_invested)}</td>
                    <td className="px-3 py-2.5 font-mono-ui text-xs text-slate-300 whitespace-nowrap">{fmtINR(metrics.vanilla_sip.final_value)}</td>
                    <td className="px-3 py-2.5 font-mono-ui text-xs text-slate-300 whitespace-nowrap">{fmtSignedPct(metrics.vanilla_sip.absolute_return_pct)}</td>
                    <td className="px-3 py-2.5 font-mono-ui text-xs text-slate-300 whitespace-nowrap">{fmtSignedPct(metrics.vanilla_sip.xirr_pct)}</td>
                    <td className="px-3 py-2.5 font-mono-ui text-xs text-red-400/80 whitespace-nowrap">-{metrics.vanilla_sip.max_drawdown_pct.toFixed(1)}%</td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>

          <p className="font-mono-ui text-[10px] uppercase tracking-[0.18em] text-slate-500 mb-3">Per-Instrument Breakdown</p>
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            <LumenSipInstrumentCard label="NIFTYBEES" m={metrics.niftybees} signals={signals} accentClass="text-sapphire-light" />
            <LumenSipInstrumentCard label="GOLDBEES" m={metrics.goldbees} signals={signals} accentClass="text-amber-400" />
          </div>
        </>
      )}

      {!loading && !hasData && (
        <p className="text-sm text-slate-500 py-10 text-center" data-testid="lumen-sip-empty">
          No backtest data yet — will appear here once evaluated.
        </p>
      )}

      <p className="text-[11px] font-light text-slate-600 mt-6 pt-4 border-t border-white/10" data-testid="lumen-sip-disclaimer">
        This is a systematic long-term allocation framework based on publicly available research (Definedge), not a personalized
        investment recommendation; backtested/simulated results are hypothetical and past performance does not guarantee future results.
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
            <PrismAlphaCard
              no="01"
              apiPath="prism-alpha"
              title="Prism Alpha"
              subtitle="Quantitative options signal engine"
              testId="prism-alpha-card"
            />
            <PrismAlphaCard
              no="02"
              apiPath="prism-alpha-2"
              title="Prism Alpha 2"
              subtitle="Quantitative options signal engine — comparison track"
              testId="prism-alpha-2-card"
            />
            <LumenSIPCard />
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
