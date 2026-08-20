import { useEffect, useState } from "react";
import axios from "axios";
import { Link, useParams, useNavigate } from "react-router-dom";
import { motion } from "framer-motion";
import { ArrowLeft, ChevronDown, ChevronRight, ExternalLink, Loader2 } from "lucide-react";
import Navbar from "../../components/site/Navbar";
import Footer from "../../components/site/Footer";
import {
  MomentumTable, openTradingViewChart,
} from "../AlphaTerminal";
import { getModule, moduleRequiresAuth } from "./modules";
import EwmaCrossoverTool from "./EwmaCrossover";
import SharpeDashboardTool from "./SharpeDashboard";
import MomentumDashboardTool from "./MomentumDashboard";
import ExitlineTool from "./Exitline";
import RelativeStrengthMatrix from "./RelativeStrengthMatrix";
import BreadthTool from "./Breadth";
import OptionsTrendTool from "./OptionsTrend";
import PeterTingleTool from "./PeterTingle";
import { useIsAdmin, useIsSignedIn } from "../../lib/auth";
import USExitlineTool from "./USExitline";
import { USMomentumLeadersTool, USMomentumInvestingTool } from "./USMomentum";
import USMarketAssessmentTool from "./USMarketAssessment";
import CryptoDashboard from "./CryptoDashboard";
import { MMMomentumLeaders, MMIndexVector, MMUnavailable } from "./MultiMarketTools";
import { VectorHero, IndexIntelligenceCard, IntelligenceFeatureStrip } from "./IndexVectorHero";

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
      className={`${title ? "pt-10 md:pt-14" : "pt-5 md:pt-6"} pb-10 md:pb-14 border-t border-white/[0.06]`}
      data-testid={testId}
    >
      {title && (
        <div
          className={`flex items-center justify-between gap-3 ${open ? "mb-6 md:mb-8" : ""} ${canCollapse ? "cursor-pointer" : ""}`}
          onClick={canCollapse ? () => setOpen((o) => !o) : undefined}
        >
          <div className="flex items-baseline gap-3">
            <span className="font-mono-ui text-xs text-sapphire-light">{no}</span>
            <h2 className="text-2xl md:text-3xl font-bold text-white tracking-tight">{title}</h2>
          </div>
          {canCollapse && <ChevronDown size={18} className={`text-slate-500 transition-transform duration-300 shrink-0 ${open ? "rotate-180" : ""}`} />}
        </div>
      )}
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

      {module.kind === "vector" ? (
        <VectorHero title={module.title} description={module.shortDescription} />
      ) : (
        <div>
          <h1 className="font-display font-normal tracking-[-0.015em] text-white text-4xl md:text-5xl leading-[0.95]">{module.title}</h1>
          {module.shortDescription && (
            <p className="text-sm md:text-base text-slate-400 font-light mt-4 max-w-xl">{module.shortDescription}</p>
          )}
        </div>
      )}
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
                <td className="px-6 py-5 text-lg font-extrabold text-white whitespace-nowrap">
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
  return scannerKey === "swing_picks" ? <SwingPicksTable rows={rows} /> : <MomentumTable rows={rows} />;
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
  <Section no="01" testId="section-live-dashboard">
    {module.kind === "vector" && (
      <>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4" data-testid="vector-index-grid">
          {module.indices.map((idx, i) => {
            const isLastOfOdd = i === module.indices.length - 1 && module.indices.length % 2 === 1;
            return (
              <div key={idx} className={isLastOfOdd ? "md:col-span-2" : ""}>
                <IndexIntelligenceCard signal={signals[idx]} index={idx} />
              </div>
            );
          })}
        </div>
        <IntelligenceFeatureStrip />
      </>
    )}
    {module.kind === "scanner" && <ScannerDashboard scannerKey={module.scannerKey} />}
    {module.kind === "ewma" && <EwmaCrossoverTool />}
    {module.kind === "sharpe" && <SharpeDashboardTool />}
    {module.kind === "momentum-investing" && <MomentumDashboardTool />}
    {module.kind === "exitline" && <ExitlineTool />}
    {module.kind === "matrix" && <RelativeStrengthMatrix groupPrefix="nifty-" />}
    {module.kind === "breadth" && <BreadthTool />}
    {module.kind === "options-trend" && <OptionsTrendTool />}
    {module.kind === "peter-tingle" && <PeterTingleTool />}
    {module.kind === "us-exitline" && <USExitlineTool />}
    {module.kind === "us-momentum-leaders" && <USMomentumLeadersTool />}
    {module.kind === "us-momentum-investing" && <USMomentumInvestingTool />}
    {module.kind === "us-breadth" && <BreadthTool seriesPath="/us-markets/breadth" fixedGroup="sp500" />}
    {module.kind === "us-relative-strength" && <RelativeStrengthMatrix groupPrefix="us-" defaultGroup="us-technology" />}
    {module.kind === "us-market-assessment" && <USMarketAssessmentTool />}
    {/* Adapter-backed modules — one component per module, `market` picks
        the data source. See MultiMarketTools.jsx for why these are generic
        rather than one component per (module x market). */}
    {/* The SAME Exitline tool the US tab renders — candlestick chart, level
        ladder and SL/TP panel — pointed at this market's endpoints. */}
    {module.kind === "mm-exitline" && (
      <USExitlineTool
        searchPath={`/markets/${module.market}/search`}
        levelsPath={`/markets/${module.market}/exitline`}
        placeholder={module.market === "crypto" ? "Search pair… e.g. BTCUSDT" : "Search pair… e.g. EURUSD"}
      />
    )}
    {/* The SAME BreadthTool the India and US tabs render — it was already
        endpoint-parameterised, so multi-market needed no new UI at all. */}
    {module.kind === "mm-breadth" && (
      <BreadthTool
        groupsPath={`/markets/${module.market}/breadth/groups`}
        seriesPath={`/markets/${module.market}/breadth`}
      />
    )}
    {module.kind === "mm-relative-strength" && (
      <RelativeStrengthMatrix
        groupsPath={`/markets/${module.market}/relative-strength/groups`}
        matrixPath={`/markets/${module.market}/relative-strength/matrix`}
        dateIsUs
      />
    )}
    {module.kind === "mm-momentum-investing" && (
      <MomentumDashboardTool
        universePath={`/markets/${module.market}/universe-symbols`}
        dashboardPath={`/markets/${module.market}/momentum-dashboard`}
        statusPath={`/markets/${module.market}/momentum-refresh-status`}
      />
    )}
    {module.kind === "mm-momentum-leaders" && <MMMomentumLeaders market={module.market} />}
    {module.kind === "mm-sharpe" && (
      <SharpeDashboardTool
        universePath={`/markets/${module.market}/universe-symbols`}
        dashboardPath={`/markets/${module.market}/sharpe-dashboard`}
        statusPath={`/markets/${module.market}/sharpe-refresh-status`}
      />
    )}
    {module.kind === "mm-ewma" && (
      <EwmaCrossoverTool
        scanPath={`/markets/${module.market}/ewma-crossover`}
        defaultSymbol={module.market === "crypto" ? "BTCUSDT" : module.market === "forex" ? "EURUSD" : "AAPL"}
      />
    )}
    {module.kind === "mm-gamma-pulse" && (
      <OptionsTrendTool scanPath={`/markets/${module.market}/options-trend/scan`} />
    )}
    {module.kind === "mm-index-vector" && <MMIndexVector market={module.market} />}
    {/* India's own Peter Tingle tool already carries an India/US market
        toggle, so US uses it directly. Forex and Crypto never reach here —
        both are locked (no balance sheet behind a pair or a token). */}
    {module.kind === "mm-peter-tingle" && <PeterTingleTool />}
    {module.kind === "mm-unavailable" && <MMUnavailable module={module} />}
    {module.kind === "crypto-dashboard" && <CryptoDashboard />}
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

// Plain observation log for the "momentum" scanner — captured automatically
// when the scanner's rows are replaced. This is the only scanner with real
// history right now; other scanner-kind modules still fall through to the
// generic "still accumulating" message. Deliberately shows what was
// observed (date, ticker, bias), not how it subsequently performed — no
// win-rate/return/drawdown framing here (see backend/momentum_track_record.py
// for the scoring this deliberately doesn't surface).
const ScannerTrackRecord = ({ scannerKey }) => {
  const [record, setRecord] = useState(null);
  const [selectedDate, setSelectedDate] = useState("all");
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
          No observations recorded yet — check back after a few sessions.
        </p>
      </div>
    );
  }

  const { overall, recent, since } = record;
  const availableDates = [...new Set(recent.map((r) => r.date))].sort((a, b) => (a < b ? 1 : -1));
  const visibleRows = selectedDate === "all" ? recent : recent.filter((r) => r.date === selectedDate);

  return (
    <>
      <p className="text-xs text-slate-500 mb-4">
        Tracking since <span className="text-slate-300">{since}</span> — {overall.count} observation{overall.count === 1 ? "" : "s"}.
      </p>

      {recent.length > 0 && (
        <div className={`${SURFACE} overflow-hidden`}>
          <div className="flex items-center justify-end gap-3 px-4 py-3 border-b border-white/10">
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
            <table className="w-full" style={{ fontVariantNumeric: "tabular-nums" }}>
              <thead>
                <tr className="border-b border-white/10">
                  {[["Date", "left"], ["Ticker", "left"], ["Bias", "left"], ["Price at Alert", "right"]].map(([h, align]) => (
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
                      <span className={r.bias === "Bullish" ? "text-emerald-400" : "text-red-400"}>{r.bias}</span>
                    </td>
                    <td className="px-4 py-2.5 font-mono-ui text-sm text-right text-slate-300 whitespace-nowrap">₹{fmtNum(r.entry_price)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </>
  );
};

/* ---------------------------- Observation Archive ---------------------------- */
const HistoricalPerformance = ({ module }) => (
  <Section no="02" title="Observation Archive" testId="section-historical-performance" collapsible>
    {module.scannerKey === "momentum" ? (
      <ScannerTrackRecord scannerKey={module.scannerKey} />
    ) : (
      <div className={`${SURFACE} border-dashed px-6 py-14 text-center`} data-testid="historical-empty">
        <p className="text-sm font-light text-slate-500 max-w-md mx-auto">
          Observations are still accumulating — check back as more sessions pass.
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
  const isAdmin = useIsAdmin();
  const isSignedIn = useIsSignedIn();

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
      {/* Keyed by slug -- every module (India/US/crypto alike) shares this
          same route+component, so switching modules only re-renders with
          new props by default rather than unmounting. Nested tools
          (RelativeStrengthMatrix, Exitline, etc.) keep their own internal
          state (selected group, fetched rows) in useState, which would
          otherwise survive the switch and briefly show the PREVIOUS
          module's data under the NEW module's chrome -- confirmed live on
          mobile as India/US Relative Strength data bleeding together. The
          key forces a full unmount/remount of everything below on every
          slug change, so each module always starts clean. */}
      <main
        key={module.slug}
        className="relative bg-void min-h-screen"
        style={module.kind === "vector" ? { backgroundColor: "#080F1D" } : undefined}
      >
        <Header module={module} />
        <div className="container-x">
          {!module.live ? (
            <PausedModuleNotice module={module} />
          ) : module.adminOnly && isAdmin !== true ? (
            <AdminOnlyNotice loading={isAdmin === null} />
          ) : moduleRequiresAuth(module) && isSignedIn !== true ? (
            <SignInRequiredNotice loading={isSignedIn === null} />
          ) : (
            <>
              <LiveDashboard module={module} signals={signals} />
              {!["exitline", "matrix", "breadth", "options-trend",
                 "us-exitline", "us-momentum-leaders", "us-momentum-investing", "us-breadth", "us-relative-strength", "us-market-assessment",
                 // Adapter-backed modules have no track record of their own --
                 // they compute live off market data rather than persisting a
                 // call history the way the Vector does.
                 "mm-exitline", "mm-breadth", "mm-relative-strength", "mm-momentum-investing",
                 "mm-momentum-leaders", "mm-sharpe", "mm-ewma", "mm-gamma-pulse",
                 "mm-index-vector", "mm-peter-tingle", "mm-unavailable", "crypto-dashboard",
                 // Index Vector's own track record is admin-only now (see
                 // Admin.jsx's IndexTrackRecordPanel) -- this section had
                 // nothing to show a public visitor but an empty "still
                 // accumulating" placeholder, so it's dropped here too.
                 "vector",
                ].includes(module.kind) && (
                <HistoricalPerformance module={module} />
              )}
            </>
          )}
        </div>
      </main>
      <Footer />
    </>
  );
}

// Shown instead of the live dashboard for a paused module (module.live ===
// false, see modules.js) -- makes no API calls.
// `module.reason` is set when a module can't run in THIS market for a real
// instrument/data reason (see modules.js MARKET_BLOCKERS) -- show that
// instead of the generic paused copy, which would be misleading: nothing is
// coming back online, the instrument doesn't exist here.
const PausedModuleNotice = ({ module }) => (
  <Section no="01" testId="section-live-dashboard">
    <div className={`${SURFACE} border-dashed px-6 py-14 text-center`} data-testid="module-coming-soon">
      <p className="font-mono-ui text-[11px] uppercase tracking-[0.28em] text-slate-600 mb-3">Coming Soon</p>
      <p className="text-sm font-light text-slate-500 max-w-xl mx-auto leading-relaxed">
        {module?.reason || "This module is temporarily paused. Research access will resume once it's back online."}
      </p>
    </div>
  </Section>
);

// Shown instead of the live dashboard for an admin-only module
// (module.adminOnly, see modules.js) when useIsAdmin() resolves to
// anything but true -- covers a non-admin hitting the URL directly (the
// directory card itself isn't even a link for them, see AlphaTerminal.jsx's
// LockedDirectoryCard). `loading` covers the brief /auth/me round trip so
// this doesn't flash "Admin Access Required" at an admin before their
// role comes back. The backend (peter_tingle_routes.py) is independently
// admin-gated too -- this is UI-layer, not the only enforcement.
// Shown when a signed-out visitor opens a gated module's URL directly.
// Index Vector and Exitline never reach this; every other module does.
// The backend enforces the same rule independently — this is the humane
// version of the 401 the API would return anyway.
const SignInRequiredNotice = ({ loading }) => (
  <Section no="01" testId="section-live-dashboard">
    <div className={`${SURFACE} border-dashed px-6 py-14 text-center`} data-testid="module-signin-required">
      {loading ? (
        <Loader2 size={18} className="animate-spin text-slate-600 mx-auto" />
      ) : (
        <>
          <p className="font-mono-ui text-[11px] uppercase tracking-[0.28em] text-slate-600 mb-3">Sign In Required</p>
          <p className="text-sm font-light text-slate-500 max-w-sm mx-auto mb-6">
            This module is available to account holders.
          </p>
          <Link
            to="/auth"
            className="inline-flex items-center gap-1.5 rounded-full border border-sapphire-light/40 bg-sapphire/10 px-5 py-2.5 text-sm font-medium text-white hover:border-sapphire-light/70 transition-colors"
            data-testid="module-signin-cta"
          >
            Sign in or create an account <ChevronRight size={14} />
          </Link>
        </>
      )}
    </div>
  </Section>
);

const AdminOnlyNotice = ({ loading }) => (
  <Section no="01" testId="section-live-dashboard">
    <div className={`${SURFACE} border-dashed px-6 py-14 text-center`} data-testid="module-admin-only">
      {loading ? (
        <Loader2 size={18} className="animate-spin text-slate-600 mx-auto" />
      ) : (
        <>
          <p className="font-mono-ui text-[11px] uppercase tracking-[0.28em] text-slate-600 mb-3">Admin Access Required</p>
          <p className="text-sm font-light text-slate-500 max-w-sm mx-auto">This module is restricted to admin accounts.</p>
        </>
      )}
    </div>
  </Section>
);
