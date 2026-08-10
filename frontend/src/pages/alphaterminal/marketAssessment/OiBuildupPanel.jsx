import { useEffect, useState } from "react";
import axios from "axios";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;
const TOP_N = 8;

const QUADRANTS = [
  { key: "long_buildup", label: "Long Buildup" },
  { key: "short_buildup", label: "Short BuildUp" },
  { key: "long_unwinding", label: "Long Unwinding" },
  { key: "short_covering", label: "Short Covering" },
];

// Reads oi_buildup.py's board (NSE OI-spurts + Definedge price %change,
// classified into the standard 4-quadrant buildup taxonomy) -- ranked by
// |OI %change| within whichever quadrant is selected, same as the
// reference dashboard's own ranking.
const OiBuildupPanel = () => {
  const [quadrant, setQuadrant] = useState("long_buildup");
  const [rows, setRows] = useState(null);

  useEffect(() => {
    let cancelled = false;
    const load = () => {
      axios.get(`${API}/terminal/oi-buildup`)
        .then(({ data }) => { if (!cancelled) setRows(data.rows || []); })
        .catch(() => { if (!cancelled) setRows([]); });
    };
    load();
    const id = setInterval(load, 120000);
    return () => { cancelled = true; clearInterval(id); };
  }, []);

  const filtered = (rows || [])
    .filter((r) => r.quadrant === quadrant)
    .sort((a, b) => Math.abs(b.oi_change_pct) - Math.abs(a.oi_change_pct))
    .slice(0, TOP_N);

  const maxOi = Math.max(1, ...filtered.map((r) => Math.abs(r.oi_change_pct)));

  return (
    <div data-testid="mkt-oi-buildup-panel">
      <div className="flex items-center justify-between px-3 py-1.5 term-panel-head">
        <span>OPEN INTEREST BUILD-UP</span>
      </div>

      <div className="flex flex-wrap gap-1 px-3 py-2 border-b" style={{ borderColor: "var(--term-border)" }}>
        {QUADRANTS.map((q) => (
          <button
            key={q.key}
            type="button"
            onClick={() => setQuadrant(q.key)}
            className="px-2 py-1 text-[10px] uppercase tracking-wider border"
            style={{
              borderColor: "var(--term-border)",
              color: quadrant === q.key ? "#000" : "var(--term-cyan)",
              background: quadrant === q.key ? "var(--term-cyan)" : "transparent",
            }}
            data-testid={`mkt-oi-quadrant-${q.key}`}
          >
            {q.label}
          </button>
        ))}
      </div>

      {rows === null ? (
        <div className="p-4 text-center term-grey text-[11px]">Loading…</div>
      ) : !filtered.length ? (
        <div className="p-4 text-center term-grey text-[11px]">No stocks in this quadrant right now.</div>
      ) : (
        <div className="px-3 py-2">
          {filtered.map((r) => (
            <div key={r.symbol} className="flex items-center gap-2 py-1.5 text-[11px]">
              <span className="w-24 shrink-0 font-bold" style={{ color: "var(--term-text)" }}>{r.symbol}</span>
              <div className="flex-1 flex flex-col gap-0.5">
                <div className="h-1.5 bg-white/5">
                  <div className="h-full" style={{ width: `${(Math.abs(r.oi_change_pct) / maxOi) * 100}%`, background: "var(--term-cyan)" }} />
                </div>
                <div className="h-1.5 bg-white/5">
                  <div className="h-full" style={{ width: `${(Math.abs(r.price_change_pct) / maxOi) * 100}%`, background: "var(--term-amber)" }} />
                </div>
              </div>
              <div className="w-32 shrink-0 text-right">
                <div style={{ color: "var(--term-cyan)" }}>{r.oi_change_pct >= 0 ? "+" : ""}{r.oi_change_pct.toFixed(2)}% OI</div>
                <div style={{ color: "var(--term-amber)" }}>{r.price_change_pct >= 0 ? "+" : ""}{r.price_change_pct.toFixed(2)}% LTP</div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
};

export default OiBuildupPanel;
