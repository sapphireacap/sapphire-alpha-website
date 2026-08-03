import { useEffect, useState } from "react";
import axios from "axios";
import { motion } from "framer-motion";
import { LayoutGrid, LineChart, Target, FileText, Box, Settings, ChevronDown, MoreHorizontal } from "lucide-react";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;

// Real data only -- no fabricated numbers. Index Vector's public spot feed
// is the only source of genuinely live tickers this site has -- NIFTY,
// BANKNIFTY, FINNIFTY are the three indices actually covered (see
// definedge_service.py's INDEX_CONFIG). There is no Dow Jones, Bitcoin, or
// XAUUSD data source anywhere in this codebase (checked: no crypto client,
// no forex/commodity feed; Alpha Vantage only covers NDX/SPX daily bars on
// a 25-req/day quota already spent by P&F Studio, and Definedge's only
// real gold instrument is MCX gold futures in INR, a different instrument
// than XAUUSD spot) -- so those three aren't shown rather than faked.
// Fails open per-tile (shows "—") rather than breaking the homepage if the
// upstream feed is down or the market's closed.
const INDICES = [
  { key: "NIFTY", label: "NIFTY 50" },
  { key: "BANKNIFTY", label: "BANK NIFTY" },
  { key: "FINNIFTY", label: "FIN NIFTY" },
];
const REFRESH_MS = 30000;
const RAIL_ICONS = [LayoutGrid, LineChart, Target, FileText, Box, Settings];

// Decorative sparkline only -- no invented price history, just a generic
// upward/downward-leaning wave whose direction matches the real % change.
const Sparkline = ({ negative }) => {
  const path = negative
    ? "M2,10 C20,18 40,14 60,26 C80,36 100,30 120,42 C140,50 160,44 178,54"
    : "M2,54 C20,46 40,50 60,38 C80,28 100,34 120,22 C140,14 160,20 178,8";
  return (
    <svg viewBox="0 0 180 60" preserveAspectRatio="none" className="w-full h-full" aria-hidden="true">
      <motion.path
        d={path}
        fill="none"
        stroke={negative ? "#F87171" : "#34D399"}
        strokeWidth="2"
        strokeLinecap="round"
        initial={{ pathLength: 0, opacity: 0 }}
        animate={{ pathLength: 1, opacity: 1 }}
        transition={{ duration: 1.4, ease: "easeInOut", delay: 0.4 }}
      />
    </svg>
  );
};

export const HeroDashboardMockup = () => {
  const [spots, setSpots] = useState({});

  useEffect(() => {
    let cancelled = false;
    const load = () => {
      Promise.all(
        INDICES.map((idx) =>
          axios.get(`${API}/terminal/spot`, { params: { index: idx.key } })
            .then((r) => [idx.key, r.data])
            .catch(() => [idx.key, null])
        )
      ).then((pairs) => { if (!cancelled) setSpots(Object.fromEntries(pairs)); });
    };
    load();
    const id = setInterval(load, REFRESH_MS);
    return () => { cancelled = true; clearInterval(id); };
  }, []);

  return (
    <motion.div
      initial={{ opacity: 0, y: 30, scale: 0.96 }}
      animate={{ opacity: 1, y: 0, scale: 1 }}
      transition={{ duration: 1.1, ease: [0.16, 1, 0.3, 1], delay: 0.7 }}
      className="relative w-full"
      data-testid="hero-dashboard-mockup"
    >
      {/* subtle blue radial lighting behind the mockup */}
      <div className="absolute -inset-16 radial-glow pointer-events-none" />
      <div className="absolute -inset-8 rounded-[2rem] bg-sapphire/10 blur-[80px] pointer-events-none" />

      <motion.div
        animate={{ y: [0, -10, 0] }}
        transition={{ duration: 7, repeat: Infinity, ease: "easeInOut" }}
        className="relative glass rounded-2xl overflow-hidden shadow-2xl shadow-black/50 flex"
      >
        {/* decorative icon rail -- purely visual, not interactive */}
        <div className="hidden sm:flex flex-col items-center gap-6 w-16 shrink-0 py-6 border-r border-white/10 bg-white/[0.015]">
          {RAIL_ICONS.map((Icon, i) => (
            <Icon key={i} size={17} className={i === 0 ? "text-sapphire-light" : "text-slate-600"} />
          ))}
        </div>

        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 px-5 py-4 sm:px-7 sm:py-5 border-b border-white/10">
            <span className="h-2.5 w-2.5 rounded-full bg-red-500/70" />
            <span className="h-2.5 w-2.5 rounded-full bg-yellow-500/70" />
            <span className="h-2.5 w-2.5 rounded-full bg-emerald-500/70" />
            <span className="ml-3 font-mono-ui text-xs text-slate-500">sac_engine · live</span>
          </div>

          <div className="p-5 sm:p-8">
            <div className="flex items-center justify-between mb-5 sm:mb-7">
              <div className="flex items-center gap-2">
                <p className="text-base sm:text-lg font-medium text-white">Market Overview</p>
                <span className="flex items-center gap-1.5 font-mono-ui text-[10px] text-emerald-400">
                  <span className="h-1.5 w-1.5 rounded-full bg-emerald-400 animate-pulse" /> Live
                </span>
              </div>
              {/* decorative chrome, not interactive */}
              <div className="hidden sm:flex items-center gap-1.5 text-slate-600" aria-hidden="true">
                <span className="flex items-center gap-0.5 font-mono-ui text-[9px] border border-white/10 rounded px-1.5 py-0.5">
                  1D <ChevronDown size={10} />
                </span>
                <MoreHorizontal size={13} />
              </div>
            </div>

            <div className="flex flex-col gap-3 sm:gap-4">
              {INDICES.map((idx) => {
                const s = spots[idx.key];
                const negative = s?.change?.startsWith("-");
                return (
                  <div
                    key={idx.key}
                    className="flex items-center justify-between gap-4 rounded-xl border border-white/10 bg-white/[0.02] px-5 py-5 sm:px-7 sm:py-6"
                  >
                    <div className="font-mono-ui">
                      <p className="text-[10px] sm:text-xs uppercase tracking-[0.12em] text-slate-500">{idx.label}</p>
                      <p className="text-2xl sm:text-3xl text-white mt-2 truncate">{s?.spot ?? "—"}</p>
                      {s?.change_pct && (
                        <p className={`text-sm mt-1.5 ${negative ? "text-red-400" : "text-emerald-400"}`}>
                          {s.change} ({s.change_pct}%)
                        </p>
                      )}
                    </div>
                    <div className="hidden xs:block w-28 sm:w-40 h-14 sm:h-16 shrink-0">
                      {s && <Sparkline negative={negative} />}
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        </div>
      </motion.div>
    </motion.div>
  );
};

export default HeroDashboardMockup;
