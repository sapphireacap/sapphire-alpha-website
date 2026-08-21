import { useState, useEffect, useRef, useMemo } from "react";
import axios from "axios";
import { toast } from "sonner";
import { Loader2, RefreshCw, TrendingUp, TrendingDown, Minus, Search } from "lucide-react";
import { createChart, CandlestickSeries, LineSeries, LineType, ColorType } from "lightweight-charts";
import SessionDividers, { useSessionDividers } from "./ChartSessionDividers";
import { useLivePrice, useLiveCandle } from "../../lib/useLivePrice";
import { LoadingParticles, EmptyState } from "./QuantLab";
import { isNseSessionLive } from "../AlphaTerminal";
import { T, F_UI, F_MONO, GLOW_SAPPHIRE, microLabel, mono, ui } from "./quantDesignTokens";

const POLL_MS = 30000; // keep the LTP marker live while results are showing

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;

const SEGMENTS = [
  { key: "NSE", label: "NSE (Cash)" },
  { key: "FUT", label: "Futures" },
  { key: "OPT", label: "Options" },
];

const fmtDate = (iso) => {
  if (!iso) return "—";
  const [y, m, d] = iso.split("-");
  return `${d}/${m}/${y}`;
};

const fmtDateLong = (iso) => {
  if (!iso) return "—";
  const [y, m, d] = iso.split("-");
  const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  return `${d} ${MONTHS[Number(m) - 1]} ${y.slice(2)}`;
};

const fmtNum = (v) => (v == null ? "—" : Number(v).toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 }));

// lightweight-charts reads UTC getters off the Date it builds from a time
// value (getUTCHours etc.) regardless of the browser's own timezone, so an
// IST-correct epoch (which is what the backend sends) would otherwise
// render as raw UTC on the axis/crosshair — 5.5h behind. Shift the display
// copy by the IST offset so the UTC getters read back IST wall-clock digits;
// the underlying series/range data (used for session-window math) is untouched.
const IST_OFFSET_MS = 5.5 * 60 * 60 * 1000;
const formatIstHm = (time) => {
  const d = new Date(time * 1000 + IST_OFFSET_MS);
  return `${String(d.getUTCHours()).padStart(2, "0")}:${String(d.getUTCMinutes()).padStart(2, "0")}`;
};

// Backend still computes all 11 levels (H1/H2/L1/L2 feed the mid-range
// commentary text used elsewhere) but only these seven are ever shown
// here — H1/H2/L1/L2 stay dropped from display, per original request; L5
// was re-added (2026-08-10) to match the reference chart, which shows the
// full H5-H4-H3-Pivot-L3-L4-L5 ladder.
const VISIBLE_LEVELS = ["H5", "H4", "H3", "Pivot", "L3", "L4", "L5"];

// The CHART draws Pivot/PZ and H4/H3 excluded -- Pivot dropped 2026-08-12
// ("completely remove the pz name and line from the chart"), H4/H3 (S4/S3)
// dropped 2026-08-20 by explicit request, keeping only the outer S5 and the
// full V3/V4/V5 support ladder on the candles themselves. Scoped to the
// chart deliberately -- VISIBLE_LEVELS still drives the live levels panel
// below it, which continues to list every level including S4/S3/PZ.
const CHART_LEVELS = ["H5", "L3", "L4", "L5"];

// Matches the reference: all H-levels (S-series, resistance overhead) red,
// Pivot cyan, all L-levels (V-series, support below) green.
const LEVEL_COLORS = {
  H5: T.bearish, H4: T.bearish, H3: T.bearish,
  Pivot: "#22D3EE",
  L3: T.bullish, L4: T.bullish, L5: T.bullish,
};

// "Sapphire Levels" branding — internal keys (H5/H4/H3/Pivot/L3/L4/L5/LTP)
// stay as-is everywhere else (backend field names, color/row-style
// lookups); only the DISPLAYED label changes, so a generic H/L/Pivot
// naming convention isn't shown to users.
const DISPLAY_LABELS = { H5: "S5", H4: "S4", H3: "S3", Pivot: "P", L3: "V3", L4: "V4", L5: "V5" };
const FULL_NAMES = {
  H5: "Sentinel 5", H4: "Sentinel 4", H3: "Sentinel 3",
  Pivot: "Pivot Zone",
  L3: "Vault 3", L4: "Vault 4", L5: "Vault 5",
};

// Backend bias values are Long/Short/Neutral (see exitline.py's
// classify_and_suggest) -- displayed as Bullish/Bearish/Neutral to match
// the rest of the terminal's vocabulary. Internal value is untouched.
const BIAS_DISPLAY = { Long: "Bullish", Short: "Bearish", Neutral: "Neutral" };
const BIAS_TONE = {
  Bullish: { color: T.bullish, Icon: TrendingUp },
  Bearish: { color: T.bearish, Icon: TrendingDown },
  Neutral: { color: T.neutral, Icon: Minus },
};

// How many bars of the PREVIOUS session to keep on screen at open, so the
// dotted session divider at today's open lands inside the pane instead of
// off its left edge. Sized from a real measurement, not taste: at the
// default zoom a session spans ~1728px against an ~1125px pane, and the
// chart's own right-edge clamp (the visible range asks for `now`, which is
// past the last bar) pushed the session start to about -422px. 12 bars of
// 5m data is only ~72px, nowhere near enough; 90 bars clears it with room
// to spare. Same value on every market so the four Exitline views open
// identically.
const PREV_SESSION_TAIL_BARS = 90;

const INTERVALS = [
  { key: 1, label: "1m" },
  { key: 5, label: "5m" },
  { key: 15, label: "15m" },
  { key: 30, label: "30m" },
  { key: 60, label: "1h" },
];

const fieldStyle = {
  background: T.cardElevated, border: `1px solid ${T.borderPrimary}`, borderRadius: 8,
  padding: "8px 10px", fontFamily: F_UI, fontSize: 13, color: T.textPrimary, colorScheme: "dark",
};

// TradingView's own open-source charting engine (not their embeddable
// tradingview.com widget — that only supports custom price-line overlays
// via the paid Charting Library). Renders our real Definedge candles with
// native price lines for the levels, fully under our control.
//
// Each session in `sessions` has its OWN level ladder (computed from THAT
// session's own previous-day H/L/C — never the same day to day), so a
// flat createPriceLine() spanning the whole 30-day chart would be wrong
// the moment a level actually changes between sessions. Each level is
// instead its own LineSeries with one point per candle (value = that
// candle's OWN session's level) and lineType: WithSteps — consecutive
// bars within a session share the same value (a flat segment); the jump
// at a session boundary renders as a clean vertical step instead of a
// diagonal interpolation, matching a real multi-session reference chart.
const buildLevelSeriesData = (chart, sessionsByDate, key) => {
  const out = [];
  for (const b of chart) {
    if (b.time == null) continue;
    const session = sessionsByDate[b.date];
    const value = session?.levels?.[key];
    if (value == null) continue;
    out.push({ time: b.time, value });
  }
  return out;
};

// No `ltp` prop: the chart no longer draws a live-price ("PX") line at
// all (2026-08-12, by request), so it has nothing to do with the live
// price. The levels panel below still takes `ltp` and still shows it.
const TVChart = ({ chart, sessions, interval, onIntervalChange, fetchGen, market, symbol }) => {
  const containerRef = useRef(null);
  const chartRef = useRef(null);
  const seriesRef = useRef(null);
  const levelSeriesRef = useRef({});
  const fitKeyRef = useRef(null); // re-fit the view on symbol/interval change, but not on a live-poll refresh (so a manual zoom/scroll sticks)

  useEffect(() => {
    if (!containerRef.current) return undefined;
    const tvChart = createChart(containerRef.current, {
      layout: { background: { type: ColorType.Solid, color: "transparent" }, textColor: T.textSecondary },
      grid: { vertLines: { visible: false }, horzLines: { visible: false } },
      localization: { timeFormatter: formatIstHm },
      timeScale: {
        timeVisible: true, secondsVisible: false, borderColor: T.borderPrimary,
        tickMarkFormatter: formatIstHm,
      },
      rightPriceScale: { borderColor: T.borderPrimary },
      handleScale: {
        mouseWheel: true, pinch: true,
        axisPressedMouseMove: { time: true, price: true },
      },
      // mouseWheel: false here (not true) -- handleScale.mouseWheel above
      // already claims the wheel for zoom, same as real TradingView.com
      // (scroll = zoom, drag = pan). Having both true fought over the same
      // wheel event, panning AND zooming on every tick, which read as
      // "zoom doesn't work" even though it was technically firing.
      handleScroll: { mouseWheel: false, pressedMouseMove: true, horzTouchDrag: true, vertTouchDrag: true },
      autoSize: true,
    });
    const series = tvChart.addSeries(CandlestickSeries, {
      upColor: T.bullish, downColor: T.bearish, borderVisible: false,
      wickUpColor: T.bullish, wickDownColor: T.bearish,
      // Both off so the chart carries NO live-price marker at all: the
      // explicit "PX" price line these originally deduplicated against was
      // removed 2026-08-12 by request, and re-enabling either of these
      // would just put an equivalent line/label straight back. The live
      // price is still shown in the live levels panel below.
      priceLineVisible: false,
      lastValueVisible: false,
    });
    chartRef.current = tvChart;
    seriesRef.current = series;

    // Belt-and-suspenders on top of data-lenis-prevent below: Lenis's own
    // wheel listener sits on window/document, an ancestor of this
    // container -- stopping propagation here (bubble phase, so it runs
    // AFTER the chart library's own listener on its inner canvas has
    // already handled the zoom) guarantees Lenis never sees the event at
    // all, regardless of whether its own data-attribute opt-out is being
    // respected correctly in whatever Lenis version is actually loaded.
    // passive:true is fine -- stopPropagation doesn't need preventDefault
    // rights, and the chart library's own listener still calls
    // preventDefault() itself, non-passively, on its own element.
    const container = containerRef.current;
    const stopWheelPropagation = (e) => e.stopPropagation();
    container.addEventListener("wheel", stopWheelPropagation, { passive: true });

    return () => {
      container.removeEventListener("wheel", stopWheelPropagation);
      Object.values(levelSeriesRef.current).forEach((s) => { try { tvChart.removeSeries(s); } catch { /* already gone with the chart */ } });
      levelSeriesRef.current = {};
      tvChart.remove();
      chartRef.current = null;
      seriesRef.current = null;
    };
  }, []);

  useEffect(() => {
    const series = seriesRef.current;
    const tvChart = chartRef.current;
    if (!series || !tvChart || !chart || chart.length === 0) return;

    const cleanChart = chart.filter((b) => b.time != null);
    series.setData(cleanChart.map((b) => ({
      time: b.time, open: b.open, high: b.high, low: b.low, close: b.close,
    })));

    // No autoscaleInfoProvider on the CANDLE series on purpose: the candles
    // alone define the price range, so they always fill the pane the way
    // tradingview.com's do. The level series opt OUT of autoscale instead
    // (see their own comment below) -- an older version did the reverse,
    // forcing the range to span every session's levels, which is why the
    // price axis never squeezed no matter how far the time axis was zoomed.

    // Each level is its own stepped LineSeries spanning the whole window --
    // its value changes at every session boundary (see buildLevelSeriesData)
    // instead of one flat line that would only ever be correct for a single
    // session.
    const sessionsByDate = Object.fromEntries((sessions || []).map((s) => [s.date, s]));
    CHART_LEVELS.forEach((k) => {
      let lineSeries = levelSeriesRef.current[k];
      if (!lineSeries) {
        lineSeries = tvChart.addSeries(LineSeries, {
          color: LEVEL_COLORS[k] || T.textMuted, lineWidth: 1, lineType: LineType.WithSteps,
          // No `title` (2026-08-12, by request) -- the price-axis tag now
          // shows only the value, not the S5/S4/V3/... name. The levels
          // panel below still names every level, and the lines stay
          // colour-coded (red above / green below), so nothing is lost.
          lastValueVisible: true, priceLineVisible: false, crosshairMarkerVisible: false,
          // Levels are DRAWN but excluded from the price autoscale (that's
          // what returning null does) -- the candles alone decide the price
          // range, exactly like real tradingview.com, where a horizontal
          // level drawing never stretches the scale. Letting them
          // participate is what kept zoom feeling broken: the ladder spans
          // ~100 points (S5 down to V5, wider still across sessions) while
          // an intraday session's candles span ~25, so autoscale fitted the
          // ladder and the candles stayed a flat squashed band no matter
          // how far the time axis was zoomed. Trade-off, and the same one
          // TradingView makes: levels far from price now sit off-screen
          // until you zoom the price axis out (drag it) or scroll out.
          autoscaleInfoProvider: () => null,
        });
        levelSeriesRef.current[k] = lineSeries;
      }
      lineSeries.setData(buildLevelSeriesData(cleanChart, sessionsByDate, k));
    });

    // Only reset the view (time+price scale) when this data actually
    // belongs to a real user-initiated fetch (submit / interval change) —
    // a background live-poll refresh must never yank a user's manual
    // scroll/zoom back to "fit all". fetchGen (tagged onto `result` by the
    // parent, only on a real fetch) is the only reliable signal for that:
    // chart[0]'s own timestamp can't be used, since every interval's first
    // bucket aligns to the same session-open time regardless of interval
    // width, so it can't tell "new interval's data" apart from "old
    // interval's data" by timestamp alone.
    if (fetchGen != null && fitKeyRef.current !== fetchGen) {
      fitKeyRef.current = fetchGen;
      series.priceScale().applyOptions({ autoScale: true });
      // Default view is just the ACTIVE (most recent) session, same as
      // before this was a 30-day series -- fitContent()/showing the whole
      // window would squash every session into unreadably thin candles.
      // The other 29 sessions are still real data, just scrolled out of
      // view to the left (handleScroll is on) rather than absent.
      const activeDate = sessions?.[sessions.length - 1]?.date;
      const activeBars = activeDate ? cleanChart.filter((b) => b.date === activeDate) : cleanChart;
      const sessionStart = activeBars[0]?.time;
      const lastBar = activeBars[activeBars.length - 1]?.time;
      if (sessionStart != null && lastBar != null) {
        const nowTs = Math.floor(Date.now() / 1000);
        // Keep a short tail of the previous session on screen so the dotted
        // session divider at today's open sits inside the pane instead of
        // exactly on the left edge, where it reads as no line at all. Real
        // prior bars, not a subtracted duration, so no empty overnight gap.
        const startIdx = cleanChart.findIndex((b) => b.time === sessionStart);
        const from = startIdx > 0 ? cleanChart[Math.max(0, startIdx - PREV_SESSION_TAIL_BARS)].time : sessionStart;
        tvChart.timeScale().setVisibleRange({ from, to: Math.max(lastBar + interval * 60, nowTs) });
      } else {
        tvChart.timeScale().fitContent();
      }
    }
  }, [chart, sessions, interval, fetchGen]);

  // Computed HERE, inside the chart component, where chartRef is
  // guaranteed populated — see ChartSessionDividers for why a child
  // component reading this ref could never work.
  const dividerXs = useSessionDividers(chartRef, containerRef, chart, [sessions, interval, fetchGen]);

  // Live price folded into the forming candle only — the heavy series
  // is fetched once and never refetched to move it. See lib/useLivePrice.
  const live = useLivePrice(market, symbol, { enabled: !!symbol });
  useLiveCandle(seriesRef, chart, live?.price, interval);

  const isEmpty = !chart || chart.length === 0;

  return (
    <div className="rounded-2xl p-4 md:p-6" style={{ background: T.card, border: `1px solid ${T.borderPrimary}` }} data-testid="exitline-chart">
      <div className="flex flex-wrap items-center justify-end gap-3 mb-3">
        <div className="flex items-center gap-1 rounded-md p-0.5" style={{ border: `1px solid ${T.borderPrimary}` }} data-testid="exitline-interval-selector">
          {INTERVALS.map((iv) => (
            <button
              key={iv.key}
              type="button"
              onClick={() => onIntervalChange(iv.key)}
              data-testid={`exitline-interval-${iv.key}`}
              className="px-2.5 py-1 rounded transition-colors"
              style={{ ...mono(11, 500, interval === iv.key ? T.sapphireBright : T.textMuted), background: interval === iv.key ? "rgba(22,119,255,0.14)" : "transparent" }}
            >
              {iv.label}
            </button>
          ))}
        </div>
      </div>
      <div className="relative h-96">
        {isEmpty && (
          <div className="absolute inset-0 flex items-center justify-center z-10" data-testid="exitline-chart-empty">
            <p style={ui(12, 400, T.textMuted)}>No intraday bars yet for this session.</p>
          </div>
        )}
        {/* App-wide Lenis smooth-scroll (SmoothScroll.jsx) reads wheel deltas on its own listener and animates the page regardless of preventDefault() elsewhere — data-lenis-prevent-wheel/data-lenis-prevent are both real Lenis opt-out attributes (confirmed against Lenis's own source, 2026-08-10); using the general one here. */}
        <div ref={containerRef} className="h-96" style={{ touchAction: "none" }} data-lenis-prevent="true" data-testid="exitline-tv-chart" />
        <SessionDividers xs={dividerXs} />
      </div>
    </div>
  );
};

/* --------------------------------------------------------------------- */
/* Instrument header — symbol identity, live price, session status        */
/* --------------------------------------------------------------------- */
const InstrumentHeader = ({ result, live, lastFetchedAt }) => {
  const sessionLive = isNseSessionLive();
  const changeNegative = live?.change < 0;
  const displayPrice = live?.price ?? result.ltp;
  const [, force] = useState(0);
  // Re-render once a minute so "Last updated" keeps counting up in words
  // without a per-second timer (this is a coarse label, not a stopwatch).
  useEffect(() => {
    const id = setInterval(() => force((n) => n + 1), 60000);
    return () => clearInterval(id);
  }, []);
  const updatedLabel = lastFetchedAt
    ? new Date(lastFetchedAt).toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit", hour12: true, timeZone: "Asia/Kolkata" }).toUpperCase() + " IST"
    : "—";

  return (
    <div
      className="flex flex-wrap items-center justify-between gap-4 rounded-2xl px-5 py-4 mb-4"
      style={{ background: T.bg2, border: `1px solid ${T.borderPrimary}` }}
      data-testid="exitline-instrument-header"
    >
      <div>
        <p style={{ ...ui(20, 600, T.textPrimary), letterSpacing: "-0.01em" }}>{result.tradingsymbol}</p>
        <p className="mt-0.5" style={ui(12, 400, T.textSecondary)}>
          {result.symbol} &middot; {SEGMENTS.find((s) => s.key === result.segment)?.label || result.segment}
          {result.expiry && <> &middot; {fmtDate(result.expiry)}</>}
        </p>
      </div>
      {displayPrice != null && (
        <div>
          <p style={microLabel}>Last Price</p>
          <p style={mono(24, 600, T.textPrimary)}>&#8377;{fmtNum(displayPrice)}</p>
          {live?.change != null && (
            <p style={mono(12, 500, changeNegative ? T.bearish : T.bullish)}>
              {changeNegative ? "" : "+"}{fmtNum(live.change)} ({live.changePct != null ? `${changeNegative ? "" : "+"}${live.changePct.toFixed(2)}%` : "—"})
            </p>
          )}
        </div>
      )}
      <div>
        <p style={microLabel}>Market Status</p>
        <p className="mt-0.5 flex items-center gap-1.5" style={ui(14, 600, sessionLive ? T.bullish : T.textMuted)}>
          {sessionLive ? "Live" : "Closed"}
          <span className="h-1.5 w-1.5 rounded-full" style={{ background: sessionLive ? T.bullish : T.textMuted }} />
        </p>
        <p className="mt-0.5" style={ui(11, 400, T.textMuted)}>{sessionLive ? "Market Open" : "Market Closed"}</p>
      </div>
      <div className="flex items-center gap-3">
        <div className="text-right">
          <p style={microLabel}>Last Updated</p>
          <p className="mt-0.5" style={mono(12, 500, T.textSecondary)}>{updatedLabel}</p>
        </div>
        <RefreshCw size={14} color={T.textMuted} />
      </div>
    </div>
  );
};

/* --------------------------------------------------------------------- */
/* Market structure — real position of price within the S3..V3 ladder     */
/* --------------------------------------------------------------------- */
const MarketStructure = ({ levels, ltp }) => {
  // ltp can be null (no live quote -- market closed, illiquid contract).
  // Every computation below reads it, so this component simply renders
  // nothing rather than let null coerce to 0 in the arithmetic (which is
  // exactly what made supports look like resistances elsewhere on this
  // page -- see LiveLevelsPanel's own guard for the full explanation).
  if (ltp == null) return null;

  // Position along the full S5..V5 ladder -- purely a real, derived
  // number (where LTP actually sits between the widest real levels), not
  // a fabricated sentiment score.
  const hi = levels.H5, lo = levels.L5;
  const pct = hi > lo ? Math.min(100, Math.max(0, ((ltp - lo) / (hi - lo)) * 100)) : 50;

  const nearestResistance = ["H3", "H4", "H5"]
    .map((k) => ({ key: k, value: levels[k] }))
    .filter((l) => l.value > ltp)
    .sort((a, b) => a.value - b.value)[0];
  const nearestSupport = ["L3", "L4", "L5"]
    .map((k) => ({ key: k, value: levels[k] }))
    .filter((l) => l.value < ltp)
    .sort((a, b) => b.value - a.value)[0];

  return (
    <div className="rounded-2xl p-5 mb-4" style={{ background: T.card, border: `1px solid ${T.borderPrimary}` }} data-testid="exitline-market-structure">
      <p className="mb-4" style={microLabel}>Market Structure</p>
      <div className="grid grid-cols-1 md:grid-cols-[1.4fr_auto_auto] gap-6 items-center">
        <div>
          <div className="relative h-1.5 rounded-full overflow-hidden" style={{ background: `linear-gradient(to right, ${T.bearish}, ${T.borderSecondary}, ${T.bullish})` }}>
            <span
              className="absolute top-1/2 h-3 w-3 -translate-y-1/2 -translate-x-1/2 rounded-full"
              style={{ left: `${pct}%`, backgroundColor: T.textPrimary, border: `2px solid ${T.bg}` }}
            />
          </div>
          <div className="mt-2 flex items-center justify-between">
            <span style={{ ...ui(11, 600, T.bearish), textTransform: "uppercase", letterSpacing: "0.08em" }}>Bearish</span>
            <span style={{ ...ui(11, 500, T.textMuted), textTransform: "uppercase", letterSpacing: "0.08em" }}>Neutral</span>
            <span style={{ ...ui(11, 600, T.bullish), textTransform: "uppercase", letterSpacing: "0.08em" }}>Bullish</span>
          </div>
        </div>
        {nearestResistance && (
          <div>
            <p style={microLabel}>Nearest Resistance</p>
            <p className="mt-1 flex items-baseline gap-2">
              <span style={ui(13, 700, T.bearish)}>{DISPLAY_LABELS[nearestResistance.key]}</span>
              <span style={mono(15, 600, T.textPrimary)}>&#8377;{fmtNum(nearestResistance.value)}</span>
              <span style={mono(11, 500, T.bearish)}>{(((nearestResistance.value - ltp) / ltp) * 100).toFixed(2)}%</span>
            </p>
          </div>
        )}
        {nearestSupport && (
          <div>
            <p style={microLabel}>Nearest Support</p>
            <p className="mt-1 flex items-baseline gap-2">
              <span style={ui(13, 700, T.bullish)}>{DISPLAY_LABELS[nearestSupport.key]}</span>
              <span style={mono(15, 600, T.textPrimary)}>&#8377;{fmtNum(nearestSupport.value)}</span>
              <span style={mono(11, 500, T.bearish)}>{(((nearestSupport.value - ltp) / ltp) * 100).toFixed(2)}%</span>
            </p>
          </div>
        )}
      </div>
    </div>
  );
};

/* --------------------------------------------------------------------- */
/* Live levels panel                                                      */
/* --------------------------------------------------------------------- */
const LiveLevelsPanel = ({ levels, ltp }) => {
  const rows = [
    ...VISIBLE_LEVELS.map((k) => ({ key: k, value: levels[k], isLtp: false })),
    { key: "LTP", value: ltp, isLtp: true },
  ].sort((a, b) => b.value - a.value);

  return (
    <div className="rounded-2xl overflow-hidden h-full" style={{ background: T.card, border: `1px solid ${T.borderPrimary}` }} data-testid="exitline-ladder">
      <div className="px-4 py-3" style={{ borderBottom: `1px solid ${T.borderSecondary}` }}>
        <p style={microLabel}>Live Levels</p>
      </div>
      <div>
        {rows.map((r) => {
          const levelColor = r.isLtp ? T.sapphireBright : r.key.startsWith("H") ? T.bearish : r.key === "Pivot" ? "#22D3EE" : T.bullish;
          return (
            <div
              key={r.key}
              data-testid={r.isLtp ? "exitline-ltp-row" : `exitline-level-${r.key}`}
              className="flex items-center justify-between px-4 py-2.5"
              style={{ borderBottom: `1px solid ${T.borderSecondary}`, background: r.isLtp ? "rgba(22,119,255,0.10)" : "transparent" }}
            >
              <div>
                <span style={ui(12, 600, levelColor)}>{r.isLtp ? "Price (Live)" : DISPLAY_LABELS[r.key] || r.key}</span>
                <span className="block mt-0.5" style={ui(9, 400, T.textMuted)}>{r.isLtp ? "Market Price" : FULL_NAMES[r.key] || ""}</span>
              </div>
              <span style={mono(12, r.isLtp ? 700 : 500, r.isLtp ? T.textPrimary : T.textSecondary)}>
                {r.value == null ? "—" : `₹${fmtNum(r.value)}`}
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
};

/* --------------------------------------------------------------------- */
/* Session history — aggregated from the real intraday chart bars, not    */
/* invented: each date's own High/Low/Close comes straight off whatever   */
/* candles were actually returned for that date.                         */
/* --------------------------------------------------------------------- */
const useSessionHistoryRows = (chart) => useMemo(() => {
  if (!chart || chart.length === 0) return [];
  const byDate = new Map();
  for (const b of chart) {
    if (!b.date) continue;
    const cur = byDate.get(b.date);
    if (!cur) {
      byDate.set(b.date, { date: b.date, high: b.high, low: b.low, close: b.close });
    } else {
      cur.high = Math.max(cur.high, b.high);
      cur.low = Math.min(cur.low, b.low);
      cur.close = b.close; // bars arrive in ascending time order, so the last write is the session's real close
    }
  }
  return [...byDate.values()].sort((a, b) => (a.date < b.date ? 1 : -1)).slice(0, 10);
}, [chart]);

const SessionHistoryTable = ({ chart }) => {
  const rows = useSessionHistoryRows(chart);
  if (rows.length === 0) return null;
  return (
    <div className="rounded-2xl overflow-hidden mt-4" style={{ background: T.card, border: `1px solid ${T.borderPrimary}` }} data-testid="exitline-session-history">
      <div className="px-5 py-3.5" style={{ borderBottom: `1px solid ${T.borderSecondary}` }}>
        <p style={microLabel}>Session History</p>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full" style={{ fontVariantNumeric: "tabular-nums" }}>
          <thead>
            <tr style={{ borderBottom: `1px solid ${T.borderSecondary}` }}>
              {[["Date", "left"], ["High", "right"], ["Low", "right"], ["Close", "right"], ["Range", "right"]].map(([h, align]) => (
                <th key={h} className={`px-5 py-2.5 whitespace-nowrap text-${align}`} style={microLabel}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.date} data-testid={`exitline-session-row-${r.date}`} style={{ borderBottom: `1px solid ${T.borderSecondary}` }}>
                <td className="px-5 py-2.5 whitespace-nowrap" style={ui(12, 400, T.textSecondary)}>{fmtDateLong(r.date)}</td>
                <td className="px-5 py-2.5 text-right whitespace-nowrap" style={mono(12, 500, T.textSecondary)}>{fmtNum(r.high)}</td>
                <td className="px-5 py-2.5 text-right whitespace-nowrap" style={mono(12, 500, T.textSecondary)}>{fmtNum(r.low)}</td>
                <td className="px-5 py-2.5 text-right whitespace-nowrap" style={mono(12, 500, T.textPrimary)}>{fmtNum(r.close)}</td>
                <td className="px-5 py-2.5 text-right whitespace-nowrap" style={mono(12, 500, T.textMuted)}>{fmtNum(r.high - r.low)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
};

/* --------------------------------------------------------------------- */
/* Stat tiles — Bias, Range (S3-P), Upside to S3, Downside to P           */
/* --------------------------------------------------------------------- */
const StatTile = ({ label: lbl, children }) => (
  <div className="rounded-2xl p-5" style={{ background: T.card, border: `1px solid ${T.borderPrimary}` }}>
    <p className="mb-2" style={microLabel}>{lbl}</p>
    {children}
  </div>
);

const StatTiles = ({ result }) => {
  const { levels, ltp, bias } = result;
  const displayBias = BIAS_DISPLAY[bias] || "Neutral";
  const tone = BIAS_TONE[displayBias] || BIAS_TONE.Neutral;
  const Icon = tone.Icon;

  const range = levels.H3 - levels.Pivot;
  const upsideToS3 = levels.H3 - ltp;
  const upsideToS3Pct = (upsideToS3 / ltp) * 100;
  const downsideToP = levels.Pivot - ltp;
  const downsideToPPct = (downsideToP / ltp) * 100;

  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4 mt-4" data-testid="exitline-stat-tiles">
      <StatTile label="Bias">
        <div className="flex items-center gap-2.5">
          <span className="inline-flex h-8 w-8 items-center justify-center rounded-full" style={{ border: `2px dashed ${tone.color}66` }}>
            <Icon size={15} color={tone.color} />
          </span>
          <span style={{ fontFamily: F_UI, fontWeight: 600, fontSize: 22, color: tone.color, letterSpacing: "-0.01em" }}>{displayBias.toUpperCase()}</span>
        </div>
        <p className="mt-2" style={ui(11, 400, T.textMuted)}>{result.reason || (result.commentary ?? "No clear directional edge")}</p>
      </StatTile>
      <StatTile label="Range (S3 - P)">
        <p style={mono(22, 600, T.textPrimary)}>&#8377;{fmtNum(Math.abs(range))}</p>
        <p className="mt-1" style={ui(11, 400, T.textMuted)}>{((Math.abs(range) / ltp) * 100).toFixed(2)}% of Price</p>
      </StatTile>
      <StatTile label="Upside to S3">
        <p style={mono(22, 600, upsideToS3 >= 0 ? T.bullish : T.bearish)}>{upsideToS3 >= 0 ? "+" : "-"}&#8377;{fmtNum(Math.abs(upsideToS3))}</p>
        <p className="mt-1" style={mono(11, 500, upsideToS3 >= 0 ? T.bullish : T.bearish)}>{upsideToS3Pct >= 0 ? "+" : ""}{upsideToS3Pct.toFixed(2)}%</p>
      </StatTile>
      <StatTile label="Downside to P">
        <p style={mono(22, 600, downsideToP <= 0 ? T.bearish : T.bullish)}>{downsideToP >= 0 ? "+" : "-"}&#8377;{fmtNum(Math.abs(downsideToP))}</p>
        <p className="mt-1" style={mono(11, 500, downsideToP <= 0 ? T.bearish : T.bullish)}>{downsideToPPct >= 0 ? "+" : ""}{downsideToPPct.toFixed(2)}%</p>
      </StatTile>
    </div>
  );
};

const ExitlineResults = ({ result, interval, onIntervalChange, instrument, lastFetchedAt }) => {
  const live = useLivePrice("india", instrument, { enabled: !!instrument });
  return (
    <div data-testid="exitline-results">
      <InstrumentHeader result={result} live={live} lastFetchedAt={lastFetchedAt} />
      <MarketStructure levels={result.levels} ltp={result.ltp} />

      <div className="grid grid-cols-1 lg:grid-cols-[1fr_220px] gap-4">
        <div>
          <TVChart chart={result.chart} sessions={result.sessions} interval={interval} onIntervalChange={onIntervalChange} fetchGen={result.__fetchGen} market="india" symbol={instrument} />
          <SessionHistoryTable chart={result.chart} />
        </div>
        <LiveLevelsPanel levels={result.levels} ltp={result.ltp} />
      </div>

      {result.ltp != null && <StatTiles result={result} />}
    </div>
  );
};

const SymbolPicker = ({ segment, symbol, onSelect }) => {
  const [query, setQuery] = useState(symbol || "");
  const [options, setOptions] = useState([]);
  const [open, setOpen] = useState(false);
  const debounceRef = useRef(null);

  useEffect(() => { setQuery(symbol || ""); }, [symbol]);

  const onChange = (e) => {
    const v = e.target.value;
    setQuery(v);
    onSelect(""); // clear confirmed selection until a real pick is made
    if (debounceRef.current) clearTimeout(debounceRef.current);
    if (v.trim().length < 1) { setOptions([]); setOpen(false); return; }
    debounceRef.current = setTimeout(async () => {
      try {
        const { data } = await axios.get(`${API}/exitline/instruments`, { params: { segment, query: v.trim() } });
        setOptions(data.symbols || []);
        setOpen(true);
      } catch {
        setOptions([]);
      }
    }, 250);
  };

  const pick = (s) => {
    setQuery(s);
    setOpen(false);
    onSelect(s);
  };

  return (
    <div className="relative">
      <label className="block mb-1.5" style={microLabel}>Scrip</label>
      <div className="relative">
        <Search size={13} color={T.textMuted} className="absolute left-3 top-1/2 -translate-y-1/2" />
        <input
          value={query}
          onChange={onChange}
          onFocus={() => options.length > 0 && setOpen(true)}
          onBlur={() => setTimeout(() => setOpen(false), 150)}
          style={{ ...fieldStyle, paddingLeft: 30, width: "100%" }}
          placeholder="Search symbol… e.g. RELIANCE"
          data-testid="exitline-symbol-input"
          autoComplete="off"
        />
      </div>
      {open && options.length > 0 && (
        <div className="absolute z-20 mt-1 w-full max-h-56 overflow-y-auto rounded-md shadow-xl" style={{ background: T.cardElevated, border: `1px solid ${T.borderPrimary}` }} data-testid="exitline-symbol-dropdown">
          {options.map((s) => (
            <button
              type="button"
              key={s}
              onClick={() => pick(s)}
              className="block w-full text-left px-3 py-2 transition-colors"
              style={mono(12, 400, T.textSecondary)}
              onMouseEnter={(e) => { e.currentTarget.style.background = "rgba(255,255,255,0.06)"; }}
              onMouseLeave={(e) => { e.currentTarget.style.background = "transparent"; }}
            >
              {s}
            </button>
          ))}
        </div>
      )}
    </div>
  );
};

const ExitlineTool = () => {
  const [segment, setSegment] = useState("NSE");
  const [symbol, setSymbol] = useState("");
  const [expiryOptions, setExpiryOptions] = useState([]);
  const [expiry, setExpiry] = useState("");
  const [strikeOptions, setStrikeOptions] = useState([]);
  const [strike, setStrike] = useState("");
  const [optionType, setOptionType] = useState("CE");
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState(null);
  const [chartInterval, setChartInterval] = useState(5);
  const [lastFetchedAt, setLastFetchedAt] = useState(null);
  const genRef = useRef(0); // bumped on a real user-initiated fetch (submit/interval change), never on a silent poll — see TVChart's fitKey
  const paramsRef = useRef(null); // last-submitted query params, kept alive for the background poll

  // `gen` is only passed for a real user-initiated fetch (submit / interval
  // change) — a plain background poll omits it, so the tag on `result`
  // carries forward from whatever it already was rather than getting
  // clobbered. This is what lets TVChart tell "genuinely new view" apart
  // from "same view, fresher candles" reliably: chart[0]'s own timestamp
  // can't be used for that (every interval's first bucket aligns to the
  // same 09:15 market open, so it's identical across interval switches).
  const fetchLevels = async (params, { silent, gen } = {}) => {
    if (!silent) { setLoading(true); setResult(null); }
    try {
      const { data } = await axios.get(`${API}/exitline/levels`, { params });
      setResult((prev) => ({ ...data, __fetchGen: gen !== undefined ? gen : prev?.__fetchGen }));
      setLastFetchedAt(Date.now());
    } catch (err) {
      if (!silent) {
        toast.error(err?.response?.data?.detail || "Could not fetch levels. Please try again.");
        setResult({ found: false, reason: err?.response?.data?.detail || "Could not fetch levels for this instrument.", __fetchGen: gen });
      }
      // a silent background refresh failing (e.g. a transient Definedge hiccup) just keeps showing the last good result
    } finally {
      if (!silent) setLoading(false);
    }
  };

  // Keeps the chart/LTP live while a result is on screen — matches the
  // "live chart of that trading session" ask, without turning this into a
  // constantly-polling dashboard when nothing has been submitted yet.
  useEffect(() => {
    const pollId = setInterval(() => {
      if (paramsRef.current) fetchLevels(paramsRef.current, { silent: true });
    }, POLL_MS);
    return () => clearInterval(pollId);
  }, []);

  const changeSegment = (e) => {
    setSegment(e.target.value);
    setSymbol(""); setExpiry(""); setStrike(""); setExpiryOptions([]); setStrikeOptions([]); setResult(null);
    paramsRef.current = null;
  };

  const selectSymbol = async (s) => {
    setSymbol(s);
    setExpiry(""); setStrike(""); setExpiryOptions([]); setStrikeOptions([]); setResult(null);
    paramsRef.current = null;
    if (!s || segment === "NSE") return;
    try {
      const { data } = await axios.get(`${API}/exitline/instruments`, { params: { segment, symbol: s } });
      setExpiryOptions(data.expiries || []);
    } catch {
      setExpiryOptions([]);
    }
  };

  const changeExpiry = async (e) => {
    const exp = e.target.value;
    setExpiry(exp);
    setStrike(""); setStrikeOptions([]); setResult(null);
    paramsRef.current = null;
    if (!exp || segment !== "OPT") return;
    try {
      const { data } = await axios.get(`${API}/exitline/instruments`, { params: { segment, symbol, expiry: exp } });
      setStrikeOptions(data.strikes || []);
    } catch {
      setStrikeOptions([]);
    }
  };

  const canSubmit =
    symbol.trim() &&
    (segment === "NSE" || (segment === "FUT" && expiry) || (segment === "OPT" && expiry && strike && optionType));

  const submit = async (e) => {
    e.preventDefault();
    if (!canSubmit) return;
    const params = {
      segment,
      symbol: symbol.trim(),
      ...(segment !== "NSE" ? { expiry } : {}),
      ...(segment === "OPT" ? { strike, option_type: optionType } : {}),
      interval: chartInterval,
    };
    paramsRef.current = params;
    genRef.current += 1;
    await fetchLevels(params, { gen: genRef.current });
  };

  const changeInterval = (iv) => {
    setChartInterval(iv);
    if (!paramsRef.current) return;
    const params = { ...paramsRef.current, interval: iv };
    paramsRef.current = params;
    genRef.current += 1;
    fetchLevels(params, { silent: true, gen: genRef.current }); // swap the chart in place, no full-page loading flash
  };

  return (
    <div data-testid="exitline-tool">
      <form onSubmit={submit} className="rounded-2xl p-5 md:p-6 mb-6" style={{ background: T.card, border: `1px solid ${T.borderPrimary}` }}>
        <div className="grid grid-cols-2 md:grid-cols-5 gap-4 items-end">
          <div>
            <label className="block mb-1.5" style={microLabel}>Segment</label>
            <select value={segment} onChange={changeSegment} style={{ ...fieldStyle, width: "100%" }} data-testid="exitline-segment">
              {SEGMENTS.map((s) => <option key={s.key} value={s.key} style={{ background: T.cardElevated }}>{s.label}</option>)}
            </select>
          </div>

          <SymbolPicker segment={segment} symbol={symbol} onSelect={selectSymbol} />

          {segment !== "NSE" && (
            <div>
              <label className="block mb-1.5" style={microLabel}>Expiry</label>
              <select value={expiry} onChange={changeExpiry} style={{ ...fieldStyle, width: "100%" }} data-testid="exitline-expiry" disabled={!symbol}>
                <option value="" style={{ background: T.cardElevated }}>Select…</option>
                {expiryOptions.map((e) => <option key={e} value={e} style={{ background: T.cardElevated }}>{fmtDate(e)}</option>)}
              </select>
            </div>
          )}

          {segment === "OPT" && (
            <>
              <div>
                <label className="block mb-1.5" style={microLabel}>Strike</label>
                <select value={strike} onChange={(e) => { setStrike(e.target.value); setResult(null); paramsRef.current = null; }} style={{ ...fieldStyle, width: "100%" }} data-testid="exitline-strike" disabled={!expiry}>
                  <option value="" style={{ background: T.cardElevated }}>Select…</option>
                  {strikeOptions.map((s) => <option key={s} value={s} style={{ background: T.cardElevated }}>{s}</option>)}
                </select>
              </div>
              <div>
                <label className="block mb-1.5" style={microLabel}>Type</label>
                <select value={optionType} onChange={(e) => { setOptionType(e.target.value); setResult(null); paramsRef.current = null; }} style={{ ...fieldStyle, width: "100%" }} data-testid="exitline-option-type">
                  <option value="CE" style={{ background: T.cardElevated }}>CE</option>
                  <option value="PE" style={{ background: T.cardElevated }}>PE</option>
                </select>
              </div>
            </>
          )}

          <button
            type="submit"
            disabled={loading || !canSubmit}
            data-testid="exitline-submit"
            className="h-[38px] rounded-lg flex items-center justify-center gap-1.5 disabled:opacity-50"
            style={{ background: T.sapphire, ...ui(13, 600, "#FFFFFF") }}
          >
            {loading ? <><Loader2 size={15} className="animate-spin" /> Fetching</> : "Get Levels"}
          </button>
        </div>
      </form>

      {loading && <LoadingParticles title="Computing Levels" subtitle="Fetching prior session H/L/C · Live PX · Level ladder" />}
      {!loading && result && result.found === false && <EmptyState reason={result.reason} />}
      {!loading && result && result.found !== false && (
        <ExitlineResults
          result={result}
          interval={chartInterval}
          onIntervalChange={changeInterval}
          lastFetchedAt={lastFetchedAt}
          // The same instrument /levels resolved — /exitline/quote takes
          // these params and returns only the LTP. `interval` is dropped:
          // it doesn't identify the instrument, and leaving it in would
          // open a fresh poll channel on every timeframe switch.
          instrument={paramsRef.current ? (({ interval, ...rest }) => rest)(paramsRef.current) : null}
        />
      )}
    </div>
  );
};

export default ExitlineTool;
