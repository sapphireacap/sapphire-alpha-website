import { useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { useNavigate, useLocation } from "react-router-dom";
import {
  Check,
  ArrowUpRight,
  ArrowRight,
  Link2,
  Layers,
  KeyRound,
  Sparkles,
  Zap,
  ShieldCheck,
  Building2,
  ChevronDown,
} from "lucide-react";
import Navbar from "../components/site/Navbar";
import Footer from "../components/site/Footer";
import Reveal from "../components/site/Reveal";
import { scrollToId } from "../components/site/SmoothScroll";

const EASE = [0.16, 1, 0.3, 1];

const CYCLES = [
  { key: "monthly", label: "Monthly", months: 1 },
  { key: "quarterly", label: "Quarterly", months: 3 },
  { key: "yearly", label: "Yearly", months: 12 },
];

// Three-step onboarding flow shown above the pricing cards.
const STEPS = [
  {
    icon: Link2,
    title: "Connect Your Broker",
    body: "Securely connect your supported broker account to Sapphire Alpha Capital.",
  },
  {
    icon: Layers,
    title: "Choose Your Strategy",
    body: "Select one or more proprietary quantitative strategies from The Black Box.",
  },
  {
    icon: KeyRound,
    title: "Authenticate Once",
    body: "After authorization, your selected strategy executes trades automatically until you pause or stop it.",
  },
];

// Pricing totals unchanged from the original structure -- each cycle's
// figure is the amount actually billed for that cycle, not a monthly rate
// multiplied out. Bundle = Black Box + P&F Studio at a lower combined rate
// (79 + 49 = 128 vs 109 -> save $19/month).
const PLANS = [
  {
    key: "blackbox",
    name: "The Black Box",
    tagline: "Automated Strategy Execution Platform",
    description:
      "Deploy proprietary quantitative trading strategies directly in your own broker account through fully automated execution.",
    features: [
      "Secure broker integration",
      "One-time authentication",
      "Fully automated trade execution",
      "Multiple proprietary quantitative strategies",
      "Automated entries, stop-loss and target execution",
      "Pause or stop any strategy anytime",
      "Real-time execution notifications",
    ],
    note: "Your broker account always remains under your control.",
    prices: { monthly: 79, quarterly: 213, yearly: 708 },
  },
  {
    key: "pnf",
    name: "P&F Studio",
    tagline: "Professional Point & Figure Platform",
    description:
      "Institutional-grade Point & Figure charting with an advanced pattern and indicator library.",
    features: [
      "Unlimited Point & Figure charts",
      "Complete pattern library",
      "Multi-timeframe analysis",
      "Advanced charting tools",
      "Professional workspace",
    ],
    prices: { monthly: 49, quarterly: 129, yearly: 444 },
  },
  {
    key: "bundle",
    name: "Bundle",
    badge: "MOST POPULAR",
    highlight: true,
    description:
      "The complete Sapphire Alpha Capital platform combining research, automation and professional charting.",
    savingsLabel: "Save $19/month",
    features: [
      "Everything in The Black Box",
      "Everything in P&F Studio",
      "Priority support",
      "Access to future Black Box strategies",
      "Best overall value",
    ],
    prices: { monthly: 109, quarterly: 299, yearly: 999 },
  },
];

const WHY = [
  {
    icon: Sparkles,
    title: "Proprietary Strategies",
    body: "Research-driven quantitative strategies developed entirely in-house.",
  },
  {
    icon: Zap,
    title: "Fully Automated",
    body: "Authenticate once and your selected strategy continues executing automatically.",
  },
  {
    icon: ShieldCheck,
    title: "Your Broker. Your Control.",
    body: "Trades execute directly in your connected broker account. Pause, resume or disconnect whenever you choose.",
  },
  {
    icon: Building2,
    title: "Institutional Execution",
    body: "Rule-based execution removes emotional decision making and follows predefined strategy logic.",
  },
];

const FAQS = [
  {
    q: "How does The Black Box work?",
    a: "You connect your broker account, choose one or more proprietary quantitative strategies, and authenticate once. From there, your selected strategy runs automatically -- entries, stop-loss and target execution -- until you choose to pause or stop it.",
  },
  {
    q: "Which brokers are supported?",
    a: "Broker integrations are being rolled out progressively ahead of launch. Join the waitlist for early access and updates as new brokers go live.",
  },
  {
    q: "Can I stop a strategy anytime?",
    a: "Yes. You can pause or stop any strategy at any time -- your broker account and your capital remain fully under your control throughout.",
  },
  {
    q: "Can I run multiple strategies?",
    a: "Yes. The Black Box is built to run multiple proprietary strategies in parallel, each with its own independent entry, exit and risk logic.",
  },
  {
    q: "Do I need to keep my computer running?",
    a: "No. Execution runs on Sapphire Alpha Capital's infrastructure, not your device -- once a strategy is active, it continues running independently.",
  },
  {
    q: "How is this different from trading signals?",
    a: "The Black Box doesn't send signals, tips or calls for you to act on manually. It executes rule-based strategy logic directly and automatically, removing manual decision-making from the process entirely.",
  },
];

const DISCLAIMER = [
  "The Black Box is an automated strategy execution platform that allows users to deploy proprietary quantitative strategies through supported broker integrations.",
  "Users retain complete control over their broker accounts and may pause or stop execution at any time.",
  "Sapphire Alpha Capital does not provide personalized investment advice.",
];

const fmt = (n) => `$${n.toLocaleString("en-US", { maximumFractionDigits: 0 })}`;
const fmtCents = (n) => `$${n.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;

const billedLabel = (cycle, price) => {
  if (cycle.key === "monthly") return "billed monthly";
  if (cycle.key === "quarterly") return `${fmt(price)} billed every 3 months`;
  return `${fmt(price)} billed yearly`;
};

const HowItWorks = () => (
  <section className="relative pb-24 md:pb-32" data-testid="how-it-works-section">
    <div className="container-x">
      <Reveal className="text-center max-w-2xl mx-auto mb-14 md:mb-20">
        <p className="overline text-sapphire-light mb-4">Onboarding</p>
        <h2 className="font-display font-black tracking-tighter text-white text-3xl md:text-5xl leading-[1.05]">
          How The Black Box Works
        </h2>
        <p className="mt-4 text-base md:text-lg font-light text-slate-400 leading-relaxed">
          Automate your trading in three simple steps.
        </p>
      </Reveal>

      <div className="flex flex-col md:flex-row md:items-start gap-10 md:gap-6 max-w-5xl mx-auto">
        {STEPS.map((step, i) => {
          const Icon = step.icon;
          return (
            <div key={step.title} className="flex md:flex-1 md:flex-col items-start md:items-center gap-5 md:gap-0">
              <Reveal
                delay={i * 0.12}
                className="flex md:flex-col items-start md:items-center gap-5 md:gap-0 md:flex-1 w-full"
              >
                <div className="relative shrink-0 md:mb-6">
                  <span className="flex h-14 w-14 items-center justify-center rounded-2xl border border-white/10 bg-white/[0.02]">
                    <Icon size={22} className="text-sapphire-light" />
                  </span>
                  <span className="absolute -top-2 -right-2 flex h-5 w-5 items-center justify-center rounded-full bg-sapphire-light font-mono-ui text-[10px] font-semibold text-void">
                    {i + 1}
                  </span>
                </div>
                <div className="md:text-center">
                  <h3 className="font-display text-lg font-bold text-white tracking-tight">{step.title}</h3>
                  <p className="mt-2 text-sm text-slate-400 leading-relaxed md:max-w-[15rem] md:mx-auto">
                    {step.body}
                  </p>
                </div>
              </Reveal>

              {i < STEPS.length - 1 && (
                <>
                  {/* connector: vertical on mobile, horizontal on desktop */}
                  <div className="hidden md:flex items-center justify-center pt-7 self-stretch px-2" aria-hidden="true">
                    <motion.div
                      initial={{ scaleX: 0, opacity: 0 }}
                      whileInView={{ scaleX: 1, opacity: 1 }}
                      viewport={{ once: true, margin: "-80px" }}
                      transition={{ duration: 0.7, ease: EASE, delay: i * 0.12 + 0.2 }}
                      className="h-px w-full origin-left bg-gradient-to-r from-sapphire-light/60 to-white/10 relative"
                    >
                      <ArrowRight size={13} className="absolute -right-1 -top-[6px] text-sapphire-light" />
                    </motion.div>
                  </div>
                  <div className="md:hidden ml-7 h-8 w-px bg-gradient-to-b from-sapphire-light/60 to-white/10" aria-hidden="true" />
                </>
              )}
            </div>
          );
        })}
      </div>
    </div>
  </section>
);

const PricingCard = ({ plan, cycle, onCta }) => {
  const price = plan.prices[cycle.key];
  const perMonth = price / cycle.months;
  const baselineAtCycle = plan.prices.monthly * cycle.months;
  const savingsPct = cycle.months > 1 ? Math.round((1 - price / baselineAtCycle) * 100) : 0;

  return (
    <div
      className={`relative rounded-2xl border p-8 flex flex-col transition-shadow duration-300 ${
        plan.highlight
          ? "border-sapphire-light/50 bg-sapphire/[0.07] shadow-[0_0_0_1px_rgba(67,126,235,0.15),0_24px_60px_-24px_rgba(31,95,208,0.5)]"
          : "border-white/10 bg-white/[0.02]"
      }`}
      data-testid={`pricing-card-${plan.key}`}
    >
      {plan.badge && (
        <span className="absolute -top-3 left-1/2 -translate-x-1/2 rounded-full bg-sapphire-light px-3 py-1 font-mono-ui text-[10px] uppercase tracking-wider text-void font-semibold whitespace-nowrap">
          {plan.badge}
        </span>
      )}
      <h3 className="font-display text-xl font-bold text-white tracking-tight">{plan.name}</h3>
      {plan.tagline && (
        <p className="mt-1.5 font-mono-ui text-[11px] uppercase tracking-[0.1em] text-sapphire-light">{plan.tagline}</p>
      )}
      <p className="mt-3 text-sm text-slate-400 leading-relaxed min-h-[3.5rem]">{plan.description}</p>

      <div className="mt-6 flex items-end gap-1.5">
        <motion.span
          key={`${plan.key}-${cycle.key}`}
          initial={{ opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.3, ease: EASE }}
          className="font-display text-4xl font-black tracking-tighter text-white"
          data-testid={`pricing-permonth-${plan.key}`}
        >
          {fmtCents(perMonth)}
        </motion.span>
        <span className="text-sm text-slate-500 mb-1.5">/mo</span>
      </div>
      <p className="mt-1.5 font-mono-ui text-[11px] text-slate-500">
        {billedLabel(cycle, price)}
        {savingsPct > 0 && <span className="text-emerald-400 ml-2">save {savingsPct}%</span>}
      </p>
      {plan.savingsLabel && (
        <p className="mt-1 font-mono-ui text-[11px] text-emerald-400">{plan.savingsLabel}</p>
      )}

      <ul className="mt-6 space-y-3 flex-1">
        {plan.features.map((f) => (
          <li key={f} className="flex items-start gap-2.5 text-sm text-slate-300">
            <Check size={15} className="text-sapphire-light mt-0.5 shrink-0" />
            {f}
          </li>
        ))}
      </ul>

      <button
        onClick={onCta}
        className={`mt-8 w-full rounded-md py-2.5 text-sm font-medium transition-colors ${
          plan.highlight
            ? "btn-sapphire"
            : "border border-white/15 text-white hover:border-white/30 hover:bg-white/5"
        }`}
        data-testid={`pricing-cta-${plan.key}`}
      >
        Get Early Access
      </button>
      {plan.note && <p className="mt-3 text-center text-xs text-slate-500">{plan.note}</p>}
    </div>
  );
};

const WhyBlackBox = () => (
  <section className="relative py-24 md:py-32 border-t border-white/5" data-testid="why-blackbox-section">
    <div className="container-x">
      <Reveal className="text-center max-w-2xl mx-auto mb-14 md:mb-16">
        <h2 className="font-display font-black tracking-tighter text-white text-3xl md:text-5xl leading-[1.05]">
          Why The Black Box?
        </h2>
      </Reveal>

      <div className="flex flex-col md:grid md:grid-cols-2 lg:grid-cols-4 gap-4 md:gap-5 max-w-6xl mx-auto">
        {WHY.map((item, i) => {
          const Icon = item.icon;
          return (
            <Reveal
              key={item.title}
              delay={i * 0.08}
              className="card-hover rounded-2xl border border-white/10 bg-white/[0.02] p-6"
              data-testid={`why-blackbox-${i}`}
            >
              <span className="flex h-11 w-11 items-center justify-center rounded-xl border border-white/10 bg-white/[0.02]">
                <Icon size={19} className="text-sapphire-light" />
              </span>
              <h3 className="mt-5 font-display text-base font-bold text-white tracking-tight">{item.title}</h3>
              <p className="mt-2 text-sm text-slate-400 leading-relaxed">{item.body}</p>
            </Reveal>
          );
        })}
      </div>
    </div>
  </section>
);

const FaqItem = ({ item, isOpen, onClick, testId }) => (
  <div className="border-b border-white/10" data-testid={testId}>
    <button
      onClick={onClick}
      className="w-full flex items-center justify-between gap-4 py-6 text-left"
      aria-expanded={isOpen}
    >
      <span className="font-display text-base md:text-lg font-medium text-white">{item.q}</span>
      <motion.span
        animate={{ rotate: isOpen ? 180 : 0 }}
        transition={{ duration: 0.3, ease: EASE }}
        className="shrink-0 text-slate-500"
      >
        <ChevronDown size={18} />
      </motion.span>
    </button>
    <AnimatePresence initial={false}>
      {isOpen && (
        <motion.div
          initial={{ height: 0, opacity: 0 }}
          animate={{ height: "auto", opacity: 1 }}
          exit={{ height: 0, opacity: 0 }}
          transition={{ duration: 0.35, ease: EASE }}
          className="overflow-hidden"
        >
          <p className="pb-6 text-sm text-slate-400 leading-relaxed max-w-2xl">{item.a}</p>
        </motion.div>
      )}
    </AnimatePresence>
  </div>
);

const Faq = () => {
  const [openIdx, setOpenIdx] = useState(0);
  return (
    <section className="relative py-24 md:py-32 border-t border-white/5" data-testid="pricing-faq-section">
      <div className="container-x">
        <Reveal className="text-center max-w-2xl mx-auto mb-12 md:mb-16">
          <h2 className="font-display font-black tracking-tighter text-white text-3xl md:text-5xl leading-[1.05]">
            Frequently Asked Questions
          </h2>
        </Reveal>

        <Reveal className="max-w-3xl mx-auto">
          {FAQS.map((item, i) => (
            <FaqItem
              key={item.q}
              item={item}
              isOpen={openIdx === i}
              onClick={() => setOpenIdx(openIdx === i ? -1 : i)}
              testId={`faq-item-${i}`}
            />
          ))}
        </Reveal>
      </div>
    </section>
  );
};

export default function Pricing() {
  const [cycleKey, setCycleKey] = useState("monthly");
  const cycle = CYCLES.find((c) => c.key === cycleKey);
  const navigate = useNavigate();
  const location = useLocation();

  const goWaitlist = () => {
    if (location.pathname !== "/") {
      navigate("/");
      setTimeout(() => scrollToId("waitlist"), 550);
    } else {
      scrollToId("waitlist");
    }
  };

  return (
    <>
      <Navbar />
      <main className="relative bg-void min-h-screen">
        <section className="relative pt-36 pb-16 md:pt-44 md:pb-20 overflow-hidden" data-testid="pricing-hero">
          <div className="absolute inset-0 radial-glow" />
          <div className="absolute inset-0 bg-gradient-to-b from-void/0 to-void pointer-events-none" />
          <div className="container-x relative z-10">
            <motion.h1
              initial={{ opacity: 0, y: 24 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.9, ease: EASE }}
              className="font-display font-black tracking-tighter text-white text-5xl md:text-7xl leading-[0.95]"
            >
              Pricing
            </motion.h1>
            <motion.p
              initial={{ opacity: 0, y: 24 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.9, ease: EASE, delay: 0.1 }}
              className="mt-6 text-base md:text-lg font-light text-slate-400 leading-relaxed max-w-2xl"
              data-testid="pricing-subtitle"
            >
              Simple, transparent pricing for The Black Box and P&amp;F Studio. Cancel anytime.
            </motion.p>
          </div>
        </section>

        <HowItWorks />

        <section className="relative pb-28 md:pb-40">
          <div className="container-x">
            <div className="flex justify-center mb-12">
              <div className="inline-flex rounded-full border border-white/10 p-1" data-testid="pricing-cycle-toggle">
                {CYCLES.map((c) => (
                  <button
                    key={c.key}
                    onClick={() => setCycleKey(c.key)}
                    className={`rounded-full px-5 py-2 font-mono-ui text-[11px] uppercase tracking-[0.14em] transition-colors duration-300 ${
                      cycleKey === c.key ? "bg-sapphire-light text-void font-semibold" : "text-slate-400 hover:text-white"
                    }`}
                    data-testid={`pricing-cycle-${c.key}`}
                  >
                    {c.label}
                  </button>
                ))}
              </div>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-3 gap-6 max-w-5xl mx-auto">
              {PLANS.map((plan) => (
                <PricingCard key={plan.key} plan={plan} cycle={cycle} onCta={goWaitlist} />
              ))}
            </div>

            <div className="mt-6 flex justify-center">
              <button
                onClick={() => navigate("/")}
                className="inline-flex items-center gap-2 text-sapphire-light hover:text-white transition-colors text-sm font-medium"
              >
                Back to home <ArrowUpRight size={15} />
              </button>
            </div>
          </div>
        </section>

        <WhyBlackBox />
        <Faq />

        <section className="relative py-16 md:py-20 border-t border-white/5" data-testid="pricing-disclaimer-section">
          <div className="container-x">
            <Reveal className="max-w-3xl mx-auto rounded-2xl border border-white/10 bg-white/[0.02] p-6 md:p-8">
              <p className="font-mono-ui text-[10px] uppercase tracking-[0.16em] text-slate-500 mb-4">Disclosure</p>
              <div className="space-y-3" data-testid="pricing-disclaimer">
                {DISCLAIMER.map((line) => (
                  <p key={line} className="text-xs font-light text-slate-500 leading-relaxed">
                    {line}
                  </p>
                ))}
              </div>
            </Reveal>
          </div>
        </section>
      </main>
      <Footer />
    </>
  );
}
