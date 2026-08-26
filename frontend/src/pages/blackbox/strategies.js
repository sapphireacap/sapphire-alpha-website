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
// Order below is deliberate: Premium Band Strangle / Structural Retest /
// Trend Ignition / Volume Cascade lead (the currently-running new
// strategies -- see PAUSED note on the legacy three), not just appended
// at the end. Convexity Window and Gamma Backspread (the original two
// options-live strategies here) were removed entirely on 2026-08-26,
// code and production data both, per explicit instruction.
// Fields added 2026-08-04 for the redesigned public Black Box page
// (card grid + "View Strategy" modal): objective/marketLabel/tradingStyle/
// automation/status/estimatedRelease/riskManagement/brokerIntegration.
// Purely additive -- summary/methodology/internalStatus/capitalValue/
// apiPath/kind stay exactly as other consumers (StrategyDetail.jsx,
// Admin.jsx's StrategyReportAccordion) already expect them.
export const STRATEGIES = [
  {
    slug: "premium-band-strangle",
    no: "01",
    apiPath: "premium_band_strangle",
    kind: "options-live",
    optionsLive: true,
    title: "Premium Band Strangle",
    subtitle: "Rule-based short strangle, no Greeks",
    assetClass: "Index Options",
    tags: ["Rule-Based", "Short Options"],
    objective: "Sells option premium in a fixed target band and rolls mechanically on profit, loss, or premium-doubling triggers.",
    marketLabel: "Options",
    tradingStyle: "Multi-Week",
    automation: "Fully Automated",
    status: "In Validation",
    estimatedRelease: "Q4 2026",
    riskManagement: "Built-in",
    brokerIntegration: "Supported",
    summary: {
      what: "Premium Band Strangle sells a NIFTY call and put (monthly expiry) whose live premium sits closest to a fixed target band, and rolls either leg back into that band on one of three fixed triggers — a profit target, a hard loss limit, or the premium approaching double its entry value. No implied volatility, no Greeks, no chart pattern of any kind.",
      market: "NIFTY Monthly Options",
      objective: "Collect option premium systematically without needing any market view, indicator, or chart read.",
      riskProfile: "Undefined-risk, short-options — losses are managed through mechanical rolls rather than a hard stop; full mechanics disclosed below.",
      holdingPeriod: "Multi-week — positions run across most of a monthly expiry cycle, rolled as triggers fire.",
      executionStyle: "Fully systematic. Every filter and every roll trigger is disclosed in full below — nothing about this strategy's logic is hidden.",
      suitableInvestor: "Not investment advice. Currently in PAPER TRADING — no real capital is deployed. Published for research and transparency.",
    },
    methodology:
      "Premium Band Strangle selects the CE and PE strike (same monthly expiry) whose live premium sits closest to a fixed target band. Each leg is monitored independently and rolled — closed and re-sold back into the band — if its profit crosses a fixed rupee threshold, if its running loss crosses a fixed rupee threshold, or if its premium approaches double what was collected at entry. Full entry and roll rules are in the Rules panel below.",
  },
  {
    slug: "structural-retest",
    no: "02",
    apiPath: "structural_retest",
    kind: "equity-live",
    equityLive: true,
    title: "Structural Retest",
    subtitle: "Rule-based P&F pattern retest, breadth-gated",
    assetClass: "Equity (NIFTY 50)",
    tags: ["Rule-Based", "Pattern-Based"],
    objective: "Trades a Point & Figure reversal pattern only once it has been re-tested at the same level, filtered by the group's own breadth extreme.",
    marketLabel: "Equity",
    tradingStyle: "Positional",
    automation: "Fully Automated",
    status: "In Validation",
    estimatedRelease: "Q4 2026",
    riskManagement: "Built-in",
    brokerIntegration: "Supported",
    summary: {
      what: "Structural Retest looks for a Point & Figure reversal pattern (a major top/bottom or pole formation) that gets tested again at the same price zone by a later pattern of the same bias — a level defended twice is treated as a stronger signal than either pattern alone — and only trades it when the NIFTY 50 group's own breadth reading confirms the group isn't already crowded the other way.",
      market: "NIFTY 50 Constituents",
      objective: "Capture reversals at price zones that have already proven themselves once, rather than a first, unconfirmed test.",
      riskProfile: "Defined-risk — each entry carries a stop derived from the pattern's own failure level, disclosed in full below.",
      holdingPeriod: "Positional — days to a few weeks per position, reviewed daily.",
      executionStyle: "Fully systematic, daily-bar cadence. Every filter and every exit rule is disclosed in full below — nothing about this strategy's logic is hidden.",
      suitableInvestor: "Not investment advice. Currently in PAPER TRADING — no real capital is deployed. Published for research and transparency.",
    },
    methodology:
      "Structural Retest scans NIFTY 50 constituents' own Point & Figure charts for a major reversal pattern (a top/bottom formation or a pole) that has been re-tested — a later pattern of the same bias completing at the same price zone. A bullish retest is only traded when the group's breadth reading is oversold; a bearish retest only when it's overbought. The position is stopped out on the pattern's own failure level, or on an opposing reversal pattern. Full rules are in the Rules panel below.",
  },
  {
    slug: "trend-ignition",
    no: "03",
    apiPath: "trend_ignition",
    kind: "equity-live",
    equityLive: true,
    title: "Trend Ignition",
    subtitle: "Rule-based multi-filter momentum scan",
    assetClass: "Equity (NIFTY 500)",
    tags: ["Rule-Based", "Momentum"],
    objective: "Confirms a fresh momentum move with a stack of independent filters before entering — trend, strength, participation, and candle quality all have to agree.",
    marketLabel: "Equity",
    tradingStyle: "Positional",
    automation: "Fully Automated",
    status: "In Validation",
    estimatedRelease: "Q4 2026",
    riskManagement: "Built-in",
    brokerIntegration: "Supported",
    summary: {
      what: "Trend Ignition only enters when five independent conditions agree on the same day: a rising short-term trend average above its longer-term counterpart, a fresh multi-day extreme in closing price, a momentum-strength reading confirming the move, a volume spike versus the recent average, and a strong-trend reading — all on a single-candle close with real conviction behind it.",
      market: "NIFTY 500 Constituents",
      objective: "Enter fresh momentum only once trend, strength, participation, and candle quality all point the same way, filtering out weak or unconfirmed breakouts.",
      riskProfile: "Defined-risk — a hard stop is set at entry, with profit booked in stages as the position moves favorably.",
      holdingPeriod: "Positional — days to a few weeks, reviewed daily.",
      executionStyle: "Fully systematic, daily-bar cadence. Every filter and every exit rule is disclosed in full below — nothing about this strategy's logic is hidden.",
      suitableInvestor: "Not investment advice. Currently in PAPER TRADING — no real capital is deployed. Published for research and transparency.",
    },
    methodology:
      "Trend Ignition requires a rising fast moving average above a slower one, a fresh multi-day high or low in closing price, a momentum-strength reading past a fixed threshold, today's volume exceeding the recent multi-day maximum, a strong-trend reading, and a full-bodied candle in the trade's direction — all on the same day — before entering. A hard stop is set at entry and profit is booked in stages as the position runs. Full rules are in the Rules panel below.",
  },
  {
    slug: "volume-cascade",
    no: "04",
    apiPath: "volume_cascade",
    kind: "equity-live",
    equityLive: true,
    title: "Volume Cascade",
    subtitle: "Rule-based volume surge + dual breakout confirmation",
    assetClass: "Equity (NIFTY 500)",
    tags: ["Rule-Based", "Breakout"],
    objective: "Confirms an unusual volume spike with two independent breakout reads — relative strength against the index, and the stock's own price chart — before entering.",
    marketLabel: "Equity",
    tradingStyle: "Positional",
    automation: "Fully Automated",
    status: "In Validation",
    estimatedRelease: "Q4 2026",
    riskManagement: "Built-in",
    brokerIntegration: "Supported",
    summary: {
      what: "Volume Cascade triggers on an unusual volume spike with a positive close, then requires two separate confirmations before entering: a fresh breakout on the stock's relative-strength chart against NIFTY 50, and the same breakout on the stock's own price chart, with its trend average sloping in the trade's direction.",
      market: "NIFTY 500 Constituents",
      objective: "Only trade a volume spike once both relative and absolute price structure confirm it's a real breakout, not noise.",
      riskProfile: "Defined-risk — a hard stop is set at entry, with a portion of the position booked once it moves favorably.",
      holdingPeriod: "Positional — days to a few weeks, reviewed daily.",
      executionStyle: "Fully systematic, daily-bar cadence. Every filter and every exit rule is disclosed in full below — nothing about this strategy's logic is hidden.",
      suitableInvestor: "Not investment advice. Currently in PAPER TRADING — no real capital is deployed. Published for research and transparency.",
    },
    methodology:
      "Volume Cascade triggers when a stock's volume exceeds twice its trailing 10-day average on a positive close, then confirms with a fresh breakout on the ratio of the stock's price to NIFTY 50 (Point & Figure basis), and the same breakout confirmed again on the stock's own price chart with its column moving average sloping in the same direction. The position is stopped out on an opposing breakout signal or the moving average turning against it, with part of the position booked at a fixed profit multiple. Full rules are in the Rules panel below.",
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
    no: "05",
    apiPath: "prism-alpha",
    kind: "prism",
    title: "Prism Alpha",
    subtitle: "Quantitative options strategy",
    assetClass: "Options",
    internalStatus: "Operational",
    capitalValue: 500000,
    tags: ["Quantitative", "Momentum", "Adaptive"],
    objective: "Captures momentum breakouts using proprietary quantitative filters.",
    marketLabel: "Options",
    tradingStyle: "Intraday",
    automation: "Fully Automated",
    status: "In Validation",
    estimatedRelease: "Q4 2026",
    riskManagement: "Built-in",
    brokerIntegration: "Supported",
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
    no: "06",
    apiPath: "prism-alpha-2",
    kind: "prism",
    title: "Prism Alpha II",
    subtitle: "Quantitative options strategy",
    assetClass: "Options",
    internalStatus: "Calibration",
    capitalValue: 500000,
    tags: ["Quantitative", "Comparison Track"],
    objective: "Isolates the marginal edge of Prism Alpha's confirming indicator as a comparison track.",
    marketLabel: "Options",
    tradingStyle: "Intraday",
    automation: "Fully Automated",
    status: "Coming Soon",
    estimatedRelease: "Q1 2027",
    riskManagement: "Built-in",
    brokerIntegration: "Supported",
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
    no: "07",
    apiPath: "lumen-sip",
    kind: "lumen",
    title: "Lumen SIP",
    subtitle: "Signal-based ETF allocation",
    assetClass: "ETF",
    internalStatus: "Operational",
    tags: ["Systematic", "Trend-Following", "Long-Term"],
    objective: "Shifts monthly ETF contributions between invested and cash phases using a systematic trend model.",
    marketLabel: "ETF",
    tradingStyle: "Systematic",
    automation: "Fully Automated",
    status: "In Validation",
    estimatedRelease: "Q4 2026",
    riskManagement: "Built-in",
    brokerIntegration: "Supported",
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
