import { useEffect, useState } from "react";
import axios from "axios";
import { toneColor } from "./terminalTheme";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;
const fmt = (n) => (n == null ? "—" : Number(n).toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 }));
const fmtSigned = (n) => (n == null ? "—" : `${n >= 0 ? "+" : ""}${n.toFixed(2)}`);
const TOP_N = 5;

// Reads the same n50-quotes board TickerBar already fetches -- just
// sorted/sliced client-side, no separate backend endpoint needed.
const GainersLosersPanel = () => {
  const [rows, setRows] = useState([]);

  useEffect(() => {
    let cancelled = false;
    const load = () => {
      axios.get(`${API}/terminal/n50-quotes`)
        .then(({ data }) => { if (!cancelled) setRows(data.rows || []); })
        .catch(() => { if (!cancelled) setRows([]); });
    };
    load();
    const id = setInterval(load, 60000);
    return () => { cancelled = true; clearInterval(id); };
  }, []);

  const sorted = [...rows].sort((a, b) => b.change_pct - a.change_pct);
  const gainers = sorted.slice(0, TOP_N);
  const losers = sorted.slice(-TOP_N).reverse();

  const Column = ({ title, list }) => (
    <div>
      <div className="px-3 py-1 text-[10px] uppercase tracking-wider term-grey border-b" style={{ borderColor: "var(--term-border)" }}>{title}</div>
      {list.map((r) => (
        <div key={r.symbol} className="flex items-center justify-between px-3 py-1.5 text-[11px] border-b" style={{ borderColor: "var(--term-border)" }}>
          <span className="font-bold" style={{ color: "var(--term-text)" }}>{r.symbol}</span>
          <span style={{ color: "var(--term-text)" }}>{fmt(r.price)}</span>
          <span style={{ color: toneColor(r.change_pct) }}>{fmtSigned(r.change_pct)}%</span>
        </div>
      ))}
      {!list.length && <div className="px-3 py-3 text-[11px] term-grey">Loading…</div>}
    </div>
  );

  return (
    <div data-testid="mkt-gainers-losers-panel">
      <div className="px-3 py-1.5 term-panel-head">TOP GAINERS &amp; LOSERS</div>
      <div className="grid grid-cols-2">
        <Column title="Gainers" list={gainers} />
        <div className="border-l" style={{ borderColor: "var(--term-border)" }}>
          <Column title="Losers" list={losers} />
        </div>
      </div>
    </div>
  );
};

export default GainersLosersPanel;
