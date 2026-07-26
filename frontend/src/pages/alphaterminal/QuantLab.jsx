import { Link } from "react-router-dom";
import { ArrowUpRight } from "lucide-react";
import ParticleField from "../../components/site/ParticleField";
import LivePulseDot from "../../components/site/LivePulseDot";

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

// Dense software-module list, not marketing cards — a status dot, the
// engine name, its system state, and a Launch action for anything active.
const ToolRow = ({ tool }) => {
  const content = (
    <>
      <span className="flex items-center gap-3.5 min-w-0">
        <span className={`inline-block h-2 w-2 rounded-full shrink-0 ${tool.active ? "bg-emerald-400" : "bg-slate-600"}`}>
          {tool.active && <LivePulseDot color="bg-emerald-400" size="h-2 w-2" />}
        </span>
        <span className="min-w-0">
          <span className="block font-display text-sm md:text-base font-bold text-white tracking-tight truncate">{tool.title}</span>
          <span className="hidden sm:block text-xs font-light text-slate-500 truncate">{tool.description}</span>
        </span>
      </span>
      <span className="flex items-center gap-4 shrink-0">
        {tool.active ? (
          <span className="font-mono-ui text-[10px] uppercase tracking-wider text-emerald-300">Operational</span>
        ) : (
          <span className="font-mono-ui text-[10px] uppercase tracking-wider text-slate-500">Calibration in Progress</span>
        )}
        {tool.active && (
          <span className="inline-flex items-center gap-1 font-mono-ui text-[10px] uppercase tracking-wider text-sapphire-light">
            Launch <ArrowUpRight size={11} />
          </span>
        )}
      </span>
    </>
  );

  const rowCls = "group flex items-center justify-between gap-4 px-5 py-4 transition-colors duration-300";

  if (!tool.active) {
    return (
      <div className={`${rowCls} opacity-50`} data-testid={`quant-tool-${tool.key}`}>
        {content}
      </div>
    );
  }
  return (
    <Link to={tool.path} className={`${rowCls} hover:bg-sapphire/[0.06] cursor-pointer`} data-testid={`quant-tool-${tool.key}`}>
      {content}
    </Link>
  );
};

export default function QuantLab() {
  return (
    <div className="glass rounded-2xl border border-white/10 divide-y divide-white/[0.06] overflow-hidden" data-testid="quant-lab">
      {TOOLS.map((tool) => <ToolRow key={tool.key} tool={tool} />)}
    </div>
  );
}
