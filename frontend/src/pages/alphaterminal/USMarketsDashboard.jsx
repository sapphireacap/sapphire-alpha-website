import { useState, useEffect, useRef } from "react";
import axios from "axios";
import { motion } from "framer-motion";
import {
  Loader2, Crosshair, Activity, Flame, Gauge, Radar, LayoutDashboard, Lock, Search,
} from "lucide-react";
import { MomentumTable } from "../AlphaTerminal";
import { field, label as fieldLabel, EmptyState } from "./QuantLab";
import BreadthTool from "./Breadth";
import RelativeStrengthMatrix from "./RelativeStrengthMatrix";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;
const SURFACE = "rounded-2xl border border-white/10 bg-[#0A0D18]";

const fmtNum = (v, dp = 2) => (v == null ? "—" : Number(v).toFixed(dp));
const fmtPctSigned = (v, dp = 2) => (v == null ? "—" : `${v > 0 ? "+" : ""}${Number(v).toFixed(dp)}%`);
const toneOf = (v) => (v == null ? "text-slate-500" : v > 0 ? "text-emerald-400" : v < 0 ? "text-red-400" : "text-white");

// Same 8-slot registry shape as CRYPTO_MODULES/modules.js -- Index Vector
// and Options Trend Scanner have no US equivalent yet (both need a live
// options-market-structure engine; Definedge, the only options data
// source in this codebase, is India-only -- see us_markets_routes.py's
// module docstring), Swing Picks has no US equivalent either (hand-
// curated pick data on the India side, not a live scan).
const US_MODULES = [
  { slug: "exitline", no: "01", icon: Crosshair, title: "US Exitline", shortDescription: "Intraday levels with a suggested SL and TP.", live: true },
  { slug: "momentum-leaders", no: "02", icon: Activity, title: "Momentum Leaders", shortDescription: "Ranks 1w/1m momentum across the S&P 500.", live: true },
  { slug: "momentum-investing", no: "03", icon: Flame, title: "Momentum Investing", shortDescription: "Risk-adjusted momentum ranking across the S&P 500.", live: true },
  { slug: "breadth", no: "04", icon: Gauge, title: "Market Breadth", shortDescription: "Percentage of the S&P 500 currently trending bullish.", live: true },
  { slug: "relative-strength", no: "05", icon: Radar, title: "Relative Strength Engine", shortDescription: "Pairwise strength matrix across US sector groups.", live: true },
  { slug: "market-assessment", no: "06", icon: LayoutDashboard, title: "Market Assessment", shortDescription: "Single-screen US market health.", live: true },
];

const ModuleCard = ({ module, index, active, onSelect }) => {
  const Icon = module.icon;
  if (!module.live) {
    return (
      <motion.div initial={{ opacity: 0, y: 16 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.5, delay: index * 0.05 }}>
        <div className="relative h-full rounded-2xl border border-white/10 bg-[#0A0D18] p-5 opacity-70" data-testid={`us-module-${module.slug}`}>
          <div className="flex items-center justify-between mb-4">
            <span className="inline-flex h-8 w-8 items-center justify-center rounded-lg border border-white/10 bg-white/[0.03] text-slate-500"><Icon size={14} /></span>
            <span className="font-mono-ui text-[10px] text-slate-500">{module.no}</span>
          </div>
          <h3 className="text-base font-bold text-white tracking-tight mb-1">{module.title}</h3>
          <p className="text-xs font-light text-slate-500 leading-relaxed mb-4">{module.shortDescription}</p>
          <span className="inline-flex items-center gap-1.5 font-mono-ui text-[10px] uppercase tracking-wider text-slate-500"><Lock size={10} /> Coming Soon</span>
        </div>
      </motion.div>
    );
  }
  return (
    <motion.div initial={{ opacity: 0, y: 16 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.5, delay: index * 0.05 }}>
      <button
        type="button"
        onClick={() => onSelect(module.slug)}
        className={`w-full text-left h-full rounded-2xl border p-5 transition-all duration-300 ${
          active === module.slug ? "border-sapphire/50 bg-sapphire/[0.06] shadow-[0_0_36px_rgba(31,95,208,0.14)]" : "border-white/10 bg-[#0A0D18] hover:border-sapphire/30 hover:bg-white/[0.02]"
        }`}
        data-testid={`us-module-${module.slug}`}
      >
        <div className="flex items-center justify-between mb-4">
          <span className="inline-flex h-8 w-8 items-center justify-center rounded-lg border border-white/10 bg-white/[0.03] text-sapphire-light"><Icon size={14} /></span>
          <span className="font-mono-ui text-[10px] text-sapphire-light">{module.no}</span>
        </div>
        <h3 className="text-base font-bold text-white tracking-tight mb-1">{module.title}</h3>
        <p className="text-xs font-light text-slate-500 leading-relaxed">{module.shortDescription}</p>
      </button>
    </motion.div>
  );
};

/* -------------------------------- Symbol picker -------------------------------- */
const SymbolPicker = ({ onSelect, placeholder = "Search symbol… e.g. AAPL" }) => {
  const [query, setQuery] = useState("");
  const [options, setOptions] = useState([]);
  const [open, setOpen] = useState(false);
  const debounceRef = useRef(null);

  const onChange = (e) => {
    const v = e.target.value;
    setQuery(v);
    if (debounceRef.current) clearTimeout(debounceRef.current);
    if (v.trim().length < 1) { setOptions([]); setOpen(false); return; }
    debounceRef.current = setTimeout(async () => {
      try {
        const { data } = await axios.get(`${API}/us-markets/symbols/search`, { params: { q: v.trim() } });
        setOptions(data || []);
        setOpen(true);
      } catch { setOptions([]); }
    }, 250);
  };

  const pick = (s) => { setQuery(s.symbol); setOpen(false); onSelect(s.symbol); };

  return (
    <div className="relative max-w-md">
      <label className={fieldLabel}>Symbol</label>
      <div className="relative">
        <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-slate-500" />
        <input
          value={query} onChange={onChange}
          onFocus={() => options.length > 0 && setOpen(true)}
          onBlur={() => setTimeout(() => setOpen(false), 150)}
          className={field + " pl-9"} placeholder={placeholder} autoComplete="off"
          data-testid="us-markets-symbol-input"
        />
      </div>
      {open && options.length > 0 && (
        <div className="absolute z-20 mt-1 w-full max-h-56 overflow-y-auto glass rounded-md border border-white/10 shadow-xl" data-testid="us-markets-symbol-dropdown">
          {options.map((s) => (
            <button type="button" key={s.symbol} onClick={() => pick(s)} className="block w-full text-left px-3 py-2 text-sm text-slate-200 hover:bg-white/10 transition-colors">
              <span className="font-mono-ui">{s.symbol}</span>
              {s.company_name && <span className="text-slate-500"> — {s.company_name}</span>}
            </button>
          ))}
        </div>
      )}
    </div>
  );
};

/* -------------------------------- Exitline module -------------------------------- */
const ExitlineModule = () => {
  const [symbol, setSymbol] = useState("");
  const [result, setResult] = useState(null);
  const [loading, setLoading] = useState(false);

  const runScan = async (sym) => {
    setSymbol(sym); setLoading(true); setResult(null);
    try {
      const { data } = await axios.get(`${API}/us-markets/exitline`, { params: { symbol: sym } });
      setResult(data);
    } catch { setResult({ error: true }); } finally { setLoading(false); }
  };

  return (
    <div data-testid="us-exitline-module">
      <div className="mb-6"><SymbolPicker onSelect={runScan} /></div>

      {!symbol && !loading && <EmptyState reason="Search for a US stock above to run its Exitline levels." />}
      {loading && (
        <div className="h-48 flex items-center justify-center text-slate-500 font-mono-ui text-sm gap-3"><Loader2 className="animate-spin" size={16} /> Loading levels…</div>
      )}
      {!loading && result?.error && <EmptyState reason={`Could not load levels for ${symbol} right now.`} />}

      {!loading && result && !result.error && (
        <>
          <div className={`${SURFACE} p-5 md:p-6 mb-5 ${result.bias === "Long" ? "border-emerald-400/25 bg-emerald-400/[0.04]" : result.bias === "Short" ? "border-red-400/25 bg-red-400/[0.04]" : ""}`} data-testid="us-exitline-signal-card">
            <div className="flex flex-wrap items-center justify-between gap-3 mb-3">
              <span className="text-lg font-bold text-white">{result.tradingsymbol} — {result.zone_label}</span>
              <span className={`font-mono-ui text-xs font-bold uppercase tracking-wider px-3 py-1 rounded-full border ${
                result.bias === "Long" ? "border-emerald-400/30 text-emerald-300" : result.bias === "Short" ? "border-red-400/30 text-red-300" : "border-white/15 text-slate-400"
              }`}>{result.bias}</span>
            </div>
            <p className="text-sm text-slate-300 leading-relaxed mb-4">{result.reason}{result.commentary ? ` ${result.commentary}` : ""}</p>
            <div className="grid grid-cols-3 gap-4">
              <div><p className="font-mono-ui text-[10px] uppercase tracking-wider text-slate-500 mb-1">Live Price</p><p className="font-mono-ui text-sm text-white font-bold">{result.ltp != null ? `$${fmtNum(result.ltp)}` : "—"}</p></div>
              <div><p className="font-mono-ui text-[10px] uppercase tracking-wider text-slate-500 mb-1">Suggested SL</p><p className="font-mono-ui text-sm text-red-400">{result.sl != null ? `$${fmtNum(result.sl)}` : "—"}</p></div>
              <div><p className="font-mono-ui text-[10px] uppercase tracking-wider text-slate-500 mb-1">{result.trail_stop ? "Target" : "Suggested TP"}</p><p className="font-mono-ui text-sm text-emerald-400">{result.trail_stop ? "Trail Stop" : result.tp != null ? `$${fmtNum(result.tp)}` : "—"}</p></div>
            </div>
          </div>

          <div className={`${SURFACE} overflow-hidden`} data-testid="us-exitline-ladder">
            <div className="px-5 py-3 border-b border-white/10"><p className="font-mono-ui text-[10px] uppercase tracking-[0.24em] text-slate-400">Level Ladder</p></div>
            <div className="overflow-x-auto">
              <table className="w-full min-w-[360px]" style={{ fontVariantNumeric: "tabular-nums" }}>
                <tbody>
                  {[...Object.entries(result.levels || {}).filter(([k]) => ["H5", "H4", "H3", "Pivot", "L3", "L4", "L5"].includes(k)), ["LTP", result.ltp]]
                    .sort((a, b) => (b[1] ?? -Infinity) - (a[1] ?? -Infinity))
                    .map(([k, v]) => (
                      <tr key={k} className={`border-b border-white/[0.05] last:border-0 ${k === "LTP" ? "bg-sapphire-light/15" : ""}`}>
                        <td className="px-5 py-3 font-mono-ui text-xs uppercase tracking-[0.14em] text-slate-400">{k === "LTP" ? "◆ Live Price" : k}</td>
                        <td className="px-5 py-3 text-right font-mono-ui text-sm text-slate-200">{v != null ? `$${fmtNum(v)}` : "—"}</td>
                      </tr>
                    ))}
                </tbody>
              </table>
            </div>
          </div>
        </>
      )}
    </div>
  );
};

/* -------------------------------- Momentum modules -------------------------------- */
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
    <MomentumTable
      rows={rows}
      onRowClick={openTradingViewUS}
      disclaimer="Computed from real Yahoo Finance daily OHLC across the S&P 500 universe. Ranked mechanically, not a curated pick list. For informational purposes only — not investment advice."
    />
  );
};

/* -------------------------------- Market Assessment -------------------------------- */
const StatChip = ({ label, value, tone = "text-white" }) => (
  <div className="flex flex-col"><span className="font-mono-ui text-[10px] uppercase tracking-[0.16em] text-slate-500">{label}</span><span className={`text-lg font-bold ${tone}`}>{value}</span></div>
);

const MarketAssessmentModule = () => {
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

/* ---------------------------------- Dashboard ---------------------------------- */
export default function USMarketsDashboard() {
  const [activeModule, setActiveModule] = useState(null);

  return (
    <div data-testid="us-markets-dashboard">
      <div className="grid grid-cols-2 md:grid-cols-3 gap-3 mb-8" data-testid="us-module-grid">
        {US_MODULES.map((m, i) => <ModuleCard key={m.slug} module={m} index={i} active={activeModule} onSelect={setActiveModule} />)}
      </div>

      {activeModule === "exitline" && <ExitlineModule />}
      {activeModule === "momentum-leaders" && (
        <MomentumRankingModule apiPath="/us-markets/momentum-leaders/top" scoreKey={(r) => r.score} scoreFmt={(r) => fmtPctSigned(r.score)} notReadyLabel="Momentum Leaders ranking isn't ready yet." />
      )}
      {activeModule === "momentum-investing" && (
        <MomentumRankingModule apiPath="/us-markets/momentum-investing/top" scoreKey={(r) => r.stats?.momentum_score} scoreFmt={(r) => fmtNum(r.stats?.momentum_score)} notReadyLabel="Momentum Investing ranking isn't ready yet." />
      )}
      {activeModule === "breadth" && <BreadthTool seriesPath="/us-markets/breadth" fixedGroup="sp500" />}
      {activeModule === "relative-strength" && <RelativeStrengthMatrix groupPrefix="us-" defaultGroup="us-technology" />}
      {activeModule === "market-assessment" && <MarketAssessmentModule />}

      {activeModule && (
        <p className="text-xs font-light text-slate-500 leading-relaxed mt-6 max-w-2xl" data-testid="us-markets-disclaimer">
          Real US market data via Yahoo Finance and Alpaca (IEX feed). For informational purposes only — not investment advice.
        </p>
      )}
    </div>
  );
}
