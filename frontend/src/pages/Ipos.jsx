import { useEffect, useState } from "react";
import axios from "axios";
import { motion } from "framer-motion";
import { useNavigate } from "react-router-dom";
import { ArrowUpRight } from "lucide-react";
import Navbar from "../components/site/Navbar";
import Footer from "../components/site/Footer";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;
const EASE = [0.16, 1, 0.3, 1];

const STATUS_FILTERS = [
  { key: "", label: "All" },
  { key: "upcoming", label: "Upcoming" },
  { key: "open", label: "Open" },
  { key: "closed", label: "Closed" },
  { key: "listed", label: "Listed" },
];

export const IpoStatusBadge = ({ status, testid }) => {
  const map = {
    upcoming: { dot: "bg-slate-400", text: "text-slate-300", ring: "border-slate-400/25 bg-slate-400/10" },
    open: { dot: "bg-emerald-400", text: "text-emerald-300", ring: "border-emerald-400/30 bg-emerald-400/10" },
    closed: { dot: "bg-amber-400", text: "text-amber-300", ring: "border-amber-400/25 bg-amber-400/10" },
    listed: { dot: "bg-sapphire-light", text: "text-sapphire-light", ring: "border-sapphire/30 bg-sapphire/10" },
  };
  const s = map[status] || map.upcoming;
  return (
    <span className={`inline-flex items-center gap-2 rounded-full border px-3 py-1 text-xs font-medium capitalize ${s.ring} ${s.text}`} data-testid={testid}>
      <span className={`h-1.5 w-1.5 rounded-full ${s.dot}`} />
      {status}
    </span>
  );
};

const fmtPrice = (band) => {
  if (!band || (band.min == null && band.max == null)) return "—";
  if (band.min === band.max || band.max == null) return `₹${band.min}`;
  return `₹${band.min} – ₹${band.max}`;
};

const fmtDate = (iso) => {
  if (!iso) return "—";
  const [y, m, d] = iso.split("-");
  const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  return `${d} ${MONTHS[Number(m) - 1]} ${y}`;
};

const IpoTable = ({ rows, onOpen }) => (
  <div className="glass rounded-2xl overflow-hidden" data-testid="ipo-table">
    <div className="hidden md:block">
      <table className="w-full text-left">
        <thead>
          <tr className="border-b border-white/10">
            {["Company", "Exchange", "Price Band", "Opens", "Closes", "Status"].map((h) => (
              <th key={h} className="px-6 py-5 font-mono-ui text-[11px] uppercase tracking-[0.18em] text-slate-500 font-semibold whitespace-nowrap">
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <motion.tr
              key={r.id}
              initial={{ opacity: 0, y: 12 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.5, ease: EASE, delay: i * 0.04 }}
              onClick={() => onOpen(r.id)}
              className="border-b border-white/[0.05] last:border-0 transition-colors duration-300 hover:bg-sapphire/[0.06] cursor-pointer"
              data-testid={`ipo-row-${i}`}
            >
              <td className="px-6 py-5">
                <span className="font-display text-base font-bold text-white tracking-tight">{r.company_name}</span>
                {r.sector && <span className="block text-xs text-slate-500 mt-0.5">{r.sector}</span>}
              </td>
              <td className="px-6 py-5 text-sm text-slate-300 whitespace-nowrap">{(r.exchange || []).join(", ") || "—"}</td>
              <td className="px-6 py-5 font-mono-ui text-sm text-slate-300 whitespace-nowrap">{fmtPrice(r.price_band)}</td>
              <td className="px-6 py-5 text-sm text-slate-400 whitespace-nowrap">{fmtDate(r.issue_open_date)}</td>
              <td className="px-6 py-5 text-sm text-slate-400 whitespace-nowrap">{fmtDate(r.issue_close_date)}</td>
              <td className="px-6 py-5"><IpoStatusBadge status={r.status} testid={`ipo-status-${i}`} /></td>
            </motion.tr>
          ))}
        </tbody>
      </table>
    </div>

    <div className="md:hidden divide-y divide-white/[0.06]">
      {rows.map((r, i) => (
        <motion.div
          key={r.id}
          initial={{ opacity: 0, y: 12 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.5, ease: EASE, delay: i * 0.04 }}
          onClick={() => onOpen(r.id)}
          className="p-5"
          data-testid={`ipo-card-${i}`}
        >
          <div className="flex items-center justify-between mb-2">
            <span className="font-display text-lg font-bold text-white tracking-tight">{r.company_name}</span>
            <IpoStatusBadge status={r.status} testid={`ipo-status-mobile-${i}`} />
          </div>
          {r.sector && <p className="text-xs text-slate-500 mb-3">{r.sector}</p>}
          <div className="flex items-center gap-6 text-sm">
            <div>
              <p className="font-mono-ui text-[10px] uppercase tracking-[0.18em] text-slate-500 mb-1">Price Band</p>
              <span className="font-mono-ui text-slate-300">{fmtPrice(r.price_band)}</span>
            </div>
            <div>
              <p className="font-mono-ui text-[10px] uppercase tracking-[0.18em] text-slate-500 mb-1">Window</p>
              <span className="text-slate-300">{fmtDate(r.issue_open_date)} – {fmtDate(r.issue_close_date)}</span>
            </div>
          </div>
        </motion.div>
      ))}
    </div>
  </div>
);

export default function Ipos() {
  const [ipos, setIpos] = useState([]);
  const [status, setStatus] = useState("");
  const [loading, setLoading] = useState(true);
  const navigate = useNavigate();

  useEffect(() => {
    window.scrollTo(0, 0);
    setLoading(true);
    axios.get(`${API}/ipos`, { params: status ? { status } : {} })
      .then((r) => setIpos(r.data))
      .catch(() => setIpos([]))
      .finally(() => setLoading(false));
  }, [status]);

  return (
    <>
      <Navbar />
      <main className="relative bg-void min-h-screen">
        <section className="relative pt-36 pb-16 md:pt-44 md:pb-20 overflow-hidden" data-testid="ipos-hero">
          <div className="absolute inset-0 radial-glow" />
          <div className="absolute inset-0 bg-gradient-to-b from-void/0 to-void pointer-events-none" />
          <div className="container-x relative z-10">
            <motion.h1
              initial={{ opacity: 0, y: 24 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.9, ease: EASE }}
              className="font-display font-black tracking-tighter text-white text-5xl md:text-7xl leading-[0.95]"
            >
              IPO Tracker
            </motion.h1>
            <motion.p
              initial={{ opacity: 0, y: 24 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.9, ease: EASE, delay: 0.1 }}
              className="mt-6 text-base md:text-lg font-light text-slate-400 leading-relaxed max-w-2xl"
              data-testid="ipos-subtitle"
            >
              Current and upcoming mainboard IPOs, with an AI-generated short read on each company's Red Herring Prospectus.
            </motion.p>
          </div>
        </section>

        <section className="relative pb-28 md:pb-40">
          <div className="container-x">
            <div className="flex flex-wrap gap-2 mb-8" data-testid="ipo-status-filters">
              {STATUS_FILTERS.map((f) => (
                <button
                  key={f.key}
                  onClick={() => setStatus(f.key)}
                  className={`rounded-full border px-4 py-2 font-mono-ui text-[11px] uppercase tracking-[0.14em] transition-colors duration-300 ${
                    status === f.key ? "border-sapphire/40 bg-sapphire/10 text-sapphire-light" : "border-white/10 text-slate-500 hover:text-slate-300 hover:border-white/20"
                  }`}
                  data-testid={`ipo-filter-${f.key || "all"}`}
                >
                  {f.label}
                </button>
              ))}
            </div>

            {loading ? (
              <div className="flex items-center justify-center py-32 text-slate-500 font-mono-ui text-sm gap-3" data-testid="ipos-loading">
                <span className="h-2 w-2 rounded-full bg-sapphire-light animate-ping" /> Loading IPOs…
              </div>
            ) : ipos.length === 0 ? (
              <div className="glass rounded-2xl py-20 text-center text-slate-500" data-testid="ipos-empty">
                No IPOs match this filter right now.
              </div>
            ) : (
              <IpoTable rows={ipos} onOpen={(id) => navigate(`/ipos/${id}`)} />
            )}

            <p className="mt-8 text-xs font-light text-slate-500 leading-relaxed max-w-4xl" data-testid="ipos-disclaimer">
              Listing data is aggregated from public exchange sources and may lag or occasionally be incomplete. AI-generated reports are summaries of public RHP filings for research and educational purposes only — not investment advice.
            </p>

            <div className="mt-4">
              <a
                href="/#waitlist"
                onClick={(e) => { e.preventDefault(); navigate("/"); }}
                className="inline-flex items-center gap-2 text-sapphire-light hover:text-white transition-colors text-sm font-medium"
              >
                Back to home <ArrowUpRight size={15} />
              </a>
            </div>
          </div>
        </section>
      </main>
      <Footer />
    </>
  );
}
