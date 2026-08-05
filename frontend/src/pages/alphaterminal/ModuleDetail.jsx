import { useEffect, useState } from "react";
import axios from "axios";
import { Link, useParams, useNavigate } from "react-router-dom";
import { motion } from "framer-motion";
import { ArrowLeft, ChevronDown, ChevronRight, ExternalLink, Loader2 } from "lucide-react";
import Navbar from "../../components/site/Navbar";
import Footer from "../../components/site/Footer";
import {
  MomentumTable, StraddleCompass, getMarketUpdatedLabel, openTradingViewChart,
} from "../AlphaTerminal";
import { getModule } from "./modules";
import EwmaCrossoverTool from "./EwmaCrossover";
import SharpeDashboardTool from "./SharpeDashboard";
import ExitlineTool from "./Exitline";
import RelativeStrengthMatrix from "./RelativeStrengthMatrix";
import BreadthTool from "./Breadth";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;
const EASE = [0.16, 1, 0.3, 1];
const SURFACE = "rounded-2xl border border-white/10 bg-[#0A0D18]";

/* ------------------------------ Section shell ------------------------------ */
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
        {canCollapse && <ChevronDown size={18} className={`text-slate-500 transition-transform duration-300 shrink-0 ${open ? "rotate-180" : ""}`} />}
      </div>
      {(!canCollapse || open) && children}
    </motion.section>
  );
};

/* --------------------------------- Header --------------------------------- */
const Header = ({ module }) => (
  <section className="relative pt-28 pb-10 md:pt-32 md:pb-14" data-testid="module-header">
    <div className="container-x">
      <Link to="/alpha-terminal" className="inline-flex items-center gap-2 text-sm text-slate-400 hover:text-white transition-colors mb-8" data-testid="back-to-terminal">
        <ArrowLeft size={15} /> Back
      </Link>

      <p className="flex items-center gap-2 font-mono-ui text-xs text-slate-500 mb-4">
        <Link to="/alpha-terminal" className="hover:text-white transition-colors">Alpha Terminal</Link>
        <ChevronRight size={12} />
        <span className="text-slate-300">{module.title}</span>
      </p>

      <div className="flex flex-col lg:flex-row lg:items-end lg:justify-between gap-8">
        <div>
          <h1 className="font-display font-black tracking-tighter text-white text-4xl md:text-5xl leading-[0.95]">{module.title}</h1>
          <div className="flex items-center gap-2 mt-5">
            <span className="relative flex h-2 w-2">
              {module.status === "Operational" && <span className="absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-60 animate-ping" />}
              <span className={`relative inline-flex h-2 w-2 rounded-full ${module.status === "Operational" ? "bg-emerald-400" : "bg-slate-500"}`} />
            </span>
            <span className={`font-mono-ui text-xs uppercase tracking-wider ${module.status === "Operational" ? "text-emerald-300" : "text-slate-400"}`}>
              {module.status}
            </span>
            {module.category && (
              <>
                <span className="text-slate-600">·</span>
                <span className="font-mono-ui text-xs uppercase tracking-wider text-slate-400">{module.category}</span>
              </>
            )}
          </div>
        </div>

        <div className="flex gap-8 shrink-0">
          <div>
            <p className="font-mono-ui text-[10px] uppercase tracking-[0.16em] text-slate-500 mb-1 whitespace-nowrap">Universe</p>
            <p className="text-sm text-white whitespace-nowrap">{module.universe}</p>
          </div>
          <div>
            <p className="font-mono-ui text-[10px] uppercase tracking-[0.16em] text-slate-500 mb-1 whitespace-nowrap">Coverage</p>
            <p className="text-sm text-white whitespace-nowrap">{module.coverage}</p>
          </div>
        </div>
      </div>
    </div>
  </section>
);

// Swing Picks isn't a scored/biased list like momentum — just Scrip,
// Company, LCP, and a reference Buy At level (no momentum score/volume/bias
// columns), so it gets its own simple table rather than overloading
// MomentumTable's shape.
const SwingPicksTable = ({ rows }) => (
  <div className={`${SURFACE} overflow-hidden`} data-testid="swing-picks-table">
    <div className="overflow-x-auto">
      <table className="w-full" style={{ fontVariantNumeric: "tabular-nums" }}>
        <thead>
          <tr className="border-b border-white/10">
            {[["Scrip", "left"], ["Company", "left"], ["LCP", "right"], ["Breakout Level", "right"], ["% from Breakout", "right"]].map(([h, align]) => (
              <th key={h} className={`px-6 py-5 font-mono-ui text-[11px] uppercase tracking-[0.18em] text-slate-500 font-semibold whitespace-nowrap text-${align}`}>{h}</th>
            ))}
            <th className="px-6 py-5 w-10"><span className="sr-only">Chart</span></th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => {
            const pctFromBreakout = r.lcp && r.buy_at ? ((r.lcp - r.buy_at) / r.buy_at) * 100 : null;
            return (
              <tr
                key={r.id}
                onClick={() => openTradingViewChart(r.ticker)}
                className="group border-b border-white/[0.05] last:border-0 transition-colors duration-300 hover:bg-sapphire/[0.06] cursor-pointer"
                data-testid={`swing-picks-row-${i}`}
              >
                <td className="px-6 py-5 font-display text-lg font-extrabold text-white whitespace-nowrap">
                  <span className="group-hover:underline">{r.ticker}</span>
                </td>
                <td className="px-6 py-5 text-sm text-slate-300 whitespace-nowrap">{r.company || "—"}</td>
                <td className="px-6 py-5 font-mono-ui text-sm text-right text-slate-300 whitespace-nowrap">{r.lcp ? `₹${fmtNum(r.lcp)}` : "—"}</td>
                <td className="px-6 py-5 font-mono-ui text-sm text-right text-sapphire-light whitespace-nowrap">{r.buy_at ? `₹${fmtNum(r.buy_at)}` : "—"}</td>
                <td className={`px-6 py-5 font-mono-ui text-sm text-right whitespace-nowrap ${pctFromBreakout == null ? "text-slate-500" : pctFromBreakout >= 0 ? "text-emerald-400" : "text-red-400"}`}>
                  {fmtPctSigned(pctFromBreakout)}
                </td>
                <td className="px-6 py-5">
                  <ExternalLink size={14} className="text-slate-500 opacity-40 group-hover:opacity-100 transition-opacity" data-testid={`swing-picks-chart-link-${i}`} />
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
    <div className="px-5 md:px-6 py-5 border-t border-white/10">
      <p className="text-xs font-light text-slate-500 leading-relaxed max-w-4xl" data-testid="swing-picks-disclaimer">
        Breakout Level is a reference entry level, not a live trigger — these are multi-day setups meant to be held and reviewed over days to weeks. Not investment advice.
      </p>
    </div>
  </div>
);

/* ----------------------------- Live Dashboard ----------------------------- */
const ScannerDashboard = ({ scannerKey }) => {
  const [rows, setRows] = useState(null);
  useEffect(() => {
    axios.get(`${API}/terminal/stocks`, { params: { scanner: scannerKey } }).then((r) => setRows(r.data)).catch(() => setRows([]));
  }, [scannerKey]);

  if (rows === null) {
    return <div className="flex items-center justify-center py-16 text-slate-500 font-mono-ui text-sm gap-3"><Loader2 className="animate-spin" size={16} /> Loading…</div>;
  }
  if (rows.length === 0) {
    return (
      <div className={`${SURFACE} border-dashed px-6 py-14 text-center`} data-testid="dashboard-empty">
        <p className="font-mono-ui text-[11px] uppercase tracking-[0.28em] text-slate-600 mb-3">Calibration in Progress</p>
        <p className="text-sm font-light text-slate-500 max-w-sm mx-auto">This engine's data feed is still being calibrated and isn't producing live output yet.</p>
      </div>
    );
  }
  return (
    <>
      <p className="font-mono-ui text-[11px] text-slate-500 mb-4">Updated: {getMarketUpdatedLabel()}</p>
      {scannerKey === "swing_picks" ? <SwingPicksTable rows={rows} /> : <MomentumTable rows={rows} />}
    </>
  );
};

// IndexTabs used to live here (shared by Live Dashboard's design and the
// public Historical Performance section) - moved to AlphaTerminal.jsx's
// exports since Historical Performance's real display is admin-only now
// (Admin.jsx's IndexTrackRecordPanel) and this file no longer needs it.
// Live Dashboard shows all covered indices at once as cards instead (no
// selector needed - this is the "what's happening right now" view). With
// an odd count (3, as of 2026-08-03's NIFTY/BANKNIFTY/FINNIFTY lineup) the
// last card spans both columns on md+ for a 2-1 formation instead of
// leaving a dangling gap next to it.
const LiveDashboard = ({ module, signals }) => (
  <Section no="01" title="Live Dashboard" testId="section-live-dashboard">
    {module.kind === "vector" && (
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4" data-testid="vector-index-grid">
        {module.indices.map((idx, i) => {
          const isLastOfOdd = i === module.indices.length - 1 && module.indices.length % 2 === 1;
          return (
            <div key={idx} className={isLastOfOdd ? "md:col-span-2" : ""}>
              <StraddleCompass signal={signals[idx]} index={idx} />
            </div>
          );
        })}
      </div>
    )}
    {module.kind === "scanner" && <ScannerDashboard scannerKey={module.scannerKey} />}
    {module.kind === "ewma" && <EwmaCrossoverTool />}
    {module.kind === "sharpe" && <SharpeDashboardTool />}
    {module.kind === "exitline" && <ExitlineTool />}
    {module.kind === "matrix" && <RelativeStrengthMatrix />}
    {module.kind === "breadth" && <BreadthTool />}
  </Section>
);

/* ------------------------ Scanner track record (Momentum) ------------------------ */
const fmtNum = (v, dp = 2) => (v == null ? "—" : Number(v).toFixed(dp));
const fmtPctSigned = (v, dp = 2) => (v == null ? "—" : `${v > 0 ? "+" : ""}${Number(v).toFixed(dp)}%`);
const fmtDateLong = (iso) => {
  if (!iso) return "—";
  const d = new Date(`${iso}T00:00:00`);
  return d.toLocaleDateString("en-GB", { day: "2-digit", month: "short", year: "numeric" });
};

const ScannerStat = ({ label, value, tone = "text-white" }) => (
  <div className={`${SURFACE} p-4 text-center`}>
    <p className="font-mono-ui text-[10px] uppercase tracking-[0.16em] text-slate-500 mb-1.5">{label}</p>
    <p className={`font-mono-ui text-xl font-bold ${tone}`}>{value}</p>
  </div>
);

// Real, date-wise performance tracking for the "momentum" scanner — captured
// automatically when the scanner's rows are replaced (entry price at that
// moment) and scored once each day's session closes. See
// backend/momentum_track_record.py for the bullish/bearish scoring rule.
// This is the only scanner with real history right now; other scanner-kind
// modules still fall through to the generic "still accumulating" message.
const ScannerTrackRecord = ({ scannerKey }) => {
  const [record, setRecord] = useState(null);
  const [selectedDate, setSelectedDate] = useState("all");
  const [logsOpen, setLogsOpen] = useState(false);
  useEffect(() => {
    axios.get(`${API}/terminal/scanner-track-record`, { params: { scanner: scannerKey } })
      .then((r) => setRecord(r.data)).catch(() => setRecord({ has_data: false }));
  }, [scannerKey]);

  if (!record) {
    return <div className="flex items-center justify-center py-16 text-slate-500 font-mono-ui text-sm gap-3"><Loader2 className="animate-spin" size={16} /> Loading…</div>;
  }
  if (!record.has_data) {
    return (
      <div className={`${SURFACE} border-dashed px-6 py-14 text-center`} data-testid="momentum-track-empty">
        <p className="text-sm font-light text-slate-500 max-w-md mx-auto">
          No calls have been scored yet. Each day's recommendations are graded once that trading session closes — check back after a few sessions for a meaningful read.
        </p>
      </div>
    );
  }

  const { overall, bullish, bearish, recent, since, trading_days, best_call, worst_call } = record;
  const winRatePct = (r) => (r?.win_rate != null ? `${(r.win_rate * 100).toFixed(0)}%` : "—");
  const ratioFmt = (r) => (r != null ? `${r.toFixed(2)} : 1` : "—");
  const availableDates = [...new Set(recent.map((r) => r.date))].sort((a, b) => (a < b ? 1 : -1));
  const visibleRows = selectedDate === "all" ? recent : recent.filter((r) => r.date === selectedDate);
  const perfTone = (v) => (v > 0 ? "text-emerald-400" : v < 0 ? "text-red-400" : "text-white");

  return (
    <>
      <p className="text-xs text-slate-500 mb-4">
        Tracking since <span className="text-slate-300">{since}</span> — {overall.count} call{overall.count === 1 ? "" : "s"} scored.
      </p>

      <p className="font-mono-ui text-[10px] uppercase tracking-[0.16em] text-slate-500 font-semibold mb-3">Key Metrics</p>
      <div className="grid grid-cols-2 md:grid-cols-5 gap-3 mb-3">
        <ScannerStat label="Overall Win Rate" value={winRatePct(overall)} tone={overall.win_rate > 0.5 ? "text-emerald-400" : "text-white"} />
        <ScannerStat label="Average Return" value={fmtPctSigned(overall.avg_performance_pct)} tone={perfTone(overall.avg_performance_pct)} />
        <ScannerStat label="Median Return" value={fmtPctSigned(overall.median_performance_pct)} tone={perfTone(overall.median_performance_pct)} />
        <ScannerStat label="Total Calls" value={overall.count} />
        <ScannerStat label="Trading Days" value={trading_days} />
      </div>
      {/* Risk : Reward card removed for now — re-add once risk < reward (overall.risk_reward available via ratioFmt(overall.risk_reward)). */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-4 md:w-4/5 md:mx-auto">
        <ScannerStat label="Avg. Max Upside" value={fmtPctSigned(overall.avg_best_case_pct)} tone="text-emerald-400" />
        <ScannerStat label="Avg. Max Drawdown" value={fmtPctSigned(overall.avg_worst_case_pct)} tone="text-red-400" />
        <ScannerStat label={`Bullish (${bullish.count}) Win Rate`} value={winRatePct(bullish)} tone="text-emerald-400" />
        <ScannerStat label={`Bearish (${bearish.count}) Win Rate`} value={winRatePct(bearish)} tone="text-red-400" />
      </div>
      <div className="grid grid-cols-2 gap-3 mb-6">
        <ScannerStat label="Bullish Avg. Return" value={fmtPctSigned(bullish.avg_performance_pct)} tone={perfTone(bullish.avg_performance_pct)} />
        <ScannerStat label="Bearish Avg. Return" value={fmtPctSigned(bearish.avg_performance_pct)} tone={perfTone(bearish.avg_performance_pct)} />
      </div>

      {(best_call || worst_call) && (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3 mb-6">
          {best_call && (
            <div className={`${SURFACE} p-4`}>
              <p className="font-mono-ui text-[10px] uppercase tracking-[0.16em] text-slate-500 mb-2">Best Call</p>
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-sm font-bold text-white">{best_call.ticker} <span className="text-slate-500 font-normal">· {fmtDateLong(best_call.date)}</span></p>
                  <p className={`text-xs ${best_call.bias === "Bullish" ? "text-emerald-400" : "text-red-400"}`}>{best_call.bias}</p>
                </div>
                <p className="font-mono-ui text-xl font-bold text-emerald-400">{fmtPctSigned(best_call.performance_pct)}</p>
              </div>
            </div>
          )}
          {worst_call && (
            <div className={`${SURFACE} p-4`}>
              <p className="font-mono-ui text-[10px] uppercase tracking-[0.16em] text-slate-500 mb-2">Worst Call</p>
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-sm font-bold text-white">{worst_call.ticker} <span className="text-slate-500 font-normal">· {fmtDateLong(worst_call.date)}</span></p>
                  <p className={`text-xs ${worst_call.bias === "Bullish" ? "text-emerald-400" : "text-red-400"}`}>{worst_call.bias}</p>
                </div>
                <p className="font-mono-ui text-xl font-bold text-red-400">{fmtPctSigned(worst_call.performance_pct)}</p>
              </div>
            </div>
          )}
        </div>
      )}

      <p className="text-[11px] font-light text-slate-600 mb-6">
        A Bullish call profits if price rises by close; a Bearish call profits if price falls (shown as positive performance either way).
        High/Low are measured from the 9:40 alert price onward only, not the full trading day. Past performance does not guarantee future results — not investment advice.
      </p>

      {recent.length > 0 && (
        <div className={`${SURFACE} overflow-hidden`}>
          <button
            type="button"
            onClick={() => setLogsOpen((o) => !o)}
            className="w-full flex items-center justify-between gap-3 px-4 py-3.5 text-left"
            data-testid="momentum-track-logs-toggle"
          >
            <span className="font-mono-ui text-[10px] uppercase tracking-[0.14em] text-slate-400 font-semibold">
              Logs — {recent.length} call{recent.length === 1 ? "" : "s"}
            </span>
            <ChevronDown size={16} className={`text-slate-500 transition-transform duration-300 shrink-0 ${logsOpen ? "rotate-180" : ""}`} />
          </button>
          {logsOpen && (
            <>
              <div className="flex items-center justify-end gap-3 px-4 py-3 border-t border-white/10">
                <label className="flex items-center gap-2 text-xs text-slate-400">
                  <span className="font-mono-ui uppercase tracking-[0.1em] text-[10px] text-slate-500">Date</span>
                  <select
                    value={selectedDate}
                    onChange={(e) => setSelectedDate(e.target.value)}
                    data-testid="momentum-track-date-filter"
                    className="bg-black/40 border border-white/10 rounded-md px-2.5 py-1.5 text-slate-200 text-xs font-mono-ui focus:outline-none focus:border-white/30"
                  >
                    <option value="all">All Dates</option>
                    {availableDates.map((d) => (
                      <option key={d} value={d}>{fmtDateLong(d)}</option>
                    ))}
                  </select>
                </label>
              </div>
              <div className="overflow-x-auto">
                <table className="w-full min-w-[920px]" style={{ fontVariantNumeric: "tabular-nums" }}>
                  <thead>
                    <tr className="border-b border-white/10">
                      {[
                        ["Date", "left"], ["Ticker", "left"], ["Bias", "left"],
                        ["Alert Price (9:40)", "right"], ["High After 9:40", "right"], ["Low After 9:40", "right"], ["Close", "right"],
                        ["Return", "right"], ["Max Upside", "right"], ["Max Drawdown", "right"],
                      ].map(([h, align]) => (
                        <th key={h} className={`px-4 py-3 font-mono-ui text-[10px] uppercase tracking-[0.14em] text-slate-500 font-semibold whitespace-nowrap text-${align}`}>{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {visibleRows.map((r) => (
                      <tr key={r.id} className="border-b border-white/[0.05] last:border-0" data-testid={`momentum-track-row-${r.id}`}>
                        <td className="px-4 py-2.5 text-sm text-slate-300 whitespace-nowrap">{fmtDateLong(r.date)}</td>
                        <td className="px-4 py-2.5 text-sm font-bold text-white whitespace-nowrap">{r.ticker}</td>
                        <td className="px-4 py-2.5 text-sm whitespace-nowrap">
                          <span className={r.bias === "Bullish" ? "text-emerald-400" : "text-red-400"}>
                            {r.bias}
                          </span>
                        </td>
                        <td className="px-4 py-2.5 font-mono-ui text-sm text-right text-slate-300 whitespace-nowrap">₹{fmtNum(r.entry_price)}</td>
                        <td className="px-4 py-2.5 font-mono-ui text-sm text-right text-slate-300 whitespace-nowrap">₹{fmtNum(r.high_price)}</td>
                        <td className="px-4 py-2.5 font-mono-ui text-sm text-right text-slate-300 whitespace-nowrap">₹{fmtNum(r.low_price)}</td>
                        <td className="px-4 py-2.5 font-mono-ui text-sm text-right text-slate-300 whitespace-nowrap">₹{fmtNum(r.close_price)}</td>
                        <td className={`px-4 py-2.5 font-mono-ui text-sm text-right whitespace-nowrap ${r.performance_pct > 0 ? "text-emerald-400" : "text-red-400"}`}>{fmtPctSigned(r.performance_pct)}</td>
                        <td className="px-4 py-2.5 font-mono-ui text-sm text-right text-emerald-400/90 whitespace-nowrap">{fmtPctSigned(r.best_case_pct)}</td>
                        <td className="px-4 py-2.5 font-mono-ui text-sm text-right text-red-400/90 whitespace-nowrap">{fmtPctSigned(r.worst_case_pct)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          )}
        </div>
      )}
    </>
  );
};

/* -------------------------- Historical Performance -------------------------- */
// module.kind === "vector" (Index Vector) used to show a real IndexTabs +
// TrackRecordPanel here, fetched from GET /terminal/track-record. That route
// is admin-only now (2026-07-28, public site shows zero Index Vector
// historical performance for now) - see Admin.jsx's IndexTrackRecordPanel
// for the admin-only version, which reuses IndexTabs/TrackRecordPanel from
// AlphaTerminal.jsx. Vector-kind modules now fall through to the same
// generic placeholder every other not-yet-public module shows.
const HistoricalPerformance = ({ module }) => (
  <Section no="02" title="Historical Performance" testId="section-historical-performance" collapsible>
    {module.scannerKey === "momentum" ? (
      <ScannerTrackRecord scannerKey={module.scannerKey} />
    ) : (
      <div className={`${SURFACE} border-dashed px-6 py-14 text-center`} data-testid="historical-empty">
        <p className="text-sm font-light text-slate-500 max-w-md mx-auto">
          Historical signal tracking for this engine is still accumulating. Repeated daily snapshots build into a track record over time — check back as more sessions pass.
        </p>
      </div>
    )}
  </Section>
);

/* ---------------------------------- Page ---------------------------------- */
export default function ModuleDetail() {
  const { slug } = useParams();
  const navigate = useNavigate();
  const module = getModule(slug);
  const [signals, setSignals] = useState({});

  useEffect(() => {
    window.scrollTo(0, 0);
    if (!module || !module.live || module.kind !== "vector") return;

    const loadSignals = () => {
      module.indices.forEach((idx) => {
        axios.get(`${API}/terminal/signal`, { params: { index: idx } })
          .then((r) => setSignals((s) => ({ ...s, [idx]: r.data })))
          .catch(() => {});
      });
    };

    // Historical Performance (track-record accuracy) is admin-only for now
    // (2026-07-28) - GET /admin/terminal/track-record is admin-gated, so the
    // public page no longer fetches it at all. See Admin.jsx's
    // IndexTrackRecordPanel for the admin-only display.
    loadSignals();
    const id = setInterval(loadSignals, 60000);
    return () => clearInterval(id);
  }, [module]);

  if (!module) {
    return (
      <>
        <Navbar />
        <main className="relative bg-void min-h-screen flex items-center justify-center">
          <div className="text-center">
            <p className="font-mono-ui text-xs uppercase tracking-[0.2em] text-slate-500 mb-4">Not Found</p>
            <button onClick={() => navigate("/alpha-terminal")} className="btn-sapphire">Back to Alpha Terminal</button>
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
        <Header module={module} />
        <div className="container-x">
          {module.live ? (
            <>
              <LiveDashboard module={module} signals={signals} />
              {module.kind !== "exitline" && module.kind !== "matrix" && (
                <HistoricalPerformance module={module} />
              )}
            </>
          ) : (
            <PausedModuleNotice />
          )}
        </div>
      </main>
      <Footer />
    </>
  );
}

// Shown instead of the live dashboard for a paused module (module.live ===
// false, see modules.js) -- makes no API calls, matches the "Coming Soon"
// treatment used elsewhere on the site (Black Box's StrategyDetail).
const PausedModuleNotice = () => (
  <Section no="01" title="Live Dashboard" testId="section-live-dashboard">
    <div className={`${SURFACE} border-dashed px-6 py-14 text-center`} data-testid="module-coming-soon">
      <p className="font-mono-ui text-[11px] uppercase tracking-[0.28em] text-slate-600 mb-3">Coming Soon</p>
      <p className="text-sm font-light text-slate-500 max-w-sm mx-auto">This module is temporarily paused. Research access will resume once it's back online.</p>
    </div>
  </Section>
);
