import { Link } from "react-router-dom";
import { ArrowLeft } from "lucide-react";

const LOGO = "https://customer-assets-agu9un31.emergentagent.net/job_systematic-alpha-1/artifacts/oys5xiox_SAC%20Logo%202.1.png";

const NotFound = () => (
  <div className="min-h-screen bg-void grid-bg flex items-center" data-testid="not-found-page">
    <div className="container-x py-16 md:py-24 max-w-3xl">
      <div className="flex items-center justify-between mb-16">
        <Link to="/" className="inline-flex items-center gap-2 text-slate-400 hover:text-white transition-colors text-sm" data-testid="not-found-home-link">
          <ArrowLeft size={16} /> Back to home
        </Link>
        <span className="logo-pill p-1.5 flex items-center justify-center">
          <img src={LOGO} alt="Sapphire Alpha Capital" className="h-6 w-6 object-contain" />
        </span>
      </div>

      <p className="overline mb-4">404</p>
      <h1 className="font-display font-black tracking-tighter text-white text-5xl md:text-7xl mb-5">Page Not Found</h1>
      <p className="text-base md:text-lg font-light text-slate-400 leading-relaxed">
        The page you're looking for doesn't exist or has moved.
      </p>
    </div>
  </div>
);

export default NotFound;
