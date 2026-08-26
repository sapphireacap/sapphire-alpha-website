import { useEffect, useMemo, useState } from "react";
import axios from "axios";
import { Loader2, ChevronDown, ArrowUpDown } from "lucide-react";
import {
  ResponsiveContainer, LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip,
} from "recharts";
import { fmtNum, fmtINR } from "./adapters";
import { RANGES, filterByRange, downloadCSV, tradesToCSV } from "../../lib/strategyStats";
import { authHeaders } from "../../lib/auth";

// Public, real-data detail page for the two new options-buying strategies
// (Convexity Window, Gamma Backspread) — see [[proprietary_naming]] memory:
// this is a DELIBERATE exception for these two strategies only (their own
// spec requires full rule disclosure, "transparent rather than a black box
// in the dishonest sense"); the original three strategies stay proprietary
// via the plain StrategyDetail.jsx. Everything shown here is PAPER MODE —
// no real capital, ever, until the site owner explicitly approves going
// live (see backend/blackbox_options_engine.py's LIVE_MODE gate).

const SURFACE = "rounded-2xl border border-white/10 bg-[#0A0D18]";
const API = `${process.env.REACT_APP_BACKEND_URL}/api`;
const INDICES = ["NIFTY", "BANKNIFTY"];
const INDEX_LABEL = { NIFTY: "Nifty", BANKNIFTY: "Bank Nifty" };

const STATUS_TONE = {
  in_trade: "bg-emerald-400/10 text-emerald-400 border-emerald-400/20",
  flat: "bg-white/5 text-slate-400 border-white/10",
};

const FILTER_LABELS = {
  direction: "Direction", atm_iv: "ATM IV", realized_vol: "Realized Vol", iv_rv_ratio: "IV / RV",
  required_move: "Required Move", required_move_threshold: "Required Move Cap", median_true_range: "Median True Range",
  candidate_count_within_vega_cap: "Candidates in Vega Cap", selected_gamma_theta_ratio: "Gamma/Theta (selected)",
  dte: "Days to Expiry", iv_percentile: "IV Percentile", iv_history_len: "IV History Samples",
  net_theta: "Net Theta", net_gamma: "Net Gamma", net_vega: "Net Vega",
};

const PCT_KEYS = new Set(["atm_iv", "realized_vol", "iv_percentile"]);

const fmtFilterValue = (key, value) => {
  if (value == null) return "—";
  if (typeof value === "boolean") return value ? "Yes" : "No";
  if (typeof value === "number") {
    if (PCT_KEYS.has(key)) return `${(value * 100).toFixed(2)}%`;
    return Number.isInteger(value) ? String(value) : value.toFixed(4);
  }
  return String(value);
};

const SectionHeader = ({ no, title }) => (
  <div className="flex items-baseline gap-3 mb-5">
    <span className="font-mono-ui text-xs text-sapphire-light">{no}</span>
    <h3 className="text-xl font-bold text-white tracking-tight">{title}</h3>
  </div>
);

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

const KpiCard = ({ label, value, tone = "neutral", note }) => (
  <div className={`${SURFACE} p-4`} title={note}>
    <p className="font-mono-ui text-[9px] uppercase tracking-[0.14em] text-slate-500 mb-1.5 leading-tight">{label}</p>
    <p className={`font-mono-ui text-xl font-bold tracking-tight ${
      tone === "pos" ? "text-emerald-400" : tone === "neg" ? "text-red-400" : "text-white"
    }`}>{value}</p>
  </div>
);

function buildCumulativeCurve(dailyDocs, field) {
  const sorted = [...dailyDocs].sort((a, b) => a.date.localeCompare(b.date));
  let cum = 0;
  return sorted.map((d) => { cum += d[field] || 0; return { date: d.date, value: cum }; });
}

function buildCombinedCurve(dailyDocs, field) {
  const byDate = new Map();
  for (const d of dailyDocs) byDate.set(d.date, (byDate.get(d.date) || 0) + (d[field] || 0));
  const dates = [...byDate.keys()].sort();
  let cum = 0;
  return dates.map((date) => { cum += byDate.get(date); return { date, value: cum }; });
}

function normalizeSignal(strategyId, s) {
  if (strategyId === "convexity_window") {
    return {
      id: s.id, index: s.index, date: s.timestamp?.slice(0, 10), side: s.side, status: s.status,
      instrument: `${s.strike} ${s.side}`,
      entry: s.entry_price != null ? `₹${s.entry_price.toFixed(2)}` : "—",
      exit: s.exit_price != null ? `₹${s.exit_price.toFixed(2)}` : "—",
      exitReason: s.exit_reason, grossPnl: s.gross_pnl, netPnl: s.net_pnl, pnlPct: s.pnl_pct,
    };
  }
  if (strategyId === "premium_band_strangle") {
    const ce = s.legs?.CE, pe = s.legs?.PE;
    return {
      id: s.id, index: s.index, date: s.timestamp?.slice(0, 10), side: "CE/PE", status: s.status,
      instrument: `${ce?.strike ?? "—"} CE / ${pe?.strike ?? "—"} PE`,
      entry: `CE ₹${ce?.entry_premium?.toFixed(2) ?? "—"} / PE ₹${pe?.entry_premium?.toFixed(2) ?? "—"}`,
      exit: s.status === "closed" ? "Expired (cash-settled)" : "—",
      exitReason: s.exit_reason, grossPnl: s.gross_pnl, netPnl: s.net_pnl, pnlPct: null,
    };
  }
  const exitPrice = s.exit_price && typeof s.exit_price === "object"
    ? `ATM ₹${s.exit_price.atm?.toFixed(2)} / OTM ₹${s.exit_price.otm?.toFixed(2)}` : "—";
  return {
    id: s.id, index: s.index, date: s.timestamp?.slice(0, 10), side: s.side, status: s.status,
    instrument: `${s.atm_strike}/${s.otm_strike} ${s.side}`,
    entry: `ATM ₹${s.atm_entry_price?.toFixed(2)} / OTM ₹${s.otm_entry_price?.toFixed(2)}`,
    exit: exitPrice,
    exitReason: s.exit_reason, grossPnl: s.gross_pnl, netPnl: s.net_pnl, pnlPct: null,
  };
}

const SORT_FIELDS = { date: "date", index: "index", pnl: "netPnl" };

function SignalTable({ signals, strategyId, slug }) {
  const [sortKey, setSortKey] = useState("date");
  const [sortDir, setSortDir] = useState(-1);
  const [page, setPage] = useState(0);
  const perPage = 20;

  const rows = useMemo(() => {
    const norm = signals.map((s) => normalizeSignal(strategyId, s));
    const field = SORT_FIELDS[sortKey] || "date";
    return [...norm].sort((a, b) => {
      const av = a[field], bv = b[field];
      if (av == null && bv == null) return 0;
      if (av == null) return 1;
      if (bv == null) return -1;
      return av > bv ? sortDir : av < bv ? -sortDir : 0;
    });
  }, [signals, strategyId, sortKey, sortDir]);

  const totalPages = Math.max(1, Math.ceil(rows.length / perPage));
  const pageRows = rows.slice(page * perPage, (page + 1) * perPage);

  const toggleSort = (key) => {
    if (sortKey === key) setSortDir((d) => -d);
    else { setSortKey(key); setSortDir(-1); }
    setPage(0);
  };

  const Th = ({ k, children }) => (
    <th
      className="px-4 py-3 font-mono-ui text-[10px] uppercase tracking-[0.14em] text-slate-500 font-semibold whitespace-nowrap cursor-pointer select-none hover:text-slate-300"
      onClick={() => toggleSort(k)}
    >
      <span className="inline-flex items-center gap-1">{children} <ArrowUpDown size={10} /></span>
    </th>
  );

  return (
    <div className={`${SURFACE} overflow-hidden`}>
      <div className="flex items-center justify-between px-5 py-4 border-b border-white/10">
        <p className="font-mono-ui text-[10px] uppercase tracking-[0.16em] text-slate-500">
          {rows.length} signals — every trade shown, including losers
        </p>
        <button
          type="button"
          onClick={() => downloadCSV(`${slug}-signals.csv`, tradesToCSV(rows, ["date", "index", "instrument", "entry", "exit", "exitReason", "grossPnl", "netPnl", "status"]))}
          disabled={!rows.length}
          className="rounded-full border border-white/15 px-4 py-1.5 text-xs font-medium text-slate-300 hover:text-white hover:border-white/30 transition-colors disabled:opacity-40"
        >
          Export CSV
        </button>
      </div>
      {rows.length ? (
        <>
          <div className="overflow-x-auto">
            <table className="w-full text-left min-w-[820px]">
              <thead>
                <tr className="border-b border-white/10">
                  <Th k="date">Date</Th>
                  <Th k="index">Index</Th>
                  <th className="px-4 py-3 font-mono-ui text-[10px] uppercase tracking-[0.14em] text-slate-500 font-semibold whitespace-nowrap">Instrument</th>
                  <th className="px-4 py-3 font-mono-ui text-[10px] uppercase tracking-[0.14em] text-slate-500 font-semibold whitespace-nowrap">Entry</th>
                  <th className="px-4 py-3 font-mono-ui text-[10px] uppercase tracking-[0.14em] text-slate-500 font-semibold whitespace-nowrap">Exit</th>
                  <th className="px-4 py-3 font-mono-ui text-[10px] uppercase tracking-[0.14em] text-slate-500 font-semibold whitespace-nowrap">Reason</th>
                  <Th k="pnl">Net P&amp;L</Th>
                  <th className="px-4 py-3 font-mono-ui text-[10px] uppercase tracking-[0.14em] text-slate-500 font-semibold whitespace-nowrap">Status</th>
                </tr>
              </thead>
              <tbody>
                {pageRows.map((r) => (
                  <tr key={r.id} className="border-b border-white/[0.05] last:border-0 hover:bg-white/[0.02] transition-colors">
                    <td className="px-4 py-3 font-mono-ui text-xs text-slate-300 whitespace-nowrap">{r.date}</td>
                    <td className="px-4 py-3 text-xs text-slate-400 whitespace-nowrap">{INDEX_LABEL[r.index] || r.index}</td>
                    <td className="px-4 py-3 font-mono-ui text-xs text-slate-300 whitespace-nowrap">{r.instrument}</td>
                    <td className="px-4 py-3 font-mono-ui text-xs text-slate-400 whitespace-nowrap">{r.entry}</td>
                    <td className="px-4 py-3 font-mono-ui text-xs text-slate-400 whitespace-nowrap">{r.exit}</td>
                    <td className="px-4 py-3 text-xs text-slate-500 whitespace-nowrap">{r.exitReason || "—"}</td>
                    <td className={`px-4 py-3 font-mono-ui text-xs whitespace-nowrap ${r.netPnl > 0 ? "text-emerald-400" : r.netPnl < 0 ? "text-red-400" : "text-slate-400"}`}>
                      {r.netPnl != null ? fmtINR(r.netPnl, 2) : "—"}
                    </td>
                    <td className="px-4 py-3 text-xs text-slate-400 whitespace-nowrap capitalize">{r.status}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="flex items-center justify-between px-5 py-3 border-t border-white/10">
            <button disabled={page === 0} onClick={() => setPage((p) => p - 1)} className="text-xs text-slate-400 hover:text-white disabled:opacity-30">Previous</button>
            <p className="font-mono-ui text-[10px] text-slate-500">Page {page + 1} / {totalPages}</p>
            <button disabled={page >= totalPages - 1} onClick={() => setPage((p) => p + 1)} className="text-xs text-slate-400 hover:text-white disabled:opacity-30">Next</button>
          </div>
        </>
      ) : <p className="text-sm text-slate-500 py-10 text-center">No signals logged yet.</p>}
    </div>
  );
}

const RULES_TEXT = {
  convexity_window: {
    entry: [
      "Evaluated once daily at 09:30 IST.",
      "Implied volatility of the at-the-money option must sit below 95% of the underlying's 20-day realized volatility — i.e. options must be pricing in less movement than the underlying has actually shown.",
      "The option's own breakeven move (√(2 × Theta ÷ Gamma)) must be smaller than 0.8× the median true daily range over the last 20 days.",
      "Among strikes within 2 of at-the-money and expiries 1–4 days out, the contract with the best Gamma-per-Theta is chosen, as long as its Vega stays under the configured cap.",
      "Direction is price-only: a call if spot is above both the previous close and the 20-period 15-minute average; a put on the mirror condition. No trade if neither holds.",
    ],
    exit: [
      "Stop-loss at −35% of premium paid.",
      "Target at +70% of premium paid.",
      "Time stop: square off by 15:15 IST regardless of P&L.",
      "Greeks stop: exit if the position's Gamma falls below 50% of its value at entry.",
    ],
  },
  gamma_backspread: {
    entry: [
      "Sells 1 at-the-money option, buys 2 further out-of-the-money options of the same type and expiry.",
      "The at-the-money option's implied volatility must sit in the cheapest 30th percentile of its own trailing history.",
      "The out-of-the-money strike is chosen so the package's net Theta lands between −0.05 and +0.05 per lot per day (closest to zero, among strikes that qualify) while net Gamma stays positive.",
      "Net Vega of the whole package must be positive.",
      "Expiry must be 5–12 days out.",
      "Direction follows the same price-only rule as Convexity Window — a call backspread on bullish alignment, a put backspread on bearish.",
    ],
    exit: [
      "Exit if live net Theta drifts below −0.15 per lot per day.",
      "Exit at 2 days-to-expiry regardless of P&L.",
      "Target at +40% of net debit paid; stop-loss at −25% of net debit.",
      "Exit if IV percentile rises above 60 — volatility has repriced, so the position takes the Vega gain and closes.",
    ],
  },
  premium_band_strangle: {
    entry: [
      "Sells the NIFTY call and put (next monthly expiry) whose live premium sits closest to a fixed target band (default ₹60–70).",
      "No implied volatility, no Greeks, no chart pattern — strike selection is premium level only.",
      "Both legs are entered together, once per expiry cycle.",
    ],
    exit: [
      "Profit shift: if a leg's own profit exceeds a fixed rupee threshold, that leg is closed and re-sold back into the target band.",
      "Loss trigger: if a leg's running loss exceeds a fixed rupee threshold, that leg is closed and re-sold back into the band.",
      "Premium-doubling trigger: if a leg's premium approaches double its entry value, it's closed and re-sold back into the band.",
      "Both legs are marked closed at expiry (cash-settled), regardless of whether a roll trigger fired that cycle.",
    ],
  },
};

function RulesAccordion({ strategyId }) {
  const [open, setOpen] = useState(false);
  const rules = RULES_TEXT[strategyId];
  if (!rules) return null;
  return (
    <div className={`${SURFACE} overflow-hidden`}>
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="w-full flex items-center justify-between px-6 py-5 text-left"
      >
        <span className="text-lg font-bold text-white">Rules — exactly what this strategy does</span>
        <ChevronDown size={18} className={`text-slate-400 transition-transform duration-300 ${open ? "rotate-180" : ""}`} />
      </button>
      {open && (
        <div className="px-6 pb-6 grid grid-cols-1 md:grid-cols-2 gap-6">
          <div>
            <p className="font-mono-ui text-[10px] uppercase tracking-[0.16em] text-sapphire-light mb-3">Entry</p>
            <ul className="space-y-2.5">
              {rules.entry.map((r, i) => <li key={i} className="text-sm text-slate-300 leading-relaxed flex gap-2"><span className="text-slate-600">—</span>{r}</li>)}
            </ul>
          </div>
          <div>
            <p className="font-mono-ui text-[10px] uppercase tracking-[0.16em] text-amber-400 mb-3">Exit</p>
            <ul className="space-y-2.5">
              {rules.exit.map((r, i) => <li key={i} className="text-sm text-slate-300 leading-relaxed flex gap-2"><span className="text-slate-600">—</span>{r}</li>)}
            </ul>
          </div>
        </div>
      )}
    </div>
  );
}

function StatusCard({ index, data }) {
  const status = data?.status || "flat";
  return (
    <div className={`${SURFACE} p-5`}>
      <div className="flex items-center justify-between mb-3">
        <p className="text-base font-bold text-white">{INDEX_LABEL[index]}</p>
        <span className={`rounded-full border px-3 py-1 font-mono-ui text-[10px] uppercase tracking-wider ${STATUS_TONE[status] || STATUS_TONE.flat}`}>
          {status === "in_trade" ? "In Trade" : "Flat"}
        </span>
      </div>
      <p className="text-xs text-slate-400 leading-relaxed mb-3">{data?.reason || "No status recorded yet."}</p>
      {data?.filters && Object.keys(data.filters).length > 0 && (
        <div className="grid grid-cols-2 gap-x-4 gap-y-1.5 pt-3 border-t border-white/[0.06]">
          {Object.entries(data.filters).map(([k, v]) => (
            <div key={k} className="flex justify-between gap-2">
              <span className="font-mono-ui text-[9px] uppercase tracking-wider text-slate-600 whitespace-nowrap">{FILTER_LABELS[k] || k}</span>
              <span className="font-mono-ui text-[10px] text-slate-300 text-right">{fmtFilterValue(k, v)}</span>
            </div>
          ))}
        </div>
      )}
      {data?.updated_at && <p className="font-mono-ui text-[9px] text-slate-600 mt-3">Updated {new Date(data.updated_at).toLocaleString("en-IN")}</p>}
    </div>
  );
}

export default function OptionsStrategyDetail({ strategy }) {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const [locked, setLocked] = useState(false);
  const [entry, setEntry] = useState(null);
  const [signals, setSignals] = useState([]);
  const [performance, setPerformance] = useState([]);
  const [curveIndex, setCurveIndex] = useState("COMBINED");
  const [curveField, setCurveField] = useState("net_pnl");
  const [range, setRange] = useState("ALL");

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(false);
    const headers = authHeaders();
    Promise.all([
      axios.get(`${API}/blackbox/strategies`, { headers }).then((r) => r.data),
      axios.get(`${API}/blackbox/signals`, { params: { strategy_id: strategy.apiPath, limit: 1000 }, headers }).then((r) => r.data),
      axios.get(`${API}/blackbox/performance`, { params: { strategy_id: strategy.apiPath }, headers }).then((r) => r.data),
    ]).then(([strategiesRes, signalsRes, perfRes]) => {
      if (cancelled) return;
      setLocked(!!strategiesRes.locked);
      setEntry(strategiesRes.strategies.find((s) => s.strategy_id === strategy.apiPath) || null);
      setSignals(signalsRes.signals || []);
      setPerformance(perfRes.daily || []);
    }).catch(() => { if (!cancelled) setError(true); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [strategy.apiPath]);

  const closedSignals = useMemo(() => signals.filter((s) => s.status === "closed"), [signals]);

  const curve = useMemo(() => {
    if (!performance.length) return [];
    if (curveIndex === "COMBINED") {
      return curveField === "net_pnl"
        ? buildCombinedCurve(performance, "net_pnl")
        : buildCombinedCurve(performance, "gross_pnl");
    }
    const docs = performance.filter((d) => d.index === curveIndex);
    return buildCumulativeCurve(docs, curveField);
  }, [performance, curveIndex, curveField]);

  const filteredCurve = useMemo(() => filterByRange(curve, range), [curve, range]);

  const stats = useMemo(() => {
    const pnls = closedSignals.map((s) => s.net_pnl).filter((v) => v != null);
    const wins = pnls.filter((v) => v > 0);
    const losses = pnls.filter((v) => v <= 0);
    const grossWin = wins.reduce((a, b) => a + b, 0);
    const grossLoss = Math.abs(losses.reduce((a, b) => a + b, 0));
    const bestDay = performance.length ? Math.max(...performance.map((d) => d.net_pnl ?? -Infinity)) : null;
    const worstDay = performance.length ? Math.min(...performance.map((d) => d.net_pnl ?? Infinity)) : null;
    const last = performance.length ? [...performance].sort((a, b) => b.date.localeCompare(a.date))[0] : null;
    return {
      totalTrades: pnls.length,
      winRate: pnls.length ? wins.length / pnls.length : null,
      avgWin: wins.length ? grossWin / wins.length : null,
      avgLoss: losses.length ? -grossLoss / losses.length : null,
      profitFactor: grossLoss > 0 ? grossWin / grossLoss : (grossWin > 0 ? Infinity : null),
      maxDrawdown: last?.max_drawdown ?? null,
      sharpe: last?.sharpe ?? null,
      bestDay, worstDay,
    };
  }, [closedSignals, performance]);

  if (loading) {
    return <div className="flex items-center justify-center py-24 text-slate-500 font-mono-ui text-sm gap-3"><Loader2 className="animate-spin" size={16} /> Loading paper track record…</div>;
  }
  if (error) {
    return <p className="text-sm text-slate-500 py-16 text-center">Could not load this strategy's data right now.</p>;
  }
  if (locked) {
    return (
      <div className={`${SURFACE} p-10 text-center`}>
        <p className="text-lg font-bold text-white mb-2">Coming Soon</p>
        <p className="text-sm text-slate-500 max-w-sm mx-auto">This strategy's rules and performance data aren't public yet.</p>
      </div>
    );
  }

  return (
    <div data-testid={`options-strategy-${strategy.slug}`}>
      <section className="mb-10">
        <SectionHeader no="01" title="Live Status" />
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          {INDICES.map((idx) => <StatusCard key={idx} index={idx} data={entry?.indices?.[idx]} />)}
        </div>
      </section>

      <section className="mb-10">
        <SectionHeader no="02" title="Performance Snapshot" />
        {stats.totalTrades > 0 ? (
          <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-3">
            <KpiCard label="Total Trades" value={stats.totalTrades} />
            <KpiCard label="Win Rate" value={stats.winRate != null ? `${(stats.winRate * 100).toFixed(0)}%` : "—"} tone={stats.winRate > 0.5 ? "pos" : "neg"} />
            <KpiCard label="Avg Win" value={fmtINR(stats.avgWin, 2)} tone="pos" />
            <KpiCard label="Avg Loss" value={fmtINR(stats.avgLoss, 2)} tone="neg" />
            <KpiCard label="Profit Factor" value={fmtNum(stats.profitFactor)} tone={stats.profitFactor > 1 ? "pos" : "neg"} />
            <KpiCard label="Max Drawdown" value={stats.maxDrawdown != null ? fmtINR(stats.maxDrawdown, 0) : "—"} tone="neg" />
            <KpiCard label="Sharpe (running)" value={fmtNum(stats.sharpe)} note="Needs a meaningful sample of trading days — will read blank until there's enough history." />
            <KpiCard label="Best Day" value={stats.bestDay != null && Number.isFinite(stats.bestDay) ? fmtINR(stats.bestDay, 0) : "—"} tone="pos" />
            <KpiCard label="Worst Day" value={stats.worstDay != null && Number.isFinite(stats.worstDay) ? fmtINR(stats.worstDay, 0) : "—"} tone="neg" />
          </div>
        ) : <p className="text-sm text-slate-500">No closed trades yet — this strategy hasn't been filtered into a real entry so far.</p>}
      </section>

      <section className="mb-10">
        <SectionHeader no="03" title="Equity Curve" />
        <div className={`${SURFACE} p-5`}>
          <div className="flex items-center justify-between flex-wrap gap-3 mb-5">
            <div className="flex gap-1">
              {["COMBINED", ...INDICES].map((k) => (
                <button key={k} type="button" onClick={() => setCurveIndex(k)}
                  className={`px-3 py-1.5 rounded-md font-mono-ui text-[11px] uppercase tracking-wider transition-colors ${curveIndex === k ? "bg-white/[0.08] text-white border border-white/10" : "text-slate-500 hover:text-slate-300"}`}>
                  {k === "COMBINED" ? "Combined" : INDEX_LABEL[k]}
                </button>
              ))}
            </div>
            <div className="flex gap-1">
              {[["net_pnl", "Net"], ["gross_pnl", "Gross"]].map(([k, label]) => (
                <button key={k} type="button" onClick={() => setCurveField(k)}
                  className={`px-3 py-1.5 rounded-md font-mono-ui text-[11px] uppercase tracking-wider transition-colors ${curveField === k ? "bg-white/[0.08] text-white border border-white/10" : "text-slate-500 hover:text-slate-300"}`}>
                  {label}
                </button>
              ))}
            </div>
            <div className="flex gap-1">
              {RANGES.map((r) => (
                <button key={r} type="button" onClick={() => setRange(r)}
                  className={`px-2.5 py-1.5 rounded-md font-mono-ui text-[10px] uppercase tracking-wider transition-colors ${range === r ? "bg-white/[0.08] text-white border border-white/10" : "text-slate-500 hover:text-slate-300"}`}>
                  {r}
                </button>
              ))}
            </div>
          </div>
          {filteredCurve.length > 1 ? (
            <div className="h-72">
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={filteredCurve} margin={{ top: 4, right: 8, left: 0, bottom: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.06)" vertical={false} />
                  <XAxis dataKey="date" tick={{ fill: "#64748B", fontSize: 10 }} axisLine={{ stroke: "rgba(255,255,255,0.1)" }} tickLine={false} minTickGap={60} />
                  <YAxis tick={{ fill: "#64748B", fontSize: 11 }} axisLine={false} tickLine={false} width={64} tickFormatter={(v) => `₹${v.toFixed(0)}`} />
                  <Tooltip content={<ChartTooltip formatter={(v) => fmtINR(v, 2)} />} />
                  <Line type="monotone" dataKey="value" name={curveField === "net_pnl" ? "Net Cumulative P&L" : "Gross Cumulative P&L"} stroke="#437EEB" strokeWidth={2} dot={false} isAnimationActive animationDuration={500} />
                </LineChart>
              </ResponsiveContainer>
            </div>
          ) : <p className="text-sm text-slate-500 py-16 text-center">Not enough daily records yet to plot a curve.</p>}
        </div>
      </section>

      <section className="mb-10">
        <SectionHeader no="04" title="Signal History" />
        <SignalTable signals={signals} strategyId={strategy.apiPath} slug={strategy.slug} />
      </section>

      <section className="mb-6">
        <SectionHeader no="05" title="Rules" />
        <RulesAccordion strategyId={strategy.apiPath} />
      </section>
    </div>
  );
}
