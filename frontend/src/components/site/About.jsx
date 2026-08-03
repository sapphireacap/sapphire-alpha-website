import { LineChart, Layers, Cpu } from "lucide-react";
import Reveal from "./Reveal";

const PILLARS = [
  {
    no: "01",
    tag: "Research",
    title: "Investment Research",
    icon: LineChart,
    body: "Studying markets through data, evidence, and disciplined analysis to understand how prices move over time.",
  },
  {
    no: "02",
    tag: "Markets",
    title: "Market Research",
    icon: Layers,
    body: "Exploring trends, sectors, macro developments, and market behaviour to uncover meaningful insights.",
  },
  {
    no: "03",
    tag: "Systems",
    title: "Systematic Investing",
    icon: Cpu,
    body: "Building rule-based investment frameworks that prioritize consistency, discipline, and repeatability.",
  },
];

export const About = () => {
  return (
    <section id="about" className="relative py-24 md:py-40" data-testid="about-section">
      <div className="container-x">
        <div className="flex flex-col md:grid md:grid-cols-12 gap-8 md:gap-16 items-end mb-16 md:mb-24">
          <Reveal className="md:col-span-7">
            <p className="overline mb-6">About · What We Build</p>
            <h2 className="font-display font-black tracking-tighter text-white text-4xl md:text-6xl leading-[1.02]">
              Precision at the intersection of data and markets.
            </h2>
          </Reveal>
          <Reveal delay={0.15} className="md:col-span-5">
            <p className="text-base md:text-lg font-light text-slate-400 leading-relaxed">
              Sapphire Alpha Capital is a research-first platform focused on
              systematic investing, financial markets, and quantitative analysis —
              grounded in evidence rather than prediction.
            </p>
          </Reveal>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-3 gap-5 md:gap-6">
          {PILLARS.map((p, i) => {
            const Icon = p.icon;
            return (
              <Reveal
                key={p.no}
                delay={i * 0.12}
                className="card-hover group relative rounded-2xl border border-white/10 bg-white/[0.02] p-8 md:p-10"
                data-testid={`pillar-card-${p.no}`}
              >
                <div className="flex items-center justify-between mb-14 md:mb-16">
                  <span className="font-mono-ui text-xs tracking-[0.2em] text-slate-500 uppercase">
                    {p.no} / {p.tag}
                  </span>
                  <span className="flex h-11 w-11 items-center justify-center rounded-xl bg-gradient-to-br from-sapphire-light/20 to-sapphire/5 border border-sapphire-light/20 group-hover:from-sapphire-light/30 group-hover:to-sapphire/10 transition-colors duration-300">
                    <Icon className="text-sapphire-light" size={20} />
                  </span>
                </div>
                <h3 className="font-display text-2xl md:text-3xl font-bold text-white mb-4">{p.title}</h3>
                <p className="text-sm md:text-base font-light text-slate-400 leading-relaxed">{p.body}</p>
              </Reveal>
            );
          })}
        </div>
      </div>
    </section>
  );
};

export default About;
