import { useEffect, useRef, useState } from "react";
import axios from "axios";
import { useParams, Link } from "react-router-dom";
import { createChart, CandlestickSeries, ColorType, LineStyle } from "lightweight-charts";
import {
  ResponsiveContainer, LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip,
} from "recharts";
import { Loader2, Sparkles, ChevronDown } from "lucide-react";
import Navbar from "../../components/site/Navbar";
import Footer from "../../components/site/Footer";
import Disclaimer from "./Disclaimer";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;
const SURFACE = "rounded-2xl border border-white/10 bg-[#0A0D18]";

const fmtNum = (v, dp = 2) => (v == null ? "—" : Number(v).toFixed(dp));
const fmtPct = (v, dp = 2) => (v == null ? "—" : `${v > 0 ? "+" : ""}${Number(v).toFixed(dp)}%`);
const fmtINR = (v) => (v == null ? "—" : `₹${Number(v).toLocaleString("en-IN", { maximumFractionDigits: 2 })}`);
const toneOf = (v) => (v == null ? "text-slate-500" : v > 0 ? "text-emerald-400" : v < 0 ? "text-red-400" : "text-white");

const KpiCard = ({ label, value, tone = "text-white" }) => (
  <div className={`${SURFACE} p-4`}>
    <p className="font-mono-ui text-[9px] uppercase tracking-[0.14em] text-slate-500 mb-1.5">{label}</p>
    <p className={`font-mono-ui text-lg font-bold ${tone}`}>{value}</p>
  </div>
);

const PriceChart = ({ bars, dma50, dma200 }) => {
  const containerRef = useRef(null);
  const chartRef = useRef(null);
  const seriesRef = useRef(null);

  useEffect(() => {
    if (!containerRef.current) return undefined;
    const chart = createChart(containerRef.current, {
      layout: { background: { type: ColorType.Solid, color: "transparent" }, textColor: "#94A3B8" },
      grid: { vertLines: { visible: false }, horzLines: { visible: false } },
      timeScale: { borderColor: "rgba(255,255,255,0.1)" },
      rightPriceScale: { borderColor: "rgba(255,255,255,0.1)" },
      handleScale: { mouseWheel: true, pinch: true, axisPressedMouseMove: { time: true, price: true } },
      handleScroll: { mouseWheel: true, pressedMouseMove: true, horzTouchDrag: true, vertTouchDrag: true },
      autoSize: true,
    });
    const series = chart.addSeries(CandlestickSeries, {
      upColor: "#34D399", downColor: "#F87171", borderVisible: false,
      wickUpColor: "#34D399", wickDownColor: "#F87171",
      priceLineVisible: false, lastValueVisible: false,
    });
    chartRef.current = chart;
    seriesRef.current = series;
    return () => { chart.remove(); chartRef.current = null; seriesRef.current = null; };
  }, []);

  useEffect(() => {
    const series = seriesRef.current, chart = chartRef.current;
    if (!series || !chart || !bars?.length) return;
    series.setData(bars.map((b) => ({ time: b.date, open: b.open, high: b.high, low: b.low, close: b.close })));

    const lines = [];
    if (dma50 != null) lines.push(series.createPriceLine({ price: dma50, color: "#437EEB", lineWidth: 1, lineStyle: LineStyle.Dashed, axisLabelVisible: true, title: "50 DMA" }));
    if (dma200 != null) lines.push(series.createPriceLine({ price: dma200, color: "#D9A441", lineWidth: 1, lineStyle: LineStyle.Dashed, axisLabelVisible: true, title: "200 DMA" }));
    chart.timeScale().fitContent();
    return () => lines.forEach((l) => series.removePriceLine(l));
  }, [bars, dma50, dma200]);

  return <div ref={containerRef} className="h-96" data-testid="facet-price-chart" />;
};

const ShareholdingChart = ({ rows }) => {
  if (!rows?.length) return <p className="text-sm text-slate-500 py-10 text-center">No shareholding history yet.</p>;
  const data = rows.map((r) => ({ quarter: r.quarter, Promoters: r.promoter_pct, FIIs: r.fii_pct, DIIs: r.dii_pct, Public: r.public_pct }));
  return (
    <div className="h-64" data-testid="facet-shareholding-chart">
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={data} margin={{ top: 4, right: 8, left: 0, bottom: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.06)" vertical={false} />
          <XAxis dataKey="quarter" tick={{ fill: "#64748B", fontSize: 10 }} axisLine={{ stroke: "rgba(255,255,255,0.1)" }} tickLine={false} />
          <YAxis tick={{ fill: "#64748B", fontSize: 11 }} axisLine={false} tickLine={false} width={44} tickFormatter={(v) => `${v}%`} />
          <Tooltip
            content={({ active, payload, label }) => (active && payload?.length ? (
              <div className="rounded-lg border border-white/10 bg-[#050710] px-3 py-2.5 text-xs">
                <p className="text-slate-500 mb-1.5 font-mono-ui">{label}</p>
                {payload.map((p) => <p key={p.dataKey} style={{ color: p.color }} className="font-mono-ui">{p.name}: {p.value?.toFixed(2)}%</p>)}
              </div>
            ) : null)}
          />
          <Line type="monotone" dataKey="Promoters" stroke="#437EEB" strokeWidth={2} dot={false} />
          <Line type="monotone" dataKey="FIIs" stroke="#34D399" strokeWidth={2} dot={false} />
          <Line type="monotone" dataKey="DIIs" stroke="#D9A441" strokeWidth={2} dot={false} />
          <Line type="monotone" dataKey="Public" stroke="#94A3B8" strokeWidth={1.5} strokeDasharray="4 3" dot={false} />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
};

const LumenAgentPanel = ({ symbol }) => {
  const [result, setResult] = useState(null);
  const [loading, setLoading] = useState(false);
  const [logsOpen, setLogsOpen] = useState(false);

  const run = async (force = false) => {
    setLoading(true);
    try {
      const { data } = await axios.post(`${API}/stock-terminal/stock/${symbol}/analyze`, null, { params: { force } });
      setResult(data);
    } catch {
      setResult({ configured: true, analysis: "Analysis failed — please try again." });
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className={`${SURFACE} p-6`} data-testid="lumen-agent-panel">
      <div className="flex items-center justify-between flex-wrap gap-3 mb-4">
        <h3 className="font-display text-base font-bold text-white flex items-center gap-2"><Sparkles size={16} className="text-sapphire-light" /> Lumen Agent</h3>
        {!result && (
          <button
            type="button"
            onClick={() => run(false)}
            disabled={loading}
            className="btn-ghost !px-4 !py-2 text-sm disabled:opacity-50"
            data-testid="lumen-agent-run-btn"
          >
            {loading ? <><Loader2 size={14} className="animate-spin" /> Analyzing…</> : "Run Analysis"}
          </button>
        )}
      </div>

      {!result && !loading && (
        <p className="text-sm text-slate-500">
          Lumen Agent researches this stock using only real, sourced data — price history, fundamentals, shareholding, peers, and sector news. Nothing is estimated or guessed.
        </p>
      )}

      {result && !result.configured && (
        <p className="text-sm text-slate-500" data-testid="lumen-agent-not-configured">
          Lumen Agent isn't configured on this deployment yet ({result.reason}).
        </p>
      )}

      {result?.configured && (
        <>
          <p className="text-sm text-slate-300 leading-relaxed whitespace-pre-wrap mb-4" data-testid="lumen-agent-analysis">{result.analysis}</p>
          {result.cached && <p className="text-xs text-slate-600 mb-3">Cached result — <button type="button" onClick={() => run(true)} className="underline hover:text-slate-400">re-run fresh</button>.</p>}
          {result.tool_calls?.length > 0 && (
            <>
              <button type="button" onClick={() => setLogsOpen((o) => !o)} className="flex items-center gap-1.5 text-xs text-slate-500 hover:text-white transition-colors" data-testid="lumen-agent-logs-toggle">
                <ChevronDown size={13} className={`transition-transform ${logsOpen ? "rotate-180" : ""}`} /> {logsOpen ? "Hide" : "Show"} tool calls ({result.tool_calls.length})
              </button>
              {logsOpen && (
                <div className="mt-3 space-y-2">
                  {result.tool_calls.map((t, i) => (
                    <div key={i} className="rounded-lg border border-white/10 bg-white/[0.02] p-3 text-xs font-mono-ui">
                      <p className="text-sapphire-light mb-1">{t.tool}({JSON.stringify(t.input)})</p>
                      <p className="text-slate-500 truncate">{JSON.stringify(t.output).slice(0, 200)}</p>
                    </div>
                  ))}
                </div>
              )}
            </>
          )}
        </>
      )}
    </div>
  );
};

export default function FacetView() {
  const { symbol } = useParams();
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => { window.scrollTo(0, 0); }, [symbol]);

  useEffect(() => {
    setLoading(true);
    axios.get(`${API}/stock-terminal/stock/${symbol}`)
      .then((r) => setData(r.data))
      .catch(() => setData({ has_data: false }))
      .finally(() => setLoading(false));
  }, [symbol]);

  if (loading) {
    return (
      <>
        <Navbar />
        <main className="bg-void min-h-screen flex items-center justify-center text-slate-500 font-mono-ui text-sm gap-3">
          <Loader2 className="animate-spin" size={16} /> Loading…
        </main>
        <Footer />
      </>
    );
  }

  if (!data?.has_data) {
    return (
      <>
        <Navbar />
        <main className="bg-void min-h-screen flex flex-col items-center justify-center text-center px-6" data-testid="facet-not-found">
          <p className="font-mono-ui text-[11px] uppercase tracking-[0.28em] text-slate-600 mb-3">Not Found</p>
          <p className="text-slate-400 mb-6 max-w-sm">"{symbol}" isn't in our research universe yet.</p>
          <Link to="/research" className="btn-sapphire">Back to Aurora</Link>
        </main>
        <Footer />
      </>
    );
  }

  const { symbol_master: m, computed_metrics: cm, fundamentals: f, shareholding, price_bars } = data;
  const latest = price_bars?.[price_bars.length - 1];

  return (
    <>
      <Navbar />
      <main className="relative bg-void min-h-screen pt-28 pb-24">
        <div className="container-x">
          <p className="font-mono-ui text-xs text-slate-500 mb-2">
            <Link to="/research" className="hover:text-white transition-colors">Aurora</Link> <span className="mx-1">›</span> Facet View
          </p>
          <div className="flex items-baseline gap-3 flex-wrap mb-1">
            <h1 className="font-display text-4xl md:text-5xl font-bold text-white tracking-tight">{m.symbol}</h1>
            <span className="font-mono-ui text-2xl text-slate-300">{fmtINR(latest?.close)}</span>
            {cm?.return_1d != null && <span className={`font-mono-ui text-sm ${toneOf(cm.return_1d)}`}>{fmtPct(cm.return_1d)}</span>}
          </div>
          <p className="text-slate-500 mb-10">{m.company_name}{m.industry ? ` · ${m.industry}` : ""}</p>

          <div className={`${SURFACE} p-4 mb-8`}>
            <PriceChart bars={price_bars} dma50={cm?.dma_50} dma200={cm?.dma_200} />
          </div>

          <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-10">
            <KpiCard label="ATH" value={fmtINR(cm?.ath)} />
            <KpiCard label="% From ATH" value={fmtPct(cm?.pct_from_ath)} tone={toneOf(cm?.pct_from_ath)} />
            <KpiCard label="1M Return" value={fmtPct(cm?.return_1m)} tone={toneOf(cm?.return_1m)} />
            <KpiCard label="1Y Return" value={fmtPct(cm?.return_1y)} tone={toneOf(cm?.return_1y)} />
          </div>

          <div className="grid grid-cols-1 lg:grid-cols-2 gap-8 mb-10">
            <div className={`${SURFACE} p-6`}>
              <h3 className="font-display text-base font-bold text-white mb-4">Fundamentals</h3>
              {!f ? (
                <p className="text-sm text-slate-500">Not yet ingested for this symbol.</p>
              ) : (
                <div className="grid grid-cols-2 gap-3">
                  <KpiCard label="P/E" value={fmtNum(f.pe_ratio)} />
                  <KpiCard label="P/B" value={fmtNum(f.pb_ratio)} />
                  <KpiCard label="ROE" value={f.roe != null ? `${fmtNum(f.roe)}%` : "—"} />
                  <KpiCard label="ROCE" value={f.roce != null ? `${fmtNum(f.roce)}%` : "—"} />
                  <KpiCard label="Debt/Equity" value={fmtNum(f.debt_to_equity)} />
                  <KpiCard label="EPS" value={fmtINR(f.eps)} />
                  <KpiCard label="OPM" value={f.opm != null ? `${fmtNum(f.opm)}%` : "—"} />
                  <KpiCard label="NPM" value={f.npm != null ? `${fmtNum(f.npm)}%` : "—"} />
                  <KpiCard label="Sales CAGR (3Y)" value={f.sales_cagr_3y != null ? `${fmtNum(f.sales_cagr_3y)}%` : "—"} />
                  <KpiCard label="Profit CAGR (3Y)" value={f.profit_cagr_3y != null ? `${fmtNum(f.profit_cagr_3y)}%` : "—"} />
                  <KpiCard label="Interest Coverage" value={fmtNum(f.interest_coverage)} />
                  <KpiCard label="Div Yield" value={f.dividend_yield != null ? `${fmtNum(f.dividend_yield)}%` : "—"} />
                </div>
              )}
            </div>
            <div className={`${SURFACE} p-6`}>
              <h3 className="font-display text-base font-bold text-white mb-4">Shareholding Pattern</h3>
              <ShareholdingChart rows={shareholding} />
            </div>
          </div>

          <div className="mb-10">
            <LumenAgentPanel symbol={m.symbol} />
          </div>

          <Disclaimer />
        </div>
      </main>
      <Footer />
    </>
  );
}
