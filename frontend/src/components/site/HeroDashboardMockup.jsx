import { useEffect, useState } from "react";
import axios from "axios";
import { motion } from "framer-motion";
import { LayoutGrid, LineChart, Target, FileText, Box, Settings, ChevronDown, MoreHorizontal, Info } from "lucide-react";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;

// Real data only -- no fabricated numbers. Index Vector's public spot feed
// (NIFTY/BANKNIFTY/FINNIFTY -- the three indices actually covered, see
// definedge_service.py's INDEX_CONFIG) and the public Intraday Momentum
// Leaders scanner, same public endpoints the rest of the site already
// uses. Fails open per-tile (shows "—") rather than breaking the homepage
// if the upstream feed is down or the market's closed. momentum_score
// (star-rating * 20, so 0-100, i.e. 0-5 stars) and volume are both real
// fields already returned by the scanner -- rendered as a 5-segment
// strength meter and a plain volume column rather than inventing either.
const INDICES = ["NIFTY", "BANKNIFTY", "FINNIFTY"];
const REFRESH_MS = 30000;
const RAIL_ICONS = [LayoutGrid, LineChart, Target, FileText, Box, Settings];
const DIRECTION_COLOR = { Bullish: "text-emerald-400", Bearish: "text-red-400", Neutral: "text-amber-400" };

const timeAgo = (iso) => {
  if (!iso) return "—";
  const diffMin = Math.max(0, Math.floor((Date.now() - new Date(iso).getTime()) / 60000));
  if (diffMin < 1) return "now";
  if (diffMin < 60) return `${diffMin}m ago`;
  return `${Math.floor(diffMin / 60)}h ago`;
};

const StrengthMeter = ({ score }) => {
  const filled = Math.round((Number(score) || 0) / 20); // 0-100 -> 0-5 segments
  return (
    <div className="flex items-center gap-0.5" aria-hidden="true">
      {Array.from({ length: 5 }).map((_, i) => (
        <span key={i} className={`h-2.5 w-1 rounded-sm ${i < filled ? "bg-sapphire-light" : "bg-white/10"}`} />
      ))}
    </div>
  );
};

export const HeroDashboardMockup = () => {
  const [spots, setSpots] = useState({});
  const [signals, setSignals] = useState(null);

  useEffect(() => {
    let cancelled = false;
    const load = () => {
      Promise.all(
        INDICES.map((idx) =>
          axios.get(`${API}/terminal/spot`, { params: { index: idx } })
            .then((r) => [idx, r.data])
            .catch(() => [idx, null])
        )
      ).then((pairs) => { if (!cancelled) setSpots(Object.fromEntries(pairs)); });

      axios.get(`${API}/terminal/stocks`, { params: { scanner: "momentum" } })
        .then((r) => { if (!cancelled) setSignals((r.data || []).slice(0, 5)); })
        .catch(() => { if (!cancelled) setSignals([]); });
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
      className="relative w-full max-w-lg mx-auto"
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
        <div className="hidden sm:flex flex-col items-center gap-5 w-14 shrink-0 py-5 border-r border-white/10 bg-white/[0.015]">
          {RAIL_ICONS.map((Icon, i) => (
            <Icon key={i} size={16} className={i === 0 ? "text-sapphire-light" : "text-slate-600"} />
          ))}
        </div>

        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 px-4 py-3 sm:px-6 sm:py-4 border-b border-white/10">
            <span className="h-2.5 w-2.5 rounded-full bg-red-500/70" />
            <span className="h-2.5 w-2.5 rounded-full bg-yellow-500/70" />
            <span className="h-2.5 w-2.5 rounded-full bg-emerald-500/70" />
            <span className="ml-3 font-mono-ui text-xs text-slate-500">sac_engine · live</span>
          </div>

          <div className="p-4 sm:p-6">
            <div className="flex items-center justify-between mb-3 sm:mb-4">
              <div className="flex items-center gap-2">
                <p className="text-sm font-medium text-white">Market Overview</p>
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

            <div className="grid grid-cols-3 gap-2 sm:gap-3 font-mono-ui">
              {INDICES.map((idx) => {
                const s = spots[idx];
                const negative = s?.change?.startsWith("-");
                return (
                  <div key={idx} className="rounded-lg border border-white/10 bg-white/[0.02] px-2.5 py-2.5 sm:px-3.5 sm:py-3.5">
                    <p className="text-[9px] uppercase tracking-[0.1em] text-slate-500">{idx}</p>
                    <p className="text-sm sm:text-base text-white mt-1.5 truncate">{s?.spot ?? "—"}</p>
                    {s?.change_pct && (
                      <p className={`text-[11px] mt-1 ${negative ? "text-red-400" : "text-emerald-400"}`}>
                        {s.change_pct}%
                      </p>
                    )}
                  </div>
                );
              })}
            </div>

            <div className="mt-6">
              <div className="flex items-center gap-1.5 mb-3.5">
                <p className="font-mono-ui text-[10px] uppercase tracking-[0.12em] text-slate-500">
                  Intraday Momentum Leaders
                </p>
                <Info size={11} className="text-slate-600" />
              </div>

              {signals === null ? (
                <div className="py-8 text-center text-xs text-slate-600 font-mono-ui">Loading…</div>
              ) : signals.length === 0 ? (
                <div className="py-8 text-center text-xs text-slate-600 font-mono-ui">No signals right now</div>
              ) : (
                <table className="w-full font-mono-ui text-[10px] sm:text-[11px]">
                  <thead>
                    <tr className="text-slate-500 border-b border-white/10">
                      <th className="text-left font-medium pb-2 sm:pb-2.5">Symbol</th>
                      <th className="text-left font-medium pb-2 sm:pb-2.5">Volume</th>
                      <th className="text-left font-medium pb-2 sm:pb-2.5">Strength</th>
                      <th className="text-left font-medium pb-2 sm:pb-2.5">Direction</th>
                      <th className="hidden sm:table-cell text-right font-medium pb-2.5">Updated</th>
                    </tr>
                  </thead>
                  <tbody>
                    {signals.map((s) => (
                      <tr key={s.id} className="border-b border-white/5 last:border-0">
                        <td className="py-2.5 sm:py-3 text-white font-medium">{s.ticker}</td>
                        <td className="py-2.5 sm:py-3 text-slate-400">{s.volume}</td>
                        <td className="py-2.5 sm:py-3"><StrengthMeter score={s.momentum_score} /></td>
                        <td className={`py-2.5 sm:py-3 ${DIRECTION_COLOR[s.bias] || "text-slate-300"}`}>{s.bias}</td>
                        <td className="hidden sm:table-cell py-3 text-right text-slate-500">{timeAgo(s.created_at)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          </div>
        </div>
      </motion.div>
    </motion.div>
  );
};

export default HeroDashboardMockup;
