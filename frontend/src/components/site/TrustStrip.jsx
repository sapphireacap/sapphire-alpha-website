import { Database, Zap, Cpu, ShieldAlert, Lock } from "lucide-react";
import Reveal from "./Reveal";

// New section, own short labels (not the reference screenshot's wording) --
// a compact trust-signal band between Hero and the rest of the page.
const SIGNALS = [
  { icon: Database, label: "Data-Driven", sub: "Every signal backed by research" },
  { icon: Zap, label: "Real-Time Data", sub: "Live prices, always current" },
  { icon: Cpu, label: "Systematic Edge", sub: "Rules-based, not discretionary" },
  { icon: ShieldAlert, label: "Risk-First", sub: "Structure before conviction" },
  { icon: Lock, label: "Private by Design", sub: "Built with care for your data" },
];

export const TrustStrip = () => (
  <section className="relative py-14 md:py-16 border-y border-white/5" data-testid="trust-strip-section">
    <div className="container-x">
      <Reveal className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-5 gap-8 md:gap-6">
        {SIGNALS.map((s) => {
          const Icon = s.icon;
          return (
            <div key={s.label} className="flex flex-col items-center text-center gap-3" data-testid={`trust-signal-${s.label.toLowerCase().replace(/\s+/g, "-")}`}>
              <span className="flex h-11 w-11 items-center justify-center rounded-xl border border-white/10 bg-white/[0.02]">
                <Icon size={19} className="text-sapphire-light" />
              </span>
              <div>
                <p className="text-sm font-medium text-white">{s.label}</p>
                <p className="text-xs text-slate-500 mt-1 leading-snug">{s.sub}</p>
              </div>
            </div>
          );
        })}
      </Reveal>
    </div>
  </section>
);

export default TrustStrip;
