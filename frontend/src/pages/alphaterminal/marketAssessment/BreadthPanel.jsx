import { useEffect, useState } from "react";
import axios from "axios";
import { toneColor } from "./terminalTheme";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;
const fmt = (n, digits = 2) => (n == null ? "—" : Number(n).toFixed(digits));
const fmtSigned = (n, digits = 2) => (n == null ? "—" : `${n >= 0 ? "+" : ""}${fmt(n, digits)}`);

const Row = ({ label, children }) => (
  <div className="flex items-center justify-between px-3 py-2 border-b" style={{ borderColor: "var(--term-border)" }}>
    <span className="term-label">{label}</span>
    {children}
  </div>
);

// Self-fetches the existing X-Percent breadth reading (same endpoint the
// Market Breadth Alpha Terminal module already reads, GROUPS["nifty-50"])
// -- the raw "31/50" count isn't served directly, but is exactly
// recoverable from the series' latest %value against the known universe
// total, so no new backend route is needed for it.
const BreadthPanel = ({ advances, declines, unchanged, weekHigh, weekLow, vix }) => {
  const [xPercent, setXPercent] = useState(null);

  useEffect(() => {
    let cancelled = false;
    axios.get(`${API}/terminal/breadth/x-percent`, { params: { group: "nifty-50" } })
      .then(({ data }) => { if (!cancelled) setXPercent(data.series?.length ? data.series[data.series.length - 1] : null); })
      .catch(() => { if (!cancelled) setXPercent(null); });
    return () => { cancelled = true; };
  }, []);

  const total = (advances || 0) + (declines || 0) + (unchanged || 0);
  const advPct = total ? ((advances || 0) / total) * 100 : 0;
  const decPct = total ? ((declines || 0) / total) * 100 : 0;

  const xCount = xPercent ? Math.round((xPercent.value / 100) * xPercent.total) : null;

  return (
    <div data-testid="mkt-breadth-panel">
      <div className="px-3 py-1.5 term-panel-head">BREADTH</div>

      <div className="px-3 py-2 border-b" style={{ borderColor: "var(--term-border)" }}>
        <div className="flex items-center justify-between text-[11px] mb-1.5">
          <span className="term-label">ADV / DEC / UNCH</span>
          <span>
            <span className="term-green">{advances ?? "—"}</span>
            <span className="term-grey"> / </span>
            <span className="term-red">{declines ?? "—"}</span>
            <span className="term-grey"> / </span>
            <span className="term-grey">{unchanged ?? "—"}</span>
          </span>
        </div>
        <div className="flex h-2 w-full overflow-hidden">
          <div style={{ width: `${advPct}%`, background: "var(--term-green)" }} />
          <div style={{ width: `${decPct}%`, background: "var(--term-red)" }} />
          <div className="flex-1" style={{ background: "var(--term-panel-head)" }} />
        </div>
      </div>

      <Row label="52W HIGH / LOW">
        <span><span className="term-green">{weekHigh ?? "—"}</span> <span className="term-grey">/</span> <span className="term-red">{weekLow ?? "—"}</span></span>
      </Row>
      <Row label="INDIA VIX">
        <span style={{ color: "var(--term-text)" }}>
          {fmt(vix?.last)} <span style={{ color: toneColor(vix?.change_pct) }}>{fmtSigned(vix?.change_pct)}%</span>
        </span>
      </Row>
      <Row label="X% BREADTH N50">
        <span style={{ color: xCount != null ? toneColor(xCount - xPercent.total / 2) : "var(--term-grey)" }}>
          {xCount != null ? `${xCount} / ${xPercent.total} IN X` : "—"}
        </span>
      </Row>
    </div>
  );
};

export default BreadthPanel;
