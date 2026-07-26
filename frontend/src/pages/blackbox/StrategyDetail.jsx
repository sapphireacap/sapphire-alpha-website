import { useEffect, useMemo, useState } from "react";
import { Link, useParams, useNavigate } from "react-router-dom";
import { motion } from "framer-motion";
import {
  ArrowLeft, ArrowUpRight, Bell, ChevronDown, Download, Loader2, TrendingUp, TrendingDown,
} from "lucide-react";
import {
  ResponsiveContainer, LineChart, Line, AreaChart, Area, BarChart, Bar,
  XAxis, YAxis, CartesianGrid, Tooltip, ReferenceLine,
} from "recharts";
import Navbar from "../../components/site/Navbar";
import Footer from "../../components/site/Footer";
import { getStrategy, RISK_DISCLOSURE } from "./strategies";
import { fetchStrategyView } from "./adapters";
import { RANGES, filterByRange, tradesToCSV, downloadCSV } from "../../lib/strategyStats";

const EASE = [0.16, 1, 0.3, 1];
const SURFACE = "rounded-2xl border border-white/10 bg-[#0A0D18]";

const TONE_TEXT = { pos: "text-emerald-400", neg: "text-red-400", neutral: "text-white" };

// Narrow-viewport-only collapse (matches the Tailwind `md` breakpoint) —
// desktop/tablet always show sections fully open, since the spec calls
// this out specifically as a mobile pattern ("single-column with
// collapsible analytics sections"), not a general progressive-disclosure
// mechanism for every screen size.
const useIsMobile = () => {
  const [isMobile, setIsMobile] = useState(() => typeof window !== "undefined" && window.innerWidth < 768);
  useEffect(() => {
    const mq = window.matchMedia("(max-width: 767px)");
    const onChange = () => setIsMobile(mq.matches);
    onChange();
    mq.addEventListener("change", onChange);
    return () => mq.removeEventListener("change", onChange);
  }, []);
  return isMobile;
};

const Section = ({ no, title, children, testId, collapsible = false }) => {
  const isMobile = useIsMobile();
  const canCollapse = collapsible && isMobile;
  // Analytics sections start collapsed on mobile (shortens the initial
  // scroll) but open on every other breakpoint — computed once at mount
  // from the same check useIsMobile uses, so there's no first-paint flash.
  const [open, setOpen] = useState(() => !(collapsible && typeof window !== "undefined" && window.innerWidth < 768));

  return (
    <motion.section
      initial={{ opacity: 0, y: 16 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.6, ease: EASE }}
      className="py-10 md:py-14 border-t border-white/[0.06]"
      data-testid={testId}
    >
      <div
        className={`flex items-center justify-between gap-3 ${open ? "mb-6 md:mb-8" : ""} ${canCollapse ? "cursor-pointer" : ""}`}
        onClick={canCollapse ? () => setOpen((o) => !o) : undefined}
      >
        <div className="flex items-baseline gap-3">
          <span className="font-mono-ui text-xs text-sapphire-light">{no}</span>
          <h2 className="font-display text-2xl md:text-3xl font-bold text-white tracking-tight">{title}</h2>
        </div>
        {canCollapse && (
          <ChevronDown size={18} className={`text-slate-500 transition-transform duration-300 shrink-0 ${open ? "rotate-180" : ""}`} />
        )}
      </div>
      {(!canCollapse || open) && children}
    </motion.section>
  );
};

const ChartTooltip = ({ active, payload, label, formatter }) =>
  active && payload?.length ? (
    <div className="rounded-lg border border-white/10 bg-[#050710] px-3 py-2.5 text-xs">
      <p className="text-slate-500 mb-1.5 font-mono-ui">{label}</p>
      {payload.map((p) => (
        <p key={p.dataKey} style={{ color: p.color }} className="font-mono-ui">
          {p.name}: {formatter ? formatter(p.value) : p.value}
        </p>
      ))}
    </div>
  ) : null;

/* --------------------------------- Header --------------------------------- */
const Header = ({ strategy, view }) => (
  <section className="relative pt-28 pb-10 md:pt-32 md:pb-14" data-testid="strategy-header">
    <div className="container-x">
      <Link to="/black-box" className="inline-flex items-center gap-2 text-sm text-slate-400 hover:text-white transition-colors mb-8" data-testid="back-to-black-box">
        <ArrowLeft size={15} /> Back to Black Box
      </Link>

      <div className="flex flex-col lg:flex-row lg:items-end lg:justify-between gap-8">
        <div className="max-w-2xl">
          <p className="font-mono-ui text-xs text-sapphire-light mb-2">Strategy #{strategy.no}</p>
          <h1 className="font-display font-black tracking-tighter text-white text-5xl md:text-6xl leading-[0.95]">{strategy.title}</h1>
          <p className="mt-4 text-base font-light text-slate-400">{strategy.subtitle}</p>

          <div className="flex items-center gap-2 mt-6">
            <span className="relative flex h-2 w-2">
              {strategy.status === "Operational" && <span className="absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-60 animate-ping" />}
              <span className={`relative inline-flex h-2 w-2 rounded-full ${strategy.status === "Operational" ? "bg-emerald-400" : "bg-slate-500"}`} />
            </span>
            <span className={`font-mono-ui text-xs uppercase tracking-wider ${strategy.status === "Operational" ? "text-emerald-300" : "text-slate-400"}`}>
              {strategy.status}
            </span>
            {view && <span className="text-xs text-slate-600 ml-2">· {view.windowLabel}</span>}
          </div>

          <div className="flex flex-wrap gap-2 mt-5">
            {strategy.tags.map((t) => (
              <span key={t} className="rounded-full border border-white/10 px-3 py-1 font-mono-ui text-[10px] uppercase tracking-wider text-slate-400">
                {t}
              </span>
            ))}
          </div>
        </div>

        <div className="flex flex-col gap-4 shrink-0">
          <div className="flex gap-6">
            {strategy.facts.map((f) => (
              <div key={f.label}>
                <p className="font-mono-ui text-[10px] uppercase tracking-[0.16em] text-slate-500 mb-1 whitespace-nowrap">{f.label}</p>
                <p className="text-base text-white font-medium whitespace-nowrap">{f.value}</p>
              </div>
            ))}
          </div>
          <div className="flex gap-3">
            <button type="button" disabled title="Coming soon" className="inline-flex items-center justify-center gap-2 rounded-full bg-[#1F5FD0]/40 px-6 py-2.5 text-sm font-semibold text-white/70 cursor-not-allowed whitespace-nowrap" data-testid="deploy-btn">
              Deploy — Coming Soon
            </button>
            <button type="button" disabled title="Coming soon" className="inline-flex items-center justify-center gap-2 rounded-full border border-white/15 px-5 py-2.5 text-sm font-medium text-slate-500 cursor-not-allowed whitespace-nowrap" data-testid="subscribe-btn">
              <Bell size={14} /> Subscribe
            </button>
          </div>
        </div>
      </div>
    </div>
  </section>
);

/* ----------------------------- Executive Summary ----------------------------- */
const SummaryRow = ({ label, value }) => (
  <div className="py-4 border-b border-white/[0.06] last:border-0 grid grid-cols-1 sm:grid-cols-[180px_1fr] gap-1 sm:gap-6">
    <p className="font-mono-ui text-[10px] uppercase tracking-[0.16em] text-slate-500">{label}</p>
    <p className="text-sm text-slate-300 leading-relaxed">{value}</p>
  </div>
);

const ExecutiveSummary = ({ summary }) => (
  <Section no="01" title="Executive Summary" testId="section-executive-summary">
    <div className={`${SURFACE} p-6 md:p-8`}>
      <p className="text-lg font-light text-white leading-relaxed mb-6 max-w-3xl">{summary.what}</p>
      <div>
        <SummaryRow label="Market" value={summary.market} />
        <SummaryRow label="Objective" value={summary.objective} />
        <SummaryRow label="Risk Profile" value={summary.riskProfile} />
        <SummaryRow label="Holding Period" value={summary.holdingPeriod} />
        <SummaryRow label="Execution Style" value={summary.executionStyle} />
        <SummaryRow label="Suitable Investor" value={summary.suitableInvestor} />
      </div>
    </div>
  </Section>
);

/* ---------------------------- Performance Snapshot ---------------------------- */
const KpiCard = ({ k }) => (
  <div className={`${SURFACE} p-4`} data-testid={`kpi-${k.key}`} title={k.note || undefined}>
    <p className="font-mono-ui text-[9px] uppercase tracking-[0.14em] text-slate-500 mb-1.5 leading-tight">{k.label}</p>
    <p className={`font-mono-ui text-xl font-bold tracking-tight ${TONE_TEXT[k.tone] || "text-white"}`}>{k.value}</p>
  </div>
);

const PerformanceSnapshot = ({ kpis }) => (
  <Section no="02" title="Performance Snapshot" testId="section-performance-snapshot">
    {kpis.length ? (
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5 gap-3">
        {kpis.map((k) => <KpiCard key={k.key} k={k} />)}
      </div>
    ) : (
      <p className="text-sm text-slate-500">Not enough closed trades yet to compute performance metrics.</p>
    )}
  </Section>
);

/* ------------------------------- Equity Curve ------------------------------- */
const EquityCurveSection = ({ equityCurve, benchmarkCurve, benchmarkLabel, isPct }) => {
  const [range, setRange] = useState("ALL");
  const filtered = useMemo(() => filterByRange(equityCurve, range), [equityCurve, range]);
  const filteredBench = useMemo(() => (benchmarkCurve ? filterByRange(benchmarkCurve, range) : null), [benchmarkCurve, range]);
  const benchByDate = useMemo(() => (filteredBench ? new Map(filteredBench.map((p) => [p.date, p.value])) : null), [filteredBench]);

  const merged = filtered.map((p) => ({ date: p.date, value: p.value, benchmark: benchByDate?.get(p.date) ?? null }));

  return (
    <Section no="03" title="Equity Curve" testId="section-equity-curve">
      <div className={`${SURFACE} p-5 md:p-7`}>
        <div className="flex items-center justify-between flex-wrap gap-3 mb-6">
          <div className="flex items-center gap-4 font-mono-ui text-[11px] text-slate-500">
            <span className="inline-flex items-center gap-1.5"><i className="h-2.5 w-2.5 rounded-sm inline-block bg-[#437EEB]" />Strategy</span>
            {benchmarkCurve && <span className="inline-flex items-center gap-1.5"><i className="h-2.5 w-2.5 rounded-sm inline-block bg-[#D9A441]" />{benchmarkLabel}</span>}
          </div>
          <div className="flex gap-1" data-testid="equity-range-selector">
            {RANGES.map((r) => (
              <button
                key={r}
                type="button"
                onClick={() => setRange(r)}
                className={`px-3 py-1.5 rounded-md font-mono-ui text-[11px] uppercase tracking-wider transition-colors duration-200 ${
                  range === r ? "bg-white/[0.08] text-white border border-white/10" : "text-slate-500 hover:text-slate-300"
                }`}
                data-testid={`equity-range-${r}`}
              >
                {r}
              </button>
            ))}
          </div>
        </div>

        {merged.length > 1 ? (
          <div className="h-80" data-testid="equity-curve-chart">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={merged} margin={{ top: 4, right: 8, left: 0, bottom: 0 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.06)" vertical={false} />
                <XAxis dataKey="date" tick={{ fill: "#64748B", fontSize: 10 }} axisLine={{ stroke: "rgba(255,255,255,0.1)" }} tickLine={false} minTickGap={60} />
                <YAxis
                  tick={{ fill: "#64748B", fontSize: 11 }}
                  axisLine={false}
                  tickLine={false}
                  domain={["auto", "auto"]}
                  width={64}
                  tickFormatter={(v) => (isPct ? `${v.toFixed(0)}%` : `₹${(v / 1000).toFixed(0)}k`)}
                />
                <Tooltip content={<ChartTooltip formatter={(v) => (isPct ? `${v.toFixed(2)}%` : `₹${v.toLocaleString("en-IN", { maximumFractionDigits: 0 })}`)} />} />
                <Line type="monotone" dataKey="value" name="Strategy" stroke="#437EEB" strokeWidth={2} dot={false} isAnimationActive animationDuration={700} />
                {benchmarkCurve && (
                  <Line type="monotone" dataKey="benchmark" name={benchmarkLabel} stroke="#D9A441" strokeWidth={1.5} strokeDasharray="5 4" dot={false} isAnimationActive animationDuration={700} />
                )}
              </LineChart>
            </ResponsiveContainer>
          </div>
        ) : (
          <p className="text-sm text-slate-500 py-16 text-center">Not enough data yet to plot an equity curve.</p>
        )}
      </div>
    </Section>
  );
};

/* ----------------------------- Drawdown Analysis ----------------------------- */
const DrawdownSection = ({ drawdownCurve, worstDrawdowns }) => (
  <Section no="04" title="Drawdown Analysis" testId="section-drawdown" collapsible>
    <div className={`${SURFACE} p-5 md:p-7 mb-5`}>
      {drawdownCurve.length > 1 ? (
        <div className="h-56" data-testid="drawdown-chart">
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={drawdownCurve} margin={{ top: 4, right: 8, left: 0, bottom: 0 }}>
              <defs>
                <linearGradient id="ddFill" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="#F87171" stopOpacity={0.35} />
                  <stop offset="100%" stopColor="#F87171" stopOpacity={0.02} />
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.06)" vertical={false} />
              <XAxis dataKey="date" tick={{ fill: "#64748B", fontSize: 10 }} axisLine={{ stroke: "rgba(255,255,255,0.1)" }} tickLine={false} minTickGap={60} />
              <YAxis tick={{ fill: "#64748B", fontSize: 11 }} axisLine={false} tickLine={false} width={54} tickFormatter={(v) => `${v.toFixed(0)}%`} />
              <ReferenceLine y={0} stroke="rgba(255,255,255,0.15)" />
              <Tooltip content={<ChartTooltip formatter={(v) => `${v.toFixed(2)}%`} />} />
              <Area type="monotone" dataKey="ddPct" name="Drawdown" stroke="#F87171" strokeWidth={1.5} fill="url(#ddFill)" isAnimationActive animationDuration={700} />
            </AreaChart>
          </ResponsiveContainer>
        </div>
      ) : (
        <p className="text-sm text-slate-500 py-10 text-center">Not enough data yet to plot drawdowns.</p>
      )}
    </div>

    {worstDrawdowns.length > 0 && (
      <div className={`${SURFACE} overflow-hidden`}>
        <div className="overflow-x-auto">
          <table className="w-full text-left min-w-[520px]">
            <thead>
              <tr className="border-b border-white/10">
                {["Peak", "Trough", "Depth", "Recovered", "Recovery Time"].map((h) => (
                  <th key={h} className="px-5 py-3 font-mono-ui text-[10px] uppercase tracking-[0.14em] text-slate-500 font-semibold whitespace-nowrap">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {worstDrawdowns.map((d, i) => (
                <tr key={i} className="border-b border-white/[0.05] last:border-0">
                  <td className="px-5 py-3 text-sm text-slate-300 whitespace-nowrap">{d.peakDate}</td>
                  <td className="px-5 py-3 text-sm text-slate-300 whitespace-nowrap">{d.troughDate}</td>
                  <td className="px-5 py-3 font-mono-ui text-sm text-red-400 whitespace-nowrap">{d.depthPct.toFixed(2)}%</td>
                  <td className="px-5 py-3 text-sm whitespace-nowrap">{d.recoveryDate ? <span className="text-emerald-400">Yes</span> : <span className="text-amber-400">Ongoing</span>}</td>
                  <td className="px-5 py-3 font-mono-ui text-sm text-slate-400 whitespace-nowrap">{d.recoveryDays != null ? `${d.recoveryDays}d` : "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    )}
  </Section>
);

/* ---------------------------- Monthly Performance ---------------------------- */
const MONTH_LABELS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

const heatColor = (pct) => {
  if (pct == null) return null;
  const a = Math.min(1, Math.abs(pct) / 8);
  return pct >= 0 ? `rgba(52,211,153,${0.12 + a * 0.55})` : `rgba(248,113,113,${0.12 + a * 0.55})`;
};

const MonthlyHeatmap = ({ monthly }) => {
  const byYear = useMemo(() => {
    const map = new Map();
    for (const m of monthly) {
      const [y, mo] = m.month.split("-");
      if (!map.has(y)) map.set(y, Array(12).fill(null));
      map.get(y)[Number(mo) - 1] = m.pct;
    }
    return [...map.entries()].sort((a, b) => b[0].localeCompare(a[0]));
  }, [monthly]);

  return (
    <Section no="05" title="Monthly Performance" testId="section-monthly-heatmap" collapsible>
      {byYear.length ? (
        <div className={`${SURFACE} p-5 md:p-7 overflow-x-auto`}>
          <table className="w-full min-w-[640px] border-separate" style={{ borderSpacing: 4 }}>
            <thead>
              <tr>
                <th className="w-14" />
                {MONTH_LABELS.map((m) => (
                  <th key={m} className="font-mono-ui text-[10px] uppercase tracking-wider text-slate-500 font-semibold pb-2">{m}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {byYear.map(([year, months]) => (
                <tr key={year}>
                  <td className="font-mono-ui text-xs text-slate-400 pr-3">{year}</td>
                  {months.map((pct, i) => (
                    <td key={i}>
                      <div
                        className={`h-10 rounded-md flex items-center justify-center font-mono-ui text-[10px] ${pct == null ? "bg-white/[0.02]" : ""}`}
                        style={pct != null ? { background: heatColor(pct) } : undefined}
                        title={pct != null ? `${year}-${String(i + 1).padStart(2, "0")}: ${pct.toFixed(2)}%` : "No data"}
                        data-testid={`heatmap-cell-${year}-${i}`}
                      >
                        {pct != null && <span className={pct >= 0 ? "text-emerald-200" : "text-red-200"}>{pct.toFixed(1)}</span>}
                      </div>
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <p className="text-sm text-slate-500">Not enough data yet for a monthly breakdown.</p>
      )}
    </Section>
  );
};

/* ------------------------------- Risk Analytics ------------------------------- */
const RiskCard = ({ label, value, testId }) => (
  <div className={`${SURFACE} p-5 text-center`} data-testid={testId}>
    <p className="font-mono-ui text-[10px] uppercase tracking-[0.16em] text-slate-500 mb-2">{label}</p>
    <p className="font-mono-ui text-2xl font-bold text-white">{value}</p>
  </div>
);

const RiskAnalytics = ({ metrics }) => (
  <Section no="06" title="Risk Analytics" testId="section-risk-analytics" collapsible>
    <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
      <RiskCard testId="risk-volatility" label="Volatility (Ann.)" value={metrics.volatilityPct != null ? `${metrics.volatilityPct.toFixed(1)}%` : "—"} />
      <RiskCard testId="risk-sharpe" label="Sharpe" value={metrics.sharpe != null ? metrics.sharpe.toFixed(2) : "—"} />
      <RiskCard testId="risk-sortino" label="Sortino" value={metrics.sortino != null ? metrics.sortino.toFixed(2) : "—"} />
      <RiskCard testId="risk-calmar" label="Calmar" value={metrics.calmar != null ? metrics.calmar.toFixed(2) : "—"} />
      <RiskCard testId="risk-ulcer" label="Ulcer Index" value={metrics.ulcerIndex != null ? metrics.ulcerIndex.toFixed(2) : "—"} />
      <RiskCard testId="risk-downside-dev" label="Downside Deviation" value={metrics.downsideDeviationPct != null ? `${metrics.downsideDeviationPct.toFixed(1)}%` : "—"} />
      <RiskCard testId="risk-exposure" label="Exposure" value={metrics.exposurePct != null ? `${metrics.exposurePct.toFixed(1)}%` : "—"} />
    </div>
  </Section>
);

/* ----------------------------- Trade Distribution ----------------------------- */
const DURATION_BUCKETS = [
  { label: "< 1h", max: 60 },
  { label: "1–4h", max: 240 },
  { label: "4–24h", max: 1440 },
  { label: "1–7d", max: 10080 },
  { label: "> 7d", max: Infinity },
];

const TradeDistribution = ({ trades }) => {
  const wins = trades.filter((t) => t.pnlTone === "pos").length;
  const losses = trades.filter((t) => t.pnlTone === "neg").length;
  const total = Math.max(1, wins + losses);

  const buckets = useMemo(() => {
    const counts = DURATION_BUCKETS.map((b) => ({ label: b.label, count: 0 }));
    for (const t of trades) {
      if (t.durationMinutes == null) continue;
      const idx = DURATION_BUCKETS.findIndex((b) => t.durationMinutes <= b.max);
      counts[idx === -1 ? counts.length - 1 : idx].count++;
    }
    return counts;
  }, [trades]);

  const monthlyFreq = useMemo(() => {
    const map = new Map();
    for (const t of trades) {
      const d = t.raw?.exit_time || t.raw?.sell?.date;
      if (!d) continue;
      const key = String(d).slice(0, 7);
      map.set(key, (map.get(key) || 0) + 1);
    }
    return [...map.entries()].sort((a, b) => a[0].localeCompare(b[0])).map(([month, count]) => ({ month, count }));
  }, [trades]);

  return (
    <Section no="07" title="Trade Distribution" testId="section-trade-distribution" collapsible>
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-5 mb-5">
        <div className={`${SURFACE} p-6`} data-testid="distribution-win-loss">
          <p className="font-mono-ui text-[10px] uppercase tracking-[0.16em] text-slate-500 mb-4">Winning vs. Losing Trades</p>
          <div className="flex items-center gap-2 mb-2">
            <TrendingUp size={14} className="text-emerald-400" />
            <span className="text-sm text-slate-300 w-16">{wins} wins</span>
            <div className="flex-1 h-2.5 rounded-full bg-white/5 overflow-hidden"><div className="h-full bg-emerald-400" style={{ width: `${(wins / total) * 100}%` }} /></div>
          </div>
          <div className="flex items-center gap-2">
            <TrendingDown size={14} className="text-red-400" />
            <span className="text-sm text-slate-300 w-16">{losses} losses</span>
            <div className="flex-1 h-2.5 rounded-full bg-white/5 overflow-hidden"><div className="h-full bg-red-400" style={{ width: `${(losses / total) * 100}%` }} /></div>
          </div>
        </div>

        <div className={`${SURFACE} p-6`} data-testid="distribution-holding">
          <p className="font-mono-ui text-[10px] uppercase tracking-[0.16em] text-slate-500 mb-4">Holding Period Distribution</p>
          <div className="h-32">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={buckets} margin={{ top: 0, right: 0, left: -20, bottom: 0 }}>
                <XAxis dataKey="label" tick={{ fill: "#64748B", fontSize: 10 }} axisLine={false} tickLine={false} />
                <YAxis tick={{ fill: "#64748B", fontSize: 10 }} axisLine={false} tickLine={false} allowDecimals={false} />
                <Tooltip content={<ChartTooltip />} cursor={{ fill: "rgba(255,255,255,0.03)" }} />
                <Bar dataKey="count" name="Trades" fill="#437EEB" radius={[3, 3, 0, 0]} isAnimationActive animationDuration={700} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>
      </div>

      <div className={`${SURFACE} p-6`} data-testid="distribution-monthly-frequency">
        <p className="font-mono-ui text-[10px] uppercase tracking-[0.16em] text-slate-500 mb-4">Monthly Trade Frequency</p>
        {monthlyFreq.length ? (
          <div className="h-40">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={monthlyFreq} margin={{ top: 0, right: 0, left: -20, bottom: 0 }}>
                <XAxis dataKey="month" tick={{ fill: "#64748B", fontSize: 9 }} axisLine={false} tickLine={false} minTickGap={30} />
                <YAxis tick={{ fill: "#64748B", fontSize: 10 }} axisLine={false} tickLine={false} allowDecimals={false} />
                <Tooltip content={<ChartTooltip />} cursor={{ fill: "rgba(255,255,255,0.03)" }} />
                <Bar dataKey="count" name="Trades" fill="#437EEB" radius={[2, 2, 0, 0]} isAnimationActive animationDuration={700} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        ) : <p className="text-sm text-slate-500 py-6 text-center">No trade history yet.</p>}
      </div>
    </Section>
  );
};

/* ------------------------------- Recent Trades ------------------------------- */
const RecentTrades = ({ trades, csvRows, slug }) => (
  <Section no="08" title="Recent Trades" testId="section-recent-trades" collapsible>
    <div className={`${SURFACE} overflow-hidden`}>
      <div className="flex items-center justify-between px-5 md:px-6 py-4 border-b border-white/10">
        <p className="font-mono-ui text-[10px] uppercase tracking-[0.16em] text-slate-500">{trades.length} trades shown</p>
        <button
          type="button"
          onClick={() => downloadCSV(`${slug}-trades.csv`, tradesToCSV(csvRows))}
          disabled={!csvRows.length}
          className="inline-flex items-center gap-2 rounded-full border border-white/15 px-4 py-1.5 text-xs font-medium text-slate-300 hover:text-white hover:border-white/30 transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
          data-testid="export-csv-btn"
        >
          <Download size={13} /> Export CSV
        </button>
      </div>

      {trades.length ? (
        <div className="overflow-x-auto">
          <table className="w-full text-left min-w-[720px]">
            <thead>
              <tr className="border-b border-white/10">
                {["Entry", "Exit", "P&L", "Duration", "Signal", "Status"].map((h) => (
                  <th key={h} className="px-5 py-3 font-mono-ui text-[10px] uppercase tracking-[0.14em] text-slate-500 font-semibold whitespace-nowrap">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {trades.slice(0, 50).map((t) => (
                <tr key={t.id} className="border-b border-white/[0.05] last:border-0 hover:bg-white/[0.02] transition-colors" data-testid={`trade-row-${t.id}`}>
                  <td className="px-5 py-3 font-mono-ui text-xs text-slate-300 whitespace-nowrap">{t.entry}</td>
                  <td className="px-5 py-3 font-mono-ui text-xs text-slate-300 whitespace-nowrap">{t.exit}</td>
                  <td className={`px-5 py-3 font-mono-ui text-xs whitespace-nowrap ${TONE_TEXT[t.pnlTone]}`}>{t.pnlLabel}</td>
                  <td className="px-5 py-3 text-xs text-slate-400 whitespace-nowrap">{t.durationLabel}</td>
                  <td className="px-5 py-3 text-xs text-slate-400 whitespace-nowrap">{t.signal}</td>
                  <td className="px-5 py-3 text-xs text-slate-400 whitespace-nowrap capitalize">{t.status}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <p className="text-sm text-slate-500 py-10 text-center">No closed trades yet.</p>
      )}
    </div>
  </Section>
);

/* -------------------------------- Methodology -------------------------------- */
const Methodology = ({ text }) => (
  <Section no="09" title="Methodology" testId="section-methodology">
    <div className={`${SURFACE} p-6 md:p-8 border-l-2 border-l-sapphire`}>
      <p className="text-base md:text-lg font-light text-slate-300 leading-relaxed italic max-w-3xl">"{text}"</p>
    </div>
  </Section>
);

/* ------------------------------ Risk Disclosure ------------------------------ */
const RiskDisclosure = () => (
  <Section no="10" title="Risk Disclosure" testId="section-risk-disclosure">
    <div className={`${SURFACE} p-6 md:p-8`}>
      <p className="text-sm font-light text-slate-400 leading-relaxed max-w-3xl">{RISK_DISCLOSURE}</p>
    </div>
  </Section>
);

/* ---------------------------------- Page ---------------------------------- */
export default function StrategyDetail() {
  const { slug } = useParams();
  const navigate = useNavigate();
  const strategy = getStrategy(slug);
  const [view, setView] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    window.scrollTo(0, 0);
    if (!strategy) return;
    setLoading(true);
    fetchStrategyView(strategy).then(setView).catch(() => setView(null)).finally(() => setLoading(false));
  }, [strategy]);

  if (!strategy) {
    return (
      <>
        <Navbar />
        <main className="relative bg-void min-h-screen flex items-center justify-center">
          <div className="text-center">
            <p className="font-mono-ui text-xs uppercase tracking-[0.2em] text-slate-500 mb-4">Not Found</p>
            <button onClick={() => navigate("/black-box")} className="btn-sapphire">Back to Black Box</button>
          </div>
        </main>
        <Footer />
      </>
    );
  }

  return (
    <>
      <Navbar />
      <main className="relative bg-void min-h-screen">
        <Header strategy={strategy} view={view} />

        <div className="container-x">
          {loading ? (
            <div className="flex items-center justify-center py-32 text-slate-500 font-mono-ui text-sm gap-3" data-testid="strategy-detail-loading">
              <Loader2 className="animate-spin" size={16} /> Loading research report…
            </div>
          ) : view ? (
            <>
              <ExecutiveSummary summary={strategy.summary} />
              <PerformanceSnapshot kpis={view.kpis} />
              <EquityCurveSection
                equityCurve={view.equityCurve}
                benchmarkCurve={view.benchmarkCurve}
                benchmarkLabel={view.benchmarkLabel}
                isPct={false}
              />
              <DrawdownSection drawdownCurve={view.drawdownCurve} worstDrawdowns={view.worstDrawdowns} />
              <MonthlyHeatmap monthly={view.monthly} />
              <RiskAnalytics metrics={view.metrics} />
              <TradeDistribution trades={view.trades} />
              <RecentTrades trades={view.trades} csvRows={view.csvRows} slug={strategy.slug} />
              <Methodology text={strategy.methodology} />
              <RiskDisclosure />

              <div className="py-14 text-center">
                <Link to="/black-box" className="inline-flex items-center gap-2 text-sapphire-light hover:text-white transition-colors text-sm font-medium" data-testid="back-to-black-box-footer">
                  View other strategies <ArrowUpRight size={15} />
                </Link>
              </div>
            </>
          ) : (
            <p className="text-sm text-slate-500 py-32 text-center">Could not load this strategy's research report.</p>
          )}
        </div>
      </main>
      <Footer />
    </>
  );
}
