import { useCallback, useEffect, useState } from "react";
import axios from "axios";
import { AlertTriangle, Lock } from "lucide-react";
import LoadingBar from "../../components/site/LoadingBar";
import { StraddleCompass, MomentumTable } from "../AlphaTerminal";

/*
  What's left here after the multi-market work: only the two modules that
  have no single India component to simply repoint, plus the locked-module
  placeholder.

  Everything else on the Forex/Crypto/US tabs now renders the SAME component
  the India tab renders, pointed at a different endpoint — Exitline
  (USExitlineTool), Market Breadth (BreadthTool), Relative Strength
  (RelativeStrengthMatrix), EWMA (EwmaCrossoverTool), Gamma Pulse
  (OptionsTrendTool), Momentum Investing (MomentumDashboardTool), Sharpe
  (SharpeDashboardTool) and Peter Tingle (PeterTingleTool). A module has to
  look and behave identically on every market tab; the only thing allowed to
  differ is which endpoint feeds it.

  The two below still live here because they compose India's own primitives
  (StraddleCompass, MomentumTable) rather than wrapping a whole India tool:
  India's Index Vector fetches per-index signals inside ModuleDetail itself,
  and its Momentum Leaders reads the curated terminal_stocks scanner —
  neither is a component that can be repointed at a URL.
*/

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;
const CARD = "rounded-2xl border border-white/10 bg-[#0A0D18]";

const Unavailable = ({ reason, title = "Not Available in This Market" }) => (
  <div className={`${CARD} p-8 md:p-10 text-center`} data-testid="module-unavailable">
    <span className="inline-flex h-14 w-14 items-center justify-center rounded-2xl border border-white/10 bg-white/[0.03] text-slate-500 mb-5">
      <Lock size={24} />
    </span>
    <h3 className="text-xl font-bold text-white tracking-tight mb-3">{title}</h3>
    <p className="text-sm font-light text-slate-400 max-w-xl mx-auto leading-relaxed">{reason}</p>
  </div>
);

const ErrorNote = ({ message }) => (
  <div className={`${CARD} p-6 flex items-start gap-3`} data-testid="module-error">
    <AlertTriangle size={16} className="text-amber-400 shrink-0 mt-0.5" />
    <p className="text-sm text-slate-400 leading-relaxed">{message}</p>
  </div>
);

/** GET one URL, render it — with the shared loading/error/unavailable states. */
const useModuleData = (url) => {
  const [state, setState] = useState({ loading: true, data: null, error: null });
  const load = useCallback(() => {
    if (!url) return;
    setState((s) => ({ ...s, loading: true, error: null }));
    axios.get(`${API}${url}`)
      .then((r) => setState({ loading: false, data: r.data, error: null }))
      .catch((e) => setState({
        loading: false, data: null,
        error: e?.response?.data?.detail || "Data is temporarily unavailable — please try again shortly.",
      }));
  }, [url]);
  useEffect(load, [load]);
  return state;
};

const ModuleShell = ({ loading, error, data, children, loadingLabel }) => {
  if (loading) return <LoadingBar inline label={loadingLabel || "Loading module data"} />;
  if (error) return <ErrorNote message={error} />;
  if (!data) return <ErrorNote message="No data returned." />;
  if (data.available === false) return <Unavailable reason={data.reason} />;
  return children(data);
};

/* -------------------------------- Index Vector ----------------------------- */

// Renders the SAME StraddleCompass grid the India tab renders, in the same
// 2-1 formation, from the same BIAS_STYLE palette.
export const MMIndexVector = ({ market }) => {
  const [symbols, setSymbols] = useState([]);
  const [signals, setSignals] = useState({});
  const [state, setState] = useState({ loading: true, error: null, blocked: null });

  useEffect(() => {
    let cancelled = false;
    setState({ loading: true, error: null, blocked: null });
    setSignals({});

    axios.get(`${API}/markets/${market}/option-underlyings`)
      .then(async (r) => {
        const list = r.data?.symbols || [];
        if (cancelled) return;
        setSymbols(list);
        const results = await Promise.all(list.map((sym) =>
          axios.get(`${API}/markets/${market}/index-vector`, { params: { symbol: sym } })
            .then((res) => [sym, res.data])
            .catch(() => [sym, null]),
        ));
        if (cancelled) return;
        const blocked = results.find(([, d]) => d && d.available === false);
        if (blocked) { setState({ loading: false, error: null, blocked: blocked[1].reason }); return; }
        setSignals(Object.fromEntries(results.filter(([, d]) => d)));
        setState({ loading: false, error: null, blocked: null });
      })
      .catch(() => {
        if (!cancelled) {
          setState({ loading: false, error: "Data is temporarily unavailable — please try again shortly.", blocked: null });
        }
      });
    return () => { cancelled = true; };
  }, [market]);

  if (state.loading) return <LoadingBar inline label="Computing confluence" />;
  if (state.blocked) return <Unavailable reason={state.blocked} />;
  if (state.error) return <ErrorNote message={state.error} />;
  if (!symbols.length) return <ErrorNote message="No index underlying available for this market." />;

  return (
    <div className="grid grid-cols-1 md:grid-cols-2 gap-4" data-testid="vector-index-grid">
      {symbols.map((sym, i) => {
        const isLastOfOdd = i === symbols.length - 1 && symbols.length % 2 === 1;
        const d = signals[sym];
        // StraddleCompass expects the India signal shape: spot is a
        // preformatted string there, a float here — normalised, not
        // reshaped, so the component itself needs no market branch.
        const signal = d
          ? { ...d, spot: d.spot == null ? null : Number(d.spot).toLocaleString("en-US", { maximumFractionDigits: 2 }) }
          : null;
        return (
          <div key={sym} className={isLastOfOdd ? "md:col-span-2" : ""}>
            <StraddleCompass signal={signal} index={sym} livePoll={false} />
          </div>
        );
      })}
    </div>
  );
};

/* ------------------------------ Momentum Leaders --------------------------- */

// Renders the SAME MomentumTable the India tab renders (ticker, company,
// momentum score, volume, bias) rather than a second table of its own.
export const MMMomentumLeaders = ({ market }) => {
  const { loading, error, data } = useModuleData(`/markets/${market}/momentum-engine/top?limit=25`);
  return (
    <ModuleShell loading={loading} error={error} data={data} loadingLabel="Loading momentum leaders">
      {(d) => {
        if (!d.has_data) return <ErrorNote message={d.reason || "This ranking hasn't been computed yet."} />;
        const rows = (d.rows || []).map((r, i) => ({
          id: r.symbol || i,
          ticker: r.symbol,
          company: r.name || "—",
          // The leader score is a blended return in percent; rounded for
          // display only, never for the ranking itself.
          momentum_score: r.score == null ? "—" : Math.round(r.score),
          volume: "—",
          bias: r.score > 0 ? "Bullish" : r.score < 0 ? "Bearish" : "Neutral",
        }));
        if (!rows.length) return <ErrorNote message="No instruments met the minimum history requirement." />;
        // No TradingView row link: its symbols are NSE-scoped, so it would
        // open the wrong instrument for a pair or a token.
        return <MomentumTable rows={rows} onRowClick={() => {}} />;
      }}
    </ModuleShell>
  );
};

/* --------------------------- No-formula placeholder ------------------------ */

export const MMUnavailable = ({ module }) => (
  <Unavailable
    title="Coming Soon"
    reason={module?.reason || "This module has no computable definition for this market yet."}
  />
);
