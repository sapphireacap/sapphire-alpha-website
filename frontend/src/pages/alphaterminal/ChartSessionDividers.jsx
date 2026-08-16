import { useEffect, useState } from "react";

/*
  Dotted vertical session dividers for the Exitline candlestick charts.

  Split deliberately into a HOOK (called inside the chart component, where
  the chart instance is guaranteed to exist) and a dumb presentational
  component. An earlier version put the whole thing in a child component
  that read the parent's chartRef, and it never drew a single line: React
  runs a child's effects BEFORE its parent's, so chartRef.current was still
  null there, and since the bars prop never changed afterwards the effect
  never re-ran. Measured, not guessed — the diagnostic showed the effect
  running with 12798 bars and chartAtStart:false forever.

  Why an HTML overlay rather than a chart series: lightweight-charts has no
  vertical-line primitive (createPriceLine is horizontal only), and a line
  series can't hold two y-values at one x. Positioning absolute elements off
  timeScale().timeToCoordinate() is the supported approach and stays in sync
  with pan/zoom, which matters — the chart holds ~30 scrollable sessions.

  Visual matches the dividers PnfChart/RenkoChart already draw (#64748B,
  3x3 dashes, 55% opacity) so the three charts read as one system.
*/

// The first bar whose calendar date differs from the previous bar's. The
// very first bar is never a boundary. Same rule as
// exitlineOverlay.findSessionBoundaries, against bars rather than columns.
export const sessionBoundaryTimes = (bars) => {
  const out = [];
  let lastDate = null;
  for (const b of bars || []) {
    if (b.time == null || !b.date) continue;
    if (lastDate !== null && b.date !== lastDate) out.push(b.time);
    lastDate = b.date;
  }
  return out;
};

/**
 * Call INSIDE the chart component, after its chart instance exists.
 * `deps` should change whenever the chart's data or view is rebuilt.
 */
export const useSessionDividers = (chartRef, containerRef, bars, deps = []) => {
  const [xs, setXs] = useState([]);

  useEffect(() => {
    const chart = chartRef.current;
    if (!chart || !bars || bars.length === 0) { setXs([]); return undefined; }
    const boundaries = sessionBoundaryTimes(bars);
    if (boundaries.length === 0) { setXs([]); return undefined; }

    const scale = chart.timeScale();
    const recompute = () => {
      // timeToCoordinate does NOT return null for an off-screen time — it
      // returns a coordinate far outside the pane (measured: -75590px for
      // the oldest boundary while the view showed a single session). The
      // width clamp is what keeps this to the few actually on screen
      // instead of mounting ~53 nodes on every pan.
      const width = containerRef.current?.clientWidth || 0;
      if (!width) return;
      const coords = boundaries.map((t) => scale.timeToCoordinate(t));
      setXs(coords.filter((x) => x != null && x >= 0 && x <= width));
    };

    recompute();
    // The visible range is set in the same effect that calls this hook's
    // deps, so one deferred pass catches the settled scale.
    const raf = requestAnimationFrame(recompute);
    scale.subscribeVisibleLogicalRangeChange(recompute);

    let observer;
    if (typeof ResizeObserver !== "undefined" && containerRef.current) {
      observer = new ResizeObserver(recompute);
      observer.observe(containerRef.current);
    }
    return () => {
      cancelAnimationFrame(raf);
      try { scale.unsubscribeVisibleLogicalRangeChange(recompute); } catch { /* chart already disposed */ }
      if (observer) observer.disconnect();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [chartRef, containerRef, bars, ...deps]);

  return xs;
};

const SessionDividers = ({ xs }) => (
  <div
    className="pointer-events-none absolute inset-0 overflow-hidden"
    data-testid="exitline-session-dividers"
    data-divider-count={(xs || []).length}
  >
    {(xs || []).map((x, i) => (
      <span
        key={`${x}-${i}`}
        className="absolute top-0 bottom-0"
        style={{ left: `${x}px`, width: 0, borderLeft: "1px dashed #64748B", opacity: 0.55 }}
      />
    ))}
  </div>
);

export default SessionDividers;
