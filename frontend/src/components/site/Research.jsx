import { motion } from "framer-motion";
import Reveal from "./Reveal";

const NODES = [
  { label: "QUANT ANALYSIS", x: 200, y: 46 },
  { label: "MARKET RESEARCH", x: 44, y: 300 },
  { label: "SYSTEMATIC", x: 356, y: 300 },
];

const CARDS = [
  {
    tag: "Research First",
    title: "Quantitative Methods",
    body: "Applying statistical techniques to better understand markets and investment decisions.",
  },
  {
    tag: "Evidence Driven",
    title: "Market Structure",
    body: "Studying trends, participation, and price behaviour across financial markets.",
  },
  {
    tag: "Systematic Thinking",
    title: "Investment Frameworks",
    body: "Developing repeatable processes designed around discipline rather than prediction.",
  },
];

const HexDiagram = () => {
  const cx = 200;
  const cy = 215;
  const draw = {
    hidden: { pathLength: 0, opacity: 0 },
    show: (i) => ({
      pathLength: 1,
      opacity: 1,
      transition: { pathLength: { duration: 1.4, delay: i * 0.25, ease: "easeInOut" }, opacity: { duration: 0.3, delay: i * 0.25 } },
    }),
  };

  return (
    <svg viewBox="0 0 400 400" className="w-full max-w-md mx-auto" data-testid="hex-diagram">
      {/* connecting lines */}
      {NODES.map((n, i) => (
        <motion.line
          key={`c-${i}`}
          x1={cx}
          y1={cy}
          x2={n.x}
          y2={n.y}
          stroke="rgba(67,126,235,0.5)"
          strokeWidth="1.5"
          strokeDasharray="4 4"
          variants={draw}
          custom={i}
          initial="hidden"
          whileInView="show"
          viewport={{ once: true }}
        />
      ))}
      {/* outer hexagon */}
      <motion.polygon
        points="200,20 355,110 355,290 200,380 45,290 45,110"
        fill="none"
        stroke="rgba(255,255,255,0.1)"
        strokeWidth="1"
        variants={draw}
        custom={0}
        initial="hidden"
        whileInView="show"
        viewport={{ once: true }}
      />
      {/* center node */}
      <circle cx={cx} cy={cy} r="6" fill="#1F5FD0" />
      <circle cx={cx} cy={cy} r="14" fill="none" stroke="rgba(31,95,208,0.4)" strokeWidth="1">
        <animate attributeName="r" values="14;22;14" dur="3s" repeatCount="indefinite" />
        <animate attributeName="opacity" values="0.6;0;0.6" dur="3s" repeatCount="indefinite" />
      </circle>
      {/* outer nodes */}
      {NODES.map((n, i) => (
        <g key={`n-${i}`}>
          <circle cx={n.x} cy={n.y} r="5" fill="#437EEB" />
          <text
            x={n.x}
            y={n.y < 100 ? n.y - 16 : n.y + 26}
            textAnchor="middle"
            className="font-mono-ui"
            fill="rgba(148,163,184,0.9)"
            fontSize="10"
            letterSpacing="1.5"
          >
            {n.label}
          </text>
        </g>
      ))}
    </svg>
  );
};

export const Research = () => {
  return (
    <section id="research" className="relative py-24 md:py-40" data-testid="research-section">
      <div className="container-x">
        <div className="grid grid-cols-12 gap-12 md:gap-16 items-center">
          <Reveal className="col-span-12 lg:col-span-6 order-2 lg:order-1">
            <p className="overline mb-6">Research · Approach</p>
            <h2 className="font-display font-black tracking-tighter text-white text-4xl md:text-5xl leading-[1.03] mb-6">
              Understanding markets through research.
            </h2>
            <p className="text-base md:text-lg font-light text-slate-400 leading-relaxed mb-10 max-w-lg">
              We publish research, market observations, and educational content that
              emphasizes evidence, structure, and long-term thinking.
            </p>

            <div className="space-y-px bg-white/10 rounded-xl overflow-hidden">
              {CARDS.map((c, i) => (
                <Reveal
                  key={c.title}
                  delay={i * 0.1}
                  className="card-hover bg-void p-6 md:p-7"
                  data-testid={`research-card-${i}`}
                >
                  <p className="overline mb-2 !text-slate-500">{c.tag}</p>
                  <h3 className="font-display text-xl font-bold text-white mb-1.5">{c.title}</h3>
                  <p className="text-sm font-light text-slate-400 leading-relaxed">{c.body}</p>
                </Reveal>
              ))}
            </div>
          </Reveal>

          <Reveal delay={0.2} className="col-span-12 lg:col-span-6 order-1 lg:order-2">
            <div className="relative">
              <div className="absolute inset-0 radial-glow scale-90" />
              <HexDiagram />
            </div>
          </Reveal>
        </div>
      </div>
    </section>
  );
};

export default Research;
