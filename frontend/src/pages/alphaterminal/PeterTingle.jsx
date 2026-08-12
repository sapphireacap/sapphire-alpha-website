import { useState, useRef } from "react";
import axios from "axios";
import { ShieldAlert } from "lucide-react";
import { field, label, LoadingParticles, EmptyState } from "./QuantLab";
import BiasBadge from "../../components/site/BiasBadge";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;
// No auth header -- Peter Tingle's read routes were made public
// 2026-08-12 (backend/peter_tingle_routes.py, modules.js's `adminOnly`
// removed at the same time). This component used to attach an admin/
// trader JWT here, back when every route required Depends(get_current_
// admin); a logged-out visitor now reaching this page would have sent
// "Authorization: Bearer null", harmless but misleading dead weight.

const FLAG_STYLE = {
  PASS: { color: "text-emerald-400", bg: "bg-emerald-400/10 border-emerald-400/25" },
  WARN: { color: "text-amber-400", bg: "bg-amber-400/10 border-amber-400/25" },
  FAIL: { color: "text-red-400", bg: "bg-red-400/10 border-red-400/25" },
  NA: { color: "text-slate-500", bg: "bg-white/5 border-white/10" },
};

const SURFACE = "rounded-2xl border border-white/10 bg-[#0A0D18]";

const MARKETS = [
  { key: "IN", label: "India", searchPath: "/stock-terminal/symbols/search", scanPath: "/peter-tingle/scan", placeholder: "Search symbol… e.g. RELIANCE", currency: "₹" },
  { key: "US", label: "US", searchPath: "/peter-tingle/us/symbols/search", scanPath: "/peter-tingle/us/scan", placeholder: "Search symbol… e.g. AAPL", currency: "$" },
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
        const { data } = await axios.get(`${API}${market.searchPath}`, { params: { q: v.trim() } });
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

const fmtPrice = (v) => (v == null ? "—" : v.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 }));
const fmtPct = (v) => (v == null ? "—" : `${v >= 0 ? "+" : ""}${v.toFixed(2)}%`);

const PRICE_PERFORMANCE_ROWS = [
  { key: "daily", label: "Daily" },
  { key: "weekly", label: "Weekly" },
  { key: "monthly", label: "Monthly" },
  { key: "quarterly", label: "Quarterly" },
  { key: "yearly", label: "Yearly" },
];

// Bar width scaled to the largest |value| across all five windows (not a
// fixed scale) -- a stock having a wild yearly move shouldn't make its
// daily move invisible, and vice versa on a quiet year with a sharp week.
const PricePerformance = ({ performance }) => {
  const values = PRICE_PERFORMANCE_ROWS.map((r) => performance?.[r.key]).filter((v) => v != null);
  const maxAbs = values.length ? Math.max(...values.map(Math.abs), 0.01) : 0.01;

  return (
    <div className={`${SURFACE} overflow-hidden`} data-testid="peter-tingle-price-performance">
      <div className="px-6 pt-6 pb-4">
        <h3 className="text-base font-bold text-white">Price Performance</h3>
      </div>
      <div className="px-6 pb-6 space-y-3">
        {PRICE_PERFORMANCE_ROWS.map(({ key, label: rowLabel }) => {
          const v = performance?.[key];
          const pct = v == null ? 0 : Math.min(Math.abs(v) / maxAbs, 1) * 100;
          const positive = v != null && v >= 0;
          return (
            <div key={key} className="flex items-center gap-4" data-testid={`peter-tingle-perf-${key}`}>
              <span className="w-20 shrink-0 font-mono-ui text-[11px] uppercase tracking-wider text-slate-500">{rowLabel}</span>
              <div className="flex-1 h-5 rounded bg-white/5 overflow-hidden">
                {v != null && (
                  <div
                    className={`h-full rounded ${positive ? "bg-emerald-500/70" : "bg-red-500/70"}`}
                    style={{ width: `${pct}%` }}
                  />
                )}
              </div>
              <span className={`w-20 shrink-0 text-right font-mono-ui text-xs ${v == null ? "text-slate-600" : positive ? "text-emerald-400" : "text-red-400"}`}>
                {fmtPct(v)}
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
};

const PIVOT_ROWS = [
  { key: "daily", label: "Daily" },
  { key: "weekly", label: "Weekly" },
  { key: "monthly", label: "Monthly" },
];
const PIVOT_COLS = ["S3", "S2", "S1", "R1", "R2", "R3"];

const PivotLevels = ({ pivotLevels, currency }) => {
  const anyData = PIVOT_ROWS.some((r) => pivotLevels?.[r.key]);
  if (!anyData) return null;
  return (
    <div className={`${SURFACE} overflow-hidden`} data-testid="peter-tingle-pivot-levels">
      <div className="px-6 pt-6 pb-2">
        <h3 className="text-base font-bold text-white">Pivot Levels</h3>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-left min-w-[520px]" style={{ fontVariantNumeric: "tabular-nums" }}>
          <thead>
            <tr className="border-t border-white/[0.05]">
              <th className="px-6 py-3 font-mono-ui text-[10px] uppercase tracking-[0.18em] text-slate-500 font-semibold whitespace-nowrap" />
              {PIVOT_COLS.map((c) => (
                <th key={c} className={`px-3 py-3 text-right font-mono-ui text-[10px] uppercase tracking-[0.18em] font-semibold whitespace-nowrap ${c[0] === "S" ? "text-emerald-500/70" : "text-red-500/70"}`}>
                  {c}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {PIVOT_ROWS.map(({ key, label: rowLabel }) => {
              const row = pivotLevels?.[key];
              return (
                <tr key={key} className="border-t border-white/[0.05]" data-testid={`peter-tingle-pivot-row-${key}`}>
                  <td className="px-6 py-3 text-sm text-white whitespace-nowrap">{rowLabel}</td>
                  {PIVOT_COLS.map((c) => (
                    <td key={c} className="px-3 py-3 text-right font-mono-ui text-xs text-slate-300 whitespace-nowrap">
                      {row ? `${currency}${fmtPrice(row[c])}` : "—"}
                    </td>
                  ))}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
};

const fmtRatio = (v) => (v == null ? "—" : v.toFixed(2));

// Key ratios shown as plain facts, not bucketed Perk/Pitfall -- see
// backend/peter_tingle_fundamentals.py's module docstring for why: a
// bare "P/E is 17.68" has no sign without a 5yr-average/industry
// baseline this codebase doesn't have real data for.
const KeyRatios = ({ keyRatios }) => {
  const entries = Object.entries(keyRatios || {}).filter(([, v]) => v != null);
  if (!entries.length) return null;
  return (
    <div className={`${SURFACE} overflow-hidden`} data-testid="peter-tingle-key-ratios">
      <div className="px-6 pt-6 pb-4">
        <h3 className="text-base font-bold text-white">Key Ratios</h3>
      </div>
      <div className="px-6 pb-6 grid grid-cols-2 sm:grid-cols-3 gap-x-4 gap-y-4">
        {entries.map(([label, v]) => (
          <div key={label} data-testid={`peter-tingle-ratio-${label}`}>
            <p className="font-mono-ui text-[10px] uppercase tracking-[0.16em] text-slate-500">{label}</p>
            <p className="text-sm font-bold text-white">{fmtRatio(v)}</p>
          </div>
        ))}
      </div>
    </div>
  );
};

// Only facts whose sign is meaningful without external comparison data
// end up here (see the backend module) -- CAGR direction, FII/DII stake
// actually rising or falling quarter over quarter, near-zero debt.
const PerksPitfalls = ({ perks, pitfalls }) => {
  if (!perks?.length && !pitfalls?.length) return null;
  return (
    <div className={`${SURFACE} overflow-hidden`} data-testid="peter-tingle-perks-pitfalls">
      <div className="grid sm:grid-cols-2 divide-y sm:divide-y-0 sm:divide-x divide-white/10">
        <div className="p-6">
          <h3 className="text-sm font-bold text-emerald-400 mb-3">Perks</h3>
          {perks?.length ? (
            <ul className="space-y-1.5">
              {perks.map((p, i) => <li key={i} className="text-xs text-slate-300">{p}</li>)}
            </ul>
          ) : (
            <p className="text-xs text-slate-600">None flagged.</p>
          )}
        </div>
        <div className="p-6">
          <h3 className="text-sm font-bold text-red-400 mb-3">Pitfalls</h3>
          {pitfalls?.length ? (
            <ul className="space-y-1.5">
              {pitfalls.map((p, i) => <li key={i} className="text-xs text-slate-300">{p}</li>)}
            </ul>
          ) : (
            <p className="text-xs text-slate-600">None flagged.</p>
          )}
        </div>
      </div>
    </div>
  );
};

const BIAS_TONE = { bullish: "text-emerald-400", bearish: "text-red-400", neutral: "text-slate-400" };
const OBSERVATION_BOXES = ["0.25%", "1%", "3%"];

// Same bullet-building rules as backend/pnf_observations.py's
// _bullets_for_box() -- kept in sync deliberately rather than just
// rendering the flat `bullets` string list the API also returns, so
// each line can carry its own bias color instead of being one plain
// block of text like the reference report's is.
const observationLines = (obs) => {
  const lines = [{ text: `Price is in column of ${obs.column_direction}`, tone: obs.column_direction === "X" ? "bullish" : "bearish" }];
  if (obs.basic_signal) {
    lines.push({ text: `${obs.basic_signal} was formed in the current session`, tone: obs.basic_signal_bias });
  }
  (obs.patterns || []).forEach((p) => {
    const label = /^(bullish|bearish)\s/i.test(p.label) ? p.label : `${p.bias.charAt(0).toUpperCase()}${p.bias.slice(1)} ${p.label}`;
    lines.push({ text: `${label} qualified`, tone: p.bias });
  });
  (obs.follow_throughs || []).forEach((ft) => {
    lines.push({ text: ft.label, tone: ft.bias });
  });
  return lines;
};

const PnfObservations = ({ pnfObservations: data }) => {
  const byBox = data?.by_box || {};
  const anyData = OBSERVATION_BOXES.some((k) => byBox[k]);
  if (!anyData) return null;

  return (
    <div className={`${SURFACE} overflow-hidden`} data-testid="peter-tingle-pnf-observations">
      <div className="px-6 pt-6 pb-4">
        <h3 className="text-base font-bold text-white">Point &amp; Figure Chart Observations</h3>
      </div>
      <div className="px-6 pb-6 grid gap-6 md:grid-cols-3">
        {OBSERVATION_BOXES.map((key) => {
          const obs = byBox[key];
          if (!obs) return null;
          return (
            <div key={key} data-testid={`peter-tingle-pnf-box-${key}`}>
              <p className="font-mono-ui text-[10px] uppercase tracking-[0.18em] text-slate-500 mb-2">{key} chart</p>
              <ul className="space-y-1.5">
                {observationLines(obs).map((line, i) => (
                  <li key={i} className={`text-xs ${BIAS_TONE[line.tone] || "text-slate-400"}`}>
                    {line.text}.
                  </li>
                ))}
              </ul>
            </div>
          );
        })}
      </div>
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
      const { data } = await axios.get(`${API}${market.scanPath}/${sym}`);
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
          <PricePerformance performance={result.price_performance} />
          <PivotLevels pivotLevels={result.pivot_levels} currency={market.currency} />
          <PnfObservations pnfObservations={result.pnf_observations} />
          {result.fundamental_observations && (
            <>
              <KeyRatios keyRatios={result.fundamental_observations.key_ratios} />
              <PerksPitfalls perks={result.fundamental_observations.perks} pitfalls={result.fundamental_observations.pitfalls} />
            </>
          )}
        </div>
      )}
    </div>
  );
};

export default PeterTingleTool;
