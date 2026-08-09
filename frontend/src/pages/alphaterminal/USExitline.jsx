import { useState, useRef } from "react";
import axios from "axios";
import { Loader2, Search } from "lucide-react";
import { field, label as fieldLabel, EmptyState } from "./QuantLab";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;
const SURFACE = "rounded-2xl border border-white/10 bg-[#0A0D18]";

const fmtNum = (v, dp = 2) => (v == null ? "—" : Number(v).toFixed(dp));

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

const USExitlineTool = () => {
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

          <p className="text-xs font-light text-slate-500 leading-relaxed mt-6 max-w-2xl">
            Real US market data via Yahoo Finance (previous close) and Alpaca (live price, IEX feed). For informational purposes only — not investment advice.
          </p>
        </>
      )}
    </div>
  );
};

export default USExitlineTool;
