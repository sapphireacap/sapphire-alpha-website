import { useState, useEffect, useMemo } from "react";
import axios from "axios";
import { TrendingUp, TrendingDown, Minus, Loader2 } from "lucide-react";
import { EmptyState } from "./QuantLab";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;
const SURFACE = "rounded-2xl border border-white/10 bg-[#0A0D18]";

const VERDICT_STYLE = {
  Bullish: { Icon: TrendingUp, tone: "text-emerald-400", box: "border-emerald-500/30 bg-emerald-500/10" },
  Bearish: { Icon: TrendingDown, tone: "text-red-400", box: "border-red-500/30 bg-red-500/10" },
  Neutral: { Icon: Minus, tone: "text-slate-500", box: "border-white/10 bg-white/[0.03]" },
};

const FILTERS = ["All", "Bullish", "Bearish", "Neutral"];

const legLabel = (dir) => (dir === "bullish" ? "Bullish" : dir === "bearish" ? "Bearish" : "—");
const legTone = (dir) => (dir === "bullish" ? "text-emerald-400" : dir === "bearish" ? "text-red-400" : "text-slate-600");

const StatChip = ({ label, value }) => (
  <div className="flex flex-col">
    <span className="font-mono-ui text-[10px] uppercase tracking-[0.16em] text-slate-500">{label}</span>
    <span className="font-display text-lg font-bold text-white">{value}</span>
  </div>
);

const Row = ({ r }) => {
  const { Icon, tone, box } = VERDICT_STYLE[r.verdict] || VERDICT_STYLE.Neutral;
  return (
    <tr className="border-b border-white/[0.05] last:border-0" data-testid={`options-trend-row-${r.symbol}`}>
      <td className="px-5 py-3.5 font-display text-sm font-bold text-white whitespace-nowrap">{r.symbol}</td>
      <td className="px-5 py-3.5">
        <span className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md border font-mono-ui text-[11px] uppercase tracking-wider font-semibold ${box} ${tone}`}>
          <Icon size={12} />
          {r.verdict}
        </span>
      </td>
      <td className={`px-5 py-3.5 font-mono-ui text-xs whitespace-nowrap ${legTone(r.future)}`}>{legLabel(r.future)}</td>
      <td className={`px-5 py-3.5 font-mono-ui text-xs whitespace-nowrap ${legTone(r.call)}`}>{legLabel(r.call)}</td>
      <td className={`px-5 py-3.5 font-mono-ui text-xs whitespace-nowrap ${legTone(r.put)}`}>{legLabel(r.put)}</td>
      <td className="px-5 py-3.5 font-mono-ui text-xs text-slate-500 whitespace-nowrap">{r.atm_strike}</td>
    </tr>
  );
};

const OptionsTrendTool = () => {
  const [data, setData] = useState(null);
  const [filter, setFilter] = useState("All");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);

  useEffect(() => {
    axios.get(`${API}/terminal/options-trend/scan`)
      .then(({ data: d }) => setData(d))
      .catch(() => setError(true))
      .finally(() => setLoading(false));
  }, []);

  const rows = useMemo(() => {
    if (!data?.results) return [];
    const filtered = filter === "All" ? data.results : data.results.filter((r) => r.verdict === filter);
    return [...filtered].sort((a, b) => a.symbol.localeCompare(b.symbol));
  }, [data, filter]);

  const counts = useMemo(() => {
    const c = { Bullish: 0, Bearish: 0, Neutral: 0 };
    (data?.results || []).forEach((r) => { c[r.verdict] = (c[r.verdict] || 0) + 1; });
    return c;
  }, [data]);

  return (
    <div data-testid="options-trend-tool">
      {loading ? (
        <div className="flex items-center justify-center py-20 text-slate-500 font-mono-ui text-sm gap-3">
          <Loader2 className="animate-spin" size={16} /> Loading scanner…
        </div>
      ) : error || !data ? (
        <EmptyState reason="Options Trend Scanner hasn't been computed yet — check back shortly." />
      ) : (
        <>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
            <StatChip label="Bullish" value={counts.Bullish} />
            <StatChip label="Bearish" value={counts.Bearish} />
            <StatChip label="Neutral" value={counts.Neutral} />
            <StatChip label="Universe" value={data.universe_total} />
          </div>

          <div className="flex flex-wrap items-center gap-2 mb-4" data-testid="options-trend-filter">
            {FILTERS.map((f) => (
              <button
                key={f}
                type="button"
                onClick={() => setFilter(f)}
                data-testid={`options-trend-filter-${f}`}
                className={`px-3.5 py-1.5 rounded-full font-mono-ui text-[11px] uppercase tracking-[0.1em] whitespace-nowrap border transition-colors duration-300 ${
                  filter === f ? "border-sapphire-light/50 bg-sapphire/10 text-white" : "border-white/10 text-slate-500 hover:text-slate-300"
                }`}
              >
                {f}
              </button>
            ))}
          </div>

          <div className={`${SURFACE} overflow-hidden`} data-testid="options-trend-table">
            <div className="overflow-x-auto">
              <table className="w-full" style={{ fontVariantNumeric: "tabular-nums" }}>
                <thead>
                  <tr className="border-b border-white/10">
                    {["Symbol", "Verdict", "Future", "Call", "Put", "ATM Strike"].map((h) => (
                      <th key={h} className="px-5 py-4 text-left font-mono-ui text-[11px] uppercase tracking-[0.18em] text-slate-500 font-semibold whitespace-nowrap">
                        {h}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {rows.map((r) => <Row key={r.symbol} r={r} />)}
                </tbody>
              </table>
            </div>
            {rows.length === 0 && (
              <div className="px-6 py-14 text-center text-sm font-light text-slate-500">No stocks match this filter right now.</div>
            )}
          </div>
        </>
      )}
    </div>
  );
};

export default OptionsTrendTool;
