import { useCallback, useEffect, useMemo, useState } from "react";
import axios from "axios";
import { motion } from "framer-motion";
import { AlertTriangle, Lock, Search, TrendingDown, TrendingUp, Minus } from "lucide-react";
import LoadingBar from "../../components/site/LoadingBar";
import BiasBadge from "../../components/site/BiasBadge";

/*
  Generic, adapter-backed module UIs — one component per module, reused by
  every non-India market tab.

  These are deliberately generic rather than one component per
  (module x market): the backend already serves every market from a single
  engine at /api/markets/{market}/..., so a per-market component would be
  three copies of the same fetch-and-render with a different string in it.
  Each component here takes `market` and nothing else changes.

  The India tab and the six original US modules keep their own bespoke
  components — those are live and already built, and rerouting them through
  this layer would be churn with no user-visible gain.
*/

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;
const EASE = [0.16, 1, 0.3, 1];

const CARD = "rounded-2xl border border-white/10 bg-[#0A0D18]";
const LABEL = "font-mono-ui text-[10px] uppercase tracking-[0.18em] text-slate-500";

const DISCLAIMER =
  "This information is intended solely for research and educational purposes and does not constitute investment advice.";

/* ------------------------------- primitives ------------------------------- */

const Panel = ({ title, subtitle, children, right }) => (
  <div className={`${CARD} overflow-hidden`}>
    {(title || right) && (
      <div className="flex items-start justify-between gap-4 px-5 md:px-6 py-4 border-b border-white/10">
        <div>
          {title && <p className={LABEL}>{title}</p>}
          {subtitle && <p className="text-xs text-slate-500 mt-1 leading-relaxed">{subtitle}</p>}
        </div>
        {right}
      </div>
    )}
    <div className="p-5 md:p-6">{children}</div>
  </div>
);

const Unavailable = ({ reason, title = "Not Available in This Market" }) => (
  <div className={`${CARD} p-8 md:p-10 text-center`} data-testid="module-unavailable">
    <span className="inline-flex h-14 w-14 items-center justify-center rounded-2xl border border-white/10 bg-white/[0.03] text-slate-500 mb-5">
      <Lock size={24} />
    </span>
    <h3 className="text-xl font-bold text-white tracking-tight mb-3">{title}</h3>
    <p className="text-sm font-light text-slate-400 max-w-xl mx-auto leading-relaxed">{reason}</p>
  </div>
);

const ErrorNote = ({ message }) => (
  <div className={`${CARD} p-6 flex items-start gap-3`} data-testid="module-error">
    <AlertTriangle size={16} className="text-amber-400 shrink-0 mt-0.5" />
    <p className="text-sm text-slate-400 leading-relaxed">{message}</p>
  </div>
);

const Disclaimer = () => (
  <p className="text-xs font-light text-slate-600 leading-relaxed mt-5 max-w-4xl">{DISCLAIMER}</p>
);

const TREND = {
  Bullish: { color: "text-emerald-400", Icon: TrendingUp },
  Bearish: { color: "text-red-400", Icon: TrendingDown },
  Neutral: { color: "text-slate-400", Icon: Minus },
  bullish: { color: "text-emerald-400", Icon: TrendingUp },
  bearish: { color: "text-red-400", Icon: TrendingDown },
};

const TrendPill = ({ value, bars }) => {
  const style = TREND[value] || TREND.Neutral;
  const { Icon } = style;
  const label = value ? String(value)[0].toUpperCase() + String(value).slice(1) : "Unresolved";
  return (
    <span className="inline-flex items-center gap-1.5">
      <Icon size={13} className={style.color} />
      <span className={`font-mono-ui text-xs ${value ? style.color : "text-slate-600"}`}>{label}</span>
      {typeof bars === "number" && (
        <span className="font-mono-ui text-[10px] text-slate-600">({bars} bars)</span>
      )}
    </span>
  );
};

/** Shared fetch hook — every module here is "GET one URL, render it". */
const useModuleData = (url, { skip = false } = {}) => {
  const [state, setState] = useState({ loading: !skip, data: null, error: null });
  const load = useCallback(() => {
    if (skip || !url) return;
    setState((s) => ({ ...s, loading: true, error: null }));
    axios
      .get(`${API}${url}`)
      .then((r) => setState({ loading: false, data: r.data, error: null }))
      .catch((e) =>
        setState({
          loading: false,
          data: null,
          error: e?.response?.data?.detail || "Data is temporarily unavailable — please try again shortly.",
        }),
      );
  }, [url, skip]);
  useEffect(load, [load]);
  return { ...state, reload: load };
};

/** Symbol picker backed by /markets/{market}/search. */
const SymbolPicker = ({ market, value, onChange, placeholder = "Search symbol…" }) => {
  const [query, setQuery] = useState("");
  const [rows, setRows] = useState([]);
  const [open, setOpen] = useState(false);

  useEffect(() => {
    let cancelled = false;
    axios
      .get(`${API}/markets/${market}/search`, { params: { q: query, limit: 12 } })
      .then((r) => { if (!cancelled) setRows(r.data || []); })
      .catch(() => { if (!cancelled) setRows([]); });
    return () => { cancelled = true; };
  }, [market, query]);

  return (
    <div className="relative">
      <div className="flex items-center gap-2 rounded-xl border border-white/10 bg-white/[0.03] px-3.5 py-2.5 focus-within:border-sapphire-light/50 transition-colors">
        <Search size={14} className="text-slate-500 shrink-0" />
        <input
          value={open ? query : value || ""}
          onFocus={() => { setOpen(true); setQuery(""); }}
          onBlur={() => setTimeout(() => setOpen(false), 150)}
          onChange={(e) => setQuery(e.target.value)}
          placeholder={placeholder}
          className="bg-transparent outline-none text-sm text-white placeholder:text-slate-600 w-full"
          data-testid="mm-symbol-input"
        />
      </div>
      {open && rows.length > 0 && (
        <div className="absolute z-20 mt-1.5 w-full max-h-64 overflow-auto rounded-xl border border-white/10 bg-[#0A0D18] shadow-xl">
          {rows.map((r) => (
            <button
              key={r.symbol}
              type="button"
              onMouseDown={() => { onChange(r.symbol); setOpen(false); }}
              className="flex w-full items-center justify-between gap-3 px-3.5 py-2.5 text-left hover:bg-sapphire/10 transition-colors"
              data-testid={`mm-symbol-option-${r.symbol}`}
            >
              <span className="text-sm font-semibold text-white">{r.symbol}</span>
              <span className="text-xs text-slate-500 truncate">{r.label || r.group}</span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
};

const GroupTabs = ({ groups, active, onChange }) => (
  <div className="flex flex-wrap items-center gap-2 mb-5">
    {(groups || []).map((g) => (
      <button
        key={g}
        type="button"
        onClick={() => onChange(g)}
        className={`px-3.5 py-1.5 rounded-full font-mono-ui text-[11px] uppercase tracking-[0.1em] whitespace-nowrap border transition-colors duration-300 ${
          active === g ? "border-sapphire-light/50 bg-sapphire/10 text-white" : "border-white/10 text-slate-500 hover:text-slate-300"
        }`}
        data-testid={`mm-group-tab-${g}`}
      >
        {g}
      </button>
    ))}
  </div>
);

/** Wraps the common loading/error/unavailable states so each module below
    only has to describe its own success rendering. */
const ModuleShell = ({ loading, error, data, children, loadingLabel }) => {
  if (loading) return <LoadingBar inline label={loadingLabel || "Loading module data"} />;
  if (error) return <ErrorNote message={error} />;
  if (!data) return <ErrorNote message="No data returned." />;
  if (data.available === false) return <Unavailable reason={data.reason} />;
  return children(data);
};

const fmt = (v, dp = 2) =>
  v == null || Number.isNaN(Number(v)) ? "—" : Number(v).toLocaleString("en-US", { minimumFractionDigits: dp, maximumFractionDigits: dp });

const pct = (v, dp = 2) => (v == null ? "—" : `${Number(v) >= 0 ? "+" : ""}${Number(v).toFixed(dp)}%`);

/* --------------------------------- Exitline -------------------------------- */

const LEVEL_ORDER = ["H5", "H4", "H3", "H2", "H1", "Pivot", "L1", "L2", "L3", "L4", "L5"];

export const MMExitline = ({ market, defaultSymbol }) => {
  const [symbol, setSymbol] = useState(defaultSymbol || (market === "crypto" ? "BTCUSDT" : market === "forex" ? "EURUSD" : "AAPL"));
  const { loading, error, data } = useModuleData(`/markets/${market}/exitline?symbol=${encodeURIComponent(symbol)}`);

  return (
    <div className="space-y-5">
      <div className="max-w-sm"><SymbolPicker market={market} value={symbol} onChange={setSymbol} /></div>
      <ModuleShell loading={loading} error={error} data={data} loadingLabel="Computing levels">
        {(d) => {
          const ltp = d.ltp;
          return (
            <div className="grid grid-cols-1 lg:grid-cols-3 gap-5">
              <div className="lg:col-span-2">
                <Panel title="Level Ladder" subtitle={`Computed from ${d.prev_date} — H ${fmt(d.high, 4)} / L ${fmt(d.low, 4)} / C ${fmt(d.close, 4)}`}>
                  <div className="divide-y divide-white/[0.06]">
                    {LEVEL_ORDER.map((key) => {
                      const level = d.levels?.[key];
                      if (level == null) return null;
                      // Mark the band the live price actually sits in, so the
                      // ladder reads as a position, not just a list.
                      const isNearest = ltp != null && LEVEL_ORDER.reduce((best, k) =>
                        Math.abs(d.levels[k] - ltp) < Math.abs(d.levels[best] - ltp) ? k : best, LEVEL_ORDER[0]) === key;
                      return (
                        <div
                          key={key}
                          className={`flex items-center justify-between py-2.5 px-2 -mx-2 rounded ${isNearest ? "bg-sapphire/10" : ""}`}
                          data-testid={`mm-level-${key}`}
                        >
                          <span className={`font-mono-ui text-xs ${key === "Pivot" ? "text-sapphire-light" : "text-slate-500"}`}>{key}</span>
                          <span className={`font-mono-ui text-sm ${isNearest ? "text-white font-semibold" : "text-slate-300"}`}>{fmt(level, 4)}</span>
                        </div>
                      );
                    })}
                  </div>
                </Panel>
              </div>
              <div className="space-y-5">
                <Panel title="Current Read">
                  <p className="font-display text-3xl font-normal tracking-tight text-white mb-1" data-testid="mm-exitline-ltp">
                    {ltp == null ? "—" : fmt(ltp, 4)}
                  </p>
                  <p className="text-xs text-slate-500 mb-4">Live price</p>
                  <div className="flex items-center gap-2 mb-4">
                    <BiasBadge bias={d.bias} testid="mm-exitline-bias" />
                    <span className="font-mono-ui text-[11px] uppercase tracking-wider text-slate-400">{d.zone_label}</span>
                  </div>
                  {d.reason && <p className="text-xs text-slate-500 leading-relaxed">{d.reason}</p>}
                </Panel>
                <Panel title="Suggested Levels">
                  <div className="grid grid-cols-2 gap-4">
                    <div>
                      <p className={LABEL}>Stop Loss</p>
                      <p className="font-mono-ui text-lg text-red-300 mt-1">{fmt(d.sl, 4)}</p>
                    </div>
                    <div>
                      <p className={LABEL}>Take Profit</p>
                      <p className="font-mono-ui text-lg text-emerald-300 mt-1">{d.trail_stop ? "Trail" : fmt(d.tp, 4)}</p>
                    </div>
                  </div>
                  <Disclaimer />
                </Panel>
              </div>
            </div>
          );
        }}
      </ModuleShell>
    </div>
  );
};

/* --------------------------------- Breadth --------------------------------- */

export const MMBreadth = ({ market }) => {
  const [group, setGroup] = useState(null);
  const url = `/markets/${market}/breadth${group ? `?group=${encodeURIComponent(group)}` : ""}`;
  const { loading, error, data } = useModuleData(url);
  const groups = data?.groups || [];

  return (
    <div>
      {groups.length > 0 && <GroupTabs groups={groups} active={group || groups[0]} onChange={setGroup} />}
      <ModuleShell loading={loading} error={error} data={data} loadingLabel="Loading breadth series">
        {(d) => {
          if (!d.has_data) {
            return (
              <ErrorNote message={`Breadth for this group hasn't been computed yet (status: ${d.status || "never run"}). It refreshes on a schedule.`} />
            );
          }
          const series = d.series || [];
          const latest = series[series.length - 1];
          const value = latest?.value ?? 0;
          const zone = value >= 75 ? "Overbought Zone" : value <= 25 ? "Oversold Zone" : "Neutral Range";
          const zoneColor = value >= 75 ? "text-red-300" : value <= 25 ? "text-emerald-300" : "text-slate-300";
          return (
            <div className="grid grid-cols-1 lg:grid-cols-3 gap-5">
              <Panel title="Current Reading">
                <p className="font-display text-5xl font-normal tracking-tight text-white" data-testid="mm-breadth-value">{value.toFixed(1)}%</p>
                <p className={`font-mono-ui text-xs uppercase tracking-wider mt-2 ${zoneColor}`}>{zone}</p>
                <p className="text-xs text-slate-500 mt-4 leading-relaxed">
                  {latest?.resolved} of {latest?.total} constituents resolved on {latest?.date}.
                </p>
              </Panel>
              <div className="lg:col-span-2">
                <Panel title="Series" subtitle={`${d.box_pct}% box, ${d.reversal_boxes}-box reversal · ${series.length} points`}>
                  <Sparkline series={series} />
                  <p className="text-xs text-slate-500 mt-4 leading-relaxed">
                    Above 75% or below 25% is an extreme zone — trends can sit there for a long stretch, so treat it as
                    a caution flag for fresh entries, not a standalone reversal trigger.
                  </p>
                  <Disclaimer />
                </Panel>
              </div>
            </div>
          );
        }}
      </ModuleShell>
    </div>
  );
};

/** Minimal inline sparkline — avoids pulling a chart library into a view
    that only ever shows one 0-100 series. */
const Sparkline = ({ series }) => {
  const points = useMemo(() => {
    const tail = (series || []).slice(-260);
    if (tail.length < 2) return "";
    const w = 600;
    const h = 140;
    return tail
      .map((p, i) => `${(i / (tail.length - 1)) * w},${h - (p.value / 100) * h}`)
      .join(" ");
  }, [series]);
  if (!points) return <p className="text-sm text-slate-500">Not enough points to plot.</p>;
  return (
    <svg viewBox="0 0 600 140" className="w-full h-auto" preserveAspectRatio="none" data-testid="mm-breadth-sparkline">
      <line x1="0" y1="35" x2="600" y2="35" stroke="rgba(248,113,113,0.25)" strokeDasharray="4 4" />
      <line x1="0" y1="105" x2="600" y2="105" stroke="rgba(52,211,153,0.25)" strokeDasharray="4 4" />
      <polyline points={points} fill="none" stroke="#4B8DF8" strokeWidth="1.5" vectorEffect="non-scaling-stroke" />
    </svg>
  );
};

/* ---------------------------- Relative Strength ---------------------------- */

const BOX_SIZES = [
  { label: "Short term", value: 1 },
  { label: "Medium term", value: 3 },
  { label: "Long term", value: 5 },
];

export const MMRelativeStrength = ({ market }) => {
  const [group, setGroup] = useState(null);
  const [boxPct, setBoxPct] = useState(3);
  const [groups, setGroups] = useState([]);

  useEffect(() => {
    axios.get(`${API}/markets/${market}/modules`)
      .then((r) => setGroups(r.data?.groups || []))
      .catch(() => setGroups([]));
  }, [market]);

  const active = group || groups[0];
  const { loading, error, data } = useModuleData(
    active ? `/markets/${market}/relative-strength?group=${encodeURIComponent(active)}&box_pct=${boxPct}` : null,
    { skip: !active },
  );

  return (
    <div>
      {groups.length > 0 && <GroupTabs groups={groups} active={active} onChange={setGroup} />}
      <div className="flex flex-wrap items-center gap-2 mb-5">
        {BOX_SIZES.map((b) => (
          <button
            key={b.value}
            type="button"
            onClick={() => setBoxPct(b.value)}
            className={`px-3 py-1.5 rounded-lg font-mono-ui text-[11px] border transition-colors ${
              boxPct === b.value ? "border-sapphire-light/50 bg-sapphire/10 text-white" : "border-white/10 text-slate-500 hover:text-slate-300"
            }`}
            data-testid={`mm-box-${b.value}`}
          >
            {b.label} · {b.value}%
          </button>
        ))}
      </div>
      <ModuleShell loading={loading || !active} error={error} data={data} loadingLabel="Building pairwise matrix">
        {(d) => {
          const ranked = Object.entries(d.scores || {}).sort((a, b) => b[1] - a[1]);
          const maxScore = (d.symbols?.length || 1) - 1;
          return (
            <Panel
              title="Pairwise Strength"
              subtitle={`${d.universe_resolved} of ${d.universe_total} resolved · ${d.box_pct}% box, ${d.reversal_boxes}-box reversal`}
            >
              <div className="space-y-2">
                {ranked.map(([symbol, score], i) => (
                  <motion.div
                    key={symbol}
                    initial={{ opacity: 0, x: -8 }}
                    animate={{ opacity: 1, x: 0 }}
                    transition={{ duration: 0.4, ease: EASE, delay: i * 0.03 }}
                    className="flex items-center gap-3"
                    data-testid={`mm-rs-row-${symbol}`}
                  >
                    <span className="font-mono-ui text-xs text-slate-500 w-6 shrink-0">{i + 1}</span>
                    <span className="text-sm font-semibold text-white w-28 shrink-0 truncate">{symbol}</span>
                    <div className="flex-1 h-2 rounded-full bg-white/[0.05] overflow-hidden">
                      <div
                        className="h-full rounded-full bg-sapphire"
                        style={{ width: `${maxScore ? (score / maxScore) * 100 : 0}%` }}
                      />
                    </div>
                    <span className="font-mono-ui text-xs text-slate-400 w-16 text-right shrink-0">
                      {score}/{maxScore}
                    </span>
                  </motion.div>
                ))}
              </div>
              <p className="text-xs text-slate-500 mt-5 leading-relaxed">
                Each score is how many of that instrument's pairwise ratio charts currently favour it. Unresolved pairs
                (not enough ratio movement to print a column at this box size) are excluded from both sides, never
                counted as a coin flip.
              </p>
              <Disclaimer />
            </Panel>
          );
        }}
      </ModuleShell>
    </div>
  );
};

/* ------------------------------ Ranking tables ----------------------------- */

const RankingTable = ({ market, slug, columns, title, subtitle, loadingLabel }) => {
  const { loading, error, data } = useModuleData(`/markets/${market}/${slug}/top?limit=25`);
  return (
    <ModuleShell loading={loading} error={error} data={data} loadingLabel={loadingLabel}>
      {(d) => {
        if (!d.has_data) return <ErrorNote message={d.reason || "This ranking hasn't been computed yet."} />;
        const rows = d.rows || [];
        if (!rows.length) return <ErrorNote message="No instruments met the minimum history requirement." />;
        return (
          <Panel title={title} subtitle={subtitle || d.methodology}>
            <div className="overflow-x-auto">
              <table className="w-full text-left min-w-[520px]">
                <thead>
                  <tr className="border-b border-white/10">
                    <th className={`${LABEL} pb-3 pr-4`}>#</th>
                    <th className={`${LABEL} pb-3 pr-4`}>Symbol</th>
                    {columns.map((c) => (
                      <th key={c.key} className={`${LABEL} pb-3 pr-4 text-right whitespace-nowrap`}>{c.label}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {rows.map((r, i) => (
                    <tr key={r.symbol} className="border-b border-white/[0.05] last:border-0" data-testid={`mm-rank-row-${i}`}>
                      <td className="py-3 pr-4 font-mono-ui text-xs text-slate-500">{i + 1}</td>
                      <td className="py-3 pr-4">
                        <span className="text-sm font-semibold text-white">{r.symbol}</span>
                        {r.name && <span className="block text-xs text-slate-500 truncate max-w-[200px]">{r.name}</span>}
                      </td>
                      {columns.map((c) => (
                        <td key={c.key} className="py-3 pr-4 text-right font-mono-ui text-sm text-slate-300 whitespace-nowrap">
                          {c.render ? c.render(r[c.key]) : fmt(r[c.key], 3)}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <Disclaimer />
          </Panel>
        );
      }}
    </ModuleShell>
  );
};

export const MMMomentumInvesting = ({ market }) => (
  <RankingTable
    market={market}
    slug="momentum-investing"
    title="Risk-Adjusted Momentum"
    loadingLabel="Loading momentum ranking"
    columns={[
      { key: "momentum_score", label: "Score" },
      { key: "return_12_1", label: "12-1 Return", render: (v) => (v == null ? "—" : `${(v * 100).toFixed(1)}%`) },
      { key: "volatility", label: "Volatility", render: (v) => (v == null ? "—" : `${(v * 100).toFixed(1)}%`) },
    ]}
  />
);

export const MMMomentumLeaders = ({ market }) => (
  <RankingTable
    market={market}
    slug="momentum-engine"
    title="Momentum Leaders"
    loadingLabel="Loading momentum leaders"
    columns={[
      { key: "score", label: "Score" },
      { key: "return_1w", label: "1W", render: (v) => pct(v, 1) },
      { key: "return_1m", label: "1M", render: (v) => pct(v, 1) },
    ]}
  />
);

export const MMSharpe = ({ market }) => (
  <RankingTable
    market={market}
    slug="sharpe-dashboard"
    title="Risk-Adjusted Ranking"
    subtitle="Annualized Sharpe and Sortino with maximum drawdown, over at least one year of daily bars."
    loadingLabel="Loading risk statistics"
    columns={[
      { key: "sharpe", label: "Sharpe" },
      { key: "sortino", label: "Sortino" },
      { key: "max_drawdown", label: "Max DD", render: (v) => (v == null ? "—" : `${(v * 100).toFixed(1)}%`) },
    ]}
  />
);

/* ------------------------------- EWMA Scanner ------------------------------ */

export const MMEwma = ({ market }) => {
  const [symbol, setSymbol] = useState(market === "crypto" ? "BTCUSDT" : market === "forex" ? "EURUSD" : "AAPL");
  const [fast, setFast] = useState(20);
  const [slow, setSlow] = useState(50);
  const { loading, error, data } = useModuleData(
    `/markets/${market}/ewma?symbol=${encodeURIComponent(symbol)}&fast=${fast}&slow=${slow}`,
  );

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-end gap-3">
        <div className="w-full max-w-xs"><SymbolPicker market={market} value={symbol} onChange={setSymbol} /></div>
        {[["Fast", fast, setFast], ["Slow", slow, setSlow]].map(([label, val, set]) => (
          <div key={label}>
            <p className={`${LABEL} mb-1.5`}>{label} span</p>
            <input
              type="number"
              min="2"
              value={val}
              onChange={(e) => set(Math.max(2, Number(e.target.value) || 2))}
              className="w-24 rounded-xl border border-white/10 bg-white/[0.03] px-3 py-2.5 text-sm text-white outline-none focus:border-sapphire-light/50 transition-colors"
              data-testid={`mm-ewma-${label.toLowerCase()}`}
            />
          </div>
        ))}
      </div>
      <ModuleShell loading={loading} error={error} data={data} loadingLabel="Running crossover backtest">
        {(d) => {
          const strat = d.stats?.strategy_return;
          const bh = d.stats?.buy_and_hold_return;
          const beat = strat != null && bh != null && strat > bh;
          return (
            <Panel
              title="Crossover vs Buy & Hold"
              subtitle={`${d.symbol} · evaluated ${d.evaluated_from} → ${d.evaluated_to} (${d.evaluated_bars} bars)`}
            >
              <div className="grid grid-cols-2 gap-5 mb-5">
                <div>
                  <p className={LABEL}>Strategy</p>
                  <p className={`font-display text-3xl font-normal tracking-tight mt-1 ${beat ? "text-emerald-300" : "text-white"}`}>
                    {strat == null ? "—" : `${(strat * 100).toFixed(1)}%`}
                  </p>
                </div>
                <div>
                  <p className={LABEL}>Buy &amp; Hold</p>
                  <p className="font-display text-3xl font-normal tracking-tight text-slate-400 mt-1">
                    {bh == null ? "—" : `${(bh * 100).toFixed(1)}%`}
                  </p>
                </div>
              </div>
              <p className="text-xs text-slate-500 leading-relaxed">
                {d.markers?.length || 0} crossover events over the evaluated window. Always shown against its own
                buy-and-hold benchmark — a strategy return means little without it.
              </p>
              <Disclaimer />
            </Panel>
          );
        }}
      </ModuleShell>
    </div>
  );
};

/* -------------------------------- Gamma Pulse ------------------------------ */

export const MMGammaPulse = ({ market }) => {
  const [symbols, setSymbols] = useState([]);
  const [symbol, setSymbol] = useState(null);

  useEffect(() => {
    axios.get(`${API}/markets/${market}/option-underlyings`)
      .then((r) => {
        setSymbols(r.data?.symbols || []);
        setSymbol((s) => s || (r.data?.symbols || [])[0] || null);
      })
      .catch(() => setSymbols([]));
  }, [market]);

  const { loading, error, data } = useModuleData(
    symbol ? `/markets/${market}/gamma-pulse?symbol=${encodeURIComponent(symbol)}` : `/markets/${market}/gamma-pulse`,
  );

  return (
    <div className="space-y-5">
      {symbols.length > 0 && <GroupTabs groups={symbols} active={symbol} onChange={setSymbol} />}
      <ModuleShell loading={loading} error={error} data={data} loadingLabel="Reading option legs">
        {(d) => (
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-5">
            <Panel title="Verdict">
              <BiasBadge bias={d.verdict} testid="mm-gamma-verdict" />
              <p className="text-xs text-slate-500 mt-4 leading-relaxed">
                Bullish needs the future and call both up with the put down; Bearish is the mirror image. Anything
                else — including a leg without enough history to have a direction — is Neutral.
              </p>
            </Panel>
            <div className="lg:col-span-2">
              <Panel
                title="Three Pillars"
                subtitle={`${d.symbol} · ATM ${fmt(d.strike, 2)} · expiry ${d.expiry}${d.expiry_is_monthly ? " (monthly)" : ""}`}
              >
                <div className="space-y-3">
                  {[["Future", d.legs?.future], ["ATM Call", d.legs?.call], ["ATM Put", d.legs?.put]].map(([label, leg]) => (
                    <div key={label} className="flex items-center justify-between py-2 border-b border-white/[0.05] last:border-0">
                      <span className="text-sm text-slate-300">{label}</span>
                      <TrendPill value={leg?.direction} bars={leg?.bars} />
                    </div>
                  ))}
                </div>
                {d.is_proxy && (
                  <p className="text-xs text-amber-300/80 mt-4 leading-relaxed">
                    Options read from {d.proxy_label} — the index itself has no directly optionable product on this feed.
                  </p>
                )}
                <p className="text-xs text-slate-500 mt-4 leading-relaxed">
                  A listed option only exists between listing and expiry, so a leg can genuinely lack the history to
                  print a column. That reads Neutral by design — the bar count above shows which case you're looking at.
                </p>
                <Disclaimer />
              </Panel>
            </div>
          </div>
        )}
      </ModuleShell>
    </div>
  );
};

/* -------------------------------- Index Vector ----------------------------- */

export const MMIndexVector = ({ market }) => {
  const [symbols, setSymbols] = useState([]);
  const [symbol, setSymbol] = useState(null);

  useEffect(() => {
    axios.get(`${API}/markets/${market}/option-underlyings`)
      .then((r) => {
        setSymbols(r.data?.symbols || []);
        setSymbol((s) => s || (r.data?.symbols || [])[0] || null);
      })
      .catch(() => setSymbols([]));
  }, [market]);

  const { loading, error, data } = useModuleData(
    symbol ? `/markets/${market}/index-vector?symbol=${encodeURIComponent(symbol)}` : `/markets/${market}/index-vector`,
  );

  return (
    <div className="space-y-5">
      {symbols.length > 0 && <GroupTabs groups={symbols} active={symbol} onChange={setSymbol} />}
      <ModuleShell loading={loading} error={error} data={data} loadingLabel="Computing confluence">
        {(d) => (
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-5">
            <Panel title="Directional Bias">
              <BiasBadge bias={d.bias} testid="mm-vector-bias" />
              <p className="font-mono-ui text-xs text-slate-500 mt-4">
                Spot <span className="text-slate-300">{fmt(d.spot, 2)}</span>
              </p>
              <p className="font-mono-ui text-xs text-slate-500 mt-1">
                ATM <span className="text-slate-300">{fmt(d.atm, 2)}</span> · expiry <span className="text-slate-300">{d.expiry}</span>
              </p>
              <p className="text-xs text-slate-500 mt-4 leading-relaxed">
                Confirmation, not a standalone entry signal — all four legs must agree before a direction is called.
              </p>
            </Panel>
            <div className="lg:col-span-2">
              <Panel
                title="Four-Leg Confluence"
                subtitle={`Straddles ${d.box_size} × ${d.reversal} · ATM legs ${d.atm_leg_box_size} × ${d.atm_leg_reversal}`}
              >
                <div className="space-y-3">
                  {[
                    [`Straddle @ ${fmt(d.up_strike, 2)}`, d.legs?.up_straddle],
                    [`Straddle @ ${fmt(d.down_strike, 2)}`, d.legs?.down_straddle],
                    ["ATM Call", d.legs?.atm_call],
                    ["ATM Put", d.legs?.atm_put],
                  ].map(([label, leg]) => (
                    <div key={label} className="flex items-center justify-between py-2 border-b border-white/[0.05] last:border-0">
                      <span className="text-sm text-slate-300">{label}</span>
                      <TrendPill value={leg?.trend} bars={leg?.bars} />
                    </div>
                  ))}
                </div>
                {d.is_proxy && (
                  <p className="text-xs text-amber-300/80 mt-4 leading-relaxed">
                    Read from {d.proxy_label} — the index itself has no directly optionable product on this feed.
                  </p>
                )}
                <Disclaimer />
              </Panel>
            </div>
          </div>
        )}
      </ModuleShell>
    </div>
  );
};

/* ------------------------------- Peter Tingle ------------------------------ */

export const MMPeterTingle = ({ market }) => {
  const [symbol, setSymbol] = useState("AAPL");
  const { loading, error, data } = useModuleData(`/markets/${market}/peter-tingle?symbol=${encodeURIComponent(symbol)}`);

  return (
    <div className="space-y-5">
      <div className="max-w-sm"><SymbolPicker market={market} value={symbol} onChange={setSymbol} /></div>
      <ModuleShell loading={loading} error={error} data={data} loadingLabel="Running caution scan">
        {(d) => {
          const flags = [...(d.technical_flags || []), ...(d.fundamental_flags || [])];
          return (
            <Panel title="Caution Scan" subtitle={`${d.symbol} · ${flags.length} rules evaluated`}>
              <div className="mb-5"><BiasBadge bias={d.verdict} testid="mm-tingle-verdict" /></div>
              <div className="space-y-2">
                {flags.map((f) => (
                  <div key={f.rule} className="flex items-start justify-between gap-4 py-2.5 border-b border-white/[0.05] last:border-0">
                    <div>
                      <p className="text-sm text-slate-300">{f.rule}</p>
                      {f.detail && <p className="text-xs text-slate-500 mt-0.5 leading-relaxed">{f.detail}</p>}
                    </div>
                    <span
                      className={`font-mono-ui text-[11px] uppercase tracking-wider shrink-0 ${
                        f.status === "FAIL" ? "text-red-300" : f.status === "WARN" ? "text-amber-300" : "text-emerald-300"
                      }`}
                    >
                      {f.status}
                    </span>
                  </div>
                ))}
              </div>
              <p className="text-xs text-slate-500 mt-5 leading-relaxed">
                Treat any FAIL as a specific, named reason to dig deeper — not a verdict to trade on by itself.
              </p>
              <Disclaimer />
            </Panel>
          );
        }}
      </ModuleShell>
    </div>
  );
};

/* --------------------------- No-formula placeholder ------------------------ */

export const MMUnavailable = ({ module }) => (
  <Unavailable
    title="Coming Soon"
    reason={module?.reason || "This module has no computable definition for this market yet."}
  />
);
