import { useState, useEffect, useMemo } from "react";
import axios from "axios";
import { Maximize2, X, Info } from "lucide-react";
import {
  ResponsiveContainer, LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ReferenceLine,
} from "recharts";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;
const AVERAGE_WINDOW = 15; // points, not minutes -- refresh cadence is ~5min but each refresh recomputes full per-minute resolution

// Same explanation the reference platform surfaces from its own "i" icon
// on this chart -- describing the real, shared X-Percent method (Prashant
// Shah, Ch. 10; see breadth_engine.py), not anything proprietary to it.
const BREADTH_DESCRIPTION =
  "This section shows the intraday chart of X% breadth indicator on the Nifty 50 universe. " +
  "X% breadth indicator calculates the number of stocks in the column of X in the given timeframe. " +
  "If more stocks are in column X, it is bullish. Based on 0.15% box-value of one-minute Nifty 50 " +
  "and Nifty 500 stocks, this chart shows the number of stocks in the column X. Rising indicator " +
  "shows that more stocks in the Nifty 50 and Nifty 500 universe are in the bullish column (X). " +
  "Falling indicator shows that more stocks in the Nifty 50 and Nifty 500 universe are in the " +
  "bearish column (O).";

const GROUPS = [
  { key: "nifty-50", label: "Nifty 50" },
  { key: "nifty-500", label: "Nifty 500" },
];

// Parses intraday_breadth's minute-key format (Definedge's DDMMYYYYHHMM,
// same as every other intraday bar `ts` in this codebase) into an HH:MM
// label for the x-axis.
const timeLabel = (ts) => (ts && ts.length >= 12 ? `${ts.slice(8, 10)}:${ts.slice(10, 12)}` : ts);

const withAverage = (series) => series.map((p, i) => {
  const window = series.slice(Math.max(0, i - AVERAGE_WINDOW + 1), i + 1);
  const avg = window.reduce((sum, w) => sum + w.value, 0) / window.length;
  return { ...p, label: timeLabel(p.date), avg: Math.round(avg * 100) / 100 };
});

const GroupToggle = ({ group, setGroup }) => (
  <div className="flex items-center gap-1">
    {GROUPS.map((g) => (
      <button
        key={g.key}
        type="button"
        disabled={g.key === "nifty-500"}
        onClick={(e) => { e.stopPropagation(); setGroup(g.key); }}
        title={g.key === "nifty-500" ? "Coming soon" : undefined}
        className="px-2 py-0.5 text-[10px] uppercase tracking-wider border"
        style={{
          borderColor: "var(--term-border)",
          color: g.key === "nifty-500" ? "var(--term-grey)" : group === g.key ? "#000" : "var(--term-cyan)",
          background: group === g.key && g.key !== "nifty-500" ? "var(--term-cyan)" : "transparent",
          opacity: g.key === "nifty-500" ? 0.4 : 1,
          cursor: g.key === "nifty-500" ? "not-allowed" : "pointer",
        }}
        data-testid={`mkt-breadth-group-${g.key}`}
      >
        {g.label}
      </button>
    ))}
  </div>
);

// Shared between the inline panel and the expanded full-screen view --
// only the container height differs, so the chart itself (data, axes,
// reference line) is never duplicated.
const BreadthChart = ({ series, latest, heightClass }) => (
  <div className={`${heightClass} px-1 py-2`}>
    {series.length ? (
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={series} margin={{ top: 4, right: 12, left: 0, bottom: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="var(--term-border)" vertical={false} />
          <XAxis dataKey="label" tick={{ fill: "var(--term-grey)", fontSize: 10 }} axisLine={{ stroke: "var(--term-border)" }} tickLine={false} minTickGap={40} />
          <YAxis domain={[0, 100]} tick={{ fill: "var(--term-grey)", fontSize: 10 }} axisLine={false} tickLine={false} width={30} tickFormatter={(v) => `${v}`} />
          <ReferenceLine y={latest?.avg} stroke="#C4553B" strokeDasharray="4 4" />
          <Tooltip
            labelFormatter={(v) => v}
            formatter={(v, name) => [`${v}%`, name === "avg" ? "Average" : "Breadth"]}
            contentStyle={{ background: "#080808", border: "1px solid var(--term-border)", fontSize: 11 }}
            labelStyle={{ color: "var(--term-grey)" }}
          />
          <Line type="stepAfter" dataKey="value" stroke="var(--term-green)" strokeWidth={1.5} dot={false} isAnimationActive={false} />
          <Line type="monotone" dataKey="avg" stroke="var(--term-red)" strokeWidth={1.5} dot={false} isAnimationActive={false} />
        </LineChart>
      </ResponsiveContainer>
    ) : (
      <div className="flex items-center justify-center h-full text-[11px] term-grey">Loading…</div>
    )}
  </div>
);

const IntradayBreadthPanel = () => {
  const [group, setGroup] = useState("nifty-50");
  const [data, setData] = useState(null);
  const [expanded, setExpanded] = useState(false);

  useEffect(() => {
    let cancelled = false;
    const load = () => {
      axios.get(`${API}/terminal/intraday-breadth`, { params: { group } })
        .then(({ data: d }) => { if (!cancelled) setData(d); })
        .catch(() => { if (!cancelled) setData({ has_data: false }); });
    };
    load();
    const id = setInterval(load, 60000);
    return () => { cancelled = true; clearInterval(id); };
  }, [group]);

  // Escape closes the expanded view -- only wired while it's actually open.
  useEffect(() => {
    if (!expanded) return undefined;
    const onKey = (e) => { if (e.key === "Escape") setExpanded(false); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [expanded]);

  const series = useMemo(() => (data?.has_data ? withAverage(data.series) : []), [data]);
  const latest = series.length ? series[series.length - 1] : null;
  const statusText = latest
    ? (
      <span className="term-grey">
        BREADTH <span style={{ color: "var(--term-text)" }}>{latest.value}%</span>, AVERAGE <span style={{ color: "var(--term-text)" }}>{latest.avg}%</span>
        {data?.stale && <span style={{ color: "var(--term-red)" }}> · LAST SESSION ({data.trading_date})</span>}
      </span>
    )
    : <span className="term-grey">{data?.reason || "Loading…"}</span>;

  return (
    <div data-testid="mkt-intraday-breadth-panel">
      <button
        type="button"
        onClick={() => setExpanded(true)}
        className="w-full flex items-center justify-between px-3 py-1.5 term-panel-head text-left hover:brightness-125 transition-[filter]"
        title="Click to expand"
        data-testid="mkt-breadth-expand-trigger"
      >
        <span className="flex items-center gap-2">
          INTRADAY X% BREADTH
          <Info size={12} className="term-grey" title={BREADTH_DESCRIPTION} data-testid="mkt-breadth-info" />
          <Maximize2 size={11} className="term-grey" />
        </span>
        <GroupToggle group={group} setGroup={setGroup} />
      </button>

      <div className="px-3 py-2 text-[11px] border-b" style={{ borderColor: "var(--term-border)" }}>
        {statusText}
      </div>

      <BreadthChart series={series} latest={latest} heightClass="h-64" />

      {expanded && (
        <div
          className="mkt-terminal fixed inset-0 z-[200] flex flex-col"
          role="dialog"
          aria-modal="true"
          data-testid="mkt-breadth-expanded"
        >
          <div className="flex items-center justify-between px-4 py-3 term-panel-head shrink-0">
            <span className="flex items-center gap-3 text-[13px]">
              INTRADAY X% BREADTH
              <Info size={13} className="term-grey" title={BREADTH_DESCRIPTION} />
              <GroupToggle group={group} setGroup={setGroup} />
            </span>
            <button type="button" onClick={() => setExpanded(false)} className="term-grey hover:text-white transition-colors" data-testid="mkt-breadth-close">
              <X size={18} />
            </button>
          </div>
          <div className="px-4 py-3 text-[13px] border-b shrink-0" style={{ borderColor: "var(--term-border)" }}>
            {statusText}
          </div>
          <div className="flex-1 min-h-0">
            <BreadthChart series={series} latest={latest} heightClass="h-full" />
          </div>
        </div>
      )}
    </div>
  );
};

export default IntradayBreadthPanel;
