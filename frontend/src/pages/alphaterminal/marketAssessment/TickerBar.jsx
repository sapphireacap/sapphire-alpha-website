import { useEffect, useState } from "react";
import axios from "axios";
import { toneColor } from "./terminalTheme";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;
const fmt = (n) => (n == null ? "—" : Number(n).toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 }));
const fmtSigned = (n) => (n == null ? "—" : `${n >= 0 ? "+" : ""}${n.toFixed(2)}`);

const TICKERS = ["RELIANCE", "HDFCBANK", "TCS", "SBIN", "INFY"];

// Reuses the same /exitline/levels endpoint as IndexSetupPanel (already
// public, already returns a live ltp + yesterday's close for any NSE
// cash symbol) rather than a new quote route -- %change is just
// (ltp - close) / close, derived client-side. Definedge returns no ltp
// at all outside trading hours (same documented behavior NSE Exitline's
// own "Live Price Unavailable" zone already handles) -- falls back to
// showing yesterday's close (flat, 0%) rather than a blank dash, so the
// ticker still shows something when the market's closed.
const TickerBar = () => {
  const [quotes, setQuotes] = useState({});

  useEffect(() => {
    let cancelled = false;
    TICKERS.forEach((symbol) => {
      axios.get(`${API}/exitline/levels`, { params: { segment: "NSE", symbol } })
        .then(({ data }) => {
          if (cancelled) return;
          const price = data.ltp ?? data.close;
          const changePct = data.ltp != null && data.close ? ((data.ltp - data.close) / data.close) * 100 : 0;
          setQuotes((q) => ({ ...q, [symbol]: { price, changePct } }));
        })
        .catch(() => { if (!cancelled) setQuotes((q) => ({ ...q, [symbol]: null })); });
    });
    return () => { cancelled = true; };
  }, []);

  const items = TICKERS.map((symbol) => {
    const q = quotes[symbol];
    return (
      <span key={symbol} className="inline-flex items-center gap-2 px-4 whitespace-nowrap text-[11px]">
        <span className="font-bold" style={{ color: "var(--term-text)" }}>{symbol}</span>
        <span style={{ color: "var(--term-text)" }}>{q ? fmt(q.price) : "—"}</span>
        <span style={{ color: q ? toneColor(q.changePct) : "var(--term-grey)" }}>{q ? `${fmtSigned(q.changePct)}%` : "—"}</span>
      </span>
    );
  });

  return (
    <div className="overflow-hidden border-t" style={{ borderColor: "var(--term-border)", background: "var(--term-panel-head)" }} data-testid="mkt-ticker-bar">
      <div className="flex term-marquee-track" style={{ width: "max-content" }}>
        <div className="flex py-2">{items}</div>
        <div className="flex py-2" aria-hidden="true">{items}</div>
      </div>
    </div>
  );
};

export default TickerBar;
