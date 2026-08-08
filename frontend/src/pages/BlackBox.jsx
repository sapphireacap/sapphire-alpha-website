import { useEffect, useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { Plug, LayoutGrid, ShieldCheck, Zap, ChevronDown, ArrowRight, ShieldQuestion } from "lucide-react";
import Navbar from "../components/site/Navbar";
import Footer from "../components/site/Footer";
import ParticleField from "../components/site/ParticleField";
import { STRATEGIES, RISK_DISCLOSURE } from "./blackbox/strategies";

const EASE = [0.16, 1, 0.3, 1];
const SURFACE = "rounded-2xl border border-white/10 bg-[#0A0D18]";

const HOW_IT_WORKS = [
  { step: "01", title: "Connect Your Broker", body: "Securely connect your supported broker account.", Icon: Plug },
  { step: "02", title: "Choose A Strategy", body: "Browse available Black Box strategies and select the one you want to deploy.", Icon: LayoutGrid },
  { step: "03", title: "Authenticate Once", body: "Approve execution permissions one time.", Icon: ShieldCheck },
  { step: "04", title: "Trade Automatically", body: "The strategy executes trades automatically until you pause or stop it.", Icon: Zap },
];

const FAQ_ITEMS = [
  {
    q: "What is The Black Box?",
    a: "The Black Box is Sapphire Alpha Capital's private collection of systematic trading strategies. Each one is developed, validated and monitored internally before it's ever made available for deployment.",
  },
  {
    q: "How does automated execution work?",
    a: "Once you connect your broker and authenticate, your chosen strategy evaluates the market continuously and places trades automatically according to its predefined rules — no manual intervention required.",
  },
  {
    q: "Do trades happen in my own broker account?",
    a: "Yes. Sapphire Alpha Capital never holds your capital. Every trade is placed directly in your own connected broker account, under the permissions you grant.",
  },
  {
    q: "Can I stop a strategy anytime?",
    a: "Yes. You can pause or stop any deployed strategy at any time, and no further trades will be placed on your behalf.",
  },
];

/* ----------------------------- How It Works ----------------------------- */
const HowItWorks = () => (
  <section className="relative pb-20 md:pb-28" data-testid="black-box-how-it-works">
    <div className="container-x">
      <motion.h2
        initial={{ opacity: 0, y: 16 }}
        whileInView={{ opacity: 1, y: 0 }}
        viewport={{ once: true, margin: "-80px" }}
        transition={{ duration: 0.7, ease: EASE }}
        className="font-display text-3xl md:text-4xl font-normal text-white tracking-tight mb-12 text-center"
      >
        How It Works
      </motion.h2>
      <div className="grid grid-cols-1 md:grid-cols-4 gap-6 md:gap-4 relative">
        {HOW_IT_WORKS.map((s, i) => (
          <motion.div
            key={s.step}
            initial={{ opacity: 0, y: 20 }}
            whileInView={{ opacity: 1, y: 0 }}
            viewport={{ once: true, margin: "-60px" }}
            transition={{ duration: 0.6, ease: EASE, delay: i * 0.1 }}
            className="relative flex flex-col items-center text-center"
          >
            {i < HOW_IT_WORKS.length - 1 && (
              <span className="hidden md:flex absolute top-8 left-[calc(50%+2.5rem)] right-[calc(-50%+2.5rem)] items-center justify-center text-slate-700">
                <ArrowRight size={16} />
              </span>
            )}
            <motion.span
              className="relative inline-flex h-16 w-16 items-center justify-center rounded-2xl border border-white/10 bg-white/[0.03] text-sapphire-light mb-5"
              whileInView={{ scale: [0.9, 1.05, 1] }}
              viewport={{ once: true }}
              transition={{ duration: 0.6, ease: EASE, delay: i * 0.1 + 0.15 }}
            >
              <s.Icon size={26} />
            </motion.span>
            <span className="font-mono-ui text-[11px] text-sapphire-light mb-2">STEP {s.step}</span>
            <h3 className="text-lg font-bold text-white tracking-tight mb-2">{s.title}</h3>
            <p className="text-sm font-light text-slate-500 leading-relaxed max-w-[220px]">{s.body}</p>
          </motion.div>
        ))}
      </div>
    </div>
  </section>
);

/* ----------------------------- Strategy counts ----------------------------- */
// Counts-only summary, computed from the real strategy registry -- no
// per-strategy cards, no internal architecture exposed. See
// blackbox/strategies.js for the underlying `status` field on each entry.
const STATUS_LABELS = ["Available", "In Validation", "Coming Soon"];

const strategyCounts = () => {
  const counts = Object.fromEntries(STATUS_LABELS.map((s) => [s, 0]));
  STRATEGIES.forEach((s) => { counts[s.status] = (counts[s.status] || 0) + 1; });
  return counts;
};

const StrategyCounts = () => {
  const counts = strategyCounts();
  return (
    <section className="relative pb-20 md:pb-28" data-testid="black-box-strategy-counts">
      <div className="container-x">
        <div className={`${SURFACE} max-w-3xl mx-auto p-8 md:p-10 text-center`}>
          <h2 className="text-2xl md:text-3xl font-bold text-white tracking-tight mb-3">
            Available Strategies
          </h2>
          <p className="text-sm md:text-base font-light text-slate-400 leading-relaxed mb-8 max-w-lg mx-auto">
            Research strategies become available only after internal validation.
          </p>
          <div className="flex flex-wrap items-center justify-center gap-8 md:gap-12">
            {STATUS_LABELS.map((label) => (
              <div key={label}>
                <p className="font-display text-3xl md:text-4xl font-normal text-white tracking-tight">{counts[label]}</p>
                <p className="font-mono-ui text-[10px] uppercase tracking-[0.14em] text-slate-500 mt-1">{label}</p>
              </div>
            ))}
          </div>
        </div>
      </div>
    </section>
  );
};

/* --------------------------- Validation notice --------------------------- */
const ValidationNotice = () => (
  <section className="relative pb-20 md:pb-28" data-testid="black-box-validation-notice">
    <div className="container-x">
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        whileInView={{ opacity: 1, y: 0 }}
        viewport={{ once: true, margin: "-80px" }}
        transition={{ duration: 0.7, ease: EASE }}
        className={`${SURFACE} max-w-3xl mx-auto p-8 md:p-10 text-center border-l-2 border-l-sapphire`}
      >
        <ShieldQuestion size={28} className="text-sapphire-light mx-auto mb-5" />
        <h2 className="text-2xl md:text-3xl font-bold text-white tracking-tight mb-4">
          Why aren't all strategies available?
        </h2>
        <p className="text-sm md:text-base font-light text-slate-400 leading-relaxed mb-3">
          Every Black Box strategy goes through a strict research and validation process before public release.
        </p>
        <p className="text-sm md:text-base font-light text-slate-400 leading-relaxed">
          Only strategies that satisfy our internal quality standards become available for deployment. This allows us to maintain consistency, robustness and execution reliability.
        </p>
      </motion.div>
    </div>
  </section>
);

/* --------------------------------- FAQ --------------------------------- */
const FaqItem = ({ item, open, onToggle }) => (
  <div className={`${SURFACE} overflow-hidden`}>
    <button
      type="button"
      onClick={onToggle}
      className="w-full flex items-center justify-between gap-4 px-6 py-5 text-left"
      data-testid={`faq-toggle-${item.q.slice(0, 12)}`}
    >
      <span className="text-base md:text-lg font-bold text-white">{item.q}</span>
      <ChevronDown size={18} className={`text-slate-400 shrink-0 transition-transform duration-300 ${open ? "rotate-180" : ""}`} />
    </button>
    <AnimatePresence initial={false}>
      {open && (
        <motion.div
          initial={{ height: 0, opacity: 0 }}
          animate={{ height: "auto", opacity: 1 }}
          exit={{ height: 0, opacity: 0 }}
          transition={{ duration: 0.25, ease: EASE }}
          className="overflow-hidden"
        >
          <p className="px-6 pb-5 text-sm font-light text-slate-400 leading-relaxed">{item.a}</p>
        </motion.div>
      )}
    </AnimatePresence>
  </div>
);

const Faq = () => {
  const [openIdx, setOpenIdx] = useState(0);
  return (
    <section className="relative pb-28 md:pb-40" data-testid="black-box-faq">
      <div className="container-x">
        <motion.h2
          initial={{ opacity: 0, y: 16 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true, margin: "-80px" }}
          transition={{ duration: 0.7, ease: EASE }}
          className="font-display text-3xl md:text-4xl font-normal text-white tracking-tight mb-10 text-center"
        >
          Frequently Asked Questions
        </motion.h2>
        <div className="max-w-2xl mx-auto space-y-3">
          {FAQ_ITEMS.map((item, i) => (
            <FaqItem key={item.q} item={item} open={openIdx === i} onToggle={() => setOpenIdx(openIdx === i ? -1 : i)} />
          ))}
        </div>
      </div>
    </section>
  );
};

/* --------------------------------- Page --------------------------------- */
export default function BlackBox() {
  useEffect(() => { window.scrollTo(0, 0); }, []);

  return (
    <>
      <Navbar />
      <main className="relative bg-void min-h-screen">
        <section className="relative pt-28 pb-16 md:pt-36 md:pb-20 overflow-hidden" data-testid="black-box-hero">
          <ParticleField density={0.00006} />
          <div className="absolute inset-0 radial-glow" />
          <div className="absolute inset-0 bg-gradient-to-b from-void/0 to-void pointer-events-none" />
          <div className="container-x relative z-10">
            <motion.h1
              initial={{ opacity: 0, y: 24 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.9, ease: EASE }}
              className="font-display font-normal tracking-[-0.015em] text-white text-5xl md:text-7xl leading-[0.95]"
            >
              The Black Box
            </motion.h1>
            <motion.p
              initial={{ opacity: 0, y: 24 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.9, ease: EASE, delay: 0.1 }}
              className="mt-6 text-lg md:text-xl font-medium text-slate-200 leading-relaxed max-w-3xl"
              data-testid="black-box-subtitle"
            >
              Trading strategies, deployed directly in your own broker account.
            </motion.p>
            <motion.div
              initial={{ opacity: 0, y: 24 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.9, ease: EASE, delay: 0.15 }}
              className="mt-6 max-w-2xl space-y-4"
            >
              <p className="text-base font-light text-slate-400 leading-relaxed">
                Choose a strategy, connect your broker, authenticate once — trades execute automatically from there, under your control throughout.
              </p>
            </motion.div>
          </div>
        </section>

        <HowItWorks />
        <StrategyCounts />
        <ValidationNotice />
        <Faq />

        <section className="relative pb-20 md:pb-28">
          <div className="container-x">
            <p className="text-xs font-light text-slate-500 leading-relaxed max-w-2xl mx-auto text-center">{RISK_DISCLOSURE}</p>
          </div>
        </section>
      </main>
      <Footer />
    </>
  );
}
