import { Link } from "react-router-dom";
import { Lock, ArrowUpRight } from "lucide-react";
import Navbar from "./Navbar";
import Footer from "./Footer";

// Shared "not available in your country" placeholder -- used by every nav
// entry that isn't actually public yet (P&F Studio, Log In / Sign Up).
// Generic on purpose: same page/route regardless of which link sent the
// visitor here, so the copy never names a specific feature.
export default function NotAvailablePage() {
  return (
    <>
      <Navbar />
      <main className="relative bg-void min-h-screen flex items-center justify-center px-6">
        <div className="text-center max-w-md">
          <div className="inline-flex items-center gap-2 rounded-full border border-white/10 px-4 py-1.5 mb-6">
            <Lock size={12} className="text-slate-500" />
            <span className="font-mono-ui text-xs uppercase tracking-wider text-slate-400">Not Available</span>
          </div>
          <h1 className="font-display font-normal tracking-[-0.015em] text-white text-3xl md:text-4xl leading-[0.95] mb-4">
            Not Available In Your Country
          </h1>
          <p className="text-sm font-light text-slate-500 leading-relaxed mb-8">
            This feature is not available for your country.
          </p>
          <Link to="/" className="inline-flex items-center gap-1.5 text-sapphire-light hover:text-white transition-colors text-sm font-medium">
            Back to home <ArrowUpRight size={15} />
          </Link>
        </div>
      </main>
      <Footer />
    </>
  );
}
