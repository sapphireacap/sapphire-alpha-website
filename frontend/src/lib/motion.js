// Shared motion flags.
//
// The landing page is prerendered at build time (scripts/prerender.mjs) and
// the client hydrates it. Anything above the fold must render in its FINAL
// state on both the server and the hydrating client, or the first paint is
// invisible text waiting on JavaScript. SKIP_INTRO is true in exactly those
// two situations, so server and client agree and hydration does not mismatch.
export const IS_SERVER = typeof window === "undefined";

export const PRERENDERED =
  !IS_SERVER &&
  typeof document !== "undefined" &&
  document.getElementById("root")?.hasAttribute("data-prerendered") === true;

export const SKIP_INTRO = IS_SERVER || PRERENDERED;

export const EASE = [0.16, 1, 0.3, 1];
