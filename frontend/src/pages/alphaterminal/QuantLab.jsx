import { Link } from "react-router-dom";
import ParticleField from "../../components/site/ParticleField";
import LivePulseDot from "../../components/site/LivePulseDot";
import { ComingSoonCard } from "../AlphaTerminal";

const TOOLS = [
  { key: "ewma", title: "EWMA Crossover", description: "Fast/slow EWMA crossover backtest vs. buy-and-hold, on any NSE/BSE/NFO/BFO symbol.", active: true, path: "/alpha-terminal/ewma-crossover" },
  { key: "sharpe", title: "Sharpe Dashboard", description: "Sharpe, Sortino, and max drawdown across the Nifty 500 — compare picks or view the top ranked.", active: true, path: "/alpha-terminal/sharpe-dashboard" },
  { key: "montecarlo", title: "Monte Carlo Simulator", description: "Forward-simulate equity paths from a strategy's historical return distribution.", active: false },
  { key: "pairs", title: "Pairs Bot", description: "Cointegration-based pairs trading scanner with spread z-score signals.", active: false },
  { key: "frontier", title: "Efficient Frontier", description: "Mean-variance optimal portfolio construction across a chosen basket.", active: false },
];

export const field = "w-full bg-white/5 border border-white/10 rounded-md px-3 py-2 text-sm text-white outline-none focus:border-sapphire-light transition-colors";
export const selectCls = field + " [color-scheme:dark]";
export const label = "font-mono-ui text-[10px] uppercase tracking-[0.18em] text-slate-500 block mb-1.5";

export const StatCard = ({ label: l, value, Icon, tone = "text-white" }) => (
  <div className="glass rounded-2xl p-5">
    <div className="flex items-center gap-2 mb-2">
      <Icon size={14} className="text-sapphire-light" />
      <p className="font-mono-ui text-[10px] uppercase tracking-[0.18em] text-slate-500">{l}</p>
    </div>
    <p className={`font-mono-ui text-3xl font-bold tracking-tight ${tone}`}>{value}</p>
  </div>
);

export const fmtPct = (v) => `${Number(v) >= 0 ? "+" : ""}${(Number(v) * 100).toFixed(2)}%`;

export const LoadingParticles = ({ title = "Running Backtest", subtitle = "Fetching history · Computing signals · Scoring returns" }) => (
  <div className="relative glass rounded-2xl border border-white/10 h-64 overflow-hidden flex flex-col items-center justify-center" data-testid="quant-lab-loading">
    <ParticleField density={0.00012} />
    <div className="absolute inset-0 radial-glow pointer-events-none" />
    <div className="relative z-10 flex flex-col items-center gap-3">
      <span className="relative flex h-3 w-3">
        <span className="absolute inline-flex h-full w-full rounded-full bg-sapphire-light opacity-75 animate-ping" />
        <span className="relative inline-flex h-3 w-3 rounded-full bg-sapphire-light" />
      </span>
      <p className="font-mono-ui text-xs uppercase tracking-[0.24em] text-slate-300">{title}</p>
      <p className="font-mono-ui text-[10px] uppercase tracking-[0.18em] text-slate-600">{subtitle}</p>
    </div>
  </div>
);

export const EmptyState = ({ reason }) => (
  <div className="glass rounded-2xl border border-white/10 p-10 text-center" data-testid="quant-lab-empty">
    <p className="font-mono-ui text-[10px] uppercase tracking-[0.24em] text-slate-500 mb-3">No Result Found</p>
    <p className="text-sm text-slate-400 leading-relaxed max-w-md mx-auto">{reason}</p>
  </div>
);

const ToolCard = ({ tool }) => {
  if (!tool.active) return <ComingSoonCard scannerKey={tool.key} />;
  return (
    <Link
      to={tool.path}
      className="group relative block text-left glass rounded-2xl border border-white/10 p-5 md:p-6 transition-all duration-300 hover:border-sapphire/40 hover:bg-sapphire/[0.03] hover:shadow-[0_0_30px_rgba(31,95,208,0.15)] cursor-pointer"
      data-testid={`quant-tool-${tool.key}`}
    >
      <span className="inline-flex items-center gap-1.5 font-mono-ui text-[10px] uppercase tracking-[0.24em] text-sapphire-light mb-3">
        <LivePulseDot color="bg-sapphire-light" size="h-1.5 w-1.5" /> Available
      </span>
      <h4 className="font-display text-lg font-bold text-white mb-2">{tool.title}</h4>
      <p className="text-sm font-light text-slate-500 leading-relaxed">{tool.description}</p>
    </Link>
  );
};

export default function QuantLab() {
  return (
    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4" data-testid="quant-lab">
      {TOOLS.map((tool) => <ToolCard key={tool.key} tool={tool} />)}
    </div>
  );
}
