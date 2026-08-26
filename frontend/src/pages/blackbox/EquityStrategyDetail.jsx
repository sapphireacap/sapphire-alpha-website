import { useEffect, useMemo, useState } from "react";
import axios from "axios";
import { Loader2, ChevronDown, ArrowUpDown } from "lucide-react";
import { fmtNum, fmtINR } from "./adapters";
import { downloadCSV, tradesToCSV } from "../../lib/strategyStats";
import { authHeaders } from "../../lib/auth";

// Public, real-data detail page for Black Box's three equity strategies
// (Structural Retest, Trend Ignition, Volume Cascade) -- the equity
// counterpart to OptionsStrategyDetail.jsx. Same full-disclosure spirit
// (nothing hidden about entry/exit logic), same PAPER MODE-only reality
// (backend/blackbox_equity_engine.py's LIVE_MODE gate). Backed by
// /blackbox/equity/* routes, which return a `locked` shape to everyone
// except the one account backend/blackbox_access.py allows through.

const SURFACE = "rounded-2xl border border-white/10 bg-[#0A0D18]";
const API = `${process.env.REACT_APP_BACKEND_URL}/api`;

const RULES_TEXT = {
  structural_retest: {
    entry: [
      "Scans NIFTY 50 constituents' own Point & Figure charts (1% box, 3-box reversal) for a major reversal pattern — a Triple Top/Bottom or a Pole — that has been RE-TESTED by a later pattern of the same bias at the same price zone.",
      "A bullish retest is only traded when the NIFTY 50 group's own breadth reading is 25% or below (oversold); a bearish retest only when breadth is 75% or above (overbought).",
      "A 4th test of the same zone is treated as over-tested and skipped, not traded.",
    ],
    exit: [
      "A bullish position exits on a Double Bottom Sell or a High Pole; a bearish position exits on a Double Top Buy or a Low Pole.",
      "Also exits if the original entry pattern's own failure level is breached.",
    ],
  },
  trend_ignition: {
    entry: [
      "Runs once daily across the NIFTY 500 universe, on daily bars.",
      "Bullish: 8-period EMA above the 34-period EMA and rising; today's close is the highest of the last 5; RSI(14) above 60; today's volume is the highest of the last 5; ADX(14) above 25; a green, full-bodied candle.",
      "Bearish is the mirror image (RSI below 45, lowest close/volume of 5, red full-bodied candle).",
    ],
    exit: [
      "A hard stop is set at entry.",
      "Profit is booked in stages — 50% at 1R, 25% at 1.5R, the remainder at 2R.",
    ],
  },
  volume_cascade: {
    entry: [
      "Triggers when a NIFTY 500 stock's volume exceeds twice its trailing 10-day average, on a positive close.",
      "Confirms with a fresh Turtle Breakout on the stock's relative-strength (Point & Figure ratio) chart against NIFTY 50.",
      "Confirms again with the same Turtle Breakout on the stock's own price chart, with its 20-column moving average sloping in the trade's direction.",
    ],
    exit: [
      "Stops out on an opposing Turtle Breakout signal, or the moving average turning against the position — whichever comes first.",
      "Books a fixed portion of the position once it reaches a set multiple of its entry stop distance.",
    ],
  },
};

const SectionHeader = ({ no, title }) => (
  <div className="flex items-baseline gap-3 mb-5">
    <span className="font-mono-ui text-xs text-sapphire-light">{no}</span>
    <h3 className="text-xl font-bold text-white tracking-tight">{title}</h3>
  </div>
);

const KpiCard = ({ label, value, tone = "neutral", note }) => (
  <div className={`${SURFACE} p-4`} title={note}>
    <p className="font-mono-ui text-[9px] uppercase tracking-[0.14em] text-slate-500 mb-1.5 leading-tight">{label}</p>
    <p className={`font-mono-ui text-xl font-bold tracking-tight ${
      tone === "pos" ? "text-emerald-400" : tone === "neg" ? "text-red-400" : "text-white"
    }`}>{value}</p>
  </div>
);

function returnPct(position) {
  const { bias, entry_price, exit_price } = position;
  if (entry_price == null || exit_price == null) return null;
  return bias === "bullish"
    ? ((exit_price - entry_price) / entry_price) * 100
    : ((entry_price - exit_price) / entry_price) * 100;
}

const SORT_FIELDS = { date: "entry_date", symbol: "symbol", ret: "ret" };

function PositionTable({ positions, slug }) {
  const [sortKey, setSortKey] = useState("date");
  const [sortDir, setSortDir] = useState(-1);
  const [page, setPage] = useState(0);
  const perPage = 20;

  const rows = useMemo(() => {
    const norm = positions.map((p) => ({ ...p, ret: returnPct(p) }));
    const field = SORT_FIELDS[sortKey] || "entry_date";
    return [...norm].sort((a, b) => {
      const av = a[field], bv = b[field];
      if (av == null && bv == null) return 0;
      if (av == null) return 1;
      if (bv == null) return -1;
      return av > bv ? sortDir : av < bv ? -sortDir : 0;
    });
  }, [positions, sortKey, sortDir]);

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
          {rows.length} positions — every trade shown, including losers
        </p>
        <button
          type="button"
          onClick={() => downloadCSV(`${slug}-positions.csv`, tradesToCSV(
            rows.map((r) => ({ date: r.entry_date, symbol: r.symbol, bias: r.bias, entry: r.entry_price, exit: r.exit_price, exitReason: r.reason, retPct: r.ret, status: r.status })),
            ["date", "symbol", "bias", "entry", "exit", "exitReason", "retPct", "status"],
          ))}
          disabled={!rows.length}
          className="rounded-full border border-white/15 px-4 py-1.5 text-xs font-medium text-slate-300 hover:text-white hover:border-white/30 transition-colors disabled:opacity-40"
        >
          Export CSV
        </button>
      </div>
      {rows.length ? (
        <>
          <div className="overflow-x-auto">
            <table className="w-full text-left min-w-[760px]">
              <thead>
                <tr className="border-b border-white/10">
                  <Th k="date">Entry Date</Th>
                  <Th k="symbol">Symbol</Th>
                  <th className="px-4 py-3 font-mono-ui text-[10px] uppercase tracking-[0.14em] text-slate-500 font-semibold whitespace-nowrap">Bias</th>
                  <th className="px-4 py-3 font-mono-ui text-[10px] uppercase tracking-[0.14em] text-slate-500 font-semibold whitespace-nowrap">Entry</th>
                  <th className="px-4 py-3 font-mono-ui text-[10px] uppercase tracking-[0.14em] text-slate-500 font-semibold whitespace-nowrap">Exit</th>
                  <th className="px-4 py-3 font-mono-ui text-[10px] uppercase tracking-[0.14em] text-slate-500 font-semibold whitespace-nowrap">Reason</th>
                  <Th k="ret">Return</Th>
                  <th className="px-4 py-3 font-mono-ui text-[10px] uppercase tracking-[0.14em] text-slate-500 font-semibold whitespace-nowrap">Status</th>
                </tr>
              </thead>
              <tbody>
                {pageRows.map((r) => (
                  <tr key={r.id} className="border-b border-white/[0.05] last:border-0 hover:bg-white/[0.02] transition-colors">
                    <td className="px-4 py-3 font-mono-ui text-xs text-slate-300 whitespace-nowrap">{r.entry_date}</td>
                    <td className="px-4 py-3 font-mono-ui text-xs text-slate-300 whitespace-nowrap">{r.symbol}</td>
                    <td className={`px-4 py-3 text-xs whitespace-nowrap capitalize ${r.bias === "bullish" ? "text-emerald-400" : "text-red-400"}`}>{r.bias}</td>
                    <td className="px-4 py-3 font-mono-ui text-xs text-slate-400 whitespace-nowrap">{r.entry_price != null ? `₹${r.entry_price.toFixed(2)}` : "—"}</td>
                    <td className="px-4 py-3 font-mono-ui text-xs text-slate-400 whitespace-nowrap">{r.exit_price != null ? `₹${r.exit_price.toFixed(2)}` : "—"}</td>
                    <td className="px-4 py-3 text-xs text-slate-500 whitespace-nowrap">{r.reason || r.action || "—"}</td>
                    <td className={`px-4 py-3 font-mono-ui text-xs whitespace-nowrap ${r.ret > 0 ? "text-emerald-400" : r.ret < 0 ? "text-red-400" : "text-slate-400"}`}>
                      {r.ret != null ? `${r.ret > 0 ? "+" : ""}${r.ret.toFixed(2)}%` : "—"}
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
      ) : <p className="text-sm text-slate-500 py-10 text-center">No positions logged yet.</p>}
    </div>
  );
}

function RulesAccordion({ strategyId }) {
  const [open, setOpen] = useState(false);
  const rules = RULES_TEXT[strategyId];
  if (!rules) return null;
  return (
    <div className={`${SURFACE} overflow-hidden`}>
      <button type="button" onClick={() => setOpen((o) => !o)} className="w-full flex items-center justify-between px-6 py-5 text-left">
        <span className="text-lg font-bold text-white">Rules — exactly what this strategy does</span>
        <ChevronDown size={18} className={`text-slate-400 transition-transform duration-300 ${open ? "rotate-180" : ""}`} />
      </button>
      {open && (
        <div className="px-6 pb-6 grid grid-cols-1 md:grid-cols-2 gap-6">
          <div>
            <p className="font-mono-ui text-[10px] uppercase tracking-[0.16em] text-sapphire-light mb-3">Entry</p>
            <ul className="space-y-2.5">{rules.entry.map((r, i) => <li key={i} className="text-sm text-slate-300 leading-relaxed flex gap-2"><span className="text-slate-600">—</span>{r}</li>)}</ul>
          </div>
          <div>
            <p className="font-mono-ui text-[10px] uppercase tracking-[0.16em] text-amber-400 mb-3">Exit</p>
            <ul className="space-y-2.5">{rules.exit.map((r, i) => <li key={i} className="text-sm text-slate-300 leading-relaxed flex gap-2"><span className="text-slate-600">—</span>{r}</li>)}</ul>
          </div>
        </div>
      )}
    </div>
  );
}

function StatusPanel({ entry }) {
  const status = entry?.status || {};
  return (
    <div className={`${SURFACE} p-5`}>
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
        <div>
          <p className="font-mono-ui text-[9px] uppercase tracking-wider text-slate-600 mb-1">Universe</p>
          <p className="text-sm font-bold text-white">{entry?.universe?.toUpperCase() || "—"} ({status.universe_size ?? "—"})</p>
        </div>
        <div>
          <p className="font-mono-ui text-[9px] uppercase tracking-wider text-slate-600 mb-1">Resolved Today</p>
          <p className="text-sm font-bold text-white">{status.resolved ?? "—"}</p>
        </div>
        {status.breadth_pct != null && (
          <div>
            <p className="font-mono-ui text-[9px] uppercase tracking-wider text-slate-600 mb-1">Group Breadth</p>
            <p className="text-sm font-bold text-white">{status.breadth_pct.toFixed(1)}%</p>
          </div>
        )}
        <div>
          <p className="font-mono-ui text-[9px] uppercase tracking-wider text-slate-600 mb-1">Entered / Exited Today</p>
          <p className="text-sm font-bold text-white">{status.entered_today?.length ?? 0} / {status.exited_today?.length ?? 0}</p>
        </div>
      </div>
      {status.last_run_at && <p className="font-mono-ui text-[9px] text-slate-600 mt-4">Last run {new Date(status.last_run_at).toLocaleString("en-IN")}</p>}
    </div>
  );
}

export default function EquityStrategyDetail({ strategy }) {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const [locked, setLocked] = useState(false);
  const [entry, setEntry] = useState(null);
  const [positions, setPositions] = useState([]);
  const [backtest, setBacktest] = useState(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(false);
    const headers = authHeaders();
    Promise.all([
      axios.get(`${API}/blackbox/equity/strategies`, { headers }).then((r) => r.data),
      axios.get(`${API}/blackbox/equity/positions`, { params: { strategy_id: strategy.apiPath, status: "closed" }, headers }).then((r) => r.data),
      axios.get(`${API}/blackbox/equity/positions`, { params: { strategy_id: strategy.apiPath, status: "open" }, headers }).then((r) => r.data),
      axios.get(`${API}/blackbox/equity/backtest-runs`, { headers }).then((r) => r.data),
    ]).then(([strategiesRes, closedRes, openRes, backtestRes]) => {
      if (cancelled) return;
      setLocked(!!strategiesRes.locked);
      setEntry(strategiesRes.strategies.find((s) => s.strategy_id === strategy.apiPath) || null);
      setPositions([...(closedRes.positions || []), ...(openRes.positions || [])]);
      const run = (backtestRes.runs || []).find((r) => r.strategy_id === strategy.apiPath);
      setBacktest(run || null);
    }).catch(() => { if (!cancelled) setError(true); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [strategy.apiPath]);

  const closed = useMemo(() => positions.filter((p) => p.status === "closed"), [positions]);

  const stats = useMemo(() => {
    const rets = closed.map(returnPct).filter((v) => v != null);
    const wins = rets.filter((v) => v > 0);
    const losses = rets.filter((v) => v <= 0);
    const grossWin = wins.reduce((a, b) => a + b, 0);
    const grossLoss = Math.abs(losses.reduce((a, b) => a + b, 0));
    return {
      totalTrades: rets.length,
      winRate: rets.length ? wins.length / rets.length : null,
      avgWin: wins.length ? grossWin / wins.length : null,
      avgLoss: losses.length ? -grossLoss / losses.length : null,
      profitFactor: grossLoss > 0 ? grossWin / grossLoss : (grossWin > 0 ? Infinity : null),
      bestTrade: rets.length ? Math.max(...rets) : null,
      worstTrade: rets.length ? Math.min(...rets) : null,
    };
  }, [closed]);

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
    <div data-testid={`equity-strategy-${strategy.slug}`}>
      <section className="mb-10">
        <SectionHeader no="01" title="Live Status" />
        <StatusPanel entry={entry} />
      </section>

      <section className="mb-10">
        <SectionHeader no="02" title="Performance Snapshot" />
        {stats.totalTrades > 0 ? (
          <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-3">
            <KpiCard label="Total Trades" value={stats.totalTrades} />
            <KpiCard label="Win Rate" value={stats.winRate != null ? `${(stats.winRate * 100).toFixed(0)}%` : "—"} tone={stats.winRate > 0.5 ? "pos" : "neg"} />
            <KpiCard label="Avg Win" value={stats.avgWin != null ? `+${stats.avgWin.toFixed(2)}%` : "—"} tone="pos" />
            <KpiCard label="Avg Loss" value={stats.avgLoss != null ? `${stats.avgLoss.toFixed(2)}%` : "—"} tone="neg" />
            <KpiCard label="Profit Factor" value={fmtNum(stats.profitFactor)} tone={stats.profitFactor > 1 ? "pos" : "neg"} />
            <KpiCard label="Best Trade" value={stats.bestTrade != null ? `+${stats.bestTrade.toFixed(2)}%` : "—"} tone="pos" />
            <KpiCard label="Worst Trade" value={stats.worstTrade != null ? `${stats.worstTrade.toFixed(2)}%` : "—"} tone="neg" />
            <KpiCard label="Open Positions" value={positions.length - closed.length} />
          </div>
        ) : <p className="text-sm text-slate-500">No closed positions yet — this strategy hasn't filtered into a real entry so far.</p>}
      </section>

      {backtest && (
        <section className="mb-10">
          <SectionHeader no="03" title="Backtest Scan" />
          <div className={`${SURFACE} p-5 grid grid-cols-2 sm:grid-cols-3 gap-4`}>
            <div>
              <p className="font-mono-ui text-[9px] uppercase tracking-wider text-slate-600 mb-1">Universe Size</p>
              <p className="text-sm font-bold text-white">{backtest.universe_size}</p>
            </div>
            <div>
              <p className="font-mono-ui text-[9px] uppercase tracking-wider text-slate-600 mb-1">Signals Found</p>
              <p className="text-sm font-bold text-white">{backtest.signals_found}</p>
            </div>
            <div>
              <p className="font-mono-ui text-[9px] uppercase tracking-wider text-slate-600 mb-1">Recorded</p>
              <p className="text-sm font-bold text-white">{new Date(backtest.recorded_at).toLocaleDateString("en-IN")}</p>
            </div>
          </div>
          <p className="text-xs text-slate-500 mt-3">{backtest.note}</p>
        </section>
      )}

      <section className="mb-10">
        <SectionHeader no={backtest ? "04" : "03"} title="Position History" />
        <PositionTable positions={positions} slug={strategy.slug} />
      </section>

      <section className="mb-6">
        <SectionHeader no={backtest ? "05" : "04"} title="Rules" />
        <RulesAccordion strategyId={strategy.apiPath} />
      </section>
    </div>
  );
}
