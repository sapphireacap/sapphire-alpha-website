import { useEffect, useState } from "react";
import axios from "axios";
import { motion } from "framer-motion";
import { toast } from "sonner";
import { useNavigate } from "react-router-dom";
import { Lock, ArrowUpRight, Loader2 } from "lucide-react";
import Navbar from "../components/site/Navbar";
import Footer from "../components/site/Footer";
import Reveal from "../components/site/Reveal";
import { TRADER_TOKEN_KEY } from "./Auth";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;
const EASE = [0.16, 1, 0.3, 1];
const RAZORPAY_SCRIPT_SRC = "https://checkout.razorpay.com/v1/checkout.js";

// Same script-loading pattern as PnfStudio.jsx — see that file's comment.
let razorpayScriptPromise = null;
const loadRazorpayScript = () => {
  if (window.Razorpay) return Promise.resolve(true);
  if (razorpayScriptPromise) return razorpayScriptPromise;
  razorpayScriptPromise = new Promise((resolve) => {
    const script = document.createElement("script");
    script.src = RAZORPAY_SCRIPT_SRC;
    script.onload = () => resolve(true);
    script.onerror = () => resolve(false);
    document.body.appendChild(script);
  });
  return razorpayScriptPromise;
};

// Renko Studio is covered by the same paid access as P&F Studio — one
// subscription, both charting products (pnf_access_until gates both).
// Figures kept in sync with PnfStudio.jsx/Pricing.jsx by hand, same as
// that file already does.
const CYCLES = [
  { key: "monthly", label: "Monthly", months: 1, price: 49 },
  { key: "quarterly", label: "Quarterly", months: 3, price: 129 },
  { key: "yearly", label: "Yearly", months: 12, price: 444 },
];

const fmtDate = (iso) =>
  new Date(iso).toLocaleDateString("en-US", { year: "numeric", month: "long", day: "numeric" });

export default function RenkoStudio() {
  const navigate = useNavigate();
  const [status, setStatus] = useState("loading"); // loading | logged-out | no-access | active
  const [user, setUser] = useState(null);
  const [cycleKey, setCycleKey] = useState("monthly");
  const [paying, setPaying] = useState(false);
  const cycle = CYCLES.find((c) => c.key === cycleKey);

  const refreshMe = () => {
    const token = localStorage.getItem(TRADER_TOKEN_KEY);
    if (!token) { setStatus("logged-out"); return; }
    return axios.get(`${API}/auth/me`, { headers: { Authorization: `Bearer ${token}` } })
      .then((r) => {
        setUser(r.data);
        const hasAccess = r.data.role === "admin" ||
          (r.data.pnf_access_until && new Date(r.data.pnf_access_until) > new Date());
        setStatus(hasAccess ? "active" : "no-access");
      })
      .catch(() => { localStorage.removeItem(TRADER_TOKEN_KEY); setStatus("logged-out"); });
  };

  useEffect(() => { refreshMe(); }, []);

  const authHeaders = () => ({ headers: { Authorization: `Bearer ${localStorage.getItem(TRADER_TOKEN_KEY)}` } });

  const pay = async () => {
    setPaying(true);
    try {
      const ready = await loadRazorpayScript();
      if (!ready) { toast.error("Couldn't load checkout. Check your connection and try again."); return; }

      const { data: order } = await axios.post(`${API}/pnf-access/checkout`, { cycle: cycleKey }, authHeaders());

      const rzp = new window.Razorpay({
        key: order.key_id,
        amount: order.amount,
        currency: order.currency,
        order_id: order.order_id,
        name: "Sapphire Alpha Capital",
        description: `Renko Studio — ${cycle.label}`,
        prefill: { email: user?.email },
        theme: { color: "#1F5FD0" },
        handler: async (response) => {
          try {
            await axios.post(`${API}/pnf-access/verify`, response, authHeaders());
            toast.success("Payment received — Renko Studio is unlocked.");
            await refreshMe();
          } catch (err) {
            toast.error("Payment received but verification failed. Contact support if access doesn't appear shortly.");
          } finally {
            setPaying(false);
          }
        },
        modal: { ondismiss: () => setPaying(false) },
      });
      rzp.on("payment.failed", () => { toast.error("Payment failed. Please try again."); setPaying(false); });
      rzp.open();
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Could not start checkout. Please try again shortly.");
      setPaying(false);
    }
  };

  return (
    <>
      <Navbar />
      <main className="relative bg-void min-h-screen">
        <section className="relative pt-36 pb-16 md:pt-44 md:pb-20 overflow-hidden" data-testid="renko-studio-hero">
          <div className="absolute inset-0 radial-glow" />
          <div className="absolute inset-0 bg-gradient-to-b from-void/0 to-void pointer-events-none" />
          <div className="container-x relative z-10">
            <motion.div
              initial={{ opacity: 0, y: 24 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.9, ease: EASE }}
              className="flex items-center gap-2 mb-5"
            >
              <Lock size={13} className="text-sapphire-light" />
              <span className="font-mono-ui text-xs uppercase tracking-[0.2em] text-sapphire-light">Paid Access Only</span>
            </motion.div>
            <motion.h1
              initial={{ opacity: 0, y: 24 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.9, ease: EASE, delay: 0.05 }}
              className="font-display font-normal tracking-[-0.015em] text-white text-5xl md:text-7xl leading-[0.95]"
            >
              Renko Studio
            </motion.h1>
            <motion.p
              initial={{ opacity: 0, y: 24 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.9, ease: EASE, delay: 0.1 }}
              className="mt-6 text-base md:text-lg font-light text-slate-400 leading-relaxed max-w-2xl"
            >
              Built for traders who read price through Renko brick charts. Analyze market structure with
              brick-pattern recognition, adapted indicators, and relative strength — the same workspace discipline
              as P&amp;F Studio, one subscription covers both.
            </motion.p>
          </div>
        </section>

        <section className="relative pb-28 md:pb-40">
          <div className="container-x max-w-lg mx-auto">
            <Reveal className="rounded-2xl border border-white/10 bg-white/[0.02] p-6 md:p-8" data-testid="renko-studio-access-panel">
              {status === "loading" && (
                <div className="flex items-center justify-center py-12 text-slate-500">
                  <Loader2 className="animate-spin" size={20} />
                </div>
              )}

              {status === "logged-out" && (
                <div data-testid="renko-studio-logged-out">
                  <h3 className="text-lg font-bold text-white">Sign in to continue</h3>
                  <p className="mt-2 text-sm text-slate-400 leading-relaxed">
                    Renko Studio requires an account. Sign in if you already have one, or create one to get started.
                  </p>
                  <div className="mt-6 flex flex-col sm:flex-row gap-3">
                    <button onClick={() => navigate("/login", { state: { from: "/renko-studio" } })} className="btn-sapphire flex-1" data-testid="renko-studio-login-btn">
                      Log In
                    </button>
                    <button
                      onClick={() => navigate("/signup", { state: { from: "/renko-studio" } })}
                      className="flex-1 rounded-md border border-white/15 text-white hover:border-white/30 hover:bg-white/5 transition-colors text-sm font-medium py-2.5"
                      data-testid="renko-studio-signup-btn"
                    >
                      Create Account
                    </button>
                  </div>
                </div>
              )}

              {status === "no-access" && (
                <div data-testid="renko-studio-no-access">
                  <h3 className="text-lg font-bold text-white">Activate a plan</h3>
                  <p className="mt-2 text-sm text-slate-400 leading-relaxed">
                    Signed in as <span className="text-white">{user?.email}</span>. Choose a billing cycle to request access.
                  </p>

                  <div className="mt-6 inline-flex rounded-full border border-white/10 p-1" data-testid="renko-studio-cycle-toggle">
                    {CYCLES.map((c) => (
                      <button
                        key={c.key}
                        onClick={() => setCycleKey(c.key)}
                        className={`rounded-full px-4 py-1.5 font-mono-ui text-[11px] uppercase tracking-[0.14em] transition-colors duration-300 ${
                          cycleKey === c.key ? "bg-sapphire-light text-void font-semibold" : "text-slate-400 hover:text-white"
                        }`}
                        data-testid={`renko-studio-cycle-${c.key}`}
                      >
                        {c.label}
                      </button>
                    ))}
                  </div>

                  <div className="mt-5 flex items-end gap-1.5">
                    <span className="font-display text-3xl font-normal tracking-[-0.015em] text-white">${cycle.price}</span>
                    <span className="text-sm text-slate-500 mb-1">/ {cycle.label.toLowerCase()}</span>
                  </div>

                  <button
                    onClick={pay}
                    disabled={paying}
                    className="btn-sapphire w-full mt-6 disabled:opacity-70"
                    data-testid="renko-studio-subscribe-btn"
                  >
                    {paying ? <><Loader2 size={16} className="animate-spin" /> Processing</> : `Subscribe — $${cycle.price}`}
                  </button>
                  <p className="mt-3 text-xs text-slate-500 leading-relaxed">
                    Secure checkout via Razorpay. Access activates immediately after payment, and covers P&amp;F Studio too.
                  </p>
                </div>
              )}

              {status === "active" && (
                <div data-testid="renko-studio-active">
                  <h3 className="text-lg font-bold text-white">You're all set</h3>
                  <p className="mt-2 text-sm text-slate-400 leading-relaxed">
                    Signed in as <span className="text-white">{user?.email}</span>.{" "}
                    {user?.role === "admin"
                      ? "Admin accounts always have access."
                      : <>Access is active until <span className="text-white">{fmtDate(user.pnf_access_until)}</span>.</>}
                  </p>
                  <button
                    onClick={() => navigate("/alpha-terminal/renko")}
                    className="btn-sapphire w-full mt-6 inline-flex items-center justify-center gap-2"
                    data-testid="renko-studio-open-btn"
                  >
                    Open Renko Studio <ArrowUpRight size={15} />
                  </button>
                </div>
              )}
            </Reveal>
          </div>
        </section>
      </main>
      <Footer />
    </>
  );
}
