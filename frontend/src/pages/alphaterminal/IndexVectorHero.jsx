import { useEffect, useState } from "react";
import axios from "axios";
import { motion } from "framer-motion";
import { RefreshCw, Minus, TrendingUp, TrendingDown, Info, Layers, Shield, Zap, Target } from "lucide-react";
import { INDEX_LABELS, isNseSessionLive } from "../AlphaTerminal";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;
const EASE = [0.16, 1, 0.3, 1];

/* --------------------------------------------------------------------- */
/* Shared tokens                                                          */
/* --------------------------------------------------------------------- */
// One color per model state, applied uniformly across a card (monogram,
// index subtitle, bias dial, bias text, spot marker) -- the card's color
// is the model's OWN current read, not a fixed identity per index. Same
// three-state convention already used elsewhere on the site (see
// AlphaTerminal.jsx's BIAS_STYLE): amber for Neutral, emerald for
// Bullish, red for Bearish.
const BIAS_TONE = {
  Bullish: { text: "text-emerald-400", ring: "border-emerald-400/40", bar: "#34D399", Icon: TrendingUp },
  Bearish: { text: "text-red-400", ring: "border-red-400/40", bar: "#F87171", Icon: TrendingDown },
  Neutral: { text: "text-amber-300", ring: "border-amber-300/40", bar: "#FCD34D", Icon: Minus },
};

const fmtNum = (v) => (v == null ? "—" : Math.round(v).toLocaleString("en-IN"));

/* --------------------------------------------------------------------- */
/* Hero                                                                   */
/* --------------------------------------------------------------------- */
// Faint abstract line/node geometry sitting behind the hero's right side --
// deliberately not a real chart of any real series, just texture that reads
// as "quantitative" without claiming to plot anything.
const HeroTexture = () => (
  <svg
    className="pointer-events-none absolute right-0 top-0 h-full w-full opacity-[0.16]"
    viewBox="0 0 800 260"
    fill="none"
    aria-hidden="true"
  >
    <path d="M420 150 L520 110 L590 130 L680 70 L760 90" stroke="#437EEB" strokeWidth="1" />
    <path d="M460 190 L540 170 L610 185 L700 140 L780 155" stroke="#437EEB" strokeWidth="1" opacity="0.6" />
    {[[420, 150], [520, 110], [590, 130], [680, 70], [760, 90], [540, 170], [610, 185], [700, 140]].map(([cx, cy], i) => (
      <circle key={i} cx={cx} cy={cy} r="2.5" fill="#437EEB" />
    ))}
    {Array.from({ length: 9 }).map((_, col) =>
      Array.from({ length: 5 }).map((_, row) => (
        <circle key={`${col}-${row}`} cx={420 + col * 42} cy={20 + row * 42} r="1" fill="#7C93B8" opacity="0.5" />
      ))
    )}
  </svg>
);

export const VectorHero = ({ title, description }) => (
  <div className="relative overflow-hidden rounded-2xl border border-white/10 bg-[#080C16] px-6 py-8 md:px-10 md:py-10" data-testid="vector-hero">
    <HeroTexture />
    <div className="relative flex flex-col lg:flex-row lg:items-start lg:justify-between gap-8">
      <div className="max-w-xl">
        <motion.p
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.5, ease: EASE }}
          className="font-mono-ui text-[11px] uppercase tracking-[0.24em] text-sapphire-light mb-3"
        >
          Multi-Factor Confirmation Model
        </motion.p>
        <motion.h1
          initial={{ opacity: 0, y: 14 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.6, ease: EASE, delay: 0.05 }}
          className="font-sans font-black tracking-tight text-5xl md:text-6xl leading-[0.95] bg-gradient-to-r from-white to-sapphire-light bg-clip-text text-transparent"
          data-testid="vector-hero-title"
        >
          {title}
        </motion.h1>
        <motion.p
          initial={{ opacity: 0, y: 12 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.6, ease: EASE, delay: 0.1 }}
          className="mt-4 text-sm md:text-base text-slate-400 font-light leading-relaxed"
        >
          {description}
          <br />
          Unbiased. Systematic. Data-driven.
        </motion.p>
      </div>

      <motion.div
        initial={{ opacity: 0, y: -10 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.6, ease: EASE, delay: 0.15 }}
        className="relative shrink-0 rounded-xl border border-white/10 bg-white/[0.03] px-5 py-4 max-w-xs"
        data-testid="vector-hero-status"
      >
        <div className="flex items-start gap-3">
          <span className="mt-0.5 inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-lg border border-sapphire-light/30 bg-sapphire/15 text-sapphire-light">
            <RefreshCw size={14} />
          </span>
          <div>
            <div className="flex items-center gap-2">
              <p className="text-sm font-semibold text-white">Model Update</p>
              <span className="inline-flex items-center gap-1 font-mono-ui text-[10px] uppercase tracking-wider text-emerald-400">
                <span className="h-1.5 w-1.5 rounded-full bg-emerald-400 animate-pulse" /> Live
              </span>
            </div>
            <p className="text-xs font-light text-slate-500 leading-relaxed mt-1">
              Continuous assessment across price, volatility and options market structure.
            </p>
          </div>
        </div>
      </motion.div>
    </div>
  </div>
);

/* --------------------------------------------------------------------- */
/* Directional bias dial                                                  */
/* --------------------------------------------------------------------- */
const BiasDial = ({ bias, tone }) => {
  const Icon = bias === "Bullish" ? TrendingUp : bias === "Bearish" ? TrendingDown : Minus;
  return (
    <span className={`relative inline-flex h-14 w-14 shrink-0 items-center justify-center rounded-full border-2 border-dashed ${tone.ring}`}>
      <Icon size={20} className={tone.text} />
    </span>
  );
};

const BIAS_READOUT = {
  Bullish: "Directional Edge Confirmed",
  Bearish: "Directional Edge Confirmed",
  Neutral: "No Clear Directional Edge",
};

/* --------------------------------------------------------------------- */
/* Threshold spectrum                                                     */
/* --------------------------------------------------------------------- */
// Builds the bar's numeric domain and per-side state from ONLY what the
// model actually returned -- an unreachable or already-aligned side never
// gets a invented number, it gets an honest label and a muted zone instead.
const buildSpectrum = (flip, spot) => {
  const bearish = flip?.bearish;
  const bullish = flip?.bullish;

  const side = (leg) => {
    if (!leg) return { kind: "unknown" };
    if (leg.already_aligned) return { kind: "aligned" };
    if (leg.reachable && leg.flip_level != null) return { kind: "level", value: leg.flip_level };
    return { kind: "unreachable" };
  };

  const left = side(bearish);
  const right = side(bullish);

  // Fixed visual margin used whenever a side has no real number to anchor
  // to -- purely a layout fallback, never rendered as a price.
  const pad = spot * 0.012;
  const leftVal = left.kind === "level" ? Math.min(left.value, spot) : spot - pad;
  const rightVal = right.kind === "level" ? Math.max(right.value, spot) : spot + pad;
  const span = Math.max(rightVal - leftVal, 1);
  const domainLo = leftVal - span * 0.08;
  const domainHi = rightVal + span * 0.08;
  const pct = (v) => ((v - domainLo) / (domainHi - domainLo)) * 100;

  return { left, right, spotPct: pct(spot), leftPct: pct(leftVal), rightPct: pct(rightVal) };
};

const ThresholdSpectrum = ({ flip, spot, tone }) => {
  if (spot == null) return null;
  const { left, right, spotPct } = buildSpectrum(flip, spot);

  return (
    <div className="mt-4" data-testid="threshold-spectrum">
      <div className="relative h-1.5 rounded-full overflow-hidden bg-white/[0.06]">
        <div className="absolute inset-y-0 left-0 w-1/2 bg-gradient-to-r from-red-500/50 to-transparent" />
        <div className="absolute inset-y-0 right-0 w-1/2 bg-gradient-to-l from-emerald-500/50 to-transparent" />
        <motion.span
          className="absolute top-1/2 h-3 w-3 -translate-y-1/2 -translate-x-1/2 rounded-full border-2 border-void"
          style={{ backgroundColor: tone.bar }}
          initial={{ left: "50%" }}
          animate={{ left: `${Math.min(96, Math.max(4, spotPct))}%` }}
          transition={{ duration: 0.6, ease: EASE }}
        />
      </div>
      <div className="mt-2.5 flex items-start justify-between gap-3 font-mono-ui text-[10px] uppercase tracking-wider">
        <div>
          <p className="text-red-400/80">Bearish</p>
          <p className="text-slate-300 normal-case tracking-normal mt-0.5">
            {left.kind === "level" ? `< ${fmtNum(left.value)}` : left.kind === "aligned" ? "Aligned" : "Not reachable now"}
          </p>
        </div>
        <div className="text-center">
          <p className="text-slate-500">Neutral Zone</p>
        </div>
        <div className="text-right">
          <p className="text-emerald-400/80">Bullish</p>
          <p className="text-slate-300 normal-case tracking-normal mt-0.5">
            {right.kind === "level" ? `> ${fmtNum(right.value)}` : right.kind === "aligned" ? "Aligned" : "Not reachable now"}
          </p>
        </div>
      </div>
    </div>
  );
};

/* --------------------------------------------------------------------- */
/* Index intelligence card                                                */
/* --------------------------------------------------------------------- */
export const IndexIntelligenceCard = ({ signal, index }) => {
  const s = signal || {};
  const bias = s.bias || "Neutral";
  const tone = BIAS_TONE[bias] || BIAS_TONE.Neutral;
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

  const displaySpot = liveSpot?.spot ?? s.spot;
  const numericSpot = typeof displaySpot === "string" ? Number(displaySpot.replace(/,/g, "")) : displaySpot;
  const changeNegative = liveSpot?.change?.startsWith("-");

  const bullishLine = s.flip?.bullish?.reachable && !s.flip.bullish.already_aligned && s.flip.bullish.flip_level != null;
  const bearishLine = s.flip?.bearish?.reachable && !s.flip.bearish.already_aligned && s.flip.bearish.flip_level != null;

  return (
    <div className="rounded-2xl border border-white/10 bg-[#0A0D18] overflow-hidden" data-testid={`index-intelligence-card-${index}`}>
      {/* Header: identity + spot */}
      <div className="flex items-start justify-between gap-4 px-6 pt-6">
        <div className="flex items-center gap-3">
          <span className={`inline-flex h-10 w-10 shrink-0 items-center justify-center rounded-full border ${tone.ring} ${tone.text} font-mono-ui font-bold`}>
            {label[0]}
          </span>
          <div>
            <p className="text-xl font-black text-white tracking-tight leading-none">{label}</p>
            <p className={`font-mono-ui text-[10px] uppercase tracking-[0.18em] mt-1 ${tone.text}`}>
              NSE {label === "NIFTY" ? "NIFTY 50" : label}
            </p>
          </div>
        </div>
        {displaySpot != null && (
          <div className="text-right shrink-0">
            <p className="font-mono-ui text-[10px] uppercase tracking-[0.18em] text-slate-500">Spot Price</p>
            <p className="font-mono-ui text-xl font-bold text-white mt-0.5">{fmtNum(numericSpot)}</p>
            {liveSpot?.change && (
              <p className={`font-mono-ui text-xs mt-0.5 ${changeNegative ? "text-red-400" : "text-emerald-400"}`}>
                {liveSpot.change} ({liveSpot.change_pct}%)
              </p>
            )}
          </div>
        )}
      </div>

      {/* Directional bias */}
      <div className="px-6 pt-6 pb-5">
        <p className="font-mono-ui text-[10px] uppercase tracking-[0.24em] text-slate-500 mb-3">Directional Bias</p>
        <div className="flex items-center gap-4">
          <BiasDial bias={bias} tone={tone} />
          <p className={`font-sans font-black text-4xl tracking-tight ${tone.text}`} data-testid={`vector-bias-${index}`}>
            {bias.toUpperCase()}
          </p>
        </div>
        <div className="mt-3 inline-flex items-center gap-1.5 rounded-full border border-white/10 px-3 py-1 font-mono-ui text-[10px] text-slate-400" title={s.note || undefined}>
          {BIAS_READOUT[bias] || BIAS_READOUT.Neutral}
          <Info size={10} className="text-slate-600" />
        </div>
        <p className="font-mono-ui text-[10px] uppercase tracking-[0.18em] text-slate-600 mt-4">
          Trade Confirmation Engine &middot; Not Financial Advice
        </p>
      </div>

      {/* Model readout */}
      {(bullishLine || bearishLine) && (
        <div className="px-6 py-5 border-t border-white/10">
          <p className="font-mono-ui text-[10px] uppercase tracking-[0.24em] text-slate-500 mb-2">Model Readout</p>
          <div className="space-y-1">
            {bullishLine && (
              <p className="text-sm text-slate-300">
                Would need {label} at <span className="text-emerald-400 font-semibold font-mono-ui">{fmtNum(s.flip.bullish.flip_level)}</span> to turn Bullish
              </p>
            )}
            {bearishLine && (
              <p className="text-sm text-slate-300">
                Would need {label} at <span className="text-red-400 font-semibold font-mono-ui">{fmtNum(s.flip.bearish.flip_level)}</span> to turn Bearish
              </p>
            )}
          </div>
          {numericSpot != null && <ThresholdSpectrum flip={s.flip} spot={numericSpot} tone={tone} />}
        </div>
      )}

      {/* Footer */}
      <div className="flex items-center justify-between gap-3 px-6 py-4 border-t border-white/10">
        <p className="font-mono-ui text-[10px] text-slate-600">
          {s.updated_label ? `Last updated: ${s.updated_label}` : "Awaiting first read"}
        </p>
        <span className="inline-flex items-center gap-1.5 font-mono-ui text-[10px] uppercase tracking-wider text-emerald-400">
          <span className="h-1.5 w-1.5 rounded-full bg-emerald-400 animate-pulse" /> Live Data
        </span>
      </div>
    </div>
  );
};

/* --------------------------------------------------------------------- */
/* Feature strip                                                          */
/* --------------------------------------------------------------------- */
const FEATURES = [
  { icon: Layers, title: "Multi-Factor Engine", description: "Price, momentum, volatility, open interest and options market structure." },
  { icon: Shield, title: "Unbiased Framework", description: "No predictions. Only probability and confirmation conditions." },
  { icon: Zap, title: "Continuous Processing", description: "Live pricing refreshed throughout the trading session." },
  { icon: Target, title: "Built for Traders", description: "Confirmation for active, disciplined market participants." },
];

export const IntelligenceFeatureStrip = () => (
  <div className="mt-6 rounded-2xl border border-white/10 bg-[#0A0D18] px-6 py-6 grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-6" data-testid="vector-feature-strip">
    {FEATURES.map(({ icon: Icon, title, description }) => (
      <div key={title} className="flex items-start gap-3">
        <span className="inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-lg border border-white/10 bg-white/[0.03] text-sapphire-light">
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
