import { useEffect, useState } from "react";
import axios from "axios";
import { motion } from "framer-motion";
import { LayoutGrid, LineChart, Target, FileText, Box, Settings, ChevronDown, MoreHorizontal } from "lucide-react";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;

// Real data only -- no fabricated numbers. NIFTY/BANKNIFTY/FINNIFTY come
// from Index Vector's public spot feed (definedge_service.py's
// INDEX_CONFIG); BTC comes straight from Binance's free public API
// (verified live: sends Access-Control-Allow-Origin: *, same source
// already used by the Crypto tab in Alpha Terminal -- no backend involved).
// SPX and Gold go through the backend's /terminal/external-spot proxy
// (server.py) instead of a direct frontend fetch -- Yahoo Finance's public
// chart API has the real data but sends no CORS header, so a browser call
// straight to Yahoo fails silently; the proxy also caches server-side so
// every visitor's poll cycle doesn't hit Yahoo's unofficial endpoint
// individually. "Gold" is COMEX gold futures (GC=F), not true spot
// XAUUSD -- Yahoo's forex-style XAUUSD=X/XAU=X symbols both 404 live, so
// it's labeled for what it actually is rather than mislabeled as spot FX.
const INDICES = [
  { key: "NIFTY", label: "NIFTY 50", kind: "index" },
  { key: "BANKNIFTY", label: "BANK NIFTY", kind: "index" },
  { key: "FINNIFTY", label: "FIN NIFTY", kind: "index" },
  { key: "BTCUSDT", label: "BITCOIN", kind: "crypto" },
  { key: "SPX", label: "S&P 500", kind: "external" },
  { key: "GOLD", label: "GOLD", kind: "external" },
];
const REFRESH_MS = 30000;
const RAIL_ICONS = [LayoutGrid, LineChart, Target, FileText, Box, Settings];
const BINANCE_API = "https://api.binance.com/api/v3";

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
        INDICES.map((idx) => {
          if (idx.kind === "crypto") {
            return axios.get(`${BINANCE_API}/ticker/24hr`, { params: { symbol: idx.key } })
              .then((r) => {
                const d = r.data;
                const price = parseFloat(d.lastPrice);
                const change = parseFloat(d.priceChange);
                return [idx.key, {
                  spot: price.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 }),
                  change: `${change >= 0 ? "+" : ""}${change.toFixed(2)}`,
                  change_pct: `${parseFloat(d.priceChangePercent) >= 0 ? "+" : ""}${parseFloat(d.priceChangePercent).toFixed(2)}`,
                }];
              })
              .catch(() => [idx.key, null]);
          }
          if (idx.kind === "external") {
            return axios.get(`${API}/terminal/external-spot`, { params: { symbol: idx.key } })
              .then((r) => [idx.key, r.data])
              .catch(() => [idx.key, null]);
          }
          return axios.get(`${API}/terminal/spot`, { params: { index: idx.key } })
            .then((r) => [idx.key, r.data])
            .catch(() => [idx.key, null]);
        })
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

      <div className="relative glass rounded-2xl overflow-hidden shadow-2xl shadow-black/50 flex">
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

            {/* Fixed-height viewport (~3 cards) with the list rendered twice
                back-to-back inside a continuously-scrolling track. Animating
                to exactly -50% of the track's own height (not a hardcoded
                pixel guess) always lands the scroll precisely on the seam
                between the two copies, so the loop point is invisible
                regardless of actual responsive card height -- true infinite
                scroll, not a reset snap. Outer window frame stays still;
                only this inner track moves. */}
            <div className="relative h-[380px] sm:h-[420px] overflow-hidden" data-testid="market-overview-scroll">
              <div className="pointer-events-none absolute inset-x-0 top-0 h-8 bg-gradient-to-b from-[#0A0D18] to-transparent z-10" />
              <div className="pointer-events-none absolute inset-x-0 bottom-0 h-8 bg-gradient-to-t from-[#0A0D18] to-transparent z-10" />
              <motion.div
                className="flex flex-col gap-3 sm:gap-4"
                animate={{ y: ["0%", "-50%"] }}
                transition={{ duration: INDICES.length * 3.5, repeat: Infinity, ease: "linear" }}
              >
                {[...INDICES, ...INDICES].map((idx, i) => {
                  const s = spots[idx.key];
                  const negative = s?.change?.startsWith("-");
                  return (
                    <div
                      key={`${idx.key}-${i}`}
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
              </motion.div>
            </div>
          </div>
        </div>
      </div>
    </motion.div>
  );
};

export default HeroDashboardMockup;
