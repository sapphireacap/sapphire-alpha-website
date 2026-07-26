// Institutional-style performance metrics, computed client-side from the
// same trade/equity data the old Black Box cards already fetched — no new
// backend endpoints. Two input shapes are supported:
//   - trade-based (Prism Alpha): a flat list of closed trades with pnl (INR)
//     and entry/exit timestamps.
//   - curve-based (any strategy): a chronological [{date, value}] equity
//     series, optionally alongside a benchmark series of the same shape.
// Metrics that need a benchmark (Beta/Alpha/Information Ratio) are simply
// omitted when no benchmark series is supplied, rather than guessed.

const MS_DAY = 86400000;

const mean = (xs) => (xs.length ? xs.reduce((a, b) => a + b, 0) / xs.length : 0);
const stdev = (xs) => {
  if (xs.length < 2) return 0;
  const m = mean(xs);
  return Math.sqrt(xs.reduce((a, b) => a + (b - m) ** 2, 0) / (xs.length - 1));
};

/* ---------------------------- trade-based ---------------------------- */
// trades: [{ pnl, entry_time, exit_time }] — already-closed trades only.
export function computeTradeStats(trades) {
  const closed = (trades || []).filter((t) => t.pnl != null && t.exit_time);
  const sorted = [...closed].sort((a, b) => new Date(a.exit_time) - new Date(b.exit_time));
  const total = sorted.length;

  if (total === 0) {
    return {
      totalTrades: 0, winRate: null, profitFactor: null, expectancy: null,
      avgTrade: null, bestTrade: null, worstTrade: null, avgHoldingMinutes: null,
      maxConsecWins: 0, maxConsecLosses: 0, monthlyPnl: [],
    };
  }

  const wins = sorted.filter((t) => t.pnl > 0);
  const losses = sorted.filter((t) => t.pnl < 0);
  const grossWin = wins.reduce((a, t) => a + t.pnl, 0);
  const grossLoss = Math.abs(losses.reduce((a, t) => a + t.pnl, 0));
  const pnls = sorted.map((t) => t.pnl);

  let streak = 0, lastSign = 0, maxW = 0, maxL = 0;
  for (const t of sorted) {
    const sign = t.pnl > 0 ? 1 : t.pnl < 0 ? -1 : 0;
    streak = sign !== 0 && sign === lastSign ? streak + 1 : 1;
    lastSign = sign;
    if (sign > 0) maxW = Math.max(maxW, streak);
    if (sign < 0) maxL = Math.max(maxL, streak);
  }

  const holdingMinutes = sorted
    .filter((t) => t.entry_time)
    .map((t) => (new Date(t.exit_time) - new Date(t.entry_time)) / 60000);

  const byMonth = new Map();
  for (const t of sorted) {
    const key = String(t.exit_time).slice(0, 7); // YYYY-MM
    byMonth.set(key, (byMonth.get(key) || 0) + t.pnl);
  }

  return {
    totalTrades: total,
    winRate: wins.length / total,
    profitFactor: grossLoss > 0 ? grossWin / grossLoss : (grossWin > 0 ? Infinity : null),
    expectancy: mean(pnls),
    avgTrade: mean(pnls),
    bestTrade: Math.max(...pnls),
    worstTrade: Math.min(...pnls),
    avgHoldingMinutes: holdingMinutes.length ? mean(holdingMinutes) : null,
    maxConsecWins: maxW,
    maxConsecLosses: maxL,
    monthlyPnl: [...byMonth.entries()].map(([month, pnl]) => ({ month, pnl })).sort((a, b) => a.month.localeCompare(b.month)),
  };
}

/* ---------------------------- curve-based ----------------------------- */
// points: [{ date: "YYYY-MM-DD", value: number }] ascending, already unique per date.
// `periodsPerYear` is auto-derived from the series' own sampling density
// (point count / elapsed years) unless explicitly overridden — a fixed 252
// (daily) assumption is wrong for a curve sampled per-trade (several a day)
// or per-signal-event rather than once per calendar day, and silently
// inflates/deflates Sharpe, Sortino, and volatility by whatever factor the
// real cadence differs from 252.
export function computeEquityStats(points, { periodsPerYear } = {}) {
  const pts = (points || []).filter((p) => p.value != null);
  if (pts.length < 2) {
    return {
      netReturnPct: null, cagrPct: null, maxDrawdownPct: null, drawdownCurve: [],
      worstDrawdowns: [], sharpe: null, sortino: null, calmar: null,
      volatilityPct: null, ulcerIndex: null, downsideDeviationPct: null, recoveryFactor: null,
    };
  }

  const first = pts[0], last = pts[pts.length - 1];
  const netReturnPct = ((last.value - first.value) / first.value) * 100;
  const years = Math.max((new Date(last.date) - new Date(first.date)) / (MS_DAY * 365.25), 1 / 365.25);
  const cagrPct = (Math.pow(last.value / first.value, 1 / years) - 1) * 100;

  // Period-over-period returns, used for Sharpe/Sortino/volatility/Ulcer.
  const rets = [];
  for (let i = 1; i < pts.length; i++) {
    if (pts[i - 1].value > 0) rets.push((pts[i].value - pts[i - 1].value) / pts[i - 1].value);
  }
  const effectivePeriodsPerYear = periodsPerYear ?? Math.max(1, rets.length / years);
  const meanRet = mean(rets);
  const sdRet = stdev(rets);
  const downsideRets = rets.filter((r) => r < 0);
  const downsideSd = stdev(downsideRets);

  // Annualizing from a handful of return samples over a short window
  // amplifies noise into a huge, misleading ratio rather than a real signal
  // — below ~20 samples or ~20 calendar days, report "not enough data"
  // instead of a technically-computed but statistically unreliable number.
  const sampleReliable = rets.length >= 20 && years >= 20 / 365.25;
  const sharpe = sampleReliable && sdRet > 0 ? (meanRet / sdRet) * Math.sqrt(effectivePeriodsPerYear) : null;
  const sortino = sampleReliable && downsideSd > 0 ? (meanRet / downsideSd) * Math.sqrt(effectivePeriodsPerYear) : null;
  const volatilityPct = sampleReliable ? sdRet * Math.sqrt(effectivePeriodsPerYear) * 100 : null;
  const downsideDeviationPct = sampleReliable ? downsideSd * Math.sqrt(effectivePeriodsPerYear) * 100 : null;

  // Drawdown curve + worst drawdown episodes (peak -> trough -> recovery).
  let peak = pts[0].value, peakDate = pts[0].date;
  const drawdownCurve = [];
  const episodes = [];
  let current = null;
  const sqDd = [];

  for (const p of pts) {
    if (p.value >= peak) {
      if (current) { current.recoveryDate = p.date; episodes.push(current); current = null; }
      peak = p.value; peakDate = p.date;
    }
    const ddPct = peak > 0 ? ((p.value - peak) / peak) * 100 : 0;
    drawdownCurve.push({ date: p.date, ddPct });
    sqDd.push(ddPct * ddPct);
    if (ddPct < 0) {
      if (!current || ddPct < current.troughPct) {
        current = { ...(current || { peakDate }), troughDate: p.date, troughPct: ddPct, peakDate: current?.peakDate || peakDate };
      }
    }
  }
  if (current) episodes.push(current); // still underwater as of the last point

  const worstDrawdowns = [...episodes].sort((a, b) => a.troughPct - b.troughPct).slice(0, 5).map((e) => ({
    peakDate: e.peakDate,
    troughDate: e.troughDate,
    depthPct: e.troughPct,
    recoveryDate: e.recoveryDate || null,
    recoveryDays: e.recoveryDate ? Math.round((new Date(e.recoveryDate) - new Date(e.peakDate)) / MS_DAY) : null,
  }));

  const maxDrawdownPct = worstDrawdowns.length ? worstDrawdowns[0].depthPct : 0;
  const ulcerIndex = Math.sqrt(mean(sqDd));
  // Below ~0.05% the drawdown denominator is near-zero, so Calmar/Recovery
  // Factor would blow up into a huge, meaningless ratio rather than a real
  // signal — report "not meaningful" (null) instead of a wild number.
  const ddMeaningful = Math.abs(maxDrawdownPct) >= 0.05;
  const calmar = ddMeaningful ? cagrPct / Math.abs(maxDrawdownPct) : null;
  const recoveryFactor = ddMeaningful ? netReturnPct / Math.abs(maxDrawdownPct) : null;

  return {
    netReturnPct, cagrPct, maxDrawdownPct, drawdownCurve, worstDrawdowns,
    sharpe, sortino, calmar, volatilityPct, ulcerIndex, downsideDeviationPct, recoveryFactor,
    periodReturns: rets,
  };
}

// Beta/Alpha/Information Ratio against a benchmark equity series of the
// same shape — only meaningful (and only ever shown) when a real benchmark
// exists; callers must not fabricate one.
export function computeBenchmarkStats(points, benchmarkPoints, { periodsPerYear } = {}) {
  if (!benchmarkPoints?.length) return { beta: null, alpha: null, informationRatio: null };

  const bench = new Map(benchmarkPoints.map((p) => [p.date, p.value]));
  const dates = points.map((p) => p.date).filter((d) => bench.has(d));
  if (dates.length < 3) return { beta: null, alpha: null, informationRatio: null };

  const years = Math.max((new Date(dates[dates.length - 1]) - new Date(dates[0])) / (MS_DAY * 365.25), 1 / 365.25);
  const effectivePeriodsPerYear = periodsPerYear ?? Math.max(1, (dates.length - 1) / years);

  const stratByDate = new Map(points.map((p) => [p.date, p.value]));
  const stratRets = [], benchRets = [];
  for (let i = 1; i < dates.length; i++) {
    const d0 = dates[i - 1], d1 = dates[i];
    const s0 = stratByDate.get(d0), s1 = stratByDate.get(d1);
    const b0 = bench.get(d0), b1 = bench.get(d1);
    if (s0 > 0 && b0 > 0) { stratRets.push((s1 - s0) / s0); benchRets.push((b1 - b0) / b0); }
  }
  if (stratRets.length < 3) return { beta: null, alpha: null, informationRatio: null };

  const mS = mean(stratRets), mB = mean(benchRets);
  let cov = 0, varB = 0;
  for (let i = 0; i < stratRets.length; i++) { cov += (stratRets[i] - mS) * (benchRets[i] - mB); varB += (benchRets[i] - mB) ** 2; }
  cov /= stratRets.length; varB /= stratRets.length;
  const beta = varB > 0 ? cov / varB : null;
  const alphaPct = beta != null ? (mS - beta * mB) * effectivePeriodsPerYear * 100 : null;

  const active = stratRets.map((r, i) => r - benchRets[i]);
  const teAnnualized = stdev(active) * Math.sqrt(effectivePeriodsPerYear);
  const informationRatio = teAnnualized > 0 ? (mean(active) * effectivePeriodsPerYear) / teAnnualized : null;

  return { beta, alpha: alphaPct, informationRatio };
}

// Month-end-to-month-end % change of an equity/portfolio value series —
// used instead of summing trade P&L when the underlying capital base isn't
// fixed (e.g. a SIP with ongoing contributions), where trade-level P&L
// summed per month wouldn't cleanly separate "return" from "new money in".
export function computeMonthlyReturnsFromCurve(points) {
  if (!points?.length) return [];
  const byMonth = new Map();
  for (const p of points) byMonth.set(String(p.date).slice(0, 7), p); // keeps last-seen = month-end
  const months = [...byMonth.entries()].sort((a, b) => a[0].localeCompare(b[0]));
  const out = [];
  for (let i = 1; i < months.length; i++) {
    const prevVal = months[i - 1][1].value, curVal = months[i][1].value;
    if (prevVal > 0) out.push({ month: months[i][0], pct: ((curVal - prevVal) / prevVal) * 100 });
  }
  return out;
}

export const RANGES = ["3M", "6M", "1Y", "3Y", "ALL"];

export function filterByRange(points, range) {
  if (!points?.length || range === "ALL") return points || [];
  const days = { "3M": 92, "6M": 183, "1Y": 365, "3Y": 365 * 3 }[range];
  if (!days) return points;
  const cutoff = new Date(points[points.length - 1].date).getTime() - days * MS_DAY;
  const filtered = points.filter((p) => new Date(p.date).getTime() >= cutoff);
  return filtered.length >= 2 ? filtered : points;
}

export function tradesToCSV(trades, columns) {
  const cols = columns || Object.keys(trades[0] || {});
  const esc = (v) => {
    const s = v == null ? "" : String(v);
    return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
  };
  const rows = [cols.join(","), ...trades.map((t) => cols.map((c) => esc(t[c])).join(","))];
  return rows.join("\n");
}

export function downloadCSV(filename, csvText) {
  const blob = new Blob([csvText], { type: "text/csv;charset=utf-8;" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}
