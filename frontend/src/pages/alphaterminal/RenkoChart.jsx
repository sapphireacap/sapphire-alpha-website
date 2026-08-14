import {
  useState, useEffect, useLayoutEffect, useMemo, useCallback, useRef,
  forwardRef, useImperativeHandle,
} from "react";
import axios from "axios";
import { toast } from "sonner";
import {
  Loader2, Search, Crosshair, TrendingUp, TrendingDown, Minus,
  MousePointer2, Activity, RotateCcw, Pencil, Ruler, Type, Eraser, Radio,
  Layers, X, Target, SeparatorVertical,
} from "lucide-react";
import { EmptyState } from "./QuantLab";
import { TRADER_TOKEN_KEY } from "../Auth";
import {
  EXITLINE_SEGMENTS, EXITLINE_VISIBLE_LEVELS, EXITLINE_LEVEL_COLORS, EXITLINE_DISPLAY_LABELS,
  fetchExitlineLevels, priceToFractionalLevel, findSessionBoundaries, isIntradayInterval,
} from "./exitlineOverlay";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;
const authHeaders = () => ({ headers: { Authorization: `Bearer ${localStorage.getItem(TRADER_TOKEN_KEY)}` } });

const SEGMENTS = [
  { key: "NSE", label: "NSE (Cash)" },
  { key: "FUT", label: "Futures" },
  { key: "OPT", label: "Options" },
  { key: "US", label: "US Stocks" },
  { key: "COMMODITY", label: "Commodities" },
  { key: "CRYPTO", label: "Crypto" },
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
// Same polling reasoning as PnfChart.jsx's LIVE_REFRESH_MS.
const LIVE_REFRESH_MS = {
  "1": 15000, "5": 20000, "15": 30000, "30": 45000, "60": 60000,
  daily: 60000, weekly: 60000, monthly: 60000,
};

// See PnfChart.jsx's identical constant for the full reasoning — no longer
// a restriction on any segment, just a marker for which intervals still
// come from Yahoo (and therefore a different underlying instrument than
// the same selector's intraday chart).
const DAILY_PLUS_INTERVALS = ["daily", "weekly", "monthly"];

// See PnfChart.jsx's identical constant for the full reasoning.
const US_INDEX_KEYS = ["NDX", "SPX"];

// Same client-side Binance fetch as PnfChart.jsx, for the same reason
// (geo-blocked from the backend's own server) — see that file's comment.
const BINANCE_API = "https://api.binance.com/api/v3";
const BINANCE_INTERVAL = {
  "1": "1m", "5": "5m", "15": "15m", "30": "30m", "60": "1h",
  daily: "1d", weekly: "1w", monthly: "1M",
};

const fetchCryptoBars = async (symbol, interval) => {
  const { data } = await axios.get(`${BINANCE_API}/klines`, {
    params: { symbol, interval: BINANCE_INTERVAL[interval], limit: 1000 },
  });
  const isDailyPlus = interval === "daily" || interval === "weekly" || interval === "monthly";
  return data.map((k) => {
    const t = new Date(k[0]);
    const row = { open: parseFloat(k[1]), high: parseFloat(k[2]), low: parseFloat(k[3]), close: parseFloat(k[4]) };
    if (isDailyPlus) {
      row.date = t.toISOString().slice(0, 10);
    } else {
      const pad = (n) => String(n).padStart(2, "0");
      row.ts = `${pad(t.getUTCDate())}${pad(t.getUTCMonth() + 1)}${t.getUTCFullYear()}${pad(t.getUTCHours())}${pad(t.getUTCMinutes())}`;
    }
    return row;
  });
};

// Book's own commonly-cited brick sizes (Ch.1: 0.25-1% short term,
// 1-3% intermediate, 3-5% longer term).
const BOX_SIZES = [0.01, 0.02, 0.05, 0.1, 0.25, 0.5, 1, 2, 3, 5];

// Fixed platform convention, same posture as PnfChart.jsx's REVERSAL:
// Renko is always close-only, 2-box reversal (see backend/renko_engine.py
// for why 2, not the "one brick reversal" a naive reading suggests) —
// brick size is the only construction dial exposed.
const REVERSAL_BOXES = 2;

// One brick = one box, rendered as a single diagonal step — unlike P&F's
// stacked X/O columns, Renko has no notion of "one box tall, many wide";
// every printed brick gets its own column slot, which is what produces
// the book's characteristic ascending/descending staircase.
const BRICK_W = 12;
const BRICK_H = 14;
const PAD_L = 8;
const PAD_T = 12;
const AXIS_W = 84;

const MIN_X_ZOOM = 1;
const MAX_X_ZOOM = 20;
const MIN_Y_ZOOM = 1;
const MAX_Y_ZOOM = 6;
const WHEEL_ZOOM_STEP = 1.15;
const AXIS_DRAG_SENSITIVITY = 0.006;
const PAD_R = 10;
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

const RenkoGrid = forwardRef(({
  data, resetKey, showMa, highlight, onHoverBrick,
  exitlineLevels, showSessionDividers,
}, ref) => {
  const { swings, grid, meta, indicators } = data;
  const frameRef = useRef(null);
  const mainSvgRef = useRef(null);
  const axisSvgRef = useRef(null);
  const dragRef = useRef(null);

  const [xZoom, setXZoom] = useState(1);
  const [yZoom, setYZoom] = useState(1);
  const [panX, setPanX] = useState(0);
  const [panY, setPanY] = useState(0);
  const [dragging, setDragging] = useState(false);
  const [autoScaleY, setAutoScaleY] = useState(true);

  const { bricks, swingBrickRange } = useMemo(() => {
    // Recompute correct per-brick levels (the flattenSwings helper above
    // walks start_level -> end_level directly, this recomputes cleanly).
    const out = [];
    const ranges = new Map();
    swings.forEach((s) => {
      const first = out.length;
      const n = s.box_count;
      for (let k = 0; k < n; k += 1) {
        const level = s.direction === "up"
          ? s.bottom_level + k
          : s.top_level - k;
        out.push({ globalIndex: out.length, level, direction: s.direction, swingIndex: s.index });
      }
      ranges.set(s.index, { first, last: out.length - 1 });
    });
    return { bricks: out, swingBrickRange: ranges };
  }, [swings]);

  const rowOf = useCallback((lvl) => grid.max_level - lvl, [grid.max_level]);
  const brickX = useCallback((i) => PAD_L + i * BRICK_W, []);

  const plotW = PAD_L + bricks.length * BRICK_W + PAD_R;
  const contentH = PAD_T * 2 + (grid.max_level - grid.min_level + 1) * BRICK_H;

  const fitYToWindow = useCallback((vxVal, viewWVal) => {
    const visible = bricks.filter((b) => {
      const x = brickX(b.globalIndex);
      return x + BRICK_W > vxVal && x < vxVal + viewWVal;
    });
    if (!visible.length) return null;
    let minLevel = Infinity;
    let maxLevel = -Infinity;
    visible.forEach((b) => {
      if (b.level < minLevel) minLevel = b.level;
      if (b.level > maxLevel) maxLevel = b.level;
    });
    // Exitline levels routinely sit outside the traded range currently in
    // view — extend the fitted band so the ladder is never clipped
    // off-screen (see PnfChart.jsx's identical fix for the full reasoning).
    if (exitlineLevels?.levels) {
      const prices = EXITLINE_VISIBLE_LEVELS.map((k) => exitlineLevels.levels[k]).filter((v) => v != null);
      if (exitlineLevels.ltp != null) prices.push(exitlineLevels.ltp);
      prices.forEach((price) => {
        const lvl = priceToFractionalLevel(price, grid.levels);
        if (lvl == null) return;
        if (lvl < minLevel) minLevel = lvl;
        if (lvl > maxLevel) maxLevel = lvl;
      });
    }
    const rowTop = rowOf(maxLevel);
    const rowBottom = rowOf(minLevel);
    const padRows = Math.max(1.5, (rowBottom - rowTop) * 0.08);
    const desiredViewH = (rowBottom - rowTop + padRows * 2) * BRICK_H + PAD_T * 2;
    const nz = clampNum(contentH / desiredViewH, MIN_Y_ZOOM, MAX_Y_ZOOM);
    const nViewH = contentH / nz;
    const centerY = PAD_T + ((rowTop + rowBottom) / 2) * BRICK_H + BRICK_H / 2;
    const panYval = clampNum(centerY - nViewH / 2, 0, Math.max(0, contentH - nViewH));
    return { yZoom: nz, panY: panYval };
  }, [bricks, brickX, rowOf, contentH, exitlineLevels, grid.levels]);

  const resetView = useCallback(() => {
    const pxW = mainSvgRef.current?.getBoundingClientRect().width || plotW;
    const initViewW = Math.min(plotW, pxW);
    const initXZoom = clampNum(plotW / initViewW, MIN_X_ZOOM, MAX_X_ZOOM);
    const initPanX = Math.max(0, plotW - plotW / initXZoom);
    setXZoom(initXZoom);
    setPanX(initPanX);
    setAutoScaleY(true);
    const fit = fitYToWindow(initPanX, plotW / initXZoom);
    if (fit) { setYZoom(fit.yZoom); setPanY(fit.panY); }
    else { setYZoom(1); setPanY(0); }
  }, [plotW, fitYToWindow]);

  useImperativeHandle(ref, () => ({ resetView }), [resetView]);

  useEffect(() => {
    if (!autoScaleY) return;
    const vw = plotW / xZoom;
    const vxNow = clampNum(panX, 0, Math.max(0, plotW - vw));
    const fit = fitYToWindow(vxNow, vw);
    if (fit) { setYZoom(fit.yZoom); setPanY(fit.panY); }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [autoScaleY, panX, xZoom, plotW, fitYToWindow]);

  useLayoutEffect(() => {
    resetView();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [resetKey]);

  const viewW = plotW / xZoom;
  const viewH = contentH / yZoom;
  const vx = clampNum(panX, 0, Math.max(0, plotW - viewW));
  const vy = clampNum(panY, 0, Math.max(0, contentH - viewH));

  useEffect(() => {
    const el = frameRef.current;
    if (!el) return undefined;
    const onWheel = (e) => {
      e.preventDefault();
      const overAxis = axisSvgRef.current?.contains(e.target);
      const factor = e.deltaY < 0 ? WHEEL_ZOOM_STEP : 1 / WHEEL_ZOOM_STEP;
      if (overAxis) {
        setAutoScaleY(false);
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

  const onPanPointerDown = (e) => {
    e.currentTarget.setPointerCapture(e.pointerId);
    dragRef.current = { mode: "pan", startX: e.clientX, startY: e.clientY, panX0: vx, panY0: vy };
    setDragging(true);
  };
  const onAxisPointerDown = (e) => {
    e.currentTarget.setPointerCapture(e.pointerId);
    setAutoScaleY(false);
    dragRef.current = { mode: "yzoom", startY: e.clientY, yZoom0: yZoom, centerY0: vy + viewH / 2 };
    setDragging(true);
  };
  const onPointerMove = (e) => {
    const d = dragRef.current;
    if (!d) return;
    if (d.mode === "pan") {
      const rect = mainSvgRef.current.getBoundingClientRect();
      const dContentX = -(e.clientX - d.startX) * (viewW / rect.width);
      setPanX(clampNum(d.panX0 + dContentX, 0, Math.max(0, plotW - viewW)));
      if (!autoScaleY) {
        const dContentY = -(e.clientY - d.startY) * (viewH / rect.height);
        setPanY(clampNum(d.panY0 + dContentY, 0, Math.max(0, contentH - viewH)));
      }
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

  const axisPxH = axisSvgRef.current?.getBoundingClientRect().height || 620;
  const pxPerRow = (axisPxH / viewH) * BRICK_H;
  const labelStep = Math.max(1, Math.ceil(MIN_LABEL_GAP_PX / Math.max(pxPerRow, 1)));

  const priceToRow = useCallback((price) => {
    const lvls = grid.levels;
    for (let k = 0; k < lvls.length - 1; k += 1) {
      const hi = lvls[lvls.length - 1 - k].price;
      const lo = lvls[lvls.length - 2 - k].price;
      if (price <= hi && price >= lo) {
        return k + (hi - price) / (hi - lo || 1);
      }
    }
    return null;
  }, [grid.levels]);

  const maPoints = useMemo(() => {
    if (!showMa) return null;
    const series = indicators?.moving_average || [];
    const pts = [];
    series.forEach((price, n) => {
      if (price == null) return;
      const row = priceToRow(price);
      if (row == null) return;
      pts.push(`${brickX(n) + BRICK_W / 2},${PAD_T + row * BRICK_H + BRICK_H / 2}`);
    });
    return pts.length > 1 ? pts.join(" ") : null;
  }, [showMa, indicators, priceToRow, brickX]);

  // Exitline overlay — see PnfChart.jsx's identical computation.
  const exitlineLines = useMemo(() => {
    if (!exitlineLevels?.levels) return [];
    const out = EXITLINE_VISIBLE_LEVELS.map((k) => {
      const price = exitlineLevels.levels[k];
      if (price == null) return null;
      const lvl = priceToFractionalLevel(price, grid.levels);
      if (lvl == null) return null;
      return { key: k, price, y: PAD_T + (grid.max_level - lvl) * BRICK_H, color: EXITLINE_LEVEL_COLORS[k], label: EXITLINE_DISPLAY_LABELS[k] };
    }).filter(Boolean);
    if (exitlineLevels.ltp != null) {
      const lvl = priceToFractionalLevel(exitlineLevels.ltp, grid.levels);
      if (lvl != null) {
        out.push({ key: "LTP", price: exitlineLevels.ltp, y: PAD_T + (grid.max_level - lvl) * BRICK_H, color: "#437EEB", label: "PX" });
      }
    }
    return out;
  }, [exitlineLevels, grid.levels, grid.max_level]);

  // Session dividers — a vertical line at the left edge of the first
  // brick of each new calendar day's swing, intraday only.
  const sessionDividers = useMemo(() => {
    if (!showSessionDividers) return [];
    return findSessionBoundaries(swings).map((b) => {
      const range = swingBrickRange.get(b.index);
      if (!range) return null;
      return { ...b, x: brickX(range.first) };
    }).filter(Boolean);
  }, [showSessionDividers, swings, swingBrickRange, brickX]);

  return (
    <div
      ref={frameRef}
      className="flex rounded-lg border border-white/10 bg-[#0B1220] overflow-hidden select-none h-full"
    >
      <div style={{ position: "relative", width: `calc(100% - ${AXIS_W}px)`, height: "100%" }}>
        <svg
          ref={mainSvgRef}
          viewBox={`${vx} ${vy} ${viewW} ${viewH}`}
          preserveAspectRatio="none"
          style={{ width: "100%", height: "100%", touchAction: "none", cursor: dragging ? "grabbing" : "grab" }}
          className="block font-mono-ui"
          onPointerDown={onPanPointerDown}
          onPointerMove={onPointerMove}
          onPointerUp={onPointerUp}
          onPointerCancel={onPointerUp}
          onDoubleClick={resetView}
        >
          {maPoints && (
            <polyline points={maPoints} fill="none" stroke="#38BDF8" strokeWidth="1.5" opacity="0.8" vectorEffect="non-scaling-stroke" />
          )}

          {/* the bricks — hollow (bullish) / filled (bearish), the
              book's own colour convention (Ch.1) */}
          {bricks.map((b) => {
            const x = brickX(b.globalIndex);
            const y = PAD_T + rowOf(b.level) * BRICK_H;
            const bullish = b.direction === "up";
            const dim = highlight && !(b.swingIndex >= highlight.start_index && b.swingIndex <= highlight.index);
            const stroke = bullish ? "#34D399" : "#F87171";
            return (
              <g key={b.globalIndex} opacity={dim ? 0.22 : 1}
                 onMouseEnter={() => onHoverBrick?.(b)} onMouseLeave={() => onHoverBrick?.(null)}
                 style={{ cursor: "crosshair" }}>
                <rect
                  x={x} y={y} width={BRICK_W} height={BRICK_H}
                  fill={bullish ? "transparent" : stroke}
                  fillOpacity={bullish ? 0 : 0.85}
                  stroke={stroke} strokeWidth="1.25"
                  vectorEffect="non-scaling-stroke"
                />
              </g>
            );
          })}

          {/* highlighted pattern bracket, mapped from swing index range
              to the brick columns that swing occupies */}
          {highlight && (() => {
            const startRange = swingBrickRange.get(highlight.start_index);
            const endRange = swingBrickRange.get(highlight.index);
            if (!startRange || !endRange) return null;
            const a = brickX(startRange.first);
            const b = brickX(endRange.last) + BRICK_W;
            const tone = highlight.bias === "bearish" ? "#F87171" : highlight.bias === "bullish" ? "#34D399" : "#94A3B8";
            return (
              <rect
                x={a} y={PAD_T} width={Math.max(b - a, BRICK_W)} height={contentH - PAD_T * 2}
                fill={tone} fillOpacity="0.07" stroke={tone} strokeOpacity="0.5" strokeWidth="1" rx="3"
                vectorEffect="non-scaling-stroke"
              />
            );
          })()}

          {/* Intraday session dividers — see PnfChart.jsx's identical block. */}
          {sessionDividers.map((b) => (
            <line
              key={`session-${b.index}`}
              x1={b.x} y1={PAD_T} x2={b.x} y2={contentH - PAD_T}
              stroke="#64748B" strokeWidth="1" strokeDasharray="3 3" opacity="0.55"
              vectorEffect="non-scaling-stroke"
            />
          ))}

          {/* Exitline levels + LTP — full-width horizontal lines at each
              level's true fractional price row. */}
          {exitlineLines.map((ln) => (
            <line
              key={`exitline-${ln.key}`}
              x1={0} y1={ln.y} x2={plotW} y2={ln.y}
              stroke={ln.color} strokeWidth={ln.key === "LTP" ? 1.5 : 1.25}
              strokeDasharray={ln.key === "LTP" ? undefined : "5 3"}
              opacity={ln.key === "LTP" ? 0.9 : 0.75}
              vectorEffect="non-scaling-stroke"
            />
          ))}
        </svg>

      </div>

      <div
        ref={axisSvgRef}
        style={{ width: AXIS_W, height: "100%", touchAction: "none", cursor: "ns-resize", flexShrink: 0, position: "relative", overflow: "hidden" }}
        className="font-mono-ui border-l border-white/5"
        onPointerDown={onAxisPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onPointerCancel={onPointerUp}
        onDoubleClick={() => setAutoScaleY(true)}
      >
        {grid.levels.map(({ level, price }) => {
          const y = PAD_T + rowOf(level) * BRICK_H;
          const isLabel = (grid.max_level - level) % labelStep === 0;
          if (!isLabel) return null;
          const topPx = ((y + BRICK_H / 2 - vy) / viewH) * axisPxH;
          if (topPx < -20 || topPx > axisPxH + 20) return null;
          return (
            <div key={level} style={{ position: "absolute", left: 10, top: topPx, transform: "translateY(-50%)", fontSize: 10.5, lineHeight: 1, color: "#94A3B8", whiteSpace: "nowrap" }}>
              {fmtNum(price, price < 100 ? 2 : 1)}
            </div>
          );
        })}

        {/* Exitline level chips — see PnfChart.jsx's identical block. */}
        {exitlineLines.map((ln) => {
          const topPx = ((ln.y - vy) / viewH) * axisPxH;
          if (topPx < -20 || topPx > axisPxH + 20) return null;
          return (
            <div
              key={`exitline-axis-${ln.key}`}
              style={{
                position: "absolute", left: 2, top: topPx, transform: "translateY(-50%)",
                display: "flex", alignItems: "center", gap: 4,
              }}
            >
              <span
                style={{
                  fontSize: 9.5, fontWeight: 700, lineHeight: 1.3, color: "#060B14",
                  background: ln.color, borderRadius: 3, padding: "1.5px 4px",
                }}
              >
                {ln.label}
              </span>
              <span style={{ fontSize: 10, lineHeight: 1, color: ln.color, whiteSpace: "nowrap" }}>
                {fmtNum(ln.price, ln.price < 100 ? 2 : 1)}
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
});

/* --------------------------------------------------------------------- */
/* Left tool rail                                                         */
/* --------------------------------------------------------------------- */

// `disabledReason` overrides the default "— coming soon" suffix for tools
// that ARE built but don't apply to the current selection — see
// PnfChart.jsx's identical RailButton for the reasoning.
const RailButton = ({ icon: Icon, active, disabled, title, disabledReason, onClick }) => (
  <button
    type="button"
    onClick={disabled ? undefined : onClick}
    disabled={disabled}
    title={disabled ? (disabledReason || `${title} — coming soon`) : title}
    className={`flex items-center justify-center w-9 h-9 rounded-md transition-colors ${
      disabled ? "text-slate-700 cursor-not-allowed"
        : active ? "text-sapphire-light bg-sapphire-light/10" : "text-slate-400 hover:text-white hover:bg-white/5"
    }`}
  >
    <Icon size={17} />
  </button>
);

const ToolRail = ({
  showMa, setShowMa, onReset,
  showExitline, onToggleExitline, exitlineDisabled, exitlineLoading,
  showSessionDividers, onToggleSessionDividers, sessionDividersDisabled,
}) => (
  <div className="hidden lg:flex flex-col items-center gap-1 w-12 shrink-0 border-r border-white/10 bg-[#0B1220] py-3">
    <RailButton icon={MousePointer2} active title="Cursor" onClick={() => {}} />
    <div className="w-6 h-px bg-white/10 my-1.5" />
    <RailButton icon={Activity} active={showMa} title="Moving Average" onClick={() => setShowMa((v) => !v)} />
    <RailButton icon={RotateCcw} title="Reset View" onClick={onReset} />
    <div className="w-6 h-px bg-white/10 my-1.5" />
    <RailButton
      icon={exitlineLoading ? Loader2 : Target}
      active={showExitline}
      disabled={exitlineDisabled}
      title="Exitline Levels"
      disabledReason="Exitline Levels — NSE/FUT/OPT only"
      onClick={onToggleExitline}
    />
    <RailButton
      icon={SeparatorVertical}
      active={showSessionDividers}
      disabled={sessionDividersDisabled}
      title="Session Dividers"
      disabledReason="Session Dividers — intraday only"
      onClick={onToggleSessionDividers}
    />
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

const RenkoChart = () => {
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
  const [showMa, setShowMa] = useState(true);
  const [onlyMajor, setOnlyMajor] = useState(true);
  const [onlyActive, setOnlyActive] = useState(true);
  const [live, setLive] = useState(false);
  const [showPatterns, setShowPatterns] = useState(false);

  // Exitline overlay + intraday session dividers — see exitlineOverlay.js
  // and PnfChart.jsx's identical wiring (same overlay, same instrument
  // shape, so the logic is a straight mirror).
  const [showExitline, setShowExitline] = useState(false);
  const [exitlineData, setExitlineData] = useState(null);
  const [exitlineLoading, setExitlineLoading] = useState(false);
  const [showSessionDividers, setShowSessionDividers] = useState(false);
  const [plottedInstrument, setPlottedInstrument] = useState(null);

  const [data, setData] = useState(null);
  const [plotCount, setPlotCount] = useState(0);
  const [loading, setLoading] = useState(false);
  const [highlight, setHighlight] = useState(null);
  const [hoverBrick, setHoverBrick] = useState(null);
  const gridRef = useRef(null);

  // See PnfChart.jsx's identical logic for the reasoning.
  const canGoLive = (segment === "US" || segment === "COMMODITY")
    ? !DAILY_PLUS_INTERVALS.includes(interval)
    : true;

  useEffect(() => {
    let cancelled = false;
    const t = setTimeout(() => {
      axios.get(`${API}/renko/instruments`, { params: { segment, query }, ...authHeaders() })
        .then(({ data: d }) => { if (!cancelled) setSymbols(d.symbols || []); })
        .catch(() => { if (!cancelled) setSymbols([]); });
    }, 250);
    return () => { cancelled = true; clearTimeout(t); };
  }, [segment, query]);

  useEffect(() => {
    setExpiry(""); setStrikes([]); setStrike("");
    if (!symbol || (segment !== "FUT" && segment !== "OPT")) { setExpiries([]); return; }
    axios.get(`${API}/renko/instruments`, { params: { segment, symbol }, ...authHeaders() })
      .then(({ data: d }) => setExpiries(d.expiries || []))
      .catch(() => setExpiries([]));
  }, [symbol, segment]);

  useEffect(() => {
    if (!symbol || !expiry || segment !== "OPT") return;
    axios.get(`${API}/renko/instruments`, { params: { segment, symbol, expiry }, ...authHeaders() })
      .then(({ data: d }) => setStrikes(d.strikes || []))
      .catch(() => setStrikes([]));
  }, [symbol, expiry, segment]);

  // Every segment now offers every interval, so nothing needs resetting
  // when the segment changes.

  const fetchChart = useCallback(async ({ silent = false } = {}) => {
    if (!symbol) return;
    if (!silent) { setLoading(true); setHighlight(null); }
    try {
      let d;
      if (segment === "CRYPTO") {
        const bars = await fetchCryptoBars(symbol, interval);
        ({ data: d } = await axios.post(`${API}/renko/chart/crypto`, { symbol, bars }, {
          params: { interval, box_pct: boxPct },
          ...authHeaders(),
        }));
      } else {
        ({ data: d } = await axios.get(`${API}/renko/chart`, {
          params: {
            symbol, segment, interval, box_pct: boxPct,
            ...(segment === "FUT" || segment === "OPT" ? { expiry } : {}),
            ...(segment === "OPT" ? { strike, option_type: optionType } : {}),
          },
          ...authHeaders(),
        }));
      }
      setData(d);
      if (!silent) {
        setPlotCount((n) => n + 1);
        setPlottedInstrument({ segment, symbol, expiry, strike, optionType });
      }
    } catch (e) {
      if (!silent) { toast.error(e?.response?.data?.detail || "Could not plot that chart."); setData(null); }
    } finally {
      if (!silent) setLoading(false);
    }
  }, [symbol, segment, interval, boxPct, expiry, strike, optionType]);

  // See PnfChart.jsx's identical effect for the reasoning.
  useEffect(() => {
    if (!showExitline || !plottedInstrument || !EXITLINE_SEGMENTS.includes(plottedInstrument.segment)) {
      setExitlineData(null);
      return undefined;
    }
    let cancelled = false;
    setExitlineLoading(true);
    fetchExitlineLevels(plottedInstrument)
      .then((d) => { if (!cancelled) setExitlineData(d); })
      .catch(() => {
        if (!cancelled) {
          setExitlineData(null);
          toast.error("Could not load Exitline levels for this instrument.");
        }
      })
      .finally(() => { if (!cancelled) setExitlineLoading(false); });
    return () => { cancelled = true; };
  }, [showExitline, plottedInstrument]);

  const plot = () => {
    if (!symbol) { toast.error("Pick an instrument first."); return; }
    if ((segment === "FUT" || segment === "OPT") && !expiry) { toast.error("Pick an expiry."); return; }
    if (segment === "OPT" && !strike) { toast.error("Pick a strike."); return; }
    fetchChart();
  };

  useEffect(() => {
    if (!live || !data || !canGoLive) return undefined;
    const ms = LIVE_REFRESH_MS[interval] || 30000;
    const id = setInterval(() => fetchChart({ silent: true }), ms);
    return () => clearInterval(id);
  }, [live, data, canGoLive, interval, fetchChart]);

  useEffect(() => {
    if (!canGoLive && live) setLive(false);
  }, [canGoLive, live]);

  const visiblePatterns = useMemo(() => {
    if (!data) return [];
    return data.patterns
      .filter((p) => (!onlyMajor || p.major) && (!onlyActive || p.active))
      .sort((a, b) => b.index - a.index)
      .slice(0, 120);
  }, [data, onlyMajor, onlyActive]);

  // The header label sits directly next to Cont./Rev., which are computed
  // off the LITERAL last-printed brick's direction (renko_chart.py's
  // current_swing) - so this label has to track that same thing, not
  // data.summary.bias (a separate pattern-vote composite across the whole
  // chart's active patterns). The two can disagree - e.g. many more
  // bullish than bearish patterns historically active, but the very last
  // brick is a bearish pullback - and showing the pattern-vote label next
  // to brick-direction levels made Cont. read as sitting BELOW Rev. while
  // still labeled "Bullish", which looks inverted/wrong even though the
  // underlying numbers were always correct for the real last-brick direction.
  const swingDirection = data?.summary?.current_swing?.direction;
  const bias = swingDirection === "up" ? "bullish" : swingDirection === "down" ? "bearish" : "neutral";
  const BiasIcon = BIAS_STYLE[bias].Icon;

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
            {BOX_SIZES.map((b) => <option key={b} value={b}>{b}% brick</option>)}
          </select>

          <button
            onClick={plot} disabled={loading}
            className="h-[30px] px-3.5 rounded-md bg-sapphire-light/90 hover:bg-sapphire-light text-white text-xs font-semibold transition-colors disabled:opacity-50 flex items-center justify-center gap-1.5"
          >
            {loading ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Crosshair className="w-3.5 h-3.5" />}
            Plot
          </button>

          {canGoLive && data && (
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

          {data && (
            <button
              onClick={() => setShowPatterns(true)}
              className="xl:hidden h-[30px] px-3 rounded-md border border-white/10 text-slate-300 hover:text-white text-xs font-medium transition-colors flex items-center gap-1.5"
            >
              <Layers size={13} />
              Formations ({visiblePatterns.length})
            </button>
          )}
        </div>

        {segment === "US" && US_INDEX_KEYS.includes(symbol) && (
          <p className="text-[11px] text-slate-500 mt-2 max-w-3xl">
            {DAILY_PLUS_INTERVALS.includes(interval)
              ? "Nasdaq 100 and S&P 500 are plotted from the real index (daily/weekly/monthly)."
              : "Intraday plots from each index's most liquid tracking ETF (QQQ / SPY), live — a different underlying from the daily/weekly/monthly index chart above."}
          </p>
        )}
        {segment === "COMMODITY" && (
          <p className="text-[11px] text-slate-500 mt-2 max-w-3xl">
            {DAILY_PLUS_INTERVALS.includes(interval)
              ? "Gold is plotted from COMEX futures at daily/weekly/monthly — a close proxy for spot XAUUSD, not spot itself."
              : "Intraday plots spot XAUUSD, live — the actual spot market, not the COMEX futures proxy used on the daily/weekly/monthly chart."}
          </p>
        )}
        {segment === "CRYPTO" && (
          <p className="text-[11px] text-slate-500 mt-2 max-w-3xl">
            Spot USDT pairs, live and intraday included — these markets trade 24/7, so there's no session close to wait on.
          </p>
        )}
      </div>

      {data && (
        <div className="shrink-0 flex flex-wrap items-center gap-x-4 gap-y-1 px-3 sm:px-4 py-2 border-b border-white/5 bg-[#080D16] text-[11px] font-mono-ui text-slate-400">
          <span className="text-white font-semibold text-xs">{data.instrument.tradingsymbol}</span>
          <span>{data.params.box_pct}% brick · {REVERSAL_BOXES}-box reversal · close-only</span>
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
            {data.meta.total_bricks} bricks · {data.meta.bars} bars · {data.meta.first_label} → {data.meta.last_label}
          </span>
        </div>
      )}

      {!data && !loading && (
        <div className="flex-1 min-h-0 flex items-center justify-center p-4 sm:p-6">
          <EmptyState reason="Pick an instrument and hit Plot to build its brick chart." />
        </div>
      )}

      {data && (
        <div className="flex-1 flex min-h-0">
          <ToolRail
            showMa={showMa} setShowMa={setShowMa}
            onReset={() => gridRef.current?.resetView()}
            showExitline={showExitline}
            onToggleExitline={() => setShowExitline((v) => !v)}
            exitlineDisabled={!EXITLINE_SEGMENTS.includes(segment)}
            exitlineLoading={exitlineLoading}
            showSessionDividers={showSessionDividers}
            onToggleSessionDividers={() => setShowSessionDividers((v) => !v)}
            sessionDividersDisabled={!isIntradayInterval(interval)}
          />

          <div className="flex-1 min-w-0 min-h-0 flex flex-col p-3 sm:p-4">
            <div className="flex-1 min-h-0">
              <RenkoGrid
                ref={gridRef}
                data={data}
                resetKey={plotCount}
                showMa={showMa}
                highlight={highlight}
                onHoverBrick={setHoverBrick}
                exitlineLevels={showExitline ? exitlineData : null}
                showSessionDividers={showSessionDividers && isIntradayInterval(interval)}
              />
            </div>
            <div className="shrink-0 mt-1.5 flex items-center justify-between text-[11px] text-slate-500 font-mono-ui">
              <span>
                {hoverBrick
                  ? <>Brick {hoverBrick.globalIndex} · {hoverBrick.direction}</>
                  : "scroll to zoom · drag to pan · drag/scroll price axis to scale (double-click axis to auto-fit again) · double-click chart to reset"}
              </span>
            </div>
          </div>

          {showPatterns && (
            <div className="fixed inset-0 z-20 bg-black/60 xl:hidden" onClick={() => setShowPatterns(false)} />
          )}
          <div
            className={`${showPatterns ? "flex" : "hidden"} xl:flex flex-col fixed xl:static inset-x-0 bottom-0 xl:inset-auto z-30 xl:z-auto max-h-[75vh] xl:max-h-none w-full xl:w-[320px] shrink-0 rounded-t-2xl xl:rounded-none border-t xl:border-t-0 xl:border-l border-white/10 bg-[#0B1220] xl:bg-white/[0.02] p-4 overflow-y-auto`}
          >
            <div className="flex items-center justify-between mb-3">
              <h2 className="font-mono-ui text-[10px] uppercase tracking-[0.18em] text-slate-500">
                Formations ({visiblePatterns.length})
              </h2>
              <button onClick={() => setShowPatterns(false)} className="xl:hidden text-slate-500 hover:text-white p-1">
                <X size={16} />
              </button>
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
                      <span>swing {p.index}</span>
                      {p.trigger_price != null && <span>trigger {fmtNum(p.trigger_price)}</span>}
                      {p.failure_price != null && <span>fails {fmtNum(p.failure_price)}</span>}
                      {p.extension_target_price != null && <span>ext. target {fmtNum(p.extension_target_price)}</span>}
                    </div>
                  </button>
                </li>
              ))}
            </ul>
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

export default RenkoChart;
