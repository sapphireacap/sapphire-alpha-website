import {
  useState, useEffect, useLayoutEffect, useMemo, useCallback, useRef,
  forwardRef, useImperativeHandle,
} from "react";
import axios from "axios";
import { toast } from "sonner";
import {
  Loader2, Search, Crosshair, TrendingUp, TrendingDown, Minus,
  MousePointer2, Activity, RotateCcw, Pencil, Ruler, Type, Eraser, Radio,
  X, Zap, Target, SeparatorVertical, Info,
} from "lucide-react";
import { EmptyState } from "./QuantLab";
import { TRADER_TOKEN_KEY } from "../Auth";
import { PnfComboModal } from "./PnfComboModal";
import {
  EXITLINE_SEGMENTS, EXITLINE_VISIBLE_LEVELS, EXITLINE_LEVEL_COLORS, EXITLINE_DISPLAY_LABELS,
  fetchExitlineLevels, priceToFractionalLevel, findSessionBoundaries, isIntradayInterval,
} from "./exitlineOverlay";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;
const authHeaders = () => ({ headers: { Authorization: `Bearer ${localStorage.getItem(TRADER_TOKEN_KEY)}` } });

// Exported for PnfWorkspace's single shared controller, which needs the
// exact same segment/interval choices as this file's own toolbar.
export const SEGMENTS = [
  { key: "NSE", label: "NSE (Cash)" },
  { key: "FUT", label: "Futures" },
  { key: "OPT", label: "Options" },
  { key: "US", label: "US Stocks" },
  { key: "COMMODITY", label: "Commodities" },
  { key: "CRYPTO", label: "Crypto" },
];

// RS/Straddle/Strangle only exists in this file's own standalone toolbar
// (below) -- PnfWorkspace's shared multi-cell dropdown still uses the
// plain SEGMENTS list above and has no UI yet for a two-leg instrument,
// so it's kept out of the array Workspace imports rather than adding a
// segment value its own plotInstrument() call can't actually fill in.
export const STANDALONE_SEGMENTS = [...SEGMENTS, { key: "COMBO", label: "RS / Straddle / Strangle" }];

export const INTERVALS = [
  { key: "daily", label: "Daily" },
  { key: "weekly", label: "Weekly" },
  { key: "monthly", label: "Monthly" },
  { key: "60", label: "60 min" },
  { key: "30", label: "30 min" },
  { key: "15", label: "15 min" },
  { key: "5", label: "5 min" },
  { key: "1", label: "1 min" },
];
// Poll cadence scales with bar size -- no point re-fetching a 60-min chart
// every 15s, and a 1-min chart every 60s would visibly lag the tape.
// Daily/weekly/monthly still move during the session too: the backend
// synthesizes today's still-forming bar off a live LTP quote (see
// backend/pnf_chart.py's _with_live_bar) precisely so the CURRENT column
// isn't frozen at yesterday's close until Definedge finalizes the day
// candle at EOD -- polling less aggressively than intraday since the
// underlying quote itself is only refreshed once per request, not ticking.
const LIVE_REFRESH_MS = {
  "1": 15000, "5": 20000, "15": 30000, "30": 45000, "60": 60000,
  daily: 60000, weekly: 60000, monthly: 60000,
};

// The intervals served by Yahoo Finance's free chart endpoint, which has no
// real intraday data (see backend/yahoo_finance_client.py). No longer a
// restriction on any segment — both segments that used to be capped here
// have their own intraday source now (US Indices via Alpaca, Gold via a
// local MetaTrader 5 terminal, see backend/mt5_client.py) — this just
// marks which intervals still route through Yahoo, since for both of those
// segments the daily+ chart and the intraday chart are different
// underlying instruments and the UI has to say so.
const DAILY_PLUS_INTERVALS = ["daily", "weekly", "monthly"];


// Crypto bars are fetched straight from the browser, not proxied through
// the backend -- Binance's public klines API sends a wildcard CORS header
// (same as the Crypto Markets dashboard already relies on), but more
// importantly, calling it FROM the backend gets geo-blocked (verified
// live, 2026-08-04: identical request works from a real browser, 502s
// from the Render-hosted server). The backend still does 100% of the
// actual P&F construction/pattern work -- this only fetches raw OHLC and
// hands it to POST /pnf/chart/crypto (see backend/pnf_routes.py) to run
// the engine. Mirrors backend/binance_client.py's interval map; keep the
// two in sync if either changes.
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

// The book's own commonly-used box sizes. Percentage boxes (not absolute)
// are the default because they keep the box a constant *proportion* of
// price, which is what makes one parameter set usable across instruments
// trading at wildly different absolute levels.
export const BOX_SIZES = [0.01, 0.02, 0.05, 0.1, 0.25, 0.5, 1, 2, 3];

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
/* Commentary panel                                                       */
/* --------------------------------------------------------------------- */
// Standard book-level P&F formation names, not a Definedge secret — the
// same engine ("Trading The Markets The Point & Figure Way", the source
// pnf_engine.py is validated against) implements exactly these four.
// Picking the MOST RECENT occurrence of each in the chart's own real
// pattern list, rather than inventing a value: a name with no match
// simply means that formation isn't currently present, shown as "—".
const COMMENTARY_PATTERNS = [
  { key: "dbs", label: "Double Bottom Sell", name: "double_bottom_sell" },
  { key: "hp", label: "High Pole", name: "high_pole" },
  { key: "dtb", label: "Double Top Buy", name: "double_top_buy" },
  { key: "lp", label: "Low Pole", name: "low_pole" },
];

const latestPatternOf = (patterns, name) => {
  const matches = (patterns || []).filter((p) => p.name === name);
  return matches.length ? matches.reduce((best, p) => (p.index > best.index ? p : best)) : null;
};

const StatRow = ({ label, value }) => (
  <div className="flex items-center justify-between py-0.5">
    <span className="text-[11px] text-slate-500">{label}</span>
    <span className="text-[11px] font-mono-ui text-white">{value}</span>
  </div>
);

// Right-side info panel — position matches the reference platform's own
// TradePoint window (confirmed with the user: right, not left). Two
// states: whole-chart stats by default, or one column's own stats while
// hovering it -- Column Reversal / Continuation / the four named
// formations stay whole-chart concepts either way, since "what would the
// NEXT print do" only means something for the presently open column, not
// an arbitrary column in the chart's history.
//
// `variant`: "sidebar" (default) is the desktop right-hand rail, hidden
// below md since there's no room for a fixed 240px column on a phone.
// "sheet" is the same content re-skinned as a full-width panel for the
// mobile bottom sheet below -- one component, two wrappers, so the two
// surfaces can never drift out of sync on what they actually show.
const CommentaryPanel = ({ data, hoverCol, variant = "sidebar", onClose }) => {
  if (!data) return null;
  const { columns, summary, patterns, params } = data;
  if (!columns?.length) return null;

  const last = columns[columns.length - 1];
  const prev = columns.length > 1 ? columns[columns.length - 2] : null;

  const scoped = hoverCol || last;
  const hi = hoverCol
    ? scoped.top_price
    : columns.reduce((m, c) => Math.max(m, c.top_price), -Infinity);
  const lo = hoverCol
    ? scoped.bottom_price
    : columns.reduce((m, c) => Math.min(m, c.bottom_price), Infinity);
  const hiCol = hoverCol ? scoped : columns.reduce((m, c) => (c.top_price > m.top_price ? c : m));
  const loCol = hoverCol ? scoped : columns.reduce((m, c) => (c.bottom_price < m.bottom_price ? c : m));

  // "Current Leg %" — this column's own move so far, box_count x box size,
  // signed by direction. Only meaningful in percentage-box mode; an
  // absolute box_value chart has no natural "%" to show here.
  const legPct = params?.box_pct != null
    ? scoped.box_count * params.box_pct * (scoped.direction === "X" ? 1 : -1)
    : null;

  // What this column reversed away from -- the previous column's own
  // extreme, on its own end date. Real and computable; deliberately not
  // labelled as "yesterday's close" or similar, since it's a P&F leg
  // boundary, not a calendar-day price.
  const priorLeg = prev ? (prev.direction === "X" ? prev.top_price : prev.bottom_price) : null;

  const wrapperClass = variant === "sheet"
    ? "flex flex-col w-full max-h-[65vh] bg-[#0B1220] px-4 pt-2 pb-5 overflow-y-auto rounded-t-2xl border-t border-white/10"
    : "hidden md:flex flex-col w-[240px] shrink-0 border-l border-white/10 bg-[#0B1220] px-3.5 py-3 overflow-y-auto";

  return (
    <div className={wrapperClass} data-testid="pnf-commentary-panel">
      {variant === "sheet" && (
        <>
          <div className="flex justify-end -mr-1">
            <button
              type="button"
              onClick={onClose}
              className="text-slate-500 hover:text-white p-1"
              aria-label="Close"
            >
              <X size={16} />
            </button>
          </div>
          <div className="w-10 h-1 rounded-full bg-white/15 mx-auto mb-3" aria-hidden="true" />
        </>
      )}
      <StatRow label="Hi" value={fmtNum(hi)} />
      <StatRow label="Lo" value={fmtNum(lo)} />
      <StatRow label="Hi Date" value={hiCol?.start_label ? hiCol.start_label.slice(0, 10) : "—"} />
      <StatRow label="Lo Date" value={loCol?.start_label ? loCol.start_label.slice(0, 10) : "—"} />
      <StatRow label="Boxes" value={scoped.box_count} />
      <StatRow label="Mid" value={fmtNum((hi + lo) / 2)} />
      {!hoverCol && (
        <>
          <StatRow label="Leg %" value={legPct == null ? "—" : `${legPct > 0 ? "+" : ""}${legPct.toFixed(2)}%`} />
          <StatRow label="Prior Leg" value={priorLeg == null ? "—" : fmtNum(priorLeg)} />
        </>
      )}

      <div className="mt-4 pt-3 border-t border-white/10">
        <p className="font-mono-ui text-[10px] uppercase tracking-[0.18em] text-slate-500 mb-2">Commentary</p>
        <StatRow label="Column Reversal" value={fmtNum(summary?.reversal_price)} />
        <StatRow label="Continuation" value={fmtNum(summary?.continuation_price)} />
        {COMMENTARY_PATTERNS.map(({ key, label, name }) => {
          const p = latestPatternOf(patterns, name);
          return <StatRow key={key} label={label} value={p?.trigger_price != null ? fmtNum(p.trigger_price) : "—"} />;
        })}
      </div>
    </div>
  );
};

/* --------------------------------------------------------------------- */
/* The chart itself                                                       */
/* --------------------------------------------------------------------- */

const PnfGrid = forwardRef(({
  data, resetKey, showTrendLines, showMa, showSmartTrend, onHoverColumn,
  exitlineLevels, showSessionDividers,
}, ref) => {
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
  // Mirrors TradingView/TradePoint's "autoscale" price axis: by default the
  // Y window always re-fits itself to whatever columns are horizontally in
  // view, so the visible price band fills the pane instead of sitting in a
  // fixed window sized for the entire history (which leaves most of the
  // pane empty once you've panned into a narrower slice of it). Any manual
  // zoom/drag on the price axis switches this off — same as TradingView —
  // until the user double-clicks the axis to turn it back on.
  const [autoScaleY, setAutoScaleY] = useState(true);

  // Level -> row index, counted from the TOP of the grid so that higher
  // prices render higher on screen.
  const rowOf = useCallback((lvl) => grid.max_level - lvl, [grid.max_level]);
  const colX = useCallback((i) => PAD_L + (i - meta.render_offset) * COL_W, [meta.render_offset]);

  const plotW = PAD_L + columns.length * COL_W + PAD_R;
  const contentH = PAD_T * 2 + (grid.max_level - grid.min_level + 1) * ROW_H;

  // Given a horizontal window (in content units), returns the {yZoom, panY}
  // that frames exactly the price range spanned by the columns inside that
  // window, plus a little breathing room top/bottom. This scales Y
  // independently of X on purpose: checked against the actual reference
  // terminal this was modeled after (TradePoint, TCS daily 0.25% box) and
  // its own boxes are NOT square when a column runs long -- O's render as
  // overlapping ellipses and X's as a compressed woven texture so the
  // full visible price range always fits the pane, rather than a fixed
  // square box size clipping most of it off-screen. Matching that took
  // priority over the "COL_W === ROW_H is a true square lattice" framing
  // this file used to lead with; a locked 1:1 scale was tried and reverted
  // after the reference showed it isn't how the real tool behaves.
  const fitYToWindow = useCallback((vxVal, viewWVal) => {
    const visible = columns.filter((c) => {
      const x = colX(c.index);
      return x + COL_W > vxVal && x < vxVal + viewWVal;
    });
    if (!visible.length) return null;
    let minLevel = Infinity;
    let maxLevel = -Infinity;
    visible.forEach((c) => c.levels.forEach((lvl) => {
      if (lvl < minLevel) minLevel = lvl;
      if (lvl > maxLevel) maxLevel = lvl;
    }));
    // Exitline levels routinely sit outside the traded range currently in
    // view (H5/L5, often H4/L4 too) — extend the fitted band to always
    // include every visible level + LTP, same "never clip the ladder off
    // screen" fix Exitline.jsx's own autoscaleInfoProvider does.
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
    const desiredViewH = (rowBottom - rowTop + padRows * 2) * ROW_H + PAD_T * 2;
    const nz = clampNum(contentH / desiredViewH, MIN_Y_ZOOM, MAX_Y_ZOOM);
    const nViewH = contentH / nz;
    const centerY = PAD_T + ((rowTop + rowBottom) / 2) * ROW_H + ROW_H / 2;
    const panYval = clampNum(centerY - nViewH / 2, 0, Math.max(0, contentH - nViewH));
    return { yZoom: nz, panY: panYval };
  }, [columns, colX, rowOf, contentH, exitlineLevels, grid.levels]);

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

  // Keep the price axis auto-fitted to whatever's horizontally in view --
  // re-running on every pan/zoom of X (and on new columns arriving from a
  // live refresh) for as long as autoscale hasn't been manually overridden.
  useEffect(() => {
    if (!autoScaleY) return;
    const vw = plotW / xZoom;
    const vxNow = clampNum(panX, 0, Math.max(0, plotW - vw));
    const fit = fitYToWindow(vxNow, vw);
    if (fit) { setYZoom(fit.yZoom); setPanY(fit.panY); }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [autoScaleY, panX, xZoom, plotW, fitYToWindow]);

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
      // While autoscale is on, the price axis re-fits itself off the new
      // panX (see the effect above) — a manual Y nudge here would just get
      // overwritten a tick later, so only hand-pan Y once it's overridden.
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

  // Price labels spaced by REAL on-screen pixels, not a fixed row count —
  // a 0.25% box over a long history produces hundreds of levels, and
  // labelling every one (or even a fixed fraction of them) overlaps as
  // soon as the price axis is zoomed out. Measures the axis pane's actual
  // rendered height so the label step always keeps at least
  // MIN_LABEL_GAP_PX between two labels, however the chart is zoomed.
  const axisPxH = axisSvgRef.current?.getBoundingClientRect().height || 620;
  const pxPerRow = (axisPxH / viewH) * ROW_H;
  const labelStep = Math.max(1, Math.ceil(MIN_LABEL_GAP_PX / Math.max(pxPerRow, 1)));

  // Converts a real PRICE back to a fractional row (not snapped to a box)
  // so a price-based line sits between boxes rather than jumping between
  // them — shared by the moving average and the smart-trend cloud below.
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
      pts.push(`${colX(meta.render_offset + n) + COL_W / 2},${PAD_T + row * ROW_H + ROW_H / 2}`);
    });
    return pts.length > 1 ? pts.join(" ") : null;
  }, [showMa, indicators, priceToRow, colX, meta.render_offset]);

  // The adaptive trend cloud: "walking" (slow, dampened in chop) and
  // "running" (fast companion) lines from backend/pnf_indicators.py's
  // smart_trend_line(), shaded between them and tinted by the current
  // overall bias. Signal glyphs (breakout arrow / exhaustion star /
  // trend pullback "P") are positioned separately below as an HTML
  // overlay, not SVG <text> — see the price-axis comment on why scaled
  // SVG text goes illegible at this app's usual zoom levels.
  const smartTrend = useMemo(() => {
    if (!showSmartTrend) return null;
    const series = indicators?.smart_trend_series;
    if (!series) return null;
    const pt = (n, row) => [colX(meta.render_offset + n) + COL_W / 2, PAD_T + row * ROW_H + ROW_H / 2];
    const walkPts = [];
    series.walking.forEach((price, n) => {
      const row = price == null ? null : priceToRow(price);
      if (row != null) walkPts.push(pt(n, row));
    });
    const runPts = [];
    series.running.forEach((price, n) => {
      const row = price == null ? null : priceToRow(price);
      if (row != null) runPts.push(pt(n, row));
    });
    // The cloud fill only makes sense where BOTH lines have a value —
    // walking's warmup (er_period) is longer than running's (a short
    // EMA), so early columns only ever get a running line.
    const both = [];
    series.walking.forEach((wPrice, n) => {
      const rPrice = series.running[n];
      if (wPrice == null || rPrice == null) return;
      const wRow = priceToRow(wPrice);
      const rRow = priceToRow(rPrice);
      if (wRow == null || rRow == null) return;
      both.push({ top: pt(n, wRow), bot: pt(n, rRow) });
    });
    const cloud = both.length > 1
      ? [...both.map((p) => p.top), ...both.slice().reverse().map((p) => p.bot)]
        .map((p) => p.join(",")).join(" ")
      : null;
    return {
      walkLine: walkPts.length > 1 ? walkPts.map((p) => p.join(",")).join(" ") : null,
      runLine: runPts.length > 1 ? runPts.map((p) => p.join(",")).join(" ") : null,
      cloud,
      bullish: indicators?.smart_trend?.bias === "bullish",
    };
  }, [showSmartTrend, indicators, priceToRow, colX, meta.render_offset]);

  // Signal glyphs (arrow/star/pullback) positioned in real screen pixels
  // over the main pane, exactly like the price-axis labels -- SVG text
  // sized in viewBox units would go sub-pixel at this app's usual
  // zoom-out levels (verified against the axis-label bug this fixed).
  const mainRect = mainSvgRef.current?.getBoundingClientRect();
  const mainPxW = mainRect?.width || 900;
  const mainPxH = mainRect?.height || 620;
  const toScreenX = useCallback((x) => ((x - vx) / viewW) * mainPxW, [vx, viewW, mainPxW]);
  const toScreenY = useCallback((y) => ((y - vy) / viewH) * mainPxH, [vy, viewH, mainPxH]);

  const smartSignals = useMemo(() => {
    if (!showSmartTrend) return [];
    const series = indicators?.smart_trend_series;
    if (!series?.signals?.length) return [];
    const byIndex = new Map(columns.map((c) => [c.index, c]));
    const SIGNAL_STYLE = {
      arrow: { bullish: { glyph: "▲", color: "#34D399" }, bearish: { glyph: "▼", color: "#F87171" } },
      star: { bullish: { glyph: "★", color: "#34D399" }, bearish: { glyph: "★", color: "#F87171" } },
      pullback: { bullish: { glyph: "P", color: "#34D399" }, bearish: { glyph: "P", color: "#F87171" } },
    };
    return series.signals.map((s, i) => {
      const col = byIndex.get(s.index);
      if (!col) return null;
      const style = SIGNAL_STYLE[s.kind]?.[s.bias];
      if (!style) return null;
      // arrow/star sit past the column's OWN extreme in the signal's
      // direction (a breakout above/exhaustion at the top, or the mirror
      // below); pullback sits on the retracing column's own extreme.
      const aboveTop = s.kind === "pullback" ? s.bias === "bearish" : s.bias === "bullish";
      const level = aboveTop ? col.top_level : col.bottom_level;
      return {
        key: `${s.kind}-${s.index}-${i}`,
        x: colX(col.index) + COL_W / 2,
        y: PAD_T + rowOf(level) * ROW_H + (aboveTop ? -ROW_H * 0.7 : ROW_H * 1.7),
        ...style,
      };
    }).filter(Boolean);
  }, [showSmartTrend, indicators, columns, colX, rowOf]);

  // Exitline overlay — each visible level (+ LTP) as a horizontal line at
  // its true fractional row (see priceToFractionalLevel), plus its label
  // for the price-axis pane below. Levels with no price (should not
  // happen — the backend always returns all 11) are simply skipped.
  // Each SESSION has its own level ladder, computed from that session's own
  // previous-day H/L/C — so a level is not one price across the whole
  // chart, it steps at every day boundary. Drawing a single flat line for
  // the active session was wrong the moment the chart showed more than one
  // day: it painted today's levels across yesterday's columns.
  //
  // Only applies intraday, and only when the backend actually returned a
  // per-session ladder; otherwise this falls back to the single-ladder
  // behaviour, which is correct for a daily/weekly/monthly chart where one
  // column IS one or more days.
  const sessionLevelSegments = useMemo(() => {
    const sessions = exitlineLevels?.sessions;
    if (!sessions?.length || !showSessionDividers) return null;

    // date -> [first column x, last column x]. A column that spans a
    // boundary belongs to the day it STARTED in, matching how the divider
    // is placed through it.
    const spanByDate = new Map();
    columns.forEach((c, i) => {
      const d = (c.start_label || "").slice(0, 10);
      if (!d) return;
      const x1 = colX(i);
      const x2 = colX(i) + COL_W;
      const cur = spanByDate.get(d);
      spanByDate.set(d, cur ? [Math.min(cur[0], x1), Math.max(cur[1], x2)] : [x1, x2]);
    });
    if (spanByDate.size < 2) return null;

    const out = [];
    for (const session of sessions) {
      const span = spanByDate.get(session.date);
      if (!span || !session.levels) continue;
      for (const k of EXITLINE_VISIBLE_LEVELS) {
        const price = session.levels[k];
        if (price == null) continue;
        const lvl = priceToFractionalLevel(price, grid.levels);
        if (lvl == null) continue;
        out.push({
          key: `${session.date}-${k}`, levelKey: k, price,
          x1: span[0], x2: span[1],
          y: PAD_T + (grid.max_level - lvl) * ROW_H,
          color: EXITLINE_LEVEL_COLORS[k], label: EXITLINE_DISPLAY_LABELS[k],
        });
      }
    }
    return out.length ? out : null;
  }, [exitlineLevels, showSessionDividers, columns, colX, grid.levels, grid.max_level]);

  const exitlineLines = useMemo(() => {
    if (!exitlineLevels?.levels) return [];
    const out = EXITLINE_VISIBLE_LEVELS.map((k) => {
      const price = exitlineLevels.levels[k];
      if (price == null) return null;
      const lvl = priceToFractionalLevel(price, grid.levels);
      if (lvl == null) return null;
      return { key: k, price, y: PAD_T + (grid.max_level - lvl) * ROW_H, color: EXITLINE_LEVEL_COLORS[k], label: EXITLINE_DISPLAY_LABELS[k] };
    }).filter(Boolean);
    if (exitlineLevels.ltp != null) {
      const lvl = priceToFractionalLevel(exitlineLevels.ltp, grid.levels);
      if (lvl != null) {
        out.push({ key: "LTP", price: exitlineLevels.ltp, y: PAD_T + (grid.max_level - lvl) * ROW_H, color: "#437EEB", label: "PX" });
      }
    }
    return out;
  }, [exitlineLevels, grid.levels, grid.max_level]);

  // Session dividers. Drawn THROUGH the column the day actually changes
  // in, not in the gap before it — a P&F column is a price move, not a
  // clock, so a column that was still printing when the session rolled
  // genuinely spans both days and the divider belongs inside it. Matches
  // how the reference platform draws it.
  const sessionDividers = useMemo(() => {
    if (!showSessionDividers) return [];
    return findSessionBoundaries(columns).map((b) => {
      const prev = columns[b.index - 1];
      const prevEndDate = prev?.end_label ? prev.end_label.slice(0, 10) : null;
      // The previous column was still open on the new day, so the boundary
      // sits inside IT — draw through its middle. Otherwise the day change
      // fell cleanly between two columns, so the gap is correct.
      const spansBoundary = prevEndDate && prevEndDate === b.date;
      return {
        ...b,
        x: spansBoundary ? colX(b.index - 1) + COL_W / 2 : colX(b.index),
      };
    });
  }, [showSessionDividers, columns, colX]);

  return (
    <div
      ref={frameRef}
      className="flex rounded-lg border border-white/10 bg-[#0B1220] overflow-hidden select-none h-full"
    >
      {/* Main pane — pans/zooms in both axes via viewBox alone; its actual
          width/height attributes never change, so this can never overflow
          its own box the way a resized SVG in a scrolling div could. Wrapped
          in a plain positioned div so the signal-glyph overlay below can sit
          on top of it at the same size without affecting the SVG's own
          layout math. */}
      <div style={{ position: "relative", width: `calc(100% - ${AXIS_W}px)`, height: "100%" }}>
      <svg
        ref={mainSvgRef}
        viewBox={`${vx} ${vy} ${viewW} ${viewH}`}
        preserveAspectRatio="none"
        style={{
          width: "100%", height: "100%",
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
              vectorEffect="non-scaling-stroke"
            />
          );
        })}

        {/* column moving average */}
        {maPoints && (
          <polyline points={maPoints} fill="none" stroke="#38BDF8" strokeWidth="1.5" opacity="0.8" vectorEffect="non-scaling-stroke" />
        )}

        {/* adaptive smart-trend cloud (walking/running lines + fill) */}
        {smartTrend && (
          <>
            {smartTrend.cloud && (
              <polygon
                points={smartTrend.cloud}
                fill={smartTrend.bullish ? "#34D399" : "#F87171"}
                fillOpacity="0.12" stroke="none"
              />
            )}
            {smartTrend.runLine && (
              <polyline points={smartTrend.runLine} fill="none" stroke="#38BDF8" strokeWidth="1" strokeDasharray="2 2" opacity="0.7" vectorEffect="non-scaling-stroke" />
            )}
            {smartTrend.walkLine && (
              <polyline points={smartTrend.walkLine} fill="none" stroke="#FBBF24" strokeWidth="1.75" opacity="0.9" vectorEffect="non-scaling-stroke" />
            )}
          </>
        )}

        {/* the X/O boxes */}
        {columns.map((col) => {
          const x = colX(col.index);
          const isX = col.direction === "X";
          const stroke = isX ? "#34D399" : "#F87171";
          return (
            <g
              key={col.index}
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
                  <g key={lvl} stroke={stroke} strokeWidth="1.5" strokeLinecap="round" vectorEffect="non-scaling-stroke">
                    <line x1={cx - r} y1={cy - r} x2={cx + r} y2={cy + r} vectorEffect="non-scaling-stroke" />
                    <line x1={cx - r} y1={cy + r} x2={cx + r} y2={cy - r} vectorEffect="non-scaling-stroke" />
                  </g>
                ) : (
                  <circle key={lvl} cx={cx} cy={cy} r={r} fill="none" stroke={stroke} strokeWidth="1.5" vectorEffect="non-scaling-stroke" />
                );
              })}
            </g>
          );
        })}

        {/* Intraday session dividers — new-day boundaries within the
            column series (see findSessionBoundaries). */}
        {sessionDividers.map((b) => (
          <line
            key={`session-${b.index}`}
            x1={b.x} y1={PAD_T} x2={b.x} y2={contentH - PAD_T}
            stroke="#64748B" strokeWidth="1" strokeDasharray="3 3" opacity="0.55"
            vectorEffect="non-scaling-stroke"
          />
        ))}

        {/* Exitline levels + LTP — full-width horizontal lines at each
            level's true fractional price row (not snapped to a box). */}
        {/* Per-session ladders when we have them: each level is drawn only
            across its own day's columns, so the ladder STEPS at the session
            divider instead of one flat line spanning days it never applied
            to. Falls back to full-width lines on a daily/weekly/monthly
            chart, where a single ladder is the correct reading. */}
        {sessionLevelSegments
          ? sessionLevelSegments.map((seg) => (
              <line
                key={`exitline-seg-${seg.key}`}
                x1={seg.x1} y1={seg.y} x2={seg.x2} y2={seg.y}
                stroke={seg.color} strokeWidth={1.25}
                opacity={0.8}
                vectorEffect="non-scaling-stroke"
              />
            ))
          : exitlineLines.filter((ln) => ln.key !== "LTP").map((ln) => (
              <line
                key={`exitline-${ln.key}`}
                x1={0} y1={ln.y} x2={plotW} y2={ln.y}
                stroke={ln.color} strokeWidth={1.25}
                strokeDasharray="5 3"
                opacity={0.75}
                vectorEffect="non-scaling-stroke"
              />
            ))}
        {/* The live price line always spans the full width — it is one
            number now, not a per-session level. */}
        {exitlineLines.filter((ln) => ln.key === "LTP").map((ln) => (
          <line
            key={`exitline-${ln.key}`}
            x1={0} y1={ln.y} x2={plotW} y2={ln.y}
            stroke={ln.color} strokeWidth={1.5}
            opacity={0.9}
            vectorEffect="non-scaling-stroke"
          />
        ))}
      </svg>

      {/* Smart-trend signal glyphs (arrow/star/pullback) — plain HTML
          positioned by real screen pixels, not SVG <text>, for the same
          reason the price-axis labels are: sized-in-viewBox-units text
          goes sub-pixel and unreadable once a column's box height is
          heavily compressed. pointerEvents:none so they never intercept
          the pan/zoom gestures on the SVG underneath. */}
      {showSmartTrend && smartSignals.length > 0 && (
        <div style={{ position: "absolute", inset: 0, overflow: "hidden", pointerEvents: "none" }}>
          {smartSignals.map((s) => {
            const left = toScreenX(s.x);
            const top = toScreenY(s.y);
            if (left < -20 || left > mainPxW + 20 || top < -20 || top > mainPxH + 20) return null;
            return (
              <div
                key={s.key}
                style={{
                  position: "absolute", left, top, transform: "translate(-50%, -50%)",
                  fontSize: 11, fontWeight: 700, lineHeight: 1, color: s.color,
                  textShadow: "0 0 3px rgba(0,0,0,0.85), 0 0 3px rgba(0,0,0,0.85)",
                }}
              >
                {s.glyph}
              </div>
            );
          })}
        </div>
      )}

      </div>

      {/* Price axis — a separate fixed-width pane so it stays put while the
          main pane pans left/right through history; its vertical window
          mirrors the main pane's (vy/viewH) so labels line up with rows,
          and dragging or scrolling on it re-scales price only — the
          TradingView "pinch the Y axis" gesture (no touch pinch on
          desktop, so drag is the equivalent here). Double-click re-enables
          autoscale (fitting to whatever's currently in view) without
          touching the X pan, same as TradingView's own axis double-click. */}
      <div
        ref={axisSvgRef}
        style={{
          width: AXIS_W, height: "100%", touchAction: "none", cursor: "ns-resize",
          flexShrink: 0, position: "relative", overflow: "hidden",
        }}
        className="font-mono-ui border-l border-white/5"
        onPointerDown={onAxisPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onPointerCancel={onPointerUp}
        onDoubleClick={() => setAutoScaleY(true)}
      >
        {/* Labels are plain absolutely-positioned HTML, not scaled SVG <text> —
            a chart spanning years of daily data at a tight box size can need
            hundreds of price rows squeezed into one pane, and SVG text sized
            in viewBox units shrinks right along with that geometry, going
            sub-pixel and unreadable exactly when there's the most history to
            label. Positioning by real screen pixels keeps every label at a
            constant, legible size no matter how compressed the row scale is. */}
        {grid.levels.map(({ level, price }) => {
          const y = PAD_T + rowOf(level) * ROW_H;
          const isLabel = (grid.max_level - level) % labelStep === 0;
          if (!isLabel) return null;
          const topPx = ((y + ROW_H / 2 - vy) / viewH) * axisPxH;
          if (topPx < -20 || topPx > axisPxH + 20) return null;
          return (
            <div
              key={level}
              style={{
                position: "absolute", left: 10, top: topPx, transform: "translateY(-50%)",
                fontSize: 10.5, lineHeight: 1, color: "#94A3B8", whiteSpace: "nowrap",
              }}
            >
              {fmtNum(price, price < 100 ? 2 : 1)}
            </div>
          );
        })}

        {/* Exitline level chips — colored, always shown regardless of
            labelStep (there are only ever 6-7 of these, never a crowding
            risk the way the dense per-box labels above are). */}
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
/* Left tool rail — TradingView-inspired. Only the tools that actually    */
/* do something are enabled; drawing/measuring tools aren't built yet     */
/* and are shown disabled rather than silently doing nothing on click.    */
/* --------------------------------------------------------------------- */

// `disabledReason` overrides the default "— coming soon" suffix for tools
// that ARE built but don't apply to the current selection (Exitline on a
// non-NSE/FUT/OPT segment, Session Dividers on a non-intraday interval) —
// those aren't unfinished, they're just inapplicable right now.
const RailButton = ({ icon: Icon, active, disabled, title, disabledReason, onClick }) => (
  <button
    type="button"
    onClick={disabled ? undefined : onClick}
    disabled={disabled}
    title={disabled ? (disabledReason || `${title} — coming soon`) : title}
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

// Exported for PnfWorkspace's single shared rail — same reasoning as the
// shared Plot controller: one rail driving whichever cell is active,
// rather than four identical rails duplicated down the page.
export const ToolRail = ({
  showTrendLines, setShowTrendLines, showMa, setShowMa,
  showSmartTrend, setShowSmartTrend, onReset,
  showExitline, onToggleExitline, exitlineDisabled, exitlineLoading,
  showSessionDividers, onToggleSessionDividers, sessionDividersDisabled,
}) => (
  <div className="flex flex-col items-center gap-1 w-10 sm:w-12 shrink-0 border-r border-white/10 bg-[#0B1220] py-2 sm:py-3">
    <RailButton icon={MousePointer2} active title="Cursor" onClick={() => {}} />
    <div className="w-6 h-px bg-white/10 my-1.5" />
    <RailButton icon={TrendingUp} active={showTrendLines} title="45° Trend Lines" onClick={() => setShowTrendLines((v) => !v)} />
    <RailButton icon={Activity} active={showMa} title="Moving Average" onClick={() => setShowMa((v) => !v)} />
    <RailButton icon={Zap} active={showSmartTrend} title="Smart Trend Cloud" onClick={() => setShowSmartTrend((v) => !v)} />
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

export const compactField = "bg-white/5 border border-white/10 rounded-md px-2.5 py-1.5 text-xs text-white outline-none focus:border-sapphire-light transition-colors [color-scheme:dark]";

// `embedded`: renders to fill its parent instead of claiming the full
// viewport (h-[100dvh] w-screen) -- what lets four instances sit in one
// CSS grid for the multi-chart workspace below, each keeping its OWN
// independent state (symbol, interval, box size, overlays), since this
// component already owns all of that internally and needed no refactor
// to be reused this way.
//
// `controlled`: hides this cell's own plot toolbar (segment/search/
// instrument/expiry/strike/interval/box/Plot/Live) AND its own left tool
// rail -- what the multi-chart workspace uses when ONE shared controller
// and ONE shared rail drive all visible cells, rather than each cell
// duplicating both. The imperative handle below (plotInstrument/setLive/
// setOverlay/resetView) is how those shared controls actually drive this
// specific cell once it's the one the user clicked into.
// `onPlotted`/`onLiveChange`/`onOverlayChange` mirror this cell's own
// plotted-instrument, live, and overlay-toggle state back up, so the
// shared Live button and shared rail reflect whichever cell is active.
const PnfChart = forwardRef(({ embedded = false, controlled = false, onPlotted, onLiveChange, onOverlayChange } = {}, ref) => {
  const [segment, setSegment] = useState("NSE");
  const [symbols, setSymbols] = useState([]);
  const [query, setQuery] = useState("");
  const [symbol, setSymbol] = useState("");
  const [expiries, setExpiries] = useState([]);
  const [expiry, setExpiry] = useState("");
  const [strikes, setStrikes] = useState([]);
  const [strike, setStrike] = useState("");
  const [optionType, setOptionType] = useState("CE");
  // RS/Straddle/Strangle -- a fully separate instrument shape (two legs,
  // not one), so it's kept out of the plain segment/symbol/expiry/strike
  // state above rather than overloading those fields with a shape they
  // don't fit. Configured via PnfComboModal, applied via Plot like any
  // other segment.
  const [comboOpen, setComboOpen] = useState(false);
  const [comboParams, setComboParams] = useState(null);

  const [interval, setIntervalKey] = useState("daily");
  const [boxPct, setBoxPct] = useState(0.25);
  const [showTrendLines, setShowTrendLines] = useState(true);
  const [showMa, setShowMa] = useState(true);
  const [showSmartTrend, setShowSmartTrend] = useState(true);
  const [live, setLive] = useState(false);

  // Exitline overlay + intraday session dividers — see exitlineOverlay.js.
  const [showExitline, setShowExitline] = useState(false);
  const [exitlineData, setExitlineData] = useState(null);
  const [exitlineLoading, setExitlineLoading] = useState(false);
  const [showSessionDividers, setShowSessionDividers] = useState(false);
  // The instrument a successful Plot actually charted -- Exitline levels
  // are fetched for THIS, not for whatever the selectors currently say,
  // so changing the segment/symbol dropdowns without hitting Plot again
  // can never show levels for an instrument that isn't on screen.
  const [plottedInstrument, setPlottedInstrument] = useState(null);

  const [data, setData] = useState(null);
  const [plotCount, setPlotCount] = useState(0);
  const [loading, setLoading] = useState(false);
  const [hoverCol, setHoverCol] = useState(null);
  // The Commentary sidebar is desktop-only (no room for a fixed 240px
  // column on a phone) -- this drives its mobile stand-in, a bottom sheet
  // opened from a small trigger in the stat readout row.
  const [showCommentarySheet, setShowCommentarySheet] = useState(false);
  const gridRef = useRef(null);

  // Every interval can go live now (see LIVE_REFRESH_MS) -- except a
  // Yahoo-backed chart, which never can (cached daily history, no live
  // quote). That's US and COMMODITY at daily/weekly/monthly only; both
  // segments' intraday runs through a genuinely refreshing source now
  // (Alpaca / a local MT5 terminal respectively).
  const canGoLive = (segment === "US" || segment === "COMMODITY")
    ? !DAILY_PLUS_INTERVALS.includes(interval)
    : true;

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

  // Every segment now offers every interval, so nothing needs resetting
  // when the segment changes.

  // `silent` skips the loading spinner/camera reset — used by the live
  // auto-refresh poll below so a background update doesn't yank focus
  // away from wherever the user has panned to, or flicker the Plot button.
  // `override` lets a caller plot an instrument that hasn't been set into
  // form state yet (or ever will be) -- what the auto-plot effect below
  // uses, rather than juggling setSegment/setSymbol/etc and hoping this
  // callback's closure has caught up before firing. Falls back to current
  // form state field by field, so every existing manual-plot call site is
  // unchanged.
  const fetchChart = useCallback(async ({ silent = false, override = null } = {}) => {
    const p = {
      symbol: override?.symbol ?? symbol, segment: override?.segment ?? segment,
      interval: override?.interval ?? interval, boxPct: override?.boxPct ?? boxPct,
      expiry: override?.expiry ?? expiry, strike: override?.strike ?? strike,
      optionType: override?.optionType ?? optionType,
    };
    if (p.segment === "COMBO" ? !comboParams : !p.symbol) return;
    if (!silent) { setLoading(true); }
    try {
      let d;
      if (p.segment === "COMBO") {
        const cp = comboParams;
        ({ data: d } = await axios.get(`${API}/pnf/chart/combo`, {
          params: {
            op: cp.op, interval: p.interval, box_pct: p.boxPct,
            leg_a_segment: cp.legA.segment, leg_a_symbol: cp.legA.symbol,
            ...(cp.legA.expiry ? { leg_a_expiry: cp.legA.expiry } : {}),
            ...(cp.legA.strike ? { leg_a_strike: cp.legA.strike, leg_a_option_type: cp.legA.optionType } : {}),
            leg_b_segment: cp.legB.segment, leg_b_symbol: cp.legB.symbol,
            ...(cp.legB.expiry ? { leg_b_expiry: cp.legB.expiry } : {}),
            ...(cp.legB.strike ? { leg_b_strike: cp.legB.strike, leg_b_option_type: cp.legB.optionType } : {}),
          },
          ...authHeaders(),
        }));
      } else if (p.segment === "CRYPTO") {
        const bars = await fetchCryptoBars(p.symbol, p.interval);
        ({ data: d } = await axios.post(`${API}/pnf/chart/crypto`, { symbol: p.symbol, bars }, {
          params: { interval: p.interval, box_pct: p.boxPct },
          ...authHeaders(),
        }));
      } else {
        ({ data: d } = await axios.get(`${API}/pnf/chart`, {
          params: {
            symbol: p.symbol, segment: p.segment, interval: p.interval, box_pct: p.boxPct,
            ...(p.segment === "FUT" || p.segment === "OPT" ? { expiry: p.expiry } : {}),
            ...(p.segment === "OPT" ? { strike: p.strike, option_type: p.optionType } : {}),
          },
          ...authHeaders(),
        }));
      }
      setData(d);
      if (!silent) {
        setPlotCount((n) => n + 1);
        setPlottedInstrument({ segment: p.segment, symbol: p.symbol, expiry: p.expiry, strike: p.strike, optionType: p.optionType });
        onPlotted?.({ ...p });
      }
    } catch (e) {
      if (!silent) { toast.error(e?.response?.data?.detail || "Could not plot that chart."); setData(null); }
    } finally {
      if (!silent) setLoading(false);
    }
  }, [symbol, segment, interval, boxPct, expiry, strike, optionType, onPlotted, comboParams]);

  // The shared workspace controller's own imperative handle onto this cell
  // (only meaningful when `controlled`, but harmless to expose always):
  // `plotInstrument` sets the visible form state to match AND plots it via
  // `fetchChart`'s override (rather than relying on state having landed
  // before fetchChart's closure reads it), `setLive` drives this cell's
  // own live-refresh toggle from the controller's single Live button.
  // `setOverlay`/`resetView` are the shared ToolRail's onto this cell's
  // own trend-line/MA/smart-trend/exitline/session-divider toggles and
  // camera reset -- same pattern as plotInstrument/setLive above.
  useImperativeHandle(ref, () => ({
    plotInstrument: (instrument) => {
      setSegment(instrument.segment);
      setSymbol(instrument.symbol);
      setExpiry(instrument.expiry || "");
      setStrike(instrument.strike ?? "");
      setOptionType(instrument.optionType || "CE");
      if (instrument.interval) setIntervalKey(instrument.interval);
      if (instrument.boxPct != null) setBoxPct(instrument.boxPct);
      fetchChart({ override: instrument });
    },
    setLive: (v) => setLive(v),
    setOverlay: (key, value) => {
      if (key === "trendLines") setShowTrendLines(value);
      else if (key === "ma") setShowMa(value);
      else if (key === "smartTrend") setShowSmartTrend(value);
      else if (key === "exitline") setShowExitline(value);
      else if (key === "sessionDividers") setShowSessionDividers(value);
    },
    resetView: () => gridRef.current?.resetView(),
  }), [fetchChart]);

  // Mirrors `live` up to the shared controller so its Live button reflects
  // this cell's real state (including the auto-off effect below correcting
  // an invalid toggle, e.g. switching a live cell to a Yahoo-only segment).
  useEffect(() => {
    onLiveChange?.(live);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [live]);

  // Mirrors this cell's overlay toggles (+ the segment/interval-derived
  // disabled states) up to the shared ToolRail, so it reflects whichever
  // cell is currently active instead of a rail-wide guess.
  useEffect(() => {
    onOverlayChange?.({
      trendLines: showTrendLines, ma: showMa, smartTrend: showSmartTrend,
      exitline: showExitline, exitlineDisabled: !EXITLINE_SEGMENTS.includes(segment), exitlineLoading,
      sessionDividers: showSessionDividers, sessionDividersDisabled: !isIntradayInterval(interval),
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [showTrendLines, showMa, showSmartTrend, showExitline, showSessionDividers, segment, interval, exitlineLoading]);

  // Exitline fetch — keyed to whatever was actually plotted, not the live
  // selector state (see plottedInstrument above). Re-fetches whenever the
  // toggle turns on or a fresh Plot lands while it's already on; does
  // nothing for a segment Exitline has no coverage for.
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
    if (segment === "COMBO") {
      if (!comboParams) { setComboOpen(true); return; }
      fetchChart();
      return;
    }
    if (!symbol) { toast.error("Pick an instrument first."); return; }
    if ((segment === "FUT" || segment === "OPT") && !expiry) { toast.error("Pick an expiry."); return; }
    if (segment === "OPT" && !strike) { toast.error("Pick a strike."); return; }
    fetchChart();
  };

  // Live updates: NSE/FUT/OPT (India) charts get a real WebSocket tick
  // stream (backend/pnf_routes.py's WS /pnf/chart/stream, backed by
  // definedge_stream.py/dhan_stream.py) instead of a poll -- the socket
  // pushes a freshly recomputed chart every time the underlying's price
  // actually moves, rather than on a fixed timer. Every other segment
  // (US/COMMODITY/Yahoo-backed charts, crypto) has no live-stream
  // integration yet and keeps the original poll unconditionally.
  //
  // The poll is NOT removed for India segments either -- it's the
  // fallback for as long as the socket isn't open (starting up,
  // reconnecting, or this pass's route rejected the segment/instrument
  // for any reason), so a chart never goes stale just because a socket
  // hiccuped. `wsOpenRef` tracks this without a re-render on every
  // connect/disconnect.
  const wsOpenRef = useRef(false);
  useEffect(() => {
    if (!live || !data || !canGoLive) return undefined;
    const ms = LIVE_REFRESH_MS[interval] || 30000;
    const id = setInterval(() => {
      if (!wsOpenRef.current) fetchChart({ silent: true });
    }, ms);
    return () => clearInterval(id);
  }, [live, data, canGoLive, interval, fetchChart]);

  useEffect(() => {
    wsOpenRef.current = false;
    if (!live || !data || !canGoLive) return undefined;
    if (!["NSE", "FUT", "OPT"].includes(segment) || !symbol) return undefined;

    const params = new URLSearchParams({
      symbol, segment, interval, token: localStorage.getItem(TRADER_TOKEN_KEY) || "",
    });
    if (boxPct != null) params.set("box_pct", boxPct);
    if (segment === "FUT" || segment === "OPT") params.set("expiry", expiry || "");
    if (segment === "OPT") { params.set("strike", strike || ""); params.set("option_type", optionType || ""); }

    const wsUrl = `${API.replace(/^http/, "ws")}/pnf/chart/stream?${params.toString()}`;
    const ws = new WebSocket(wsUrl);
    ws.onopen = () => { wsOpenRef.current = true; };
    ws.onmessage = (event) => {
      try {
        const msg = JSON.parse(event.data);
        if (msg.type === "full" && msg.chart) setData(msg.chart);
      } catch {
        // malformed push -- the poll fallback (still running whenever
        // wsOpenRef is false) will correct the display on its own next tick
      }
    };
    ws.onclose = () => { wsOpenRef.current = false; };
    ws.onerror = () => { wsOpenRef.current = false; };
    return () => { wsOpenRef.current = false; ws.close(); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [live, data === null, canGoLive, segment, symbol, interval, boxPct, expiry, strike, optionType]);

  // Auto-off if the user switches to a US index while Live was on.
  useEffect(() => {
    if (!canGoLive && live) setLive(false);
  }, [canGoLive, live]);

  const bias = data?.summary?.bias || "neutral";
  const BiasIcon = BIAS_STYLE[bias].Icon;

  return (
    <div className={`${embedded ? "h-full w-full" : "h-[100dvh] w-screen"} overflow-hidden bg-[#060B14] text-white flex flex-col`}>
      {/* Compact toolbar — everything needed to plot a chart in one row,
          wraps on narrow screens instead of stacking into a tall block.
          Skipped entirely when `controlled` -- the workspace's single
          shared controller replaces this whole row. */}
      {!controlled && (
      <div className="shrink-0 border-b border-white/10 bg-[#0B1220] px-3 sm:px-4 py-2.5">
        <div className="flex flex-wrap items-center gap-2">
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

        </div>

      </div>
      )}

      <PnfComboModal
        open={comboOpen}
        onClose={() => setComboOpen(false)}
        onApply={(params) => setComboParams(params)}
      />

      {/* Compact instrument/stat readout — just identity + price + bias;
          everything else here (bull/bear standing, Cont./Rev., cols/bars/
          date-range) either duplicated the Commentary panel or was pure
          clutter, so it's gone rather than hidden. */}
      {data && (
        <div className="shrink-0 flex flex-wrap items-center gap-x-4 gap-y-1 px-3 sm:px-4 py-2 border-b border-white/5 bg-[#080D16] text-[11px] font-mono-ui text-slate-400">
          <span className="text-white font-semibold text-xs">{data.instrument.tradingsymbol}</span>
          <span>{data.params.box_pct}% × {data.params.reversal} · close-only</span>
          <span>CMP <span className="text-white">{fmtNum(data.meta.last_price)}</span></span>
          <span className={`inline-flex items-center gap-1 ${BIAS_STYLE[bias].text}`}>
            <BiasIcon size={12} />{bias[0].toUpperCase() + bias.slice(1)}
          </span>
          {live && (
            <span className="inline-flex items-center gap-1.5 text-emerald-400">
              <span className="h-1.5 w-1.5 rounded-full bg-emerald-400 animate-pulse" /> Live
            </span>
          )}
          {/* Commentary lives in the right-hand sidebar on md+ (see
              CommentaryPanel); below that this is the only way to reach it. */}
          <button
            type="button"
            onClick={() => setShowCommentarySheet(true)}
            className="md:hidden inline-flex items-center gap-1 text-sapphire-light ml-auto"
            data-testid="pnf-commentary-sheet-open"
          >
            <Info size={12} /> Commentary
          </button>
        </div>
      )}

      {!data && !loading && (
        <div className="flex-1 min-h-0 flex items-center justify-center p-4 sm:p-6">
          <EmptyState reason="Pick an instrument and hit Plot to build its structure chart." />
        </div>
      )}

      {data && (
        <div className="flex-1 flex min-h-0">
          {/* Skipped when `controlled` -- the workspace's single shared
              rail (see the exported ToolRail) drives whichever cell is
              active instead of one rail per cell. */}
          {!controlled && (
          <ToolRail
            showTrendLines={showTrendLines} setShowTrendLines={setShowTrendLines}
            showMa={showMa} setShowMa={setShowMa}
            showSmartTrend={showSmartTrend} setShowSmartTrend={setShowSmartTrend}
            onReset={() => gridRef.current?.resetView()}
            showExitline={showExitline}
            onToggleExitline={() => setShowExitline((v) => !v)}
            exitlineDisabled={!EXITLINE_SEGMENTS.includes(segment)}
            exitlineLoading={exitlineLoading}
            showSessionDividers={showSessionDividers}
            onToggleSessionDividers={() => setShowSessionDividers((v) => !v)}
            sessionDividersDisabled={!isIntradayInterval(interval)}
          />
          )}

          <div className="flex-1 min-w-0 min-h-0 flex flex-col p-3 sm:p-4">
            <div className="flex-1 min-h-0">
              <PnfGrid
                ref={gridRef}
                data={data}
                resetKey={plotCount}
                showTrendLines={showTrendLines}
                showMa={showMa}
                showSmartTrend={showSmartTrend}
                onHoverColumn={setHoverCol}
                exitlineLevels={showExitline ? exitlineData : null}
                showSessionDividers={showSessionDividers && isIntradayInterval(interval)}
              />
            </div>
          </div>

          <CommentaryPanel data={data} hoverCol={hoverCol} />

          {/* Mobile stand-in for the sidebar above — same component, a
              bottom-sheet wrapper instead (see CommentaryPanel's `variant`). */}
          {showCommentarySheet && (
            <div
              className="md:hidden fixed inset-0 z-50 flex items-end justify-center"
              onClick={() => setShowCommentarySheet(false)}
            >
              <div className="absolute inset-0 bg-black/60" aria-hidden="true" />
              <div className="relative w-full" onClick={(e) => e.stopPropagation()}>
                <CommentaryPanel
                  data={data} hoverCol={hoverCol} variant="sheet"
                  onClose={() => setShowCommentarySheet(false)}
                />
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
});

PnfChart.displayName = "PnfChart";

export default PnfChart;
