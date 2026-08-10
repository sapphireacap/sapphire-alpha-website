import { useEffect, useRef, useState } from "react";
import axios from "axios";
import { toneColor } from "./terminalTheme";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;
const fmt = (n) => (n == null ? "—" : Number(n).toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 }));
const fmtSigned = (n) => (n == null ? "—" : `${n >= 0 ? "+" : ""}${n.toFixed(2)}`);

// Constant px/sec regardless of item count -- the CSS class's 40s
// duration was tuned for 5 hardcoded stocks; at 50 the track is ~10x
// wider so the same fixed duration crawled at ~1/10th the visual speed
// (confirmed live). Measuring one copy's real width and deriving the
// duration from a fixed speed keeps the crawl rate constant no matter
// how many symbols the board ends up with.
const PIXELS_PER_SECOND = 90;

// One shared batch endpoint (n50_quotes.py, refreshed every 5min through
// the session) backs the whole N50 board -- both this tape and
// GainersLosersPanel read the same cached rows rather than each making
// its own 50x round-trip.
const TickerBar = () => {
  const [rows, setRows] = useState([]);
  const [duration, setDuration] = useState(40);
  const copyRef = useRef(null);

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

  useEffect(() => {
    if (!copyRef.current) return;
    const width = copyRef.current.offsetWidth;
    if (width > 0) setDuration(width / PIXELS_PER_SECOND);
  }, [rows]);

  const items = rows.map((r) => (
    <span key={r.symbol} className="inline-flex items-center gap-2 px-4 whitespace-nowrap text-[11px]">
      <span className="font-bold" style={{ color: "var(--term-text)" }}>{r.symbol}</span>
      <span style={{ color: "var(--term-text)" }}>{fmt(r.price)}</span>
      <span style={{ color: toneColor(r.change_pct) }}>{fmtSigned(r.change_pct)}%</span>
    </span>
  ));

  return (
    <div className="overflow-hidden border-b" style={{ borderColor: "var(--term-border)", background: "var(--term-panel-head)" }} data-testid="mkt-ticker-bar">
      {rows.length ? (
        <div className="flex term-marquee-track" style={{ width: "max-content", animationDuration: `${duration}s` }}>
          <div ref={copyRef} className="flex py-2">{items}</div>
          <div className="flex py-2" aria-hidden="true">{items}</div>
        </div>
      ) : (
        <div className="py-2 px-3 text-[11px] term-grey">Loading N50 board…</div>
      )}
    </div>
  );
};

export default TickerBar;
