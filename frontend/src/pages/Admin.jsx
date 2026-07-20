import { useEffect, useState, useCallback } from "react";
import axios from "axios";
import { toast } from "sonner";
import { Link } from "react-router-dom";
import {
  Loader2, LogOut, Plus, Trash2, GripVertical, Save, X, ArrowLeft, ShieldCheck,
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

/* ------------------------ Straddle Compass panel ------------------------ */
const BIAS_OPTS = ["Neutral", "Bullish", "Bearish"];
const TREND_OPTS = ["Neutral", "Bullish", "Bearish"];

const SignalPanel = ({ onAuthError }) => {
  const empty = { bias: "Neutral", spot: "", atm: "", up_strike: "", up_trend: "Neutral", down_strike: "", down_trend: "Neutral", note: "", source: "manual" };
  const [sig, setSig] = useState(empty);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    axios.get(`${API}/terminal/signal`).then((r) => setSig({ ...empty, ...r.data })).catch(() => {});
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const set = (k) => (e) => setSig((s) => ({ ...s, [k]: e.target.value }));

  const save = async () => {
    setSaving(true);
    try {
      const { data } = await axios.put(`${API}/terminal/signal`, sig, authHeaders());
      setSig((s) => ({ ...s, ...data }));
      toast.success("Straddle Compass updated. Live on the terminal.");
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
        <h2 className="font-display text-xl font-bold text-white">Straddle Compass</h2>
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
        <SignalPanel onAuthError={onLogout} />

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
