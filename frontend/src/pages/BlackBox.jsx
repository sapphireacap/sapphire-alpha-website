import { useEffect, useState } from "react";
import axios from "axios";
import { motion } from "framer-motion";
import { Link } from "react-router-dom";
import { ArrowUpRight, Lock } from "lucide-react";
import Navbar from "../components/site/Navbar";
import Footer from "../components/site/Footer";
import ParticleField from "../components/site/ParticleField";
import { STRATEGIES } from "./blackbox/strategies";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;
const EASE = [0.16, 1, 0.3, 1];

// Lightweight, preview-only status per card — no trades, no backtest, no
// full performance history. That's deliberate: the directory is a strategy
// index, not a place to read complete results (StrategyDetail.jsx is).
const useCardState = (strategy) => {
  const [state, setState] = useState(null);
  useEffect(() => {
    let cancelled = false;
    const path = strategy.kind === "lumen" ? "lumen-sip/status" : `${strategy.apiPath}/status`;
    axios.get(`${API}/blackbox/${path}`).then((r) => { if (!cancelled) setState(r.data); }).catch(() => {});
    return () => { cancelled = true; };
  }, [strategy]);
  return state;
};

const CurrentStateLine = ({ strategy }) => {
  const state = useCardState(strategy);
  if (strategy.status !== "Operational") return null;

  if (strategy.kind === "lumen") {
    const buying = state?.instruments
      ? Object.entries(state.instruments).filter(([, v]) => v.phase === "buy").map(([k]) => k.toUpperCase())
      : [];
    return (
      <div>
        <p className="font-mono-ui text-[10px] uppercase tracking-[0.18em] text-slate-500 mb-1">Current Allocation</p>
        <p className="text-sm text-white">{buying.length ? buying.join(" · ") : state ? "All Cash" : "—"}</p>
      </div>
    );
  }

  return (
    <div>
      <p className="font-mono-ui text-[10px] uppercase tracking-[0.18em] text-slate-500 mb-1">Current State</p>
      <p className="text-sm text-emerald-300 font-medium tracking-wide">LIVE</p>
    </div>
  );
};

const StatusDot = ({ status }) => (
  <span className="inline-flex items-center gap-2">
    <span className="relative flex h-2 w-2">
      {status === "Operational" && (
        <span className="absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-60 animate-ping" />
      )}
      <span className={`relative inline-flex h-2 w-2 rounded-full ${status === "Operational" ? "bg-emerald-400" : "bg-slate-500"}`} />
    </span>
    <span className={`font-mono-ui text-xs uppercase tracking-wider ${status === "Operational" ? "text-emerald-300" : "text-slate-400"}`}>
      {status}
    </span>
  </span>
);

const StrategyCard = ({ strategy, index }) => (
  <motion.div
    initial={{ opacity: 0, y: 20 }}
    animate={{ opacity: 1, y: 0 }}
    transition={{ duration: 0.6, ease: EASE, delay: index * 0.08 }}
  >
    <Link
      to={`/black-box/${strategy.slug}`}
      className="group block rounded-2xl border border-white/10 bg-[#0A0D18] p-6 md:p-7 transition-all duration-300 hover:-translate-y-1 hover:border-sapphire/40 hover:shadow-[0_0_36px_rgba(31,95,208,0.14)]"
      data-testid={`black-box-strategy-${strategy.slug}`}
    >
      <div className="flex items-start justify-between gap-4 mb-6">
        <div>
          <span className="font-mono-ui text-xs text-sapphire-light block mb-1.5">#{strategy.no}</span>
          <h3 className="font-display text-2xl font-bold text-white tracking-tight">{strategy.title}</h3>
          <p className="text-sm font-light text-slate-500 mt-1">{strategy.subtitle}</p>
        </div>
        <ArrowUpRight size={18} className="text-slate-600 group-hover:text-sapphire-light transition-colors shrink-0 mt-1" />
      </div>

      <div className="mb-6">
        <p className="font-mono-ui text-[10px] uppercase tracking-[0.18em] text-slate-500 mb-1.5">Status</p>
        <StatusDot status={strategy.status} />
      </div>

      {strategy.status === "Operational" ? (
        <div className="grid grid-cols-2 gap-x-4 gap-y-5 pt-5 border-t border-white/[0.06]">
          {strategy.facts.map((f) => (
            <div key={f.label}>
              <p className="font-mono-ui text-[10px] uppercase tracking-[0.18em] text-slate-500 mb-1">{f.label}</p>
              <p className="text-sm text-white">{f.value}</p>
            </div>
          ))}
          <CurrentStateLine strategy={strategy} />
        </div>
      ) : (
        <p className="text-xs font-light text-slate-500 pt-5 border-t border-white/[0.06] leading-relaxed">
          This track is being calibrated internally and isn't open for research review yet.
        </p>
      )}

      <p className="mt-6 inline-flex items-center gap-1.5 text-xs font-medium text-sapphire-light group-hover:text-white transition-colors">
        View Research <ArrowUpRight size={13} />
      </p>
    </Link>
  </motion.div>
);

const ReservedSlotCard = ({ no }) => (
  <div
    className="relative rounded-2xl border border-dashed border-white/10 opacity-40 px-6 py-14 flex flex-col items-center justify-center text-center"
    data-testid={`black-box-reserved-${no}`}
  >
    <Lock size={16} className="absolute top-4 right-4 text-slate-600" />
    <span className="font-mono-ui text-xs text-slate-500 mb-3">#{no}</span>
    <h4 className="font-display text-xl font-bold text-slate-400">Reserved</h4>
    <p className="mt-3 text-sm font-light text-slate-600 max-w-xs">Next strategy in development.</p>
  </div>
);

export default function BlackBox() {
  useEffect(() => { window.scrollTo(0, 0); }, []);

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
              Systematic strategies developed, tested and monitored in-house.
            </motion.p>
          </div>
        </section>

        <section className="relative pb-24 md:pb-32">
          <div className="container-x">
            <div className="grid grid-cols-1 md:grid-cols-2 gap-5" data-testid="black-box-strategies">
              {STRATEGIES.map((s, i) => <StrategyCard key={s.slug} strategy={s} index={i} />)}
              <ReservedSlotCard no="04" />
            </div>
          </div>
        </section>
      </main>
      <Footer />
    </>
  );
}
