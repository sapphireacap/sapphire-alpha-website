import { useEffect, useState } from "react";
import axios from "axios";
import { biasLabel, biasClass } from "./terminalTheme";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;
const fmt = (n) => (n == null ? "—" : Number(n).toLocaleString("en-IN", { maximumFractionDigits: 0 }));

// Exitline resolves NSE index instruments by Definedge's own master
// SYMBOL field, which is "NIFTY 50" / "NIFTY BANK" (with a space) -- NOT
// "NIFTY"/"BANKNIFTY" (confirmed live, 2026-08-10: those bare strings
// 404 as "Instrument not found"). `label` is the short display form used
// everywhere else on this page.
const SYMBOLS = [
  { key: "NIFTY", exitlineSymbol: "NIFTY 50", label: "NIFTY" },
  { key: "BANKNIFTY", exitlineSymbol: "NIFTY BANK", label: "BANKNIFTY" },
];

// Self-fetches Exitline's existing /exitline/levels endpoint (same one
// the Intraday Exitline module already uses) for NIFTY/BANKNIFTY -- R/
// Pivot/S map directly onto Exitline's own H3/Pivot/L3 trading-zone
// edges, no new backend logic needed.
const IndexSetupPanel = () => {
  const [rows, setRows] = useState({});

  useEffect(() => {
    let cancelled = false;
    SYMBOLS.forEach(({ key, exitlineSymbol }) => {
      axios.get(`${API}/exitline/levels`, { params: { segment: "NSE", symbol: exitlineSymbol } })
        .then(({ data }) => { if (!cancelled) setRows((r) => ({ ...r, [key]: data })); })
        .catch(() => { if (!cancelled) setRows((r) => ({ ...r, [key]: null })); });
    });
    return () => { cancelled = true; };
  }, []);

  return (
    <div data-testid="mkt-index-setup-panel">
      <div className="px-3 py-1.5 term-panel-head">INDEX SETUP</div>
      {SYMBOLS.map(({ key, label }) => {
        const d = rows[key];
        return (
          <div key={key} className="flex items-center justify-between px-3 py-2 border-b text-[11px]" style={{ borderColor: "var(--term-border)" }} data-testid={`mkt-setup-row-${key}`}>
            <span style={{ color: "var(--term-text)" }} className="w-24 shrink-0 font-bold">{label}</span>
            {d === undefined ? (
              <span className="term-grey">LOADING…</span>
            ) : d === null ? (
              <span className="term-grey">UNAVAILABLE</span>
            ) : (
              <>
                <span className="w-16 shrink-0 text-right"><span className={biasClass(d.bias)}>{biasLabel(d.bias)}</span></span>
                <span className="term-grey">R <span style={{ color: "var(--term-text)" }}>{fmt(d.levels?.H3)}</span></span>
                <span className="term-grey">PIVOT <span style={{ color: "var(--term-text)" }}>{fmt(d.levels?.Pivot)}</span></span>
                <span className="term-grey">S <span style={{ color: "var(--term-text)" }}>{fmt(d.levels?.L3)}</span></span>
              </>
            )}
          </div>
        );
      })}
    </div>
  );
};

export default IndexSetupPanel;
