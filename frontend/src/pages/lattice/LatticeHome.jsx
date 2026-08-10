import { useEffect, useState } from "react";
import axios from "axios";
import { useNavigate } from "react-router-dom";
import { motion } from "framer-motion";
import { Search, Loader2 } from "lucide-react";
import Navbar from "../../components/site/Navbar";
import Footer from "../../components/site/Footer";
import ParticleField from "../../components/site/ParticleField";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;
const EASE = [0.16, 1, 0.3, 1];
const SURFACE = "rounded-2xl border border-white/10 bg-[#0A0D18]";

const DISCLAIMER =
  "Every decision here is a simulated (paper) trade for research and education purposes only — no real capital is deployed, and nothing here is investment advice. Sapphire Alpha Capital does not manage client capital or execute trades on behalf of any third party through this platform.";

const fmtINR = (v) => (v == null ? "—" : `₹${Math.round(v).toLocaleString("en-IN")}`);
const fmtPct = (v) => (v == null ? "—" : `${v > 0 ? "+" : ""}${v.toFixed(2)}%`);

const SymbolSearch = () => {
  const [q, setQ] = useState("");
  const [results, setResults] = useState([]);
  const navigate = useNavigate();

  useEffect(() => {
    if (q.trim().length < 1) { setResults([]); return; }
    const id = setTimeout(() => {
      axios.get(`${API}/stock-terminal/symbols/search`, { params: { q } })
        .then((r) => setResults(r.data))
        .catch(() => setResults([]));
    }, 250);
    return () => clearTimeout(id);
  }, [q]);

  return (
    <div className="relative max-w-xl" data-testid="lattice-symbol-search">
      <div className="relative">
        <Search size={16} className="absolute left-4 top-1/2 -translate-y-1/2 text-slate-500" />
        <input
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="Run the pipeline on a stock — e.g. RELIANCE, TCS…"
          className="w-full rounded-xl border border-white/10 bg-white/[0.02] pl-11 pr-4 py-3.5 text-sm text-white placeholder:text-slate-600 focus:outline-none focus:border-sapphire-light/40"
          data-testid="lattice-search-input"
        />
      </div>
      {results.length > 0 && (
        <div className={`${SURFACE} absolute z-20 mt-2 w-full overflow-hidden`} data-testid="lattice-search-results">
          {results.map((r) => (
            <button
              key={r.symbol}
              type="button"
              onClick={() => navigate(`/lattice/${r.symbol}`)}
              className="w-full text-left px-4 py-3 hover:bg-white/[0.04] transition-colors border-b border-white/[0.05] last:border-0"
              data-testid={`lattice-search-result-${r.symbol}`}
            >
              <span className="font-bold text-white">{r.symbol}</span>
              <span className="ml-2 text-sm text-slate-500">{r.company_name}</span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
};

const StatTile = ({ label, value, tone = "text-white" }) => (
  <div className={`${SURFACE} p-4 text-center`}>
    <p className="font-mono-ui text-[10px] uppercase tracking-[0.16em] text-slate-500 mb-1.5">{label}</p>
    <p className={`font-mono-ui text-xl font-bold ${tone}`}>{value}</p>
  </div>
);

const PositionRow = ({ p, onClick }) => {
  const pnl = p.status === "open" ? p.unrealized_pnl_pct : p.realized_pnl_pct;
  const tone = pnl == null ? "text-slate-400" : pnl >= 0 ? "text-emerald-400" : "text-red-400";
  return (
    <button
      type="button"
      onClick={onClick}
      className="w-full flex items-center justify-between px-5 py-3.5 border-b border-white/[0.05] last:border-0 hover:bg-white/[0.03] transition-colors text-left"
      data-testid={`lattice-position-${p.id}`}
    >
      <div>
        <p className="font-bold text-white">{p.symbol}</p>
        <p className="text-xs text-slate-500">
          {p.status === "open" ? `Entry ${fmtINR(p.entry_price)}` : `${p.exit_reason} · exited ${p.exit_date}`}
        </p>
      </div>
      <span className={`font-mono-ui text-sm font-semibold ${tone}`}>{fmtPct(pnl)}</span>
    </button>
  );
};

export default function LatticeHome() {
  const navigate = useNavigate();
  const [portfolio, setPortfolio] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => { window.scrollTo(0, 0); }, []);

  useEffect(() => {
    axios.get(`${API}/lattice/portfolio`)
      .then((r) => setPortfolio(r.data))
      .catch(() => setPortfolio(null))
      .finally(() => setLoading(false));
  }, []);

  return (
    <>
      <Navbar />
      <main className="relative bg-void min-h-screen">
        <section className="relative pt-28 pb-14 md:pt-36 md:pb-16 overflow-hidden" data-testid="lattice-hero">
          <ParticleField density={0.00006} />
          <div className="absolute inset-0 radial-glow" />
          <div className="absolute inset-0 bg-gradient-to-b from-void/0 to-void pointer-events-none" />
          <div className="container-x relative z-10">
            <motion.h1
              initial={{ opacity: 0, y: 24 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.9, ease: EASE }}
              className="font-display font-normal tracking-[-0.015em] text-white text-5xl md:text-7xl leading-[0.95]"
            >
              Lattice
            </motion.h1>
            <p className="mt-6 text-base md:text-lg font-light text-slate-400 leading-relaxed max-w-2xl">
              Systematic calls on NSE stocks, made the same way every time. No discretion, no live orders. Every
              position is paper only, tracked in one simulated portfolio, with the reasoning written down before
              the outcome is known.
            </p>
            <div className="mt-8"><SymbolSearch /></div>
          </div>
        </section>

        <section className="container-x pb-24 md:pb-32">
          {loading ? (
            <div className="flex items-center justify-center py-16 text-slate-500 font-mono-ui text-sm gap-3">
              <Loader2 className="animate-spin" size={16} /> Loading portfolio…
            </div>
          ) : !portfolio ? (
            <div className={`${SURFACE} border-dashed px-6 py-14 text-center`} data-testid="lattice-portfolio-empty">
              <p className="text-sm font-light text-slate-500 max-w-md mx-auto">Could not load the paper portfolio right now — try again shortly.</p>
            </div>
          ) : (
            <>
              <p className="font-mono-ui text-[11px] uppercase tracking-[0.16em] text-slate-500 mb-4">Paper Portfolio</p>
              <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-10">
                <StatTile label="Total Value" value={fmtINR(portfolio.total_value)} />
                <StatTile label="Cash" value={fmtINR(portfolio.cash)} />
                <StatTile label="Realized P&L" value={fmtINR(portfolio.realized_pnl_rupees)} tone={portfolio.realized_pnl_rupees >= 0 ? "text-emerald-400" : "text-red-400"} />
                <StatTile label="Win Rate" value={portfolio.win_rate == null ? "—" : `${(portfolio.win_rate * 100).toFixed(0)}%`} />
              </div>

              <p className="font-mono-ui text-[11px] uppercase tracking-[0.16em] text-slate-500 mb-3">
                Open Positions ({portfolio.open_positions.length})
              </p>
              <div className={`${SURFACE} overflow-hidden mb-10`}>
                {portfolio.open_positions.length === 0 ? (
                  <p className="text-sm text-slate-500 px-5 py-8 text-center">No open positions right now.</p>
                ) : (
                  portfolio.open_positions.map((p) => <PositionRow key={p.id} p={p} onClick={() => navigate(`/lattice/${p.symbol}`)} />)
                )}
              </div>

              <p className="font-mono-ui text-[11px] uppercase tracking-[0.16em] text-slate-500 mb-3">
                Recent Closed ({portfolio.total_closed})
              </p>
              <div className={`${SURFACE} overflow-hidden`}>
                {portfolio.closed_positions.length === 0 ? (
                  <p className="text-sm text-slate-500 px-5 py-8 text-center">No closed positions yet.</p>
                ) : (
                  portfolio.closed_positions.slice(0, 20).map((p) => <PositionRow key={p.id} p={p} onClick={() => navigate(`/lattice/${p.symbol}`)} />)
                )}
              </div>
            </>
          )}

          <p className="text-xs font-light text-slate-500 leading-relaxed max-w-3xl mx-auto text-center mt-10">{DISCLAIMER}</p>
        </section>
      </main>
      <Footer />
    </>
  );
}
