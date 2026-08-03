import { useEffect, useState } from "react";
import axios from "axios";
import { Link } from "react-router-dom";
import { Lock, Loader2, ArrowUpRight } from "lucide-react";
import Navbar from "./Navbar";
import Footer from "./Footer";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;

// P&F Studio isn't public yet -- this route exists only to show the right
// placeholder message, not the real (still admin-gated) tool at
// /alpha-terminal/pnf. India specifically gets a hard "not available" via
// an IP-based lookup (see the /geo/country backend route's own note on
// why that has to be a backend call, not something the browser can
// determine on its own); everywhere else gets a plain "coming soon".
export default function PnfStudioGate() {
  const [status, setStatus] = useState("checking"); // checking | blocked | soon

  useEffect(() => {
    let cancelled = false;
    axios.get(`${API}/geo/country`)
      .then(({ data }) => { if (!cancelled) setStatus(data?.country_code === "IN" ? "blocked" : "soon"); })
      .catch(() => { if (!cancelled) setStatus("soon"); });
    return () => { cancelled = true; };
  }, []);

  const blocked = status === "blocked";

  return (
    <>
      <Navbar />
      <main className="relative bg-void min-h-screen flex items-center justify-center px-6">
        <div className="text-center max-w-md">
          {status === "checking" ? (
            <Loader2 className="w-5 h-5 animate-spin text-slate-500 mx-auto mb-6" />
          ) : (
            <div className="inline-flex items-center gap-2 rounded-full border border-white/10 px-4 py-1.5 mb-6">
              <Lock size={12} className="text-slate-500" />
              <span className="font-mono-ui text-xs uppercase tracking-wider text-slate-400">
                {blocked ? "Not Available" : "Coming Soon"}
              </span>
            </div>
          )}
          <h1 className="font-display font-black tracking-tighter text-white text-3xl md:text-4xl leading-[0.95] mb-4">
            P&amp;F Studio
          </h1>
          {status !== "checking" && (
            <p className="text-sm font-light text-slate-500 leading-relaxed mb-8">
              {blocked
                ? "P&F Studio is not available for your country."
                : "P&F Studio is coming soon."}
            </p>
          )}
          <Link to="/" className="inline-flex items-center gap-1.5 text-sapphire-light hover:text-white transition-colors text-sm font-medium">
            Back to home <ArrowUpRight size={15} />
          </Link>
        </div>
      </main>
      <Footer />
    </>
  );
}
