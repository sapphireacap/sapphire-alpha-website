import { useState } from "react";
import { motion } from "framer-motion";
import { useNavigate, useLocation } from "react-router-dom";
import { Check, ArrowUpRight } from "lucide-react";
import Navbar from "../components/site/Navbar";
import Footer from "../components/site/Footer";
import { scrollToId } from "../components/site/SmoothScroll";

const EASE = [0.16, 1, 0.3, 1];

const CYCLES = [
  { key: "monthly", label: "Monthly", months: 1 },
  { key: "quarterly", label: "Quarterly", months: 3 },
  { key: "yearly", label: "Yearly", months: 12 },
];

// Illustrative pricing, structured like a typical market-data / charting
// tool subscription (TradingView, TrendSpider, and similar) -- a flat
// monthly rate with a discount for longer commitments. Prices are USD;
// each plan's quarterly/yearly total is the number actually billed for
// that cycle, not a monthly rate multiplied out.
const PLANS = [
  {
    key: "blackbox",
    name: "The Black Box",
    tagline: "Real-time P&F options signal system across every strategy module.",
    features: [
      "All Black Box strategy modules",
      "Live trade confirmation signals",
      "Entry, stop-loss & take-profit levels",
      "Platform alerts",
    ],
    prices: { monthly: 79, quarterly: 213, yearly: 708 },
  },
  {
    key: "pnf",
    name: "P&F Studio",
    tagline: "Full point & figure charting with the complete pattern and indicator library.",
    features: [
      "Unlimited P&F charting",
      "Full pattern & indicator library",
      "Multi-timeframe structure engine",
      "45° trend lines & moving averages",
    ],
    prices: { monthly: 49, quarterly: 129, yearly: 444 },
  },
  {
    key: "bundle",
    name: "Bundle",
    tagline: "The Black Box and P&F Studio together, at a lower combined rate.",
    highlight: true,
    features: [
      "Everything in The Black Box",
      "Everything in P&F Studio",
      "Priority support",
      "Best overall value",
    ],
    prices: { monthly: 109, quarterly: 299, yearly: 999 },
  },
];

const fmt = (n) => `$${n.toLocaleString("en-US", { maximumFractionDigits: 0 })}`;
const fmtCents = (n) => `$${n.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;

const billedLabel = (cycle, price) => {
  if (cycle.key === "monthly") return "billed monthly";
  if (cycle.key === "quarterly") return `${fmt(price)} billed every 3 months`;
  return `${fmt(price)} billed yearly`;
};

const PricingCard = ({ plan, cycle, onCta }) => {
  const price = plan.prices[cycle.key];
  const perMonth = price / cycle.months;
  const baselineAtCycle = plan.prices.monthly * cycle.months;
  const savingsPct = cycle.months > 1 ? Math.round((1 - price / baselineAtCycle) * 100) : 0;

  return (
    <div
      className={`relative rounded-2xl border p-8 flex flex-col ${
        plan.highlight ? "border-sapphire/40 bg-sapphire/[0.06]" : "border-white/10 bg-white/[0.02]"
      }`}
      data-testid={`pricing-card-${plan.key}`}
    >
      {plan.highlight && (
        <span className="absolute -top-3 left-1/2 -translate-x-1/2 rounded-full bg-sapphire-light px-3 py-1 font-mono-ui text-[10px] uppercase tracking-wider text-void font-semibold">
          Best Value
        </span>
      )}
      <h3 className="font-display text-xl font-bold text-white tracking-tight">{plan.name}</h3>
      <p className="mt-2 text-sm text-slate-400 leading-relaxed min-h-[2.5rem]">{plan.tagline}</p>

      <div className="mt-6 flex items-end gap-1.5">
        <span className="font-display text-4xl font-black tracking-tighter text-white" data-testid={`pricing-permonth-${plan.key}`}>
          {fmtCents(perMonth)}
        </span>
        <span className="text-sm text-slate-500 mb-1.5">/mo</span>
      </div>
      <p className="mt-1.5 font-mono-ui text-[11px] text-slate-500">
        {billedLabel(cycle, price)}
        {savingsPct > 0 && <span className="text-emerald-400 ml-2">save {savingsPct}%</span>}
      </p>

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
        Get Notified
      </button>
    </div>
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

            <p className="mt-10 text-xs font-light text-slate-500 leading-relaxed max-w-4xl mx-auto text-center" data-testid="pricing-disclaimer">
              Prices are in USD. The Black Box and P&amp;F Studio are research and trade-confirmation tools, not
              investment advice. Sapphire Alpha Capital is not a registered investment adviser.
            </p>

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
      </main>
      <Footer />
    </>
  );
}
