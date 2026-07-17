import { motion } from "framer-motion";
import Reveal from "./Reveal";

const EASE = [0.16, 1, 0.3, 1];

const CHAPTERS = [
  {
    no: "01",
    title: "Evidence Before Conviction.",
    body: "We let data lead. Every idea is tested against history, structure, and statistical reasoning before it earns a place in our thinking.",
  },
  {
    no: "02",
    title: "Systematic Over Discretionary.",
    body: "Repeatable, rule-based processes remove noise and emotion — prioritising discipline and consistency over prediction.",
  },
  {
    no: "03",
    title: "Research Compounds.",
    body: "Insight accumulates. We publish, observe, and iterate — building a body of work designed for long-term understanding.",
  },
];

const MaskedTitle = ({ children }) => (
  <motion.span
    className="block overflow-hidden"
    initial="hidden"
    whileInView="show"
    viewport={{ once: true, amount: 0.15 }}
  >
    <motion.span
      className="block"
      variants={{ hidden: { y: "110%" }, show: { y: 0 } }}
      transition={{ duration: 1, ease: EASE }}
    >
      {children}
    </motion.span>
  </motion.span>
);

export const Manifesto = () => {
  return (
    <section className="relative py-24 md:py-40 bg-surface/40 border-y border-white/5" data-testid="manifesto-section">
      <div className="absolute inset-0 grid-bg opacity-40 pointer-events-none" />
      <div className="container-x relative">
        <Reveal>
          <p className="overline mb-16 md:mb-24">Manifesto · How We Think</p>
        </Reveal>

        <div className="space-y-16 md:space-y-28">
          {CHAPTERS.map((c) => (
            <div
              key={c.no}
              className="grid grid-cols-12 gap-6 md:gap-16 items-start border-t border-white/10 pt-10 md:pt-16"
              data-testid={`manifesto-chapter-${c.no}`}
            >
              <div className="col-span-12 md:col-span-2">
                <span className="font-mono-ui text-sm text-sapphire-light tracking-[0.2em]">/ {c.no}</span>
              </div>
              <div className="col-span-12 md:col-span-7">
                <h3 className="font-display font-black tracking-tighter text-white text-3xl sm:text-5xl md:text-6xl leading-[0.98]">
                  <MaskedTitle>{c.title}</MaskedTitle>
                </h3>
              </div>
              <Reveal delay={0.2} className="col-span-12 md:col-span-3">
                <p className="text-base font-light text-slate-400 leading-relaxed">{c.body}</p>
              </Reveal>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
};

export default Manifesto;
