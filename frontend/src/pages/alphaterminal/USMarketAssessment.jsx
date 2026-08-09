import { useState, useEffect } from "react";
import axios from "axios";
import { Loader2 } from "lucide-react";
import { EmptyState } from "./QuantLab";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;
const SURFACE = "rounded-2xl border border-white/10 bg-[#0A0D18]";

const fmtNum = (v, dp = 2) => (v == null ? "—" : Number(v).toFixed(dp));
const fmtPctSigned = (v, dp = 2) => (v == null ? "—" : `${v > 0 ? "+" : ""}${Number(v).toFixed(dp)}%`);
const toneOf = (v) => (v == null ? "text-slate-500" : v > 0 ? "text-emerald-400" : v < 0 ? "text-red-400" : "text-white");

const StatChip = ({ label, value, tone = "text-white" }) => (
  <div className="flex flex-col"><span className="font-mono-ui text-[10px] uppercase tracking-[0.16em] text-slate-500">{label}</span><span className={`text-lg font-bold ${tone}`}>{value}</span></div>
);

const USMarketAssessmentTool = () => {
  const [data, setData] = useState(null);
  const [error, setError] = useState(false);

  useEffect(() => {
    let cancelled = false;
    axios.get(`${API}/us-markets/market-assessment`).then(({ data: d }) => { if (!cancelled) setData(d); }).catch(() => { if (!cancelled) setError(true); });
    return () => { cancelled = true; };
  }, []);

  if (error) return <EmptyState reason="Could not load market assessment right now." />;
  if (!data) return <div className="h-64 flex items-center justify-center text-slate-500 font-mono-ui text-sm gap-3"><Loader2 className="animate-spin" size={16} /> Loading…</div>;

  return (
    <div className="space-y-6" data-testid="us-market-assessment">
      <div className={`${SURFACE} p-6 grid grid-cols-2 md:grid-cols-4 gap-6`}>
        {Object.entries(data.index_levels || {}).map(([key, q]) => (
          <StatChip key={key} label={key === "SPX" ? "S&P 500" : "Nasdaq 100"} value={q ? fmtNum(q.last) : "—"} tone={q ? toneOf(q.change_pct) : "text-slate-500"} />
        ))}
        <StatChip label="Breadth (Bullish)" value={data.breadth_pct != null ? `${data.breadth_pct}%` : "—"} />
        <StatChip label="Universe" value={data.universe_size ?? "—"} />
      </div>

      {data.sector_performance?.length > 0 && (
        <div className={`${SURFACE} overflow-hidden`}>
          <div className="px-5 py-3 border-b border-white/10"><p className="font-mono-ui text-[10px] uppercase tracking-[0.24em] text-slate-400">Sector Performance (1D)</p></div>
          <div className="overflow-x-auto"><table className="w-full"><tbody>
            {data.sector_performance.map((s) => (
              <tr key={s.sector} className="border-b border-white/[0.05] last:border-0">
                <td className="px-5 py-3 text-sm text-slate-200">{s.sector}</td>
                <td className="px-5 py-3 text-xs text-slate-500 text-right">{s.count} names</td>
                <td className={`px-5 py-3 text-right font-mono-ui text-sm font-semibold ${toneOf(s.avg_return_1d)}`}>{fmtPctSigned(s.avg_return_1d)}</td>
              </tr>
            ))}
          </tbody></table></div>
        </div>
      )}

      <div className="grid md:grid-cols-2 gap-6">
        {[["Gainers", data.gainers], ["Losers", data.losers]].map(([title, rows]) => (
          <div key={title} className={`${SURFACE} overflow-hidden`}>
            <div className="px-5 py-3 border-b border-white/10"><p className="font-mono-ui text-[10px] uppercase tracking-[0.24em] text-slate-400">{title}</p></div>
            <div className="overflow-x-auto"><table className="w-full"><tbody>
              {(rows || []).map((r) => (
                <tr key={r.symbol} className="border-b border-white/[0.05] last:border-0">
                  <td className="px-5 py-3 font-mono-ui text-sm text-white">{r.symbol}</td>
                  <td className={`px-5 py-3 text-right font-mono-ui text-sm font-semibold ${toneOf(r.return_1d)}`}>{fmtPctSigned(r.return_1d)}</td>
                </tr>
              ))}
            </tbody></table></div>
          </div>
        ))}
      </div>
    </div>
  );
};

export default USMarketAssessmentTool;
