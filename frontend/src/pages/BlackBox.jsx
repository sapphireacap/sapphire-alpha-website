import { useEffect } from "react";
import { motion } from "framer-motion";
import { Clock } from "lucide-react";
import Navbar from "../components/site/Navbar";
import Footer from "../components/site/Footer";
import ParticleField from "../components/site/ParticleField";

const EASE = [0.16, 1, 0.3, 1];

const STRATEGIES = [
  { no: "01", title: "Strategy 01" },
  { no: "02", title: "Strategy 02" },
  { no: "03", title: "Strategy 03" },
  { no: "04", title: "Strategy 04" },
];

const StrategyCard = ({ strategy }) => (
  <div
    className="relative glass rounded-2xl border border-dashed border-white/10 opacity-40 px-6 py-14 flex flex-col items-center justify-center text-center"
    data-testid={`black-box-strategy-${strategy.no}`}
  >
    <Clock size={16} className="absolute top-4 right-4 text-slate-600" />
    <span className="font-mono-ui text-xs text-sapphire-light mb-3">{strategy.no}</span>
    <h4 className="font-display text-2xl font-bold text-slate-300">{strategy.title}</h4>
    <p className="mt-3 text-sm font-light text-slate-500 max-w-xs">Coming Soon</p>
  </div>
);

export default function BlackBox() {
  useEffect(() => { window.scrollTo(0, 0); }, []);

  return (
    <>
      <Navbar />
      <main className="relative bg-void min-h-screen">
        <section className="relative pt-28 pb-10 md:pt-32 md:pb-14 overflow-hidden" data-testid="black-box-hero">
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
              Systematic strategies, built and tested in-house.
            </motion.p>
          </div>
        </section>

        <section className="relative pb-20 md:pb-28">
          <div className="container-x">
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4" data-testid="black-box-strategies">
              {STRATEGIES.map((s) => <StrategyCard key={s.no} strategy={s} />)}
            </div>
          </div>
        </section>
      </main>
      <Footer />
    </>
  );
}
