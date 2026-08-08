import { motion } from "framer-motion";
import { ArrowUpRight } from "lucide-react";
import { Link } from "react-router-dom";
import { MODULES } from "@/pages/alphaterminal/modules";
import { scrollToId } from "./SmoothScroll";

const EASE = [0.16, 1, 0.3, 1];

const liveModules = MODULES.filter((m) => m.live);
const liveCount = liveModules.length;

export const Hero = () => (
  <section
    id="home"
    className="relative min-h-screen flex items-center overflow-hidden"
    data-testid="hero-section"
  >
    <div className="container-x relative z-10 w-full pt-28 pb-24 md:pt-32 md:pb-28">
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-14 lg:gap-16 items-start">
        <div className="lg:col-span-7">
          <motion.h1
            initial={{ opacity: 0, y: 14 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 1, ease: EASE }}
            className="font-display text-bone leading-[1.02] tracking-[-0.02em] text-[2.75rem] sm:text-6xl lg:text-[4.25rem]"
          >
            Built on Research.
            <br />
            Driven by Alpha.
          </motion.h1>

          <motion.p
            initial={{ opacity: 0, y: 14 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 1, ease: EASE, delay: 0.12 }}
            className="mt-8 max-w-[62ch] text-[15px] md:text-base leading-relaxed text-bone/65"
            data-testid="hero-description"
          >
            Sapphire Alpha Capital is building a quantitative research platform
            focused on research, technology and analytical tools for the capital
            markets. Currently under development. More to come.
          </motion.p>

          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            transition={{ duration: 1, ease: EASE, delay: 0.24 }}
            className="mt-12 flex flex-col sm:flex-row sm:items-stretch gap-8 sm:gap-12"
          >
            <Link
              to="/alpha-terminal"
              className="group border-t border-bone/30 pt-3.5 transition-colors duration-300 hover:border-bone/70"
              data-testid="hero-terminal-btn"
            >
              <span className="flex items-center gap-2 text-bone text-sm">
                Open Alpha Terminal
                <ArrowUpRight
                  size={15}
                  className="transition-transform duration-300 group-hover:translate-x-0.5 group-hover:-translate-y-0.5"
                />
              </span>
              <span className="mt-1 block font-mono text-[10.5px] uppercase tracking-[0.16em] text-bone/60">
                {liveCount} engines live
              </span>
            </Link>

            <button
              onClick={() => scrollToId("about")}
              className="group text-left border-t border-bone/15 pt-3.5 transition-colors duration-300 hover:border-bone/45"
              data-testid="hero-learn-btn"
            >
              <span className="block text-bone/80 text-sm group-hover:text-bone transition-colors duration-300">
                How a read is built
              </span>
              <span className="mt-1 block font-mono text-[10.5px] uppercase tracking-[0.16em] text-bone/60">
                Method and limits
              </span>
            </button>
          </motion.div>
        </div>

        {/* The plate's margin: where an atlas records how the reading was made
            and what it cannot tell you. */}
        <motion.aside
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ duration: 1.1, ease: EASE, delay: 0.36 }}
          className="lg:col-span-4 lg:col-start-9 lg:border-l lg:border-bone/12 lg:pl-8"
        >
          <dl className="space-y-7">
            <div>
              <dt className="font-mono text-[10.5px] uppercase tracking-[0.18em] text-bone/60">
                Method
              </dt>
              <dd className="mt-2.5 text-[13.5px] leading-relaxed text-bone/70">
                Each engine computes independently from exchange data. None of them
                sees another's output, so agreement between them is evidence rather
                than an average.
              </dd>
            </div>
            <div>
              <dt className="font-mono text-[10.5px] uppercase tracking-[0.18em] text-bone/60">
                Limits
              </dt>
              <dd className="mt-2.5 text-[13.5px] leading-relaxed text-bone/70">
                Nothing here forecasts price and nothing here is advice. Where an
                engine has no reading, it says so instead of estimating one.
              </dd>
            </div>
          </dl>
        </motion.aside>
      </div>
    </div>

    {/* The plate's index. Fills the hero's lower band with the actual
        contents of the terminal rather than decoration, and stays honest
        by naming only the engines currently live. */}
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      transition={{ duration: 1.2, ease: EASE, delay: 0.5 }}
      className="absolute inset-x-0 bottom-0 z-10 hidden md:block"
    >
      <div className="container-x pb-10">
        <ul className="flex flex-wrap gap-x-7 gap-y-2.5 border-t border-bone/12 pt-4">
          {liveModules.map((m) => (
            <li
              key={m.slug}
              className="font-mono text-[10px] uppercase tracking-[0.16em] text-bone/60"
            >
              {m.title}
            </li>
          ))}
        </ul>
      </div>
    </motion.div>
  </section>
);

export default Hero;
