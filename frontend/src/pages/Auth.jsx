import { useState, useEffect } from "react";
import axios from "axios";
import { toast } from "sonner";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { Loader2, ShieldCheck, ArrowLeft, Mail, KeyRound, UserPlus } from "lucide-react";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;
export const TRADER_TOKEN_KEY = "sac_trader_token";

const field =
  "w-full bg-transparent border-b border-white/15 focus:border-sapphire-light outline-none text-white font-light py-3 placeholder:text-slate-600 transition-colors duration-300";

const errMsg = (err, fallback) => {
  const d = err?.response?.data?.detail;
  return typeof d === "string" ? d : fallback;
};

const AuthShell = ({ icon: Icon, title, subtitle, children }) => (
  <div className="min-h-screen bg-void grid-bg flex items-center justify-center px-6">
    <div className="absolute inset-0 radial-glow pointer-events-none" />
    <div className="glass rounded-3xl p-8 md:p-12 w-full max-w-md relative z-10">
      <div className="flex items-center gap-3 mb-8">
        <span className="h-10 w-10 rounded-xl bg-sapphire/15 border border-sapphire/30 flex items-center justify-center">
          <Icon size={18} className="text-sapphire-light" />
        </span>
        <div>
          <h1 className="font-display text-xl font-bold text-white">{title}</h1>
          <p className="font-mono-ui text-[10px] uppercase tracking-[0.2em] text-slate-500">{subtitle}</p>
        </div>
      </div>
      {children}
      <Link to="/" className="mt-6 inline-flex items-center gap-2 text-slate-500 hover:text-white transition-colors text-sm">
        <ArrowLeft size={14} /> Back to site
      </Link>
    </div>
  </div>
);

/* ----------------------------- Sign up ----------------------------- */
export const SignupPage = () => {
  const [form, setForm] = useState({ name: "", email: "", password: "" });
  const [loading, setLoading] = useState(false);
  const [done, setDone] = useState(false);
  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }));

  const submit = async (e) => {
    e.preventDefault();
    setLoading(true);
    try {
      await axios.post(`${API}/auth/signup`, form);
      setDone(true);
      toast.success("Account created — check your email.");
    } catch (err) {
      toast.error(errMsg(err, "Signup failed."));
    } finally {
      setLoading(false);
    }
  };

  if (done) {
    return (
      <AuthShell icon={UserPlus} title="Check your email" subtitle="Sapphire Trading Journal">
        <p className="text-sm text-slate-400 leading-relaxed">
          We've sent a verification link to <span className="text-white">{form.email}</span>. Click it to activate your account, then sign in.
        </p>
        <Link to="/login" className="btn-sapphire w-full mt-8 inline-flex items-center justify-center">Go to Sign In</Link>
      </AuthShell>
    );
  }

  return (
    <AuthShell icon={UserPlus} title="Create Account" subtitle="Sapphire Trading Journal">
      <form onSubmit={submit} data-testid="signup-form">
        <div className="space-y-6">
          <div>
            <label className="font-mono-ui text-[11px] uppercase tracking-[0.2em] text-slate-500 block mb-2">Name</label>
            <input value={form.name} onChange={set("name")} className={field} placeholder="Your name" data-testid="signup-name" required />
          </div>
          <div>
            <label className="font-mono-ui text-[11px] uppercase tracking-[0.2em] text-slate-500 block mb-2">Email</label>
            <input type="email" value={form.email} onChange={set("email")} className={field} placeholder="you@example.com" data-testid="signup-email" required />
          </div>
          <div>
            <label className="font-mono-ui text-[11px] uppercase tracking-[0.2em] text-slate-500 block mb-2">Password</label>
            <input type="password" value={form.password} onChange={set("password")} className={field} placeholder="••••••••" data-testid="signup-password" required />
          </div>
        </div>
        <button type="submit" disabled={loading} className="btn-sapphire w-full mt-10 disabled:opacity-70" data-testid="signup-submit-btn">
          {loading ? <><Loader2 size={16} className="animate-spin" /> Creating account</> : "Create Account"}
        </button>
        <p className="mt-6 text-sm text-slate-500">
          Already have an account? <Link to="/login" className="text-sapphire-light hover:underline">Sign in</Link>
        </p>
      </form>
    </AuthShell>
  );
};

/* ----------------------------- Login ----------------------------- */
export const LoginPage = () => {
  const [form, setForm] = useState({ email: "", password: "" });
  const [loading, setLoading] = useState(false);
  const navigate = useNavigate();
  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }));

  useEffect(() => {
    const token = localStorage.getItem(TRADER_TOKEN_KEY);
    if (!token) return;
    axios.get(`${API}/auth/me`, { headers: { Authorization: `Bearer ${token}` } })
      .then(() => navigate("/journal", { replace: true }))
      .catch(() => localStorage.removeItem(TRADER_TOKEN_KEY));
  }, [navigate]);

  const submit = async (e) => {
    e.preventDefault();
    setLoading(true);
    try {
      const { data } = await axios.post(`${API}/auth/login`, form, { withCredentials: true });
      localStorage.setItem(TRADER_TOKEN_KEY, data.access_token);
      toast.success("Signed in.");
      navigate("/journal");
    } catch (err) {
      toast.error(errMsg(err, "Login failed."));
    } finally {
      setLoading(false);
    }
  };

  return (
    <AuthShell icon={ShieldCheck} title="Sign In" subtitle="Sapphire Trading Journal">
      <form onSubmit={submit} data-testid="login-form">
        <div className="space-y-6">
          <div>
            <label className="font-mono-ui text-[11px] uppercase tracking-[0.2em] text-slate-500 block mb-2">Email</label>
            <input type="email" value={form.email} onChange={set("email")} className={field} placeholder="you@example.com" data-testid="login-email" required />
          </div>
          <div>
            <label className="font-mono-ui text-[11px] uppercase tracking-[0.2em] text-slate-500 block mb-2">Password</label>
            <input type="password" value={form.password} onChange={set("password")} className={field} placeholder="••••••••" data-testid="login-password" required />
          </div>
        </div>
        <button type="submit" disabled={loading} className="btn-sapphire w-full mt-10 disabled:opacity-70" data-testid="login-submit-btn">
          {loading ? <><Loader2 size={16} className="animate-spin" /> Signing in</> : "Sign In"}
        </button>
        <div className="mt-6 flex items-center justify-between text-sm">
          <Link to="/signup" className="text-sapphire-light hover:underline">Create account</Link>
          <Link to="/forgot-password" className="text-slate-500 hover:text-white transition-colors">Forgot password?</Link>
        </div>
      </form>
    </AuthShell>
  );
};

/* ------------------------- Forgot password ------------------------- */
export const ForgotPasswordPage = () => {
  const [email, setEmail] = useState("");
  const [loading, setLoading] = useState(false);
  const [done, setDone] = useState(false);

  const submit = async (e) => {
    e.preventDefault();
    setLoading(true);
    try {
      await axios.post(`${API}/auth/request-password-reset`, { email });
      setDone(true);
    } catch (err) {
      toast.error(errMsg(err, "Something went wrong."));
    } finally {
      setLoading(false);
    }
  };

  if (done) {
    return (
      <AuthShell icon={Mail} title="Check your email" subtitle="Sapphire Trading Journal">
        <p className="text-sm text-slate-400 leading-relaxed">
          If an account exists for <span className="text-white">{email}</span>, a reset link is on its way. The link expires in 1 hour.
        </p>
      </AuthShell>
    );
  }

  return (
    <AuthShell icon={Mail} title="Reset Password" subtitle="Sapphire Trading Journal">
      <form onSubmit={submit} data-testid="forgot-password-form">
        <label className="font-mono-ui text-[11px] uppercase tracking-[0.2em] text-slate-500 block mb-2">Email</label>
        <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} className={field} placeholder="you@example.com" data-testid="forgot-password-email" required />
        <button type="submit" disabled={loading} className="btn-sapphire w-full mt-10 disabled:opacity-70" data-testid="forgot-password-submit-btn">
          {loading ? <><Loader2 size={16} className="animate-spin" /> Sending</> : "Send Reset Link"}
        </button>
      </form>
    </AuthShell>
  );
};

/* --------------------------- Reset password -------------------------- */
export const ResetPasswordPage = () => {
  const [params] = useSearchParams();
  const token = params.get("token") || "";
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [done, setDone] = useState(false);
  const navigate = useNavigate();

  const submit = async (e) => {
    e.preventDefault();
    setLoading(true);
    try {
      await axios.post(`${API}/auth/reset-password`, { token, new_password: password });
      setDone(true);
      toast.success("Password updated.");
    } catch (err) {
      toast.error(errMsg(err, "Reset failed."));
    } finally {
      setLoading(false);
    }
  };

  if (!token) {
    return (
      <AuthShell icon={KeyRound} title="Invalid Link" subtitle="Sapphire Trading Journal">
        <p className="text-sm text-slate-400">This password reset link is missing its token. Request a new one.</p>
        <Link to="/forgot-password" className="btn-sapphire w-full mt-8 inline-flex items-center justify-center">Request New Link</Link>
      </AuthShell>
    );
  }

  if (done) {
    return (
      <AuthShell icon={KeyRound} title="Password Updated" subtitle="Sapphire Trading Journal">
        <p className="text-sm text-slate-400 mb-8">Your password has been changed.</p>
        <button onClick={() => navigate("/login")} className="btn-sapphire w-full">Sign In</button>
      </AuthShell>
    );
  }

  return (
    <AuthShell icon={KeyRound} title="Choose New Password" subtitle="Sapphire Trading Journal">
      <form onSubmit={submit} data-testid="reset-password-form">
        <label className="font-mono-ui text-[11px] uppercase tracking-[0.2em] text-slate-500 block mb-2">New Password</label>
        <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} className={field} placeholder="••••••••" data-testid="reset-password-input" required />
        <button type="submit" disabled={loading} className="btn-sapphire w-full mt-10 disabled:opacity-70" data-testid="reset-password-submit-btn">
          {loading ? <><Loader2 size={16} className="animate-spin" /> Updating</> : "Update Password"}
        </button>
      </form>
    </AuthShell>
  );
};

/* --------------------------- Verify email --------------------------- */
export const VerifyEmailPage = () => {
  const [params] = useSearchParams();
  const token = params.get("token") || "";
  const [status, setStatus] = useState("verifying"); // verifying | success | error
  const [message, setMessage] = useState("");

  useEffect(() => {
    if (!token) { setStatus("error"); setMessage("Missing verification token."); return; }
    axios.get(`${API}/auth/verify-email`, { params: { token } })
      .then(() => setStatus("success"))
      .catch((err) => { setStatus("error"); setMessage(errMsg(err, "Verification failed.")); });
  }, [token]);

  return (
    <AuthShell icon={ShieldCheck} title="Email Verification" subtitle="Sapphire Trading Journal">
      {status === "verifying" && (
        <p className="text-sm text-slate-400 flex items-center gap-2"><Loader2 size={16} className="animate-spin" /> Verifying…</p>
      )}
      {status === "success" && (
        <>
          <p className="text-sm text-slate-400 mb-8">Your email is verified. You can now sign in.</p>
          <Link to="/login" className="btn-sapphire w-full inline-flex items-center justify-center">Sign In</Link>
        </>
      )}
      {status === "error" && <p className="text-sm text-red-400">{message}</p>}
    </AuthShell>
  );
};
