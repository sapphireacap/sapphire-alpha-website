import { useState, useEffect, useLayoutEffect, useMemo, useCallback, useRef } from "react";
import axios from "axios";
import { toast } from "sonner";
import { Loader2, Search, Crosshair, TrendingUp, TrendingDown, Minus } from "lucide-react";
import { field, selectCls, label, EmptyState } from "./QuantLab";
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
const AXIS_W = 78;

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
const FRAME_H = 620;   // fixed pixel height of the chart frame — the <svg> elements
                        // below are always exactly this size, so zoom/pan can never
                        // grow the DOM box itself and spill into the page; only the
                        // viewBox "window" onto the data moves.
const PAD_R = 10;       // right padding inside the main (non-axis) pane

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

const PnfGrid = ({ data, showTrendLines, showMa, highlight, onHoverColumn }) => {
  const { columns, grid, trend_lines: lines, meta, indicators } = data;
  const frameRef = useRef(null);
  const mainSvgRef = useRef(null);
  const axisSvgRef = useRef(null);
  const dragRef = useRef(null);

  // xZoom/yZoom + panX/panY define a "camera" window (an SVG viewBox) over
  // the chart's full content space. The two <svg> elements below never
  // change physical size — only the window they look through does — so
  // the chart is always fully contained inside the FRAME_H-tall frame,
  // exactly like a TradingView pane, instead of growing an oversized SVG
  // inside a scrolling container (which is what let zoom escape into a
  // page-level scroll before).
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

  // Reset the camera whenever a new chart is plotted, rather than carrying
  // a stale zoom/pan over onto unrelated data. Defaults to the most recent
  // columns at the chart's native box size (same visual density as
  // before), pinned to the right edge — older columns are reached by
  // panning left, same as scrolling a TradingView chart back in time.
  useLayoutEffect(() => {
    const pxW = mainSvgRef.current?.getBoundingClientRect().width || plotW;
    const initViewW = Math.min(plotW, pxW);
    const initXZoom = clampNum(plotW / initViewW, MIN_X_ZOOM, MAX_X_ZOOM);
    setXZoom(initXZoom);
    setPanX(Math.max(0, plotW - plotW / initXZoom));
    setYZoom(1);
    setPanY(0);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data]);

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

  const resetView = useCallback(() => {
    const pxW = mainSvgRef.current?.getBoundingClientRect().width || plotW;
    const initViewW = Math.min(plotW, pxW);
    const initXZoom = clampNum(plotW / initViewW, MIN_X_ZOOM, MAX_X_ZOOM);
    setXZoom(initXZoom);
    setPanX(Math.max(0, plotW - plotW / initXZoom));
    setYZoom(1);
    setPanY(0);
  }, [plotW]);

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

  // Price labels every few rows only, based on how many rows are actually
  // in view right now — a 0.25% box over a long history produces hundreds
  // of levels and labelling all of them is unreadable, but zooming the
  // price axis in should reveal more labels, not the same fixed step.
  const labelStep = Math.max(1, Math.round(viewH / ROW_H / 26));

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
      className="flex rounded-lg border border-white/10 bg-[#0B1220] overflow-hidden select-none"
      style={{ height: FRAME_H }}
    >
      {/* Main pane — pans/zooms in both axes via viewBox alone; its actual
          width/height attributes never change, so this can never overflow
          its own box the way a resized SVG in a scrolling div could. */}
      <svg
        ref={mainSvgRef}
        viewBox={`${vx} ${vy} ${viewW} ${viewH}`}
        preserveAspectRatio="none"
        style={{
          width: `calc(100% - ${AXIS_W}px)`, height: FRAME_H,
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
        width={AXIS_W}
        height={FRAME_H}
        style={{ touchAction: "none", cursor: "ns-resize", flexShrink: 0 }}
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
            <text key={level} x={8} y={y + ROW_H / 2 + 3.5} fill="#64748B" fontSize="10">
              {fmtNum(price, price < 100 ? 2 : 1)}
            </text>
          );
        })}
      </svg>
    </div>
  );
};

/* --------------------------------------------------------------------- */
/* Page                                                                   */
/* --------------------------------------------------------------------- */

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

  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [highlight, setHighlight] = useState(null);
  const [hoverCol, setHoverCol] = useState(null);

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

  const plot = async () => {
    if (!symbol) { toast.error("Pick an instrument first."); return; }
    if ((segment === "FUT" || segment === "OPT") && !expiry) { toast.error("Pick an expiry."); return; }
    if (segment === "OPT" && !strike) { toast.error("Pick a strike."); return; }
    setLoading(true); setHighlight(null);
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
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Could not plot that chart.");
      setData(null);
    } finally {
      setLoading(false);
    }
  };

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
    <div className="min-h-screen bg-[#060B14] text-white px-4 sm:px-8 py-10">
      <div className="max-w-[1500px] mx-auto">
        <header className="mb-8">
          <p className="font-mono-ui text-[10px] uppercase tracking-[0.28em] text-slate-500 mb-2">
            Alpha Terminal · Structure Engine
          </p>
          <h1 className="text-2xl sm:text-3xl font-semibold tracking-tight">Point &amp; Figure Studio</h1>
          <p className="text-sm text-slate-400 mt-2 max-w-3xl">
            Noiseless price structure — boxes, columns and objective formations, each with its own
            predefined trigger and failure level. Every pattern below is detected by rule, not by eye.
          </p>
        </header>

        {/* Controls */}
        <div className="grid grid-cols-2 md:grid-cols-4 xl:grid-cols-7 gap-3 mb-6 p-4 rounded-lg border border-white/10 bg-white/[0.02]">
          <div>
            <span className={label}>Segment</span>
            <select className={selectCls} value={segment} onChange={(e) => { setSegment(e.target.value); setSymbol(""); }}>
              {SEGMENTS.map((s) => <option key={s.key} value={s.key}>{s.label}</option>)}
            </select>
          </div>
          <div>
            <span className={label}>Search</span>
            <div className="relative">
              <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-slate-500" />
              <input className={field + " pl-8"} value={query} placeholder="e.g. NIFTYBEES"
                     onChange={(e) => setQuery(e.target.value)} />
            </div>
          </div>
          <div>
            <span className={label}>Instrument</span>
            <select className={selectCls} value={symbol} onChange={(e) => setSymbol(e.target.value)}>
              <option value="">Select…</option>
              {symbols.map((s) => <option key={s} value={s}>{s}</option>)}
            </select>
          </div>
          {(segment === "FUT" || segment === "OPT") && (
            <div>
              <span className={label}>Expiry</span>
              <select className={selectCls} value={expiry} onChange={(e) => setExpiry(e.target.value)}>
                <option value="">Select…</option>
                {expiries.map((e2) => <option key={e2} value={e2}>{e2}</option>)}
              </select>
            </div>
          )}
          {segment === "OPT" && (
            <>
              <div>
                <span className={label}>Strike</span>
                <select className={selectCls} value={strike} onChange={(e) => setStrike(e.target.value)}>
                  <option value="">Select…</option>
                  {strikes.map((s) => <option key={s} value={s}>{s}</option>)}
                </select>
              </div>
              <div>
                <span className={label}>Type</span>
                <select className={selectCls} value={optionType} onChange={(e) => setOptionType(e.target.value)}>
                  <option value="CE">CE</option><option value="PE">PE</option>
                </select>
              </div>
            </>
          )}
          <div>
            <span className={label}>Timeframe</span>
            <select className={selectCls} value={interval} onChange={(e) => setIntervalKey(e.target.value)}>
              {(segment === "US" ? INTERVALS.filter((i) => US_INTERVALS.includes(i.key)) : INTERVALS)
                .map((i) => <option key={i.key} value={i.key}>{i.label}</option>)}
            </select>
          </div>
          <div>
            <span className={label}>Box size</span>
            <select className={selectCls} value={boxPct} onChange={(e) => setBoxPct(Number(e.target.value))}>
              {BOX_SIZES.map((b) => <option key={b} value={b}>{b}%</option>)}
            </select>
          </div>
          <div>
            <span className={label}>Method</span>
            <div className={selectCls + " flex items-center text-slate-400 cursor-default"}>
              {REVERSAL}-box · close-only
            </div>
          </div>
          <div className="flex items-end">
            <button
              onClick={plot} disabled={loading}
              className="w-full h-[38px] rounded-md bg-sapphire-light/90 hover:bg-sapphire-light text-white text-sm font-medium transition-colors disabled:opacity-50 flex items-center justify-center gap-2"
            >
              {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Crosshair className="w-4 h-4" />}
              Plot
            </button>
          </div>
        </div>

        {segment === "US" && (
          <p className="text-[11px] text-slate-500 -mt-4 mb-6 max-w-3xl">
            Nasdaq 100 and S&amp;P 500 are plotted from their most liquid tracking ETF (QQQ / SPY) —
            the only source with real daily history on this data feed. Structure and patterns are
            effectively identical to the raw index; daily/weekly/monthly only, no intraday.
          </p>
        )}

        {!data && !loading && (
          <EmptyState reason="Pick an instrument and hit Plot to build its structure chart." />
        )}

        {data && (
          <>
            {/* Summary strip */}
            <div className="grid grid-cols-2 lg:grid-cols-6 gap-3 mb-5">
              <SummaryTile title="Structure bias" value={
                <span className={`inline-flex items-center gap-1.5 ${BIAS_STYLE[bias].text}`}>
                  <BiasIcon className="w-4 h-4" />{bias[0].toUpperCase() + bias.slice(1)}
                </span>
              } sub={`${data.summary.active_bullish} bull · ${data.summary.active_bearish} bear standing`} />
              <SummaryTile title="Current column"
                value={<span className={data.summary.current_column.direction === "X" ? "text-emerald-300" : "text-rose-300"}>
                  {data.summary.current_column.direction} × {data.summary.current_column.boxes}
                </span>}
                sub={`${fmtNum(data.summary.current_column.bottom_price)} – ${fmtNum(data.summary.current_column.top_price)}`} />
              <SummaryTile title="Continuation at" value={fmtNum(data.summary.continuation_price)}
                sub="one more box, same column" />
              <SummaryTile title="Reversal at" value={fmtNum(data.summary.reversal_price)}
                sub={`${data.params.reversal} boxes against`} />
              <SummaryTile title="45° trend" value={data.indicators.trend_45 === "up" ? "Up" : data.indicators.trend_45 === "down" ? "Down" : "—"}
                sub={`MA trend ${data.indicators.ma_trend || "—"}`} />
              <SummaryTile title="XO Zone"
                value={<span className={data.indicators.xo_zone.value > 0 ? "text-emerald-300" : data.indicators.xo_zone.value < 0 ? "text-rose-300" : ""}>
                  {data.indicators.xo_zone.value ?? "—"}
                </span>}
                sub={data.indicators.xo_zone.crossover ? `${data.indicators.xo_zone.crossover} crossover` : `${data.indicators.xo_zone.zone || "—"} zone`} />
            </div>

            <div className="flex flex-wrap items-center gap-4 mb-3 text-xs text-slate-400">
              <span className="font-mono-ui text-[10px] uppercase tracking-[0.18em] text-slate-500">
                {data.instrument.tradingsymbol} · {data.params.box_pct}% × {data.params.reversal} · {data.params.interval} · close-only
              </span>
              <Toggle on={showTrendLines} set={setShowTrendLines} text="45° lines" />
              <Toggle on={showMa} set={setShowMa} text={`${data.params.ma_period}-col MA`} />
              <span className="text-slate-600">scroll to zoom · drag to pan · drag/scroll price axis to scale · double-click to reset</span>
              <span className="ml-auto text-slate-500">
                {data.meta.total_columns} columns · {data.meta.bars} bars · {data.meta.first_label} → {data.meta.last_label}
              </span>
            </div>

            <div className="grid grid-cols-1 xl:grid-cols-[1fr_340px] gap-5">
              <div className="min-w-0">
                <PnfGrid
                  data={data}
                  showTrendLines={showTrendLines}
                  showMa={showMa}
                  highlight={highlight}
                  onHoverColumn={setHoverCol}
                />
                {hoverCol && (
                  <div className="mt-2 text-xs text-slate-400 font-mono-ui">
                    Col {hoverCol.index} · {hoverCol.direction} × {hoverCol.box_count} ·{" "}
                    {fmtNum(hoverCol.bottom_price)} – {fmtNum(hoverCol.top_price)}
                    {hoverCol.start_label && <> · {hoverCol.start_label} → {hoverCol.end_label}</>}
                  </div>
                )}
              </div>

              {/* Pattern panel */}
              <div className="rounded-lg border border-white/10 bg-white/[0.02] p-4 max-h-[720px] overflow-y-auto">
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
          </>
        )}
      </div>
    </div>
  );
};

const SummaryTile = ({ title, value, sub }) => (
  <div className="rounded-lg border border-white/10 bg-white/[0.02] px-4 py-3">
    <p className="font-mono-ui text-[10px] uppercase tracking-[0.18em] text-slate-500 mb-1">{title}</p>
    <p className="text-lg font-semibold tabular-nums">{value}</p>
    {sub && <p className="text-[11px] text-slate-500 mt-0.5">{sub}</p>}
  </div>
);

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
