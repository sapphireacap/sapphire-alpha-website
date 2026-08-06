import {
  Compass, Crosshair, Activity, Radar, BarChart3, Sliders, TrendingUp, Target, Gauge, GitBranch, LayoutDashboard,
} from "lucide-react";

// Every research module shown on the Alpha Terminal directory and served at
// its own /alpha-terminal/:slug page (ModuleDetail.jsx). `kind` decides what
// ModuleDetail's Current Reading section renders:
//   "vector"    -> one StraddleCompass per covered index (see indices below)
//                  — the Index Vector's public bias/spot read, per index
//   "scanner"   -> MomentumTable against /terminal/stocks?scanner=<scannerKey>
//   "ewma"      -> the standalone EwmaCrossoverTool, embedded
//   "sharpe"    -> the standalone SharpeDashboardTool, embedded
//   "exitline"  -> the standalone ExitlineTool, embedded (segment -> scrip
//                  -> level ladder + SL/TP)
// `live: false` modules are paused (2026-07-29) to cut backend memory/load
// while the Render free-tier instance keeps crash-restarting on its memory
// limit -- their pages show a "Coming Soon" placeholder and make no API
// calls at all, instead of their normal dashboard. Nothing about the
// module's own data or backend code is touched; flip the field back to
// `true` to fully restore. Index Vector, Exitline, and Momentum Leaders
// stay live throughout -- every other module is explicitly `live: false`
// below (set on each one, not defaulted, so it's never ambiguous).
export const MODULES = [
  {
    slug: "index-vector",
    no: "01",
    kind: "vector",
    live: true,
    icon: Compass,
    title: "Index Vector",
    shortDescription: "Market regime confirmation model.",
    // Displayed inside the module page, one compass per index, in this
    // order (2-1 formation on the Current Reading grid — see ModuleDetail.jsx).
    // Same P&F box%/reversal parameters and same all-legs-must-agree
    // confluence rule for every index — only the underlying contracts
    // differ. NIFTY still lists real weekly-cadence contracts; BANKNIFTY/
    // FINNIFTY are monthly-only (confirmed live against Definedge's master
    // data), so those two skip the weekly leg entirely rather than reading
    // a fake one — see definedge_service.py's INDEX_CONFIG chart_mode for
    // the backend side of this.
    indices: ["NIFTY", "BANKNIFTY", "FINNIFTY"],
    overview: {
      purpose: "Confirms the near-term directional regime for NIFTY, BANKNIFTY, and FINNIFTY before you commit to a trade.",
      whatItMeasures: "Aggregates signals across each index's options market structure into a single Bullish, Bearish, or Neutral read.",
      interpret: "Use it as confirmation, not a standalone entry signal — an aligned bias supports a trade idea already in place; an opposing bias is a caution flag.",
    },
  },
  {
    slug: "exitline",
    no: "02",
    kind: "exitline",
    live: true,
    icon: Crosshair,
    title: "Intraday Exitline",
    shortDescription: "Intraday levels with a suggested SL and TP.",
    overview: {
      purpose: "Turns yesterday's high/low/close into an intraday level ladder against the live price, with a rule-based stop-loss and take-profit.",
      whatItMeasures: "Classifies the current price into a mean-reversion Trading Zone (S3–R3) or a trend-day Breakout Zone (beyond R4/S4), and derives SL/TP from that read.",
      interpret: "Near R3/S3, treat it as a mean-reversion trigger with a fixed target; beyond R4/S4, treat it as a trend day — trail the stop, no fixed target.",
    },
  },
  {
    slug: "momentum-engine",
    no: "03",
    kind: "scanner",
    live: true,
    scannerKey: "momentum",
    icon: Activity,
    title: "Intraday Momentum Leaders",
    shortDescription: "Ranks momentum across NSE.",
    overview: {
      purpose: "Surfaces the NSE-listed names showing the strongest momentum right now.",
      whatItMeasures: "Ranks stocks by a composite momentum score built from price action, volume, and conviction scoring.",
      interpret: "A higher score reflects stronger, more confirmed momentum — treat the list as a daily research starting point, not a buy list.",
    },
  },
  {
    slug: "swing-picks",
    no: "04",
    kind: "scanner",
    live: false,
    scannerKey: "swing_picks",
    icon: Target,
    title: "Swing Picks",
    shortDescription: "Multi-day swing picks with a buy-at level.",
    overview: {
      purpose: "Surfaces multi-day swing setups to hold over several sessions, not intraday turnover.",
      whatItMeasures: "Screens for structural setups that develop over days to weeks, each with a defined buy-at level.",
      interpret: "Picks here are meant to be held and reviewed over days to weeks, not exited same-day — the buy-at level is the reference entry, not a live trigger.",
    },
  },
  {
    slug: "relative-strength",
    no: "05",
    kind: "matrix",
    live: true,
    icon: Radar,
    title: "Relative Strength Engine",
    shortDescription: "Pairwise strength matrix across sector groups.",
    overview: {
      purpose: "Ranks every stock in a sector against every other stock in that sector, not just against a single benchmark.",
      whatItMeasures: "For each pair, builds a Point & Figure chart of their price ratio — a rising ratio favors the first stock, a falling ratio favors the second. Each stock's score is how many of its pairwise comparisons currently favor it.",
      interpret: "Run across short, medium and long-term box sizes at once — a stock outperforming most of its peers on all three is showing broader, more durable strength than one that only ranks well on a single timeframe.",
    },
  },
  {
    slug: "sharpe-dashboard",
    no: "06",
    kind: "sharpe",
    live: false,
    icon: BarChart3,
    title: "Sharpe Dashboard",
    shortDescription: "Risk-adjusted stock ranking engine.",
    overview: {
      purpose: "Ranks opportunities by risk-adjusted return rather than raw performance.",
      whatItMeasures: "Computes Sharpe, Sortino, and maximum drawdown across the Nifty 500 for any basket you choose, or the full ranked universe.",
      interpret: "A higher Sharpe reflects steadier, more risk-efficient returns — useful for comparing very different names on equal footing.",
    },
  },
  {
    slug: "ewma-scanner",
    no: "07",
    kind: "ewma",
    live: false,
    icon: Sliders,
    title: "EWMA Scanner",
    shortDescription: "Trend acceleration and crossover engine.",
    overview: {
      purpose: "Flags trend acceleration and crossover events using a fast/slow moving-average model.",
      whatItMeasures: "Runs an exponentially-weighted moving-average crossover, with an acceleration filter, against buy-and-hold on any symbol you choose.",
      interpret: "A fresh bullish crossover suggests emerging upward momentum; a bearish crossover suggests the opposite — always shown against its own buy-and-hold benchmark for context.",
    },
  },
  {
    slug: "breadth-indicator",
    no: "09",
    kind: "breadth",
    live: true,
    icon: Gauge,
    title: "Market Breadth",
    shortDescription: "Percentage of the group currently trending bullish.",
    overview: {
      purpose: "Reads market health from participation, not just the index level — a rising index on narrow participation is a weaker trend than one lifting most of its constituents.",
      whatItMeasures: "Percentage of stocks in the group currently in a bullish swing on their own chart, independent of every other constituent.",
      interpret: "Above 75% or below 25% is an extreme zone — trends can sit there for a long stretch, so treat it as a caution flag for fresh entries, not a standalone reversal trigger.",
    },
  },
  {
    slug: "options-trend-scanner",
    no: "10",
    kind: "options-trend",
    live: true,
    icon: GitBranch,
    title: "Options Trend Scanner",
    shortDescription: "Confirms directional setups across future, call, and put together.",
    overview: {
      purpose: "Confirms a stock's directional setup isn't just a single-chart read — the underlying, its call, and its put all have to agree.",
      whatItMeasures: "Reads each of the three instrument's own chart independently, then applies a strict agreement rule: bullish needs the future AND call both up with the put down, bearish is the mirror image, everything else is neutral.",
      interpret: "A Bullish or Bearish verdict reflects real cross-instrument momentum agreement, not a guess off the underlying alone — treat Neutral as no current edge, not a hidden signal.",
    },
  },
  {
    slug: "market-dashboard",
    no: "11",
    kind: "market-dashboard",
    live: true,
    icon: LayoutDashboard,
    title: "Market Assessment",
    shortDescription: "Single-screen market health, built entirely from free public data.",
    overview: {
      purpose: "A single-screen read on overall market health — index levels, participation, sentiment — independent of any broker session.",
      whatItMeasures: "Sector and segment performance, market-wide advance/decline, India VIX, 52-week high/low counts, FII/DII cash-market flows, and global index levels.",
      interpret: "Use it as market context before drilling into any other module — broad participation (many sectors green, advances beating declines) supports conviction; narrow or negative breadth is a caution flag even when the headline index looks fine.",
    },
  },
  {
    slug: "breakout-candidates",
    no: "08",
    kind: "scanner",
    live: false,
    scannerKey: "breakout",
    icon: TrendingUp,
    title: "Breakout Candidates",
    shortDescription: "Detects high-conviction breakout setups.",
    overview: {
      purpose: "Detects names approaching or clearing a key structural price level.",
      whatItMeasures: "Screens for price action nearing a defined resistance or support level alongside volume confirmation.",
      interpret: "A candidate here is a setup to watch, not a trigger — confirmation typically requires the breakout to hold with follow-through volume.",
    },
  },
];

export const getModule = (slug) => MODULES.find((m) => m.slug === slug) || null;
