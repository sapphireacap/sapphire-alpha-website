import { useEffect } from "react";
import { useParams, Link } from "react-router-dom";
import Navbar from "../components/site/Navbar";
import Footer from "../components/site/Footer";
import ParticleField from "../components/site/ParticleField";
import { getStrategy } from "./blackbox/strategies";
import OptionsStrategyDetail from "./blackbox/OptionsStrategyDetail";
import EquityStrategyDetail from "./blackbox/EquityStrategyDetail";

const SURFACE = "rounded-2xl border border-white/10 bg-[#0A0D18]";

// Per-strategy detail route. Full rules/backtest/metrics are only ever
// returned by the backend to the one account blackbox_access.py allows
// (everyone else gets a `locked` shape back from the same endpoints,
// rendered as "Coming Soon" by OptionsStrategyDetail/EquityStrategyDetail
// themselves) -- this page just picks which detail component fits the
// strategy's `kind` and otherwise falls back to the same "Coming Soon"
// treatment the public directory (BlackBox.jsx) already shows for
// strategies that don't have a real-data detail page (prism/lumen).
const ComingSoon = () => (
  <div className={`${SURFACE} p-10 text-center`}>
    <p className="text-lg font-bold text-white mb-2">Coming Soon</p>
    <p className="text-sm text-slate-500 max-w-sm mx-auto">This strategy's rules and performance data aren't public yet.</p>
  </div>
);

export default function BlackBoxStrategyDetail() {
  const { slug } = useParams();
  const strategy = getStrategy(slug);
  useEffect(() => { window.scrollTo(0, 0); }, [slug]);

  return (
    <>
      <Navbar />
      <main className="relative bg-void min-h-screen">
        <section className="relative pt-28 pb-12 md:pt-36 md:pb-16 overflow-hidden">
          <ParticleField density={0.00006} />
          <div className="absolute inset-0 radial-glow" />
          <div className="absolute inset-0 bg-gradient-to-b from-void/0 to-void pointer-events-none" />
          <div className="container-x relative z-10">
            <Link to="/black-box" className="font-mono-ui text-[11px] uppercase tracking-wider text-slate-500 hover:text-slate-300 transition-colors">
              ← Black Box
            </Link>
            <h1 className="mt-4 font-display font-normal tracking-[-0.015em] text-white text-4xl md:text-5xl leading-[0.95]">
              {strategy?.title || "Strategy"}
            </h1>
            {strategy?.subtitle && <p className="mt-3 text-base text-slate-400">{strategy.subtitle}</p>}
          </div>
        </section>
        <section className="relative pb-20 md:pb-28">
          <div className="container-x">
            {!strategy || !["options-live", "equity-live"].includes(strategy.kind) ? (
              <ComingSoon />
            ) : strategy.kind === "options-live" ? (
              <OptionsStrategyDetail strategy={strategy} />
            ) : (
              <EquityStrategyDetail strategy={strategy} />
            )}
          </div>
        </section>
      </main>
      <Footer />
    </>
  );
}
