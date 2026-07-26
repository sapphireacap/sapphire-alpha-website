import {
  Compass, Activity, Radar, BarChart3, Sliders, TrendingUp, Target,
} from "lucide-react";

// Every research module shown on the Alpha Terminal directory and served at
// its own /alpha-terminal/:slug page (ModuleDetail.jsx). `kind` decides what
// ModuleDetail's Live Dashboard section renders:
//   "vector"  -> StraddleCompass (the Nifty Vector's public bias/spot read)
//   "scanner" -> MomentumTable against /terminal/stocks?scanner=<scannerKey>
//   "ewma"    -> the standalone EwmaCrossoverTool, embedded
//   "sharpe"  -> the standalone SharpeDashboardTool, embedded
export const MODULES = [
  {
    slug: "nifty-vector",
    no: "01",
    kind: "vector",
    icon: Compass,
    title: "Sapphire Nifty Vector",
    shortDescription: "Institutional market regime confirmation model.",
    category: "Market Intelligence",
    status: "Operational",
    universe: "NIFTY Index Options",
    coverage: "Weekly & Monthly Expiries",
    overview: {
      purpose: "Confirms the near-term directional regime for NIFTY before you commit to a trade.",
      whatItMeasures: "Aggregates signals across NIFTY's options market structure into a single Bullish, Bearish, or Neutral read.",
      interpret: "Use it as confirmation, not a standalone entry signal — an aligned bias supports a trade idea already in place; an opposing bias is a caution flag.",
    },
    methodology: "The Vector reads NIFTY's options market structure for directional pressure across multiple expiries and combines them into one confluence read. Exact mechanics, parameters, and decision rules are proprietary and not disclosed.",
    researchNotes: [
      { date: "2026-07-27", note: "Public output limited to bias, spot, and update time — underlying signal construction is no longer exposed on this page." },
      { date: "2026-07-27", note: "Track record reset to begin counting fresh from live data." },
      { date: "2026-07-26", note: "Extended to a 6-signal weekly + monthly confluence model, up from the original 2-signal weekly-only version." },
    ],
  },
  {
    slug: "momentum-engine",
    no: "02",
    kind: "scanner",
    scannerKey: "momentum",
    icon: Activity,
    title: "Momentum Engine",
    shortDescription: "Ranks institutional momentum across NSE.",
    category: "Screening Engine",
    status: "Operational",
    universe: "NSE Cash Market",
    coverage: "Daily, pre-market",
    overview: {
      purpose: "Surfaces the NSE-listed names showing the strongest institutional-grade momentum right now.",
      whatItMeasures: "Ranks stocks by a composite momentum score built from price action, volume, and conviction scoring.",
      interpret: "A higher score reflects stronger, more confirmed momentum — treat the list as a daily research starting point, not a buy list.",
    },
    methodology: "Combines price momentum, volume surge, and conviction scoring into a single ranked list, refreshed each session. The exact weighting and thresholds are proprietary and not disclosed.",
    researchNotes: [
      { date: "2026-07-27", note: "Sync workflow moved to a single-direction-per-day model — the leaderboard now shows exactly one confirmed read (bullish or bearish) rather than a fixed top-3/bottom-3 split." },
    ],
  },
  {
    slug: "relative-strength",
    no: "03",
    kind: "scanner",
    scannerKey: "relative_strength",
    icon: Radar,
    title: "Relative Strength Engine",
    shortDescription: "Ranks outperforming stocks.",
    category: "Screening Engine",
    status: "Calibration in Progress",
    universe: "NSE Cash Market",
    coverage: "Daily, pre-market",
    overview: {
      purpose: "Identifies names outperforming the broader market on a relative basis.",
      whatItMeasures: "Compares each stock's price performance against its peer universe across multiple lookback windows.",
      interpret: "Strength here is relative, not absolute — a stock can rank highly while still falling, simply by falling less than its peers.",
    },
    methodology: "Scores each name's price performance relative to its peer universe across multiple lookback windows. The exact universe construction and weighting are proprietary and not disclosed.",
    researchNotes: [
      { date: "2026-07-27", note: "Module registered — data feed is being calibrated before the leaderboard goes live." },
    ],
  },
  {
    slug: "sharpe-dashboard",
    no: "04",
    kind: "sharpe",
    icon: BarChart3,
    title: "Sharpe Dashboard",
    shortDescription: "Risk-adjusted stock ranking engine.",
    category: "Risk Analytics",
    status: "Operational",
    universe: "Nifty 500",
    coverage: "On demand, any lookback",
    overview: {
      purpose: "Ranks opportunities by risk-adjusted return rather than raw performance.",
      whatItMeasures: "Computes Sharpe, Sortino, and maximum drawdown across the Nifty 500 for any basket you choose, or the full ranked universe.",
      interpret: "A higher Sharpe reflects steadier, more risk-efficient returns — useful for comparing very different names on equal footing.",
    },
    methodology: "Computes Sharpe, Sortino, and maximum drawdown from each name's historical daily returns over the selected lookback window, using standard risk-adjusted return formulas.",
    researchNotes: [
      { date: "2026-07-20", note: "Module launched with support for custom baskets and full Nifty 500 ranking." },
    ],
  },
  {
    slug: "ewma-scanner",
    no: "05",
    kind: "ewma",
    icon: Sliders,
    title: "EWMA Scanner",
    shortDescription: "Trend acceleration and crossover engine.",
    category: "Signal Engine",
    status: "Operational",
    universe: "NSE / BSE / NFO / BFO",
    coverage: "On demand, any symbol",
    overview: {
      purpose: "Flags trend acceleration and crossover events using a fast/slow moving-average model.",
      whatItMeasures: "Runs an exponentially-weighted moving-average crossover, with an acceleration filter, against buy-and-hold on any symbol you choose.",
      interpret: "A fresh bullish crossover suggests emerging upward momentum; a bearish crossover suggests the opposite — always shown against its own buy-and-hold benchmark for context.",
    },
    methodology: "Runs fast/slow exponentially-weighted moving-average crossovers with an acceleration filter, backtested against buy-and-hold on the chosen symbol. Exact period parameters are configurable per run, not fixed or disclosed as a single ruleset.",
    researchNotes: [
      { date: "2026-07-18", note: "Module launched, supporting any NSE/BSE/NFO/BFO symbol." },
    ],
  },
  {
    slug: "breakout-candidates",
    no: "06",
    kind: "scanner",
    scannerKey: "breakout",
    icon: TrendingUp,
    title: "Breakout Candidates",
    shortDescription: "Detects high-conviction breakout setups.",
    category: "Screening Engine",
    status: "Calibration in Progress",
    universe: "NSE Cash Market",
    coverage: "Daily, pre-market",
    overview: {
      purpose: "Detects names approaching or clearing a key structural price level.",
      whatItMeasures: "Screens for price action nearing a defined resistance or support level alongside volume confirmation.",
      interpret: "A candidate here is a setup to watch, not a trigger — confirmation typically requires the breakout to hold with follow-through volume.",
    },
    methodology: "Flags price action clearing a defined structural level on above-average volume. The exact level construction and volume threshold are proprietary and not disclosed.",
    researchNotes: [
      { date: "2026-07-27", note: "Module registered — data feed is being calibrated before the leaderboard goes live." },
    ],
  },
  {
    slug: "positional-opportunities",
    no: "07",
    kind: "scanner",
    scannerKey: "positional",
    icon: Target,
    title: "Positional Opportunities",
    shortDescription: "Swing and positional screening engine.",
    category: "Screening Engine",
    status: "Calibration in Progress",
    universe: "NSE Cash Market",
    coverage: "Daily, pre-market",
    overview: {
      purpose: "Screens for setups suited to multi-day positional or swing holding, not intraday turnover.",
      whatItMeasures: "Looks for structural setups that develop over several sessions rather than within a single day.",
      interpret: "Positions flagged here are meant to be held and reviewed over days to weeks, not exited same-day.",
    },
    methodology: "Screens for structural setups that develop over multiple sessions rather than intraday turnover. The exact setup criteria are proprietary and not disclosed.",
    researchNotes: [
      { date: "2026-07-27", note: "Module registered — data feed is being calibrated before the leaderboard goes live." },
    ],
  },
];

export const getModule = (slug) => MODULES.find((m) => m.slug === slug) || null;
