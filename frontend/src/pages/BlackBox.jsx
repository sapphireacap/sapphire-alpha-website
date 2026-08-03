import { useEffect } from "react";
import { motion } from "framer-motion";
import { Link } from "react-router-dom";
import { Lock, ArrowUpRight } from "lucide-react";
import Navbar from "../components/site/Navbar";
import Footer from "../components/site/Footer";
import ParticleField from "../components/site/ParticleField";
import { STRATEGIES } from "./blackbox/strategies";

const EASE = [0.16, 1, 0.3, 1];

// Every card is deliberately minimal and identical in shape: name, one-line
// description, optional asset class, a neutral "Coming Soon" status, and a
// link into the (also numbers-free) info page. No live data is fetched for
// this page at all — nothing here should ever hint at real performance,
// capital, or allocation. See [[black_box_redesign]] memory for the fuller
// "why" and what moved to the admin-only dashboard instead.
const StrategyCard = ({ strategy, index, className = "" }) => (
  <motion.div
    initial={{ opacity: 0, y: 24 }}
    animate={{ opacity: 1, y: 0 }}
    transition={{ duration: 0.7, ease: EASE, delay: index * 0.12 }}
    className={className}
  >
    <Link
      to={`/black-box/${strategy.slug}`}
      className="group relative block h-full rounded-2xl border border-white/10 bg-[#0A0D18] p-8 md:p-9 overflow-hidden transition-all duration-500 hover:-translate-y-1 hover:border-sapphire/40 hover:shadow-[0_0_44px_rgba(31,95,208,0.18)] cursor-pointer"
      data-testid={`black-box-strategy-${strategy.slug}`}
    >
      <span className="font-mono-ui text-xs text-sapphire-light block mb-6">#{strategy.no}</span>
      <h3 className="font-display text-2xl md:text-3xl font-bold text-white tracking-tight">{strategy.title}</h3>
      <p className="mt-3 text-sm font-light text-slate-500 leading-relaxed">{strategy.subtitle}</p>

      <div className="flex flex-wrap items-center gap-2 mt-8">
        {strategy.assetClass && (
          <span className="rounded-full border border-white/10 px-3 py-1 font-mono-ui text-[10px] uppercase tracking-wider text-slate-500">
            {strategy.assetClass}
          </span>
        )}
        <span className="inline-flex items-center gap-1.5 rounded-full border border-white/10 px-3 py-1 font-mono-ui text-[10px] uppercase tracking-wider text-slate-400">
          <Lock size={10} /> Coming Soon
        </span>
      </div>

      {/* Hover overlay */}
      <div className="absolute inset-0 flex flex-col items-center justify-center text-center px-8 bg-void/92 backdrop-blur-sm opacity-0 group-hover:opacity-100 transition-opacity duration-500 pointer-events-none">
        <p className="font-display text-2xl font-bold text-white mb-3">Coming Soon</p>
        <p className="text-sm font-light text-slate-400 max-w-xs leading-relaxed">
          Research access will open after internal validation.
        </p>
        <span className="mt-6 inline-flex items-center gap-1.5 text-xs font-medium text-sapphire-light">
          Research <ArrowUpRight size={13} />
        </span>
      </div>
    </Link>
  </motion.div>
);

// Real-status card for the two publicly-tracked options strategies —
// LiveStrategyCard (real status pill + link into OptionsStrategyDetail.jsx)
// removed 2026-08-04 -- Convexity Window and Gamma Backspread now use the
// same StrategyCard as every other strategy below, nothing opens, every
// card is a uniform "Coming Soon". Nothing deleted on the backend/detail
// side, just stopped, same pattern as the paused features elsewhere in
// this codebase.

export default function BlackBox() {
  useEffect(() => { window.scrollTo(0, 0); }, []);
  const [convexity, backspread, alphaI, alphaII, lumen] = STRATEGIES;

  return (
    <>
      <Navbar />
      <main className="relative bg-void min-h-screen">
        <section className="relative pt-28 pb-14 md:pt-36 md:pb-20 overflow-hidden" data-testid="black-box-hero">
          <ParticleField density={0.00006} />
          <div className="absolute inset-0 radial-glow" />
          <div className="absolute inset-0 bg-gradient-to-b from-void/0 to-void pointer-events-none" />
          <div className="container-x relative z-10">
            <motion.h1
              initial={{ opacity: 0, y: 24 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.9, ease: EASE }}
              className="font-display font-black tracking-tighter text-white text-5xl md:text-7xl leading-[0.95]"
            >
              The Black Box
            </motion.h1>
            <motion.p
              initial={{ opacity: 0, y: 24 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.9, ease: EASE, delay: 0.1 }}
              className="mt-6 text-base md:text-lg font-light text-slate-400 leading-relaxed max-w-2xl"
              data-testid="black-box-subtitle"
            >
              A private quantitative research lab. Strategies developed and validated in-house, released only when ready.
            </motion.p>
          </div>
        </section>

        <section className="relative pb-16 md:pb-24">
          <div className="container-x">
            <div className="grid grid-cols-1 md:grid-cols-2 gap-6 md:gap-8 max-w-4xl mx-auto" data-testid="black-box-options-strategies">
              <StrategyCard strategy={convexity} index={0} />
              <StrategyCard strategy={backspread} index={1} />
            </div>
          </div>
        </section>

        {/* Paused 2026-07-29 (backend evaluation/backtest/admin panel all
            disabled, see server.py's DISABLED_FEATURES) -- still shown here
            exactly as before (nothing deleted), so nothing changes visually
            beyond the section ordering above promoting the two live
            strategies first. */}
        <section className="relative pb-28 md:pb-40">
          <div className="container-x">
            <p className="font-mono-ui text-xs uppercase tracking-[0.2em] text-slate-500 mb-6 max-w-4xl mx-auto">In Validation</p>
            <div className="flex flex-col items-center gap-6 md:gap-8 max-w-4xl mx-auto" data-testid="black-box-strategies">
              <div className="grid grid-cols-1 md:grid-cols-2 gap-6 md:gap-8 w-full">
                <StrategyCard strategy={alphaI} index={0} />
                <StrategyCard strategy={alphaII} index={1} />
              </div>
              <StrategyCard strategy={lumen} index={2} className="w-full md:w-[calc(50%-1rem)]" />
            </div>
          </div>
        </section>
      </main>
      <Footer />
    </>
  );
}
