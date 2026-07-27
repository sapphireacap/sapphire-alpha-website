import {
  Compass, Crosshair, Activity, Radar, BarChart3, Sliders, TrendingUp, Target,
} from "lucide-react";

// Every research module shown on the Alpha Terminal directory and served at
// its own /alpha-terminal/:slug page (ModuleDetail.jsx). `kind` decides what
// ModuleDetail's Live Dashboard section renders:
//   "vector"    -> one StraddleCompass per covered index (see indices below)
//                  — the Index Vector's public bias/spot read, per index
//   "scanner"   -> MomentumTable against /terminal/stocks?scanner=<scannerKey>
//   "ewma"      -> the standalone EwmaCrossoverTool, embedded
//   "sharpe"    -> the standalone SharpeDashboardTool, embedded
//   "exitline"  -> the standalone ExitlineTool, embedded (segment -> scrip
//                  -> proprietary level ladder + SL/TP)
export const MODULES = [
  {
    slug: "index-vector",
    no: "01",
    kind: "vector",
    icon: Compass,
    title: "Index Vector",
    shortDescription: "Institutional market regime confirmation model.",
    category: "Market Intelligence",
    status: "Operational",
    universe: "NIFTY, BANKNIFTY, SENSEX, BANKEX Index Options",
    coverage: "Weekly & Monthly Expiries",
    // Displayed inside the module page, one compass per index, in this
    // order. Same P&F box%/reversal parameters and same all-legs-must-agree
    // confluence rule for every index — only the underlying contracts
    // differ. NIFTY/SENSEX still list real weekly-cadence contracts;
    // BANKNIFTY/BANKEX are monthly-only now (confirmed live against
    // Definedge's master data), so those two skip the weekly leg entirely
    // rather than reading a fake one — see definedge_service.py's
    // INDEX_CONFIG chart_mode for the backend side of this.
    indices: ["NIFTY", "BANKNIFTY", "SENSEX", "BANKEX"],
    overview: {
      purpose: "Confirms the near-term directional regime for NIFTY, BANKNIFTY, SENSEX, and BANKEX before you commit to a trade.",
      whatItMeasures: "Aggregates signals across each index's options market structure into a single Bullish, Bearish, or Neutral read.",
      interpret: "Use it as confirmation, not a standalone entry signal — an aligned bias supports a trade idea already in place; an opposing bias is a caution flag.",
    },
  },
  {
    slug: "exitline",
    no: "02",
    kind: "exitline",
    icon: Crosshair,
    title: "Exitline",
    shortDescription: "Proprietary intraday levels with a suggested SL and TP.",
    category: "Trade Execution",
    status: "Operational",
    universe: "NSE Cash, Futures & Options",
    coverage: "On demand, any symbol",
    overview: {
      purpose: "Turns yesterday's high/low/close into a proprietary intraday level ladder against the live price, with a rule-based stop-loss and take-profit.",
      whatItMeasures: "Classifies the current price into a mean-reversion Trading Zone (S3–R3) or a trend-day Breakout Zone (beyond R4/S4), and derives SL/TP from that read.",
      interpret: "Near R3/S3, treat it as a mean-reversion trigger with a fixed target; beyond R4/S4, treat it as a trend day — trail the stop, no fixed target.",
    },
  },
  {
    slug: "momentum-engine",
    no: "03",
    kind: "scanner",
    scannerKey: "momentum",
    icon: Activity,
    title: "Intraday Momentum Leaders",
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
  },
  {
    slug: "relative-strength",
    no: "04",
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
  },
  {
    slug: "sharpe-dashboard",
    no: "05",
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
  },
  {
    slug: "ewma-scanner",
    no: "06",
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
  },
  {
    slug: "breakout-candidates",
    no: "07",
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
  },
  {
    slug: "positional-opportunities",
    no: "08",
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
  },
];

export const getModule = (slug) => MODULES.find((m) => m.slug === slug) || null;
