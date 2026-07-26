// Static registry driving both the Black Box directory page and every
// strategy detail page. `kind` selects which data-fetching/metrics adapter
// StrategyDetail.jsx uses ("prism" = intraday options trade log, "lumen" =
// daily-bar ETF allocation with server-computed XIRR/benchmark). Content
// here (status, tags, facts, summary, methodology) is editorial copy, not
// computed data — it changes when the underlying strategy's real status
// changes, not on every deploy.
export const STRATEGIES = [
  {
    slug: "prism-alpha",
    no: "01",
    apiPath: "prism-alpha",
    kind: "prism",
    title: "Prism Alpha",
    subtitle: "Quantitative options strategy",
    status: "Operational",
    capitalValue: 500000,
    facts: [
      { label: "Capital Required", value: "₹5,00,000" },
      { label: "Asset Class", value: "Options" },
      { label: "Since", value: "2026" },
    ],
    tags: ["Options", "Quantitative", "Momentum", "Adaptive"],
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
    no: "02",
    apiPath: "prism-alpha-2",
    kind: "prism",
    title: "Prism Alpha II",
    subtitle: "Quantitative options strategy",
    status: "Calibration",
    capitalValue: 500000,
    facts: [
      { label: "Capital Required", value: "₹5,00,000" },
      { label: "Asset Class", value: "Options" },
      { label: "Since", value: "2026" },
    ],
    tags: ["Options", "Quantitative", "Comparison Track"],
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
    no: "03",
    apiPath: "lumen-sip",
    kind: "lumen",
    title: "Lumen SIP",
    subtitle: "Signal-based ETF allocation",
    status: "Operational",
    facts: [
      { label: "Monthly Contribution", value: "₹5,000" },
      { label: "Asset Class", value: "ETF" },
      { label: "Since", value: "2016 (backtested)" },
    ],
    tags: ["ETF", "Systematic", "Trend-Following", "Long-Term"],
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
  "All performance figures shown — live and backtested — are for research and educational purposes only and do not constitute investment advice. Backtested results are hypothetical: they are computed by applying the strategy's rules to historical market data and do not reflect actual trading, slippage, liquidity constraints, or capital limitations. Past performance, whether live or simulated, does not guarantee future results. Sapphire Alpha Capital does not manage client capital or execute trades on behalf of any third party through this platform.";
