import { useEffect, useState } from "react";
import axios from "axios";
import { useParams, useNavigate } from "react-router-dom";
import { ArrowLeft, ExternalLink, Loader2, FileText } from "lucide-react";
import Navbar from "../components/site/Navbar";
import Footer from "../components/site/Footer";
import { IpoStatusBadge } from "./Ipos";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const fmtDate = (iso) => {
  if (!iso) return "—";
  const [y, m, d] = iso.split("-");
  return `${d} ${MONTHS[Number(m) - 1]} ${y}`;
};
const fmtPrice = (band) => {
  if (!band || (band.min == null && band.max == null)) return "—";
  if (band.min === band.max || band.max == null) return `₹${band.min}`;
  return `₹${band.min} – ₹${band.max}`;
};

const FactCard = ({ label, value }) => (
  <div className="glass rounded-2xl p-5">
    <p className="font-mono-ui text-[10px] uppercase tracking-[0.18em] text-slate-500 mb-2">{label}</p>
    <p className="font-display text-lg font-bold text-white tracking-tight">{value ?? "—"}</p>
  </div>
);

const ReportSection = ({ ipo }) => {
  if (ipo.report_error) {
    return (
      <div className="glass rounded-2xl border border-white/10 p-8 text-center" data-testid="ipo-report-error">
        <p className="font-mono-ui text-[10px] uppercase tracking-[0.24em] text-slate-500 mb-3">Report Unavailable</p>
        <p className="text-sm text-slate-400 leading-relaxed max-w-md mx-auto">{ipo.report_error}</p>
      </div>
    );
  }
  if (!ipo.short_report) {
    return (
      <div className="glass rounded-2xl border border-white/10 p-8 text-center" data-testid="ipo-report-pending">
        <p className="font-mono-ui text-[10px] uppercase tracking-[0.24em] text-slate-500 mb-3">Report Generating</p>
        <p className="text-sm text-slate-400 leading-relaxed max-w-md mx-auto">
          {ipo.rhp_url
            ? "The AI-generated report for this IPO is being prepared from its RHP filing. Check back shortly — refreshing this page will pick it up once it's ready."
            : "No RHP filing has been linked for this IPO yet, so a report hasn't been generated."}
        </p>
      </div>
    );
  }
  return (
    <div className="glass rounded-2xl p-6 md:p-8" data-testid="ipo-report">
      <div className="flex items-center gap-3 mb-5">
        <FileText size={16} className="text-sapphire-light" />
        <span className="font-mono-ui text-[10px] uppercase tracking-[0.22em] text-slate-500">AI-Generated RHP Summary</span>
      </div>
      <div className="space-y-4">
        {ipo.short_report.split(/\n\s*\n/).map((para, i) => (
          <p key={i} className="text-sm text-slate-300 leading-relaxed whitespace-pre-wrap">{para.trim()}</p>
        ))}
      </div>
      <p className="text-[11px] font-light text-slate-600 mt-6 pt-4 border-t border-white/10">
        AI-generated summary of the public RHP filing, for research and educational purposes only — not investment advice. Always verify against the original RHP linked above.
      </p>
    </div>
  );
};

export default function IpoDetail() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [ipo, setIpo] = useState(null);
  const [loading, setLoading] = useState(true);
  const [notFound, setNotFound] = useState(false);

  useEffect(() => {
    window.scrollTo(0, 0);
    setLoading(true);
    setNotFound(false);
    axios.get(`${API}/ipos/${id}`)
      .then((r) => setIpo(r.data))
      .catch(() => setNotFound(true))
      .finally(() => setLoading(false));
  }, [id]);

  return (
    <>
      <Navbar />
      <main className="relative bg-void min-h-screen">
        <section className="relative pt-36 pb-16 md:pt-44 md:pb-20 overflow-hidden">
          <div className="absolute inset-0 radial-glow" />
          <div className="absolute inset-0 bg-gradient-to-b from-void/0 to-void pointer-events-none" />
          <div className="container-x relative z-10">
            <button
              onClick={() => navigate("/ipos")}
              className="inline-flex items-center gap-2 text-slate-500 hover:text-white transition-colors text-sm mb-8"
              data-testid="ipo-detail-back"
            >
              <ArrowLeft size={14} /> Back to IPO Tracker
            </button>

            {loading ? (
              <div className="flex items-center justify-center py-24 text-slate-500 gap-3" data-testid="ipo-detail-loading">
                <Loader2 className="animate-spin" size={18} /> Loading…
              </div>
            ) : notFound || !ipo ? (
              <div className="glass rounded-2xl py-20 text-center text-slate-500" data-testid="ipo-detail-not-found">
                IPO not found.
              </div>
            ) : (
              <>
                <div className="flex flex-wrap items-center gap-4 mb-4">
                  <h1 className="font-display font-black tracking-tighter text-white text-4xl md:text-6xl leading-[0.95]" data-testid="ipo-detail-name">
                    {ipo.company_name}
                  </h1>
                  <IpoStatusBadge status={ipo.status} testid="ipo-detail-status" />
                </div>
                {ipo.sector && <p className="text-base text-slate-400 mb-8">{ipo.sector}</p>}

                <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
                  <FactCard label="Exchange" value={(ipo.exchange || []).join(", ") || "—"} />
                  <FactCard label="Price Band" value={fmtPrice(ipo.price_band)} />
                  <FactCard label="Lot Size" value={ipo.lot_size} />
                  <FactCard label="Issue Size" value={ipo.issue_size} />
                  <FactCard label="Issue Opens" value={fmtDate(ipo.issue_open_date)} />
                  <FactCard label="Issue Closes" value={fmtDate(ipo.issue_close_date)} />
                  <FactCard label="Listing Date" value={fmtDate(ipo.listing_date)} />
                  <FactCard
                    label="RHP Filing"
                    value={ipo.rhp_url ? (
                      <a href={ipo.rhp_url} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1.5 text-sapphire-light hover:text-white transition-colors text-base">
                        View PDF <ExternalLink size={14} />
                      </a>
                    ) : "—"}
                  />
                </div>

                <ReportSection ipo={ipo} />
              </>
            )}
          </div>
        </section>
      </main>
      <Footer />
    </>
  );
}
