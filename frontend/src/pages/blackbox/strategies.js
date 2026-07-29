// Static registry for the Black Box strategies. Two very different
// audiences read this file:
//   - The public directory (BlackBox.jsx) and info page (StrategyDetail.jsx)
//     only ever use slug/no/title/subtitle/assetClass/tags/summary/
//     methodology — no capital figures, no real operational status. Every
//     card publicly shows "Coming Soon" regardless of `internalStatus`.
//   - The admin-only report (AdminStrategyReport.jsx, rendered inside
//     Admin.jsx's BlackBoxPanel) additionally uses apiPath/kind/
//     capitalValue/internalStatus to fetch and compute real performance.
// `capitalValue` is an internal computation input (the % base for Net
// Return/CAGR), not something rendered to the public — don't add a public
// "Capital Required" field back without checking this is still true.
// Order below is deliberate: Convexity Window / Gamma Backspread lead
// (they're the only strategies currently running -- see PAUSED note on the
// legacy three), not just appended at the end.
export const STRATEGIES = [
  {
    slug: "convexity-window",
    no: "01",
    apiPath: "convexity_window",
    kind: "options-live",
    optionsLive: true,
    title: "Convexity Window",
    subtitle: "Rule-based NIFTY / BANK NIFTY options buying",
    assetClass: "Index Options",
    tags: ["Rule-Based", "Long Options", "Paper Trading"],
    summary: {
      what: "Convexity Window buys a single near-the-money NIFTY or BANK NIFTY option only when a set of volatility and price filters suggest convexity is cheap relative to the underlying's recent behavior — never on discretion.",
      market: "NIFTY & BANK NIFTY Weekly Options",
      objective: "Capture short, sharp directional moves by paying for convexity only when it looks statistically underpriced.",
      riskProfile: "Defined-risk, long-options only — the maximum loss on any trade is capped at the premium paid, with a hard stop-loss and a Greeks-based exit besides.",
      holdingPeriod: "Intraday — every position is opened and closed within the same trading session (hard time stop 15:15 IST).",
      executionStyle: "Fully systematic. Every filter and every exit rule is disclosed in full below — nothing about this strategy's logic is hidden.",
      suitableInvestor: "Not investment advice. Currently in PAPER TRADING — no real capital is deployed. Published for research and transparency.",
    },
    methodology:
      "Convexity Window computes implied volatility, Delta, Gamma, Theta and Vega itself from live option prices (not broker-supplied Greeks), and only enters a long call or put when: implied volatility sits meaningfully below 20-day realized volatility, the option's own breakeven move is smaller than the underlying's typical daily range, and price is trading on the same side of both the prior close and a 20-period intraday average. Full entry and exit rules are in the Rules panel below.",
  },
  {
    slug: "gamma-backspread",
    no: "02",
    apiPath: "gamma_backspread",
    kind: "options-live",
    optionsLive: true,
    title: "Gamma Backspread",
    subtitle: "Rule-based near-zero-theta options structure",
    assetClass: "Index Options",
    tags: ["Rule-Based", "Options Structure", "Paper Trading"],
    summary: {
      what: "Gamma Backspread sells one at-the-money option and buys two further out-of-the-money options of the same type and expiry, sized so the package carries close to zero time decay while staying net long Gamma — entered only when implied volatility is cheap on its own trailing history.",
      market: "NIFTY & BANK NIFTY Options",
      objective: "Hold long convexity for longer than a single-option trade can (5–12 days to expiry) without theta working hard against the position.",
      riskProfile: "Defined-risk on the long legs; the structure's overall risk is bounded by construction, not unlimited — full mechanics disclosed below.",
      holdingPeriod: "Multi-day — positions are typically held several sessions, exited by rule (target/stop, theta drift, or 2 days-to-expiry, whichever comes first).",
      executionStyle: "Fully systematic. Every filter and every exit rule is disclosed in full below — nothing about this strategy's logic is hidden.",
      suitableInvestor: "Not investment advice. Currently in PAPER TRADING — no real capital is deployed. Published for research and transparency.",
    },
    methodology:
      "Gamma Backspread computes implied volatility and Greeks itself from live option prices (not broker-supplied Greeks). It only enters when the at-the-money option's implied volatility sits in the cheapest third of its own trailing history, and only if an out-of-the-money strike exists that brings the package's net time decay close to zero while keeping Gamma and Vega positive. Full entry and exit rules are in the Rules panel below.",
  },
  // PAUSED (2026-07-29, to cut backend memory/load): backtest, live
  // evaluation, and the admin panel for these three are all disabled on
  // the backend (see server.py's DISABLED_FEATURES) -- nothing deleted,
  // just stopped. They already showed "Coming Soon" with no real data on
  // the public site before this (see the module docstring below), so the
  // only visible change is the admin panel now shows a paused notice too
  // instead of live buttons (see Admin.jsx's BlackBoxPanel).
  {
    slug: "prism-alpha",
    no: "03",
    apiPath: "prism-alpha",
    kind: "prism",
    title: "Prism Alpha",
    subtitle: "Quantitative options strategy",
    assetClass: "Options",
    internalStatus: "Operational",
    capitalValue: 500000,
    tags: ["Quantitative", "Momentum", "Adaptive"],
    summary: {
      what: "Prism Alpha trades NIFTY weekly at-the-money options, using an internally developed pattern-recognition engine to time entries and exits within the session.",
      market: "NIFTY Weekly Options (NFO)",
      objective: "Capture short-duration directional moves in the underlying through long CE/PE positions.",
      riskProfile: "Defined-risk, long-options only — the maximum loss on any trade is capped at the premium paid.",
      holdingPeriod: "Intraday — every position is opened and closed within the same trading session.",
      executionStyle: "Fully systematic. Entries, exits, and stop conditions are signal-driven and re-evaluated continuously through the session.",
      suitableInvestor: "Investors seeking short-duration, defined-risk exposure to intraday NIFTY volatility.",
    },
    methodology:
      "Prism Alpha is a quantitative options strategy that dynamically adjusts exposure according to internally developed market-state models. Entries and exits are fully systematic and re-evaluated continuously through the trading session. The underlying pattern-recognition logic, parameters, and decision rules are proprietary and not disclosed.",
  },
  {
    slug: "prism-alpha-2",
    no: "04",
    apiPath: "prism-alpha-2",
    kind: "prism",
    title: "Prism Alpha II",
    subtitle: "Quantitative options strategy",
    assetClass: "Options",
    internalStatus: "Calibration",
    capitalValue: 500000,
    tags: ["Quantitative", "Comparison Track"],
    summary: {
      what: "Prism Alpha II runs the same core options engine as Prism Alpha without its confirming indicator gate, kept as an internal comparison track while its standalone edge is validated.",
      market: "NIFTY Weekly Options (NFO)",
      objective: "Isolate the marginal value of Prism Alpha's confirming indicator by tracking the ungated variant side by side.",
      riskProfile: "Defined-risk, long-options only — the maximum loss on any trade is capped at the premium paid.",
      holdingPeriod: "Intraday — every position is opened and closed within the same trading session.",
      executionStyle: "Fully systematic, same execution engine as Prism Alpha with one confirming condition removed.",
      suitableInvestor: "Not yet suitable for allocation — this track exists to validate the strategy internally, not for external use.",
    },
    methodology:
      "Prism Alpha II is a comparison variant of Prism Alpha, evaluated in parallel to measure the marginal contribution of one confirming condition in the primary strategy's decision engine. The underlying pattern-recognition logic, parameters, and decision rules are proprietary and not disclosed.",
  },
  {
    slug: "lumen-sip",
    no: "05",
    apiPath: "lumen-sip",
    kind: "lumen",
    title: "Lumen SIP",
    subtitle: "Signal-based ETF allocation",
    assetClass: "ETF",
    internalStatus: "Operational",
    tags: ["Systematic", "Trend-Following", "Long-Term"],
    summary: {
      what: "Lumen SIP allocates a fixed monthly contribution between NIFTYBEES and GOLDBEES, shifting each instrument between an invested and cash phase using an internally developed trend model.",
      market: "NIFTYBEES & GOLDBEES (NSE ETFs)",
      objective: "Improve on a plain monthly SIP by staying invested during favorable trend regimes and holding cash during unfavorable ones.",
      riskProfile: "Long-only, no leverage — capital not currently deployed is held as cash, not at risk.",
      holdingPeriod: "Multi-week to multi-month per phase, reviewed daily.",
      executionStyle: "Fully systematic, daily-bar cadence — no intraday monitoring required.",
      suitableInvestor: "Investors building a long-term, low-maintenance systematic allocation across Indian equity and gold ETFs.",
    },
    methodology:
      "Lumen SIP is a signal-based ETF allocation framework that shifts monthly contributions between an invested and cash phase using an internally developed trend model, built on publicly available research. The specific signal construction and parameters are proprietary and not disclosed.",
  },
];

export const getStrategy = (slug) => STRATEGIES.find((s) => s.slug === slug) || null;

export const RISK_DISCLOSURE =
  "All performance figures — live and backtested — are for research and educational purposes only and do not constitute investment advice. Backtested results are hypothetical: they are computed by applying a strategy's rules to historical market data and do not reflect actual trading, slippage, liquidity constraints, or capital limitations. Past performance, whether live or simulated, does not guarantee future results. Sapphire Alpha Capital does not manage client capital or execute trades on behalf of any third party through this platform.";
