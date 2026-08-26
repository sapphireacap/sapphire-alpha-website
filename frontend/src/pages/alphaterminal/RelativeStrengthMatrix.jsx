import { useState, useEffect, useRef } from "react";
import axios from "axios";
import { authHeaders } from "../../lib/auth";
import { EmptyState } from "./QuantLab";
import LoadingBar from "../../components/site/LoadingBar";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;
const SURFACE = "rounded-2xl border border-white/10 bg-[#0A0D18]";

const BOX_SIZES = [
  { key: "0.25", label: "Short-Term", short: "Short" },
  { key: "1", label: "Medium-Term", short: "Medium" },
  { key: "3", label: "Long-Term", short: "Long" },
];

// Rough constituent counts for groups sourced live from an NSE index CSV
// (relative_strength_groups.py's `csv_url` entries) — only used here to
// decide whether to show the "big group" computing treatment below, not
// for anything the matrix math depends on. A group missing from this map
// (any hand-curated sector basket) is treated as small, which is correct
// for all of them (8-14 symbols).
const GROUP_SIZE_HINT = {
  "nifty-50": 50,
  "nifty-100": 100,
  "nifty-midcap-100": 100,
  "nifty-smallcap-250": 250,
  "nifty-bank": 14,
};
const BIG_GROUP_THRESHOLD = 30;

// Mirrors the actual computation pipeline (relative_strength_matrix.py):
// for every pair, build a P&F chart of the price ratio at each box size,
// read its last column's direction, then aggregate. Rotated during the
// load so a long wait on a big group reads as real work happening, not a
// stuck spinner.
const COMPUTE_STAGES = [
  "Fetching daily closes…",
  "Building P&F ratio charts for each pair…",
  "Scoring bullish / bearish bias per pair…",
  "Aggregating short, medium & long-term scores…",
  "Ranking by combined score…",
];

const useComputeStage = (active, big) => {
  const [stage, setStage] = useState(0);
  const timerRef = useRef(null);
  useEffect(() => {
    if (!active) {
      setStage(0);
      return;
    }
    const intervalMs = big ? 1400 : 900;
    timerRef.current = setInterval(() => {
      setStage((s) => Math.min(s + 1, COMPUTE_STAGES.length - 1));
    }, intervalMs);
    return () => clearInterval(timerRef.current);
  }, [active, big]);
  return stage;
};

// India stays DD/MM/YYYY (existing convention everywhere else on the
// India side); US groups (groupPrefix "us-") use the US convention
// MM/DD/YYYY instead -- this component is shared between both markets
// (see the groupPrefix comment below), so the date format has to branch
// on which market is actually showing, not just pick one.
const fmtDate = (iso, isUs) => {
  if (!iso) return "—";
  const [y, m, d] = iso.split("-");
  return isUs ? `${m}/${d}/${y}` : `${d}/${m}/${y}`;
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
                <td className="px-5 py-3.5 text-sm font-bold text-white whitespace-nowrap">
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

// `groupPrefix` scopes the selector to one market's groups out of the
// single shared GROUPS registry (relative_strength_groups.py) -- India
// passes "nifty-", US passes "us-", so neither market's dropdown lists
// the other's groups. Confirmed live as a real bug (2026-08-10): the
// India page used to omit groupPrefix entirely, so its selector showed
// every group from BOTH markets side by side (Nifty Bank/IT/Auto mixed
// in with US Technology/Financials/etc.) -- always pass a prefix now.
// `groupsPath`/`matrixPath` point this same tool at another market's
// relative-strength endpoints, which speak an identical contract (see
// multi_market_engine.relative_strength). Forex/Crypto groups come from
// their own market-scoped endpoint, so they need no `groupPrefix` filter —
// that mechanism exists only because India and US share one GROUPS
// registry. `dateIsUs` controls date formatting independently of the
// prefix, since a non-India market may have no prefix at all.
const RelativeStrengthMatrix = ({ groupPrefix, defaultGroup = "nifty-bank",
                                  groupsPath = "/terminal/relative-strength/groups",
                                  matrixPath = "/terminal/relative-strength/matrix",
                                  dateIsUs = null }) => {
  const isUs = dateIsUs === null ? groupPrefix === "us-" : dateIsUs;
  const [groups, setGroups] = useState([]);
  const [group, setGroup] = useState(defaultGroup);
  const [boxTab, setBoxTab] = useState("1");
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const groupSize = GROUP_SIZE_HINT[group] || 0;
  const isBigGroup = groupSize >= BIG_GROUP_THRESHOLD;
  const stage = useComputeStage(loading, isBigGroup);

  useEffect(() => {
    axios.get(`${API}${groupsPath}`, { headers: authHeaders() })
      .then(({ data: d }) => {
        const list = groupPrefix ? d.groups.filter((g) => g.key.startsWith(groupPrefix)) : d.groups;
        setGroups(list);
        // Same self-correction as BreadthTool: a market whose group keys
        // don't include the default would otherwise open on a blank matrix.
        setGroup((g) => (list.some((x) => x.key === g) ? g : (list[0]?.key || g)));
      })
      .catch(() => {});
  }, [groupPrefix, groupsPath]);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(false);
    axios.get(`${API}${matrixPath}`, { params: { group, box_pcts: "0.25,1,3" }, headers: authHeaders() })
      .then(({ data: d }) => { if (!cancelled) setData(d); })
      .catch(() => { if (!cancelled) setError(true); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [group, matrixPath]);

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
        <div className="flex flex-col items-center justify-center gap-4 py-20" data-testid="rs-matrix-loading">
          <LoadingBar inline label={COMPUTE_STAGES[stage]} />
          {isBigGroup && (
            <p className="font-mono-ui text-[10px] uppercase tracking-[0.14em] text-slate-600 text-center max-w-xs">
              {groupSize} instruments · {Math.round((groupSize * (groupSize - 1)) / 2)} pairs per timeframe — this group takes a little longer
            </p>
          )}
        </div>
      ) : error || !data ? (
        <EmptyState reason="Could not load this group's matrix right now — try again shortly." />
      ) : (
        <>
          <div className="flex flex-wrap items-center justify-between gap-3 mb-5">
            <div>
              <p className="text-xl font-bold text-white">{data.label}</p>
              <p className="font-mono-ui text-[10px] uppercase tracking-[0.18em] text-slate-500 mt-1">
                {data.symbols.length} instruments · As of {fmtDate(data.as_of, isUs)}
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
