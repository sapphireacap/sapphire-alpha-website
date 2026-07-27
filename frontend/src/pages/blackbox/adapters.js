import axios from "axios";
import {
  computeTradeStats, computeEquityStats, computeBenchmarkStats, computeMonthlyReturnsFromCurve,
} from "../../lib/strategyStats";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;

export const fmtPct = (v, dp = 1) => (v == null || Number.isNaN(v) ? "—" : `${v > 0 ? "+" : ""}${v.toFixed(dp)}%`);
export const fmtNum = (v, dp = 2) => (v == null || Number.isNaN(v) ? "—" : v.toFixed(dp));
export const fmtINR = (v, dp = 0) => (v == null ? "—" : `₹${v.toLocaleString("en-IN", { minimumFractionDigits: dp, maximumFractionDigits: dp })}`);
const toneOf = (v) => (v == null ? "neutral" : v > 0 ? "pos" : v < 0 ? "neg" : "neutral");

const fmtMinutes = (m) => {
  if (m == null) return "—";
  if (m < 60) return `${Math.round(m)}m`;
  return `${Math.floor(m / 60)}h ${Math.round(m % 60)}m`;
};
const fmtDays = (d) => (d == null ? "—" : d < 1 ? `${Math.round(d * 24)}h` : `${d.toFixed(0)}d`);

const kpi = (key, label, value, tone = "neutral", note) => ({ key, label, value, tone, note });

/* ------------------------------- Prism ------------------------------- */
// Every /blackbox/* read route is admin-gated (trading performance is
// internal-only) — `config` must carry an Authorization header, supplied by
// the caller (the admin dashboard). There is no public caller of this module
// anymore.
async function fetchPrism(apiPath, config) {
  const [status, liveStats, liveTrades, backtestSummary, backtestTrades] = await Promise.all([
    axios.get(`${API}/blackbox/${apiPath}/status`, config).then((r) => r.data),
    axios.get(`${API}/blackbox/${apiPath}/stats`, config).then((r) => r.data),
    axios.get(`${API}/blackbox/${apiPath}/trades`, config).then((r) => r.data),
    axios.get(`${API}/blackbox/${apiPath}/backtest/summary`, config).then((r) => r.data),
    axios.get(`${API}/blackbox/${apiPath}/backtest/trades`, config).then((r) => r.data),
  ]);
  return { status, liveStats, liveTrades, backtestSummary, backtestTrades };
}

function buildPrismView(strategy, raw) {
  const useLive = raw.liveStats.total_trades > 0;
  const trades = useLive ? raw.liveTrades : raw.backtestTrades;
  const closed = trades.filter((t) => t.status === "closed" && t.pnl != null);
  const capital = strategy.capitalValue;

  // Equity curve in ₹ terms (capital + cumulative pnl), so % metrics are
  // against real deployed capital, not an arbitrary base of 0.
  const sorted = [...closed].sort((a, b) => new Date(a.exit_time) - new Date(b.exit_time));
  let cum = 0;
  const equityCurve = [{ date: sorted[0]?.entry_time?.slice(0, 10) || raw.backtestSummary.run?.start_date, value: capital }];
  for (const t of sorted) {
    cum += t.pnl;
    equityCurve.push({ date: t.exit_time.slice(0, 10), value: capital + cum });
  }

  const eq = computeEquityStats(equityCurve);
  const tr = computeTradeStats(closed);
  const monthly = tr.monthlyPnl.map((m) => ({ month: m.month, pct: (m.pnl / capital) * 100 }));
  const avgMonthlyPct = monthly.length ? monthly.reduce((a, m) => a + m.pct, 0) / monthly.length : null;

  // Exposure: total time spent in a position vs. total elapsed time across
  // the track record window — an intraday strategy is flat overnight, so
  // this will always read modest even when it trades every session.
  const holdMinutes = closed.reduce((a, t) => a + (t.entry_time && t.exit_time ? (new Date(t.exit_time) - new Date(t.entry_time)) / 60000 : 0), 0);
  const windowStart = equityCurve[0]?.date ? new Date(equityCurve[0].date) : null;
  const windowEnd = equityCurve[equityCurve.length - 1]?.date ? new Date(equityCurve[equityCurve.length - 1].date) : null;
  const windowMinutes = windowStart && windowEnd ? Math.max(1, (windowEnd - windowStart) / 60000 + 375) : null;
  const exposurePct = windowMinutes ? Math.min(100, (holdMinutes / windowMinutes) * 100) : null;

  const kpis = [
    kpi("netReturn", "Net Return", fmtPct(eq.netReturnPct), toneOf(eq.netReturnPct)),
    kpi("cagr", "CAGR", fmtPct(eq.cagrPct), toneOf(eq.cagrPct), "Annualized over the track record window shown — short windows overstate this."),
    kpi("sharpe", "Sharpe Ratio", fmtNum(eq.sharpe), eq.sharpe > 1 ? "pos" : "neutral"),
    kpi("sortino", "Sortino Ratio", fmtNum(eq.sortino), eq.sortino > 1 ? "pos" : "neutral"),
    kpi("maxDD", "Max Drawdown", eq.maxDrawdownPct != null ? `${eq.maxDrawdownPct.toFixed(1)}%` : "—", "neg"),
    kpi("calmar", "Calmar Ratio", fmtNum(eq.calmar), "neutral"),
    kpi("totalTrades", "Total Trades", tr.totalTrades ?? "—", "neutral"),
    kpi("winRate", "Win Rate", tr.winRate != null ? `${(tr.winRate * 100).toFixed(0)}%` : "—", tr.winRate > 0.5 ? "pos" : tr.winRate != null ? "neg" : "neutral"),
    kpi("profitFactor", "Profit Factor", fmtNum(tr.profitFactor), tr.profitFactor > 1 ? "pos" : tr.profitFactor != null ? "neg" : "neutral"),
    kpi("expectancy", "Expectancy", fmtINR(tr.expectancy, 2), toneOf(tr.expectancy)),
    kpi("avgTrade", "Average Trade", fmtINR(tr.avgTrade, 2), toneOf(tr.avgTrade)),
    kpi("bestTrade", "Best Trade", fmtINR(tr.bestTrade, 2), "pos"),
    kpi("worstTrade", "Worst Trade", fmtINR(tr.worstTrade, 2), "neg"),
    kpi("recoveryFactor", "Recovery Factor", fmtNum(eq.recoveryFactor), "neutral"),
    kpi("avgHold", "Average Holding Period", fmtMinutes(tr.avgHoldingMinutes), "neutral"),
    kpi("avgMonthly", "Average Monthly Return", fmtPct(avgMonthlyPct), toneOf(avgMonthlyPct)),
    kpi("maxConsecWins", "Maximum Consecutive Wins", tr.maxConsecWins, "neutral"),
    kpi("maxConsecLosses", "Maximum Consecutive Losses", tr.maxConsecLosses, "neutral"),
  ];

  const displayTrades = closed.slice(0, 200).map((t) => ({
    id: t.id,
    entry: `${t.entry_time?.slice(0, 16).replace("T", " ")} @ ₹${t.entry_price?.toFixed(2)}`,
    exit: t.exit_time ? `${t.exit_time.slice(0, 16).replace("T", " ")} @ ₹${t.exit_price?.toFixed(2)}` : "—",
    pnlLabel: fmtINR(t.pnl, 2),
    pnlTone: toneOf(t.pnl),
    durationMinutes: t.entry_time && t.exit_time ? (new Date(t.exit_time) - new Date(t.entry_time)) / 60000 : null,
    durationLabel: fmtMinutes(t.entry_time && t.exit_time ? (new Date(t.exit_time) - new Date(t.entry_time)) / 60000 : null),
    signal: t.direction,
    status: t.status,
    raw: t,
  })).sort((a, b) => new Date(b.raw.exit_time) - new Date(a.raw.exit_time));

  return {
    isBacktest: !useLive,
    windowLabel: useLive
      ? "Live track record"
      : raw.backtestSummary.run ? `${raw.backtestSummary.run.start_date} – ${raw.backtestSummary.run.end_date} (backtested)` : "No data yet",
    kpis,
    metrics: {
      sharpe: eq.sharpe, sortino: eq.sortino, calmar: eq.calmar, volatilityPct: eq.volatilityPct,
      ulcerIndex: eq.ulcerIndex, downsideDeviationPct: eq.downsideDeviationPct, exposurePct,
    },
    equityCurve,
    benchmarkCurve: null,
    benchmarkLabel: null,
    drawdownCurve: eq.drawdownCurve,
    worstDrawdowns: eq.worstDrawdowns,
    monthly,
    trades: displayTrades,
    csvRows: closed.map((t) => ({
      date: t.date, direction: t.direction, strike: t.strike, entry_time: t.entry_time, entry_price: t.entry_price,
      exit_time: t.exit_time, exit_price: t.exit_price, pnl: t.pnl, exit_reason: t.exit_reason,
    })),
  };
}

/* ------------------------------- Lumen SIP ------------------------------- */
async function fetchLumen(config) {
  const [status, portfolio, signals, metrics] = await Promise.all([
    axios.get(`${API}/blackbox/lumen-sip/status`, config).then((r) => r.data),
    axios.get(`${API}/blackbox/lumen-sip/backtest/portfolio`, config).then((r) => r.data),
    axios.get(`${API}/blackbox/lumen-sip/backtest/signals`, config).then((r) => r.data),
    axios.get(`${API}/blackbox/lumen-sip/backtest/metrics`, config).then((r) => r.data),
  ]);
  return { status, portfolio, signals, metrics };
}

// Round-trips (buy -> sell) per instrument, merged and sorted — the same
// pairing logic the old LumenSipTradeTable used, generalized across both.
function roundTrips(signals) {
  const out = [];
  for (const instrument of ["NIFTYBEES", "GOLDBEES"]) {
    const sigs = signals.filter((s) => s.instrument === instrument).sort((a, b) => a.date.localeCompare(b.date));
    let buy = null;
    for (const s of sigs) {
      if (s.signal_type === "buy") buy = s;
      else if (s.signal_type === "sell" && buy) { out.push({ instrument, buy, sell: s }); buy = null; }
    }
  }
  return out.sort((a, b) => b.sell.date.localeCompare(a.sell.date));
}

function buildLumenView(strategy, raw) {
  const m = raw.metrics;
  if (!m?.has_data) {
    return { isBacktest: true, windowLabel: "No data yet", kpis: [], metrics: {}, equityCurve: [], benchmarkCurve: null, benchmarkLabel: null, drawdownCurve: [], worstDrawdowns: [], monthly: [], trades: [], csvRows: [] };
  }

  const equityCurve = raw.portfolio.map((p) => ({ date: p.date, value: p.total_value }));
  const benchmarkCurve = m.vanilla_sip.curve.map((p) => ({ date: p.date, value: p.value }));
  const eq = computeEquityStats(equityCurve);
  const bench = computeBenchmarkStats(equityCurve, benchmarkCurve);

  const trips = roundTrips(raw.signals);
  const asTrades = trips.map((t) => ({
    pnl: ((t.sell.price - t.buy.price) / t.buy.price) * 100, // % return, not ₹ — computeTradeStats is unit-agnostic
    entry_time: t.buy.date, exit_time: t.sell.date,
  }));
  const tr = computeTradeStats(asTrades);
  const monthly = computeMonthlyReturnsFromCurve(equityCurve);
  const avgMonthlyPct = monthly.length ? monthly.reduce((a, x) => a + x.pct, 0) / monthly.length : null;

  const recoveryFactor = m.portfolio.max_drawdown_pct ? m.portfolio.absolute_return_pct / m.portfolio.max_drawdown_pct : null;
  const exposurePct = (m.niftybees.allocation_pct * m.niftybees.time_in_market_pct + m.goldbees.allocation_pct * m.goldbees.time_in_market_pct) / 100;

  const kpis = [
    kpi("netReturn", "Net Return", fmtPct(m.portfolio.absolute_return_pct), toneOf(m.portfolio.absolute_return_pct)),
    kpi("cagr", "XIRR", fmtPct(m.portfolio.xirr_pct), toneOf(m.portfolio.xirr_pct), "Money-weighted annualized return — the correct measure for a strategy with ongoing monthly contributions."),
    kpi("sharpe", "Sharpe Ratio", fmtNum(eq.sharpe), eq.sharpe > 1 ? "pos" : "neutral"),
    kpi("sortino", "Sortino Ratio", fmtNum(eq.sortino), eq.sortino > 1 ? "pos" : "neutral"),
    kpi("maxDD", "Max Drawdown", `-${m.portfolio.max_drawdown_pct.toFixed(1)}%`, "neg"),
    kpi("calmar", "Calmar Ratio", fmtNum(m.portfolio.xirr_pct / m.portfolio.max_drawdown_pct), "neutral"),
    kpi("totalTrades", "Total Trades", tr.totalTrades ?? "—", "neutral"),
    kpi("winRate", "Win Rate", tr.winRate != null ? `${(tr.winRate * 100).toFixed(0)}%` : "—", tr.winRate > 0.5 ? "pos" : tr.winRate != null ? "neg" : "neutral"),
    kpi("profitFactor", "Profit Factor", fmtNum(tr.profitFactor), tr.profitFactor > 1 ? "pos" : tr.profitFactor != null ? "neg" : "neutral"),
    kpi("expectancy", "Expectancy", fmtPct(tr.expectancy, 2), toneOf(tr.expectancy)),
    kpi("avgTrade", "Average Trade", fmtPct(tr.avgTrade, 2), toneOf(tr.avgTrade)),
    kpi("bestTrade", "Best Trade", fmtPct(tr.bestTrade, 2), "pos"),
    kpi("worstTrade", "Worst Trade", fmtPct(tr.worstTrade, 2), "neg"),
    kpi("recoveryFactor", "Recovery Factor", fmtNum(recoveryFactor), "neutral"),
    kpi("avgHold", "Average Holding Period", fmtDays(tr.avgHoldingMinutes != null ? tr.avgHoldingMinutes / 1440 : null), "neutral"),
    kpi("avgMonthly", "Average Monthly Return", fmtPct(avgMonthlyPct), toneOf(avgMonthlyPct)),
    kpi("maxConsecWins", "Maximum Consecutive Wins", tr.maxConsecWins, "neutral"),
    kpi("maxConsecLosses", "Maximum Consecutive Losses", tr.maxConsecLosses, "neutral"),
    kpi("alpha", "Alpha", fmtPct(bench.alpha), toneOf(bench.alpha), "Annualized excess return vs. a vanilla (no-signal) monthly SIP in the same instruments."),
    kpi("beta", "Beta", fmtNum(bench.beta), "neutral", "Sensitivity to the vanilla SIP benchmark's day-to-day moves."),
    kpi("infoRatio", "Information Ratio", fmtNum(bench.informationRatio), "neutral", "Consistency of the excess return vs. the vanilla SIP benchmark."),
  ];

  const displayTrades = trips.slice(0, 200).map((t, i) => {
    const retPct = ((t.sell.price - t.buy.price) / t.buy.price) * 100;
    const days = Math.round((new Date(t.sell.date) - new Date(t.buy.date)) / 86400000);
    return {
      id: `${t.instrument}-${i}`,
      entry: `${t.buy.date} @ ₹${t.buy.price.toFixed(2)}`,
      exit: `${t.sell.date} @ ₹${t.sell.price.toFixed(2)}`,
      pnlLabel: fmtPct(retPct, 2),
      pnlTone: toneOf(retPct),
      durationMinutes: days * 1440,
      durationLabel: `${days}d`,
      signal: t.instrument,
      status: "closed",
      raw: t,
    };
  });

  return {
    isBacktest: true,
    windowLabel: `${m.period.start} – ${m.period.end} (backtested, ${m.period.months} months)`,
    kpis,
    metrics: {
      sharpe: eq.sharpe, sortino: eq.sortino, calmar: m.portfolio.xirr_pct / m.portfolio.max_drawdown_pct,
      volatilityPct: eq.volatilityPct, ulcerIndex: eq.ulcerIndex, downsideDeviationPct: eq.downsideDeviationPct, exposurePct,
    },
    equityCurve,
    benchmarkCurve,
    benchmarkLabel: "Vanilla SIP (no signal)",
    drawdownCurve: eq.drawdownCurve,
    worstDrawdowns: eq.worstDrawdowns,
    monthly,
    trades: displayTrades,
    csvRows: trips.map((t) => ({
      instrument: t.instrument, buy_date: t.buy.date, buy_price: t.buy.price, sell_date: t.sell.date, sell_price: t.sell.price,
      return_pct: (((t.sell.price - t.buy.price) / t.buy.price) * 100).toFixed(2),
    })),
  };
}

export async function fetchStrategyView(strategy, config) {
  if (strategy.kind === "lumen") {
    const raw = await fetchLumen(config);
    return buildLumenView(strategy, raw);
  }
  const raw = await fetchPrism(strategy.apiPath, config);
  return buildPrismView(strategy, raw);
}
