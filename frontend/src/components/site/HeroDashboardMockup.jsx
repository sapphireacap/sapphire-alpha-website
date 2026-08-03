import { motion } from "framer-motion";

const EASE = [0.16, 1, 0.3, 1];

// Decorative only -- no real data, no invented copy. The three metric
// tiles reuse the exact SIGNAL_STRENGTH/REGIME/STATUS values already
// printed in Hero's own ticker row (kept byte-identical there); the
// "sac_engine · live" label is reused verbatim from Investing.jsx's
// Terminal component. The chart is a decorative animated path, same
// pathLength-draw technique already used by Research.jsx's hex diagram.
const CHART_PATH = "M4,86 C24,78 34,52 54,58 C74,64 84,30 104,34 C124,38 134,74 154,66 C174,58 184,18 204,22 C224,26 234,50 254,42 C274,34 284,8 296,10";
const AREA_PATH = `${CHART_PATH} L296,120 L4,120 Z`;

export const HeroDashboardMockup = () => (
  <motion.div
    initial={{ opacity: 0, y: 30, scale: 0.96 }}
    animate={{ opacity: 1, y: 0, scale: 1 }}
    transition={{ duration: 1.1, ease: EASE, delay: 0.7 }}
    className="relative w-full max-w-md mx-auto"
    data-testid="hero-dashboard-mockup"
  >
    {/* subtle blue radial lighting behind the mockup */}
    <div className="absolute -inset-16 radial-glow pointer-events-none" />
    <div className="absolute -inset-8 rounded-[2rem] bg-sapphire/10 blur-[80px] pointer-events-none" />

    <motion.div
      animate={{ y: [0, -10, 0] }}
      transition={{ duration: 7, repeat: Infinity, ease: "easeInOut" }}
      className="relative glass rounded-2xl overflow-hidden shadow-2xl shadow-black/50"
    >
      <div className="flex items-center gap-2 px-5 py-3.5 border-b border-white/10">
        <span className="h-2.5 w-2.5 rounded-full bg-red-500/70" />
        <span className="h-2.5 w-2.5 rounded-full bg-yellow-500/70" />
        <span className="h-2.5 w-2.5 rounded-full bg-emerald-500/70" />
        <span className="ml-3 font-mono-ui text-xs text-slate-500">sac_engine · live</span>
      </div>

      <div className="p-6">
        <svg viewBox="0 0 300 120" className="w-full h-32" preserveAspectRatio="none" aria-hidden="true">
          <defs>
            <linearGradient id="heroChartFill" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="#437EEB" stopOpacity="0.35" />
              <stop offset="100%" stopColor="#437EEB" stopOpacity="0" />
            </linearGradient>
          </defs>
          <motion.path
            d={AREA_PATH}
            fill="url(#heroChartFill)"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            transition={{ duration: 1, delay: 1.6 }}
          />
          <motion.path
            d={CHART_PATH}
            fill="none"
            stroke="#437EEB"
            strokeWidth="2"
            strokeLinecap="round"
            initial={{ pathLength: 0 }}
            animate={{ pathLength: 1 }}
            transition={{ duration: 1.6, delay: 0.9, ease: "easeInOut" }}
          />
        </svg>

        <div className="mt-5 grid grid-cols-3 gap-3 font-mono-ui">
          <div className="rounded-lg border border-white/10 bg-white/[0.02] px-3 py-2.5">
            <p className="text-[9px] uppercase tracking-[0.12em] text-slate-500">Signal</p>
            <p className="text-sm text-emerald-400 mt-1">0.847</p>
          </div>
          <div className="rounded-lg border border-white/10 bg-white/[0.02] px-3 py-2.5">
            <p className="text-[9px] uppercase tracking-[0.12em] text-slate-500">Regime</p>
            <p className="text-sm text-emerald-400 mt-1">RISK_ON</p>
          </div>
          <div className="rounded-lg border border-white/10 bg-white/[0.02] px-3 py-2.5">
            <p className="text-[9px] uppercase tracking-[0.12em] text-slate-500">Status</p>
            <p className="text-sm text-white mt-1">BUILDING</p>
          </div>
        </div>
      </div>
    </motion.div>
  </motion.div>
);

export default HeroDashboardMockup;
