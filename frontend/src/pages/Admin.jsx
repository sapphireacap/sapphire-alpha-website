import { useEffect, useState, useCallback } from "react";
import axios from "axios";
import { toast } from "sonner";
import { Link } from "react-router-dom";
import {
  Loader2, LogOut, Plus, Trash2, GripVertical, Save, X, ArrowLeft, ShieldCheck,
  Wifi, WifiOff, RefreshCw, ChevronDown,
} from "lucide-react";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;
const TOKEN_KEY = "sac_admin_token";

const SCANNERS = [
  { key: "momentum", label: "Momentum Leaders" },
  { key: "relative_strength", label: "Relative Strength Leaders" },
  { key: "breakout", label: "Breakout Candidates" },
  { key: "positional", label: "Positional Opportunities" },
];
const BIAS = ["Bullish", "Bearish", "Neutral"];

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
      toast.success("Definedge connected.");
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

  const refreshNow = async () => {
    setRefreshing(true);
    try {
      const { data } = await axios.post(`${API}/admin/definedge/refresh`, {}, authHeaders());
      onSignalUpdate(data);
      toast.success("Sapphire Nifty Vector refreshed from live data.");
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
        <h2 className="font-display text-xl font-bold text-white">Definedge Live Connection</h2>
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

const SignalPanel = ({ onAuthError, signal }) => {
  const empty = { bias: "Neutral", spot: "", atm: "", up_strike: "", up_trend: "Neutral", down_strike: "", down_trend: "Neutral", note: "", source: "manual" };
  const [sig, setSig] = useState(empty);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (signal) setSig((s) => ({ ...empty, ...signal }));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [signal]);

  const set = (k) => (e) => setSig((s) => ({ ...s, [k]: e.target.value }));

  const save = async () => {
    setSaving(true);
    try {
      const { data } = await axios.put(`${API}/terminal/signal`, sig, authHeaders());
      setSig((s) => ({ ...s, ...data }));
      toast.success("Sapphire Nifty Vector updated. Live on the terminal.");
    } catch (err) {
      if (err?.response?.status === 401) { toast.error("Session expired."); onAuthError(); return; }
      toast.error("Failed to save signal.");
    } finally {
      setSaving(false);
    }
  };

  const fld = "w-full bg-white/5 border border-white/10 rounded-md px-3 py-2 text-sm text-white outline-none focus:border-sapphire-light transition-colors";
  const sel = fld + " [color-scheme:dark]";

  return (
    <div className="glass rounded-2xl p-6 md:p-8 mb-10" data-testid="admin-signal-panel">
      <div className="flex items-center gap-3 mb-2">
        <h2 className="font-display text-xl font-bold text-white">Sapphire Nifty Vector</h2>
        <span className="font-mono-ui text-[10px] uppercase tracking-[0.2em] text-sapphire-light">Nifty Bias</span>
      </div>
      <p className="text-sm text-slate-500 mb-6">
        Set the ATM ±200 straddle trends. Leave Bias on <em>Neutral</em> to auto-derive it from the two legs
        (falling +200 &amp; rising −200 ⇒ Bullish).
      </p>
      <div className="grid grid-cols-2 md:grid-cols-4 gap-5">
        <div>
          <label className="font-mono-ui text-[10px] uppercase tracking-[0.18em] text-slate-500 block mb-1.5">Bias</label>
          <select value={sig.bias} onChange={set("bias")} style={{ colorScheme: "dark" }} className={sel} data-testid="signal-bias">
            {BIAS_OPTS.map((b) => <option key={b} value={b} className="bg-surface">{b === "Neutral" ? "Neutral (auto)" : b}</option>)}
          </select>
        </div>
        <div>
          <label className="font-mono-ui text-[10px] uppercase tracking-[0.18em] text-slate-500 block mb-1.5">Spot</label>
          <input value={sig.spot} onChange={set("spot")} className={fld} placeholder="24,000" data-testid="signal-spot" />
        </div>
        <div>
          <label className="font-mono-ui text-[10px] uppercase tracking-[0.18em] text-slate-500 block mb-1.5">ATM</label>
          <input value={sig.atm} onChange={set("atm")} className={fld} placeholder="24000" data-testid="signal-atm" />
        </div>
        <div className="hidden md:block" />
        <div>
          <label className="font-mono-ui text-[10px] uppercase tracking-[0.18em] text-slate-500 block mb-1.5">ATM +200 strike</label>
          <input value={sig.up_strike} onChange={set("up_strike")} className={fld} placeholder="24200" data-testid="signal-up-strike" />
        </div>
        <div>
          <label className="font-mono-ui text-[10px] uppercase tracking-[0.18em] text-slate-500 block mb-1.5">+200 straddle trend</label>
          <select value={sig.up_trend} onChange={set("up_trend")} style={{ colorScheme: "dark" }} className={sel} data-testid="signal-up-trend">
            {TREND_OPTS.map((t) => <option key={t} value={t} className="bg-surface">{t === "Bullish" ? "Rising" : t === "Bearish" ? "Falling" : "Flat"}</option>)}
          </select>
        </div>
        <div>
          <label className="font-mono-ui text-[10px] uppercase tracking-[0.18em] text-slate-500 block mb-1.5">ATM −200 strike</label>
          <input value={sig.down_strike} onChange={set("down_strike")} className={fld} placeholder="23800" data-testid="signal-down-strike" />
        </div>
        <div>
          <label className="font-mono-ui text-[10px] uppercase tracking-[0.18em] text-slate-500 block mb-1.5">−200 straddle trend</label>
          <select value={sig.down_trend} onChange={set("down_trend")} style={{ colorScheme: "dark" }} className={sel} data-testid="signal-down-trend">
            {TREND_OPTS.map((t) => <option key={t} value={t} className="bg-surface">{t === "Bullish" ? "Rising" : t === "Bearish" ? "Falling" : "Flat"}</option>)}
          </select>
        </div>
      </div>
      <div className="mt-5">
        <label className="font-mono-ui text-[10px] uppercase tracking-[0.18em] text-slate-500 block mb-1.5">Note (optional)</label>
        <input value={sig.note} onChange={set("note")} className={fld} placeholder="Context shown under the bias" data-testid="signal-note" />
      </div>
      <button onClick={save} disabled={saving} className="btn-sapphire mt-6 disabled:opacity-70" data-testid="signal-save-btn">
        {saving ? <><Loader2 size={16} className="animate-spin" /> Saving</> : <><Save size={15} /> Update Compass</>}
      </button>
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
          <button onClick={() => startEdit(null)} className="btn-sapphire !px-4 !py-2 text-sm" data-testid="ipo-add-btn">
            <Plus size={15} /> Add IPO
          </button>
        </div>
      </div>
      <p className="text-sm text-slate-500 mb-6">
        Company name/dates/price band/issue size auto-populate from NSE's public IPO listings where available — add
        the RHP link (plus sector/lot size, which NSE's feed doesn't expose) to trigger the AI report.
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
              <p className="text-[11px] text-slate-600 mt-1">Saving a new or changed link kicks off AI report generation in the background — usually ready within a couple minutes.</p>
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
  const [signal, setSignal] = useState(null);

  useEffect(() => {
    axios.get(`${API}/terminal/signal`).then((r) => setSignal(r.data)).catch(() => {});
  }, []);

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
        <DefinedgeConnect onAuthError={onLogout} onSignalUpdate={setSignal} />
        <SignalPanel onAuthError={onLogout} signal={signal} />
        <IpoPanel onAuthError={onLogout} />

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
