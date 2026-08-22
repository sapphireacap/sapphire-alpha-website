import { useState, useEffect } from "react";
import axios from "axios";
import { Loader2 } from "lucide-react";
import { LoadingParticles, EmptyState } from "./QuantLab";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;
const INDICES = ["NIFTY", "BANKNIFTY", "FINNIFTY"];

const fmtNum = (v, dp = 2) => (v === null || v === undefined ? "—" : Number(v).toLocaleString("en-IN", { maximumFractionDigits: dp }));
const fmtPct = (v) => (v === null || v === undefined ? "—" : `${(Number(v) * 100).toFixed(2)}%`);

const Stat = ({ label, value, sub, tone }) => (
  <div className="rounded-2xl border border-white/10 bg-[#0A0D18] p-5" data-testid={`options-analytics-stat-${label.toLowerCase().replace(/\s+/g, "-")}`}>
    <p className="font-mono-ui text-[10px] uppercase tracking-[0.24em] text-slate-500 mb-2">{label}</p>
    <p className={`font-display text-2xl md:text-3xl font-bold ${tone || "text-white"}`}>{value}</p>
    {sub && <p className="text-xs text-slate-500 mt-1">{sub}</p>}
  </div>
);

const OptionsAnalyticsTool = () => {
  const [index, setIndex] = useState("NIFTY");
  const [loading, setLoading] = useState(true);
  const [result, setResult] = useState(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    axios.get(`${API}/options-analytics/${index}`)
      .then((r) => { if (!cancelled) setResult(r.data); })
      .catch(() => { if (!cancelled) setResult({ found: false, reason: "Request failed. Please try again." }); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [index]);

  const pcrTone = (pcr) => {
    if (pcr === null || pcr === undefined) return "text-white";
    if (pcr >= 1.3) return "text-red-400";
    if (pcr <= 0.7) return "text-emerald-400";
    return "text-white";
  };

  const ivTone = (rank) => {
    if (rank === null || rank === undefined) return "text-white";
    if (rank >= 75) return "text-red-400";
    if (rank <= 25) return "text-emerald-400";
    return "text-white";
  };

  return (
    <div className="mt-6" data-testid="options-analytics-tool">
      <div className="flex gap-2 mb-6">
        {INDICES.map((idx) => (
          <button
            key={idx}
            onClick={() => setIndex(idx)}
            className={`rounded-full border px-4 py-2 font-mono-ui text-[11px] uppercase tracking-[0.14em] transition-colors duration-300 ${
              index === idx ? "border-sapphire/40 bg-sapphire/10 text-sapphire-light" : "border-white/10 text-slate-500 hover:text-slate-300 hover:border-white/20"
            }`}
            data-testid={`options-analytics-tab-${idx}`}
          >
            {idx}
          </button>
        ))}
      </div>

      {loading && <LoadingParticles title="Reading the Option Chain" subtitle="Aggregating open interest · Solving max pain · Ranking volatility" />}

      {!loading && result && !result.found && <EmptyState reason={result.reason || "No data available right now."} />}

      {!loading && result && result.found && (
        <div data-testid="options-analytics-results">
          <p className="text-xs text-slate-500 mb-4 font-mono-ui">
            {result.index} · {result.expiry} expiry · Spot ₹{fmtNum(result.spot)}
          </p>
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
            <Stat
              label="Max Pain"
              value={result.max_pain ? `₹${fmtNum(result.max_pain.strike, 0)}` : "—"}
              sub={result.max_pain ? (result.spot > result.max_pain.strike ? "Below spot" : result.spot < result.max_pain.strike ? "Above spot" : "At spot") : "Not enough OI"}
            />
            <Stat
              label="Put-Call Ratio"
              value={result.pcr === null ? "—" : result.pcr.toFixed(2)}
              tone={pcrTone(result.pcr)}
              sub={result.pcr === null ? "No call OI" : result.pcr >= 1.3 ? "Bearish extreme" : result.pcr <= 0.7 ? "Bullish extreme" : "Neutral zone"}
            />
            <Stat
              label="ATM IV"
              value={fmtPct(result.atm_iv)}
              sub="Nearest-strike average"
            />
            <Stat
              label="IV Rank / Percentile"
              value={result.iv_rank === null ? "—" : `${result.iv_rank} / ${result.iv_percentile}`}
              tone={ivTone(result.iv_rank)}
              sub={result.history_days > 0 ? `vs. ${result.history_days} realized-vol readings` : "Not enough underlying history yet"}
            />
          </div>
          <p className="text-[11px] font-light text-slate-600 mt-5 max-w-2xl">
            Max Pain is the strike where option writers collectively owe the least at expiry — a gravitational tendency into expiry, not a guarantee. No vendor here publishes historical implied volatility, so IV Rank/Percentile benchmarks today's live IV against the underlying's own realized-volatility history instead — a standard proxy, not the same thing as ranking against real historical IV. PCR and IV Rank/Percentile extremes indicate possible exhaustion, not a standalone reversal signal. Not investment advice.
          </p>
        </div>
      )}
    </div>
  );
};

export default OptionsAnalyticsTool;
