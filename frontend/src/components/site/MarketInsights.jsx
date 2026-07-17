import { TrendingUp, Globe, Sigma, BookOpen } from "lucide-react";
import Reveal from "./Reveal";

const INSIGHTS = [
  {
    icon: Sigma,
    tag: "Quantitative",
    title: "Signals & Factors",
    body: "Statistical studies on price behaviour, factor structure, and the anatomy of market returns.",
    span: "md:col-span-7",
  },
  {
    icon: Globe,
    tag: "Macro",
    title: "Regimes & Cycles",
    body: "How macro developments and shifting regimes reshape risk across asset classes.",
    span: "md:col-span-5",
  },
  {
    icon: TrendingUp,
    tag: "Markets",
    title: "Market Structure",
    body: "Trends, participation, and liquidity dynamics across global financial markets.",
    span: "md:col-span-5",
  },
  {
    icon: BookOpen,
    tag: "Education",
    title: "Research Notes",
    body: "Clear, evidence-led writing that makes quantitative thinking approachable.",
    span: "md:col-span-7",
  },
];

export const MarketInsights = () => {
  return (
    <section id="insights" className="relative py-24 md:py-40 bg-surface/40 border-y border-white/5" data-testid="insights-section">
      <div className="container-x">
        <Reveal>
          <p className="overline mb-6">Market Insights</p>
          <h2 className="font-display font-black tracking-tighter text-white text-4xl md:text-6xl leading-[1.02] max-w-3xl">
            Insight, grounded in evidence.
          </h2>
          <p className="mt-6 text-base md:text-lg font-light text-slate-400 max-w-xl">
            A forthcoming stream of research and commentary spanning four pillars of
            our work — published as the platform takes shape.
          </p>
        </Reveal>

        <div className="mt-16 grid grid-cols-1 md:grid-cols-12 gap-5">
          {INSIGHTS.map((it, i) => {
            const Icon = it.icon;
            return (
              <Reveal
                key={it.title}
                delay={i * 0.08}
                className={`col-span-1 ${it.span} card-hover glass rounded-2xl p-8 md:p-10 min-h-[200px] flex flex-col justify-between`}
                data-testid={`insight-card-${i}`}
              >
                <div className="flex items-center justify-between">
                  <span className="overline !text-slate-500">{it.tag}</span>
                  <Icon size={20} className="text-sapphire-light" />
                </div>
                <div className="mt-10">
                  <h3 className="font-display text-2xl md:text-3xl font-bold text-white mb-2">{it.title}</h3>
                  <p className="text-sm md:text-base font-light text-slate-400 leading-relaxed max-w-md">{it.body}</p>
                </div>
              </Reveal>
            );
          })}
        </div>
      </div>
    </section>
  );
};

export default MarketInsights;
