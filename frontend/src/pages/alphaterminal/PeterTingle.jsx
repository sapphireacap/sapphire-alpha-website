import { useState, useRef } from "react";
import axios from "axios";
import { ShieldAlert } from "lucide-react";
import { field, label, LoadingParticles, EmptyState } from "./QuantLab";
import BiasBadge from "../../components/site/BiasBadge";
import { ADMIN_TOKEN_KEY } from "../../lib/auth";
import { TRADER_TOKEN_KEY } from "../Auth";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;
// Peter Tingle's own routes (backend/peter_tingle_routes.py) are
// admin-gated -- only an admin ever reaches this component at all (see
// ModuleDetail.jsx's AdminOnlyNotice), but the calls themselves still
// need the JWT attached. Checks both token keys since an admin may be
// signed in via /admin33 or as a trader account with role "admin" (same
// precedent as lib/auth.js's useIsAdmin).
const authHeaders = () => ({
  headers: { Authorization: `Bearer ${localStorage.getItem(ADMIN_TOKEN_KEY) || localStorage.getItem(TRADER_TOKEN_KEY)}` },
});

const FLAG_STYLE = {
  PASS: { color: "text-emerald-400", bg: "bg-emerald-400/10 border-emerald-400/25" },
  WARN: { color: "text-amber-400", bg: "bg-amber-400/10 border-amber-400/25" },
  FAIL: { color: "text-red-400", bg: "bg-red-400/10 border-red-400/25" },
  NA: { color: "text-slate-500", bg: "bg-white/5 border-white/10" },
};

const SURFACE = "rounded-2xl border border-white/10 bg-[#0A0D18]";

const MARKETS = [
  { key: "IN", label: "India", searchPath: "/stock-terminal/symbols/search", scanPath: "/peter-tingle/scan", placeholder: "Search symbol… e.g. RELIANCE" },
  { key: "US", label: "US", searchPath: "/peter-tingle/us/symbols/search", scanPath: "/peter-tingle/us/scan", placeholder: "Search symbol… e.g. AAPL" },
];

const MarketToggle = ({ market, onChange }) => (
  <div className="inline-flex rounded-full border border-white/10 p-1" data-testid="peter-tingle-market-toggle">
    {MARKETS.map((m) => (
      <button
        type="button"
        key={m.key}
        onClick={() => onChange(m.key)}
        className={`px-4 py-1.5 rounded-full text-xs font-medium transition-colors ${
          market === m.key ? "bg-sapphire-light text-[#050710]" : "text-slate-400 hover:text-white"
        }`}
        data-testid={`peter-tingle-market-${m.key.toLowerCase()}`}
      >
        {m.label}
      </button>
    ))}
  </div>
);

const SymbolPicker = ({ market, onSelect }) => {
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
        const { data } = await axios.get(`${API}${market.searchPath}`, { params: { q: v.trim() }, ...authHeaders() });
        setOptions(data || []);
        setOpen(true);
      } catch {
        setOptions([]);
      }
    }, 250);
  };

  const pick = (s) => {
    setQuery(s.symbol);
    setOpen(false);
    onSelect(s.symbol);
  };

  return (
    <div className="relative">
      <label className={label}>Symbol</label>
      <input
        value={query}
        onChange={onChange}
        onFocus={() => options.length > 0 && setOpen(true)}
        onBlur={() => setTimeout(() => setOpen(false), 150)}
        className={field}
        placeholder={market.placeholder}
        data-testid="peter-tingle-symbol-input"
        autoComplete="off"
      />
      {open && options.length > 0 && (
        <div className="absolute z-20 mt-1 w-full max-h-56 overflow-y-auto glass rounded-md border border-white/10 shadow-xl" data-testid="peter-tingle-symbol-dropdown">
          {options.map((s) => (
            <button
              type="button"
              key={s.symbol}
              onClick={() => pick(s)}
              className="block w-full text-left px-3 py-2 text-sm text-slate-200 hover:bg-white/10 transition-colors"
            >
              <span className="font-mono-ui">{s.symbol}</span>
              {s.company_name && <span className="text-slate-500"> — {s.company_name}</span>}
            </button>
          ))}
        </div>
      )}
    </div>
  );
};

const FlagTable = ({ title, flags, testId }) => (
  <div className={`${SURFACE} overflow-hidden`} data-testid={testId}>
    <div className="px-6 pt-6 pb-2">
      <h3 className="text-base font-bold text-white">{title}</h3>
    </div>
    <div className="overflow-x-auto">
      <table className="w-full text-left min-w-[480px]">
        <tbody>
          {flags.map((f) => {
            const style = FLAG_STYLE[f.status] || FLAG_STYLE.NA;
            return (
              <tr key={f.rule} className="border-t border-white/[0.05]">
                <td className="px-6 py-3 text-sm text-white whitespace-nowrap">{f.rule}</td>
                <td className="px-3 py-3">
                  <span className={`inline-flex items-center justify-center rounded-full border px-2.5 py-0.5 font-mono-ui text-[10px] uppercase tracking-wider ${style.color} ${style.bg}`}>{f.status}</span>
                </td>
                <td className="px-3 py-3 text-xs text-slate-500">{f.detail}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  </div>
);

const PeterTingleTool = () => {
  const [marketKey, setMarketKey] = useState("IN");
  const [symbol, setSymbol] = useState("");
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState(null);
  const market = MARKETS.find((m) => m.key === marketKey);

  const changeMarket = (key) => {
    setMarketKey(key);
    setSymbol("");
    setResult(null);
  };

  const runScan = async (sym) => {
    setSymbol(sym);
    setLoading(true);
    setResult(null);
    try {
      const { data } = await axios.get(`${API}${market.scanPath}/${sym}`, authHeaders());
      setResult(data);
    } catch {
      setResult({ has_data: false });
    } finally {
      setLoading(false);
    }
  };

  return (
    <div data-testid="peter-tingle-tool">
      <div className="mb-6 flex flex-wrap items-end gap-4">
        <div className="max-w-md flex-1 min-w-[220px]">
          <SymbolPicker market={market} onSelect={runScan} />
        </div>
        <MarketToggle market={marketKey} onChange={changeMarket} />
      </div>

      {!symbol && !loading && (
        <EmptyState reason="Search for a stock above to run its caution scan." />
      )}

      {loading && <LoadingParticles title="Running Peter Tingle" subtitle="Scanning technicals · Scanning fundamentals · Weighing the flags" />}

      {!loading && result && !result.has_data && symbol && (
        <EmptyState reason={`No data on file yet for ${symbol}.`} />
      )}

      {!loading && result?.has_data && (
        <div className="space-y-6">
          <div className={`${SURFACE} p-6 flex items-center justify-between flex-wrap gap-3`} data-testid="peter-tingle-verdict">
            <div className="flex items-center gap-2">
              <ShieldAlert size={16} className="text-sapphire-light" />
              <div>
                <p className="text-xl font-bold text-white">{result.symbol}</p>
                {result.company_name && <p className="text-xs text-slate-500">{result.company_name}</p>}
              </div>
            </div>
            <BiasBadge bias={result.verdict} testid="peter-tingle-verdict-badge" />
          </div>

          <FlagTable title="Technical Scan" flags={result.technical_flags} testId="peter-tingle-technical-table" />
          <FlagTable title="Fundamental Scan" flags={result.fundamental_flags} testId="peter-tingle-fundamental-table" />
        </div>
      )}
    </div>
  );
};

export default PeterTingleTool;
