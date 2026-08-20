import {
  Compass, Crosshair, Activity, Radar, BarChart3, Sliders, TrendingUp, Target, Gauge, GitBranch, LayoutDashboard, Flame, ShieldAlert, LineChart,
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
// `live: false` modules are paused to cut backend memory/load while the
// Render free-tier instance keeps crash-restarting on its memory limit --
// their pages show a "Coming Soon" placeholder and make no API calls at
// all, instead of their normal dashboard. Nothing about the module's own
// data or backend code is touched; flip the field back to `true` to fully
// restore. Index Vector and Exitline stay live throughout -- every other
// paused module is explicitly `live: false` below (set on each one, not
// defaulted, so it's never ambiguous). Intraday Momentum Leaders was
// turned off 2026-08-12 (was live), swapped tile positions with Peter
// Tingle (was adminOnly, now public), at the user's explicit direction.
// Live modules are listed first (grouped together), paused ones after --
// `no` is renumbered sequentially to match this visual order rather than
// the historical build order, so the badge on each card always reads
// top-to-bottom, left-to-right with no gaps/out-of-order jumps.
export const MODULES = [
  {
    slug: "index-vector",
    no: "01",
    kind: "vector",
    live: true,
    icon: Compass,
    title: "Index Vector",
    shortDescription: "A multi-factor confirmation model for major indices.",
    // Displayed inside the module page, one card per index (see
    // ModuleDetail.jsx / IndexVectorHero.jsx). FINNIFTY dropped 2026-08-20
    // at the user's explicit direction -- NIFTY and BANKNIFTY only now.
    // Same P&F box%/reversal parameters and same all-legs-must-agree
    // confluence rule for both -- only the underlying contracts differ.
    // NIFTY lists real weekly-cadence contracts; BANKNIFTY is monthly-only
    // (confirmed live against Definedge's master data), so it skips the
    // weekly leg entirely rather than reading a fake one -- see
    // definedge_service.py's INDEX_CONFIG chart_mode for the backend side.
    indices: ["NIFTY", "BANKNIFTY"],
    overview: {
      purpose: "Confirms the near-term directional bias for NIFTY and BANKNIFTY before you commit to a trade.",
      whatItMeasures: "Aggregates signals across each index's options market structure into a single Bullish, Bearish, or Neutral read.",
      interpret: "Use it as confirmation, not a standalone entry signal -- an aligned bias supports a trade idea already in place; an opposing bias is a caution flag.",
    },
  },
  {
    slug: "exitline",
    no: "02",
    kind: "exitline",
    live: true,
    icon: Crosshair,
    title: "Exitline",
    shortDescription: "Intraday levels with a suggested SL and TP.",
    overview: {
      purpose: "Turns yesterday's high/low/close into an intraday level ladder against the live price, with a rule-based stop-loss and take-profit.",
      whatItMeasures: "Classifies the current price into a mean-reversion Trading Zone (S3–R3) or a trend-day Breakout Zone (beyond R4/S4), and derives SL/TP from that read.",
      interpret: "Near R3/S3, treat it as a mean-reversion trigger with a fixed target; beyond R4/S4, treat it as a trend day — trail the stop, no fixed target.",
    },
  },
  {
    slug: "peter-tingle",
    no: "03",
    kind: "peter-tingle",
    live: true,
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
    slug: "relative-strength",
    no: "04",
    kind: "matrix",
    live: true,
    icon: Radar,
    title: "Relative Strength Engine",
    // Card copy across every module is deliberately instrument-neutral so
    // the identical string is true on all four market tabs -- naming NSE or
    // the Nifty 500 here would read as a plain falsehood on Forex/Crypto.
    // The market-specific detail lives in each module's own page instead.
    shortDescription: "Pairwise strength matrix across peer groups.",
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
    slug: "swing-picks",
    no: "07",
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
    no: "08",
    kind: "momentum-investing",
    live: true,
    icon: Flame,
    title: "Momentum Investing",
    shortDescription: "Risk-adjusted momentum ranking across the market's universe.",
    overview: {
      purpose: "Ranks positional investment candidates by momentum, not raw price performance alone.",
      whatItMeasures: "Trailing 12-month return (excluding the most recent month) divided by realized volatility over the same window — a steadier uptrend outranks a choppier one with the same headline return.",
      interpret: "Use it to build or review a positional watchlist, not as a same-day trigger — this is a periodic-rebalance style read, not an intraday signal.",
    },
  },
  {
    slug: "momentum-engine",
    no: "09",
    kind: "scanner",
    live: false,
    scannerKey: "momentum",
    icon: Activity,
    title: "Intraday Momentum Leaders",
    shortDescription: "Ranks short-term momentum across the market's liquid universe.",
    overview: {
      purpose: "Surfaces the NSE-listed names showing the strongest momentum right now.",
      whatItMeasures: "Ranks stocks by a composite momentum score built from price action, volume, and conviction scoring.",
      interpret: "A higher score reflects stronger, more confirmed momentum — treat the list as a daily research starting point, not a buy list.",
    },
  },
  {
    slug: "sharpe-dashboard",
    no: "10",
    kind: "sharpe",
    live: false,
    icon: BarChart3,
    title: "Sharpe Dashboard",
    shortDescription: "Risk-adjusted ranking engine.",
    overview: {
      purpose: "Ranks opportunities by risk-adjusted return rather than raw performance.",
      whatItMeasures: "Computes Sharpe, Sortino, and maximum drawdown across the Nifty 500 for any basket you choose, or the full ranked universe.",
      interpret: "A higher Sharpe reflects steadier, more risk-efficient returns — useful for comparing very different names on equal footing.",
    },
  },
  {
    slug: "ewma-scanner",
    no: "11",
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
    no: "12",
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
    title: "Exitline",
    shortDescription: "Intraday levels with a suggested SL and TP.",
    overview: {
      purpose: "Same Camarilla level ladder and SL/TP logic as Exitline, for US equities.",
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

/* ==========================================================================
   Multi-market parity — Forex, Crypto, and the rest of the US set
   ==========================================================================

   Every market tab shows the SAME twelve modules, with the same titles and
   the same description copy, because all four are generated from MODULES
   above rather than retyped per market. That is deliberate and load-bearing:
   the acceptance criterion is that a module reads identically on every tab,
   and copy that is written once cannot drift.

   What legitimately varies per market is only:
     - `slug`   the market's own page URL
     - `live`   whether that market has the instrument the module needs
     - `reason` why not, when it doesn't (shown on the locked card)
     - `market` which backend adapter the page queries

   The backend mirrors this exactly: one pure implementation of each
   calculation, handed a different data adapter per market (see
   backend/multi_market_engine.py). Nothing is reimplemented on either side.

   US keeps its six ORIGINAL slugs (us-exitline, us-breadth, ...) because
   those pages are live and already wired to their own components; the six
   modules US was missing are added alongside them rather than renaming
   anything. US also keeps Market Assessment, which has no India
   counterpart — it is a genuine extra for that market, not a replacement
   for one of the twelve.
*/

// Why a module cannot run in a given market. These are real instrument/data
// limits, not "not built yet" — the backend returns the same reasons from
// /api/markets/{market}/modules, and the locked card shows them verbatim.
const NO_FORMULA_REASON = {
  "swing-picks": "Swing Picks is a curated pick list synced from a CSV export, not a computed scan — there is no formula to run against another market's instruments.",
  "breakout-candidates": "Breakout Candidates is served from curated ingested rows, not a computed scan — there is no formula to port.",
};

const MARKET_BLOCKERS = {
  us: {},
  forex: {
    "index-vector": "Index Vector reads options-market structure. No free, standardized listed FX options chain exists — retail FX options trade OTC, with no public chain to read.",
    "options-trend-scanner": "Gamma Pulse needs a future, an ATM call and an ATM put on the same instrument. FX options are OTC with no public listed chain, so two of the three legs cannot be read at all.",
    "peter-tingle": "The technical half runs on any price series, but the fundamental half (leverage, cash flow, interest cover) has no meaning for a currency pair — there is no balance sheet behind EURUSD.",
  },
  crypto: {
    "peter-tingle": "The technical half runs on any price series, but the fundamental half (promoter pledge, cash flow quality, interest cover) has no equivalent for a token — there is no balance sheet to scan.",
  },
};

// Per-market slug for each canonical module. US reuses its existing live
// slugs wherever one already exists so no working page changes URL.
const SLUG_MAP = {
  us: {
    "exitline": "us-exitline",
    "momentum-engine": "us-momentum-leaders",
    "momentum-investing": "us-momentum-investing",
    "breadth-indicator": "us-breadth",
    "relative-strength": "us-relative-strength",
    "index-vector": "us-index-vector",
    "peter-tingle": "us-peter-tingle",
    "options-trend-scanner": "us-gamma-pulse",
    "swing-picks": "us-swing-picks",
    "sharpe-dashboard": "us-sharpe-dashboard",
    "ewma-scanner": "us-ewma-scanner",
    "breakout-candidates": "us-breakout-candidates",
  },
};

// The `kind` ModuleDetail renders for each canonical module on a
// generic (adapter-backed) market tab. US's six original modules keep
// their own bespoke kinds via US_MODULES and are not affected.
const GENERIC_KIND = {
  "index-vector": "mm-index-vector",
  "exitline": "mm-exitline",
  "peter-tingle": "mm-peter-tingle",
  "relative-strength": "mm-relative-strength",
  "breadth-indicator": "mm-breadth",
  "options-trend-scanner": "mm-gamma-pulse",
  "swing-picks": "mm-unavailable",
  "momentum-investing": "mm-momentum-investing",
  "momentum-engine": "mm-momentum-leaders",
  "sharpe-dashboard": "mm-sharpe",
  "ewma-scanner": "mm-ewma",
  "breakout-candidates": "mm-unavailable",
};

// Card copy (title + shortDescription) is instrument-neutral and therefore
// identical on every tab. The longer "About Module" overview is not always
// neutral: a few India entries name the actual contracts they read, which is
// genuinely useful on the India tab and simply false anywhere else. Those
// few get a market-neutral overview off-India rather than either degrading
// India's copy or shipping a wrong statement.
const OVERVIEW_OVERRIDES = {
  "index-vector": {
    purpose: "Confirms the near-term directional bias for this market's index instruments before you commit to a trade.",
    whatItMeasures: "Aggregates signals across the index's options market structure into a single Bullish, Bearish, or Neutral read: two straddles either side of the money plus the at-the-money call and put, all four of which must agree.",
    interpret: "Use it as confirmation, not a standalone entry signal -- an aligned bias supports a trade idea already in place; an opposing bias is a caution flag.",
  },
  "peter-tingle": {
    purpose: "A spider-sense check on a single instrument — surfaces the technical and fundamental warning signs before you commit, in one place.",
    whatItMeasures: "Technical side (identical rules in every market): trend structure, distance from the all-time high, short-term shocks, and multi-window momentum decay. The fundamental side is market-specific and only runs where a balance sheet exists.",
    interpret: "Clear means no rule tripped; Caution means one hard fail or a cluster of soft warnings; Danger means multiple hard fails. Treat any FAIL as a specific, named reason to dig deeper — not a verdict to trade on by itself.",
  },
  "sharpe-dashboard": {
    purpose: "Ranks opportunities by risk-adjusted return rather than raw performance.",
    whatItMeasures: "Computes Sharpe, Sortino, and maximum drawdown across this market's universe, over at least one year of daily bars. The formula is identical in every market; the risk-free rate used is the one appropriate to the market's own currency.",
    interpret: "A higher Sharpe reflects steadier, more risk-efficient returns — useful for comparing very different instruments on equal footing.",
  },
  "momentum-engine": {
    purpose: "Surfaces the names in this market's liquid universe showing the strongest short-term momentum right now.",
    whatItMeasures: "Ranks instruments by a blend of 1-week and 1-month return, computed from real daily bars.",
    interpret: "A higher score reflects stronger short-term momentum — treat the list as a daily research starting point, not a buy list.",
  },
};

const buildMarketModules = (market) => {
  const blockers = MARKET_BLOCKERS[market] || {};
  const slugs = SLUG_MAP[market] || {};
  return MODULES.map((m) => {
    const reason = NO_FORMULA_REASON[m.slug] || blockers[m.slug] || null;
    return {
      // Title, shortDescription and icon are carried over untouched — the
      // whole point of generating rather than retyping.
      ...m,
      overview: OVERVIEW_OVERRIDES[m.slug] || m.overview,
      slug: slugs[m.slug] || `${market}-${m.slug}`,
      canonicalSlug: m.slug,
      market,
      kind: GENERIC_KIND[m.slug],
      live: !reason,
      reason,
    };
  });
};

export const FOREX_MODULES = buildMarketModules("forex");

// Crypto keeps the live multi-pair candlestick dashboard that used to BE
// the whole crypto tab. It isn't one of the twelve (India has no
// counterpart), but it is real, working, free-data functionality — folded
// in as a crypto-only extra rather than dropped to make the tabs
// symmetrical, exactly as US keeps Market Assessment.
export const CRYPTO_MODULES = buildMarketModules("crypto").concat([{
  slug: "crypto-live-chart",
  no: "13",
  kind: "crypto-dashboard",
  live: true,
  market: "crypto",
  canonicalSlug: "crypto-live-chart",
  icon: LineChart,
  title: "Live Chart",
  shortDescription: "Live candlestick charts across major USDT pairs.",
  overview: {
    purpose: "A live candlestick view of the major USDT pairs, for context before opening any other crypto module.",
    whatItMeasures: "Real-time price, 24h change and volume across the top pairs, with selectable intervals from 1 minute to 1 day.",
    interpret: "Market context only — this is raw price data with no model applied, unlike every other module on this tab.",
  },
}]).map((m, i) => ({ ...m, no: String(i + 1).padStart(2, "0") }));

// The six US modules that already had bespoke implementations keep them;
// the other six come from the generic adapter-backed layer. Merged by
// canonical order so the US grid reads top-to-bottom in the same sequence
// as every other tab, and renumbered to match that visual order.
const US_BESPOKE_BY_CANONICAL = {
  "exitline": "us-exitline",
  "momentum-engine": "us-momentum-leaders",
  "momentum-investing": "us-momentum-investing",
  "breadth-indicator": "us-breadth",
  "relative-strength": "us-relative-strength",
};

export const US_FULL_MODULES = buildMarketModules("us").map((m) => {
  const bespokeSlug = US_BESPOKE_BY_CANONICAL[m.canonicalSlug];
  if (!bespokeSlug) return m;
  const bespoke = US_MODULES.find((u) => u.slug === bespokeSlug);
  // Keep the bespoke page's own `kind` (its dedicated component) but take
  // the canonical title/description, so the US tab reads identically to
  // every other tab while still opening the component already built for it.
  return bespoke ? { ...m, kind: bespoke.kind } : m;
}).concat(
  // Market Assessment has no India counterpart — a genuine US-only extra,
  // kept rather than dropped just to make the tabs symmetrical.
  US_MODULES.filter((m) => m.slug === "us-market-assessment"),
).map((m, i) => ({ ...m, no: String(i + 1).padStart(2, "0") }));

export const MARKET_MODULES = {
  india: MODULES,
  us: US_FULL_MODULES,
  forex: FOREX_MODULES,
  crypto: CRYPTO_MODULES,
};

export const getModulesForMarket = (market) => MARKET_MODULES[market] || MODULES;

const ALL_MODULES = [...MODULES, ...US_MODULES, ...US_FULL_MODULES, ...FOREX_MODULES, ...CRYPTO_MODULES];

export const getModule = (slug) => ALL_MODULES.find((m) => m.slug === slug) || null;

/* ---------------------------- Sign-in requirement ---------------------------
   Index Vector and Exitline are the only Alpha Terminal modules open to
   signed-out visitors. Every other module on every market tab requires an
   account.

   Keyed on the CANONICAL slug, so this holds across all four markets at
   once — us-breadth, forex-breadth and crypto-breadth are all gated by the
   single "breadth-indicator" entry, and a new market inherits the rule
   automatically rather than needing its own list.

   This is the UI half only. It is enforced independently on the backend
   (see the auth dependency in multi_market_routes.py and the India/US
   module routers) — a client-side flag alone would be trivially bypassed
   by calling the API directly, so it is not the access control, just the
   thing that stops a signed-out visitor walking into a dead page.
*/
export const FREE_MODULE_SLUGS = new Set(["index-vector", "exitline"]);

export const moduleRequiresAuth = (module) => {
  if (!module) return false;
  return !FREE_MODULE_SLUGS.has(module.canonicalSlug || module.slug);
};
