// Shared design tokens for the quant-terminal redesign, first built for
// Index Vector (IndexVectorHero.jsx) and reused as-is for Exitline so the
// two modules read as one system. Scoped to these pages only -- neither
// the font choices nor the hex palette touch the site's own
// font-sans/font-mono tokens or any other module's styling.
export const F_UI = "'Inter', sans-serif";
export const F_MONO = "'IBM Plex Mono', monospace";

export const T = {
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

export const GLOW_SAPPHIRE = "0 0 30px rgba(22, 119, 255, 0.08)";
export const GLOW_BULLISH = "0 0 30px rgba(22, 199, 132, 0.06)";

export const microLabel = { fontFamily: F_UI, fontSize: 11, fontWeight: 500, letterSpacing: "0.12em", textTransform: "uppercase", color: T.microLabel };
export const mono = (size = 14, weight = 500, color = T.textPrimary) => ({ fontFamily: F_MONO, fontSize: size, fontWeight: weight, color });
export const ui = (size = 14, weight = 400, color = T.textPrimary) => ({ fontFamily: F_UI, fontSize: size, fontWeight: weight, color });
