import { useEffect } from "react";
import { Link } from "react-router-dom";
import { ArrowLeft } from "lucide-react";
import { LEGAL, SITE } from "@/content/homepage";
import LOGO from "../../assets/sac-logo-mark.svg";

export const LegalPage = ({ page }) => {
  const data = LEGAL[page];
  useEffect(() => {
    window.scrollTo(0, 0);
  }, [page]);

  if (!data) return null;

  return (
    <main id="main" className="min-h-screen bg-void grid-bg" data-testid={`legal-${page}`}>
      <div className="container-x py-16 md:py-24 max-w-3xl">
        <div className="flex items-center justify-between mb-16">
          <Link to="/" className="inline-flex items-center gap-2 text-slate-400 hover:text-white transition-colors text-sm" data-testid="legal-back-link">
            <ArrowLeft size={16} /> Back to home
          </Link>
          <span className="logo-pill p-1 flex items-center justify-center">
            <img src={LOGO} alt="Sapphire Alpha Capital" className="h-7 w-7 object-contain" />
          </span>
        </div>

        <p className="label-mono mb-4">Legal</p>
        <h1 className="font-display font-normal tracking-[-0.015em] text-white text-4xl md:text-6xl mb-3">{data.title}</h1>
        <p className="font-mono-ui text-xs text-slate-400 mb-12">{data.updated}</p>
        <p className="text-base md:text-lg font-light text-slate-300 leading-relaxed mb-14">{data.intro}</p>

        <div className="space-y-10">
          {data.sections.map((s) => (
            <div key={s.h}>
              <h2 className="text-xl md:text-2xl font-bold text-white mb-3">{s.h}</h2>
              <p className="text-base font-light text-slate-400 leading-relaxed">{s.p}</p>
            </div>
          ))}
        </div>

        <div className="mt-20 pt-8 border-t border-white/10">
          <p className="font-mono-ui text-xs text-slate-400">© {SITE.year} {SITE.name}. All rights reserved.</p>
        </div>
      </div>
    </main>
  );
};

export default LegalPage;
