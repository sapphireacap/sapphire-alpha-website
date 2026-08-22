import { useState, useEffect } from "react";
import axios from "axios";
import { Loader2, ArrowUpDown } from "lucide-react";
import { LoadingParticles, EmptyState } from "./QuantLab";
import { openTradingViewChart } from "../AlphaTerminal";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;

const fmtNum = (v) => (v === null || v === undefined ? "—" : Number(v).toFixed(2));
const fmtDateLong = (iso) => {
  if (!iso) return "—";
  const d = new Date(`${iso}T00:00:00`);
  return d.toLocaleDateString("en-GB", { day: "2-digit", month: "short", year: "numeric" });
};
const displaySymbol = (r) => (r.resolved_symbol || r.symbol || "").replace(/-EQ$/, "");

const SORT_ACCESSORS = {
  symbol: (r) => displaySymbol(r),
  label: (r) => r.label,
  bias: (r) => r.bias,
  date: (r) => r.date,
};

const ResultsTable = ({ results }) => {
  const [sortKey, setSortKey] = useState("date");
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
      data-testid={`swing-reversal-header-${k}`}
    >
      <span className="inline-flex items-center gap-1.5">
        {children}
        <ArrowUpDown size={11} className={sortKey === k ? "text-sapphire-light" : "text-slate-700"} />
      </span>
    </th>
  );

  return (
    <div className="glass rounded-2xl overflow-hidden" data-testid="swing-reversal-results-table">
      <div className="hidden md:block">
        <table className="w-full text-left">
          <thead>
            <tr className="border-b border-white/10">
              <Header k="symbol">Symbol</Header>
              <Header k="label">Pattern</Header>
              <Header k="bias">Bias</Header>
              <th className="px-6 py-5 font-mono-ui text-[11px] uppercase tracking-[0.18em] text-slate-500 font-semibold whitespace-nowrap text-right">Trigger</th>
              <th className="px-6 py-5 font-mono-ui text-[11px] uppercase tracking-[0.18em] text-slate-500 font-semibold whitespace-nowrap text-right">Stop-Loss</th>
              <Header k="date">Date</Header>
            </tr>
          </thead>
          <tbody>
            {sorted.map((r, i) => (
              <tr
                key={`${r.symbol}-${r.key}-${i}`}
                onClick={() => openTradingViewChart(displaySymbol(r))}
                className="group border-b border-white/[0.05] last:border-0 hover:bg-sapphire/[0.06] transition-colors duration-300 cursor-pointer"
                data-testid={`swing-reversal-row-${i}`}
              >
                <td className="px-6 py-4"><span className="font-display text-base font-bold text-white group-hover:underline">{displaySymbol(r)}</span></td>
                <td className="px-6 py-4 text-sm text-slate-300 whitespace-nowrap">{r.label}</td>
                <td className="px-6 py-4 text-sm whitespace-nowrap">
                  <span className={r.bias === "bullish" ? "text-emerald-400" : "text-red-400"}>{r.bias === "bullish" ? "Bullish" : "Bearish"}</span>
                </td>
                <td className="px-6 py-4 font-mono-ui text-sm text-right text-slate-300">₹{fmtNum(r.trigger_price)}</td>
                <td className="px-6 py-4 font-mono-ui text-sm text-right text-slate-400">₹{fmtNum(r.stop_loss)}</td>
                <td className="px-6 py-4 text-sm text-slate-400 whitespace-nowrap">{fmtDateLong(r.date)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="md:hidden divide-y divide-white/[0.06]">
        {sorted.map((r, i) => (
          <div
            key={`${r.symbol}-${r.key}-${i}`}
            onClick={() => openTradingViewChart(displaySymbol(r))}
            className="p-5 cursor-pointer"
            data-testid={`swing-reversal-card-${i}`}
          >
            <div className="flex items-center justify-between mb-2">
              <p className="font-display text-lg font-bold text-white">{displaySymbol(r)}</p>
              <span className={`text-sm ${r.bias === "bullish" ? "text-emerald-400" : "text-red-400"}`}>{r.bias === "bullish" ? "Bullish" : "Bearish"}</span>
            </div>
            <p className="text-sm text-slate-300 mb-3">{r.label} · {fmtDateLong(r.date)}</p>
            <div className="flex items-center gap-6 text-sm">
              <div>
                <p className="font-mono-ui text-[10px] uppercase tracking-[0.18em] text-slate-500 mb-1">Trigger</p>
                <span className="text-slate-300">₹{fmtNum(r.trigger_price)}</span>
              </div>
              <div>
                <p className="font-mono-ui text-[10px] uppercase tracking-[0.18em] text-slate-500 mb-1">Stop-Loss</p>
                <span className="text-slate-400">₹{fmtNum(r.stop_loss)}</span>
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
};

const SwingReversalTool = () => {
  const [loading, setLoading] = useState(true);
  const [result, setResult] = useState(null);
  const [refreshStatus, setRefreshStatus] = useState(null);

  const load = async () => {
    setLoading(true);
    try {
      const { data } = await axios.get(`${API}/swing-reversal/scan`);
      setResult(data);
      if (!data.found) {
        axios.get(`${API}/swing-reversal/refresh-status`).then((r) => setRefreshStatus(r.data)).catch(() => {});
      }
    } catch {
      setResult({ found: false, reason: "Request failed. Please try again." });
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); }, []);

  return (
    <div className="mt-6" data-testid="swing-reversal-tool">
      {loading && <LoadingParticles title="Scanning for Reversals" subtitle="Checking swing points · Matching reversal rules · Ranking by date" />}

      {!loading && result && !result.found && (
        <div>
          <EmptyState reason="No reversal signals are cached for today yet." />
          {refreshStatus?.status === "running" && (
            <p className="text-center text-xs text-slate-500 mt-3 font-mono-ui" data-testid="swing-reversal-refresh-progress">
              Refresh in progress — {refreshStatus.done}/{refreshStatus.total} constituents processed.
            </p>
          )}
        </div>
      )}

      {!loading && result && result.found && (
        <div data-testid="swing-reversal-results">
          <p className="text-xs text-slate-500 mb-4 font-mono-ui">
            {result.results.length} active signal{result.results.length === 1 ? "" : "s"} across {result.universe_coverage.cached} of ~{result.universe_coverage.total} Nifty 500 constituents cached today.
          </p>
          {result.results.length === 0 ? (
            <EmptyState reason="No stock triggered a reversal pattern in today's session." />
          ) : (
            <ResultsTable results={result.results} />
          )}
          <p className="text-[11px] font-light text-slate-600 mt-4 max-w-2xl">
            Each signal is a precise, rule-based relationship between a session's own price action and its prior swing point or session — not a subjective chart read. Stop-Loss is a reference level from the pattern's own construction, not a live trigger. Past performance doesn't guarantee future results — not investment advice.
          </p>
        </div>
      )}
    </div>
  );
};

export default SwingReversalTool;
