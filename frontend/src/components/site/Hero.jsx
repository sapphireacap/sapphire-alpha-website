import { motion } from "framer-motion";
import { ArrowUpRight } from "lucide-react";
import { Link } from "react-router-dom";
import { MODULES } from "@/pages/alphaterminal/modules";
import { HERO } from "@/content/homepage";
import { EASE, SKIP_INTRO } from "@/lib/motion";

const liveCount = MODULES.filter((m) => m.live).length;

// Above-the-fold content renders in its final state when prerendered
// (SKIP_INTRO) so the first paint is the real page, not text waiting on an
// animation. In dev, where nothing is prerendered, it still fades up.
const rise = (delay) =>
  SKIP_INTRO
    ? { initial: false }
    : {
        initial: { opacity: 0, y: 14 },
        animate: { opacity: 1, y: 0 },
        transition: { duration: 0.9, ease: EASE, delay },
      };

export const Hero = () => (
  <section
    id="home"
    aria-labelledby="hero-heading"
    className="relative min-h-[100svh] flex items-center overflow-hidden"
    data-testid="hero-section"
  >
    <div className="container-x relative z-10 w-full pt-32 pb-20 md:pt-40 md:pb-28">
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-14 lg:gap-16 items-start">
        <div className="lg:col-span-7">
          <motion.h1
            id="hero-heading"
            {...rise(0)}
            className="font-display text-bone leading-[1.04] tracking-[-0.02em] text-[2.75rem] sm:text-6xl lg:text-[4.25rem]"
          >
            {HERO.headline[0]}
            <br />
            {HERO.headline[1]}
          </motion.h1>

          <motion.p
            {...rise(0.1)}
            className="mt-8 max-w-[60ch] text-base md:text-[17px] leading-relaxed text-bone/80"
            data-testid="hero-description"
          >
            {HERO.sub}
          </motion.p>

          <motion.p
            {...rise(0.16)}
            className="mt-5 max-w-[60ch] text-base md:text-[17px] leading-relaxed text-bone"
            data-testid="hero-what-it-does"
          >
            {HERO.whatItDoes}
          </motion.p>

          <motion.div
            {...rise(0.22)}
            className="mt-12 flex flex-col items-start gap-6 sm:flex-row sm:items-center sm:gap-8"
          >
            <Link
              to="/alpha-terminal"
              className="group inline-flex min-h-[52px] items-center gap-2.5 bg-bone px-7 py-3.5 text-[15px] font-semibold text-plate transition-colors duration-200 hover:bg-white"
              data-testid="hero-terminal-btn"
            >
              {HERO.ctaPrimary}
              <ArrowUpRight
                size={17}
                aria-hidden="true"
                className="transition-transform duration-200 group-hover:translate-x-0.5 group-hover:-translate-y-0.5"
              />
            </Link>
            <Link
              to="/signup"
              className="inline-flex min-h-[44px] items-center text-[15px] text-bone underline decoration-bone/40 underline-offset-[6px] transition-colors duration-200 hover:decoration-bone"
              data-testid="hero-signup-btn"
            >
              {HERO.ctaSecondary}
            </Link>
          </motion.div>
          <p className="mt-4 font-mono text-[11px] uppercase tracking-[0.16em] text-bone/70">
            {HERO.ctaPrimaryNote(liveCount)}
          </p>
        </div>

        {/* The plate's margin: where an atlas records how the reading was made
            and what it cannot tell you. */}
        <motion.aside
          {...(SKIP_INTRO ? { initial: false } : { initial: { opacity: 0 }, animate: { opacity: 1 }, transition: { duration: 1, ease: EASE, delay: 0.3 } })}
          aria-label="Method and limits"
          className="lg:col-span-4 lg:col-start-9 lg:border-l lg:border-bone/15 lg:pl-8"
        >
          <dl className="space-y-7">
            {[HERO.method, HERO.limits].map((item) => (
              <div key={item.label}>
                <dt className="font-mono text-[11px] uppercase tracking-[0.18em] text-bone/70">
                  {item.label}
                </dt>
                <dd className="mt-2.5 text-sm leading-relaxed text-bone/80">{item.text}</dd>
              </div>
            ))}
          </dl>
        </motion.aside>
      </div>
    </div>
  </section>
);

export default Hero;
