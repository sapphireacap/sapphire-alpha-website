import { useState } from "react";
import axios from "axios";
import { Link, useParams, useNavigate } from "react-router-dom";
import { motion } from "framer-motion";
import { ArrowLeft, ChevronRight, Loader2, Sparkles, Swords, Hammer, ShieldCheck, Vault as VaultIcon } from "lucide-react";
import Navbar from "../../components/site/Navbar";
import Footer from "../../components/site/Footer";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;
const EASE = [0.16, 1, 0.3, 1];
const SURFACE = "rounded-2xl border border-white/10 bg-[#0A0D18]";

const fmtINR = (v) => (v == null ? "—" : `₹${Math.round(v).toLocaleString("en-IN")}`);

const ACTION_TONE = {
  BUY: "text-emerald-400 border-emerald-400/30 bg-emerald-400/10",
  SELL: "text-red-400 border-red-400/30 bg-red-400/10",
  HOLD: "text-slate-300 border-white/15 bg-white/5",
  REJECTED: "text-amber-300 border-amber-400/30 bg-amber-400/10",
  APPROVE: "text-emerald-400 border-emerald-400/30 bg-emerald-400/10",
  ADJUST: "text-amber-300 border-amber-400/30 bg-amber-400/10",
  REJECT: "text-red-400 border-red-400/30 bg-red-400/10",
};

const Section = ({ no, title, icon: Icon, children }) => (
  <motion.section
    initial={{ opacity: 0, y: 16 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.6, ease: EASE }}
    className="py-8 border-t border-white/[0.06]"
  >
    <div className="flex items-center gap-3 mb-5">
      <span className="font-mono-ui text-xs text-sapphire-light">{no}</span>
      {Icon && <Icon size={16} className="text-sapphire-light" />}
      <h2 className="text-xl font-bold text-white tracking-tight">{title}</h2>
    </div>
    {children}
  </motion.section>
);

const ActionCard = ({ label, verdict, reasoning, extra }) => (
  <div className={`${SURFACE} p-5`}>
    <div className="flex items-center justify-between gap-3 mb-3">
      <span className="font-mono-ui text-[10px] uppercase tracking-wider text-slate-500">{label}</span>
      <span className={`rounded-full border px-3 py-1 font-mono-ui text-[10px] uppercase tracking-wider ${ACTION_TONE[verdict] || ACTION_TONE.HOLD}`}>
        {verdict}
      </span>
    </div>
    <p className="text-sm text-slate-300 leading-relaxed">{reasoning}</p>
    {extra && <p className="text-xs text-slate-500 mt-2 font-mono-ui">{extra}</p>}
  </div>
);

export default function LatticeRun() {
  const { symbol } = useParams();
  const navigate = useNavigate();
  const [result, setResult] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const run = async () => {
    setLoading(true);
    setError(null);
    try {
      const { data } = await axios.post(`${API}/lattice/run/${symbol}`);
      setResult(data);
    } catch (err) {
      setError(err?.response?.data?.detail || "Pipeline run failed — please try again.");
    } finally {
      setLoading(false);
    }
  };

  const bullRounds = result?.crucible?.transcript?.filter((t) => t.persona === "BULL") || [];
  const bearRounds = result?.crucible?.transcript?.filter((t) => t.persona === "BEAR") || [];

  return (
    <>
      <Navbar />
      <main className="relative bg-void min-h-screen">
        <section className="relative pt-28 pb-10 md:pt-32 md:pb-14">
          <div className="container-x">
            <Link to="/lattice" className="inline-flex items-center gap-2 text-sm text-slate-400 hover:text-white transition-colors mb-8">
              <ArrowLeft size={15} /> Back
            </Link>
            <p className="flex items-center gap-2 font-mono-ui text-xs text-slate-500 mb-4">
              <Link to="/lattice" className="hover:text-white transition-colors">Lattice</Link>
              <ChevronRight size={12} />
              <span className="text-slate-300">{symbol}</span>
            </p>
            <div className="flex flex-wrap items-center justify-between gap-4">
              <h1 className="font-display font-normal tracking-[-0.015em] text-white text-4xl md:text-5xl leading-[0.95]">{symbol}</h1>
              <button
                onClick={run} disabled={loading}
                className="btn-sapphire disabled:opacity-70"
                data-testid="lattice-run-btn"
              >
                {loading ? <><Loader2 size={16} className="animate-spin" /> Running Pipeline</> : "Run Pipeline"}
              </button>
            </div>
          </div>
        </section>

        <div className="container-x pb-24">
          {error && (
            <div className={`${SURFACE} border-dashed px-6 py-10 text-center mb-8`}>
              <p className="text-sm font-light text-slate-500">{error}</p>
            </div>
          )}

          {!result && !loading && !error && (
            <div className={`${SURFACE} border-dashed px-6 py-16 text-center`}>
              <p className="text-sm font-light text-slate-500 max-w-md mx-auto">
                Hit "Run Pipeline" to chain Lumen Agent, The Crucible, The Forge, The Temper, and The Vault for {symbol}
                — the full trail renders here once it completes.
              </p>
            </div>
          )}

          {result && (
            <>
              <Section no="01" title="Lumen Agent" icon={Sparkles}>
                {!result.lumen_agent.configured ? (
                  <p className="text-sm text-slate-500">Not configured on this deployment ({result.lumen_agent.reason}).</p>
                ) : (
                  <div className={`${SURFACE} p-5`}>
                    <p className="text-sm text-slate-300 leading-relaxed whitespace-pre-wrap">{result.lumen_agent.analysis}</p>
                  </div>
                )}
              </Section>

              <Section no="02" title="Clarity Score & Fracture Scan">
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                  <div className={`${SURFACE} p-5 text-center`}>
                    <p className="font-mono-ui text-[10px] uppercase tracking-wider text-slate-500 mb-2">Clarity Score</p>
                    <p className="font-display text-3xl font-normal text-white">{result.clarity_score.final_score?.toFixed(1) ?? "—"}<span className="text-slate-600 text-lg">/10</span></p>
                  </div>
                  <div className={`${SURFACE} p-5`}>
                    <p className="font-mono-ui text-[10px] uppercase tracking-wider text-slate-500 mb-2">Fracture Scan</p>
                    <div className="flex flex-wrap gap-2">
                      {result.red_flags.map((r) => (
                        <span
                          key={r.rule}
                          className={`rounded-full border px-2.5 py-1 font-mono-ui text-[10px] ${
                            r.status === "FAIL" ? "border-red-400/30 text-red-300 bg-red-400/10"
                              : r.status === "WARN" ? "border-amber-400/30 text-amber-300 bg-amber-400/10"
                              : r.status === "PASS" ? "border-emerald-400/30 text-emerald-300 bg-emerald-400/10"
                              : "border-white/15 text-slate-500 bg-white/5"
                          }`}
                        >
                          {r.rule}: {r.status}
                        </span>
                      ))}
                    </div>
                  </div>
                </div>
              </Section>

              <Section no="03" title="The Crucible" icon={Swords}>
                {!result.crucible.configured ? (
                  <p className="text-sm text-slate-500">Not configured on this deployment ({result.crucible.reason}).</p>
                ) : (
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                    <div>
                      <p className="font-mono-ui text-[10px] uppercase tracking-wider text-emerald-400 mb-2">Bull Case</p>
                      <div className="space-y-2">
                        {bullRounds.map((t) => (
                          <div key={t.round} className="rounded-lg border border-emerald-400/20 bg-emerald-400/5 p-3 text-sm text-slate-300">{t.text}</div>
                        ))}
                      </div>
                    </div>
                    <div>
                      <p className="font-mono-ui text-[10px] uppercase tracking-wider text-red-400 mb-2">Bear Case</p>
                      <div className="space-y-2">
                        {bearRounds.map((t) => (
                          <div key={t.round} className="rounded-lg border border-red-400/20 bg-red-400/5 p-3 text-sm text-slate-300">{t.text}</div>
                        ))}
                      </div>
                    </div>
                  </div>
                )}
              </Section>

              <Section no="04" title="The Forge" icon={Hammer}>
                {!result.forge.configured ? (
                  <p className="text-sm text-slate-500">Not configured on this deployment ({result.forge.reason}).</p>
                ) : (
                  <ActionCard
                    label="Proposal" verdict={result.forge.decision.action} reasoning={result.forge.decision.reasoning}
                    extra={result.forge.decision.action !== "HOLD"
                      ? `${result.forge.decision.position_size_pct}% size · SL ${result.forge.decision.stop_loss_pct ?? "—"}% · Target ${result.forge.decision.target_pct ?? "—"}% · ${result.forge.decision.holding_horizon_days ?? "—"}d horizon`
                      : null}
                  />
                )}
              </Section>

              <Section no="05" title="The Temper" icon={ShieldCheck}>
                <ActionCard
                  label="Risk Verdict" verdict={result.temper.verdict.verdict} reasoning={result.temper.verdict.reasoning}
                  extra={result.temper.verdict.adjusted_position_size_pct != null ? `Adjusted to ${result.temper.verdict.adjusted_position_size_pct}%` : null}
                />
              </Section>

              <Section no="06" title="The Vault" icon={VaultIcon}>
                <ActionCard
                  label="Final Decision" verdict={result.vault.decision.final_action} reasoning={result.vault.decision.reasoning}
                  extra={result.vault.decision.final_position_size_pct != null ? `${result.vault.decision.final_position_size_pct}% of paper capital` : null}
                />
                {result.position_result && (
                  <p className="text-xs text-slate-500 mt-4 font-mono-ui">
                    {result.position_result.opened === false && `Position not opened: ${result.position_result.reason}`}
                    {result.position_result.opened === true && `Position opened at ${fmtINR(result.position_result.position.entry_price)}, ${fmtINR(result.position_result.position.capital_allocated)} allocated.`}
                    {result.position_result.closed === true && `Position closed — realized ${result.position_result.realized_pnl_pct?.toFixed(2)}%.`}
                    {result.position_result.closed === false && `Position not closed: ${result.position_result.reason}`}
                  </p>
                )}
              </Section>

              <p className="text-xs font-light text-slate-500 leading-relaxed mt-8 max-w-2xl">
                Every stage above reasons only over real, sourced data — Lumen Agent's tool calls, The Crucible's shared
                data blob, Fracture Scan and Clarity Score's deterministic rules. This is a simulated (paper) decision
                for research and education purposes only — not investment advice.
              </p>
            </>
          )}
        </div>
      </main>
      <Footer />
    </>
  );
}
