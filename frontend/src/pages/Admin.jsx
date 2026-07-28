import { useEffect, useState, useCallback } from "react";
import axios from "axios";
import { toast } from "sonner";
import { Link } from "react-router-dom";
import {
  Loader2, LogOut, Plus, Trash2, GripVertical, Save, X, ArrowLeft, ShieldCheck,
  Wifi, WifiOff, RefreshCw, ChevronDown, FileText,
} from "lucide-react";
import { STRATEGIES } from "./blackbox/strategies";
import AdminStrategyReport from "./blackbox/AdminStrategyReport";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;
const TOKEN_KEY = "sac_admin_token";

const SCANNERS = [
  { key: "momentum", label: "Momentum Leaders" },
  { key: "relative_strength", label: "Relative Strength Leaders" },
  { key: "breakout", label: "Breakout Candidates" },
  { key: "positional", label: "Positional Opportunities" },
];
const BIAS = ["Bullish", "Bearish", "Neutral"];

// Mirrors backend/definedge_service.py's INDEX_CONFIG chart_mode — NIFTY and
// SENSEX still list real weekly-cadence contracts (6-leg confluence);
// BANKNIFTY and BANKEX are monthly-only now, so their manual-override form
// skips the weekly fields entirely rather than showing inputs for legs that
// don't exist. Kept in sync manually since this is presentation-only (the
// backend is the source of truth for how bias actually gets computed/derived).
const INDEX_OPTS = ["NIFTY", "BANKNIFTY", "SENSEX", "BANKEX"];
const INDEX_CHART_MODE = { NIFTY: "6", BANKNIFTY: "4", SENSEX: "6", BANKEX: "4" };

const authHeaders = () => ({ headers: { Authorization: `Bearer ${localStorage.getItem(TOKEN_KEY)}` } });
const tempId = () => `new-${Math.random().toString(36).slice(2)}`;

/* ----------------------------- Login ----------------------------- */
const Login = ({ onSuccess }) => {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);

  const submit = async (e) => {
    e.preventDefault();
    setLoading(true);
    try {
      const { data } = await axios.post(`${API}/auth/login`, { email, password });
      localStorage.setItem(TOKEN_KEY, data.access_token);
      toast.success("Signed in.");
      onSuccess(data.user);
    } catch (err) {
      const d = err?.response?.data?.detail;
      toast.error(typeof d === "string" ? d : "Login failed.");
    } finally {
      setLoading(false);
    }
  };

  const field =
    "w-full bg-transparent border-b border-white/15 focus:border-sapphire-light outline-none text-white font-light py-3 placeholder:text-slate-600 transition-colors duration-300";

  return (
    <div className="min-h-screen bg-void grid-bg flex items-center justify-center px-6" data-testid="admin-login">
      <div className="absolute inset-0 radial-glow pointer-events-none" />
      <form onSubmit={submit} className="glass rounded-3xl p-8 md:p-12 w-full max-w-md relative z-10">
        <div className="flex items-center gap-3 mb-8">
          <span className="h-10 w-10 rounded-xl bg-sapphire/15 border border-sapphire/30 flex items-center justify-center">
            <ShieldCheck size={18} className="text-sapphire-light" />
          </span>
          <div>
            <h1 className="font-display text-xl font-bold text-white">Admin Access</h1>
            <p className="font-mono-ui text-[10px] uppercase tracking-[0.2em] text-slate-500">Alpha Terminal Console</p>
          </div>
        </div>
        <div className="space-y-6">
          <div>
            <label className="font-mono-ui text-[11px] uppercase tracking-[0.2em] text-slate-500 block mb-2">Email</label>
            <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} className={field} placeholder="you@example.com" data-testid="admin-email" />
          </div>
          <div>
            <label className="font-mono-ui text-[11px] uppercase tracking-[0.2em] text-slate-500 block mb-2">Password</label>
            <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} className={field} placeholder="••••••••" data-testid="admin-password" />
          </div>
        </div>
        <button type="submit" disabled={loading} className="btn-sapphire w-full mt-10 disabled:opacity-70" data-testid="admin-login-btn">
          {loading ? <><Loader2 size={16} className="animate-spin" /> Signing in</> : "Sign In"}
        </button>
        <Link to="/" className="mt-6 inline-flex items-center gap-2 text-slate-500 hover:text-white transition-colors text-sm">
          <ArrowLeft size={14} /> Back to site
        </Link>
      </form>
    </div>
  );
};

/* ------------------------ Definedge live connection ------------------------ */
const errMsg = (err, fallback) => {
  const d = err?.response?.data?.detail;
  return typeof d === "string" ? d : fallback;
};

const DefinedgeConnect = ({ onAuthError, onSignalUpdate }) => {
  const [status, setStatus] = useState(null);
  const [otp, setOtp] = useState("");
  const [otpToken, setOtpToken] = useState(null);
  const [sendingOtp, setSendingOtp] = useState(false);
  const [verifyingOtp, setVerifyingOtp] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [showDebug, setShowDebug] = useState(false);
  const [masterSample, setMasterSample] = useState(null);
  const [loadingMaster, setLoadingMaster] = useState(false);

  const loadStatus = useCallback(async () => {
    try {
      const { data } = await axios.get(`${API}/admin/definedge/status`, authHeaders());
      setStatus(data);
    } catch (err) {
      if (err?.response?.status === 401) onAuthError();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => { loadStatus(); }, [loadStatus]);

  const sendOtp = async () => {
    setSendingOtp(true);
    try {
      const { data } = await axios.post(`${API}/admin/definedge/otp-init`, {}, authHeaders());
      setOtpToken(data.otp_token ?? null);
      toast.success(data.message || "OTP sent.");
    } catch (err) {
      if (err?.response?.status === 401) { onAuthError(); return; }
      toast.error(errMsg(err, "Failed to send OTP."));
    } finally {
      setSendingOtp(false);
    }
  };

  const verifyOtp = async () => {
    if (!otp.trim()) return;
    setVerifyingOtp(true);
    try {
      await axios.post(`${API}/admin/definedge/otp-verify`, { otp, otp_token: otpToken }, authHeaders());
      toast.success("Connected.");
      setOtp("");
      setOtpToken(null);
      await loadStatus();
    } catch (err) {
      if (err?.response?.status === 401) { onAuthError(); return; }
      toast.error(errMsg(err, "OTP verification failed."));
    } finally {
      setVerifyingOtp(false);
    }
  };

  const [refreshIndex, setRefreshIndex] = useState("NIFTY");

  const refreshNow = async () => {
    setRefreshing(true);
    try {
      const { data } = await axios.post(`${API}/admin/definedge/refresh`, {}, { ...authHeaders(), params: { index: refreshIndex } });
      onSignalUpdate(data);
      toast.success(`${refreshIndex} Index Vector refreshed from live data.`);
    } catch (err) {
      if (err?.response?.status === 401) { onAuthError(); return; }
      toast.error(errMsg(err, "Refresh failed."));
    } finally {
      setRefreshing(false);
    }
  };

  const toggleDebug = async () => {
    const next = !showDebug;
    setShowDebug(next);
    if (next && !masterSample) {
      setLoadingMaster(true);
      try {
        const { data } = await axios.get(`${API}/admin/definedge/master-sample`, authHeaders());
        setMasterSample(data);
      } catch (err) {
        if (err?.response?.status === 401) { onAuthError(); return; }
        toast.error(errMsg(err, "Failed to load master sample."));
      } finally {
        setLoadingMaster(false);
      }
    }
  };

  const connected = !!status?.connected;
  const configured = !!status?.configured;
  const pill = connected
    ? { icon: Wifi, cls: "text-emerald-300 border-emerald-400/30 bg-emerald-400/10", dot: "bg-emerald-400", label: "Connected" }
    : configured
    ? { icon: WifiOff, cls: "text-amber-300 border-amber-400/30 bg-amber-400/10", dot: "bg-amber-400", label: "Not connected" }
    : { icon: WifiOff, cls: "text-slate-400 border-white/15 bg-white/5", dot: "bg-slate-500", label: "Not configured" };
  const PillIcon = pill.icon;

  const fld = "w-full bg-white/5 border border-white/10 rounded-md px-3 py-2 text-sm text-white outline-none focus:border-sapphire-light transition-colors";

  return (
    <div className="glass rounded-2xl p-6 md:p-8 mb-6" data-testid="definedge-connect-panel">
      <div className="flex flex-wrap items-center justify-between gap-3 mb-2">
        <h2 className="font-display text-xl font-bold text-white">Market Data Connection</h2>
        <span className={`inline-flex items-center gap-1.5 rounded-full border px-3 py-1 font-mono-ui text-[10px] uppercase tracking-[0.18em] ${pill.cls}`} data-testid="definedge-status-pill">
          <span className={`h-1.5 w-1.5 rounded-full ${pill.dot}`} />
          <PillIcon size={12} /> {pill.label}
        </span>
      </div>
      <p className="text-sm text-slate-500 mb-6">
        Log in with the daily OTP to enable auto-live updates. The session resets every trading day —
        repeat this each morning.
        {status?.session_updated_at && (
          <span className="block mt-1 text-xs text-slate-600">Session updated: {status.session_updated_at}</span>
        )}
      </p>

      <div className="flex flex-wrap items-end gap-4">
        <button
          onClick={sendOtp}
          disabled={!configured || sendingOtp}
          className="btn-sapphire disabled:opacity-50"
          data-testid="definedge-send-otp-btn"
        >
          {sendingOtp ? <><Loader2 size={16} className="animate-spin" /> Sending</> : "Send OTP"}
        </button>

        <div className="flex-1 min-w-[160px]">
          <label className="font-mono-ui text-[10px] uppercase tracking-[0.18em] text-slate-500 block mb-1.5">OTP</label>
          <input
            value={otp}
            onChange={(e) => setOtp(e.target.value)}
            className={fld}
            placeholder="Enter OTP"
            data-testid="definedge-otp-input"
          />
        </div>
        <button
          onClick={verifyOtp}
          disabled={!otp.trim() || verifyingOtp}
          className="btn-ghost !px-4 !py-2.5 text-sm disabled:opacity-50"
          data-testid="definedge-verify-otp-btn"
        >
          {verifyingOtp ? <><Loader2 size={16} className="animate-spin" /> Verifying</> : "Verify"}
        </button>

        <div className="w-32">
          <label className="font-mono-ui text-[10px] uppercase tracking-[0.18em] text-slate-500 block mb-1.5">Index</label>
          <select value={refreshIndex} onChange={(e) => setRefreshIndex(e.target.value)} style={{ colorScheme: "dark" }} className={fld} data-testid="definedge-refresh-index">
            {INDEX_OPTS.map((i) => <option key={i} value={i} className="bg-surface">{i}</option>)}
          </select>
        </div>
        <button
          onClick={refreshNow}
          disabled={!connected || refreshing}
          className="btn-ghost !px-4 !py-2.5 text-sm disabled:opacity-50"
          data-testid="definedge-refresh-btn"
        >
          {refreshing ? <><Loader2 size={16} className="animate-spin" /> Refreshing</> : <><RefreshCw size={15} /> Refresh Now</>}
        </button>
      </div>

      <div className="mt-6 border-t border-white/10 pt-4">
        <button
          onClick={toggleDebug}
          className="inline-flex items-center gap-1.5 text-xs text-slate-500 hover:text-white transition-colors"
          data-testid="definedge-debug-toggle"
        >
          <ChevronDown size={14} className={`transition-transform ${showDebug ? "rotate-180" : ""}`} />
          Debug: master file sample
        </button>
        {showDebug && (
          <div className="mt-3">
            {loadingMaster ? (
              <div className="flex items-center gap-2 text-sm text-slate-500"><Loader2 size={14} className="animate-spin" /> Loading…</div>
            ) : masterSample ? (
              <pre className="text-[11px] font-mono-ui text-slate-400 bg-black/30 rounded-lg p-3 overflow-x-auto max-h-64">
                {`shape: ${JSON.stringify(masterSample.shape)}\n\n${JSON.stringify(masterSample.head, null, 2)}`}
              </pre>
            ) : (
              <p className="text-sm text-slate-600">No data loaded.</p>
            )}
          </div>
        )}
      </div>
    </div>
  );
};

/* ------------------------ Straddle Compass panel ------------------------ */
const BIAS_OPTS = ["Neutral", "Bullish", "Bearish"];
const TREND_OPTS = ["Neutral", "Bullish", "Bearish"];

const SignalPanel = ({ onAuthError }) => {
  const empty = (index) => ({
    index, bias: "Neutral", spot: "", atm: "", up_strike: "", down_strike: "",
    weekly_expiry: "", monthly_expiry: "",
    weekly_up_trend: "Neutral", weekly_down_trend: "Neutral",
    monthly_up_trend: "Neutral", monthly_down_trend: "Neutral",
    monthly_atm_ce_trend: "Neutral", monthly_atm_pe_trend: "Neutral",
    note: "", source: "manual",
  });
  const [index, setIndex] = useState("NIFTY");
  const [sig, setSig] = useState(empty("NIFTY"));
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const chartMode = INDEX_CHART_MODE[index];

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    axios.get(`${API}/admin/terminal/signal`, { ...authHeaders(), params: { index } })
      .then(({ data }) => { if (!cancelled) setSig({ ...empty(index), ...data }); })
      .catch((err) => {
        if (cancelled) return;
        if (err?.response?.status === 401) { onAuthError(); return; }
        setSig(empty(index));
      })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [index]);

  const set = (k) => (e) => setSig((s) => ({ ...s, [k]: e.target.value }));

  const save = async () => {
    setSaving(true);
    try {
      const { data } = await axios.put(`${API}/terminal/signal`, sig, authHeaders());
      setSig((s) => ({ ...s, ...data }));
      toast.success(`${index} Index Vector updated. Live on the terminal.`);
    } catch (err) {
      if (err?.response?.status === 401) { toast.error("Session expired."); onAuthError(); return; }
      toast.error("Failed to save signal.");
    } finally {
      setSaving(false);
    }
  };

  const fld = "w-full bg-white/5 border border-white/10 rounded-md px-3 py-2 text-sm text-white outline-none focus:border-sapphire-light transition-colors";
  const sel = fld + " [color-scheme:dark]";
  const TrendSelect = (key, testId) => (
    <select value={sig[key]} onChange={set(key)} style={{ colorScheme: "dark" }} className={sel} data-testid={testId}>
      {TREND_OPTS.map((t) => <option key={t} value={t} className="bg-surface">{t === "Bullish" ? "Rising" : t === "Bearish" ? "Falling" : "Flat"}</option>)}
    </select>
  );
  const Field = ({ label, children }) => (
    <div>
      <label className="font-mono-ui text-[10px] uppercase tracking-[0.18em] text-slate-500 block mb-1.5">{label}</label>
      {children}
    </div>
  );

  return (
    <div className="glass rounded-2xl p-6 md:p-8 mb-10" data-testid="admin-signal-panel">
      <div className="flex flex-wrap items-center justify-between gap-3 mb-2">
        <div className="flex items-center gap-3">
          <h2 className="font-display text-xl font-bold text-white">Index Vector</h2>
          <span className="font-mono-ui text-[10px] uppercase tracking-[0.2em] text-sapphire-light">
            {chartMode === "6" ? "6-Chart Confluence" : "4-Chart Confluence (monthly-only)"}
          </span>
        </div>
        <div className="w-36">
          <select value={index} onChange={(e) => setIndex(e.target.value)} style={{ colorScheme: "dark" }} className={sel} data-testid="signal-index-select">
            {INDEX_OPTS.map((i) => <option key={i} value={i} className="bg-surface">{i}</option>)}
          </select>
        </div>
      </div>
      <p className="text-sm text-slate-500 mb-6">
        {chartMode === "6" ? (
          <>Leave Bias on <em>Neutral</em> to auto-derive it from all six legs. Bullish needs +200 falling &amp; −200 rising
          on BOTH weekly and monthly, AND monthly ATM CE rising &amp; PE falling — mirror image for Bearish. Any single leg
          out of line stays Neutral.</>
        ) : (
          <>{index} has no real weekly-cadence contract (NSE/BSE consolidated it to monthly-only), so this reads only the
          four monthly legs. Leave Bias on <em>Neutral</em> to auto-derive it: Bullish needs +200 falling &amp; −200 rising,
          AND monthly ATM CE rising &amp; PE falling — mirror image for Bearish.</>
        )}
      </p>

      {loading ? (
        <div className="flex items-center gap-2 text-slate-500 text-sm py-10 justify-center"><Loader2 className="animate-spin" size={16} /> Loading</div>
      ) : (
        <>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-5 mb-6">
            <Field label="Bias">
              <select value={sig.bias} onChange={set("bias")} style={{ colorScheme: "dark" }} className={sel} data-testid="signal-bias">
                {BIAS_OPTS.map((b) => <option key={b} value={b} className="bg-surface">{b === "Neutral" ? "Neutral (auto)" : b}</option>)}
              </select>
            </Field>
            <Field label="Spot"><input value={sig.spot} onChange={set("spot")} className={fld} placeholder="24,000" data-testid="signal-spot" /></Field>
            <Field label="ATM"><input value={sig.atm} onChange={set("atm")} className={fld} placeholder="24000" data-testid="signal-atm" /></Field>
            <div className="hidden md:block" />
            <Field label="ATM +200 strike"><input value={sig.up_strike} onChange={set("up_strike")} className={fld} placeholder="24200" data-testid="signal-up-strike" /></Field>
            <Field label="ATM −200 strike"><input value={sig.down_strike} onChange={set("down_strike")} className={fld} placeholder="23800" data-testid="signal-down-strike" /></Field>
            {chartMode === "6" && (
              <Field label="Weekly expiry"><input value={sig.weekly_expiry} onChange={set("weekly_expiry")} className={fld} placeholder="2026-07-28" data-testid="signal-weekly-expiry" /></Field>
            )}
            <Field label="Monthly expiry"><input value={sig.monthly_expiry} onChange={set("monthly_expiry")} className={fld} placeholder="2026-08-25" data-testid="signal-monthly-expiry" /></Field>
          </div>

          {chartMode === "6" && (
            <>
              <p className="font-mono-ui text-[10px] uppercase tracking-[0.18em] text-sapphire-light mb-2">Weekly Straddle (0.5% × 3)</p>
              <div className="grid grid-cols-2 gap-5 mb-6">
                <Field label="+200 trend">{TrendSelect("weekly_up_trend", "signal-weekly-up-trend")}</Field>
                <Field label="−200 trend">{TrendSelect("weekly_down_trend", "signal-weekly-down-trend")}</Field>
              </div>
            </>
          )}

          <p className="font-mono-ui text-[10px] uppercase tracking-[0.18em] text-sapphire-light mb-2">Monthly Straddle (0.5% × 3)</p>
          <div className="grid grid-cols-2 gap-5 mb-6">
            <Field label="+200 trend">{TrendSelect("monthly_up_trend", "signal-monthly-up-trend")}</Field>
            <Field label="−200 trend">{TrendSelect("monthly_down_trend", "signal-monthly-down-trend")}</Field>
          </div>

          <p className="font-mono-ui text-[10px] uppercase tracking-[0.18em] text-sapphire-light mb-2">Monthly ATM CE / PE, individually (3% × 3)</p>
          <div className="grid grid-cols-2 gap-5 mb-6">
            <Field label="ATM CE trend">{TrendSelect("monthly_atm_ce_trend", "signal-monthly-ce-trend")}</Field>
            <Field label="ATM PE trend">{TrendSelect("monthly_atm_pe_trend", "signal-monthly-pe-trend")}</Field>
          </div>

          <Field label="Note (optional)"><input value={sig.note} onChange={set("note")} className={fld} placeholder="Context shown under the bias" data-testid="signal-note" /></Field>
          <button onClick={save} disabled={saving} className="btn-sapphire mt-6 disabled:opacity-70" data-testid="signal-save-btn">
            {saving ? <><Loader2 size={16} className="animate-spin" /> Saving</> : <><Save size={15} /> Update Compass</>}
          </button>
        </>
      )}
    </div>
  );
};

/* ----------------------------- Quant Lab ----------------------------- */
const QuantLabPanel = ({ onAuthError }) => {
  const [status, setStatus] = useState(null);
  const [starting, setStarting] = useState(false);

  const loadStatus = useCallback(async () => {
    try {
      const { data } = await axios.get(`${API}/quant-lab/sharpe-refresh-status`);
      setStatus(data);
    } catch {
      // best-effort — leave last-known status showing
    }
  }, []);

  useEffect(() => { loadStatus(); }, [loadStatus]);

  useEffect(() => {
    if (status?.status !== "running") return undefined;
    const id = setInterval(loadStatus, 3000);
    return () => clearInterval(id);
  }, [status?.status, loadStatus]);

  const refreshNow = async () => {
    setStarting(true);
    try {
      await axios.post(`${API}/quant-lab/admin/sharpe-refresh-now`, {}, authHeaders());
      toast.success("Nifty 500 Sharpe refresh started — takes a few minutes.");
      await loadStatus();
    } catch (err) {
      if (err?.response?.status === 401) { onAuthError(); return; }
      toast.error(errMsg(err, "Failed to start refresh."));
    } finally {
      setStarting(false);
    }
  };

  const running = status?.status === "running";

  return (
    <div className="glass rounded-2xl p-6 md:p-8 mb-10" data-testid="admin-quant-lab-panel">
      <div className="flex flex-wrap items-center justify-between gap-3 mb-2">
        <h2 className="font-display text-xl font-bold text-white">Quant Lab — Sharpe Dashboard</h2>
        <button
          onClick={refreshNow}
          disabled={starting || running}
          className="btn-ghost !px-4 !py-2 text-sm disabled:opacity-50"
          data-testid="sharpe-refresh-nifty500-btn"
        >
          {running ? <><Loader2 size={16} className="animate-spin" /> Refreshing</> : <><RefreshCw size={15} /> Refresh Nifty 500 Cache</>}
        </button>
      </div>
      <p className="text-sm text-slate-500 mb-4">
        Recomputes Sharpe/Sortino/max drawdown for all Nifty 500 constituents (takes a few minutes) — needed once before
        "Top Ranked" mode on the public Sharpe Dashboard has anything to rank. Individual symbols in "Compare" mode
        compute on demand and don't need this.
      </p>
      {status && (
        <div className="text-xs text-slate-500 font-mono-ui" data-testid="sharpe-refresh-status-line">
          {status.status === "idle" && "No refresh has run yet."}
          {running && `Running — ${status.done ?? 0}/${status.total ?? 0} processed (${status.cached ?? 0} cached, ${status.failed ?? 0} failed).`}
          {status.status === "done" && !running && (
            <>Last refresh: {status.cached ?? 0}/{status.total ?? 0} cached, {status.failed ?? 0} failed{status.completed_at ? ` — ${new Date(status.completed_at).toLocaleString("en-IN")}` : ""}.</>
          )}
        </div>
      )}
    </div>
  );
};

/* ------------------------------ Black Box — Prism Alpha ------------------------------ */
const StrategyReportAccordion = ({ strategy, onAuthError }) => {
  const [open, setOpen] = useState(false);
  return (
    <div className="rounded-2xl border border-white/10 bg-[#0A0D18]" data-testid={`admin-report-accordion-${strategy.slug}`}>
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="w-full flex items-center justify-between gap-4 p-5 text-left"
        data-testid={`admin-report-toggle-${strategy.slug}`}
      >
        <span className="flex items-center gap-3">
          <FileText size={16} className="text-sapphire-light shrink-0" />
          <span>
            <span className="block font-display text-base font-bold text-white">{strategy.title}</span>
            <span className="block text-xs text-slate-500">{strategy.internalStatus} · Full internal report</span>
          </span>
        </span>
        <ChevronDown size={16} className={`text-slate-500 transition-transform duration-300 ${open ? "rotate-180" : ""}`} />
      </button>
      {open && (
        <div className="px-5 pb-5 border-t border-white/10">
          <AdminStrategyReport strategy={strategy} authConfig={authHeaders()} onAuthError={onAuthError} />
        </div>
      )}
    </div>
  );
};

const BlackBoxPanel = ({ onAuthError }) => {
  const [running, setRunning] = useState(false);
  const [lastResult, setLastResult] = useState(null);
  const [backtesting, setBacktesting] = useState(false);
  const [lastBacktest, setLastBacktest] = useState(null);
  const [lumenRunning, setLumenRunning] = useState(false);
  const [lastLumenResult, setLastLumenResult] = useState(null);
  const [lumenBacktesting, setLumenBacktesting] = useState(false);
  const [lastLumenBacktest, setLastLumenBacktest] = useState(null);

  const evaluateNow = async () => {
    setRunning(true);
    try {
      const { data } = await axios.post(`${API}/blackbox/admin/prism-alpha-evaluate-now`, {}, authHeaders());
      setLastResult(data);
      const pa = data.prism_alpha, pa2 = data.prism_alpha_2;
      toast.success(`Evaluated — Prism Alpha: ${pa?.action}${pa?.reason ? ` (${pa.reason})` : ""}; Prism Alpha 2: ${pa2?.action}${pa2?.reason ? ` (${pa2.reason})` : ""}.`);
    } catch (err) {
      if (err?.response?.status === 401) { onAuthError(); return; }
      toast.error(errMsg(err, "Evaluation failed."));
    } finally {
      setRunning(false);
    }
  };

  const runBacktest = async () => {
    setBacktesting(true);
    try {
      const { data } = await axios.post(`${API}/blackbox/admin/prism-alpha-backtest-run`, {}, authHeaders());
      setLastBacktest(data);
      toast.success(`Backtest complete — Prism Alpha: ${data.prism_alpha_trades} trade(s), Prism Alpha 2: ${data.prism_alpha_2_trades} trade(s), ${data.start_date} to ${data.end_date}.`);
    } catch (err) {
      if (err?.response?.status === 401) { onAuthError(); return; }
      toast.error(errMsg(err, "Backtest run failed."));
    } finally {
      setBacktesting(false);
    }
  };

  const evaluateLumenSip = async () => {
    setLumenRunning(true);
    try {
      const { data } = await axios.post(`${API}/blackbox/admin/lumen-sip-evaluate-now`, {}, authHeaders());
      setLastLumenResult(data);
      toast.success(`Lumen SIP live evaluated — NIFTYBEES: ${data.current_phase?.NIFTYBEES}, GOLDBEES: ${data.current_phase?.GOLDBEES} (${data.signals_logged} new signal(s)).`);
    } catch (err) {
      if (err?.response?.status === 401) { onAuthError(); return; }
      toast.error(errMsg(err, "Lumen SIP evaluation failed."));
    } finally {
      setLumenRunning(false);
    }
  };

  const runLumenSipBacktest = async () => {
    setLumenBacktesting(true);
    try {
      const { data } = await axios.post(`${API}/blackbox/admin/lumen-sip-backtest-run`, {}, authHeaders());
      setLastLumenBacktest(data);
      toast.success(`Lumen SIP backtest rebuilt — ${data.portfolio_snapshots} daily snapshots, ${data.signals_logged} signals.`);
    } catch (err) {
      if (err?.response?.status === 401) { onAuthError(); return; }
      toast.error(errMsg(err, "Lumen SIP backtest run failed."));
    } finally {
      setLumenBacktesting(false);
    }
  };

  return (
    <div className="glass rounded-2xl p-6 md:p-8 mb-10" data-testid="admin-blackbox-panel">
      <div className="flex flex-wrap items-center justify-between gap-3 mb-2">
        <h2 className="font-display text-xl font-bold text-white">Black Box — Prism Alpha</h2>
        <div className="flex flex-wrap items-center gap-3">
          <button onClick={evaluateNow} disabled={running} className="btn-ghost !px-4 !py-2 text-sm disabled:opacity-50" data-testid="prism-alpha-evaluate-now-btn">
            {running ? <><Loader2 size={16} className="animate-spin" /> Evaluating</> : <><RefreshCw size={15} /> Evaluate Now</>}
          </button>
          <button onClick={runBacktest} disabled={backtesting} className="btn-ghost !px-4 !py-2 text-sm disabled:opacity-50" data-testid="prism-alpha-backtest-run-btn">
            {backtesting ? <><Loader2 size={16} className="animate-spin" /> Backtesting</> : <><RefreshCw size={15} /> Run Backtest</>}
          </button>
        </div>
      </div>
      <p className="text-sm text-slate-500 mb-4">
        "Evaluate Now" runs one live cycle for BOTH Prism Alpha (RSI + XO Zone gated) and Prism Alpha 2 (pattern-only, no indicator gate) —
        entry check if flat, stop/target/trailing-stop check if in a position. The external cron should hit{" "}
        <code className="text-slate-400">/api/blackbox/admin/prism-alpha-evaluate</code> every minute during market hours.
        "Run Backtest" replays real 1-minute data (Nifty spot + option premium — no daily/EOD approximation) for both variants,
        deliberately kept to the last ~1-2 weeks — that's the widest window that stays inside a single real weekly expiry cycle
        (the live strategy rolls to a new expiry every week; expired-contract data can't be resolved to replay that roll here).
        Heavier, on-demand only.
      </p>
      {lastResult && (
        <div className="text-xs text-slate-500 font-mono-ui space-y-0.5" data-testid="prism-alpha-last-result">
          <div>Prism Alpha: {lastResult.prism_alpha?.action}{lastResult.prism_alpha?.reason ? ` — ${lastResult.prism_alpha.reason}` : ""}</div>
          <div>Prism Alpha 2: {lastResult.prism_alpha_2?.action}{lastResult.prism_alpha_2?.reason ? ` — ${lastResult.prism_alpha_2.reason}` : ""}</div>
        </div>
      )}
      {lastBacktest && (
        <div className="text-xs text-slate-500 font-mono-ui mt-1" data-testid="prism-alpha-last-backtest">
          Last backtest: {lastBacktest.start_date} – {lastBacktest.end_date} ({lastBacktest.spot_ticks_evaluated} spot ticks) — Prism Alpha: {lastBacktest.prism_alpha_trades} trade(s), Prism Alpha 2: {lastBacktest.prism_alpha_2_trades} trade(s).
        </div>
      )}

      <div className="flex flex-wrap items-center justify-between gap-3 mt-8 mb-2 pt-6 border-t border-white/10">
        <h2 className="font-display text-xl font-bold text-white">Black Box — Lumen SIP</h2>
        <div className="flex flex-wrap items-center gap-3">
          <button onClick={evaluateLumenSip} disabled={lumenRunning} className="btn-ghost !px-4 !py-2 text-sm disabled:opacity-50" data-testid="lumen-sip-evaluate-now-btn">
            {lumenRunning ? <><Loader2 size={16} className="animate-spin" /> Evaluating</> : <><RefreshCw size={15} /> Evaluate Now (Live)</>}
          </button>
          <button onClick={runLumenSipBacktest} disabled={lumenBacktesting} className="btn-ghost !px-4 !py-2 text-sm disabled:opacity-50" data-testid="lumen-sip-backtest-run-btn">
            {lumenBacktesting ? <><Loader2 size={16} className="animate-spin" /> Backtesting</> : <><RefreshCw size={15} /> Run Backtest</>}
          </button>
        </div>
      </div>
      <p className="text-sm text-slate-500 mb-4">
        "Evaluate Now (Live)" resumes the REAL portfolio from its last recorded state and walks forward only through any new
        trading day(s) — rewrites nothing, just appends to <code className="text-slate-400">blackbox_lumen_sip_signals</code> /{" "}
        <code className="text-slate-400">blackbox_lumen_sip_portfolio</code>. The external cron should hit{" "}
        <code className="text-slate-400">/api/blackbox/admin/lumen-sip-evaluate</code> once/day after market close.
        "Run Backtest" re-fetches 10 years of daily NIFTYBEES/GOLDBEES history and replays the full Renko + MAST-cloud walk-forward
        simulation from a zero starting portfolio — an illustrative "since inception" track record, always rebuilt from scratch into{" "}
        <code className="text-slate-400">blackbox_lumen_sip_backtest_signals</code> /{" "}
        <code className="text-slate-400">blackbox_lumen_sip_backtest_portfolio</code>, separate from the live collections. Heavier, on-demand only.
      </p>
      {lastLumenResult && (
        <div className="text-xs text-slate-500 font-mono-ui space-y-0.5" data-testid="lumen-sip-last-result">
          <div>Live — NIFTYBEES: {lastLumenResult.current_phase?.NIFTYBEES} · GOLDBEES: {lastLumenResult.current_phase?.GOLDBEES}</div>
          <div>{lastLumenResult.signals_logged} new signal(s), {lastLumenResult.portfolio_snapshots} new snapshot(s).</div>
        </div>
      )}
      {lastLumenBacktest && (
        <div className="text-xs text-slate-500 font-mono-ui space-y-0.5 mt-1" data-testid="lumen-sip-last-backtest">
          <div>Backtest — NIFTYBEES: {lastLumenBacktest.current_phase?.NIFTYBEES} · GOLDBEES: {lastLumenBacktest.current_phase?.GOLDBEES}</div>
          <div>{lastLumenBacktest.signals_logged} signals, {lastLumenBacktest.portfolio_snapshots} daily snapshots.</div>
        </div>
      )}

      <div className="mt-8 pt-6 border-t border-white/10">
        <h2 className="font-display text-xl font-bold text-white mb-1">Internal Strategy Reports</h2>
        <p className="text-sm text-slate-500 mb-4">
          Full performance data — live/backtested trades, equity curves, drawdowns, risk analytics — for each strategy. Not visible anywhere
          on the public site; these routes require this admin session's token.
        </p>
        <div className="space-y-3" data-testid="admin-strategy-reports">
          {STRATEGIES.map((s) => <StrategyReportAccordion key={s.slug} strategy={s} onAuthError={onAuthError} />)}
        </div>
      </div>
    </div>
  );
};

/* ------------------------- Momentum Track Record ------------------------- */
const SURFACE = "rounded-2xl border border-white/10 bg-[#0A0D18]";
const fmtStatNum = (v, dp = 2) => (v == null ? "—" : Number(v).toFixed(dp));
const fmtStatPctSigned = (v, dp = 2) => (v == null ? "—" : `${v > 0 ? "+" : ""}${Number(v).toFixed(dp)}%`);
const fmtStatDateLong = (iso) => {
  if (!iso) return "—";
  const d = new Date(`${iso}T00:00:00`);
  return d.toLocaleDateString("en-GB", { day: "2-digit", month: "short", year: "numeric" });
};

const ScannerStat = ({ label, value, tone = "text-white" }) => (
  <div className={`${SURFACE} p-4 text-center`}>
    <p className="font-mono-ui text-[10px] uppercase tracking-[0.16em] text-slate-500 mb-1.5">{label}</p>
    <p className={`font-mono-ui text-xl font-bold ${tone}`}>{value}</p>
  </div>
);

// Admin-only display of the momentum scanner's historical performance —
// moved off the public site (was frontend/src/pages/alphaterminal/
// ModuleDetail.jsx's ScannerTrackRecord) so nothing performance-related
// shows to visitors until the reset track record is convincing enough to
// make public again. Hits GET /admin/terminal/scanner-track-record (now
// admin-gated, previously public) with the same authHeaders() every other
// admin call here uses.
const ScannerTrackRecordAdmin = ({ scannerKey, onAuthError }) => {
  const [record, setRecord] = useState(null);
  const [selectedDate, setSelectedDate] = useState("all");
  const [logsOpen, setLogsOpen] = useState(false);

  useEffect(() => {
    axios.get(`${API}/admin/terminal/scanner-track-record`, { ...authHeaders(), params: { scanner: scannerKey } })
      .then((r) => setRecord(r.data))
      .catch((err) => {
        if (err?.response?.status === 401) { onAuthError(); return; }
        setRecord({ has_data: false });
      });
  }, [scannerKey, onAuthError]);

  if (!record) {
    return <div className="flex items-center justify-center py-10 text-slate-500 font-mono-ui text-sm gap-3"><Loader2 className="animate-spin" size={16} /> Loading…</div>;
  }
  if (!record.has_data) {
    return (
      <div className={`${SURFACE} border-dashed px-6 py-10 text-center`} data-testid="momentum-track-empty">
        <p className="text-sm font-light text-slate-500 max-w-md mx-auto">
          No calls have been scored yet. Each day's recommendations are graded once that trading session closes — check back after a few sessions for a meaningful read.
        </p>
      </div>
    );
  }

  const { overall, bullish, bearish, recent, since, trading_days, best_call, worst_call } = record;
  const winRatePct = (r) => (r?.win_rate != null ? `${(r.win_rate * 100).toFixed(0)}%` : "—");
  const availableDates = [...new Set(recent.map((r) => r.date))].sort((a, b) => (a < b ? 1 : -1));
  const visibleRows = selectedDate === "all" ? recent : recent.filter((r) => r.date === selectedDate);
  const perfTone = (v) => (v > 0 ? "text-emerald-400" : v < 0 ? "text-red-400" : "text-white");

  return (
    <div className="mt-6 pt-6 border-t border-white/10">
      <p className="text-xs text-slate-500 mb-4">
        Tracking since <span className="text-slate-300">{since}</span> — {overall.count} call{overall.count === 1 ? "" : "s"} scored.
      </p>

      <p className="font-mono-ui text-[10px] uppercase tracking-[0.16em] text-slate-500 font-semibold mb-3">Key Metrics</p>
      <div className="grid grid-cols-2 md:grid-cols-5 gap-3 mb-3">
        <ScannerStat label="Overall Win Rate" value={winRatePct(overall)} tone={overall.win_rate > 0.5 ? "text-emerald-400" : "text-white"} />
        <ScannerStat label="Average Return" value={fmtStatPctSigned(overall.avg_performance_pct)} tone={perfTone(overall.avg_performance_pct)} />
        <ScannerStat label="Median Return" value={fmtStatPctSigned(overall.median_performance_pct)} tone={perfTone(overall.median_performance_pct)} />
        <ScannerStat label="Total Calls" value={overall.count} />
        <ScannerStat label="Trading Days" value={trading_days} />
      </div>
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-4 md:w-4/5 md:mx-auto">
        <ScannerStat label="Avg. Max Upside" value={fmtStatPctSigned(overall.avg_best_case_pct)} tone="text-emerald-400" />
        <ScannerStat label="Avg. Max Drawdown" value={fmtStatPctSigned(overall.avg_worst_case_pct)} tone="text-red-400" />
        <ScannerStat label={`Bullish (${bullish.count}) Win Rate`} value={winRatePct(bullish)} tone="text-emerald-400" />
        <ScannerStat label={`Bearish (${bearish.count}) Win Rate`} value={winRatePct(bearish)} tone="text-red-400" />
      </div>
      <div className="grid grid-cols-2 gap-3 mb-6">
        <ScannerStat label="Bullish Avg. Return" value={fmtStatPctSigned(bullish.avg_performance_pct)} tone={perfTone(bullish.avg_performance_pct)} />
        <ScannerStat label="Bearish Avg. Return" value={fmtStatPctSigned(bearish.avg_performance_pct)} tone={perfTone(bearish.avg_performance_pct)} />
      </div>

      {(best_call || worst_call) && (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3 mb-6">
          {best_call && (
            <div className={`${SURFACE} p-4`}>
              <p className="font-mono-ui text-[10px] uppercase tracking-[0.16em] text-slate-500 mb-2">Best Call</p>
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-sm font-bold text-white">{best_call.ticker} <span className="text-slate-500 font-normal">· {fmtStatDateLong(best_call.date)}</span></p>
                  <p className={`text-xs ${best_call.bias === "Bullish" ? "text-emerald-400" : "text-red-400"}`}>{best_call.bias}</p>
                </div>
                <p className="font-mono-ui text-xl font-bold text-emerald-400">{fmtStatPctSigned(best_call.performance_pct)}</p>
              </div>
            </div>
          )}
          {worst_call && (
            <div className={`${SURFACE} p-4`}>
              <p className="font-mono-ui text-[10px] uppercase tracking-[0.16em] text-slate-500 mb-2">Worst Call</p>
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-sm font-bold text-white">{worst_call.ticker} <span className="text-slate-500 font-normal">· {fmtStatDateLong(worst_call.date)}</span></p>
                  <p className={`text-xs ${worst_call.bias === "Bullish" ? "text-emerald-400" : "text-red-400"}`}>{worst_call.bias}</p>
                </div>
                <p className="font-mono-ui text-xl font-bold text-red-400">{fmtStatPctSigned(worst_call.performance_pct)}</p>
              </div>
            </div>
          )}
        </div>
      )}

      <p className="text-[11px] font-light text-slate-600 mb-6">
        A Bullish call profits if price rises by close; a Bearish call profits if price falls (shown as positive performance either way).
        High/Low are measured from the 9:40 alert price onward only, not the full trading day. Past performance does not guarantee future results — not investment advice.
      </p>

      {recent.length > 0 && (
        <div className={`${SURFACE} overflow-hidden`}>
          <button
            type="button"
            onClick={() => setLogsOpen((o) => !o)}
            className="w-full flex items-center justify-between gap-3 px-4 py-3.5 text-left"
            data-testid="momentum-track-logs-toggle"
          >
            <span className="font-mono-ui text-[10px] uppercase tracking-[0.14em] text-slate-400 font-semibold">
              Logs — {recent.length} call{recent.length === 1 ? "" : "s"}
            </span>
            <ChevronDown size={16} className={`text-slate-500 transition-transform duration-300 shrink-0 ${logsOpen ? "rotate-180" : ""}`} />
          </button>
          {logsOpen && (
            <>
              <div className="flex items-center justify-end gap-3 px-4 py-3 border-t border-white/10">
                <label className="flex items-center gap-2 text-xs text-slate-400">
                  <span className="font-mono-ui uppercase tracking-[0.1em] text-[10px] text-slate-500">Date</span>
                  <select
                    value={selectedDate}
                    onChange={(e) => setSelectedDate(e.target.value)}
                    data-testid="momentum-track-date-filter"
                    className="bg-black/40 border border-white/10 rounded-md px-2.5 py-1.5 text-slate-200 text-xs font-mono-ui focus:outline-none focus:border-white/30"
                  >
                    <option value="all">All Dates</option>
                    {availableDates.map((d) => (
                      <option key={d} value={d}>{fmtStatDateLong(d)}</option>
                    ))}
                  </select>
                </label>
              </div>
              <div className="overflow-x-auto">
                <table className="w-full min-w-[920px]" style={{ fontVariantNumeric: "tabular-nums" }}>
                  <thead>
                    <tr className="border-b border-white/10">
                      {[
                        ["Date", "left"], ["Ticker", "left"], ["Bias", "left"],
                        ["Alert Price (9:40)", "right"], ["High After 9:40", "right"], ["Low After 9:40", "right"], ["Close", "right"],
                        ["Return", "right"], ["Max Upside", "right"], ["Max Drawdown", "right"],
                      ].map(([h, align]) => (
                        <th key={h} className={`px-4 py-3 font-mono-ui text-[10px] uppercase tracking-[0.14em] text-slate-500 font-semibold whitespace-nowrap text-${align}`}>{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {visibleRows.map((r) => (
                      <tr key={r.id} className="border-b border-white/[0.05] last:border-0" data-testid={`momentum-track-row-${r.id}`}>
                        <td className="px-4 py-2.5 text-sm text-slate-300 whitespace-nowrap">{fmtStatDateLong(r.date)}</td>
                        <td className="px-4 py-2.5 text-sm font-bold text-white whitespace-nowrap">{r.ticker}</td>
                        <td className="px-4 py-2.5 text-sm whitespace-nowrap">
                          <span className={r.bias === "Bullish" ? "text-emerald-400" : "text-red-400"}>
                            {r.bias === "Bullish" ? "🟢 Bullish" : "🔴 Bearish"}
                          </span>
                        </td>
                        <td className="px-4 py-2.5 font-mono-ui text-sm text-right text-slate-300 whitespace-nowrap">₹{fmtStatNum(r.entry_price)}</td>
                        <td className="px-4 py-2.5 font-mono-ui text-sm text-right text-slate-300 whitespace-nowrap">₹{fmtStatNum(r.high_price)}</td>
                        <td className="px-4 py-2.5 font-mono-ui text-sm text-right text-slate-300 whitespace-nowrap">₹{fmtStatNum(r.low_price)}</td>
                        <td className="px-4 py-2.5 font-mono-ui text-sm text-right text-slate-300 whitespace-nowrap">₹{fmtStatNum(r.close_price)}</td>
                        <td className={`px-4 py-2.5 font-mono-ui text-sm text-right whitespace-nowrap ${r.performance_pct > 0 ? "text-emerald-400" : "text-red-400"}`}>{fmtStatPctSigned(r.performance_pct)}</td>
                        <td className="px-4 py-2.5 font-mono-ui text-sm text-right text-emerald-400/90 whitespace-nowrap">{fmtStatPctSigned(r.best_case_pct)}</td>
                        <td className="px-4 py-2.5 font-mono-ui text-sm text-right text-red-400/90 whitespace-nowrap">{fmtStatPctSigned(r.worst_case_pct)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          )}
        </div>
      )}
    </div>
  );
};

const MomentumTrackRecordPanel = ({ onAuthError }) => {
  const [running, setRunning] = useState(false);
  const [lastResult, setLastResult] = useState(null);

  const evaluateNow = async () => {
    setRunning(true);
    try {
      const { data } = await axios.post(`${API}/admin/terminal/momentum-track-evaluate-now`, {}, authHeaders());
      setLastResult(data);
      toast.success(`Evaluated ${data.evaluated} call(s)${data.failed ? `, ${data.failed} failed` : ""}.`);
    } catch (err) {
      if (err?.response?.status === 401) { onAuthError(); return; }
      toast.error(errMsg(err, "Evaluation failed."));
    } finally {
      setRunning(false);
    }
  };

  return (
    <div className="glass rounded-2xl p-6 md:p-8 mb-10" data-testid="admin-momentum-track-panel">
      <div className="flex flex-wrap items-center justify-between gap-3 mb-2">
        <h2 className="font-display text-xl font-bold text-white">Intraday Momentum Leaders — Track Record</h2>
        <button onClick={evaluateNow} disabled={running} className="btn-ghost !px-4 !py-2 text-sm disabled:opacity-50" data-testid="momentum-track-evaluate-btn">
          {running ? <><Loader2 size={16} className="animate-spin" /> Evaluating</> : <><RefreshCw size={15} /> Evaluate Now</>}
        </button>
      </div>
      <p className="text-sm text-slate-500 mb-4">
        Entry prices are captured automatically whenever the scanner's rows are replaced (the daily sync). "Evaluate Now" fetches
        each pending call's real day OHLC once its session has closed and scores it — Bullish calls profit on a rise, Bearish
        calls profit on a fall (a decline shows as positive performance for a Bearish call, same convention as scoring a short).
        The external cron should hit <code className="text-slate-400">/api/admin/terminal/momentum-track-evaluate</code> once/day
        shortly after 15:30 IST close.
      </p>
      {lastResult && (
        <div className="text-xs text-slate-500 font-mono-ui" data-testid="momentum-track-last-result">
          Evaluated: {lastResult.evaluated} · Not yet closed: {lastResult.not_yet_closed} · Failed: {lastResult.failed} · Total pending: {lastResult.total_pending}
        </div>
      )}
      <ScannerTrackRecordAdmin scannerKey="momentum" onAuthError={onAuthError} />
    </div>
  );
};

/* ------------------------------ IPO Section ------------------------------ */
const EXCHANGES = ["NSE", "BSE"];
const emptyIpo = () => ({
  id: null, company_name: "", sector: "", issue_open_date: "", issue_close_date: "", listing_date: "",
  price_band: { min: "", max: "" }, lot_size: "", issue_size: "", exchange: ["NSE"], rhp_url: "", nse_symbol: "",
});

const IpoPanel = ({ onAuthError }) => {
  const [ipos, setIpos] = useState([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [refreshingGmp, setRefreshingGmp] = useState(false);
  const [editing, setEditing] = useState(null);
  const [saving, setSaving] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const { data } = await axios.get(`${API}/ipos`);
      setIpos(data);
    } catch {
      toast.error("Failed to load IPOs.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const refreshNse = async () => {
    setRefreshing(true);
    try {
      const { data } = await axios.post(`${API}/admin/ipos/refresh-now`, {}, authHeaders());
      toast.success(`Refreshed from NSE — ${data.upserted} entries updated.`);
      await load();
    } catch (err) {
      if (err?.response?.status === 401) { onAuthError(); return; }
      toast.error(errMsg(err, "NSE refresh failed."));
    } finally {
      setRefreshing(false);
    }
  };

  const refreshGmp = async () => {
    setRefreshingGmp(true);
    try {
      const { data } = await axios.post(`${API}/admin/ipos/gmp-refresh-now`, {}, authHeaders());
      const summary = Object.entries(data)
        .map(([source, r]) => (r.error ? `${source}: failed` : `${source}: ${r.matched}/${r.total_rows}`))
        .join(", ");
      toast.success(`GMP refreshed — ${summary}`);
      await load();
    } catch (err) {
      if (err?.response?.status === 401) { onAuthError(); return; }
      toast.error(errMsg(err, "GMP refresh failed."));
    } finally {
      setRefreshingGmp(false);
    }
  };

  const startEdit = (ipo) => setEditing(ipo ? {
    ...emptyIpo(),
    ...ipo,
    price_band: { min: ipo.price_band?.min ?? "", max: ipo.price_band?.max ?? "" },
    exchange: ipo.exchange?.length ? ipo.exchange : ["NSE"],
  } : emptyIpo());

  const setField = (k) => (e) => setEditing((f) => ({ ...f, [k]: e.target.value }));
  const setBandField = (k) => (e) => setEditing((f) => ({ ...f, price_band: { ...f.price_band, [k]: e.target.value } }));
  const toggleExchange = (ex) => setEditing((f) => ({
    ...f,
    exchange: f.exchange.includes(ex) ? f.exchange.filter((x) => x !== ex) : [...f.exchange, ex],
  }));

  const save = async () => {
    if (!editing.company_name.trim()) { toast.error("Company name is required."); return; }
    setSaving(true);
    try {
      const body = {
        company_name: editing.company_name,
        sector: editing.sector || null,
        issue_open_date: editing.issue_open_date || null,
        issue_close_date: editing.issue_close_date || null,
        listing_date: editing.listing_date || null,
        price_band: {
          min: editing.price_band.min === "" ? null : Number(editing.price_band.min),
          max: editing.price_band.max === "" ? null : Number(editing.price_band.max),
        },
        lot_size: editing.lot_size === "" ? null : Number(editing.lot_size),
        issue_size: editing.issue_size || null,
        exchange: editing.exchange,
        rhp_url: editing.rhp_url || null,
        nse_symbol: editing.nse_symbol || null,
      };
      if (editing.id) {
        await axios.put(`${API}/ipos/${editing.id}`, body, authHeaders());
      } else {
        await axios.post(`${API}/ipos`, body, authHeaders());
      }
      toast.success("IPO saved. Report generation runs in the background if an RHP link is set.");
      setEditing(null);
      await load();
    } catch (err) {
      if (err?.response?.status === 401) { onAuthError(); return; }
      toast.error(errMsg(err, "Save failed."));
    } finally {
      setSaving(false);
    }
  };

  const fld = "w-full bg-white/5 border border-white/10 rounded-md px-3 py-2 text-sm text-white outline-none focus:border-sapphire-light transition-colors";

  return (
    <div className="glass rounded-2xl p-6 md:p-8 mb-10" data-testid="admin-ipo-panel">
      <div className="flex flex-wrap items-center justify-between gap-3 mb-2">
        <h2 className="font-display text-xl font-bold text-white">IPO Section</h2>
        <div className="flex items-center gap-3">
          <button onClick={refreshNse} disabled={refreshing} className="btn-ghost !px-4 !py-2 text-sm disabled:opacity-50" data-testid="ipo-refresh-nse-btn">
            {refreshing ? <><Loader2 size={16} className="animate-spin" /> Refreshing</> : <><RefreshCw size={15} /> Refresh from NSE</>}
          </button>
          <button onClick={refreshGmp} disabled={refreshingGmp} className="btn-ghost !px-4 !py-2 text-sm disabled:opacity-50" data-testid="ipo-refresh-gmp-btn">
            {refreshingGmp ? <><Loader2 size={16} className="animate-spin" /> Refreshing</> : <><RefreshCw size={15} /> Refresh GMP Now</>}
          </button>
          <button onClick={() => startEdit(null)} className="btn-sapphire !px-4 !py-2 text-sm" data-testid="ipo-add-btn">
            <Plus size={15} /> Add IPO
          </button>
        </div>
      </div>
      <p className="text-sm text-slate-500 mb-6">
        Company name/dates/price band/issue size auto-populate from NSE, listing date from the SEBI T+3 rule (or
        NSE's own confirmed date once known), the RHP link from SEBI's public filings (mainboard company IPOs, not
        InvITs/REITs — triggers the automated report), and lot size from Zerodha's public IPO pages. Sector stays
        admin-only — add it manually if you want it shown.
      </p>

      {loading ? (
        <div className="flex items-center justify-center py-12 text-slate-500 gap-3"><Loader2 className="animate-spin" size={18} /> Loading…</div>
      ) : (
        <div className="rounded-2xl overflow-hidden border border-white/10">
          <div className="overflow-x-auto">
            <table className="w-full min-w-[760px] text-left">
              <thead>
                <tr className="border-b border-white/10 text-slate-500 font-mono-ui text-[11px] uppercase tracking-[0.15em]">
                  <th className="px-4 py-3">Company</th>
                  <th className="px-4 py-3">Status</th>
                  <th className="px-4 py-3">Source</th>
                  <th className="px-4 py-3">RHP</th>
                  <th className="px-4 py-3">Report</th>
                  <th className="px-4 py-3 w-16"></th>
                </tr>
              </thead>
              <tbody>
                {ipos.map((ipo) => (
                  <tr key={ipo.id} className="border-b border-white/[0.05] last:border-0" data-testid={`admin-ipo-row-${ipo.id}`}>
                    <td className="px-4 py-3 text-sm text-white">{ipo.company_name}</td>
                    <td className="px-4 py-3"><span className="capitalize text-xs text-slate-400">{ipo.status}</span></td>
                    <td className="px-4 py-3 text-xs text-slate-500">{ipo.nse_symbol ? "NSE auto" : "Manual"}</td>
                    <td className="px-4 py-3 text-xs">{ipo.rhp_url ? <span className="text-emerald-400">Linked</span> : <span className="text-slate-600">—</span>}</td>
                    <td className="px-4 py-3 text-xs">
                      {ipo.report_error ? (
                        <span className="text-red-400">Error</span>
                      ) : ipo.short_report ? (
                        <span className="text-emerald-400">Ready</span>
                      ) : ipo.rhp_url ? (
                        <span className="text-amber-400">Generating</span>
                      ) : (
                        <span className="text-slate-600">—</span>
                      )}
                    </td>
                    <td className="px-4 py-3">
                      <button onClick={() => startEdit(ipo)} className="text-slate-500 hover:text-white transition-colors text-xs" data-testid={`admin-ipo-edit-${ipo.id}`}>
                        Edit
                      </button>
                    </td>
                  </tr>
                ))}
                {ipos.length === 0 && (
                  <tr><td colSpan={6} className="px-6 py-10 text-center text-slate-500 text-sm">No IPOs yet. Click "Refresh from NSE" or "Add IPO".</td></tr>
                )}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {editing && (
        <div className="mt-6 border-t border-white/10 pt-6">
          <h3 className="font-display text-base font-bold text-white mb-4">{editing.id ? "Edit IPO" : "Add IPO"}</h3>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-4">
            <div className="col-span-2">
              <label className="font-mono-ui text-[10px] uppercase tracking-[0.18em] text-slate-500 block mb-1.5">Company Name</label>
              <input value={editing.company_name} onChange={setField("company_name")} className={fld} data-testid="ipo-form-company" />
            </div>
            <div className="col-span-2">
              <label className="font-mono-ui text-[10px] uppercase tracking-[0.18em] text-slate-500 block mb-1.5">Sector</label>
              <input value={editing.sector} onChange={setField("sector")} className={fld} placeholder="e.g. Financial Services" data-testid="ipo-form-sector" />
            </div>
            <div>
              <label className="font-mono-ui text-[10px] uppercase tracking-[0.18em] text-slate-500 block mb-1.5">Issue Opens</label>
              <input type="date" value={editing.issue_open_date || ""} onChange={setField("issue_open_date")} className={fld} data-testid="ipo-form-open-date" />
            </div>
            <div>
              <label className="font-mono-ui text-[10px] uppercase tracking-[0.18em] text-slate-500 block mb-1.5">Issue Closes</label>
              <input type="date" value={editing.issue_close_date || ""} onChange={setField("issue_close_date")} className={fld} data-testid="ipo-form-close-date" />
            </div>
            <div>
              <label className="font-mono-ui text-[10px] uppercase tracking-[0.18em] text-slate-500 block mb-1.5">Listing Date</label>
              <input type="date" value={editing.listing_date || ""} onChange={setField("listing_date")} className={fld} data-testid="ipo-form-listing-date" />
            </div>
            <div>
              <label className="font-mono-ui text-[10px] uppercase tracking-[0.18em] text-slate-500 block mb-1.5">Lot Size</label>
              <input value={editing.lot_size} onChange={setField("lot_size")} className={fld} placeholder="e.g. 100" data-testid="ipo-form-lot-size" />
            </div>
            <div>
              <label className="font-mono-ui text-[10px] uppercase tracking-[0.18em] text-slate-500 block mb-1.5">Price Band Min (₹)</label>
              <input value={editing.price_band.min} onChange={setBandField("min")} className={fld} data-testid="ipo-form-price-min" />
            </div>
            <div>
              <label className="font-mono-ui text-[10px] uppercase tracking-[0.18em] text-slate-500 block mb-1.5">Price Band Max (₹)</label>
              <input value={editing.price_band.max} onChange={setBandField("max")} className={fld} data-testid="ipo-form-price-max" />
            </div>
            <div>
              <label className="font-mono-ui text-[10px] uppercase tracking-[0.18em] text-slate-500 block mb-1.5">Issue Size</label>
              <input value={editing.issue_size} onChange={setField("issue_size")} className={fld} placeholder="e.g. 91,93,800 shares" data-testid="ipo-form-issue-size" />
            </div>
            <div>
              <label className="font-mono-ui text-[10px] uppercase tracking-[0.18em] text-slate-500 block mb-1.5">Exchange</label>
              <div className="flex gap-2 pt-1.5">
                {EXCHANGES.map((ex) => (
                  <button
                    type="button"
                    key={ex}
                    onClick={() => toggleExchange(ex)}
                    className={`rounded-md border px-3 py-2 text-xs font-medium transition-colors ${
                      editing.exchange.includes(ex) ? "border-sapphire/40 bg-sapphire/10 text-sapphire-light" : "border-white/10 text-slate-500"
                    }`}
                    data-testid={`ipo-form-exchange-${ex}`}
                  >
                    {ex}
                  </button>
                ))}
              </div>
            </div>
            <div className="col-span-2 md:col-span-4">
              <label className="font-mono-ui text-[10px] uppercase tracking-[0.18em] text-slate-500 block mb-1.5">RHP PDF URL</label>
              <input value={editing.rhp_url} onChange={setField("rhp_url")} className={fld} placeholder="https://..." data-testid="ipo-form-rhp-url" />
              <p className="text-[11px] text-slate-600 mt-1">Saving a new or changed link kicks off automated report generation in the background — usually ready within a couple minutes.</p>
            </div>
          </div>
          <div className="flex items-center gap-3">
            <button onClick={save} disabled={saving} className="btn-sapphire disabled:opacity-70" data-testid="ipo-form-save-btn">
              {saving ? <><Loader2 size={16} className="animate-spin" /> Saving</> : <><Save size={15} /> Save IPO</>}
            </button>
            <button onClick={() => setEditing(null)} className="btn-ghost !px-4 !py-2 text-sm" data-testid="ipo-form-cancel-btn">
              <X size={15} /> Cancel
            </button>
          </div>
        </div>
      )}
    </div>
  );
};

/* --------------------------- Dashboard --------------------------- */
const Dashboard = ({ onLogout }) => {
  const [scanner, setScanner] = useState("momentum");
  const [rows, setRows] = useState([]);
  const [original, setOriginal] = useState([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [dragIndex, setDragIndex] = useState(null);

  const load = useCallback(async (sc) => {
    setLoading(true);
    try {
      const { data } = await axios.get(`${API}/terminal/stocks`, { params: { scanner: sc } });
      setRows(data);
      setOriginal(data);
    } catch {
      toast.error("Failed to load data.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(scanner); }, [scanner, load]);

  const dirty = JSON.stringify(rows) !== JSON.stringify(original);

  const updateRow = (id, key, value) =>
    setRows((rs) => rs.map((r) => (r.id === id ? { ...r, [key]: value } : r)));

  const addRow = () =>
    setRows((rs) => [
      ...rs,
      { id: tempId(), scanner, ticker: "", company: "", momentum_score: "", volume: "", bias: "Neutral", order: rs.length },
    ]);

  const removeRow = (id) => setRows((rs) => rs.filter((r) => r.id !== id));

  const onDrop = (targetIndex) => {
    if (dragIndex === null || dragIndex === targetIndex) return;
    setRows((rs) => {
      const copy = [...rs];
      const [moved] = copy.splice(dragIndex, 1);
      copy.splice(targetIndex, 0, moved);
      return copy;
    });
    setDragIndex(null);
  };

  const cancel = () => { setRows(original); toast.info("Changes discarded."); };

  const save = async () => {
    // validate
    for (const r of rows) {
      if (!r.ticker.trim()) { toast.error("Every row needs a Ticker."); return; }
    }
    setSaving(true);
    try {
      const origIds = original.map((r) => r.id);
      const currentIds = rows.map((r) => r.id);
      // deletions
      const deletions = origIds.filter((id) => !currentIds.includes(id));
      for (const id of deletions) {
        await axios.delete(`${API}/terminal/stocks/${id}`, authHeaders());
      }
      // creates + updates, keep resolved order
      const resolved = [];
      for (const r of rows) {
        const body = {
          scanner,
          ticker: r.ticker,
          company: r.company,
          momentum_score: r.momentum_score,
          volume: r.volume,
          bias: r.bias,
        };
        if (String(r.id).startsWith("new-")) {
          const { data } = await axios.post(`${API}/terminal/stocks`, body, authHeaders());
          resolved.push(data.id);
        } else {
          await axios.put(`${API}/terminal/stocks/${r.id}`, body, authHeaders());
          resolved.push(r.id);
        }
      }
      // reorder
      await axios.put(`${API}/terminal/stocks/reorder/apply`, { scanner, ordered_ids: resolved }, authHeaders());
      toast.success("Saved. The public terminal is now up to date.");
      await load(scanner);
    } catch (err) {
      if (err?.response?.status === 401) { toast.error("Session expired. Please sign in again."); onLogout(); return; }
      toast.error("Save failed. Please try again.");
    } finally {
      setSaving(false);
    }
  };

  const inputCls = "w-full bg-white/5 border border-white/10 rounded-md px-3 py-2 text-sm text-white outline-none focus:border-sapphire-light transition-colors";

  return (
    <div className="min-h-screen bg-void grid-bg" data-testid="admin-dashboard">
      <div className="border-b border-white/10 backdrop-blur-xl bg-void/70 sticky top-0 z-20">
        <div className="container-x flex items-center justify-between h-16">
          <div className="flex items-center gap-3">
            <span className="font-display font-extrabold text-white tracking-tight">Alpha Terminal</span>
            <span className="font-mono-ui text-[10px] uppercase tracking-[0.2em] text-sapphire-light">Admin</span>
          </div>
          <div className="flex items-center gap-3">
            <Link to="/alpha-terminal" className="text-sm text-slate-400 hover:text-white transition-colors">View site</Link>
            <button onClick={onLogout} className="btn-ghost !px-4 !py-2 text-sm" data-testid="admin-logout-btn">
              <LogOut size={14} /> Logout
            </button>
          </div>
        </div>
      </div>

      <div className="container-x py-10">
        <DefinedgeConnect onAuthError={onLogout} onSignalUpdate={() => {}} />
        <SignalPanel onAuthError={onLogout} />
        <QuantLabPanel onAuthError={onLogout} />
        <IpoPanel onAuthError={onLogout} />
        <BlackBoxPanel onAuthError={onLogout} />
        <MomentumTrackRecordPanel onAuthError={onLogout} />

        <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4 mb-8">
          <div>
            <h2 className="font-display text-2xl font-bold text-white">Manage Scanners</h2>
            <p className="text-sm text-slate-500 mt-1">Add, edit, reorder, or remove entries. Changes go live on Save.</p>
          </div>
          <select
            value={scanner}
            onChange={(e) => setScanner(e.target.value)}
            style={{ colorScheme: "dark" }}
            className="bg-[#0A0D18] border border-white/15 rounded-lg px-4 py-2.5 text-sm text-white outline-none focus:border-sapphire-light"
            data-testid="admin-scanner-select"
          >
            {SCANNERS.map((s) => <option key={s.key} value={s.key} className="bg-surface">{s.label}</option>)}
          </select>
        </div>

        {loading ? (
          <div className="flex items-center justify-center py-24 text-slate-500 gap-3"><Loader2 className="animate-spin" size={18} /> Loading…</div>
        ) : (
          <>
            <div className="glass rounded-2xl overflow-hidden">
              <div className="overflow-x-auto">
                <table className="w-full min-w-[860px] text-left">
                  <thead>
                    <tr className="border-b border-white/10 text-slate-500 font-mono-ui text-[11px] uppercase tracking-[0.15em]">
                      <th className="px-3 py-4 w-10"></th>
                      <th className="px-3 py-4">Ticker</th>
                      <th className="px-3 py-4">Company</th>
                      <th className="px-3 py-4 w-36">Momentum Score</th>
                      <th className="px-3 py-4 w-32">Volume</th>
                      <th className="px-3 py-4 w-40">Bias</th>
                      <th className="px-3 py-4 w-12"></th>
                    </tr>
                  </thead>
                  <tbody>
                    {rows.map((r, i) => (
                      <tr
                        key={r.id}
                        draggable
                        onDragStart={() => setDragIndex(i)}
                        onDragOver={(e) => e.preventDefault()}
                        onDrop={() => onDrop(i)}
                        className={`border-b border-white/[0.05] last:border-0 ${dragIndex === i ? "opacity-50" : ""}`}
                        data-testid={`admin-row-${i}`}
                      >
                        <td className="px-3 py-3 text-slate-600 cursor-grab active:cursor-grabbing" data-testid={`admin-drag-${i}`}><GripVertical size={16} /></td>
                        <td className="px-3 py-3"><input value={r.ticker} onChange={(e) => updateRow(r.id, "ticker", e.target.value)} className={inputCls} placeholder="NVDA" data-testid={`admin-ticker-${i}`} /></td>
                        <td className="px-3 py-3"><input value={r.company} onChange={(e) => updateRow(r.id, "company", e.target.value)} className={inputCls} placeholder="NVIDIA Corp." data-testid={`admin-company-${i}`} /></td>
                        <td className="px-3 py-3"><input value={r.momentum_score} onChange={(e) => updateRow(r.id, "momentum_score", e.target.value)} className={inputCls} placeholder="98.4" data-testid={`admin-score-${i}`} /></td>
                        <td className="px-3 py-3"><input value={r.volume} onChange={(e) => updateRow(r.id, "volume", e.target.value)} className={inputCls} placeholder="3.2x avg" data-testid={`admin-volume-${i}`} /></td>
                        <td className="px-3 py-3">
                          <select value={r.bias} onChange={(e) => updateRow(r.id, "bias", e.target.value)} style={{ colorScheme: "dark" }} className={inputCls} data-testid={`admin-bias-${i}`}>
                            {BIAS.map((b) => <option key={b} value={b} className="bg-surface">{b}</option>)}
                          </select>
                        </td>
                        <td className="px-3 py-3">
                          <button onClick={() => removeRow(r.id)} className="text-slate-500 hover:text-red-400 transition-colors p-1.5" data-testid={`admin-delete-${i}`} aria-label="Delete row">
                            <Trash2 size={16} />
                          </button>
                        </td>
                      </tr>
                    ))}
                    {rows.length === 0 && (
                      <tr><td colSpan={7} className="px-6 py-12 text-center text-slate-500 text-sm">No entries yet. Add a stock to activate this scanner.</td></tr>
                    )}
                  </tbody>
                </table>
              </div>
              <div className="px-4 py-4 border-t border-white/10">
                <button onClick={addRow} className="btn-ghost !px-4 !py-2 text-sm" data-testid="admin-add-btn"><Plus size={15} /> Add Stock</button>
              </div>
            </div>

            <div className="flex items-center gap-3 mt-8">
              <button onClick={save} disabled={saving || !dirty} className="btn-sapphire disabled:opacity-50" data-testid="admin-save-btn">
                {saving ? <><Loader2 size={16} className="animate-spin" /> Saving</> : <><Save size={15} /> Save Changes</>}
              </button>
              <button onClick={cancel} disabled={saving || !dirty} className="btn-ghost disabled:opacity-40" data-testid="admin-cancel-btn">
                <X size={15} /> Cancel
              </button>
              {dirty && <span className="font-mono-ui text-xs text-amber-400/80">Unsaved changes</span>}
            </div>
          </>
        )}
      </div>
    </div>
  );
};

/* ----------------------------- Root ----------------------------- */
export default function Admin() {
  const [authed, setAuthed] = useState(null); // null=checking, false=login, true=in

  useEffect(() => {
    const token = localStorage.getItem(TOKEN_KEY);
    if (!token) { setAuthed(false); return; }
    axios.get(`${API}/auth/me`, authHeaders())
      .then(() => setAuthed(true))
      .catch(() => { localStorage.removeItem(TOKEN_KEY); setAuthed(false); });
  }, []);

  const logout = () => { localStorage.removeItem(TOKEN_KEY); setAuthed(false); };

  if (authed === null) {
    return <div className="min-h-screen bg-void flex items-center justify-center text-slate-500"><Loader2 className="animate-spin" /></div>;
  }
  return authed ? <Dashboard onLogout={logout} /> : <Login onSuccess={() => setAuthed(true)} />;
}
