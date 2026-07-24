import { useNavigate } from "react-router-dom";
import { motion } from "framer-motion";
import { ArrowLeft } from "lucide-react";
import Navbar from "../../components/site/Navbar";
import Footer from "../../components/site/Footer";
import LivePulseDot from "../../components/site/LivePulseDot";

const EASE = [0.16, 1, 0.3, 1];

// Shared page chrome for each Quant Lab tool's and each scanner's own
// route — back-link + title/description hero, tighter than the main
// Alpha Terminal hub's hero per the terminal-density redesign.
const QuantLabToolShell = ({ title, description, live = true, icon: Icon, children }) => {
  const navigate = useNavigate();
  return (
    <>
      <Navbar />
      <main className="relative bg-void min-h-screen">
        <section className="relative pt-28 pb-10 md:pt-32 md:pb-14 overflow-hidden" data-testid="quant-lab-tool-hero">
          <div className="absolute inset-0 radial-glow" />
          <div className="absolute inset-0 bg-gradient-to-b from-void/0 to-void pointer-events-none" />
          <div className="container-x relative z-10">
            <button
              onClick={() => navigate("/alpha-terminal")}
              className="inline-flex items-center gap-2 text-slate-500 hover:text-white transition-colors text-sm mb-8"
              data-testid="quant-lab-tool-back"
            >
              <ArrowLeft size={14} /> Back to Alpha Terminal
            </button>
            <motion.div
              initial={{ opacity: 0, y: 16 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.7, ease: EASE }}
              className="flex flex-wrap items-center gap-3 mb-4"
            >
              {Icon && (
                <span className="inline-flex h-10 w-10 items-center justify-center rounded-xl border border-sapphire/30 bg-sapphire/15 text-sapphire-light">
                  <Icon size={18} />
                </span>
              )}
              <h1 className="font-display font-black tracking-tighter text-white text-3xl md:text-5xl leading-[0.95]" data-testid="quant-lab-tool-title">
                {title}
              </h1>
              {live && (
                <span className="inline-flex items-center gap-1.5 rounded-full border border-emerald-400/25 bg-emerald-400/10 px-2.5 py-0.5 font-mono-ui text-[10px] uppercase tracking-wider text-emerald-300">
                  <LivePulseDot /> Live
                </span>
              )}
            </motion.div>
            {description && (
              <motion.p
                initial={{ opacity: 0, y: 16 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.7, ease: EASE, delay: 0.1 }}
                className="text-base font-light text-slate-400 leading-relaxed max-w-2xl"
                data-testid="quant-lab-tool-description"
              >
                {description}
              </motion.p>
            )}
          </div>
        </section>

        <section className="relative pb-20 md:pb-28">
          <div className="container-x">{children}</div>
        </section>
      </main>
      <Footer />
    </>
  );
};

export default QuantLabToolShell;
