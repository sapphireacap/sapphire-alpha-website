import { useState, useEffect } from "react";
import axios from "axios";
import { toast } from "sonner";
import { Loader2, ArrowUpDown } from "lucide-react";
import { LoadingParticles, EmptyState, field, label } from "./QuantLab";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;

const MODES = [
  { key: "compare", title: "Compare Stocks" },
  { key: "top", title: "Top Ranked" },
];

const fmtNum = (v, digits = 2) => (v === null || v === undefined ? "—" : Number(v).toFixed(digits));
const fmtPctStat = (v) => (v === null || v === undefined ? "—" : `${(Number(v) * 100).toFixed(2)}%`);
const displaySymbol = (r) => (r.resolved_symbol || r.symbol || "").replace(/-EQ$/, "");

const SymbolMultiSelect = ({ universe, selected, onChange, max = 10 }) => {
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState(false);
  const selectedSet = new Set(selected);
  const atMax = selected.length >= max;

  const matches = query.trim() && !atMax
    ? universe
        .filter((s) => !selectedSet.has(s.symbol))
        .filter((s) => {
          const q = query.trim().toLowerCase();
          return s.symbol.toLowerCase().includes(q) || s.company_name.toLowerCase().includes(q);
        })
        .slice(0, 8)
    : [];

  const addSymbol = (symbol) => {
    if (selected.length >= max) return;
    onChange([...selected, symbol]);
    setQuery("");
  };
  const removeSymbol = (symbol) => onChange(selected.filter((s) => s !== symbol));

  return (
    <div>
      {selected.length > 0 && (
        <div className="flex flex-wrap gap-2 mb-3" data-testid="sharpe-selected-chips">
          {selected.map((sym) => (
            <span key={sym} className="inline-flex items-center gap-1.5 rounded-full border border-white/15 bg-white/5 px-3 py-1 text-xs text-slate-300 font-mono-ui">
              {sym}
              <button type="button" onClick={() => removeSymbol(sym)} className="text-slate-500 hover:text-red-400" data-testid={`sharpe-remove-${sym}`}>×</button>
            </span>
          ))}
        </div>
      )}
      <div className="relative">
        <input
          value={query}
          onChange={(e) => { setQuery(e.target.value); setOpen(true); }}
          onFocus={() => setOpen(true)}
          onBlur={() => setTimeout(() => setOpen(false), 150)}
          className={field}
          placeholder={atMax ? `Maximum ${max} symbols selected` : "Search Nifty 500 by symbol or company name"}
          disabled={atMax}
          data-testid="sharpe-symbol-search"
        />
        {open && matches.length > 0 && (
          <div className="absolute z-20 mt-1 w-full max-h-64 overflow-y-auto rounded-md border border-white/10 bg-[#0A0D18] shadow-xl">
            {matches.map((s) => (
              <button
                type="button"
                key={s.symbol}
                onMouseDown={(e) => e.preventDefault()}
                onClick={() => addSymbol(s.symbol)}
                className="w-full text-left px-3 py-2 text-sm hover:bg-sapphire/10 transition-colors flex items-center justify-between gap-3"
                data-testid={`sharpe-option-${s.symbol}`}
              >
                <span className="font-mono-ui text-xs text-sapphire-light shrink-0">{s.symbol}</span>
                <span className="text-slate-500 text-xs truncate">{s.company_name}</span>
              </button>
            ))}
          </div>
        )}
      </div>
    </div>
  );
};

const SORT_ACCESSORS = {
  symbol: (r) => displaySymbol(r),
  sharpe: (r) => (r.stats.sharpe ?? -Infinity),
  sortino: (r) => (r.stats.sortino ?? -Infinity),
  max_drawdown: (r) => (r.stats.max_drawdown ?? -Infinity),
};

const ResultsTable = ({ results }) => {
  const [sortKey, setSortKey] = useState("sharpe");
  const [sortDir, setSortDir] = useState("desc");

  const toggleSort = (key) => {
    if (sortKey === key) setSortDir((d) => (d === "desc" ? "asc" : "desc"));
    else { setSortKey(key); setSortDir("desc"); }
  };

  const sorted = [...results].sort((a, b) => {
    const av = SORT_ACCESSORS[sortKey](a);
    const bv = SORT_ACCESSORS[sortKey](b);
    if (av < bv) return sortDir === "asc" ? -1 : 1;
    if (av > bv) return sortDir === "asc" ? 1 : -1;
    return 0;
  });

  const Header = ({ k, children }) => (
    <th
      onClick={() => toggleSort(k)}
      className="px-6 py-5 font-mono-ui text-[11px] uppercase tracking-[0.18em] text-slate-500 font-semibold whitespace-nowrap cursor-pointer select-none hover:text-slate-300 transition-colors"
      data-testid={`sharpe-header-${k}`}
    >
      <span className="inline-flex items-center gap-1.5">
        {children}
        <ArrowUpDown size={11} className={sortKey === k ? "text-sapphire-light" : "text-slate-700"} />
      </span>
    </th>
  );

  return (
    <div className="glass rounded-2xl overflow-hidden" data-testid="sharpe-results-table">
      <div className="hidden md:block">
        <table className="w-full text-left">
          <thead>
            <tr className="border-b border-white/10">
              <Header k="symbol">Symbol</Header>
              <Header k="sharpe">Sharpe</Header>
              <Header k="sortino">Sortino</Header>
              <Header k="max_drawdown">Max Drawdown</Header>
            </tr>
          </thead>
          <tbody>
            {sorted.map((r, i) => (
              <tr key={r.symbol} className="border-b border-white/[0.05] last:border-0 hover:bg-sapphire/[0.06] transition-colors" data-testid={`sharpe-row-${i}`}>
                <td className="px-6 py-4"><span className="text-base font-bold text-white">{displaySymbol(r)}</span></td>
                <td className="px-6 py-4 font-mono-ui text-sm text-slate-300">{fmtNum(r.stats.sharpe)}</td>
                <td className="px-6 py-4 font-mono-ui text-sm text-slate-300">{fmtNum(r.stats.sortino)}</td>
                <td className="px-6 py-4 font-mono-ui text-sm text-red-300">{fmtPctStat(r.stats.max_drawdown)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="md:hidden divide-y divide-white/[0.06]">
        {sorted.map((r, i) => (
          <div key={r.symbol} className="p-5" data-testid={`sharpe-card-${i}`}>
            <p className="text-lg font-bold text-white mb-3">{displaySymbol(r)}</p>
            <div className="flex items-center gap-6 text-sm">
              <div>
                <p className="font-mono-ui text-[10px] uppercase tracking-[0.18em] text-slate-500 mb-1">Sharpe</p>
                <span className="text-slate-300">{fmtNum(r.stats.sharpe)}</span>
              </div>
              <div>
                <p className="font-mono-ui text-[10px] uppercase tracking-[0.18em] text-slate-500 mb-1">Sortino</p>
                <span className="text-slate-300">{fmtNum(r.stats.sortino)}</span>
              </div>
              <div>
                <p className="font-mono-ui text-[10px] uppercase tracking-[0.18em] text-slate-500 mb-1">Max DD</p>
                <span className="text-red-300">{fmtPctStat(r.stats.max_drawdown)}</span>
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
};

// Endpoint props let this same tool serve any market; the multi-market
// routes speak the identical quant-lab contract (see
// multi_market_routes' _dashboard). India defaults are unchanged.
const SharpeDashboardTool = ({
  universePath = "/quant-lab/nifty500-symbols",
  dashboardPath = "/quant-lab/sharpe-dashboard",
  statusPath = "/quant-lab/sharpe-refresh-status",
} = {}) => {
  const [mode, setMode] = useState("compare");
  const [universe, setUniverse] = useState([]);
  const [selected, setSelected] = useState([]);
  const [topN, setTopN] = useState(10);
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState(null);
  const [refreshStatus, setRefreshStatus] = useState(null);

  useEffect(() => {
    axios.get(`${API}${universePath}`).then((r) => setUniverse(r.data)).catch(() => {});
  }, [universePath]);

  const submit = async () => {
    setLoading(true);
    setResult(null);
    try {
      const body = mode === "compare"
        ? { mode: "compare", symbols: selected }
        : { mode: "top", top_n: Number(topN) };
      const { data } = await axios.post(`${API}${dashboardPath}`, body);
      setResult(data);
      if (!data.found && mode === "top") {
        axios.get(`${API}${statusPath}`).then((r) => setRefreshStatus(r.data)).catch(() => {});
      }
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Request failed. Please try again.");
    } finally {
      setLoading(false);
    }
  };

  const canSubmitCompare = selected.length >= 2 && selected.length <= 10;

  return (
    <div className="mt-6" data-testid="sharpe-tool">
      <div className="flex gap-2 mb-6">
        {MODES.map((m) => (
          <button
            key={m.key}
            onClick={() => { setMode(m.key); setResult(null); }}
            className={`rounded-full border px-4 py-2 font-mono-ui text-[11px] uppercase tracking-[0.14em] transition-colors duration-300 ${
              mode === m.key ? "border-sapphire/40 bg-sapphire/10 text-sapphire-light" : "border-white/10 text-slate-500 hover:text-slate-300 hover:border-white/20"
            }`}
            data-testid={`sharpe-mode-${m.key}`}
          >
            {m.title}
          </button>
        ))}
      </div>

      <div className="glass rounded-2xl border border-white/10 p-5 md:p-6 mb-6">
        <p className="font-mono-ui text-[10px] uppercase tracking-[0.24em] text-sapphire-light mb-4 pb-4 border-b border-white/10">
          {mode === "compare" ? "Custom Comparison" : "Custom Ranking"}
        </p>
        {mode === "compare" ? (
          <>
            <label className={label}>Symbols (2–10)</label>
            <SymbolMultiSelect universe={universe} selected={selected} onChange={setSelected} max={10} />
            <button
              onClick={submit}
              disabled={!canSubmitCompare || loading}
              className="btn-sapphire disabled:opacity-50 mt-4"
              data-testid="sharpe-compare-submit"
            >
              {loading ? <><Loader2 size={16} className="animate-spin" /> Running</> : "Compare"}
            </button>
          </>
        ) : (
          <div className="flex items-end gap-4">
            <div>
              <label className={label}>Top N</label>
              <input
                type="number" min={1} max={20} value={topN}
                onChange={(e) => setTopN(e.target.value)}
                className={field + " w-32"}
                data-testid="sharpe-top-n"
              />
            </div>
            <button
              onClick={submit}
              disabled={loading}
              className="btn-sapphire disabled:opacity-70 h-[42px]"
              data-testid="sharpe-top-submit"
            >
              {loading ? <><Loader2 size={16} className="animate-spin" /> Running</> : "Show Top Ranked"}
            </button>
          </div>
        )}
      </div>

      {loading && <LoadingParticles title="Computing Risk Stats" subtitle="Fetching history · Scoring Sharpe & Sortino · Ranking" />}

      {!loading && result && !result.found && (
        <div>
          <EmptyState reason={result.reason || "No result found."} />
          {mode === "top" && refreshStatus?.status === "running" && (
            <p className="text-center text-xs text-slate-500 mt-3 font-mono-ui" data-testid="sharpe-refresh-progress">
              Refresh in progress — {refreshStatus.done}/{refreshStatus.total} constituents processed.
            </p>
          )}
        </div>
      )}

      {!loading && result && result.found && (
        <div data-testid="sharpe-results">
          {mode === "top" && result.universe_coverage && (
            <p className="text-xs text-slate-500 mb-4 font-mono-ui">
              Ranked across {result.universe_coverage.cached} of ~{result.universe_coverage.total} Nifty 500 constituents cached today.
            </p>
          )}
          {mode === "compare" && result.skipped?.length > 0 && (
            <p className="text-xs text-amber-400/80 mb-4 font-mono-ui" data-testid="sharpe-skipped">
              Skipped: {result.skipped.map((s) => `${s.symbol} (${s.reason})`).join(", ")}
            </p>
          )}
          <ResultsTable results={result.results} />
          <p className="text-[11px] font-light text-slate-600 mt-4 max-w-2xl">
            Annualized Sharpe and Sortino computed over up to 10 years of daily returns (or since listing if shorter), against an assumed 6.5% risk-free rate. Max drawdown is the largest peak-to-trough decline over the same window. Past performance doesn't guarantee future results — not investment advice.
          </p>
        </div>
      )}
    </div>
  );
};

export default SharpeDashboardTool;
