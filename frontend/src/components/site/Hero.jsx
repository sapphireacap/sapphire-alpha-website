import { useRef } from "react";
import { motion, useScroll, useTransform } from "framer-motion";
import { ArrowDown, ArrowUpRight } from "lucide-react";
import ParticleField from "./ParticleField";
import { scrollToId } from "./SmoothScroll";

const EASE = [0.16, 1, 0.3, 1];

const Line = ({ children, delay }) => (
  <span className="block overflow-hidden">
    <motion.span
      className="block"
      initial={{ y: "110%" }}
      animate={{ y: 0 }}
      transition={{ duration: 1.1, ease: EASE, delay }}
    >
      {children}
    </motion.span>
  </span>
);

export const Hero = () => {
  const ref = useRef(null);
  const { scrollYProgress } = useScroll({ target: ref, offset: ["start start", "end start"] });
  const y = useTransform(scrollYProgress, [0, 1], [0, 180]);
  const opacity = useTransform(scrollYProgress, [0, 0.8], [1, 0]);

  return (
    <section
      id="home"
      ref={ref}
      className="relative min-h-screen flex items-center overflow-hidden"
      data-testid="hero-section"
    >
      <ParticleField />
      <div className="absolute inset-0 radial-glow" />
      <div className="absolute top-1/3 -left-40 w-[500px] h-[500px] rounded-full bg-sapphire/10 blur-[120px] pointer-events-none" />
      <div className="absolute inset-0 bg-gradient-to-b from-void/0 via-void/0 to-void pointer-events-none" />

      <motion.div style={{ y, opacity }} className="container-x relative z-10 pt-28 pb-20">
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ delay: 0.15, duration: 0.8 }}
          className="flex items-center gap-3 mb-8"
        >
          <span className="relative flex h-2 w-2">
            <span className="absolute inline-flex h-full w-full rounded-full bg-sapphire-light opacity-75 animate-ping" />
            <span className="relative inline-flex h-2 w-2 rounded-full bg-sapphire-light" />
          </span>
          <span className="overline">Quantitative Research · Currently in Development</span>
        </motion.div>

        <h1 className="font-display font-black tracking-tighter leading-[0.95] text-white text-5xl sm:text-7xl lg:text-8xl xl:text-[8.5rem]">
          <Line delay={0.35}>Built on Research.</Line>
          <Line delay={0.5}>
            <span
              className="inline-block"
              style={{
                backgroundImage: "linear-gradient(90deg, #5B92F5 0%, #437EEB 45%, #1F5FD0 100%)",
                WebkitBackgroundClip: "text",
                backgroundClip: "text",
                WebkitTextFillColor: "transparent",
                color: "transparent",
              }}
            >
              Driven by Alpha.
            </span>
          </Line>
        </h1>

        <motion.p
          initial={{ opacity: 0, y: 24 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.9, duration: 0.9, ease: EASE }}
          className="mt-8 max-w-xl text-base md:text-lg font-light text-slate-400 leading-relaxed"
          data-testid="hero-description"
        >
          Sapphire Alpha Capital is building a data-driven platform focused on
          quantitative research, systematic investing, and financial market
          insights. Currently under development.
        </motion.p>

        <motion.div
          initial={{ opacity: 0, y: 24 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 1.05, duration: 0.9, ease: EASE }}
          className="mt-10 flex flex-wrap items-center gap-4"
        >
          <button onClick={() => scrollToId("waitlist")} className="btn-sapphire" data-testid="hero-notify-btn">
            Get Notified <ArrowUpRight size={16} />
          </button>
          <button onClick={() => scrollToId("about")} className="btn-ghost" data-testid="hero-learn-btn">
            Learn More
          </button>
        </motion.div>

        {/* Data readout ticker */}
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ delay: 1.3, duration: 1 }}
          className="mt-16 flex flex-wrap gap-x-10 gap-y-3 font-mono-ui text-xs text-slate-500"
        >
          <span><span className="text-sapphire-light">//</span> SIGNAL_STRENGTH: <span className="text-emerald-400">0.847</span></span>
          <span><span className="text-sapphire-light">//</span> REGIME: <span className="text-emerald-400">RISK_ON</span></span>
          <span><span className="text-sapphire-light">//</span> STATUS: <span className="text-white">BUILDING</span></span>
        </motion.div>
      </motion.div>

      <motion.button
        onClick={() => scrollToId("about")}
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        transition={{ delay: 1.6, duration: 1 }}
        className="absolute bottom-8 left-1/2 -translate-x-1/2 flex flex-col items-center gap-2 text-slate-500 hover:text-white transition-colors"
        data-testid="hero-scroll-indicator"
        aria-label="Scroll down"
      >
        <span className="font-mono-ui text-[10px] tracking-[0.3em] uppercase">Scroll</span>
        <motion.span animate={{ y: [0, 6, 0] }} transition={{ repeat: Infinity, duration: 1.8 }}>
          <ArrowDown size={16} />
        </motion.span>
      </motion.button>
    </section>
  );
};

export default Hero;
