import { useEffect, useState } from "react";
import axios from "axios";
import { motion, AnimatePresence } from "framer-motion";
import { Link } from "react-router-dom";
import { ArrowUpRight, ChevronRight, TrendingUp, TrendingDown, Minus, ExternalLink, X, Lock, Unlock, Globe, LayoutDashboard, Shield, Zap, Target } from "lucide-react";
import Navbar from "../components/site/Navbar";
import Footer from "../components/site/Footer";
import BiasBadge from "../components/site/BiasBadge";
import { MODULES } from "./alphaterminal/modules";
import CryptoDashboard from "./alphaterminal/CryptoDashboard";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;
const EASE = [0.16, 1, 0.3, 1];

const DISCLAIMER =
  "This information is intended solely for research and educational purposes and does not constitute investment advice.";

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

// NSE full-day trading holidays (equity/derivatives segment). Source: NSE holiday
// circular, cross-checked against Groww/ClearTax. Needs a fresh entry set added
// each calendar year — extend NSE_HOLIDAYS with the next year's list in advance.
const NSE_HOLIDAYS = new Set([
  // 2026
  "2026-01-26", // Republic Day
  "2026-03-03", // Holi
  "2026-03-26", // Shri Ram Navami
  "2026-03-31", // Shri Mahavir Jayanti
  "2026-04-03", // Good Friday
  "2026-04-14", // Dr. Baba Saheb Ambedkar Jayanti
  "2026-05-01", // Maharashtra Day
  "2026-05-28", // Bakri Id
  "2026-06-26", // Muharram
  "2026-09-14", // Ganesh Chaturthi
  "2026-10-02", // Mahatma Gandhi Jayanti
  "2026-10-20", // Dussehra
  "2026-11-10", // Diwali-Balipratipada
  "2026-11-24", // Prakash Gurpurb Sri Guru Nanak Dev
  "2026-12-25", // Christmas
]);

const isoDateIst = (d) => `${d.getUTCFullYear()}-${String(d.getUTCMonth() + 1).padStart(2, "0")}-${String(d.getUTCDate()).padStart(2, "0")}`;

// `d` must already be shifted to IST wall-clock time (see nowIst below) and read via getUTC* getters.
const isTradingDay = (d) => {
  const day = d.getUTCDay();
  if (day === 0 || day === 6) return false;
  return !NSE_HOLIDAYS.has(isoDateIst(d));
};

const nowIst = () => new Date(Date.now() + 5.5 * 60 * 60 * 1000);

export const getMarketUpdatedLabel = () => {
  const now = nowIst();
  const mins = now.getUTCHours() * 60 + now.getUTCMinutes();
  if (isTradingDay(now) && mins >= 9 * 60 + 40) return "Today, 09:40 AM IST";
  let cursor = new Date(now.getTime() - 24 * 60 * 60 * 1000);
  for (let i = 0; i < 14; i++) {
    if (isTradingDay(cursor)) return `${cursor.getUTCDate()} ${MONTHS[cursor.getUTCMonth()]}, 09:40 AM IST`;
    cursor = new Date(cursor.getTime() - 24 * 60 * 60 * 1000);
  }
  return "—";
};

export const isNseSessionLive = () => {
  const now = nowIst();
  if (!isTradingDay(now)) return false;
  const mins = now.getUTCHours() * 60 + now.getUTCMinutes();
  return mins >= 9 * 60 + 15 && mins <= 15 * 60 + 30;
};

// Ticks once/second so any component calling this re-renders with a fresh
// relative label — used by the Vector's live output panel and directory
// cards, both of which read signal.updated_at.
export const useElapsedLabel = (iso, { prefix = "Updated " } = {}) => {
  const [, force] = useState(0);
  useEffect(() => {
    const id = setInterval(() => force((n) => n + 1), 1000);
    return () => clearInterval(id);
  }, []);
  if (!iso) return `${prefix}—`;
  const diff = Math.max(0, Math.floor((Date.now() - new Date(iso).getTime()) / 1000));
  if (diff < 60) return `${prefix}${diff}s ago`;
  if (diff < 3600) return `${prefix}${Math.floor(diff / 60)}m ago`;
  if (diff < 86400) return `${prefix}${Math.floor(diff / 3600)}h ago`;
  return `${prefix}${Math.floor(diff / 86400)}d ago`;
};

const MOMENTUM_TREND = {
  Bullish: { Icon: TrendingUp, color: "text-emerald-400", box: "border-emerald-400/25 bg-emerald-400/10 text-emerald-300" },
  Bearish: { Icon: TrendingDown, color: "text-red-400", box: "border-red-400/25 bg-red-400/10 text-red-300" },
  Neutral: { Icon: Minus, color: "text-slate-400", box: "border-white/15 bg-white/5 text-slate-300" },
};

// Add an entry here if a ticker's symbol in our own data ever differs from
// TradingView's NSE listing symbol — empty for now, everything we've seen
// matches directly.
const TICKER_ALIASES = {};

export const openTradingViewChart = (ticker) => {
  const symbol = (TICKER_ALIASES[ticker] || ticker || "").toUpperCase().replace(/\s+/g, "");
  if (!symbol) return;
  window.open(`https://www.tradingview.com/chart/?symbol=NSE:${symbol}`, "_blank", "noopener,noreferrer");
};

export const MomentumTable = ({ rows, onRowClick, disclaimer = DISCLAIMER }) => {
  const handleClick = onRowClick || ((r) => openTradingViewChart(r.ticker));
  return (
  <div className="rounded-2xl border border-white/10 bg-[#0A0D18] overflow-hidden" data-testid="momentum-table">
    {/* Desktop / tablet table */}
    <div className="hidden md:block">
      <table className="w-full text-left">
        <thead>
          <tr className="border-b border-white/10">
            {["Ticker", "Company", "Momentum Score", "Volume", "Bias"].map((h) => (
              <th key={h} className="px-6 py-5 font-mono-ui text-[11px] uppercase tracking-[0.18em] text-slate-500 font-semibold whitespace-nowrap">
                {h}
              </th>
            ))}
            <th className="px-6 py-5 w-10">
              <span className="sr-only">Chart</span>
            </th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <motion.tr
              key={r.id}
              initial={{ opacity: 0, y: 12 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.5, ease: EASE, delay: i * 0.06 }}
              onClick={() => handleClick(r)}
              className="group border-b border-white/[0.05] last:border-0 transition-colors duration-300 hover:bg-sapphire/[0.06] cursor-pointer"
              data-testid={`momentum-row-${i}`}
            >
              <td className="px-6 py-5 whitespace-nowrap">
                <span className="inline-flex items-center gap-1.5 font-display text-lg font-extrabold text-white tracking-tight">
                  <span className="group-hover:underline">{r.ticker}</span>
                  {(() => { const { Icon, color } = MOMENTUM_TREND[r.bias] || MOMENTUM_TREND.Neutral; return <Icon size={14} className={color} />; })()}
                </span>
              </td>
              <td className="px-6 py-5 text-sm text-slate-300 whitespace-nowrap">{r.company || "—"}</td>
              <td className="px-6 py-5">
                <span className={`inline-flex items-center justify-center w-14 py-1 rounded-md border font-mono-ui text-sm font-semibold ${(MOMENTUM_TREND[r.bias] || MOMENTUM_TREND.Neutral).box}`}>
                  {r.momentum_score}
                </span>
              </td>
              <td className="px-6 py-5 font-mono-ui text-sm text-slate-300 whitespace-nowrap">{r.volume}</td>
              <td className="px-6 py-5"><BiasBadge bias={r.bias} testid={`momentum-bias-${i}`} /></td>
              <td className="px-6 py-5">
                <ExternalLink size={14} className="text-slate-500 opacity-40 group-hover:opacity-100 transition-opacity" data-testid={`momentum-chart-link-${i}`} />
              </td>
            </motion.tr>
          ))}
        </tbody>
      </table>
    </div>

    {/* Mobile stacked cards */}
    <div className="md:hidden divide-y divide-white/[0.06]">
      {rows.map((r, i) => (
        <motion.div
          key={r.id}
          initial={{ opacity: 0, y: 12 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.5, ease: EASE, delay: i * 0.06 }}
          onClick={() => handleClick(r)}
          className="p-5 cursor-pointer active:bg-sapphire/[0.06] transition-colors"
          data-testid={`momentum-card-${i}`}
        >
          <div className="flex items-center justify-between mb-3">
            <span className="inline-flex items-center gap-1.5 font-display text-xl font-extrabold text-white tracking-tight">
              {r.ticker}
              {(() => { const { Icon, color } = MOMENTUM_TREND[r.bias] || MOMENTUM_TREND.Neutral; return <Icon size={15} className={color} />; })()}
            </span>
            <span className="flex items-center gap-2">
              <BiasBadge bias={r.bias} testid={`momentum-bias-${i}`} />
              <ExternalLink size={14} className="text-slate-500 opacity-60" data-testid={`momentum-chart-link-mobile-${i}`} />
            </span>
          </div>
          <p className="text-sm text-slate-400 mb-4">{r.company || "—"}</p>
          <div className="flex items-center gap-6">
            <div>
              <p className="font-mono-ui text-[10px] uppercase tracking-[0.18em] text-slate-500 mb-1">Momentum</p>
              <span className={`inline-flex items-center justify-center w-14 py-1 rounded-md border font-mono-ui text-sm font-semibold ${(MOMENTUM_TREND[r.bias] || MOMENTUM_TREND.Neutral).box}`}>
                {r.momentum_score}
              </span>
            </div>
            <div>
              <p className="font-mono-ui text-[10px] uppercase tracking-[0.18em] text-slate-500 mb-1">Volume</p>
              <span className="font-mono-ui text-sm text-slate-300">{r.volume}</span>
            </div>
          </div>
        </motion.div>
      ))}
    </div>

    <div className="px-5 md:px-6 py-5 border-t border-white/10">
      <p className="text-xs font-light text-slate-500 leading-relaxed max-w-4xl" data-testid="momentum-disclaimer">
        {disclaimer}
      </p>
    </div>
  </div>
  );
};

export const BIAS_STYLE = {
  Bullish: { color: "text-emerald-300", ring: "border-emerald-400/30", glow: "rgba(52,211,153,0.18)", Icon: TrendingUp, dot: "bg-emerald-400" },
  Bearish: { color: "text-red-300", ring: "border-red-400/30", glow: "rgba(248,113,113,0.18)", Icon: TrendingDown, dot: "bg-red-400" },
  Neutral: { color: "text-amber-300", ring: "border-amber-400/30", glow: "rgba(245,158,11,0.18)", Icon: Minus, dot: "bg-amber-400" },
};

// Rich, live-data view of the Vector's current call — used as the Nifty
// Vector module's Live Dashboard. Deliberately does not surface anything
// about how the bias is computed (no strikes, expiries, or leg trends): the
// public signal API itself only ever returns bias/spot/note/updated_at now,
// so there is nothing to leak here even if this component tried to.
export const INDEX_LABELS = { NIFTY: "NIFTY", BANKNIFTY: "BANKNIFTY", FINNIFTY: "FINNIFTY" };

const fmtFlipLevel = (v) => (v == null ? "—" : Math.round(v).toLocaleString("en-IN"));

export const StraddleCompass = ({ signal, index = "NIFTY" }) => {
  const s = signal || {};
  const bias = s.bias || "Neutral";
  const style = BIAS_STYLE[bias] || BIAS_STYLE.Neutral;
  const { Icon } = style;
  const label = INDEX_LABELS[index] || index;

  const [liveSpot, setLiveSpot] = useState(null);
  useEffect(() => {
    setLiveSpot(null);
    const tick = () => {
      if (!isNseSessionLive()) return;
      axios.get(`${API}/terminal/spot`, { params: { index } }).then((r) => {
        if (r.data?.spot) setLiveSpot(r.data);
      }).catch(() => {});
    };
    tick();
    const id = setInterval(tick, 3000);
    return () => clearInterval(id);
  }, [index]);

  const displaySpot = liveSpot?.spot || s.spot;
  const changeNegative = liveSpot?.change?.startsWith("-");

  return (
    <div
      className={`relative rounded-xl border ${style.ring} overflow-hidden`}
      style={{ boxShadow: `0 0 40px ${style.glow} inset`, borderLeftWidth: 3 }}
      data-testid={`straddle-compass-${index}`}
    >
      <div className="flex flex-col items-center text-center gap-4 p-6 md:p-8">
        <div className="flex flex-col items-center gap-1.5">
          <p className="font-display text-3xl md:text-4xl font-extrabold text-white tracking-tight" data-testid="compass-index-name">{label}</p>
          <p className="font-mono-ui text-[10px] uppercase tracking-[0.28em] text-slate-500">Directional Bias</p>
        </div>
        <div className="flex items-center gap-4">
          <span className={`inline-flex h-12 w-12 items-center justify-center rounded-xl border ${style.ring} ${style.color}`}>
            <Icon size={26} />
          </span>
          <span className={`font-display text-4xl md:text-5xl font-black tracking-tighter ${style.color}`} data-testid="compass-bias">
            {bias.toUpperCase()}
          </span>
        </div>
        <p className="font-mono-ui text-xs uppercase tracking-[0.18em] text-slate-500">
          Trade Confirmation Engine • Not Financial Advice
        </p>
      </div>
      {displaySpot && (
        <div className="px-6 md:px-8 py-4 border-t border-white/10">
          <p className="font-mono-ui text-[11px] text-slate-500">
            {label} SPOT: <span className="text-slate-300">{displaySpot}</span>
            {liveSpot?.change && (
              <span className={`ml-1 ${changeNegative ? "text-red-400" : "text-emerald-400"}`}>
                ({liveSpot.change}, {liveSpot.change_pct}%)
              </span>
            )}
          </p>
        </div>
      )}
      {s.flip && (s.flip.bullish?.reachable || s.flip.bearish?.reachable) && (
        <div className="px-6 md:px-8 py-4 border-t border-white/10 flex flex-col gap-1.5" data-testid="compass-flip-levels">
          {s.flip.bullish?.reachable && !s.flip.bullish?.already_aligned && (
            <p className="font-mono-ui text-[11px] text-slate-400">
              Would need {label} at <span className="text-emerald-400 font-semibold">{fmtFlipLevel(s.flip.bullish.flip_level)}</span> to turn Bullish
            </p>
          )}
          {s.flip.bearish?.reachable && !s.flip.bearish?.already_aligned && (
            <p className="font-mono-ui text-[11px] text-slate-400">
              Would need {label} at <span className="text-red-400 font-semibold">{fmtFlipLevel(s.flip.bearish.flip_level)}</span> to turn Bearish
            </p>
          )}
        </div>
      )}
    </div>
  );
};

const fmtSince = (iso) => {
  if (!iso) return "—";
  const [y, m, d] = iso.split("-");
  return `${d} ${MONTHS[Number(m) - 1]} ${y}`;
};

// One small pill row selecting which of a vector module's covered indices
// to show a track record for - moved here from ModuleDetail.jsx (2026-07-28)
// since the public Historical Performance section no longer shows this
// (admin-only now); Admin.jsx's IndexTrackRecordPanel imports it from here.
export const IndexTabs = ({ indices, active, onChange }) => (
  <div className="flex items-center gap-2 mb-5" data-testid="index-tabs">
    {indices.map((idx) => (
      <button
        key={idx}
        type="button"
        onClick={() => onChange(idx)}
        className={`px-3.5 py-1.5 rounded-full font-mono-ui text-[11px] uppercase tracking-[0.1em] whitespace-nowrap border transition-colors duration-300 ${
          active === idx ? "border-sapphire-light/50 bg-sapphire/10 text-white" : "border-white/10 text-slate-500 hover:text-slate-300"
        }`}
        data-testid={`index-tab-${idx}`}
      >
        {idx}
      </button>
    ))}
  </div>
);

export const TrackRecordPanel = ({ record }) => (
  <div data-testid="track-record-panel">
    {!record ? (
      <p className="text-sm text-slate-500">Loading…</p>
    ) : record.low_data ? (
      <p className="text-sm text-slate-400 leading-relaxed max-w-md">
        Building track record since <span className="text-white">{fmtSince(record.since)}</span> —{" "}
        <span className="text-white">{record.total_readings}</span> readings so far. Check back after a few more trading sessions for a meaningful accuracy read.
      </p>
    ) : (
      <>
        <p className="text-xs text-slate-500 mb-4">
          Tracking since <span className="text-slate-300">{fmtSince(record.since)}</span> across{" "}
          <span className="text-slate-300">{record.trading_sessions}</span> sessions — {record.total_readings} readings evaluated.
        </p>
        <div className="grid grid-cols-3 gap-3">
          {record.horizons.map((h) => (
            <div key={h.minutes} className="rounded-xl border border-white/10 bg-white/[0.02] p-4 text-center">
              <p className="font-mono-ui text-[10px] uppercase tracking-[0.18em] text-slate-500 mb-1.5">{h.minutes} min</p>
              <p className="font-mono-ui text-2xl md:text-3xl font-bold text-white mb-1">{(h.accuracy * 100).toFixed(0)}%</p>
              <p className="text-[11px] text-slate-500">{h.correct}/{h.evaluated} correct</p>
            </div>
          ))}
        </div>
        <p className="text-[11px] font-light text-slate-600 mt-4">
          A call is "correct" when Nifty moved in the read direction by the time each horizon elapsed. Past accuracy doesn't guarantee future results — not investment advice.
        </p>
      </>
    )}
  </div>
);

/* ------------------------------ Directory card ------------------------------ */

// Paused modules (module.live === false, see modules.js) skip the live-data
// hook entirely (no API call) and render a locked card instead — same
// visual treatment as Black Box's "Coming Soon" cards, so a paused Alpha
// Terminal module and a not-yet-released Black Box strategy read
// consistently across the site.
const PausedDirectoryCard = ({ module, index }) => {
  const Icon = module.icon;
  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.6, ease: EASE, delay: index * 0.06 }}
    >
      <div
        className="relative block h-full rounded-2xl border border-white/10 bg-[#0A0D18] p-6 opacity-70"
        data-testid={`module-card-${module.slug}`}
      >
        <div className="flex items-start justify-between gap-3 mb-5">
          <span className="flex items-center gap-3">
            <span className="inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-lg border border-white/10 bg-white/[0.03] text-slate-500">
              <Icon size={16} />
            </span>
            <span className="font-mono-ui text-xs text-slate-500">{module.no}</span>
          </span>
        </div>
        <h3 className="font-display text-xl font-bold text-white tracking-tight mb-1.5">{module.title}</h3>
        <p className="text-sm font-light text-slate-500 mb-6 leading-relaxed">{module.shortDescription}</p>
        <div className="flex items-center justify-end gap-3 pt-4 border-t border-white/[0.06]">
          <span className="inline-flex items-center gap-1.5 font-mono-ui text-[11px] uppercase tracking-wider text-slate-500">
            <Lock size={10} /> Coming Soon
          </span>
        </div>
      </div>
    </motion.div>
  );
};

const DirectoryCard = ({ module, index, onAbout }) => {
  const Icon = module.icon;

  if (!module.live) return <PausedDirectoryCard module={module} index={index} />;

  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.6, ease: EASE, delay: index * 0.06 }}
    >
      <Link
        to={`/alpha-terminal/${module.slug}`}
        className="group block h-full rounded-2xl border border-white/10 bg-[#0A0D18] p-6 transition-all duration-300 hover:-translate-y-1 hover:border-sapphire/40 hover:bg-white/[0.02] hover:shadow-[0_0_36px_rgba(31,95,208,0.14)]"
        data-testid={`module-card-${module.slug}`}
      >
        <div className="flex items-start justify-between gap-3 mb-5">
          <span className="flex items-center gap-3">
            <span className="inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-lg border border-white/10 bg-white/[0.03] text-sapphire-light">
              <Icon size={16} />
            </span>
            <span className="font-mono-ui text-xs text-sapphire-light">{module.no}</span>
          </span>
          <button
            type="button"
            onClick={(e) => { e.preventDefault(); e.stopPropagation(); onAbout(module); }}
            className="rounded-full border border-white/15 px-3.5 py-1.5 font-mono-ui text-[11px] uppercase tracking-wider text-slate-400 whitespace-nowrap shrink-0 hover:border-sapphire-light/50 hover:text-white transition-colors"
            data-testid={`about-module-${module.slug}`}
          >
            About Module
          </button>
        </div>

        <h3 className="font-display text-xl font-bold text-white tracking-tight mb-1.5">{module.title}</h3>
        <p className="text-sm font-light text-slate-500 mb-6 leading-relaxed">{module.shortDescription}</p>

        <p className="pt-4 border-t border-white/[0.06] inline-flex items-center gap-1.5 text-xs font-medium text-sapphire-light group-hover:text-white transition-colors">
          Open Module <ArrowUpRight size={13} />
        </p>
      </Link>
    </motion.div>
  );
};

/* ------------------------------ Market selector ------------------------------ */
// Adding a future market only requires a new entry here — nothing else in
// this file branches on a specific market id.
const MARKETS = [
  { id: "india", flag: "🇮🇳", name: "Indian Markets", available: true },
  { id: "us", flag: "🇺🇸", name: "US Markets", available: false },
  { id: "forex", flag: "💱", name: "Forex", available: false },
  { id: "crypto", flag: "₿", name: "Crypto", available: true },
];

const MarketSelector = ({ active, onChange }) => (
  <motion.div
    initial={{ opacity: 0, y: 16 }}
    animate={{ opacity: 1, y: 0 }}
    transition={{ duration: 0.7, ease: EASE, delay: 0.3 }}
    className="flex justify-center mt-10"
  >
    <div
      role="tablist"
      aria-label="Select market"
      className="inline-flex flex-wrap items-center justify-center gap-1 rounded-full border border-white/10 bg-white/[0.04] backdrop-blur-xl p-1"
      data-testid="market-selector"
    >
      {MARKETS.map((m) => {
        const isActive = active === m.id;
        return (
          <button
            key={m.id}
            type="button"
            role="tab"
            aria-selected={isActive}
            onClick={() => onChange(m.id)}
            className={`relative rounded-full px-4 py-2 font-mono-ui text-[11px] md:text-[12px] uppercase tracking-wider whitespace-nowrap transition-colors duration-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sapphire-light/60 ${
              isActive ? "text-white" : "text-slate-400 hover:text-slate-200"
            }`}
            data-testid={`market-tab-${m.id}`}
          >
            {isActive && (
              <motion.span
                layoutId="market-selector-pill"
                className="absolute inset-0 rounded-full bg-sapphire -z-10"
                transition={{ duration: 0.2, ease: EASE }}
              />
            )}
            <span className="relative z-10 inline-flex items-center gap-2">
              <span aria-hidden="true">{m.flag}</span>
              {m.name}
            </span>
          </button>
        );
      })}
    </div>
  </motion.div>
);

const UnavailableMarket = ({ market }) => (
  <motion.div
    key={market.id}
    initial={{ opacity: 0 }}
    animate={{ opacity: 1 }}
    exit={{ opacity: 0 }}
    transition={{ duration: 0.25, ease: EASE }}
    className="flex flex-col items-center justify-center text-center py-20 md:py-28"
    data-testid={`market-unavailable-${market.id}`}
  >
    <span className="inline-flex h-16 w-16 items-center justify-center rounded-2xl border border-white/10 bg-white/[0.03] text-slate-500 mb-6">
      <Globe size={28} />
    </span>
    <h2 className="font-display text-2xl md:text-3xl font-bold text-white tracking-tight mb-3">
      Not Available in Your Country
    </h2>
    <p className="text-sm font-light text-slate-500 max-w-sm mb-8">
      This market is currently unavailable in your region.
    </p>
    <button
      type="button"
      disabled
      className="rounded-full border border-white/10 bg-white/[0.03] px-6 py-2.5 text-sm font-medium text-slate-500 cursor-not-allowed"
      data-testid={`market-notify-${market.id}`}
    >
      Notify Me When Available
    </button>
  </motion.div>
);

// Small popup, not a page section — triggered by a directory card's "About
// Module" badge. Deliberately the only place Overview copy (purpose/what it
// measures/how to interpret) shows up at all; the module's own detail page
// no longer has an Overview section.
const AboutModuleModal = ({ module, onClose }) => (
  <motion.div
    initial={{ opacity: 0 }}
    animate={{ opacity: 1 }}
    exit={{ opacity: 0 }}
    transition={{ duration: 0.25 }}
    className="fixed inset-0 z-50 flex items-center justify-center bg-void/80 backdrop-blur-sm px-6"
    onClick={onClose}
    data-testid="about-module-modal-overlay"
  >
    <motion.div
      initial={{ opacity: 0, y: 12, scale: 0.97 }}
      animate={{ opacity: 1, y: 0, scale: 1 }}
      exit={{ opacity: 0, y: 8, scale: 0.98 }}
      transition={{ duration: 0.25, ease: EASE }}
      onClick={(e) => e.stopPropagation()}
      className="relative w-full max-w-md rounded-2xl border border-white/10 bg-[#0A0D18] p-6 md:p-7"
      data-testid="about-module-modal"
    >
      <button
        type="button"
        onClick={onClose}
        className="absolute top-4 right-4 text-slate-500 hover:text-white transition-colors"
        data-testid="about-module-close"
      >
        <X size={18} />
      </button>
      <p className="font-mono-ui text-[10px] uppercase tracking-[0.2em] text-sapphire-light mb-2">About Module</p>
      <h3 className="font-display text-xl font-bold text-white tracking-tight mb-5">{module.title}</h3>
      <div className="space-y-4">
        <div>
          <p className="font-mono-ui text-[10px] uppercase tracking-[0.16em] text-slate-500 mb-1">Purpose</p>
          <p className="text-sm text-slate-300 leading-relaxed">{module.overview.purpose}</p>
        </div>
        <div>
          <p className="font-mono-ui text-[10px] uppercase tracking-[0.16em] text-slate-500 mb-1">What It Measures</p>
          <p className="text-sm text-slate-300 leading-relaxed">{module.overview.whatItMeasures}</p>
        </div>
        <div>
          <p className="font-mono-ui text-[10px] uppercase tracking-[0.16em] text-slate-500 mb-1">How To Interpret</p>
          <p className="text-sm text-slate-300 leading-relaxed">{module.overview.interpret}</p>
        </div>
      </div>
    </motion.div>
  </motion.div>
);

// Compact top-right info panel -- terminal-wide counterpart to each card's
// "About Module" popup. Reuses the page's own existing subtitle copy rather
// than inventing new marketing text.
const AboutTerminalPanel = ({ onClick }) => (
  <motion.button
    type="button"
    onClick={onClick}
    initial={{ opacity: 0, y: -12 }}
    animate={{ opacity: 1, y: 0 }}
    transition={{ duration: 0.7, ease: EASE, delay: 0.15 }}
    className="group flex items-center gap-4 rounded-2xl border border-white/10 bg-white/[0.03] px-5 py-4 text-left transition-colors duration-300 hover:border-sapphire-light/40 hover:bg-white/[0.05]"
    data-testid="about-terminal-panel"
  >
    <span className="inline-flex h-10 w-10 shrink-0 items-center justify-center rounded-xl border border-sapphire-light/30 bg-sapphire/15 text-sapphire-light">
      <LayoutDashboard size={18} />
    </span>
    <span>
      <span className="block font-display text-sm font-bold text-white tracking-tight">About Alpha Terminal</span>
      <span className="block text-xs font-light text-slate-500 mt-0.5">Explore how our modules give you an edge</span>
    </span>
    <ChevronRight size={16} className="text-slate-500 group-hover:text-sapphire-light transition-colors ml-2 shrink-0" />
  </motion.button>
);

const AboutTerminalModal = ({ onClose }) => (
  <motion.div
    initial={{ opacity: 0 }}
    animate={{ opacity: 1 }}
    exit={{ opacity: 0 }}
    transition={{ duration: 0.25 }}
    className="fixed inset-0 z-50 flex items-center justify-center bg-void/80 backdrop-blur-sm px-6"
    onClick={onClose}
    data-testid="about-terminal-modal-overlay"
  >
    <motion.div
      initial={{ opacity: 0, y: 12, scale: 0.97 }}
      animate={{ opacity: 1, y: 0, scale: 1 }}
      exit={{ opacity: 0, y: 8, scale: 0.98 }}
      transition={{ duration: 0.25, ease: EASE }}
      onClick={(e) => e.stopPropagation()}
      className="relative w-full max-w-md rounded-2xl border border-white/10 bg-[#0A0D18] p-6 md:p-7"
      data-testid="about-terminal-modal"
    >
      <button
        type="button"
        onClick={onClose}
        className="absolute top-4 right-4 text-slate-500 hover:text-white transition-colors"
        data-testid="about-terminal-close"
      >
        <X size={18} />
      </button>
      <p className="font-mono-ui text-[10px] uppercase tracking-[0.2em] text-sapphire-light mb-2">About Alpha Terminal</p>
      <h3 className="font-display text-xl font-bold text-white tracking-tight mb-4">Market Intelligence</h3>
      <p className="text-sm text-slate-300 leading-relaxed">
        Research modules and screening engines for disciplined investors. Each module runs its own model against
        live market data -- open one to see its current reading, or tap "About Module" on any card for what it
        measures and how to interpret it.
      </p>
    </motion.div>
  </motion.div>
);

// Bottom-of-page trust strip -- same four pillars on every market tab.
const FEATURE_STRIP = [
  { icon: Shield, title: "Data-Driven", description: "Built on robust quantitative models and real market data." },
  { icon: Zap, title: "Systematic Edge", description: "Remove emotion. Follow the data. Stay consistent." },
  { icon: Unlock, title: "Transparent", description: "No hidden black boxes. Just clear logic." },
  { icon: Target, title: "Built for Traders", description: "From intraday scalpers to swing traders. Every module serves a purpose." },
];

const FeatureStrip = () => (
  <div className="border-t border-white/[0.06] pt-10 mt-16 grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-8" data-testid="terminal-feature-strip">
    {FEATURE_STRIP.map(({ icon: Icon, title, description }) => (
      <div key={title} className="flex items-start gap-3.5">
        <span className="inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-lg border border-white/10 bg-white/[0.03] text-slate-400">
          <Icon size={16} />
        </span>
        <span>
          <span className="block text-sm font-semibold text-white">{title}</span>
          <span className="block text-xs font-light text-slate-500 mt-1 leading-relaxed">{description}</span>
        </span>
      </div>
    ))}
  </div>
);

/* --------------------------------- Directory --------------------------------- */
export default function AlphaTerminal() {
  const [aboutModule, setAboutModule] = useState(null);
  const [aboutTerminalOpen, setAboutTerminalOpen] = useState(false);
  const [activeMarket, setActiveMarket] = useState("india");
  useEffect(() => { window.scrollTo(0, 0); }, []);
  const market = MARKETS.find((m) => m.id === activeMarket) || MARKETS[0];

  return (
    <>
      <Navbar />
      <main className="relative bg-void min-h-screen">
        <section className="relative pt-28 pb-8 md:pt-32 md:pb-10" data-testid="terminal-hero">
          <div className="container-x">
            <div className="flex flex-col md:flex-row md:items-start md:justify-between gap-6">
              <div>
                <motion.div
                  initial={{ opacity: 0, y: 20 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ duration: 0.7, ease: EASE }}
                  className="flex items-center gap-4"
                >
                  <span className="inline-flex h-14 w-14 shrink-0 items-center justify-center rounded-2xl border border-sapphire-light/30 bg-sapphire/15 text-sapphire-light">
                    <LayoutDashboard size={24} />
                  </span>
                  <h1 className="font-display font-black tracking-tighter text-white text-4xl md:text-5xl leading-[0.95]">
                    Market Intelligence
                  </h1>
                </motion.div>
                <motion.p
                  initial={{ opacity: 0, y: 16 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ duration: 0.7, ease: EASE, delay: 0.1 }}
                  className="mt-4 text-sm md:text-base font-light text-slate-400 leading-relaxed max-w-lg"
                  data-testid="terminal-subtitle"
                >
                  Research modules and screening engines for disciplined investors.
                </motion.p>
              </div>
              <AboutTerminalPanel onClick={() => setAboutTerminalOpen(true)} />
            </div>
            <MarketSelector active={activeMarket} onChange={setActiveMarket} />
          </div>
        </section>

        <section className="relative pb-24 md:pb-32">
          <div className="container-x">
            <AnimatePresence mode="wait">
              {!market.available ? (
                <UnavailableMarket market={market} />
              ) : market.id === "crypto" ? (
                <motion.div
                  key={market.id}
                  initial={{ opacity: 0 }}
                  animate={{ opacity: 1 }}
                  exit={{ opacity: 0 }}
                  transition={{ duration: 0.25, ease: EASE }}
                >
                  <CryptoDashboard />
                </motion.div>
              ) : (
                <motion.div
                  key={market.id}
                  initial={{ opacity: 0 }}
                  animate={{ opacity: 1 }}
                  exit={{ opacity: 0 }}
                  transition={{ duration: 0.25, ease: EASE }}
                  className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-5"
                  data-testid="module-directory"
                >
                  {MODULES.map((m, i) => <DirectoryCard key={m.slug} module={m} index={i} onAbout={setAboutModule} />)}
                </motion.div>
              )}
            </AnimatePresence>
            {market.available && market.id !== "crypto" && <FeatureStrip />}
          </div>
        </section>
      </main>
      <Footer />
      <AnimatePresence>
        {aboutModule && <AboutModuleModal module={aboutModule} onClose={() => setAboutModule(null)} />}
        {aboutTerminalOpen && <AboutTerminalModal onClose={() => setAboutTerminalOpen(false)} />}
      </AnimatePresence>
    </>
  );
}
