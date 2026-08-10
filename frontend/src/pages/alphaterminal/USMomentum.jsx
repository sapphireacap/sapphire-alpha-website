import { useState, useEffect } from "react";
import axios from "axios";
import { Loader2 } from "lucide-react";
import { MomentumTable } from "../AlphaTerminal";
import { EmptyState } from "./QuantLab";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;

const fmtNum = (v, dp = 2) => (v == null ? "—" : Number(v).toFixed(dp));
const fmtPctSigned = (v, dp = 2) => (v == null ? "—" : `${v > 0 ? "+" : ""}${Number(v).toFixed(dp)}%`);

const openTradingViewUS = (r) => window.open(`https://www.tradingview.com/chart/?symbol=${r.ticker}`, "_blank", "noopener,noreferrer");

const MomentumRankingModule = ({ apiPath, scoreKey, scoreFmt, notReadyLabel }) => {
  const [rows, setRows] = useState(null);
  const [reason, setReason] = useState(null);

  useEffect(() => {
    let cancelled = false;
    axios.get(`${API}${apiPath}`, { params: { limit: 20 } }).then(({ data }) => {
      if (cancelled) return;
      if (!data.found) { setReason(data.reason); setRows([]); return; }
      setRows(data.results.map((r) => ({
        id: r.symbol, ticker: r.symbol, company: r.company_name || "—",
        momentum_score: scoreFmt(r),
        bias: (scoreKey(r) ?? 0) >= 0 ? "Bullish" : "Bearish",
        volume: "—",
      })));
    }).catch(() => { if (!cancelled) { setReason("Could not load right now."); setRows([]); } });
    return () => { cancelled = true; };
    // scoreFmt/scoreKey are plain literal functions passed inline by the
    // caller (new reference every render) -- only apiPath should trigger
    // a refetch, not a parent re-render.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [apiPath]);

  if (rows === null) return <div className="h-64 flex items-center justify-center text-slate-500 font-mono-ui text-sm gap-3"><Loader2 className="animate-spin" size={16} /> Loading…</div>;
  if (!rows.length) return <EmptyState reason={reason || notReadyLabel} />;
  return (
    <MomentumTable rows={rows} onRowClick={openTradingViewUS} />
  );
};

export const USMomentumLeadersTool = () => (
  <MomentumRankingModule
    apiPath="/us-markets/momentum-leaders/top"
    scoreKey={(r) => r.score}
    scoreFmt={(r) => fmtPctSigned(r.score)}
    notReadyLabel="Momentum Leaders ranking isn't ready yet — check back shortly."
  />
);

export const USMomentumInvestingTool = () => (
  <MomentumRankingModule
    apiPath="/us-markets/momentum-investing/top"
    scoreKey={(r) => r.stats?.momentum_score}
    scoreFmt={(r) => fmtNum(r.stats?.momentum_score)}
    notReadyLabel="Momentum Investing ranking isn't ready yet — check back shortly."
  />
);
