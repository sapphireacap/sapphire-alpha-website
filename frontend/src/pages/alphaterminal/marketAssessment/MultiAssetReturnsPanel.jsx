import { useState, useEffect, useMemo } from "react";
import axios from "axios";
import {
  ResponsiveContainer, LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ReferenceLine,
} from "recharts";
import { toneColor } from "./terminalTheme";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;
const fmtSigned = (n) => (n == null ? "—" : `${n >= 0 ? "+" : ""}${n.toFixed(2)}%`);

// Fixed per-asset colors, distinct from the term-green/term-red tone
// palette used everywhere else on this page (those are reserved for
// price-direction semantics; a 3-line comparison chart needs its own
// stable hues so a line's color never gets misread as "this one is
// bearish").
const ASSET_COLOR = { NIFTY50: "var(--term-cyan)", USDINR: "var(--term-green)", GOLD: "var(--term-amber)" };

const fmtDate = (iso) => {
  if (!iso) return "";
  const [, m, d] = iso.split("-");
  const MONTHS = ["", "Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  return `${d} ${MONTHS[Number(m)]}`;
};

const MultiAssetReturnsPanel = () => {
  const [data, setData] = useState(null);

  useEffect(() => {
    let cancelled = false;
    axios.get(`${API}/terminal/multi-asset-returns`, { params: { days: 90 } })
      .then(({ data: d }) => { if (!cancelled) setData(d); })
      .catch(() => { if (!cancelled) setData({ assets: [], unavailable: [] }); });
    return () => { cancelled = true; };
  }, []);

  const chartRows = useMemo(() => {
    if (!data?.assets?.length) return [];
    const byDate = {};
    data.assets.forEach((a) => {
      a.points.forEach((p) => {
        byDate[p.date] = byDate[p.date] || { date: p.date };
        byDate[p.date][a.key] = p.value;
      });
    });
    return Object.keys(byDate).sort().map((d) => ({ ...byDate[d], label: fmtDate(d) }));
  }, [data]);

  if (!data) {
    return <div className="flex items-center justify-center h-64 text-[11px] term-grey">Loading…</div>;
  }

  return (
    <div data-testid="mkt-multi-asset-panel">
      <div className="px-3 py-1.5 term-panel-head">MULTI ASSET RETURNS % (3 MONTHS)</div>

      <div className="flex flex-wrap gap-4 px-3 py-2 text-[11px] border-b" style={{ borderColor: "var(--term-border)" }}>
        {data.assets.map((a) => (
          <span key={a.key}>
            <span style={{ color: ASSET_COLOR[a.key] }}>{a.label}</span>{" "}
            <span style={{ color: toneColor(a.change_pct) }}>{fmtSigned(a.change_pct)}</span>
          </span>
        ))}
        {data.unavailable?.map((a) => (
          <span key={a.key} className="term-grey">{a.label}: N/A</span>
        ))}
      </div>

      <div className="h-64 px-1 py-2">
        {chartRows.length ? (
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={chartRows} margin={{ top: 4, right: 12, left: 0, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="var(--term-border)" vertical={false} />
              <XAxis dataKey="label" tick={{ fill: "var(--term-grey)", fontSize: 10 }} axisLine={{ stroke: "var(--term-border)" }} tickLine={false} minTickGap={50} />
              <YAxis domain={["auto", "auto"]} tick={{ fill: "var(--term-grey)", fontSize: 10 }} axisLine={false} tickLine={false} width={34} />
              <ReferenceLine y={100} stroke="#C4553B" strokeDasharray="4 4" />
              <Tooltip
                formatter={(v, key) => [`${Number(v).toFixed(2)}`, data.assets.find((a) => a.key === key)?.label || key]}
                contentStyle={{ background: "#080808", border: "1px solid var(--term-border)", fontSize: 11 }}
                labelStyle={{ color: "var(--term-grey)" }}
              />
              {data.assets.map((a) => (
                <Line key={a.key} type="monotone" dataKey={a.key} stroke={ASSET_COLOR[a.key]} strokeWidth={1.5} dot={false} isAnimationActive={false} connectNulls />
              ))}
            </LineChart>
          </ResponsiveContainer>
        ) : (
          <div className="flex items-center justify-center h-full text-[11px] term-grey">No data available right now.</div>
        )}
      </div>
    </div>
  );
};

export default MultiAssetReturnsPanel;
