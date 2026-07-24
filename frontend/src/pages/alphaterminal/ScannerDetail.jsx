import { useEffect, useState } from "react";
import axios from "axios";
import { TrendingUp } from "lucide-react";
import QuantLabToolShell from "./QuantLabToolShell";
import { MomentumTable, getMarketUpdatedLabel } from "../AlphaTerminal";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;

// Generic scanner-detail page — one component, instantiated per-route in
// App.js with a different scannerKey/label. Rendering logic is already
// identical across all four scanners (same terminal_stocks schema), so a
// single dedicated page per scanner would just be duplicated wiring.
export default function ScannerDetail({ scannerKey, label: scannerLabel }) {
  const [rows, setRows] = useState(null);

  useEffect(() => {
    window.scrollTo(0, 0);
    axios.get(`${API}/terminal/stocks`, { params: { scanner: scannerKey } })
      .then((r) => setRows(r.data))
      .catch(() => setRows([]));
  }, [scannerKey]);

  const hasData = rows !== null && rows.length > 0;

  return (
    <QuantLabToolShell
      title={scannerLabel}
      description={hasData ? `Updated: ${getMarketUpdatedLabel()}` : "This scanner is being calibrated and isn't live yet."}
      live={hasData}
      icon={TrendingUp}
    >
      {rows === null ? (
        <div className="flex items-center justify-center py-24 text-slate-500 font-mono-ui text-sm gap-3" data-testid="scanner-detail-loading">
          <span className="h-2 w-2 rounded-full bg-sapphire-light animate-ping" /> Loading…
        </div>
      ) : hasData ? (
        <MomentumTable rows={rows} />
      ) : (
        <div className="glass rounded-2xl border border-dashed border-white/10 opacity-40 px-6 py-10 md:py-14 text-center" data-testid="scanner-detail-empty">
          <p className="font-mono-ui text-[11px] uppercase tracking-[0.28em] text-slate-600 mb-4">In Development</p>
          <h4 className="font-display text-2xl font-bold text-slate-300">Coming Soon</h4>
          <p className="mt-3 text-sm font-light text-slate-500 max-w-sm mx-auto">
            This scanner is being calibrated and will activate here as soon as it goes live.
          </p>
        </div>
      )}
    </QuantLabToolShell>
  );
}
