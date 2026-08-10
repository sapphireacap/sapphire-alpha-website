import { toneColor } from "./terminalTheme";

const fmt = (n) => (n == null ? "—" : Number(n).toLocaleString("en-IN", { maximumFractionDigits: 2 }));
const fmtSigned = (n) => (n == null ? "—" : `${n >= 0 ? "+" : ""}${n.toFixed(2)}%`);

// Pure presentational -- `rows` is market-dashboard/snapshot's own
// `global_indices` array (Dow/Nasdaq/S&P/ASX via Yahoo), already fetched
// by MarketDashboard's single snapshot call, just never rendered until now.
const GlobalIndicesPanel = ({ rows }) => (
  <div data-testid="mkt-global-indices-panel">
    <div className="px-3 py-1.5 term-panel-head">GLOBAL INDICES</div>
    {rows?.length ? rows.map((r) => (
      <div key={r.key} className="flex items-center justify-between px-3 py-2 text-[11px] border-b" style={{ borderColor: "var(--term-border)" }}>
        <span style={{ color: "var(--term-text)" }} className="font-bold">{r.label}</span>
        <span style={{ color: "var(--term-text)" }}>{fmt(r.last)}</span>
        <span style={{ color: toneColor(r.change_pct) }}>{fmtSigned(r.change_pct)}</span>
      </div>
    )) : (
      <div className="p-4 text-center term-grey text-[11px]">Global indices unavailable.</div>
    )}
  </div>
);

export default GlobalIndicesPanel;
