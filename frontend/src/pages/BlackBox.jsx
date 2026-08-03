import { useEffect, useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import {
  CheckCircle2, Plug, LayoutGrid, ShieldCheck, Zap, X, ChevronDown, ArrowRight, ShieldQuestion,
} from "lucide-react";
import Navbar from "../components/site/Navbar";
import Footer from "../components/site/Footer";
import ParticleField from "../components/site/ParticleField";
import { STRATEGIES, RISK_DISCLOSURE } from "./blackbox/strategies";

const EASE = [0.16, 1, 0.3, 1];
const SURFACE = "rounded-2xl border border-white/10 bg-[#0A0D18]";

const FEATURE_CHIPS = [
  "Proprietary Quantitative Models",
  "Fully Automated Execution",
  "Your Broker. Your Control.",
  "Research Driven",
];

const HOW_IT_WORKS = [
  { step: "01", title: "Connect Your Broker", body: "Securely connect your supported broker account.", Icon: Plug },
  { step: "02", title: "Choose A Strategy", body: "Browse available Black Box strategies and select the one you want to deploy.", Icon: LayoutGrid },
  { step: "03", title: "Authenticate Once", body: "Approve execution permissions one time.", Icon: ShieldCheck },
  { step: "04", title: "Trade Automatically", body: "The strategy executes trades automatically until you pause or stop it.", Icon: Zap },
];

const FAQ_ITEMS = [
  {
    q: "What is The Black Box?",
    a: "The Black Box is Sapphire Alpha Capital's private collection of research-driven systematic trading strategies. Each one is developed, validated and monitored internally before it's ever made available for deployment.",
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
  {
    q: "Are these trading signals?",
    a: "No. Unlike a signal service, you never have to manually place a trade yourself. Once deployed, the strategy executes automatically within its own rules.",
  },
  {
    q: "How are strategies validated?",
    a: "Every strategy goes through internal research, forward performance testing and risk review before it satisfies our standards for public release — see \"Why aren't all strategies available?\" above for the full process.",
  },
];

const STATUS_STYLE = {
  Available: "border-emerald-400/30 bg-emerald-400/10 text-emerald-300",
  "In Validation": "border-amber-400/30 bg-amber-400/10 text-amber-300",
  "Coming Soon": "border-white/15 bg-white/5 text-slate-400",
};

const STATUS_DESCRIPTION = {
  Available: (s) => `${s.title} is live and available for deployment.`,
  "In Validation": (s) => `${s.title} is a systematic options strategy currently undergoing forward validation and execution testing.`,
  "Coming Soon": (s) => `${s.title} is a systematic options strategy currently in early research and development.`,
};

/* --------------------------------- Hero --------------------------------- */
const FeatureChip = ({ label, index }) => (
  <motion.span
    initial={{ opacity: 0, y: 12 }}
    animate={{ opacity: 1, y: 0 }}
    transition={{ duration: 0.6, ease: EASE, delay: 0.3 + index * 0.08 }}
    className="inline-flex items-center gap-2 rounded-full border border-white/10 bg-white/[0.03] px-4 py-2 font-mono-ui text-[11px] uppercase tracking-wider text-slate-300"
  >
    <CheckCircle2 size={13} className="text-sapphire-light shrink-0" />
    {label}
  </motion.span>
);

/* ----------------------------- How It Works ----------------------------- */
const HowItWorks = () => (
  <section className="relative pb-20 md:pb-28" data-testid="black-box-how-it-works">
    <div className="container-x">
      <motion.h2
        initial={{ opacity: 0, y: 16 }}
        whileInView={{ opacity: 1, y: 0 }}
        viewport={{ once: true, margin: "-80px" }}
        transition={{ duration: 0.7, ease: EASE }}
        className="font-display text-3xl md:text-4xl font-bold text-white tracking-tight mb-12 text-center"
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
            <h3 className="font-display text-lg font-bold text-white tracking-tight mb-2">{s.title}</h3>
            <p className="text-sm font-light text-slate-500 leading-relaxed max-w-[220px]">{s.body}</p>
          </motion.div>
        ))}
      </div>
    </div>
  </section>
);

/* ------------------------------ Strategy card ------------------------------ */
const InfoRow = ({ label, value }) => (
  <div className="flex items-center justify-between gap-3">
    <span className="font-mono-ui text-[10px] uppercase tracking-wider text-slate-500 whitespace-nowrap">{label}</span>
    <span className="text-xs text-slate-300 text-right">{value}</span>
  </div>
);

const StrategyCard = ({ strategy, index, onView, className = "" }) => (
  <motion.div
    initial={{ opacity: 0, y: 24 }}
    whileInView={{ opacity: 1, y: 0 }}
    viewport={{ once: true, margin: "-60px" }}
    transition={{ duration: 0.7, ease: EASE, delay: (index % 3) * 0.1 }}
    className={`${SURFACE} p-6 md:p-7 flex flex-col h-full transition-all duration-500 hover:border-sapphire/30 hover:shadow-[0_0_44px_rgba(31,95,208,0.12)] ${className}`}
    data-testid={`black-box-strategy-${strategy.slug}`}
  >
    <div className="flex items-center justify-between mb-5">
      <span className="font-mono-ui text-xs text-sapphire-light">#{strategy.no}</span>
      <span className={`rounded-full border px-3 py-1 font-mono-ui text-[10px] uppercase tracking-wider whitespace-nowrap ${STATUS_STYLE[strategy.status] || STATUS_STYLE["Coming Soon"]}`}>
        {strategy.status}
      </span>
    </div>

    <h3 className="font-display text-2xl font-bold text-white tracking-tight mb-2">{strategy.title}</h3>
    <p className="text-sm font-light text-slate-400 leading-relaxed mb-6">{strategy.objective}</p>

    <div className="space-y-2.5 mb-6 pb-6 border-b border-white/[0.06]">
      <InfoRow label="Market" value={strategy.marketLabel} />
      <InfoRow label="Trading Style" value={strategy.tradingStyle} />
      <InfoRow label="Automation" value={strategy.automation} />
      <InfoRow label="Est. Release" value={strategy.estimatedRelease} />
    </div>

    <button
      type="button"
      onClick={() => onView(strategy)}
      className="mt-auto w-full inline-flex items-center justify-center gap-2 rounded-full border border-white/15 py-2.5 text-sm font-medium text-white hover:border-sapphire-light/50 hover:bg-sapphire/10 transition-colors duration-300"
      data-testid={`view-strategy-${strategy.slug}`}
    >
      View Strategy <ArrowRight size={14} />
    </button>
  </motion.div>
);

/* ------------------------------ Strategy modal ------------------------------ */
const ModalInfoRow = ({ label, value }) => (
  <div className="py-3 border-b border-white/[0.06] last:border-0 grid grid-cols-[140px_1fr] gap-4 items-center">
    <span className="font-mono-ui text-[10px] uppercase tracking-[0.14em] text-slate-500">{label}</span>
    <span className="text-sm text-slate-200">{value}</span>
  </div>
);

const StrategyModal = ({ strategy, onClose }) => {
  const describe = STATUS_DESCRIPTION[strategy.status] || STATUS_DESCRIPTION["Coming Soon"];
  const secondLine = strategy.status === "Coming Soon"
    ? "This strategy will become available once it satisfies our internal research and validation requirements."
    : "This strategy will become available once it satisfies our internal performance, robustness and risk requirements.";
  const expectedAvailability = strategy.status === "Coming Soon" ? "Coming Soon" : strategy.estimatedRelease;

  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      transition={{ duration: 0.25, ease: EASE }}
      className="fixed inset-0 z-50 flex items-center justify-center bg-void/85 backdrop-blur-sm px-4 md:px-6 py-10 overflow-y-auto"
      onClick={onClose}
      data-testid="strategy-modal-overlay"
    >
      <motion.div
        initial={{ opacity: 0, y: 16, scale: 0.98 }}
        animate={{ opacity: 1, y: 0, scale: 1 }}
        exit={{ opacity: 0, y: 10, scale: 0.98 }}
        transition={{ duration: 0.3, ease: EASE }}
        onClick={(e) => e.stopPropagation()}
        className={`${SURFACE} relative w-full max-w-lg my-auto p-7 md:p-8`}
        data-testid={`strategy-modal-${strategy.slug}`}
      >
        <button
          type="button"
          onClick={onClose}
          className="absolute top-5 right-5 text-slate-500 hover:text-white transition-colors"
          data-testid="strategy-modal-close"
        >
          <X size={18} />
        </button>

        <p className="font-mono-ui text-xs text-sapphire-light mb-2">Strategy #{strategy.no}</p>
        <h2 className="font-display text-2xl md:text-3xl font-bold text-white tracking-tight mb-4">{strategy.title}</h2>

        <div className="flex items-center gap-2 mb-6">
          <span className={`inline-flex items-center gap-1.5 rounded-full border px-3 py-1 font-mono-ui text-[10px] uppercase tracking-wider ${STATUS_STYLE[strategy.status] || STATUS_STYLE["Coming Soon"]}`}>
            Currently {strategy.status}
          </span>
        </div>

        <p className="text-sm font-light text-slate-300 leading-relaxed mb-3">{describe(strategy)}</p>
        <p className="text-sm font-light text-slate-500 leading-relaxed mb-7">{secondLine}</p>

        <p className="font-mono-ui text-[10px] uppercase tracking-[0.16em] text-slate-500 mb-2">Strategy Information</p>
        <div className="mb-7">
          <ModalInfoRow label="Market" value={strategy.marketLabel} />
          <ModalInfoRow label="Trading Style" value={strategy.tradingStyle} />
          <ModalInfoRow label="Execution" value={strategy.automation} />
          <ModalInfoRow label="Risk Management" value={strategy.riskManagement} />
          <ModalInfoRow label="Broker Integration" value={strategy.brokerIntegration} />
        </div>

        <div className={`${SURFACE} bg-white/[0.02] px-5 py-4 mb-7 flex items-center justify-between`}>
          <span className="font-mono-ui text-[10px] uppercase tracking-[0.16em] text-slate-500">Expected Availability</span>
          <span className="font-mono-ui text-sm text-white">{expectedAvailability}</span>
        </div>

        <div className="flex flex-col sm:flex-row gap-3">
          <button
            type="button"
            disabled
            title="Coming soon"
            className="flex-1 inline-flex items-center justify-center rounded-full bg-[#1F5FD0]/40 px-6 py-2.5 text-sm font-semibold text-white/70 cursor-not-allowed whitespace-nowrap"
            data-testid="strategy-modal-notify"
          >
            Notify Me When Released
          </button>
          <button
            type="button"
            onClick={onClose}
            className="flex-1 inline-flex items-center justify-center rounded-full border border-white/15 px-6 py-2.5 text-sm font-medium text-slate-300 hover:text-white hover:border-white/30 transition-colors"
            data-testid="strategy-modal-back"
          >
            Back
          </button>
        </div>
      </motion.div>
    </motion.div>
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
        <h2 className="font-display text-2xl md:text-3xl font-bold text-white tracking-tight mb-4">
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
      <span className="font-display text-base md:text-lg font-bold text-white">{item.q}</span>
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
          className="font-display text-3xl md:text-4xl font-bold text-white tracking-tight mb-10 text-center"
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
  const [viewingStrategy, setViewingStrategy] = useState(null);
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
              className="font-display font-black tracking-tighter text-white text-5xl md:text-7xl leading-[0.95]"
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
              Deploy proprietary quantitative trading strategies directly in your own broker account through fully automated execution.
            </motion.p>
            <motion.div
              initial={{ opacity: 0, y: 24 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.9, ease: EASE, delay: 0.15 }}
              className="mt-6 max-w-2xl space-y-4"
            >
              <p className="text-base font-light text-slate-400 leading-relaxed">
                The Black Box is Sapphire Alpha Capital's private collection of research-driven systematic trading strategies.
              </p>
              <p className="text-base font-light text-slate-400 leading-relaxed">
                Choose a strategy, connect your broker, authenticate once and let the platform execute trades automatically according to predefined rules.
              </p>
              <p className="text-base font-light text-slate-400 leading-relaxed">
                Every strategy is developed, validated and monitored internally before release.
              </p>
            </motion.div>
            <div className="flex flex-wrap gap-3 mt-8" data-testid="black-box-feature-chips">
              {FEATURE_CHIPS.map((label, i) => <FeatureChip key={label} label={label} index={i} />)}
            </div>
          </div>
        </section>

        <HowItWorks />

        <section className="relative pb-8 md:pb-10">
          <div className="container-x">
            <motion.h2
              initial={{ opacity: 0, y: 16 }}
              whileInView={{ opacity: 1, y: 0 }}
              viewport={{ once: true, margin: "-80px" }}
              transition={{ duration: 0.7, ease: EASE }}
              className="font-display text-3xl md:text-4xl font-bold text-white tracking-tight mb-3 text-center"
            >
              Strategy Library
            </motion.h2>
            <motion.p
              initial={{ opacity: 0, y: 16 }}
              whileInView={{ opacity: 1, y: 0 }}
              viewport={{ once: true, margin: "-80px" }}
              transition={{ duration: 0.7, ease: EASE, delay: 0.05 }}
              className="text-sm md:text-base font-light text-slate-500 leading-relaxed max-w-xl mx-auto text-center"
            >
              Each strategy is designed for a different market condition and follows its own quantitative framework. Click any strategy to learn how it works.
            </motion.p>
          </div>
        </section>

        <section className="relative pb-20 md:pb-28">
          <div className="container-x">
            {/* flex-wrap + justify-center (not a plain grid) so a partial
                last row centers itself instead of sitting flush-left with
                empty trailing columns -- each card's width is set to match
                what a 3-column grid cell would be at each breakpoint, so
                full rows look identical to a real grid either way. */}
            <div className="flex flex-wrap justify-center gap-6" data-testid="black-box-strategies">
              {STRATEGIES.map((s, i) => (
                <StrategyCard
                  key={s.slug}
                  strategy={s}
                  index={i}
                  onView={setViewingStrategy}
                  className="w-full md:w-[calc(50%-0.75rem)] lg:w-[calc(33.333%-1rem)]"
                />
              ))}
            </div>
          </div>
        </section>

        <ValidationNotice />
        <Faq />

        <section className="relative pb-20 md:pb-28">
          <div className="container-x">
            <p className="text-xs font-light text-slate-500 leading-relaxed max-w-2xl mx-auto text-center">{RISK_DISCLOSURE}</p>
          </div>
        </section>
      </main>
      <Footer />
      <AnimatePresence>
        {viewingStrategy && <StrategyModal strategy={viewingStrategy} onClose={() => setViewingStrategy(null)} />}
      </AnimatePresence>
    </>
  );
}
