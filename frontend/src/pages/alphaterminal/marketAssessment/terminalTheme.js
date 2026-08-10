// Shared terminal theme for Market Assessment's Bloomberg/terminal-style
// redesign. Color tokens live here (not hardcoded per component) so the
// same palette can be reused if other sections (Alpha Terminal, Black
// Box) get terminal-ified later -- see terminal.css for the CSS custom
// properties these names resolve to, and the shared panel/border/flash
// styles built on top of them.
export const TERM = {
  amber: "var(--term-amber)",
  cyan: "var(--term-cyan)",
  green: "var(--term-green)",
  red: "var(--term-red)",
  grey: "var(--term-grey)",
  text: "var(--term-text)",
};

// Bias/sign -> color, the one mapping every panel needs.
export const toneColor = (v) => (v == null ? TERM.grey : v > 0 ? TERM.green : v < 0 ? TERM.red : TERM.grey);
export const toneClass = (v) => (v == null ? "term-grey" : v > 0 ? "term-green" : v < 0 ? "term-red" : "term-grey");

// Exitline's own bias vocabulary (Long/Short/Neutral) mapped to this
// panel's Bullish/Bearish/Neutral display labels -- a presentational
// relabel only, the underlying zone/bias value from the API is untouched.
export const biasLabel = (bias) => (bias === "Long" ? "BULLISH" : bias === "Short" ? "BEARISH" : "NEUTRAL");
export const biasClass = (bias) => (bias === "Long" ? "term-green" : bias === "Short" ? "term-red" : "term-grey");
