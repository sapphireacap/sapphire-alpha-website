import { useState, useEffect } from "react";
import axios from "axios";
import { Loader2 } from "lucide-react";
import { EmptyState } from "./QuantLab";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;
const SURFACE = "rounded-2xl border border-white/10 bg-[#0A0D18]";

const BOX_SIZES = [
  { key: "0.25", label: "Short-Term", short: "Short" },
  { key: "1", label: "Medium-Term", short: "Medium" },
  { key: "3", label: "Long-Term", short: "Long" },
];

const fmtDate = (iso) => {
  if (!iso) return "—";
  const [y, m, d] = iso.split("-");
  return `${d}/${m}/${y}`;
};

const RankingTable = ({ ranking, groupSize }) => {
  const maxTotal = (groupSize - 1) * BOX_SIZES.length;
  return (
    <div className={`${SURFACE} overflow-hidden`} data-testid="rs-ranking-table">
      <div className="overflow-x-auto">
        <table className="w-full" style={{ fontVariantNumeric: "tabular-nums" }}>
          <thead>
            <tr className="border-b border-white/10">
              <th className="px-5 py-4 text-left font-mono-ui text-[11px] uppercase tracking-[0.18em] text-slate-500 font-semibold">Scrip</th>
              {BOX_SIZES.map((b) => (
                <th key={b.key} className="px-4 py-4 text-right font-mono-ui text-[11px] uppercase tracking-[0.18em] text-slate-500 font-semibold whitespace-nowrap">
                  {b.short}
                </th>
              ))}
              <th className="px-5 py-4 text-right font-mono-ui text-[11px] uppercase tracking-[0.18em] text-sapphire-light font-semibold">Total</th>
            </tr>
          </thead>
          <tbody>
            {ranking.map((r, i) => (
              <tr key={r.symbol} className="border-b border-white/[0.05] last:border-0" data-testid={`rs-rank-row-${i}`}>
                <td className="px-5 py-3.5 font-display text-sm font-bold text-white whitespace-nowrap">
                  <span className="font-mono-ui text-[10px] text-slate-600 mr-2">#{i + 1}</span>
                  {r.symbol}
                </td>
                {BOX_SIZES.map((b) => (
                  <td key={b.key} className="px-4 py-3.5 text-right font-mono-ui text-sm text-slate-300">{r.scores[b.key]}</td>
                ))}
                <td className="px-5 py-3.5 text-right font-mono-ui text-base font-bold text-sapphire-light">
                  {r.total}<span className="text-slate-600 font-normal">/{maxTotal}</span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
};

const MatrixGrid = ({ symbols, grid }) => (
  <div className={`${SURFACE} overflow-hidden`} data-testid="rs-matrix-grid">
    <div className="overflow-x-auto">
      <table className="w-full" style={{ fontVariantNumeric: "tabular-nums" }}>
        <thead>
          <tr className="border-b border-white/10">
            <th className="px-4 py-3 text-left font-mono-ui text-[10px] uppercase tracking-[0.14em] text-slate-500 sticky left-0 bg-[#0A0D18]">vs</th>
            {symbols.map((s) => (
              <th key={s} className="px-3 py-3 text-center font-mono-ui text-[10px] uppercase tracking-[0.1em] text-slate-500 whitespace-nowrap">{s}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {symbols.map((row) => (
            <tr key={row} className="border-b border-white/[0.05] last:border-0">
              <td className="px-4 py-2.5 font-mono-ui text-[11px] font-semibold text-white sticky left-0 bg-[#0A0D18] whitespace-nowrap">{row}</td>
              {symbols.map((col) => {
                if (col === row) return <td key={col} className="px-3 py-2.5 text-center text-slate-700">—</td>;
                const bias = grid[row]?.[col];
                return (
                  <td key={col} className="px-3 py-2.5 text-center">
                    {bias == null ? (
                      <span className="text-slate-700 text-[10px]">n/a</span>
                    ) : (
                      <span className={`font-mono-ui text-[10px] font-bold uppercase tracking-wider ${bias === "bullish" ? "text-emerald-400" : "text-red-400"}`}>
                        {bias === "bullish" ? "Bull" : "Bear"}
                      </span>
                    )}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  </div>
);

const RelativeStrengthMatrix = () => {
  const [groups, setGroups] = useState([]);
  const [group, setGroup] = useState("nifty-bank");
  const [boxTab, setBoxTab] = useState("1");
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);

  useEffect(() => {
    axios.get(`${API}/terminal/relative-strength/groups`)
      .then(({ data: d }) => setGroups(d.groups))
      .catch(() => {});
  }, []);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(false);
    axios.get(`${API}/terminal/relative-strength/matrix`, { params: { group, box_pcts: "0.25,1,3" } })
      .then(({ data: d }) => { if (!cancelled) setData(d); })
      .catch(() => { if (!cancelled) setError(true); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [group]);

  return (
    <div data-testid="rs-matrix-tool">
      <div className="flex flex-wrap items-center gap-2 mb-6" data-testid="rs-group-selector">
        {groups.map((g) => (
          <button
            key={g.key}
            type="button"
            onClick={() => setGroup(g.key)}
            className={`px-3.5 py-1.5 rounded-full font-mono-ui text-[11px] uppercase tracking-[0.1em] whitespace-nowrap border transition-colors duration-300 ${
              group === g.key ? "border-sapphire-light/50 bg-sapphire/10 text-white" : "border-white/10 text-slate-500 hover:text-slate-300"
            }`}
            data-testid={`rs-group-${g.key}`}
          >
            {g.label}
          </button>
        ))}
      </div>

      {loading ? (
        <div className="flex items-center justify-center py-20 text-slate-500 font-mono-ui text-sm gap-3">
          <Loader2 className="animate-spin" size={16} /> Building matrix…
        </div>
      ) : error || !data ? (
        <EmptyState reason="Could not load this group's matrix right now — try again shortly." />
      ) : (
        <>
          <div className="flex flex-wrap items-center justify-between gap-3 mb-5">
            <div>
              <p className="font-display text-xl font-bold text-white">{data.label}</p>
              <p className="font-mono-ui text-[10px] uppercase tracking-[0.18em] text-slate-500 mt-1">
                {data.symbols.length} instruments · As of {fmtDate(data.as_of)}
              </p>
            </div>
          </div>

          <p className="font-mono-ui text-[10px] uppercase tracking-[0.16em] text-slate-500 mb-3">Combined Ranking</p>
          <RankingTable ranking={data.ranking} groupSize={data.symbols.length} />

          <p className="font-mono-ui text-[10px] uppercase tracking-[0.16em] text-slate-500 mt-8 mb-3">Pairwise Matrix</p>
          <div className="flex items-center gap-1 rounded-md border border-white/10 p-0.5 w-fit mb-4" data-testid="rs-box-tabs">
            {BOX_SIZES.map((b) => (
              <button
                key={b.key}
                type="button"
                onClick={() => setBoxTab(b.key)}
                data-testid={`rs-box-tab-${b.key}`}
                className={`font-mono-ui text-[10px] uppercase tracking-wider px-3 py-1.5 rounded transition-colors ${
                  boxTab === b.key ? "bg-sapphire-light/20 text-sapphire-light" : "text-slate-500 hover:text-slate-300"
                }`}
              >
                {b.label}
              </button>
            ))}
          </div>
          <MatrixGrid symbols={data.symbols} grid={data.matrices[boxTab]?.grid || {}} />
        </>
      )}
    </div>
  );
};

export default RelativeStrengthMatrix;
