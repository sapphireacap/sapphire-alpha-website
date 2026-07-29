import { Link } from "react-router-dom";
import { Lock, ArrowUpRight } from "lucide-react";
import Navbar from "./Navbar";
import Footer from "./Footer";

// Full-page "temporarily paused" notice, reused for any top-level section
// that's been paused (2026-07-29, to cut backend memory/load) without
// deleting its real page component or backend code -- App.js just points
// the route here instead of at the real page for now. Not to be confused
// with ComingSoon.jsx (the landing page's waitlist section) -- different
// component, different purpose.
export default function PausedFeature({ title, description }) {
  return (
    <>
      <Navbar />
      <main className="relative bg-void min-h-screen flex items-center justify-center px-6">
        <div className="text-center max-w-md">
          <div className="inline-flex items-center gap-2 rounded-full border border-white/10 px-4 py-1.5 mb-6">
            <Lock size={12} className="text-slate-500" />
            <span className="font-mono-ui text-xs uppercase tracking-wider text-slate-400">Coming Soon</span>
          </div>
          <h1 className="font-display font-black tracking-tighter text-white text-3xl md:text-4xl leading-[0.95] mb-4">{title}</h1>
          {description && <p className="text-sm font-light text-slate-500 leading-relaxed mb-8">{description}</p>}
          <Link to="/" className="inline-flex items-center gap-1.5 text-sapphire-light hover:text-white transition-colors text-sm font-medium">
            Back to home <ArrowUpRight size={15} />
          </Link>
        </div>
      </main>
      <Footer />
    </>
  );
}
