import { useEffect, useState } from "react";

/*
  Dotted vertical session dividers for the Exitline candlestick charts.

  Why an HTML overlay rather than a chart series: lightweight-charts has no
  vertical-line primitive (createPriceLine is horizontal only), and a line
  series can't hold two y-values at one x. Positioning absolute divs off
  timeScale().timeToCoordinate() is the supported way to do this and stays
  in sync with pan/zoom, which is what actually matters here — the chart
  spans ~30 sessions and is scrollable.

  Visual matches the dividers PnfChart/RenkoChart already draw (#64748B,
  3x3 dashes, 55% opacity) so the three charts read as one system.

  Boundary rule: the first bar whose calendar date differs from the
  previous bar's. The very first session is skipped — a divider at the left
  edge marks nothing. This is the same rule as
  exitlineOverlay.findSessionBoundaries, expressed against bars (which
  carry `date`) rather than P&F columns' start_label.
*/
const SessionDividers = ({ chartRef, bars, redrawKey }) => {
  const [xs, setXs] = useState([]);

  useEffect(() => {
    const chart = chartRef?.current;
    if (!chart || !bars || bars.length === 0) { setXs([]); return undefined; }

    const boundaries = [];
    let lastDate = null;
    for (const b of bars) {
      if (b.time == null || !b.date) continue;
      if (lastDate !== null && b.date !== lastDate) boundaries.push(b.time);
      lastDate = b.date;
    }
    if (boundaries.length === 0) { setXs([]); return undefined; }

    const timeScale = chart.timeScale();
    const recompute = () => {
      setXs(
        boundaries
          .map((t) => timeScale.timeToCoordinate(t))
          // Off-screen boundaries return null while panned away.
          .filter((x) => x != null),
      );
    };

    recompute();
    timeScale.subscribeVisibleLogicalRangeChange(recompute);
    // autoSize charts resize without a logical-range change, so the
    // container itself has to be watched too or the lines drift on resize.
    let observer;
    if (typeof ResizeObserver !== "undefined" && chart.chartElement) {
      observer = new ResizeObserver(recompute);
      observer.observe(chart.chartElement());
    }
    return () => {
      try { timeScale.unsubscribeVisibleLogicalRangeChange(recompute); } catch { /* chart already disposed */ }
      if (observer) observer.disconnect();
    };
  }, [chartRef, bars, redrawKey]);

  if (xs.length === 0) return null;

  return (
    <div className="pointer-events-none absolute inset-0 overflow-hidden" data-testid="exitline-session-dividers">
      {xs.map((x, i) => (
        <span
          key={`${x}-${i}`}
          className="absolute top-0 bottom-0"
          style={{
            left: `${x}px`,
            width: 0,
            borderLeft: "1px dashed #64748B",
            opacity: 0.55,
          }}
        />
      ))}
    </div>
  );
};

export default SessionDividers;
