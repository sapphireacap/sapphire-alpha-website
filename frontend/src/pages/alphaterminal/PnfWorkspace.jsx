import { useState, useEffect, useRef, useCallback } from "react";
import axios from "axios";
import { toast } from "sonner";
import { LayoutGrid, Rows2, Square, Search, Crosshair, Loader2, Radio } from "lucide-react";
import PnfChart, { SEGMENTS, INTERVALS, BOX_SIZES } from "./PnfChart";
import { TRADER_TOKEN_KEY } from "../Auth";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;
const authHeaders = () => ({ headers: { Authorization: `Bearer ${localStorage.getItem(TRADER_TOKEN_KEY)}` } });

/*
  Multi-chart layout for P&F Studio — TradingView-style 1/2/4 grid, driven
  by ONE shared controller rather than each cell carrying its own full
  plot form. Click a cell to make it active (highlighted border), build
  the instrument in the top bar, hit Plot — it lands in whichever cell you
  clicked. Each cell still keeps its OWN tool rail (trend lines/MA/smart
  trend/exitline/session dividers) and Commentary panel, since those are
  per-chart display toggles, not part of "what to plot".

  All four cells stay MOUNTED at all times; layout only changes which are
  VISIBLE (via CSS) and how the grid divides — switching from 4-up back to
  1-up does not re-plot a chart that was hidden, since it was never
  unmounted (same reasoning TradingView's own layout switch uses).
*/

const LAYOUTS = [
  { key: "1", label: "1 Chart", icon: Square, cells: 1 },
  { key: "2", label: "2 Charts", icon: Rows2, cells: 2 },
  { key: "4", label: "4 Charts", icon: LayoutGrid, cells: 4 },
];

// Tailwind needs literal class strings (no dynamic template interpolation
// makes it into the build), so the grid shape per layout is spelled out
// rather than computed from `cells`.
const GRID_CLASS = {
  1: "grid-cols-1 grid-rows-1",
  2: "grid-cols-2 grid-rows-1",
  4: "grid-cols-2 grid-rows-2",
};

const LayoutPicker = ({ active, onChange }) => (
  <div
    className="flex items-center gap-1 rounded-lg border border-white/10 bg-[#0B1220] p-1"
    role="tablist"
    aria-label="Chart layout"
    data-testid="pnf-layout-picker"
  >
    {LAYOUTS.map(({ key, label, icon: Icon }) => (
      <button
        key={key}
        type="button"
        role="tab"
        aria-selected={active === key}
        title={label}
        onClick={() => onChange(key)}
        className={`h-7 w-7 flex items-center justify-center rounded-md transition-colors ${
          active === key ? "bg-sapphire-light/90 text-white" : "text-slate-500 hover:text-slate-300"
        }`}
        data-testid={`pnf-layout-${key}`}
      >
        <Icon size={14} />
      </button>
    ))}
  </div>
);

const compactField = "bg-white/5 border border-white/10 rounded-md px-2.5 py-1.5 text-xs text-white outline-none focus:border-sapphire-light transition-colors [color-scheme:dark]";

const PnfWorkspace = () => {
  const [layout, setLayout] = useState("1");
  const cellCount = LAYOUTS.find((l) => l.key === layout)?.cells || 1;

  const [activeCell, setActiveCell] = useState(0);
  const cellRefs = [useRef(null), useRef(null), useRef(null), useRef(null)];
  // Mirrors each cell's own live/has-plotted state back up so the shared
  // Live button reflects whichever cell is currently active, and so the
  // Live button only ever appears once that cell actually has a chart.
  const [liveByCell, setLiveByCell] = useState([false, false, false, false]);
  const [plottedByCell, setPlottedByCell] = useState([false, false, false, false]);

  // The shared controller's own form state — plots into whichever cell is
  // active, same fields PnfChart's own (now-hidden-when-embedded) toolbar
  // used to carry individually.
  const [segment, setSegment] = useState("NSE");
  const [symbols, setSymbols] = useState([]);
  const [query, setQuery] = useState("");
  const [symbol, setSymbol] = useState("");
  const [expiries, setExpiries] = useState([]);
  const [expiry, setExpiry] = useState("");
  const [strikes, setStrikes] = useState([]);
  const [strike, setStrike] = useState("");
  const [optionType, setOptionType] = useState("CE");
  const [interval, setIntervalKey] = useState("daily");
  const [boxPct, setBoxPct] = useState(0.25);
  const [plotting, setPlotting] = useState(false);

  useEffect(() => {
    let cancelled = false;
    const t = setTimeout(() => {
      axios.get(`${API}/pnf/instruments`, { params: { segment, query }, ...authHeaders() })
        .then(({ data: d }) => { if (!cancelled) setSymbols(d.symbols || []); })
        .catch(() => { if (!cancelled) setSymbols([]); });
    }, 250);
    return () => { cancelled = true; clearTimeout(t); };
  }, [segment, query]);

  useEffect(() => {
    setExpiry(""); setStrikes([]); setStrike("");
    if (!symbol || (segment !== "FUT" && segment !== "OPT")) { setExpiries([]); return; }
    axios.get(`${API}/pnf/instruments`, { params: { segment, symbol }, ...authHeaders() })
      .then(({ data: d }) => setExpiries(d.expiries || []))
      .catch(() => setExpiries([]));
  }, [symbol, segment]);

  useEffect(() => {
    if (!symbol || !expiry || segment !== "OPT") return;
    axios.get(`${API}/pnf/instruments`, { params: { segment, symbol, expiry }, ...authHeaders() })
      .then(({ data: d }) => setStrikes(d.strikes || []))
      .catch(() => setStrikes([]));
  }, [symbol, expiry, segment]);

  const plot = async () => {
    if (!symbol) { toast.error("Pick an instrument first."); return; }
    if ((segment === "FUT" || segment === "OPT") && !expiry) { toast.error("Pick an expiry."); return; }
    if (segment === "OPT" && !strike) { toast.error("Pick a strike."); return; }
    setPlotting(true);
    try {
      cellRefs[activeCell].current?.plotInstrument({ segment, symbol, expiry, strike, optionType, interval, boxPct });
    } finally {
      setPlotting(false);
    }
  };

  const onCellPlotted = useCallback((i) => {
    setPlottedByCell((prev) => { const next = [...prev]; next[i] = true; return next; });
  }, []);
  const onCellLiveChange = useCallback((i, v) => {
    setLiveByCell((prev) => { const next = [...prev]; next[i] = v; return next; });
  }, []);

  const activeHasData = plottedByCell[activeCell];
  const activeLive = liveByCell[activeCell];

  return (
    <div className="h-[100dvh] w-screen overflow-hidden bg-[#060B14] text-white flex flex-col">
      <div className="shrink-0 border-b border-white/10 bg-[#0B1220] px-3 sm:px-4 py-2.5">
        <div className="flex flex-wrap items-center gap-2">
          <select className={compactField} value={segment} onChange={(e) => { setSegment(e.target.value); setSymbol(""); }}>
            {SEGMENTS.map((s) => <option key={s.key} value={s.key}>{s.label}</option>)}
          </select>

          <div className="relative">
            <Search className="absolute left-2 top-1/2 -translate-y-1/2 w-3 h-3 text-slate-500" />
            <input
              className={compactField + " pl-6 w-28 sm:w-36"}
              value={query} placeholder="Search"
              onChange={(e) => setQuery(e.target.value)}
            />
          </div>
          <select className={compactField + " min-w-0 max-w-[9rem]"} value={symbol} onChange={(e) => setSymbol(e.target.value)}>
            <option value="">Instrument…</option>
            {symbols.map((s) => <option key={s} value={s}>{s}</option>)}
          </select>

          {(segment === "FUT" || segment === "OPT") && (
            <select className={compactField} value={expiry} onChange={(e) => setExpiry(e.target.value)}>
              <option value="">Expiry…</option>
              {expiries.map((e2) => <option key={e2} value={e2}>{e2}</option>)}
            </select>
          )}
          {segment === "OPT" && (
            <>
              <select className={compactField} value={strike} onChange={(e) => setStrike(e.target.value)}>
                <option value="">Strike…</option>
                {strikes.map((s) => <option key={s} value={s}>{s}</option>)}
              </select>
              <select className={compactField} value={optionType} onChange={(e) => setOptionType(e.target.value)}>
                <option value="CE">CE</option><option value="PE">PE</option>
              </select>
            </>
          )}

          <select className={compactField} value={interval} onChange={(e) => setIntervalKey(e.target.value)}>
            {INTERVALS.map((i) => <option key={i.key} value={i.key}>{i.label}</option>)}
          </select>
          <select className={compactField} value={boxPct} onChange={(e) => setBoxPct(Number(e.target.value))}>
            {BOX_SIZES.map((b) => <option key={b} value={b}>{b}% box</option>)}
          </select>

          <button
            onClick={plot} disabled={plotting}
            className="h-[30px] px-3.5 rounded-md bg-sapphire-light/90 hover:bg-sapphire-light text-white text-xs font-semibold transition-colors disabled:opacity-50 flex items-center justify-center gap-1.5"
            data-testid="pnf-workspace-plot"
          >
            {plotting ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Crosshair className="w-3.5 h-3.5" />}
            Plot into cell {activeCell + 1}
          </button>

          {activeHasData && (
            <button
              onClick={() => cellRefs[activeCell].current?.setLive(!activeLive)}
              title={activeLive ? "Auto-refreshing on this timeframe" : "Auto-refresh the active cell while the market is live"}
              className={`h-[30px] px-3 rounded-md text-xs font-semibold transition-colors flex items-center gap-1.5 ${
                activeLive ? "bg-emerald-500/15 text-emerald-300 border border-emerald-500/30" : "border border-white/10 text-slate-400 hover:text-white"
              }`}
            >
              <Radio size={13} className={activeLive ? "animate-pulse" : ""} />
              Live
            </button>
          )}

          <div className="ml-auto">
            <LayoutPicker active={layout} onChange={setLayout} />
          </div>
        </div>
      </div>

      <div className={`flex-1 min-h-0 grid ${GRID_CLASS[cellCount]}`} data-testid="pnf-workspace-grid">
        {[0, 1, 2, 3].map((i) => (
          <div
            key={`pnf-cell-${i}`}
            onClick={() => setActiveCell(i)}
            // Cells beyond the current layout's count stay mounted (see
            // module docstring) but are removed from layout AND painting,
            // so a hidden chart costs no space and no compositing.
            className={`min-w-0 min-h-0 overflow-hidden transition-shadow ${
              i < cellCount ? "block" : "hidden"
            } ${i % 2 === 0 && cellCount > 1 ? "border-r border-white/10" : ""} ${
              i < 2 && cellCount > 2 ? "border-b border-white/10" : ""
            } ${activeCell === i && cellCount > 1 ? "ring-1 ring-inset ring-sapphire-light/60" : ""}`}
            data-testid={`pnf-cell-${i}`}
          >
            <PnfChart
              ref={cellRefs[i]}
              embedded
              controlled
              onPlotted={() => onCellPlotted(i)}
              onLiveChange={(v) => onCellLiveChange(i, v)}
            />
          </div>
        ))}
      </div>
    </div>
  );
};

export default PnfWorkspace;
