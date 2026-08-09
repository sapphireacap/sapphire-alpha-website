import { useState, useEffect, useMemo } from "react";
import axios from "axios";
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
  BarChart, Bar, Cell, PieChart, Pie,
} from "recharts";
import { Loader2, TrendingUp, TrendingDown } from "lucide-react";
import { EmptyState } from "./QuantLab";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;
const SURFACE = "rounded-2xl border border-white/10 bg-[#0A0D18]";
const UP = "#3ED598";
const DOWN = "#F87171";

const fmt = (n, digits = 2) => (n == null ? "—" : Number(n).toLocaleString("en-IN", { maximumFractionDigits: digits, minimumFractionDigits: digits }));
const fmtSigned = (n, digits = 2) => (n == null ? "—" : `${n >= 0 ? "+" : ""}${fmt(n, digits)}`);
const changeColor = (n) => (n == null ? "text-slate-500" : n >= 0 ? "text-emerald-400" : "text-red-400");

// NSE cash session: 09:15-15:30 IST, weekdays. The backend snapshot itself
// only moves during this window (market-dashboard-refresh.yml's cron is
// weekdays-only, 09:15-15:30 IST) -- polling outside it would just hit the
// same cached doc repeatedly, so this gates the interval below rather than
// running it unconditionally.
const isSessionLive = () => {
  const now = new Date();
  const istMinutes = Math.floor((now.getTime() + (330 + now.getTimezoneOffset()) * 60000) / 60000);
  const day = new Date(istMinutes * 60000).getUTCDay();
  if (day === 0 || day === 6) return false;
  const minuteOfDay = istMinutes % 1440;
  return minuteOfDay >= 9 * 60 + 15 && minuteOfDay <= 15 * 60 + 30;
};

const SectionLabel = ({ children }) => (
  <p className="font-mono-ui text-[10px] uppercase tracking-[0.16em] text-slate-500 mb-3">{children}</p>
);

const CardError = ({ reason }) => (
  <div className={`${SURFACE} px-5 py-8 text-center`}>
    <p className="text-xs font-light text-slate-500">{reason || "This card's data source is unavailable right now."}</p>
  </div>
);

const HeadlineStrip = ({ rows }) => (
  <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-3 mb-8" data-testid="md-headline-strip">
    {rows.map((r) => (
      <div key={r.index} className={`${SURFACE} p-4`}>
        <p className="font-mono-ui text-[10px] uppercase tracking-[0.12em] text-slate-500 truncate">{r.index}</p>
        <p className="text-lg font-bold text-white mt-1">{fmt(r.last, r.last > 1000 ? 0 : 2)}</p>
        <p className={`font-mono-ui text-xs mt-0.5 flex items-center gap-1 ${changeColor(r.change_pct)}`}>
          {r.change_pct >= 0 ? <TrendingUp size={11} /> : <TrendingDown size={11} />}
          {fmtSigned(r.change)} ({fmtSigned(r.change_pct)}%)
        </p>
      </div>
    ))}
  </div>
);

const IndexBarChart = ({ rows, testId }) => {
  const data = [...rows].sort((a, b) => (b.change_pct ?? 0) - (a.change_pct ?? 0));
  const height = Math.max(160, data.length * 32);
  return (
    <div className={`${SURFACE} p-4`} style={{ height }} data-testid={testId}>
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={data} layout="vertical" margin={{ top: 4, right: 24, left: 4, bottom: 4 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.06)" horizontal={false} />
          <XAxis type="number" tick={{ fill: "#64748B", fontSize: 10 }} axisLine={false} tickLine={false} tickFormatter={(v) => `${v}%`} />
          <YAxis type="category" dataKey="index" width={140} tick={{ fill: "#94A3B8", fontSize: 11 }} axisLine={false} tickLine={false} />
          <Tooltip
            formatter={(v) => [`${fmtSigned(v)}%`, "Change"]}
            contentStyle={{ background: "#0A0D18", border: "1px solid rgba(255,255,255,0.1)", borderRadius: 8, fontSize: 12 }}
            labelStyle={{ color: "#94A3B8" }}
          />
          <Bar dataKey="change_pct" radius={[0, 4, 4, 0]}>
            {data.map((r) => <Cell key={r.index} fill={(r.change_pct ?? 0) >= 0 ? UP : DOWN} />)}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
};

const AdvanceDeclineDonut = ({ advances, declines, unchanged }) => {
  const total = (advances || 0) + (declines || 0) + (unchanged || 0);
  const data = [
    { name: "Advance", value: advances || 0, color: UP },
    { name: "Decline", value: declines || 0, color: DOWN },
  ];
  return (
    <div className={`${SURFACE} p-4 flex items-center gap-6`} data-testid="md-ad-donut">
      <div style={{ width: 140, height: 140 }} className="shrink-0">
        <ResponsiveContainer width="100%" height="100%">
          <PieChart>
            <Pie data={data} dataKey="value" innerRadius={42} outerRadius={64} startAngle={90} endAngle={-270} stroke="none">
              {data.map((d) => <Cell key={d.name} fill={d.color} />)}
            </Pie>
          </PieChart>
        </ResponsiveContainer>
      </div>
      <div className="flex flex-col gap-2">
        <div className="flex items-center gap-2">
          <span className="w-2.5 h-2.5 rounded-sm shrink-0" style={{ background: UP }} />
          <span className="font-mono-ui text-xs text-slate-300">Advance {advances ?? "—"}{total ? ` (${((advances / total) * 100).toFixed(1)}%)` : ""}</span>
        </div>
        <div className="flex items-center gap-2">
          <span className="w-2.5 h-2.5 rounded-sm shrink-0" style={{ background: DOWN }} />
          <span className="font-mono-ui text-xs text-slate-300">Decline {declines ?? "—"}{total ? ` (${((declines / total) * 100).toFixed(1)}%)` : ""}</span>
        </div>
        <div className="flex items-center gap-2">
          <span className="w-2.5 h-2.5 rounded-sm shrink-0 bg-white/20" />
          <span className="font-mono-ui text-xs text-slate-500">Unchanged {unchanged ?? "—"}</span>
        </div>
      </div>
    </div>
  );
};

const IntradayAdChart = ({ points }) => (
  <div className={`${SURFACE} p-4`} style={{ height: 260 }} data-testid="md-intraday-ad-chart">
    <ResponsiveContainer width="100%" height="100%">
      <LineChart data={points} margin={{ top: 10, right: 10, left: 0, bottom: 0 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.06)" vertical={false} />
        <XAxis dataKey="time" tick={{ fill: "#64748B", fontSize: 10 }} axisLine={{ stroke: "rgba(255,255,255,0.1)" }} tickLine={false} minTickGap={45} />
        <YAxis tick={{ fill: "#64748B", fontSize: 11 }} axisLine={false} tickLine={false} width={40} />
        <Tooltip
          contentStyle={{ background: "#0A0D18", border: "1px solid rgba(255,255,255,0.1)", borderRadius: 8, fontSize: 12 }}
          labelStyle={{ color: "#94A3B8" }}
        />
        <Line type="monotone" dataKey="advances" name="Advances" stroke={UP} strokeWidth={1.5} dot={false} isAnimationActive={false} />
        <Line type="monotone" dataKey="declines" name="Declines" stroke={DOWN} strokeWidth={1.5} dot={false} isAnimationActive={false} />
      </LineChart>
    </ResponsiveContainer>
  </div>
);

const HiLoStat = ({ high, low }) => (
  <div className={`${SURFACE} p-5 grid grid-cols-2 gap-4`} data-testid="md-52w-hilo">
    <div>
      <p className="font-mono-ui text-[10px] uppercase tracking-[0.16em] text-slate-500">New 52W High</p>
      <p className="text-2xl font-bold text-emerald-400 mt-1">{high ?? "—"}</p>
    </div>
    <div>
      <p className="font-mono-ui text-[10px] uppercase tracking-[0.16em] text-slate-500">New 52W Low</p>
      <p className="text-2xl font-bold text-red-400 mt-1">{low ?? "—"}</p>
    </div>
  </div>
);

const FiiDiiTable = ({ rows }) => (
  <div className={`${SURFACE} overflow-hidden`} data-testid="md-fii-dii-table">
    <div className="overflow-x-auto">
      <table className="w-full" style={{ fontVariantNumeric: "tabular-nums" }}>
        <thead>
          <tr className="border-b border-white/10">
            {["Date", "FII/DII Net", "FII Net", "DII Net"].map((h) => (
              <th key={h} className="px-4 py-3 text-left font-mono-ui text-[10px] uppercase tracking-[0.16em] text-slate-500 font-semibold whitespace-nowrap">{h}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => {
            const combined = (r.fii?.net ?? 0) + (r.dii?.net ?? 0);
            return (
              <tr key={r.date} className="border-b border-white/[0.05] last:border-0">
                <td className="px-4 py-2.5 font-mono-ui text-xs text-slate-300 whitespace-nowrap">{r.date}</td>
                <td className={`px-4 py-2.5 font-mono-ui text-xs whitespace-nowrap ${changeColor(combined)}`}>{fmtSigned(combined)}</td>
                <td className={`px-4 py-2.5 font-mono-ui text-xs whitespace-nowrap ${changeColor(r.fii?.net)}`}>{fmtSigned(r.fii?.net)}</td>
                <td className={`px-4 py-2.5 font-mono-ui text-xs whitespace-nowrap ${changeColor(r.dii?.net)}`}>{fmtSigned(r.dii?.net)}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  </div>
);

const GlobalIndicesGrid = ({ rows }) => (
  <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-3" data-testid="md-global-indices">
    {rows.map((r) => (
      <div key={r.key} className={`${SURFACE} p-4`}>
        <p className="font-mono-ui text-[10px] uppercase tracking-[0.12em] text-slate-500 truncate">{r.label}</p>
        <p className="text-lg font-bold text-white mt-1">{fmt(r.last, 0)}</p>
        <p className={`font-mono-ui text-xs mt-0.5 ${changeColor(r.change_pct)}`}>{fmtSigned(r.change_pct)}%</p>
      </div>
    ))}
  </div>
);

const StatusBar = ({ updatedAt }) => {
  const live = isSessionLive();
  const time = updatedAt
    ? new Date(updatedAt).toLocaleTimeString("en-IN", { timeZone: "Asia/Kolkata", hour: "2-digit", minute: "2-digit" })
    : "—";
  return (
    <div className="flex items-center gap-2 mb-6" data-testid="md-status">
      <span className={`h-1.5 w-1.5 rounded-full shrink-0 ${live ? "bg-emerald-400 animate-pulse" : "bg-slate-600"}`} />
      <p className="font-mono-ui text-[10px] uppercase tracking-[0.14em] text-slate-500">
        {live ? "Live — updating every minute" : `Market closed — last updated ${time} IST`}
      </p>
    </div>
  );
};

const MarketDashboardTool = () => {
  const [data, setData] = useState(null);
  const [adHistory, setAdHistory] = useState(null);
  const [fiiDiiHistory, setFiiDiiHistory] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);

  useEffect(() => {
    let cancelled = false;

    const load = (isInitial) => {
      Promise.all([
        axios.get(`${API}/terminal/market-dashboard/snapshot`),
        axios.get(`${API}/terminal/market-dashboard/advance-decline-intraday`).catch(() => ({ data: { points: [] } })),
        axios.get(`${API}/terminal/market-dashboard/fii-dii-history`).catch(() => ({ data: { rows: [] } })),
      ])
        .then(([snap, ad, fd]) => {
          if (cancelled) return;
          setData(snap.data);
          setAdHistory(ad.data.points || []);
          setFiiDiiHistory(fd.data.rows || []);
          setError(false);
        })
        .catch(() => { if (!cancelled) setError(true); })
        .finally(() => { if (!cancelled && isInitial) setLoading(false); });
    };

    load(true);

    // Polls every minute while the NSE cash session is live, self-stopping
    // the moment it isn't -- re-checked on every tick rather than just once
    // at mount, so a tab left open through the 15:30 close stops polling
    // instead of hitting the same cached snapshot forever.
    const id = setInterval(() => {
      if (!isSessionLive()) return;
      load(false);
    }, 60000);

    return () => { cancelled = true; clearInterval(id); };
  }, []);

  const errors = data?.errors || {};
  const indices = data?.indices;

  if (loading) {
    return (
      <div className="flex items-center justify-center py-20 text-slate-500 font-mono-ui text-sm gap-3">
        <Loader2 className="animate-spin" size={16} /> Loading market dashboard…
      </div>
    );
  }
  if (error || !data) {
    return <EmptyState reason="Market Dashboard hasn't been computed yet — check back shortly." />;
  }

  return (
    <div data-testid="market-dashboard-tool">
      <StatusBar updatedAt={data.updated_at} />
      {indices?.headline?.length ? <HeadlineStrip rows={indices.headline} /> : <CardError reason="Index levels unavailable." />}

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 mb-8">
        <div>
          <SectionLabel>Sector performance</SectionLabel>
          {indices?.sectors?.length ? <IndexBarChart rows={indices.sectors} testId="md-sector-chart" /> : <CardError />}
        </div>
        <div>
          <SectionLabel>Segment performance</SectionLabel>
          {indices?.segments?.length ? <IndexBarChart rows={indices.segments} testId="md-segment-chart" /> : <CardError />}
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6 mb-8">
        <div>
          <SectionLabel>Advance / decline</SectionLabel>
          {indices ? (
            <AdvanceDeclineDonut advances={indices.market_advances} declines={indices.market_declines} unchanged={indices.market_unchanged} />
          ) : <CardError />}
        </div>
        <div>
          <SectionLabel>52-week highs / lows</SectionLabel>
          {data.week_hilo ? <HiLoStat high={data.week_hilo.high} low={data.week_hilo.low} /> : <CardError reason={errors.week_hilo} />}
        </div>
        <div>
          <SectionLabel>India VIX</SectionLabel>
          <div className={`${SURFACE} p-5`}>
            {indices?.vix ? (
              <>
                <p className="text-2xl font-bold text-white">{fmt(indices.vix.last)}</p>
                <p className={`font-mono-ui text-xs mt-1 ${changeColor(indices.vix.change_pct)}`}>{fmtSigned(indices.vix.change_pct)}%</p>
              </>
            ) : <p className="text-xs font-light text-slate-500">Unavailable.</p>}
          </div>
        </div>
      </div>

      <SectionLabel>Intraday advance / decline</SectionLabel>
      <div className="mb-8">
        {adHistory?.length ? <IntradayAdChart points={adHistory} /> : <CardError reason="Not enough readings yet today — check back later in the session." />}
      </div>

      <SectionLabel>Global indices</SectionLabel>
      <div className="mb-8">
        {data.global_indices?.length ? <GlobalIndicesGrid rows={data.global_indices} /> : <CardError reason={errors.global_indices} />}
      </div>

      <SectionLabel>FII / DII activity (cash market)</SectionLabel>
      {fiiDiiHistory?.length ? <FiiDiiTable rows={fiiDiiHistory} /> : <CardError reason={errors.fii_dii} />}

      <p className="text-[11px] font-light text-slate-600 mt-6 max-w-2xl leading-relaxed">
        Built entirely from free, public NSE and Yahoo Finance data — independent of any broker session. For research and educational purposes only — not investment advice.
      </p>
    </div>
  );
};

export default MarketDashboardTool;
