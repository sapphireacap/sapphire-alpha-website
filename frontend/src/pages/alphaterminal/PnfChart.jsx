import {
  useState, useEffect, useLayoutEffect, useMemo, useCallback, useRef,
  forwardRef, useImperativeHandle,
} from "react";
import axios from "axios";
import { toast } from "sonner";
import {
  Loader2, Search, Crosshair, TrendingUp, TrendingDown, Minus,
  MousePointer2, Activity, RotateCcw, Pencil, Ruler, Type, Eraser, Radio,
} from "lucide-react";
import { EmptyState } from "./QuantLab";
import { TRADER_TOKEN_KEY } from "../Auth";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;
const authHeaders = () => ({ headers: { Authorization: `Bearer ${localStorage.getItem(TRADER_TOKEN_KEY)}` } });

const SEGMENTS = [
  { key: "NSE", label: "NSE (Cash)" },
  { key: "FUT", label: "Futures" },
  { key: "OPT", label: "Options" },
  { key: "US", label: "US Indices" },
];

const INTERVALS = [
  { key: "daily", label: "Daily" },
  { key: "weekly", label: "Weekly" },
  { key: "monthly", label: "Monthly" },
  { key: "60", label: "60 min" },
  { key: "30", label: "30 min" },
  { key: "15", label: "15 min" },
  { key: "5", label: "5 min" },
  { key: "1", label: "1 min" },
];
const INTRADAY_INTERVALS = new Set(["60", "30", "15", "5", "1"]);
// Poll cadence scales with bar size -- no point re-fetching a 60-min chart
// every 15s, and a 1-min chart every 60s would visibly lag the tape.
const LIVE_REFRESH_MS = { "1": 15000, "5": 20000, "15": 30000, "30": 45000, "60": 60000 };

// US indices come from a free-tier data source that only has daily
// history (no real intraday index data) — see backend/alpha_vantage_client.py.
const US_INTERVALS = ["daily", "weekly", "monthly"];

// The book's own commonly-used box sizes. Percentage boxes (not absolute)
// are the default because they keep the box a constant *proportion* of
// price, which is what makes one parameter set usable across instruments
// trading at wildly different absolute levels.
const BOX_SIZES = [0.1, 0.25, 0.5, 1, 2, 3];

// Fixed platform convention: close-only plotting, 3-box reversal, always.
// Box size is the only construction dial — the backend doesn't accept a
// reversal parameter at all, so there is deliberately no control for it.
const REVERSAL = 3;

// Geometry of the rendered grid, in SVG units. One column is COL_W wide
// and one box is ROW_H tall; they are deliberately EQUAL so the grid is a
// true square lattice — that is precisely what makes a 45-degree trend
// line meaningful on a P&F chart, and it would be silently wrong to
// stretch either axis for looks.
const COL_W = 14;
const ROW_H = 14;
const PAD_L = 8;
const PAD_T = 12;
const AXIS_W = 84;

// Zoom/pan range for the TradingView-style "camera" (see PnfGrid below) —
// purely visual (an SVG viewBox window), so nothing about the underlying
// grid math above is touched. X and Y scale independently, matching
// TradingView's own split: the mouse wheel / drag over the chart scales
// time, the wheel / drag over the price axis scales price only.
const MIN_X_ZOOM = 1;
const MAX_X_ZOOM = 20;
const MIN_Y_ZOOM = 1;
const MAX_Y_ZOOM = 6;
const WHEEL_ZOOM_STEP = 1.15;
const AXIS_DRAG_SENSITIVITY = 0.006; // exponential factor per px dragged on the price axis
const PAD_R = 10;       // right padding inside the main (non-axis) pane
// Minimum vertical gap (in real pixels) between two price-axis labels
// before one gets skipped -- keeps labels from ever visually overlapping
// regardless of zoom level or how many boxes are in view.
const MIN_LABEL_GAP_PX = 22;

const clampNum = (v, lo, hi) => Math.min(hi, Math.max(lo, v));

const fmtNum = (v, d = 2) =>
  v == null ? "—" : Number(v).toLocaleString("en-IN", { minimumFractionDigits: d, maximumFractionDigits: d });

const BIAS_STYLE = {
  bullish: { text: "text-emerald-300", dot: "bg-emerald-400", Icon: TrendingUp },
  bearish: { text: "text-rose-300", dot: "bg-rose-400", Icon: TrendingDown },
  neutral: { text: "text-slate-300", dot: "bg-slate-400", Icon: Minus },
};

/* --------------------------------------------------------------------- */
/* The chart itself                                                       */
/* --------------------------------------------------------------------- */

const PnfGrid = forwardRef(({ data, resetKey, showTrendLines, showMa, highlight, onHoverColumn }, ref) => {
  const { columns, grid, trend_lines: lines, meta, indicators } = data;
  const frameRef = useRef(null);
  const mainSvgRef = useRef(null);
  const axisSvgRef = useRef(null);
  const dragRef = useRef(null);

  // xZoom/yZoom + panX/panY define a "camera" window (an SVG viewBox) over
  // the chart's full content space. The two <svg> elements below never
  // change physical size — only the window they look through does — so
  // the chart is always fully contained inside its frame, exactly like a
  // TradingView pane, instead of growing an oversized SVG inside a
  // scrolling container (which is what let zoom escape into a page-level
  // scroll before).
  const [xZoom, setXZoom] = useState(1);
  const [yZoom, setYZoom] = useState(1);
  const [panX, setPanX] = useState(0);
  const [panY, setPanY] = useState(0);
  const [dragging, setDragging] = useState(false);

  // Level -> row index, counted from the TOP of the grid so that higher
  // prices render higher on screen.
  const rowOf = useCallback((lvl) => grid.max_level - lvl, [grid.max_level]);
  const colX = useCallback((i) => PAD_L + (i - meta.render_offset) * COL_W, [meta.render_offset]);

  const plotW = PAD_L + columns.length * COL_W + PAD_R;
  const contentH = PAD_T * 2 + (grid.max_level - grid.min_level + 1) * ROW_H;

  const resetView = useCallback(() => {
    const pxW = mainSvgRef.current?.getBoundingClientRect().width || plotW;
    const initViewW = Math.min(plotW, pxW);
    const initXZoom = clampNum(plotW / initViewW, MIN_X_ZOOM, MAX_X_ZOOM);
    setXZoom(initXZoom);
    setPanX(Math.max(0, plotW - plotW / initXZoom));
    setYZoom(1);
    setPanY(0);
  }, [plotW]);

  useImperativeHandle(ref, () => ({ resetView }), [resetView]);

  // Reset the camera only when resetKey changes (a fresh manual "Plot" —
  // see the page component), NOT on every `data` update. A live auto-
  // refresh replaces `data` with a new column set too, and re-centering
  // the camera on every 15-second poll would fight anyone currently
  // panned back through history. Defaults to the most recent columns at
  // the chart's native box size, pinned to the right edge — older
  // columns are reached by panning left, same as scrolling a
  // TradingView chart back in time.
  useLayoutEffect(() => {
    resetView();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [resetKey]);

  const viewW = plotW / xZoom;
  const viewH = contentH / yZoom;
  const vx = clampNum(panX, 0, Math.max(0, plotW - viewW));
  const vy = clampNum(panY, 0, Math.max(0, contentH - viewH));

  // Wheel over the price axis scales price (Y); wheel over the chart
  // itself scales time (X) — the same split TradingView uses. Both zoom
  // toward the cursor so the point under it stays put. Native (non-React)
  // listener so preventDefault reliably stops the PAGE itself from
  // scrolling while the wheel is over the chart — React's synthetic
  // onWheel is attached passively and can't reliably do this.
  useEffect(() => {
    const el = frameRef.current;
    if (!el) return undefined;
    const onWheel = (e) => {
      e.preventDefault();
      const overAxis = axisSvgRef.current?.contains(e.target);
      const factor = e.deltaY < 0 ? WHEEL_ZOOM_STEP : 1 / WHEEL_ZOOM_STEP;
      if (overAxis) {
        const rect = axisSvgRef.current.getBoundingClientRect();
        const frac = clampNum((e.clientY - rect.top) / rect.height, 0, 1);
        const nz = clampNum(yZoom * factor, MIN_Y_ZOOM, MAX_Y_ZOOM);
        const nViewH = contentH / nz;
        setYZoom(nz);
        setPanY(clampNum(vy + frac * viewH - frac * nViewH, 0, Math.max(0, contentH - nViewH)));
      } else {
        const rect = mainSvgRef.current.getBoundingClientRect();
        const frac = clampNum((e.clientX - rect.left) / rect.width, 0, 1);
        const nz = clampNum(xZoom * factor, MIN_X_ZOOM, MAX_X_ZOOM);
        const nViewW = plotW / nz;
        setXZoom(nz);
        setPanX(clampNum(vx + frac * viewW - frac * nViewW, 0, Math.max(0, plotW - nViewW)));
      }
    };
    el.addEventListener("wheel", onWheel, { passive: false });
    return () => el.removeEventListener("wheel", onWheel);
  }, [vx, vy, viewW, viewH, plotW, contentH, xZoom, yZoom]);

  // Drag on the chart pans in both axes, staying clamped inside the data's
  // own bounds (so it can never scroll into empty space, let alone past
  // the frame). Drag on the price axis instead re-scales price only — the
  // "pinch the Y axis" gesture. Pointer capture keeps tracking the drag
  // even once the cursor leaves the element.
  const onPanPointerDown = (e) => {
    e.currentTarget.setPointerCapture(e.pointerId);
    dragRef.current = { mode: "pan", startX: e.clientX, startY: e.clientY, panX0: vx, panY0: vy };
    setDragging(true);
  };
  const onAxisPointerDown = (e) => {
    e.currentTarget.setPointerCapture(e.pointerId);
    dragRef.current = { mode: "yzoom", startY: e.clientY, yZoom0: yZoom, centerY0: vy + viewH / 2 };
    setDragging(true);
  };
  const onPointerMove = (e) => {
    const d = dragRef.current;
    if (!d) return;
    if (d.mode === "pan") {
      const rect = mainSvgRef.current.getBoundingClientRect();
      const dContentX = -(e.clientX - d.startX) * (viewW / rect.width);
      const dContentY = -(e.clientY - d.startY) * (viewH / rect.height);
      setPanX(clampNum(d.panX0 + dContentX, 0, Math.max(0, plotW - viewW)));
      setPanY(clampNum(d.panY0 + dContentY, 0, Math.max(0, contentH - viewH)));
    } else if (d.mode === "yzoom") {
      const deltaPx = e.clientY - d.startY;
      const nz = clampNum(d.yZoom0 * Math.exp(-deltaPx * AXIS_DRAG_SENSITIVITY), MIN_Y_ZOOM, MAX_Y_ZOOM);
      const nViewH = contentH / nz;
      setYZoom(nz);
      setPanY(clampNum(d.centerY0 - nViewH / 2, 0, Math.max(0, contentH - nViewH)));
    }
  };
  const onPointerUp = (e) => {
    if (dragRef.current) {
      try { e.currentTarget.releasePointerCapture(e.pointerId); } catch { /* already released */ }
    }
    dragRef.current = null;
    setDragging(false);
  };

  // Price labels spaced by REAL on-screen pixels, not a fixed row count —
  // a 0.25% box over a long history produces hundreds of levels, and
  // labelling every one (or even a fixed fraction of them) overlaps as
  // soon as the price axis is zoomed out. Measures the axis pane's actual
  // rendered height so the label step always keeps at least
  // MIN_LABEL_GAP_PX between two labels, however the chart is zoomed.
  const axisPxH = axisSvgRef.current?.getBoundingClientRect().height || 620;
  const pxPerRow = (axisPxH / viewH) * ROW_H;
  const labelStep = Math.max(1, Math.ceil(MIN_LABEL_GAP_PX / Math.max(pxPerRow, 1)));

  const maPoints = useMemo(() => {
    if (!showMa) return null;
    const series = indicators?.moving_average || [];
    const pts = [];
    series.forEach((price, n) => {
      if (price == null) return;
      // Convert the average's PRICE back to a fractional row so the line
      // sits between boxes rather than snapping to one.
      const lvls = grid.levels;
      let row = null;
      for (let k = 0; k < lvls.length - 1; k += 1) {
        const hi = lvls[lvls.length - 1 - k].price;
        const lo = lvls[lvls.length - 2 - k].price;
        if (price <= hi && price >= lo) {
          row = k + (hi - price) / (hi - lo || 1);
          break;
        }
      }
      if (row == null) return;
      pts.push(`${colX(meta.render_offset + n) + COL_W / 2},${PAD_T + row * ROW_H + ROW_H / 2}`);
    });
    return pts.length > 1 ? pts.join(" ") : null;
  }, [showMa, indicators, grid.levels, colX, meta.render_offset]);

  return (
    <div
      ref={frameRef}
      className="flex rounded-lg border border-white/10 bg-[#0B1220] overflow-hidden select-none h-[360px] sm:h-[460px] lg:h-[600px]"
    >
      {/* Main pane — pans/zooms in both axes via viewBox alone; its actual
          width/height attributes never change, so this can never overflow
          its own box the way a resized SVG in a scrolling div could. */}
      <svg
        ref={mainSvgRef}
        viewBox={`${vx} ${vy} ${viewW} ${viewH}`}
        preserveAspectRatio="none"
        style={{
          width: `calc(100% - ${AXIS_W}px)`, height: "100%",
          touchAction: "none", cursor: dragging ? "grabbing" : "grab",
        }}
        className="block font-mono-ui"
        onPointerDown={onPanPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onPointerCancel={onPointerUp}
        onDoubleClick={resetView}
      >
        {/* 45-degree objective trend lines */}
        {showTrendLines && lines.map((ln, n) => {
          const x1 = colX(Math.max(ln.start_index, meta.render_offset)) + COL_W / 2;
          const x2 = colX(ln.end_index) + COL_W / 2;
          if (x2 < PAD_L) return null;
          const startLvl = ln.start_level + (Math.max(ln.start_index, meta.render_offset) - ln.start_index)
            * (ln.direction === "bullish" ? 1 : -1);
          const y1 = PAD_T + rowOf(startLvl) * ROW_H + ROW_H / 2;
          const y2 = PAD_T + rowOf(ln.end_level) * ROW_H + ROW_H / 2;
          return (
            <line
              key={n} x1={x1} y1={y1} x2={x2} y2={y2}
              stroke={ln.direction === "bullish" ? "#34D399" : "#F87171"}
              strokeWidth="1.25" strokeDasharray="4 3" opacity="0.65"
            />
          );
        })}

        {/* column moving average */}
        {maPoints && (
          <polyline points={maPoints} fill="none" stroke="#38BDF8" strokeWidth="1.5" opacity="0.8" />
        )}

        {/* the X/O boxes */}
        {columns.map((col) => {
          const x = colX(col.index);
          const isX = col.direction === "X";
          const dim = highlight && !(col.index >= highlight.start_index && col.index <= highlight.index);
          const stroke = isX ? "#34D399" : "#F87171";
          return (
            <g
              key={col.index}
              opacity={dim ? 0.22 : 1}
              onMouseEnter={() => onHoverColumn?.(col)}
              onMouseLeave={() => onHoverColumn?.(null)}
              style={{ cursor: "crosshair" }}
            >
              <rect x={x} y={PAD_T} width={COL_W} height={contentH - PAD_T * 2} fill="transparent" />
              {col.levels.map((lvl) => {
                const y = PAD_T + rowOf(lvl) * ROW_H;
                const cx = x + COL_W / 2;
                const cy = y + ROW_H / 2;
                const r = ROW_H * 0.32;
                return isX ? (
                  <g key={lvl} stroke={stroke} strokeWidth="1.5" strokeLinecap="round">
                    <line x1={cx - r} y1={cy - r} x2={cx + r} y2={cy + r} />
                    <line x1={cx - r} y1={cy + r} x2={cx + r} y2={cy - r} />
                  </g>
                ) : (
                  <circle key={lvl} cx={cx} cy={cy} r={r} fill="none" stroke={stroke} strokeWidth="1.5" />
                );
              })}
            </g>
          );
        })}

        {/* highlighted pattern bracket */}
        {highlight && (() => {
          const a = colX(Math.max(highlight.start_index, meta.render_offset));
          const b = colX(highlight.index) + COL_W;
          if (b < PAD_L) return null;
          const tone = highlight.bias === "bearish" ? "#F87171" : highlight.bias === "bullish" ? "#34D399" : "#94A3B8";
          return (
            <rect
              x={a} y={PAD_T} width={Math.max(b - a, COL_W)} height={contentH - PAD_T * 2}
              fill={tone} fillOpacity="0.07" stroke={tone} strokeOpacity="0.5" strokeWidth="1" rx="3"
            />
          );
        })()}
      </svg>

      {/* Price axis — a separate fixed-width pane so it stays put while the
          main pane pans left/right through history; its vertical window
          mirrors the main pane's (vy/viewH) so labels line up with rows,
          and dragging or scrolling on it re-scales price only — the
          TradingView "pinch the Y axis" gesture (no touch pinch on
          desktop, so drag is the equivalent here). */}
      <svg
        ref={axisSvgRef}
        viewBox={`0 ${vy} ${AXIS_W} ${viewH}`}
        preserveAspectRatio="none"
        style={{ width: AXIS_W, height: "100%", touchAction: "none", cursor: "ns-resize", flexShrink: 0 }}
        className="block font-mono-ui border-l border-white/5"
        onPointerDown={onAxisPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onPointerCancel={onPointerUp}
        onDoubleClick={resetView}
      >
        {grid.levels.map(({ level, price }) => {
          const y = PAD_T + rowOf(level) * ROW_H;
          const isLabel = (grid.max_level - level) % labelStep === 0;
          if (!isLabel) return null;
          return (
            <text key={level} x={10} y={y + ROW_H / 2 + 3.5} fill="#94A3B8" fontSize="10.5">
              {fmtNum(price, price < 100 ? 2 : 1)}
            </text>
          );
        })}
      </svg>
    </div>
  );
});

/* --------------------------------------------------------------------- */
/* Left tool rail — TradingView-inspired. Only the tools that actually    */
/* do something are enabled; drawing/measuring tools aren't built yet     */
/* and are shown disabled rather than silently doing nothing on click.    */
/* --------------------------------------------------------------------- */

const RailButton = ({ icon: Icon, active, disabled, title, onClick }) => (
  <button
    type="button"
    onClick={disabled ? undefined : onClick}
    disabled={disabled}
    title={disabled ? `${title} — coming soon` : title}
    className={`flex items-center justify-center w-9 h-9 rounded-md transition-colors ${
      disabled
        ? "text-slate-700 cursor-not-allowed"
        : active
          ? "text-sapphire-light bg-sapphire-light/10"
          : "text-slate-400 hover:text-white hover:bg-white/5"
    }`}
  >
    <Icon size={17} />
  </button>
);

const ToolRail = ({ showTrendLines, setShowTrendLines, showMa, setShowMa, onReset }) => (
  <div className="hidden lg:flex flex-col items-center gap-1 w-12 shrink-0 border-r border-white/10 bg-[#0B1220] py-3">
    <RailButton icon={MousePointer2} active title="Cursor" onClick={() => {}} />
    <div className="w-6 h-px bg-white/10 my-1.5" />
    <RailButton icon={TrendingUp} active={showTrendLines} title="45° Trend Lines" onClick={() => setShowTrendLines((v) => !v)} />
    <RailButton icon={Activity} active={showMa} title="Moving Average" onClick={() => setShowMa((v) => !v)} />
    <RailButton icon={RotateCcw} title="Reset View" onClick={onReset} />
    <div className="w-6 h-px bg-white/10 my-1.5" />
    <RailButton icon={Pencil} disabled title="Draw Trendline" />
    <RailButton icon={Ruler} disabled title="Measure" />
    <RailButton icon={Type} disabled title="Text Note" />
    <RailButton icon={Eraser} disabled title="Clear Drawings" />
  </div>
);

/* --------------------------------------------------------------------- */
/* Page                                                                   */
/* --------------------------------------------------------------------- */

const compactField = "bg-white/5 border border-white/10 rounded-md px-2.5 py-1.5 text-xs text-white outline-none focus:border-sapphire-light transition-colors [color-scheme:dark]";

const PnfChart = () => {
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
  const [showTrendLines, setShowTrendLines] = useState(true);
  const [showMa, setShowMa] = useState(true);
  const [onlyMajor, setOnlyMajor] = useState(true);
  const [onlyActive, setOnlyActive] = useState(true);
  const [live, setLive] = useState(false);

  const [data, setData] = useState(null);
  const [plotCount, setPlotCount] = useState(0);
  const [loading, setLoading] = useState(false);
  const [highlight, setHighlight] = useState(null);
  const [hoverCol, setHoverCol] = useState(null);
  const gridRef = useRef(null);

  const isIntraday = INTRADAY_INTERVALS.has(interval) && segment !== "US";

  // Symbol search
  useEffect(() => {
    let cancelled = false;
    const t = setTimeout(() => {
      axios.get(`${API}/pnf/instruments`, { params: { segment, query }, ...authHeaders() })
        .then(({ data: d }) => { if (!cancelled) setSymbols(d.symbols || []); })
        .catch(() => { if (!cancelled) setSymbols([]); });
    }, 250);
    return () => { cancelled = true; clearTimeout(t); };
  }, [segment, query]);

  // Derivative chains — only FUT/OPT have expiries/strikes; NSE and US
  // (index proxies, no derivatives) never fetch them.
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

  // US indices only have daily+ history — drop back to daily if an
  // intraday interval was left selected from a different segment.
  useEffect(() => {
    if (segment === "US" && !US_INTERVALS.includes(interval)) setIntervalKey("daily");
  }, [segment, interval]);

  // `silent` skips the loading spinner/camera reset — used by the live
  // auto-refresh poll below so a background update doesn't yank focus
  // away from wherever the user has panned to, or flicker the Plot button.
  const fetchChart = useCallback(async ({ silent = false } = {}) => {
    if (!symbol) return;
    if (!silent) { setLoading(true); setHighlight(null); }
    try {
      const { data: d } = await axios.get(`${API}/pnf/chart`, {
        params: {
          symbol, segment, interval, box_pct: boxPct,
          ...(segment === "FUT" || segment === "OPT" ? { expiry } : {}),
          ...(segment === "OPT" ? { strike, option_type: optionType } : {}),
        },
        ...authHeaders(),
      });
      setData(d);
      if (!silent) setPlotCount((n) => n + 1);
    } catch (e) {
      if (!silent) { toast.error(e?.response?.data?.detail || "Could not plot that chart."); setData(null); }
    } finally {
      if (!silent) setLoading(false);
    }
  }, [symbol, segment, interval, boxPct, expiry, strike, optionType]);

  const plot = () => {
    if (!symbol) { toast.error("Pick an instrument first."); return; }
    if ((segment === "FUT" || segment === "OPT") && !expiry) { toast.error("Pick an expiry."); return; }
    if (segment === "OPT" && !strike) { toast.error("Pick a strike."); return; }
    fetchChart();
  };

  // Live auto-refresh: only meaningful once a chart is on screen and an
  // intraday timeframe is selected -- daily+ bars don't move within a
  // session, so polling them would just be wasted requests.
  useEffect(() => {
    if (!live || !data || !isIntraday) return undefined;
    const ms = LIVE_REFRESH_MS[interval] || 30000;
    const id = setInterval(() => fetchChart({ silent: true }), ms);
    return () => clearInterval(id);
  }, [live, data, isIntraday, interval, fetchChart]);

  // Live only makes sense for intraday timeframes -- auto-off if the user
  // switches to daily/weekly/monthly or a US index while it was on.
  useEffect(() => {
    if (!isIntraday && live) setLive(false);
  }, [isIntraday, live]);

  const visiblePatterns = useMemo(() => {
    if (!data) return [];
    return data.patterns
      .filter((p) => (!onlyMajor || p.major) && (!onlyActive || p.active))
      .sort((a, b) => b.index - a.index)
      .slice(0, 120);
  }, [data, onlyMajor, onlyActive]);

  const bias = data?.summary?.bias || "neutral";
  const BiasIcon = BIAS_STYLE[bias].Icon;

  return (
    <div className="min-h-screen bg-[#060B14] text-white flex flex-col">
      {/* Compact toolbar — everything needed to plot a chart in one row,
          wraps on narrow screens instead of stacking into a tall block. */}
      <div className="border-b border-white/10 bg-[#0B1220] px-3 sm:px-4 py-2.5">
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
            {(segment === "US" ? INTERVALS.filter((i) => US_INTERVALS.includes(i.key)) : INTERVALS)
              .map((i) => <option key={i.key} value={i.key}>{i.label}</option>)}
          </select>
          <select className={compactField} value={boxPct} onChange={(e) => setBoxPct(Number(e.target.value))}>
            {BOX_SIZES.map((b) => <option key={b} value={b}>{b}% box</option>)}
          </select>

          <button
            onClick={plot} disabled={loading}
            className="h-[30px] px-3.5 rounded-md bg-sapphire-light/90 hover:bg-sapphire-light text-white text-xs font-semibold transition-colors disabled:opacity-50 flex items-center justify-center gap-1.5"
          >
            {loading ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Crosshair className="w-3.5 h-3.5" />}
            Plot
          </button>

          {isIntraday && data && (
            <button
              onClick={() => setLive((v) => !v)}
              title={live ? "Auto-refreshing on this timeframe" : "Auto-refresh this chart while the market is live"}
              className={`h-[30px] px-3 rounded-md text-xs font-semibold transition-colors flex items-center gap-1.5 ${
                live ? "bg-emerald-500/15 text-emerald-300 border border-emerald-500/30" : "border border-white/10 text-slate-400 hover:text-white"
              }`}
            >
              <Radio size={13} className={live ? "animate-pulse" : ""} />
              Live
            </button>
          )}
        </div>

        {segment === "US" && (
          <p className="text-[11px] text-slate-500 mt-2 max-w-3xl">
            Nasdaq 100 and S&amp;P 500 are plotted from their most liquid tracking ETF (QQQ / SPY) — daily/weekly/monthly only, no intraday.
          </p>
        )}
      </div>

      {/* Compact instrument/stat readout — replaces the old 6-tile summary
          strip with a single dense line, TradingView-style, so the chart
          itself gets almost the whole viewport instead of being crowded
          out by chrome above it. */}
      {data && (
        <div className="flex flex-wrap items-center gap-x-4 gap-y-1 px-3 sm:px-4 py-2 border-b border-white/5 bg-[#080D16] text-[11px] font-mono-ui text-slate-400">
          <span className="text-white font-semibold text-xs">{data.instrument.tradingsymbol}</span>
          <span>{data.params.box_pct}% × {data.params.reversal} · close-only</span>
          <span>CMP <span className="text-white">{fmtNum(data.meta.last_price)}</span></span>
          <span className={`inline-flex items-center gap-1 ${BIAS_STYLE[bias].text}`}>
            <BiasIcon size={12} />{bias[0].toUpperCase() + bias.slice(1)}
          </span>
          <span>{data.summary.active_bullish} bull · {data.summary.active_bearish} bear standing</span>
          <span>Cont. {fmtNum(data.summary.continuation_price)}</span>
          <span>Rev. {fmtNum(data.summary.reversal_price)}</span>
          {live && (
            <span className="inline-flex items-center gap-1.5 text-emerald-400">
              <span className="h-1.5 w-1.5 rounded-full bg-emerald-400 animate-pulse" /> Live
            </span>
          )}
          <span className="ml-auto text-slate-500">
            {data.meta.total_columns} cols · {data.meta.bars} bars · {data.meta.first_label} → {data.meta.last_label}
          </span>
        </div>
      )}

      {!data && !loading && (
        <div className="p-4 sm:p-6">
          <EmptyState reason="Pick an instrument and hit Plot to build its structure chart." />
        </div>
      )}

      {data && (
        <div className="flex-1 flex min-h-0">
          <ToolRail
            showTrendLines={showTrendLines} setShowTrendLines={setShowTrendLines}
            showMa={showMa} setShowMa={setShowMa}
            onReset={() => gridRef.current?.resetView()}
          />

          <div className="flex-1 min-w-0 flex flex-col xl:flex-row gap-3 xl:gap-4 p-3 sm:p-4">
            <div className="flex-1 min-w-0">
              <PnfGrid
                ref={gridRef}
                data={data}
                resetKey={plotCount}
                showTrendLines={showTrendLines}
                showMa={showMa}
                highlight={highlight}
                onHoverColumn={setHoverCol}
              />
              <div className="mt-1.5 flex items-center justify-between text-[11px] text-slate-500 font-mono-ui">
                <span>
                  {hoverCol
                    ? <>Col {hoverCol.index} · {hoverCol.direction} × {hoverCol.box_count} · {fmtNum(hoverCol.bottom_price)} – {fmtNum(hoverCol.top_price)}{hoverCol.start_label && <> · {hoverCol.start_label} → {hoverCol.end_label}</>}</>
                    : "scroll to zoom · drag to pan · drag/scroll price axis to scale · double-click to reset"}
                </span>
              </div>
            </div>

            {/* Pattern panel — side column on desktop, stacks below the
                chart on mobile (flex-col above xl: avoids ever forcing
                the page wider than the viewport). */}
            <div className="w-full xl:w-[320px] shrink-0 rounded-lg border border-white/10 bg-white/[0.02] p-4 max-h-[420px] xl:max-h-[640px] overflow-y-auto">
              <div className="flex items-center justify-between mb-3">
                <h2 className="font-mono-ui text-[10px] uppercase tracking-[0.18em] text-slate-500">
                  Formations ({visiblePatterns.length})
                </h2>
              </div>
              <div className="flex gap-3 mb-3">
                <Toggle on={onlyMajor} set={setOnlyMajor} text="Major only" />
                <Toggle on={onlyActive} set={setOnlyActive} text="Still valid" />
              </div>
              {visiblePatterns.length === 0 && (
                <p className="text-xs text-slate-500">No formations match these filters.</p>
              )}
              <ul className="space-y-2">
                {visiblePatterns.map((p, n) => (
                  <li key={`${p.name}-${p.index}-${n}`}>
                    <button
                      onMouseEnter={() => setHighlight(p)}
                      onMouseLeave={() => setHighlight(null)}
                      className="w-full text-left rounded-md border border-white/10 hover:border-white/25 bg-white/[0.02] px-3 py-2 transition-colors"
                    >
                      <div className="flex items-center gap-2">
                        <span className={`w-1.5 h-1.5 rounded-full ${BIAS_STYLE[p.bias].dot}`} />
                        <span className="text-sm text-white">{p.label}</span>
                        {!p.active && p.bias !== "neutral" && (
                          <span className="ml-auto text-[10px] font-mono-ui uppercase tracking-wider text-amber-400/80">
                            negated
                          </span>
                        )}
                        {p.follow_through_index != null && (
                          <span className="ml-auto text-[10px] font-mono-ui uppercase tracking-wider text-sky-300/80">
                            follow-through
                          </span>
                        )}
                      </div>
                      <div className="mt-1 flex flex-wrap gap-x-3 gap-y-0.5 text-[11px] text-slate-400 font-mono-ui">
                        <span>col {p.index}</span>
                        {p.trigger_price != null && <span>trigger {fmtNum(p.trigger_price)}</span>}
                        {p.failure_price != null && <span>fails {fmtNum(p.failure_price)}</span>}
                      </div>
                    </button>
                  </li>
                ))}
              </ul>

              {data.counts.length > 0 && (
                <>
                  <h2 className="font-mono-ui text-[10px] uppercase tracking-[0.18em] text-slate-500 mt-6 mb-2">
                    Counts (projections)
                  </h2>
                  <ul className="space-y-1.5">
                    {data.counts.slice(-6).reverse().map((c, n) => (
                      <li key={n} className="text-[11px] font-mono-ui text-slate-400 flex justify-between">
                        <span className={c.bias === "bullish" ? "text-emerald-300/80" : "text-rose-300/80"}>
                          {c.bias === "bullish" ? "▲" : "▼"} col {c.column_index} · {c.meta.boxes} boxes
                        </span>
                        <span className="text-slate-300">{fmtNum(c.target_price)}</span>
                      </li>
                    ))}
                  </ul>
                </>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

const Toggle = ({ on, set, text }) => (
  <button
    onClick={() => set(!on)}
    className={`text-[11px] font-mono-ui uppercase tracking-wider px-2 py-1 rounded border transition-colors ${
      on ? "border-sapphire-light/60 text-sapphire-light bg-sapphire-light/10"
         : "border-white/10 text-slate-500 hover:text-slate-300"
    }`}
  >
    {text}
  </button>
);

export default PnfChart;
