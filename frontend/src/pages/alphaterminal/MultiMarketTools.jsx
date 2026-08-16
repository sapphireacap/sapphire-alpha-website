import { useCallback, useEffect, useMemo, useState } from "react";
import axios from "axios";
import { motion } from "framer-motion";
import { AlertTriangle, Lock, Search, TrendingDown, TrendingUp, Minus } from "lucide-react";
import LoadingBar from "../../components/site/LoadingBar";
import BiasBadge from "../../components/site/BiasBadge";
import { StraddleCompass } from "../AlphaTerminal";

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

/* --------------------------------- Breadth --------------------------------- */

/* ---------------------------- Relative Strength ---------------------------- */

const BOX_SIZES = [
  { label: "Short term", value: 1 },
  { label: "Medium term", value: 3 },
  { label: "Long term", value: 5 },
];

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

/* -------------------------------- Gamma Pulse ------------------------------ */

/* -------------------------------- Index Vector ----------------------------- */

// Renders the SAME StraddleCompass grid the India tab renders, in the same
// 2-1 formation, from the same BIAS_STYLE palette. Index Vector must look
// identical on every market tab -- only the endpoint feeding it differs.
export const MMIndexVector = ({ market }) => {
  const [symbols, setSymbols] = useState([]);
  const [signals, setSignals] = useState({});
  const [state, setState] = useState({ loading: true, error: null, blocked: null });

  useEffect(() => {
    let cancelled = false;
    setState({ loading: true, error: null, blocked: null });
    setSignals({});

    axios.get(`${API}/markets/${market}/option-underlyings`)
      .then(async (r) => {
        const list = r.data?.symbols || [];
        if (cancelled) return;
        setSymbols(list);
        const results = await Promise.all(list.map((sym) =>
          axios.get(`${API}/markets/${market}/index-vector`, { params: { symbol: sym } })
            .then((res) => [sym, res.data])
            .catch(() => [sym, null]),
        ));
        if (cancelled) return;
        const blocked = results.find(([, d]) => d && d.available === false);
        if (blocked) { setState({ loading: false, error: null, blocked: blocked[1].reason }); return; }
        setSignals(Object.fromEntries(results.filter(([, d]) => d)));
        setState({ loading: false, error: null, blocked: null });
      })
      .catch(() => {
        if (!cancelled) setState({ loading: false, error: "Data is temporarily unavailable — please try again shortly.", blocked: null });
      });
    return () => { cancelled = true; };
  }, [market]);

  if (state.loading) return <LoadingBar inline label="Computing confluence" />;
  if (state.blocked) return <Unavailable reason={state.blocked} />;
  if (state.error) return <ErrorNote message={state.error} />;
  if (!symbols.length) return <ErrorNote message="No index underlying available for this market." />;

  return (
    <div className="grid grid-cols-1 md:grid-cols-2 gap-4" data-testid="vector-index-grid">
      {symbols.map((sym, i) => {
        const isLastOfOdd = i === symbols.length - 1 && symbols.length % 2 === 1;
        const d = signals[sym];
        // StraddleCompass expects the India signal shape: spot is a
        // preformatted string there, a float here — normalised, not
        // reshaped, so the component itself needs no market branch.
        const signal = d ? { ...d, spot: d.spot == null ? null : Number(d.spot).toLocaleString("en-US", { maximumFractionDigits: 2 }) } : null;
        return (
          <div key={sym} className={isLastOfOdd ? "md:col-span-2" : ""}>
            <StraddleCompass signal={signal} index={sym} livePoll={false} />
          </div>
        );
      })}
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
