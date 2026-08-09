import {
  Compass, Crosshair, Activity, Radar, BarChart3, Sliders, TrendingUp, Target, Gauge, GitBranch, LayoutDashboard, Flame, ShieldAlert,
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
//   "peter-tingle" -> the standalone PeterTingleTool, embedded (symbol
//                  search -> technical + fundamental caution scan)
//   "us-exitline" / "us-momentum-leaders" / "us-momentum-investing" /
//   "us-breadth" / "us-relative-strength" / "us-market-assessment" ->
//                  US_MODULES below, each its own standalone tool
//                  component, same one-kind-per-module pattern
// `live: false` modules are paused (2026-07-29) to cut backend memory/load
// while the Render free-tier instance keeps crash-restarting on its memory
// limit -- their pages show a "Coming Soon" placeholder and make no API
// calls at all, instead of their normal dashboard. Nothing about the
// module's own data or backend code is touched; flip the field back to
// `true` to fully restore. Index Vector, Exitline, and Momentum Leaders
// stay live throughout -- every other module is explicitly `live: false`
// below (set on each one, not defaulted, so it's never ambiguous).
// Live modules are listed first (grouped together), paused ones after --
// `no` is renumbered sequentially to match this visual order rather than
// the historical build order, so the badge on each card always reads
// top-to-bottom, left-to-right with no gaps/out-of-order jumps.
// `adminOnly: true` (Peter Tingle) greys out the directory card and
// blocks the module page for anyone whose /auth/me role isn't "admin" --
// see AlphaTerminal.jsx's useIsAdmin() gate and ModuleDetail.jsx's
// AdminOnlyNotice. The backend routes are independently admin-gated too
// (peter_tingle_routes.py), so this is UI-layer, not the only enforcement.
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
    slug: "relative-strength",
    no: "04",
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
    slug: "breadth-indicator",
    no: "05",
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
    no: "06",
    kind: "options-trend",
    live: true,
    icon: GitBranch,
    title: "Gamma Pulse",
    shortDescription: "Confirms directional setups across future, call, and put together.",
    overview: {
      purpose: "Confirms a stock's directional setup isn't just a single-chart read — the underlying, its call, and its put all have to agree.",
      whatItMeasures: "Reads each of the three instrument's own chart independently, then applies a strict agreement rule: bullish needs the future AND call both up with the put down, bearish is the mirror image, everything else is neutral.",
      interpret: "A Bullish or Bearish verdict reflects real cross-instrument momentum agreement, not a guess off the underlying alone — treat Neutral as no current edge, not a hidden signal.",
    },
  },
  {
    slug: "market-dashboard",
    no: "07",
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
    slug: "swing-picks",
    no: "08",
    kind: "scanner",
    live: true,
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
    slug: "momentum-investing",
    no: "09",
    kind: "momentum-investing",
    live: true,
    icon: Flame,
    title: "Momentum Investing",
    shortDescription: "Risk-adjusted momentum ranking across the Nifty 500.",
    overview: {
      purpose: "Ranks positional investment candidates by momentum, not raw price performance alone.",
      whatItMeasures: "Trailing 12-month return (excluding the most recent month) divided by realized volatility over the same window — a steadier uptrend outranks a choppier one with the same headline return.",
      interpret: "Use it to build or review a positional watchlist, not as a same-day trigger — this is a periodic-rebalance style read, not an intraday signal.",
    },
  },
  {
    slug: "peter-tingle",
    no: "10",
    kind: "peter-tingle",
    live: true,
    adminOnly: true,
    icon: ShieldAlert,
    title: "Peter Tingle",
    shortDescription: "Technical and fundamental analysis that assesses a stock's overall risk and caution signals.",
    overview: {
      purpose: "A spider-sense check on a single stock — surfaces the technical and fundamental warning signs before you commit, in one place. Covers both the Nifty 500 (India) and the S&P 500 (US) via a market toggle.",
      whatItMeasures: "Technical side (same rules both markets): trend structure, distance from its all-time high, short-term shocks, and multi-window momentum decay. Fundamental side is market-specific — India runs the same Fracture Scan rules used elsewhere on the terminal (promoter pledge, cash flow quality, receivables growth, leverage, interest coverage, promoter-holding erosion); US runs leverage, profitability, liquidity, short interest, and sell-side analyst outlook instead, since promoter-specific rules have no real US equivalent.",
      interpret: "Clear means no rule tripped; Caution means one hard fail or a cluster of soft warnings; Danger means multiple hard fails across the two scans. Treat any FAIL as a specific, named reason to dig deeper — not a verdict to trade on by itself.",
    },
  },
  {
    slug: "sharpe-dashboard",
    no: "11",
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
    no: "12",
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
    slug: "breakout-candidates",
    no: "13",
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

// US Markets — same directory-of-pages shape as MODULES above (own
// slug, own /alpha-terminal/:slug page via ModuleDetail.jsx), shown
// instead of MODULES when the Alpha Terminal market selector is set to
// "US Markets" (see AlphaTerminal.jsx). Index Vector and Options Trend
// Scanner have no US equivalent yet — both read live options-market
// structure, and Definedge (the only options data source in this
// codebase) is India-only; Alpaca does serve real US options quotes
// (confirmed live) but replicating those two modules' full P&F
// confluence engines is separate, dedicated work. Swing Picks also has
// no US equivalent (hand-curated pick data on the India side, not a
// live scan). All six US modules reuse an existing engine unchanged,
// just pointed at Yahoo/Alpaca instead of Definedge — see each
// component and backend/us_markets_routes.py for the specifics.
export const US_MODULES = [
  {
    slug: "us-exitline",
    no: "01",
    kind: "us-exitline",
    live: true,
    icon: Crosshair,
    title: "US Exitline",
    shortDescription: "Intraday levels with a suggested SL and TP.",
    overview: {
      purpose: "Same Camarilla level ladder and SL/TP logic as Intraday Exitline, for US equities.",
      whatItMeasures: "Classifies the current price into a mean-reversion Trading Zone or a trend-day Breakout Zone against yesterday's close, and derives SL/TP from that read.",
      interpret: "Near the H3/L3 edge, treat it as a mean-reversion trigger; beyond H4/L4, treat it as a trend day — trail the stop, no fixed target.",
    },
  },
  {
    slug: "us-momentum-leaders",
    no: "02",
    kind: "us-momentum-leaders",
    live: true,
    icon: Activity,
    title: "Momentum Leaders",
    shortDescription: "Ranks 1w/1m momentum across the S&P 500.",
    overview: {
      purpose: "Surfaces the S&P 500 names showing the strongest short-term momentum right now.",
      whatItMeasures: "Ranks stocks by a blend of 1-week and 1-month return, computed from real Yahoo Finance daily bars.",
      interpret: "A higher score reflects stronger short-term momentum — treat the list as a daily research starting point, not a buy list.",
    },
  },
  {
    slug: "us-momentum-investing",
    no: "03",
    kind: "us-momentum-investing",
    live: true,
    icon: Flame,
    title: "Momentum Investing",
    shortDescription: "Risk-adjusted momentum ranking across the S&P 500.",
    overview: {
      purpose: "Ranks positional investment candidates by momentum, not raw price performance alone.",
      whatItMeasures: "Trailing 12-month return (excluding the most recent month) divided by realized volatility over the same window — same \"12-1\" methodology as the India-side Momentum Investing module.",
      interpret: "Use it to build or review a positional watchlist, not as a same-day trigger — this is a periodic-rebalance style read, not an intraday signal.",
    },
  },
  {
    slug: "us-breadth",
    no: "04",
    kind: "us-breadth",
    live: true,
    icon: Gauge,
    title: "Market Breadth",
    shortDescription: "Percentage of the S&P 500 currently trending bullish.",
    overview: {
      purpose: "Reads US market health from participation, not just the index level.",
      whatItMeasures: "Percentage of S&P 500 constituents currently in a bullish P&F swing on their own chart, independent of every other constituent.",
      interpret: "Above 75% or below 25% is an extreme zone — trends can sit there for a long stretch, so treat it as a caution flag for fresh entries, not a standalone reversal trigger.",
    },
  },
  {
    slug: "us-relative-strength",
    no: "05",
    kind: "us-relative-strength",
    live: true,
    icon: Radar,
    title: "Relative Strength Engine",
    shortDescription: "Pairwise strength matrix across US sector groups.",
    overview: {
      purpose: "Ranks every stock in a US GICS sector against every other stock in that sector, not just against a single benchmark.",
      whatItMeasures: "For each pair, builds a Point & Figure chart of their price ratio — a rising ratio favors the first stock, a falling ratio favors the second.",
      interpret: "Run across short, medium and long-term box sizes at once — a stock outperforming most of its peers on all three is showing broader, more durable strength than one that only ranks well on a single timeframe.",
    },
  },
  {
    slug: "us-market-assessment",
    no: "06",
    kind: "us-market-assessment",
    live: true,
    icon: LayoutDashboard,
    title: "Market Assessment",
    shortDescription: "Single-screen US market health.",
    overview: {
      purpose: "A single-screen read on overall US market health — index levels, sector performance, breadth, and movers.",
      whatItMeasures: "S&P 500 and Nasdaq 100 levels, S&P 500 breadth percentage, 1-day sector performance by GICS sector, and the day's biggest gainers/losers.",
      interpret: "Use it as market context before drilling into any other US module — broad sector participation supports conviction; a narrow or negative sector spread is a caution flag even when the headline index looks fine.",
    },
  },
];

export const getModule = (slug) => MODULES.find((m) => m.slug === slug) || US_MODULES.find((m) => m.slug === slug) || null;
