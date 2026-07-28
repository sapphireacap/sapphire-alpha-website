import { useEffect, useState, lazy, Suspense } from "react";
import axios from "axios";
import { useNavigate } from "react-router-dom";
import { motion } from "framer-motion";
import { Search, Loader2, TrendingUp, TrendingDown, Volume2, VolumeX } from "lucide-react";
import Navbar from "../../components/site/Navbar";
import Footer from "../../components/site/Footer";
import ParticleField from "../../components/site/ParticleField";
import Disclaimer from "./Disclaimer";
import { startAmbientDrone, stopAmbientDrone } from "../../components/research/ambientAudio";

// three.js is a large dependency (~130kB gzipped) used only by this one
// component -- lazy-loaded so it's a separate chunk that only downloads
// when a visitor actually lands on Aurora, not part of every page's
// initial bundle (this app doesn't route-split otherwise, so isolating
// just the heavy import here is the contained fix).
const MarketCore = lazy(() => import("../../components/research/MarketCore"));

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;
const EASE = [0.16, 1, 0.3, 1];
const SURFACE = "rounded-2xl border border-white/10 bg-[#0A0D18]";

const fmtPct = (v) => (v == null ? "—" : `${v > 0 ? "+" : ""}${v.toFixed(2)}%`);

const SymbolSearch = () => {
  const [q, setQ] = useState("");
  const [results, setResults] = useState([]);
  const navigate = useNavigate();

  useEffect(() => {
    if (q.trim().length < 1) {
      setResults([]);
      return;
    }
    const id = setTimeout(() => {
      axios.get(`${API}/stock-terminal/symbols/search`, { params: { q } })
        .then((r) => setResults(r.data))
        .catch(() => setResults([]));
    }, 250);
    return () => clearTimeout(id);
  }, [q]);

  return (
    <div className="relative max-w-xl" data-testid="aurora-symbol-search">
      <div className="relative">
        <Search size={16} className="absolute left-4 top-1/2 -translate-y-1/2 text-slate-500" />
        <input
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="Search a stock — e.g. RELIANCE, TCS…"
          className="w-full rounded-xl border border-white/10 bg-white/[0.02] pl-11 pr-4 py-3.5 text-sm text-white placeholder:text-slate-600 focus:outline-none focus:border-sapphire-light/40"
          data-testid="aurora-search-input"
        />
      </div>
      {results.length > 0 && (
        <div className={`${SURFACE} absolute z-20 mt-2 w-full overflow-hidden`} data-testid="aurora-search-results">
          {results.map((r) => (
            <button
              key={r.symbol}
              type="button"
              onClick={() => navigate(`/research/${r.symbol}`)}
              className="w-full text-left px-4 py-3 hover:bg-white/[0.04] transition-colors border-b border-white/[0.05] last:border-0"
              data-testid={`aurora-search-result-${r.symbol}`}
            >
              <span className="font-display font-bold text-white">{r.symbol}</span>
              <span className="ml-2 text-sm text-slate-500">{r.company_name}</span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
};

const MoverRow = ({ row, tone }) => (
  <div className="flex items-center justify-between px-5 py-3 border-b border-white/[0.05] last:border-0">
    <div>
      <p className="font-display font-bold text-white">{row.symbol}</p>
      <p className="text-xs text-slate-500">{row.company_name || "—"}</p>
    </div>
    <span className={`font-mono-ui text-sm font-semibold ${tone === "up" ? "text-emerald-400" : "text-red-400"}`}>
      {fmtPct(row.return_1d)}
    </span>
  </div>
);

const BreadthGauge = ({ pct, counted }) => {
  const tone = pct == null ? "text-slate-400" : pct >= 50 ? "text-emerald-400" : "text-red-400";
  return (
    <div className={`${SURFACE} p-6 text-center`} data-testid="aurora-breadth">
      <p className="font-mono-ui text-[10px] uppercase tracking-[0.24em] text-slate-500 mb-3">Market Breadth</p>
      <p className={`font-display text-5xl font-black ${tone}`}>{pct == null ? "—" : `${pct.toFixed(0)}%`}</p>
      <p className="text-xs text-slate-500 mt-2">{counted ?? 0} stocks counted, of the Nifty 500</p>
    </div>
  );
};

const AmbientToggle = () => {
  const [on, setOn] = useState(false);
  const toggle = () => {
    if (on) stopAmbientDrone(); else startAmbientDrone();
    setOn((o) => !o);
  };
  return (
    <button
      type="button"
      onClick={toggle}
      className="inline-flex items-center gap-2 rounded-full border border-white/15 px-4 py-2 text-xs font-medium text-slate-300 hover:text-white hover:border-white/30 transition-colors"
      data-testid="aurora-ambient-toggle"
    >
      {on ? <Volume2 size={13} /> : <VolumeX size={13} />} Ambient {on ? "On" : "Off"}
    </button>
  );
};

export default function Aurora() {
  useEffect(() => { window.scrollTo(0, 0); }, []);
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    axios.get(`${API}/stock-terminal/market-pulse`)
      .then((r) => setData(r.data))
      .catch(() => setData({ has_data: false }))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => () => stopAmbientDrone(), []); // stop the drone if the user navigates away with it on

  return (
    <>
      <Navbar />
      <main className="relative bg-void min-h-screen">
        <section className="relative pt-28 pb-14 md:pt-36 md:pb-20 overflow-hidden" data-testid="aurora-hero">
          <ParticleField density={0.00006} />
          <div className="absolute inset-0 radial-glow" />
          <div className="absolute inset-0 bg-gradient-to-b from-void/0 to-void pointer-events-none" />
          <div className="container-x relative z-10 grid grid-cols-1 lg:grid-cols-2 gap-10 items-center">
            <div>
              <motion.h1
                initial={{ opacity: 0, y: 24 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.9, ease: EASE }}
                className="font-display text-4xl md:text-6xl font-bold text-white tracking-tight mb-4"
              >
                Aurora
              </motion.h1>
              <p className="text-slate-400 max-w-xl mb-6">
                A live pulse on the market — breadth, movers, and a way into Facet View, our systematic per-stock research page.
              </p>
              <div className="flex items-center gap-3 flex-wrap mb-6">
                <SymbolSearch />
                <AmbientToggle />
              </div>
            </div>
            <div className="h-72 md:h-96" data-testid="aurora-geode-wrap">
              <Suspense fallback={null}>
                <MarketCore breadthPct={data?.breadth_pct} className="w-full h-full" />
              </Suspense>
            </div>
          </div>
        </section>

        <section className="container-x pb-24">
          {loading ? (
            <div className="flex items-center justify-center py-16 text-slate-500 font-mono-ui text-sm gap-3">
              <Loader2 className="animate-spin" size={16} /> Loading…
            </div>
          ) : !data?.has_data ? (
            <div className={`${SURFACE} border-dashed px-6 py-14 text-center`} data-testid="aurora-empty">
              <p className="text-sm font-light text-slate-500 max-w-md mx-auto">
                No market data has been ingested yet — check back after the next scheduled refresh.
              </p>
            </div>
          ) : (
            <>
              <p className="font-mono-ui text-[11px] text-slate-500 mb-6">
                {data.universe_size} stocks tracked · updated {data.updated_at ? new Date(data.updated_at).toLocaleString("en-IN") : "—"}
              </p>
              <div className="grid grid-cols-1 md:grid-cols-3 gap-6 mb-10">
                <BreadthGauge pct={data.breadth_pct} counted={data.breadth_counted} />
                <div className={`${SURFACE} overflow-hidden`}>
                  <p className="font-mono-ui text-[10px] uppercase tracking-[0.18em] text-slate-500 px-5 pt-5 pb-2 flex items-center gap-1.5">
                    <TrendingUp size={12} className="text-emerald-400" /> Top Gainers
                  </p>
                  {data.gainers.map((r) => <MoverRow key={r.symbol} row={r} tone="up" />)}
                </div>
                <div className={`${SURFACE} overflow-hidden`}>
                  <p className="font-mono-ui text-[10px] uppercase tracking-[0.18em] text-slate-500 px-5 pt-5 pb-2 flex items-center gap-1.5">
                    <TrendingDown size={12} className="text-red-400" /> Top Losers
                  </p>
                  {data.losers.map((r) => <MoverRow key={r.symbol} row={r} tone="down" />)}
                </div>
              </div>
            </>
          )}
          <Disclaimer />
        </section>
      </main>
      <Footer />
    </>
  );
}
