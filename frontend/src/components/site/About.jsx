import { LineChart, Layers, Cpu } from "lucide-react";
import { ABOUT, FOUNDER } from "@/content/homepage";
import Reveal from "./Reveal";

const ICONS = [LineChart, Layers, Cpu];

const SHOW_FOUNDER = !FOUNDER.name.startsWith("[TODO");

export const About = () => (
  <section id="about" aria-labelledby="about-heading" className="relative section-y" data-testid="about-section">
    <div className="container-x">
      <div className="flex flex-col md:grid md:grid-cols-12 gap-8 md:gap-16 items-end mb-14 md:mb-20">
        <Reveal className="md:col-span-7">
          <p className="label-mono mb-6">{ABOUT.label}</p>
          <h2 id="about-heading" className="font-display font-normal tracking-[-0.015em] text-bone text-[2.25rem] md:text-6xl leading-[1.04]">
            {ABOUT.heading}
          </h2>
        </Reveal>
        <Reveal delay={0.12} className="md:col-span-5">
          <p className="text-base md:text-lg font-light text-bone/80 leading-relaxed">{ABOUT.intro}</p>
        </Reveal>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-5 md:gap-6">
        {ABOUT.pillars.map((p, i) => {
          const Icon = ICONS[i];
          return (
            <Reveal
              key={p.no}
              delay={i * 0.08}
              className="card-hover group relative rounded-2xl border border-white/10 bg-white/[0.02] p-8 md:p-10"
              data-testid={`pillar-card-${p.no}`}
            >
              <div className="flex items-center justify-between mb-14 md:mb-16">
                <span className="font-mono-ui text-xs tracking-[0.2em] text-bone/70 uppercase">
                  {p.no} / {p.tag}
                </span>
                <span className="flex h-11 w-11 items-center justify-center rounded-xl bg-gradient-to-br from-sapphire-light/20 to-sapphire/5 border border-sapphire-light/20 transition-colors duration-300 group-hover:from-sapphire-light/30">
                  <Icon className="text-sapphire-light" size={20} aria-hidden="true" />
                </span>
              </div>
              <h3 className="text-2xl md:text-3xl font-bold text-white mb-4">{p.title}</h3>
              <p className="text-sm md:text-base font-light text-bone/75 leading-relaxed">{p.body}</p>
            </Reveal>
          );
        })}
      </div>

      <div className="mt-16 md:mt-24 grid grid-cols-1 gap-12 border-t border-bone/15 pt-12 md:grid-cols-12 md:gap-16">
        {SHOW_FOUNDER && (
        <Reveal className="md:col-span-7" data-testid="founder-block">
          <p className="label-mono mb-5">{FOUNDER.label}</p>
          <p className="font-display text-3xl md:text-4xl text-bone leading-tight">{FOUNDER.name}</p>
          <p className="mt-4 max-w-[52ch] text-base leading-relaxed text-bone/80">{FOUNDER.line}</p>
          {FOUNDER.links.length > 0 && (
            <ul className="mt-5 flex flex-wrap gap-x-6 gap-y-2">
              {FOUNDER.links.map((l) => (
                <li key={l.href}>
                  <a
                    href={l.href}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="inline-flex min-h-[44px] items-center text-sm text-bone underline decoration-bone/40 underline-offset-[6px] hover:decoration-bone"
                  >
                    {l.label}
                  </a>
                </li>
              ))}
            </ul>
          )}
        </Reveal>
        )}
        <Reveal delay={0.1} className={SHOW_FOUNDER ? "md:col-span-5" : "md:col-span-12 max-w-2xl"} data-testid="does-not-block">
          <p className="label-mono mb-5">{ABOUT.doesNotLabel}</p>
          <p className="text-base leading-relaxed text-bone/80">{ABOUT.doesNot}</p>
        </Reveal>
      </div>
    </div>
  </section>
);

export default About;
