import { useEffect, useState } from "react";
import axios from "axios";
import { motion } from "framer-motion";
import { RefreshCw, Minus, TrendingUp, TrendingDown, Info } from "lucide-react";
import { INDEX_LABELS, isNseSessionLive } from "../AlphaTerminal";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;
const EASE = [0.16, 1, 0.3, 1];

// Scoped to this page only -- Inter for UI text, IBM Plex Mono for every
// number, per the design system given for this redesign. Neither
// overrides the site's own font-sans/font-mono tokens (Archivo /
// JetBrains Mono), which every other page keeps using unchanged.
const F_UI = "'Inter', sans-serif";
const F_MONO = "'IBM Plex Mono', monospace";

/* --------------------------------------------------------------------- */
/* Design tokens                                                          */
/* --------------------------------------------------------------------- */
const T = {
  bg: "#080F1D",
  bg2: "#0A1221",
  card: "#0D1728",
  cardElevated: "#101C2F",
  textPrimary: "#F1F5F9",
  textSecondary: "#94A3B8",
  textMuted: "#64748B",
  microLabel: "#7F93AD",
  sapphire: "#1677FF",
  sapphireBright: "#3B8CFF",
  sapphireDeep: "#0B4FB3",
  bullish: "#16C784",
  bullishBright: "#22D995",
  bullishBg: "#06271D",
  bearish: "#EF5350",
  bearishBg: "#2A1115",
  neutral: "#CBD5E1",
  neutralBg: "#182235",
  borderPrimary: "#1E3048",
  borderSecondary: "#17263A",
  borderHover: "#29415F",
};

const GLOW_SAPPHIRE = "0 0 30px rgba(22, 119, 255, 0.08)";

// One color per model state, applied uniformly across a card (monogram,
// index subtitle, bias dial, bias text, spot marker) -- Neutral is its
// own distinct tone (a light slate), not the sapphire brand accent, so a
// Neutral read never reads as "the model leans bullish-ish."
const BIAS_TONE = {
  Bullish: { color: T.bullish, bg: T.bullishBg, Icon: TrendingUp },
  Bearish: { color: T.bearish, bg: T.bearishBg, Icon: TrendingDown },
  Neutral: { color: T.neutral, bg: T.neutralBg, Icon: Minus },
};

const microLabel = { fontFamily: F_UI, fontSize: 11, fontWeight: 500, letterSpacing: "0.12em", textTransform: "uppercase", color: T.microLabel };
const mono = (size = 14, weight = 500, color = T.textPrimary) => ({ fontFamily: F_MONO, fontSize: size, fontWeight: weight, color });
const ui = (size = 14, weight = 400, color = T.textPrimary) => ({ fontFamily: F_UI, fontSize: size, fontWeight: weight, color });

const fmtNum = (v) => (v == null ? "-" : Math.round(v).toLocaleString("en-IN"));

/* --------------------------------------------------------------------- */
/* Hero                                                                   */
/* --------------------------------------------------------------------- */
// Faint abstract line/node geometry sitting behind the hero's right side --
// deliberately not a real chart of any real series, just texture that reads
// as quantitative without claiming to plot anything.
const HeroTexture = () => (
  <svg className="pointer-events-none absolute right-0 top-0 h-full w-full opacity-[0.14]" viewBox="0 0 800 260" fill="none" aria-hidden="true">
    <path d="M420 150 L520 110 L590 130 L680 70 L760 90" stroke={T.sapphireBright} strokeWidth="1" />
    <path d="M460 190 L540 170 L610 185 L700 140 L780 155" stroke={T.sapphireBright} strokeWidth="1" opacity="0.6" />
    {[[420, 150], [520, 110], [590, 130], [680, 70], [760, 90], [540, 170], [610, 185], [700, 140]].map(([cx, cy], i) => (
      <circle key={i} cx={cx} cy={cy} r="2.5" fill={T.sapphireBright} />
    ))}
    {Array.from({ length: 9 }).map((_, col) =>
      Array.from({ length: 5 }).map((_, row) => (
        <circle key={`${col}-${row}`} cx={420 + col * 42} cy={20 + row * 42} r="1" fill={T.textMuted} opacity="0.5" />
      ))
    )}
  </svg>
);

// Re-checked periodically (not just once at mount) so a tab left open
// across the market open/close boundary updates its own "Live" state
// instead of freezing whatever was true when the page first loaded.
const useSessionLive = () => {
  const [live, setLive] = useState(isNseSessionLive());
  useEffect(() => {
    const id = setInterval(() => setLive(isNseSessionLive()), 30000);
    return () => clearInterval(id);
  }, []);
  return live;
};

export const VectorHero = ({ title, description }) => {
  const sessionLive = useSessionLive();
  return (
  <div
    className="relative overflow-hidden rounded-2xl px-6 py-8 md:px-10 md:py-10"
    style={{ background: T.bg2, border: `1px solid ${T.borderPrimary}` }}
    data-testid="vector-hero"
  >
    <HeroTexture />
    <div className="relative flex flex-col lg:flex-row lg:items-start lg:justify-between gap-8">
      <div className="max-w-xl">
        <motion.p
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.5, ease: EASE }}
          className="mb-3"
          style={{ ...microLabel, color: T.sapphireBright }}
        >
          Multi-Factor Confirmation Model
        </motion.p>
        <motion.h1
          initial={{ opacity: 0, y: 14 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.6, ease: EASE, delay: 0.05 }}
          className="leading-[0.95] bg-gradient-to-r from-white to-[#3B8CFF] bg-clip-text text-transparent"
          style={{ fontFamily: F_UI, fontWeight: 700, letterSpacing: "-0.02em", fontSize: "clamp(40px, 6vw, 60px)" }}
          data-testid="vector-hero-title"
        >
          {title}
        </motion.h1>
        <motion.p
          initial={{ opacity: 0, y: 12 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.6, ease: EASE, delay: 0.1 }}
          className="mt-4 leading-relaxed"
          style={ui(15, 400, T.textSecondary)}
        >
          {description}
        </motion.p>
      </div>

      <motion.div
        initial={{ opacity: 0, y: -10 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.6, ease: EASE, delay: 0.15 }}
        className="relative shrink-0 rounded-xl px-5 py-4 max-w-xs"
        style={{ background: T.cardElevated, border: `1px solid ${T.borderPrimary}`, boxShadow: GLOW_SAPPHIRE }}
        data-testid="vector-hero-status"
      >
        <div className="flex items-start gap-3">
          <span
            className="mt-0.5 inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-lg"
            style={{ border: `1px solid ${T.sapphireDeep}`, background: "rgba(22,119,255,0.12)", color: T.sapphireBright }}
          >
            <RefreshCw size={14} />
          </span>
          <div>
            <div className="flex items-center gap-2">
              <p style={ui(14, 600, T.textPrimary)}>Model Update</p>
              <span className="inline-flex items-center gap-1" style={{ ...microLabel, color: sessionLive ? T.bullish : T.textMuted, letterSpacing: "0.08em" }}>
                <span className={`h-1.5 w-1.5 rounded-full ${sessionLive ? "animate-pulse" : ""}`} style={{ background: sessionLive ? T.bullish : T.textMuted }} />
                {sessionLive ? "Live" : "Market Closed"}
              </span>
            </div>
            <p className="mt-1 leading-relaxed" style={ui(12, 400, T.textMuted)}>
              Continuous assessment across price, volatility and options market structure.
            </p>
          </div>
        </div>
      </motion.div>
    </div>
  </div>
  );
};

/* --------------------------------------------------------------------- */
/* Directional bias dial                                                  */
/* --------------------------------------------------------------------- */
const BiasDial = ({ bias, tone }) => {
  const Icon = tone.Icon;
  return (
    <span
      className="relative inline-flex h-14 w-14 shrink-0 items-center justify-center rounded-full"
      style={{ border: `2px dashed ${tone.color}66` }}
    >
      <Icon size={20} color={tone.color} />
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
// gets an invented number, it gets an honest label and a muted zone instead.
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

  return { left, right, spotPct: pct(spot) };
};

const ThresholdSpectrum = ({ flip, spot, tone }) => {
  if (spot == null) return null;
  const { left, right, spotPct } = buildSpectrum(flip, spot);

  return (
    <div className="mt-4" data-testid="threshold-spectrum">
      <div className="relative h-1.5 rounded-full overflow-hidden" style={{ background: T.borderSecondary }}>
        <div className="absolute inset-y-0 left-0 w-1/2" style={{ background: `linear-gradient(to right, ${T.bearish}80, transparent)` }} />
        <div className="absolute inset-y-0 right-0 w-1/2" style={{ background: `linear-gradient(to left, ${T.bullish}80, transparent)` }} />
        <motion.span
          className="absolute top-1/2 h-3 w-3 -translate-y-1/2 -translate-x-1/2 rounded-full"
          style={{ backgroundColor: tone.color, border: `2px solid ${T.bg}` }}
          initial={{ left: "50%" }}
          animate={{ left: `${Math.min(96, Math.max(4, spotPct))}%` }}
          transition={{ duration: 0.6, ease: EASE }}
        />
      </div>
      <div className="mt-2.5 flex items-start justify-between gap-3">
        <div>
          <p style={{ ...microLabel, letterSpacing: "0.08em", color: `${T.bearish}CC` }}>Bearish</p>
          <p className="mt-0.5" style={mono(12, 500, T.textSecondary)}>
            {left.kind === "level" ? `< ${fmtNum(left.value)}` : left.kind === "aligned" ? "Aligned" : "Not reachable now"}
          </p>
        </div>
        <div className="text-center">
          <p style={{ ...microLabel, letterSpacing: "0.08em" }}>Neutral Zone</p>
        </div>
        <div className="text-right">
          <p style={{ ...microLabel, letterSpacing: "0.08em", color: `${T.bullish}CC` }}>Bullish</p>
          <p className="mt-0.5" style={mono(12, 500, T.textSecondary)}>
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
  const sessionLive = useSessionLive();

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
    <div
      className="h-full flex flex-col rounded-2xl overflow-hidden"
      style={{ background: T.card, border: `1px solid ${T.borderPrimary}` }}
      data-testid={`index-intelligence-card-${index}`}
    >
      {/* Header: identity + spot */}
      <div className="flex items-start justify-between gap-4 px-6 pt-6">
        <div className="flex items-center gap-3">
          <span
            className="inline-flex h-10 w-10 shrink-0 items-center justify-center rounded-full font-bold"
            style={{ border: `1px solid ${tone.color}66`, color: tone.color, fontFamily: F_MONO }}
          >
            {label[0]}
          </span>
          <div>
            <p style={{ ...ui(28, 600, T.textPrimary), letterSpacing: "-0.01em", lineHeight: 1 }}>{label}</p>
            <p className="mt-1" style={{ ...microLabel, letterSpacing: "0.1em", color: tone.color }}>
              NSE {label === "NIFTY" ? "NIFTY 50" : label}
            </p>
          </div>
        </div>
        {displaySpot != null && (
          <div className="text-right shrink-0">
            <p style={microLabel}>Spot Price</p>
            <p className="mt-0.5" style={mono(24, 600, T.textPrimary)}>{fmtNum(numericSpot)}</p>
            {liveSpot?.change && (
              <p className="mt-0.5" style={mono(12, 500, changeNegative ? T.bearish : T.bullish)}>
                {liveSpot.change} ({liveSpot.change_pct}%)
              </p>
            )}
          </div>
        )}
      </div>

      {/* Directional bias */}
      <div className="px-6 pt-6 pb-5">
        <p className="mb-3" style={microLabel}>Directional Bias</p>
        <div className="flex items-center gap-4">
          <BiasDial bias={bias} tone={tone} />
          <p style={{ fontFamily: F_UI, fontWeight: 600, fontSize: 42, letterSpacing: "-0.01em", color: tone.color }} data-testid={`vector-bias-${index}`}>
            {bias.toUpperCase()}
          </p>
        </div>
        <div
          className="mt-3 inline-flex items-center gap-1.5 rounded-full px-3 py-1"
          style={{ border: `1px solid ${T.borderPrimary}` }}
          title={s.note || undefined}
        >
          <span style={mono(11, 400, T.textSecondary)}>{BIAS_READOUT[bias] || BIAS_READOUT.Neutral}</span>
          <Info size={10} color={T.textMuted} />
        </div>
        <p className="mt-4" style={{ ...microLabel, color: T.textMuted, letterSpacing: "0.1em" }}>
          Trade Confirmation Engine
        </p>
      </div>

      {/* Model readout */}
      {(bullishLine || bearishLine) && (
        <div className="px-6 py-5" style={{ borderTop: `1px solid ${T.borderSecondary}` }}>
          <div className="space-y-1">
            {bullishLine && (
              <p style={ui(14, 400, T.textSecondary)}>
                Would need {label} at <span style={mono(14, 600, T.bullish)}>{fmtNum(s.flip.bullish.flip_level)}</span> to turn Bullish
              </p>
            )}
            {bearishLine && (
              <p style={ui(14, 400, T.textSecondary)}>
                Would need {label} at <span style={mono(14, 600, T.bearish)}>{fmtNum(s.flip.bearish.flip_level)}</span> to turn Bearish
              </p>
            )}
          </div>
          {numericSpot != null && <ThresholdSpectrum flip={s.flip} spot={numericSpot} tone={tone} />}
        </div>
      )}

      {/* Footer -- mt-auto so it always sits at the card's bottom edge even
          when the sibling card has an extra Model Readout line (e.g. one
          index reachable both ways, the other only one) */}
      <div className="mt-auto flex items-center justify-between gap-3 px-6 py-4" style={{ borderTop: `1px solid ${T.borderSecondary}` }}>
        <p style={mono(11, 400, T.textMuted)}>
          {s.updated_label ? `Last updated: ${s.updated_label}` : "Awaiting first read"}
        </p>
        <span className="inline-flex items-center gap-1.5" style={{ ...microLabel, letterSpacing: "0.08em", color: sessionLive ? T.bullish : T.textMuted }}>
          <span className={`h-1.5 w-1.5 rounded-full ${sessionLive ? "animate-pulse" : ""}`} style={{ background: sessionLive ? T.bullish : T.textMuted }} />
          {sessionLive ? "Live Data" : "Market Closed"}
        </span>
      </div>
    </div>
  );
};

