import { useState, useEffect, useRef, useCallback } from "react";
import axios from "axios";
import { toast } from "sonner";
import { LayoutGrid, Rows2, Square, Search, Crosshair, Loader2, Radio } from "lucide-react";
import PnfChart, { STANDALONE_SEGMENTS, INTERVALS, BOX_SIZES, ToolRail } from "./PnfChart";
import { PnfComboModal } from "./PnfComboModal";
import { TRADER_TOKEN_KEY } from "../Auth";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;
const authHeaders = () => ({ headers: { Authorization: `Bearer ${localStorage.getItem(TRADER_TOKEN_KEY)}` } });

/*
  Multi-chart layout for P&F Studio — TradingView-style 1/2/4 grid, driven
  by ONE shared plot controller and ONE shared tool rail rather than each
  cell carrying its own full form and its own rail. Click a cell to make
  it active (highlighted border) — the controller's Plot lands there, the
  rail's toggles (trend lines/MA/smart trend/exitline/session dividers)
  apply there, and its Live button reflects its state. Each cell still
  keeps its OWN Commentary panel, since that's a per-chart readout, not a
  control.

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
//
// Below `sm`, the container itself switches from `grid` to a plain
// vertical `flex` (see the JSX below) -- a CSS grid dividing a phone's
// viewport height into 2 or 4 EQUAL rows leaves each chart a sliver too
// short to read, whereas a scrollable flex column gives every cell a real,
// usable height and lets the user scroll between them. These classes only
// need to describe the sm+ grid shape; the mobile stack needs no grid
// classes of its own.
const GRID_CLASS = {
  1: "sm:grid-cols-1 sm:grid-rows-1",
  2: "sm:grid-cols-2 sm:grid-rows-1",
  4: "sm:grid-cols-2 sm:grid-rows-2",
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

// Mirrors PnfChart's own overlay defaults (trend lines/MA/smart trend on,
// exitline/session dividers off) so a freshly-mounted cell's rail state
// matches what that cell will actually report the moment it has data.
const DEFAULT_OVERLAYS = {
  trendLines: true, ma: true, smartTrend: true,
  exitline: false, exitlineDisabled: true, exitlineLoading: false,
  sessionDividers: false, sessionDividersDisabled: true,
};

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
  // Mirrors each cell's own overlay-toggle state so the shared ToolRail
  // reflects whichever cell is currently active (see PnfChart's
  // onOverlayChange).
  const [overlaysByCell, setOverlaysByCell] = useState([
    DEFAULT_OVERLAYS, DEFAULT_OVERLAYS, DEFAULT_OVERLAYS, DEFAULT_OVERLAYS,
  ]);

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
  const [comboOpen, setComboOpen] = useState(false);
  const [comboParams, setComboParams] = useState(null);

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
    if (segment === "COMBO") {
      if (!comboParams) { setComboOpen(true); return; }
      setPlotting(true);
      try {
        cellRefs[activeCell].current?.plotCombo(comboParams, { interval, boxPct });
      } finally {
        setPlotting(false);
      }
      return;
    }
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
  const onCellOverlayChange = useCallback((i, overlays) => {
    setOverlaysByCell((prev) => { const next = [...prev]; next[i] = overlays; return next; });
  }, []);

  const activeHasData = plottedByCell[activeCell];
  const activeLive = liveByCell[activeCell];
  const activeOverlays = overlaysByCell[activeCell];

  // Mimics React's own setState signature (plain value OR an updater
  // function) so the shared ToolRail — which calls e.g.
  // `setShowTrendLines((v) => !v)` internally — can drive the active
  // cell's imperative setOverlay without knowing it's not real state.
  const makeOverlaySetter = (key) => (updater) => {
    const current = overlaysByCell[activeCell]?.[key] ?? false;
    const next = typeof updater === "function" ? updater(current) : updater;
    cellRefs[activeCell].current?.setOverlay(key, next);
  };

  return (
    <div className="h-[100dvh] w-screen overflow-hidden bg-[#060B14] text-white flex flex-col">
      <div className="shrink-0 border-b border-white/10 bg-[#0B1220] px-2 sm:px-4 py-2 sm:py-2.5">
        <div className="flex flex-wrap items-center gap-1.5 sm:gap-2">
          <select className={compactField} value={segment} onChange={(e) => { setSegment(e.target.value); setSymbol(""); }}>
            {STANDALONE_SEGMENTS.map((s) => <option key={s.key} value={s.key}>{s.label}</option>)}
          </select>

          {segment === "COMBO" ? (
            <button
              onClick={() => setComboOpen(true)}
              className={compactField + " hover:border-sapphire-light transition-colors"}
            >
              {comboParams
                ? `${comboParams.op.toUpperCase()}: ${comboParams.legA.symbol} / ${comboParams.legB.symbol}`
                : "Configure legs…"}
            </button>
          ) : (
          <>
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

      {/* ONE tool rail for every cell, same reasoning as the shared Plot
          controller above — it drives whichever cell is active rather
          than each cell carrying its own identical rail. */}
      <div className="flex-1 min-h-0 flex">
        <ToolRail
          showTrendLines={activeOverlays.trendLines} setShowTrendLines={makeOverlaySetter("trendLines")}
          showMa={activeOverlays.ma} setShowMa={makeOverlaySetter("ma")}
          showSmartTrend={activeOverlays.smartTrend} setShowSmartTrend={makeOverlaySetter("smartTrend")}
          onReset={() => cellRefs[activeCell].current?.resetView()}
          showExitline={activeOverlays.exitline}
          onToggleExitline={() => makeOverlaySetter("exitline")((v) => !v)}
          exitlineDisabled={activeOverlays.exitlineDisabled}
          exitlineLoading={activeOverlays.exitlineLoading}
          showSessionDividers={activeOverlays.sessionDividers}
          onToggleSessionDividers={() => makeOverlaySetter("sessionDividers")((v) => !v)}
          sessionDividersDisabled={activeOverlays.sessionDividersDisabled}
        />

        {/* Below `sm`: a scrollable vertical stack, each cell a real
            fraction of the viewport tall. At `sm`+: the actual 1/2/4 grid,
            no scroll needed since the grid divides the available height
            evenly. */}
        <div
          className={`flex-1 min-h-0 flex flex-col sm:grid overflow-y-auto sm:overflow-hidden ${GRID_CLASS[cellCount]}`}
          data-testid="pnf-workspace-grid"
        >
          {[0, 1, 2, 3].map((i) => {
            const borderParts = [];
            // Mobile stack: a divider under every visible cell but the last.
            if (i < cellCount - 1) borderParts.push("border-b border-white/10 sm:border-b-0");
            // sm+ grid: right border on the left column, bottom border on the top row.
            if (cellCount > 1 && i % 2 === 0) borderParts.push("sm:border-r sm:border-white/10");
            if (cellCount > 2 && i < 2) borderParts.push("sm:border-b sm:border-white/10");
            return (
              <div
                key={`pnf-cell-${i}`}
                onClick={() => setActiveCell(i)}
                // Cells beyond the current layout's count stay mounted (see
                // module docstring) but are removed from layout AND painting,
                // so a hidden chart costs no space and no compositing.
                // `min-h-[70vh] sm:min-h-0 shrink-0` gives every stacked
                // mobile cell a genuinely usable height instead of letting
                // flex divide the viewport into slivers.
                className={`min-w-0 min-h-[70vh] sm:min-h-0 shrink-0 sm:shrink overflow-hidden transition-shadow ${
                  i < cellCount ? "block" : "hidden"
                } ${borderParts.join(" ")} ${
                  activeCell === i && cellCount > 1 ? "ring-1 ring-inset ring-sapphire-light/60" : ""
                }`}
                data-testid={`pnf-cell-${i}`}
              >
                <PnfChart
                  ref={cellRefs[i]}
                  embedded
                  controlled
                  onPlotted={() => onCellPlotted(i)}
                  onLiveChange={(v) => onCellLiveChange(i, v)}
                  onOverlayChange={(overlays) => onCellOverlayChange(i, overlays)}
                />
              </div>
            );
          })}
        </div>
      </div>

      <PnfComboModal
        open={comboOpen}
        onClose={() => setComboOpen(false)}
        onApply={(params) => setComboParams(params)}
      />
    </div>
  );
};

export default PnfWorkspace;
