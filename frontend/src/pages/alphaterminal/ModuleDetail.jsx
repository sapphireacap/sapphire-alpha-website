import { useEffect, useState } from "react";
import axios from "axios";
import { Link, useParams, useNavigate } from "react-router-dom";
import { motion } from "framer-motion";
import { ArrowLeft, ChevronDown, ChevronRight, Loader2 } from "lucide-react";
import Navbar from "../../components/site/Navbar";
import Footer from "../../components/site/Footer";
import {
  MomentumTable, StraddleCompass, TrackRecordPanel, getMarketUpdatedLabel,
} from "../AlphaTerminal";
import { getModule } from "./modules";
import EwmaCrossoverTool from "./EwmaCrossover";
import SharpeDashboardTool from "./SharpeDashboard";
import ExitlineTool from "./Exitline";

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
            {[["Scrip", "left"], ["Company", "left"], ["LCP", "right"], ["Buy At", "right"]].map(([h, align]) => (
              <th key={h} className={`px-6 py-5 font-mono-ui text-[11px] uppercase tracking-[0.18em] text-slate-500 font-semibold whitespace-nowrap text-${align}`}>{h}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={r.id} className="border-b border-white/[0.05] last:border-0" data-testid={`swing-picks-row-${i}`}>
              <td className="px-6 py-5 font-display text-lg font-extrabold text-white whitespace-nowrap">{r.ticker}</td>
              <td className="px-6 py-5 text-sm text-slate-300 whitespace-nowrap">{r.company || "—"}</td>
              <td className="px-6 py-5 font-mono-ui text-sm text-right text-slate-300 whitespace-nowrap">{r.lcp ? `₹${fmtNum(r.lcp)}` : "—"}</td>
              <td className="px-6 py-5 font-mono-ui text-sm text-right text-sapphire-light whitespace-nowrap">{r.buy_at ? `₹${fmtNum(r.buy_at)}` : "—"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
    <div className="px-5 md:px-6 py-5 border-t border-white/10">
      <p className="text-xs font-light text-slate-500 leading-relaxed max-w-4xl" data-testid="swing-picks-disclaimer">
        Buy At is a reference entry level, not a live trigger — these are multi-day setups meant to be held and reviewed over days to weeks. Not investment advice.
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

// Shared by Live Dashboard and Historical Performance for a "vector" kind
// module — one small pill row selects which of the covered indices both
// sections show, so switching updates them together rather than needing two
// independent selectors.
const IndexTabs = ({ indices, active, onChange }) => (
  <div className="flex items-center gap-2 mb-5" data-testid="index-tabs">
    {indices.map((idx) => (
      <button
        key={idx}
        type="button"
        onClick={() => onChange(idx)}
        className={`px-3.5 py-1.5 rounded-full font-mono-ui text-[11px] uppercase tracking-[0.1em] whitespace-nowrap border transition-colors duration-300 ${
          active === idx ? "border-sapphire-light/50 bg-sapphire/10 text-white" : "border-white/10 text-slate-500 hover:text-slate-300"
        }`}
        data-testid={`index-tab-${idx}`}
      >
        {idx}
      </button>
    ))}
  </div>
);

// Live Dashboard shows all 4 covered indices at once as cards (no selector
// needed — this is the "what's happening right now" view). Historical
// Performance below is the one that still uses IndexTabs, since a track
// record is denser and reads better one index at a time.
const LiveDashboard = ({ module, signals }) => (
  <Section no="01" title="Live Dashboard" testId="section-live-dashboard">
    {module.kind === "vector" && (
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4" data-testid="vector-index-grid">
        {module.indices.map((idx) => (
          <StraddleCompass key={idx} signal={signals[idx]} index={idx} />
        ))}
      </div>
    )}
    {module.kind === "scanner" && <ScannerDashboard scannerKey={module.scannerKey} />}
    {module.kind === "ewma" && <EwmaCrossoverTool />}
    {module.kind === "sharpe" && <SharpeDashboardTool />}
    {module.kind === "exitline" && <ExitlineTool />}
  </Section>
);

/* ------------------------ Scanner track record (Momentum) ------------------------ */
// Moved to the admin-only dashboard (Admin.jsx's MomentumTrackRecordPanel) —
// public site shows zero performance data for now, per explicit instruction,
// same pattern as the Black Box redesign. Re-add here (and drop the
// admin-only gate on GET /admin/terminal/scanner-track-record) once the
// user is satisfied with the reset track record and wants it public again.
const fmtNum = (v, dp = 2) => (v == null ? "—" : Number(v).toFixed(dp));

/* -------------------------- Historical Performance -------------------------- */
const HistoricalPerformance = ({ module, trackRecords, activeIndex, onChangeIndex }) => (
  <Section no="02" title="Historical Performance" testId="section-historical-performance" collapsible>
    {module.kind === "vector" ? (
      <>
        <IndexTabs indices={module.indices} active={activeIndex} onChange={onChangeIndex} />
        <div className={`${SURFACE} p-6 md:p-8`}>
          <TrackRecordPanel record={trackRecords[activeIndex]} />
        </div>
      </>
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
  const [trackRecords, setTrackRecords] = useState({});
  const [activeIndex, setActiveIndex] = useState(module?.indices?.[0] || "NIFTY");

  useEffect(() => {
    window.scrollTo(0, 0);
    if (!module || module.kind !== "vector") return;

    const loadSignals = () => {
      module.indices.forEach((idx) => {
        axios.get(`${API}/terminal/signal`, { params: { index: idx } })
          .then((r) => setSignals((s) => ({ ...s, [idx]: r.data })))
          .catch(() => {});
      });
    };
    const loadTrackRecords = () => {
      module.indices.forEach((idx) => {
        axios.get(`${API}/terminal/track-record`, { params: { index: idx } })
          .then((r) => setTrackRecords((t) => ({ ...t, [idx]: r.data })))
          .catch(() => {});
      });
    };

    loadSignals();
    loadTrackRecords();
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
          <LiveDashboard module={module} signals={signals} />
          {module.kind !== "exitline" && (
            <HistoricalPerformance module={module} trackRecords={trackRecords} activeIndex={activeIndex} onChangeIndex={setActiveIndex} />
          )}
        </div>
      </main>
      <Footer />
    </>
  );
}
