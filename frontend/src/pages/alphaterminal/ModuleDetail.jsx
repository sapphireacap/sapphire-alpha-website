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
            <span className="text-slate-600">·</span>
            <span className="font-mono-ui text-xs uppercase tracking-wider text-slate-400">{module.category}</span>
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

/* ------------------------------- Overview ------------------------------- */
const Row = ({ label, value }) => (
  <div className="py-4 border-b border-white/[0.06] last:border-0 grid grid-cols-1 sm:grid-cols-[160px_1fr] gap-1 sm:gap-6">
    <p className="font-mono-ui text-[10px] uppercase tracking-[0.16em] text-slate-500">{label}</p>
    <p className="text-sm text-slate-300 leading-relaxed">{value}</p>
  </div>
);

const Overview = ({ overview }) => (
  <Section no="01" title="Overview" testId="section-overview">
    <div className={`${SURFACE} p-6 md:p-8`}>
      <Row label="Purpose" value={overview.purpose} />
      <Row label="What It Measures" value={overview.whatItMeasures} />
      <Row label="How To Interpret" value={overview.interpret} />
    </div>
  </Section>
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
      <MomentumTable rows={rows} />
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

const LiveDashboard = ({ module, signals, activeIndex, onChangeIndex }) => (
  <Section no="02" title="Live Dashboard" testId="section-live-dashboard">
    {module.kind === "vector" && (
      <>
        <IndexTabs indices={module.indices} active={activeIndex} onChange={onChangeIndex} />
        <StraddleCompass signal={signals[activeIndex]} index={activeIndex} />
      </>
    )}
    {module.kind === "scanner" && <ScannerDashboard scannerKey={module.scannerKey} />}
    {module.kind === "ewma" && <EwmaCrossoverTool />}
    {module.kind === "sharpe" && <SharpeDashboardTool />}
  </Section>
);

/* -------------------------- Historical Performance -------------------------- */
const HistoricalPerformance = ({ module, trackRecords, activeIndex, onChangeIndex }) => (
  <Section no="03" title="Historical Performance" testId="section-historical-performance" collapsible>
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

/* -------------------------------- Methodology -------------------------------- */
const Methodology = ({ text }) => (
  <Section no="04" title="Methodology" testId="section-methodology">
    <div className={`${SURFACE} p-6 md:p-8 border-l-2 border-l-sapphire`}>
      <p className="text-base md:text-lg font-light text-slate-300 leading-relaxed italic max-w-3xl">"{text}"</p>
    </div>
  </Section>
);

/* ------------------------------- Research Notes ------------------------------- */
const fmtNoteDate = (iso) => {
  const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  const [y, m, d] = iso.split("-");
  return `${d} ${MONTHS[Number(m) - 1]} ${y}`;
};

const ResearchNotes = ({ notes }) => (
  <Section no="05" title="Research Notes" testId="section-research-notes" collapsible>
    <div className={`${SURFACE} divide-y divide-white/[0.06]`}>
      {notes.map((n, i) => (
        <div key={i} className="flex gap-6 px-6 py-4">
          <span className="font-mono-ui text-xs text-slate-500 shrink-0 w-24">{fmtNoteDate(n.date)}</span>
          <span className="text-sm text-slate-300 leading-relaxed">{n.note}</span>
        </div>
      ))}
    </div>
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
          <Overview overview={module.overview} />
          <LiveDashboard module={module} signals={signals} activeIndex={activeIndex} onChangeIndex={setActiveIndex} />
          <HistoricalPerformance module={module} trackRecords={trackRecords} activeIndex={activeIndex} onChangeIndex={setActiveIndex} />
          <Methodology text={module.methodology} />
          <ResearchNotes notes={module.researchNotes} />
        </div>
      </main>
      <Footer />
    </>
  );
}
