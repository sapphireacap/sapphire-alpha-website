import { useState, useEffect } from "react";
import axios from "axios";
import { toast } from "sonner";
import { Loader2, ArrowUpDown } from "lucide-react";
import { LoadingParticles, EmptyState, field, label } from "./QuantLab";
import { openTradingViewChart } from "../AlphaTerminal";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;

const fmtNum = (v, dp = 2) => (v === null || v === undefined ? "—" : Number(v).toFixed(dp));
const fmtPctSigned = (v, dp = 2) => (v === null || v === undefined ? "—" : `${v > 0 ? "+" : ""}${Number(v).toFixed(dp)}%`);
const displaySymbol = (r) => (r.resolved_symbol || r.symbol || "").replace(/-EQ$/, "");

const SORT_ACCESSORS = {
  symbol: (r) => displaySymbol(r),
  return_pct: (r) => r.return_pct,
  volar_score: (r) => (r.volar_score ?? -Infinity),
  retracement_pct: (r) => r.retracement_pct,
  total_volume: (r) => r.total_volume,
};

const ResultsTable = ({ results }) => {
  const [sortKey, setSortKey] = useState("volar_score");
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

  const Header = ({ k, children, align = "left" }) => (
    <th
      onClick={() => toggleSort(k)}
      className={`px-6 py-5 font-mono-ui text-[11px] uppercase tracking-[0.18em] text-slate-500 font-semibold whitespace-nowrap cursor-pointer select-none hover:text-slate-300 transition-colors text-${align}`}
      data-testid={`intraday-momentum-header-${k}`}
    >
      <span className="inline-flex items-center gap-1.5">
        {children}
        <ArrowUpDown size={11} className={sortKey === k ? "text-sapphire-light" : "text-slate-700"} />
      </span>
    </th>
  );

  return (
    <div className="glass rounded-2xl overflow-hidden" data-testid="intraday-momentum-results-table">
      <div className="hidden md:block">
        <table className="w-full text-left">
          <thead>
            <tr className="border-b border-white/10">
              <Header k="symbol">Symbol</Header>
              <Header k="return_pct" align="right">Return%</Header>
              <Header k="volar_score" align="right">VOLAR</Header>
              <Header k="retracement_pct" align="right">Retracement%</Header>
              <Header k="total_volume" align="right">Volume</Header>
            </tr>
          </thead>
          <tbody>
            {sorted.map((r, i) => (
              <tr
                key={r.symbol}
                onClick={() => openTradingViewChart(displaySymbol(r))}
                className="group border-b border-white/[0.05] last:border-0 hover:bg-sapphire/[0.06] transition-colors duration-300 cursor-pointer"
                data-testid={`intraday-momentum-row-${i}`}
              >
                <td className="px-6 py-4"><span className="font-display text-base font-bold text-white group-hover:underline">{displaySymbol(r)}</span></td>
                <td className={`px-6 py-4 font-mono-ui text-sm text-right ${r.return_pct >= 0 ? "text-emerald-400" : "text-red-400"}`}>{fmtPctSigned(r.return_pct)}</td>
                <td className="px-6 py-4 font-mono-ui text-sm text-right text-slate-300">{fmtNum(r.volar_score, 3)}</td>
                <td className="px-6 py-4 font-mono-ui text-sm text-right text-slate-400">{fmtNum(r.retracement_pct)}%</td>
                <td className="px-6 py-4 font-mono-ui text-sm text-right text-slate-400">{r.total_volume?.toLocaleString("en-IN") ?? "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="md:hidden divide-y divide-white/[0.06]">
        {sorted.map((r, i) => (
          <div key={r.symbol} onClick={() => openTradingViewChart(displaySymbol(r))} className="p-5 cursor-pointer" data-testid={`intraday-momentum-card-${i}`}>
            <div className="flex items-center justify-between mb-2">
              <p className="font-display text-lg font-bold text-white">{displaySymbol(r)}</p>
              <span className={`text-sm font-mono-ui ${r.return_pct >= 0 ? "text-emerald-400" : "text-red-400"}`}>{fmtPctSigned(r.return_pct)}</span>
            </div>
            <div className="flex items-center gap-6 text-sm">
              <div>
                <p className="font-mono-ui text-[10px] uppercase tracking-[0.18em] text-slate-500 mb-1">VOLAR</p>
                <span className="text-slate-300">{fmtNum(r.volar_score, 3)}</span>
              </div>
              <div>
                <p className="font-mono-ui text-[10px] uppercase tracking-[0.18em] text-slate-500 mb-1">Retracement</p>
                <span className="text-slate-400">{fmtNum(r.retracement_pct)}%</span>
              </div>
              <div>
                <p className="font-mono-ui text-[10px] uppercase tracking-[0.18em] text-slate-500 mb-1">Volume</p>
                <span className="text-slate-400">{r.total_volume?.toLocaleString("en-IN") ?? "—"}</span>
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
};

const EMA_CHOICES = [10, 20, 50, 100, 200];

const IntradayMomentumScannerTool = () => {
  const [period, setPeriod] = useState(20);
  const [emaSelected, setEmaSelected] = useState([]);
  const [minVolume, setMinVolume] = useState("");
  const [maxRetracement, setMaxRetracement] = useState("");
  const [relative, setRelative] = useState(false);
  const [denominator, setDenominator] = useState("NIFTY");
  const [topN, setTopN] = useState(25);
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState(null);
  const [refreshStatus, setRefreshStatus] = useState(null);

  const toggleEma = (p) => {
    setEmaSelected((cur) => (cur.includes(p) ? cur.filter((x) => x !== p) : [...cur, p]));
  };

  const runScan = async () => {
    setLoading(true);
    setResult(null);
    try {
      const body = {
        period: Number(period),
        ema_periods: emaSelected,
        min_volume: minVolume ? Number(minVolume) : null,
        max_retracement_pct: maxRetracement ? Number(maxRetracement) : null,
        relative,
        denominator: relative ? denominator.trim().toUpperCase() : null,
        top_n: Number(topN),
      };
      const { data } = await axios.post(`${API}/intraday-momentum/scan`, body);
      setResult(data);
      if (!data.found) {
        axios.get(`${API}/intraday-momentum/refresh-status`).then((r) => setRefreshStatus(r.data)).catch(() => {});
      }
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Scan failed. Please try again.");
    } finally {
      setLoading(false);
    }
  };

  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { runScan(); }, []);

  return (
    <div className="mt-6" data-testid="intraday-momentum-tool">
      <div className="glass rounded-2xl border border-white/10 p-5 md:p-6 mb-6">
        <p className="font-mono-ui text-[10px] uppercase tracking-[0.24em] text-sapphire-light mb-4 pb-4 border-b border-white/10">
          Scan Parameters
        </p>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-4">
          <div>
            <label className={label}>Period (5-min bars)</label>
            <input type="number" min={2} max={149} value={period} onChange={(e) => setPeriod(e.target.value)} className={field} data-testid="intraday-momentum-period" />
          </div>
          <div>
            <label className={label}>Min Volume</label>
            <input type="number" min={0} value={minVolume} onChange={(e) => setMinVolume(e.target.value)} placeholder="No minimum" className={field} data-testid="intraday-momentum-min-volume" />
          </div>
          <div>
            <label className={label}>Max Retracement %</label>
            <input type="number" min={0} value={maxRetracement} onChange={(e) => setMaxRetracement(e.target.value)} placeholder="No limit" className={field} data-testid="intraday-momentum-max-retracement" />
          </div>
          <div>
            <label className={label}>Top N</label>
            <input type="number" min={1} max={100} value={topN} onChange={(e) => setTopN(e.target.value)} className={field} data-testid="intraday-momentum-top-n" />
          </div>
        </div>

        <label className={label}>EMA Filter — must be trading above every EMA selected</label>
        <div className="flex flex-wrap gap-2 mb-4">
          {EMA_CHOICES.map((p) => (
            <button
              key={p}
              onClick={() => toggleEma(p)}
              className={`rounded-full border px-3 py-1.5 font-mono-ui text-[11px] transition-colors duration-300 ${
                emaSelected.includes(p) ? "border-sapphire/40 bg-sapphire/10 text-sapphire-light" : "border-white/10 text-slate-500 hover:text-slate-300 hover:border-white/20"
              }`}
              data-testid={`intraday-momentum-ema-${p}`}
            >
              {p}-EMA
            </button>
          ))}
        </div>

        <label className="flex items-center gap-2 mb-4 cursor-pointer select-none">
          <input type="checkbox" checked={relative} onChange={(e) => setRelative(e.target.checked)} data-testid="intraday-momentum-relative-toggle" />
          <span className="text-sm text-slate-300">Relative momentum (score off a ratio chart against a denominator)</span>
        </label>
        {relative && (
          <div className="mb-4">
            <label className={label}>Denominator Symbol</label>
            <input value={denominator} onChange={(e) => setDenominator(e.target.value)} className={field + " w-48"} data-testid="intraday-momentum-denominator" />
          </div>
        )}

        <button onClick={runScan} disabled={loading} className="btn-sapphire disabled:opacity-50" data-testid="intraday-momentum-scan-btn">
          {loading ? <><Loader2 size={16} className="animate-spin" /> Scanning</> : "Scan"}
        </button>
      </div>

      {loading && <LoadingParticles title="Scanning the Universe" subtitle="Reading intraday closes · Scoring VOLAR · Applying filters" />}

      {!loading && result && !result.found && (
        <div>
          <EmptyState reason={result.reason || "No result found."} />
          {refreshStatus?.status === "running" && (
            <p className="text-center text-xs text-slate-500 mt-3 font-mono-ui" data-testid="intraday-momentum-refresh-progress">
              Refresh in progress — {refreshStatus.done}/{refreshStatus.total} constituents processed.
            </p>
          )}
        </div>
      )}

      {!loading && result && result.found && (
        <div data-testid="intraday-momentum-results">
          <p className="text-xs text-slate-500 mb-4 font-mono-ui">
            {result.qualified} qualifying of {result.universe_coverage.cached} cached ({result.universe_coverage.fresh} refreshed within the last 10 minutes) — showing top {result.results.length}.
          </p>
          {result.results.length === 0 ? (
            <EmptyState reason="No stock matched every filter this scan." />
          ) : (
            <ResultsTable results={result.results} />
          )}
          <p className="text-[11px] font-light text-slate-600 mt-4 max-w-2xl">
            VOLAR is Return% divided by the volatility realized over the same period — Definedge's own public term for a risk-adjusted return score, adapted here to intraday bars. Retracement% is the pullback from the period's own high, not a 52-week/all-time reference. Not investment advice.
          </p>
        </div>
      )}
    </div>
  );
};

export default IntradayMomentumScannerTool;
