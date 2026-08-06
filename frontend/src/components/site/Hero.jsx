import { useRef } from "react";
import { motion, useScroll, useTransform } from "framer-motion";
import { ArrowDown, ArrowUpRight, ChevronRight, PlayCircle } from "lucide-react";
import ParticleField from "./ParticleField";
import { scrollToId } from "./SmoothScroll";
import HeroDashboardMockup from "./HeroDashboardMockup";

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

      <motion.div style={{ y, opacity }} className="container-x relative z-10 pt-24 pb-14 sm:pt-28 sm:pb-20 lg:pt-28">
        <div className="grid grid-cols-1 lg:grid-cols-12 gap-16 lg:gap-10 items-center">
          <div className="lg:col-span-6">
            <motion.div
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              transition={{ delay: 0.15, duration: 0.8 }}
              className="inline-flex items-center gap-3 mb-8 rounded-xl border border-white/10 bg-white/[0.02] pl-4 pr-3.5 py-2.5"
            >
              <span className="relative flex h-2 w-2">
                <span className="absolute inline-flex h-full w-full rounded-full bg-sapphire-light opacity-75 animate-ping" />
                <span className="relative inline-flex h-2 w-2 rounded-full bg-sapphire-light" />
              </span>
              <span className="overline">Quantitative Research</span>
              <ChevronRight size={14} className="text-slate-500" />
            </motion.div>

            <h1 className="font-display font-black tracking-tighter leading-[0.95] text-white text-5xl sm:text-6xl md:text-7xl lg:text-6xl xl:text-7xl">
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
              Quantitative tools and market intelligence for traders who
              want structure before conviction.
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
                Learn More <PlayCircle size={16} />
              </button>
            </motion.div>
          </div>

          <div className="flex lg:col-span-6 items-center justify-center">
            <HeroDashboardMockup />
          </div>
        </div>
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
