import { Link, useParams, useNavigate } from "react-router-dom";
import { motion } from "framer-motion";
import { ArrowLeft, ArrowUpRight, Lock } from "lucide-react";
import Navbar from "../../components/site/Navbar";
import Footer from "../../components/site/Footer";
import { getStrategy, RISK_DISCLOSURE } from "./strategies";

// Public strategy page — deliberately numbers-free. No trades, no P&L, no
// equity curve, no capital, no allocation, no status beyond "Coming Soon".
// The full internal report (real performance) lives only in the admin
// dashboard now (AdminStrategyReport.jsx, rendered inside Admin.jsx's
// BlackBoxPanel, behind admin auth) — see [[black_box_redesign]] memory for
// why this split exists before adding any data back here.
// OptionsStrategyDetail.jsx (the real live-data view for Convexity Window/
// Gamma Backspread) is intentionally no longer routed to from here as of
// 2026-08-04 -- every strategy now shows the same Coming Soon page,
// nothing deleted, just stopped, same pattern as the paused features
// elsewhere in this codebase.

const EASE = [0.16, 1, 0.3, 1];
const SURFACE = "rounded-2xl border border-white/10 bg-[#0A0D18]";

const SummaryRow = ({ label, value }) => (
  <div className="py-4 border-b border-white/[0.06] last:border-0 grid grid-cols-1 sm:grid-cols-[160px_1fr] gap-1 sm:gap-6">
    <p className="font-mono-ui text-[10px] uppercase tracking-[0.16em] text-slate-500">{label}</p>
    <p className="text-sm text-slate-300 leading-relaxed">{value}</p>
  </div>
);

export default function StrategyDetail() {
  const { slug } = useParams();
  const navigate = useNavigate();
  const strategy = getStrategy(slug);

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
        <section className="relative pt-28 pb-14 md:pt-32 md:pb-20">
          <div className="container-x max-w-3xl">
            <Link to="/black-box" className="inline-flex items-center gap-2 text-sm text-slate-400 hover:text-white transition-colors mb-10" data-testid="back-to-black-box">
              <ArrowLeft size={15} /> Back to Black Box
            </Link>

            <motion.div initial={{ opacity: 0, y: 16 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.7, ease: EASE }}>
              <p className="font-mono-ui text-xs text-sapphire-light mb-2">Strategy #{strategy.no}</p>
              <h1 className="font-display font-black tracking-tighter text-white text-4xl md:text-5xl leading-[0.95]">{strategy.title}</h1>
              <p className="mt-4 text-base font-light text-slate-400">{strategy.subtitle}</p>

              <div className="flex items-center gap-2 mt-6">
                <Lock size={12} className="text-slate-500" />
                <span className="font-mono-ui text-xs uppercase tracking-wider text-slate-400">Coming Soon</span>
              </div>

              <div className="flex flex-wrap gap-2 mt-5">
                {strategy.assetClass && (
                  <span className="rounded-full border border-white/10 px-3 py-1 font-mono-ui text-[10px] uppercase tracking-wider text-slate-400">
                    {strategy.assetClass}
                  </span>
                )}
                {strategy.tags.map((t) => (
                  <span key={t} className="rounded-full border border-white/10 px-3 py-1 font-mono-ui text-[10px] uppercase tracking-wider text-slate-400">
                    {t}
                  </span>
                ))}
              </div>
            </motion.div>

            <motion.div
              initial={{ opacity: 0, y: 16 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.7, ease: EASE, delay: 0.1 }}
              className={`${SURFACE} p-6 md:p-8 mt-10`}
            >
              <p className="text-lg font-light text-white leading-relaxed mb-6">{strategy.summary.what}</p>
              <div>
                <SummaryRow label="Market" value={strategy.summary.market} />
                <SummaryRow label="Objective" value={strategy.summary.objective} />
                <SummaryRow label="Risk Profile" value={strategy.summary.riskProfile} />
                <SummaryRow label="Holding Period" value={strategy.summary.holdingPeriod} />
              </div>
            </motion.div>

            <motion.div
              initial={{ opacity: 0, y: 16 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.7, ease: EASE, delay: 0.2 }}
              className={`${SURFACE} p-6 md:p-8 mt-6 border-l-2 border-l-sapphire`}
            >
              <p className="font-mono-ui text-[10px] uppercase tracking-[0.16em] text-slate-500 mb-3">Methodology</p>
              <p className="text-base font-light text-slate-300 leading-relaxed italic">"{strategy.methodology}"</p>
            </motion.div>

            <motion.div
              initial={{ opacity: 0, y: 16 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.7, ease: EASE, delay: 0.3 }}
              className="mt-10 flex flex-col sm:flex-row sm:items-center gap-4"
            >
              <button
                type="button"
                disabled
                title="Coming soon"
                className="inline-flex items-center justify-center gap-2 rounded-full bg-[#1F5FD0]/40 px-6 py-2.5 text-sm font-semibold text-white/70 cursor-not-allowed whitespace-nowrap"
                data-testid="request-access-btn"
              >
                Request Research Access — Coming Soon
              </button>
              <p className="text-xs text-slate-500">Research access will open after internal validation.</p>
            </motion.div>

            <p className="mt-14 text-xs font-light text-slate-500 leading-relaxed max-w-2xl border-t border-white/[0.06] pt-8">{RISK_DISCLOSURE}</p>

            <div className="mt-10">
              <Link to="/black-box" className="inline-flex items-center gap-2 text-sapphire-light hover:text-white transition-colors text-sm font-medium" data-testid="back-to-black-box-footer">
                View other strategies <ArrowUpRight size={15} />
              </Link>
            </div>
          </div>
        </section>
      </main>
      <Footer />
    </>
  );
}
