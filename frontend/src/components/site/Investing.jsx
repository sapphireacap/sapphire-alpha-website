import { Search, FlaskConical, RefreshCw } from "lucide-react";
import Reveal from "./Reveal";

const STEPS = [
  { no: "01", icon: Search, title: "Research", body: "Develop investment ideas through structured research and market analysis." },
  { no: "02", icon: FlaskConical, title: "Evaluate", body: "Test assumptions using data, historical evidence, and systematic reasoning." },
  { no: "03", icon: RefreshCw, title: "Improve", body: "Continuously refine ideas through observation, learning, and iteration." },
];

// Illustrates the three steps above as a command sequence, in the same
// terminal chrome used elsewhere on the site -- deliberately NOT a live or
// randomized readout (no fabricated signal strength, confidence, or Sharpe
// figures). What actually runs through this pipeline is proprietary and
// isn't shown; the sequence itself is real.
const Terminal = () => (
  <div
    className="font-mono-ui text-xs md:text-sm rounded-xl border border-white/10 bg-black/60 overflow-hidden"
    style={{ boxShadow: "0 20px 50px -20px rgba(0,0,0,0.6), 0 0 60px -20px rgba(31,95,208,0.25)" }}
    data-testid="terminal-readout"
  >
    <div className="flex items-center gap-2 px-4 py-3 border-b border-white/10">
      <span className="h-2.5 w-2.5 rounded-full bg-red-500/70" />
      <span className="h-2.5 w-2.5 rounded-full bg-yellow-500/70" />
      <span className="h-2.5 w-2.5 rounded-full bg-emerald-500/70" />
      <span className="ml-3 text-slate-500">sac_engine</span>
    </div>
    <div className="p-5 space-y-2 leading-relaxed">
      <p className="text-slate-300">$ research --idea=core-thesis</p>
      <p className="text-slate-600 pl-4">→ structured analysis, not a hunch</p>
      <p className="text-slate-300">$ evaluate --against=historical-data</p>
      <p className="text-slate-600 pl-4">→ assumptions tested, not assumed</p>
      <p className="text-slate-300">$ improve --on=observed-results</p>
      <p className="text-slate-600 pl-4">→ iteration, not a one-time build</p>
    </div>
  </div>
);

export const Investing = () => {
  return (
    <section id="investing" className="relative py-24 md:py-40" data-testid="investing-section">
      <div className="container-x">
        <div className="flex flex-col lg:grid lg:grid-cols-12 gap-12 md:gap-16 items-start">
          <div className="lg:col-span-7">
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

          <Reveal delay={0.2} className="lg:col-span-5 lg:sticky lg:top-28">
            <Terminal />
          </Reveal>
        </div>
      </div>
    </section>
  );
};

export default Investing;
