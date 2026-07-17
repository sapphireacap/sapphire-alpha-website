import { useEffect, useState } from "react";
import { Search, FlaskConical, RefreshCw } from "lucide-react";
import Reveal from "./Reveal";

const STEPS = [
  { no: "01", icon: Search, title: "Research", body: "Develop investment ideas through structured research and market analysis." },
  { no: "02", icon: FlaskConical, title: "Evaluate", body: "Test assumptions using data, historical evidence, and systematic reasoning." },
  { no: "03", icon: RefreshCw, title: "Improve", body: "Continuously refine ideas through observation, learning, and iteration." },
];

const Terminal = () => {
  const [signal, setSignal] = useState(0.847);
  useEffect(() => {
    const t = setInterval(() => {
      setSignal((0.6 + Math.random() * 0.39));
    }, 2200);
    return () => clearInterval(t);
  }, []);
  return (
    <div className="font-mono-ui text-xs md:text-sm rounded-xl border border-white/10 bg-black/60 overflow-hidden" data-testid="terminal-readout">
      <div className="flex items-center gap-2 px-4 py-3 border-b border-white/10">
        <span className="h-2.5 w-2.5 rounded-full bg-red-500/70" />
        <span className="h-2.5 w-2.5 rounded-full bg-yellow-500/70" />
        <span className="h-2.5 w-2.5 rounded-full bg-emerald-500/70" />
        <span className="ml-3 text-slate-500">sac_engine · live</span>
      </div>
      <div className="p-5 space-y-2 leading-relaxed">
        <p className="text-slate-500">$ evaluate --strategy=core</p>
        <p className="text-slate-300">SIGNAL_STRENGTH: <span className="text-emerald-400">{signal.toFixed(3)}</span></p>
        <p className="text-slate-300">REGIME: <span className="text-sapphire-light">RISK_ON</span></p>
        <p className="text-slate-300">CONFIDENCE: <span className="text-emerald-400">HIGH</span></p>
        <p className="text-slate-300">SHARPE_EST: <span className="text-emerald-400">1.62</span></p>
        <p className="text-slate-500">→ iterating<span className="animate-pulse">_</span></p>
      </div>
    </div>
  );
};

export const Investing = () => {
  return (
    <section id="investing" className="relative py-24 md:py-40" data-testid="investing-section">
      <div className="container-x">
        <div className="grid grid-cols-12 gap-12 md:gap-16 items-start">
          <div className="col-span-12 lg:col-span-7">
            <Reveal>
              <p className="overline mb-6">Systematic Investing · Process</p>
              <h2 className="font-display font-black tracking-tighter text-white text-4xl md:text-6xl leading-[1.02] mb-14">
                A disciplined framework.
              </h2>
            </Reveal>

            <div className="relative border-l border-white/10 ml-4">
              {STEPS.map((s, i) => {
                const Icon = s.icon;
                return (
                  <Reveal key={s.no} delay={i * 0.12} className="relative pl-10 pb-12 last:pb-0" data-testid={`step-${s.no}`}>
                    <span className="absolute -left-[9px] top-1 h-4 w-4 rounded-full bg-sapphire ring-4 ring-void" />
                    <div className="flex items-center gap-3 mb-3">
                      <Icon size={18} className="text-sapphire-light" />
                      <span className="font-mono-ui text-xs text-slate-500 tracking-[0.2em]">STEP {s.no}</span>
                    </div>
                    <h3 className="font-display text-2xl md:text-3xl font-bold text-white mb-2">{s.title}</h3>
                    <p className="text-sm md:text-base font-light text-slate-400 leading-relaxed max-w-md">{s.body}</p>
                  </Reveal>
                );
              })}
            </div>
          </div>

          <Reveal delay={0.2} className="col-span-12 lg:col-span-5 lg:sticky lg:top-28">
            <Terminal />
            <p className="mt-4 font-mono-ui text-[11px] text-slate-600 leading-relaxed">
              * Illustrative readout. Figures are representative of methodology, not live performance.
            </p>
          </Reveal>
        </div>
      </div>
    </section>
  );
};

export default Investing;
