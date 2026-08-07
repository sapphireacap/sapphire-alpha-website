import { useEffect, useRef, useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { Menu, X, ChevronDown, Ticket, NotebookText, LineChart, Mail, User } from "lucide-react";
import { useNavigate, useLocation } from "react-router-dom";
import { scrollToId } from "./SmoothScroll";
// Dark mode toggle is hidden for now (2026-08-03) -- ThemeToggle.jsx and
// ThemeContext are untouched, just not imported/rendered here. Re-add the
// import and drop `<ThemeToggle />` back into the actions cluster below
// to bring it back.
// import ThemeToggle from "./ThemeToggle";

const LOGO = "https://customer-assets-agu9un31.emergentagent.net/job_systematic-alpha-1/artifacts/oys5xiox_SAC%20Logo%202.1.png";
const EASE = [0.16, 1, 0.3, 1];

// Kept visible: the core product pages. Tucked into "More": the page's
// own identity anchors (About/Contact) plus IPOs and Journal -- keeps the
// primary bar to four items instead of nine wide.
// "Research" replaced with "P&F Studio" (2026-08-04): /research was already
// just a paused-feature placeholder in the primary bar, while P&F Studio is
// a real paid product (see /pnf-studio, backend's get_current_pnf_subscriber)
// that deserves primary billing, not a tuck-away link.
// "P&F Studio" replaced with a "Charting" parent item (2026-08-06): Renko
// Studio launched as a second charting method (same paid tier, see
// /renko-studio, backend's renko_routes.py) -- both charting products now
// live under one primary-bar dropdown instead of adding a second standalone
// top-level link.
const PRIMARY_LINKS = [
  { label: "Lattice", to: "/lattice" },
  { label: "Alpha Terminal", to: "/alpha-terminal" },
  { label: "The Black Box", to: "/black-box" },
  { label: "Pricing", to: "/pricing" },
];

const CHARTING_LINKS = [
  { label: "P&F Studio", to: "/pnf-studio" },
  { label: "Renko Studio", to: "/renko-studio" },
];

const MORE_LINKS = [
  { label: "IPOs", to: "/ipos", icon: Ticket },
  { label: "Journal", to: "/journal", icon: NotebookText },
  { label: "Research", to: "/research", icon: LineChart },
  { label: "Contact", id: "contact", icon: Mail },
  { label: "About", id: "about", icon: User },
];

const ALL_LINKS = [...PRIMARY_LINKS.slice(0, 1), ...CHARTING_LINKS, ...PRIMARY_LINKS.slice(1), ...MORE_LINKS];

export const Navbar = () => {
  const [scrolled, setScrolled] = useState(false);
  const [open, setOpen] = useState(false);
  const [moreOpen, setMoreOpen] = useState(false);
  const [chartingOpen, setChartingOpen] = useState(false);
  const moreRef = useRef(null);
  const chartingRef = useRef(null);
  const navigate = useNavigate();
  const location = useLocation();

  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 24);
    window.addEventListener("scroll", onScroll);
    return () => window.removeEventListener("scroll", onScroll);
  }, []);

  useEffect(() => {
    if (!moreOpen) return undefined;
    const onClickOutside = (e) => {
      if (moreRef.current && !moreRef.current.contains(e.target)) setMoreOpen(false);
    };
    document.addEventListener("mousedown", onClickOutside);
    return () => document.removeEventListener("mousedown", onClickOutside);
  }, [moreOpen]);

  useEffect(() => {
    if (!chartingOpen) return undefined;
    const onClickOutside = (e) => {
      if (chartingRef.current && !chartingRef.current.contains(e.target)) setChartingOpen(false);
    };
    document.addEventListener("mousedown", onClickOutside);
    return () => document.removeEventListener("mousedown", onClickOutside);
  }, [chartingOpen]);

  const goSection = (id) => {
    setOpen(false);
    if (location.pathname !== "/") {
      navigate("/");
      setTimeout(() => scrollToId(id), 550);
    } else {
      scrollToId(id);
    }
  };

  const handleLink = (l) => {
    setOpen(false);
    setMoreOpen(false);
    setChartingOpen(false);
    if (l.to) navigate(l.to);
    else goSection(l.id);
  };

  const testId = (l) => l.id || l.to.slice(1);

  return (
    <motion.header
      initial={{ y: -80, opacity: 0 }}
      animate={{ y: 0, opacity: 1 }}
      transition={{ duration: 0.9, ease: EASE, delay: 0.2 }}
      className={`fixed top-0 left-0 right-0 z-50 transition-colors duration-500 ${
        scrolled ? "backdrop-blur-xl bg-void/70 border-b border-white/5" : "bg-transparent"
      }`}
      data-testid="site-navbar"
    >
      <nav className="w-full max-w-7xl mx-auto px-6 md:px-10 lg:px-14 flex items-center justify-between gap-4 h-16 md:h-20">
        <button
          onClick={() => goSection("home")}
          className="flex items-center gap-3.5 group min-w-0"
          data-testid="nav-logo"
        >
          <span className="logo-pill p-2 flex items-center justify-center shrink-0 transition-transform duration-300 group-hover:scale-105">
            <img src={LOGO} alt="Sapphire Alpha Capital" className="h-8 w-8 object-contain" />
          </span>
          <span className="flex flex-col leading-none text-left">
            <span className="font-display font-extrabold text-white text-[13px] sm:text-base tracking-normal sm:tracking-tight whitespace-nowrap">
              SAPPHIRE ALPHA
            </span>
            <span className="font-mono-ui text-[9px] tracking-[0.3em] text-sapphire-light uppercase mt-0.5">
              Capital
            </span>
          </span>
        </button>

        <div className="hidden md:flex items-center gap-8 lg:gap-10">
          {PRIMARY_LINKS.slice(0, 1).map((l) => (
            <button
              key={l.id || l.to}
              onClick={() => handleLink(l)}
              className="relative text-sm text-slate-300 hover:text-white transition-colors duration-200 group"
              data-testid={`nav-${testId(l)}-link`}
            >
              {l.label}
              <span className="absolute -bottom-1.5 left-0 h-px w-0 bg-sapphire-light transition-all duration-200 ease-out group-hover:w-full" />
            </button>
          ))}

          <div className="relative" ref={chartingRef}>
            <button
              onClick={() => setChartingOpen((v) => !v)}
              className="relative flex items-center gap-1 text-sm text-slate-300 hover:text-white transition-colors duration-200"
              data-testid="nav-charting-link"
              aria-expanded={chartingOpen}
            >
              Charting
              <ChevronDown size={14} className={`transition-transform duration-200 ${chartingOpen ? "rotate-180" : ""}`} />
            </button>
            <AnimatePresence>
              {chartingOpen && (
                <motion.div
                  initial={{ opacity: 0, y: -6, scale: 0.98 }}
                  animate={{ opacity: 1, y: 0, scale: 1 }}
                  exit={{ opacity: 0, y: -6, scale: 0.98 }}
                  transition={{ duration: 0.2, ease: EASE }}
                  className="absolute top-full left-0 mt-3 w-44 rounded-xl border border-white/10 bg-void/95 backdrop-blur-xl p-2 shadow-2xl shadow-black/50"
                  data-testid="nav-charting-menu"
                >
                  {CHARTING_LINKS.map((l) => (
                    <button
                      key={l.to}
                      onClick={() => handleLink(l)}
                      className="w-full text-left px-3.5 py-2.5 rounded-lg text-sm text-slate-300 hover:text-white hover:bg-white/5 transition-colors duration-200"
                      data-testid={`nav-charting-${testId(l)}-link`}
                    >
                      {l.label}
                    </button>
                  ))}
                </motion.div>
              )}
            </AnimatePresence>
          </div>

          {PRIMARY_LINKS.slice(1).map((l) => (
            <button
              key={l.id || l.to}
              onClick={() => handleLink(l)}
              className="relative text-sm text-slate-300 hover:text-white transition-colors duration-200 group"
              data-testid={`nav-${testId(l)}-link`}
            >
              {l.label}
              <span className="absolute -bottom-1.5 left-0 h-px w-0 bg-sapphire-light transition-all duration-200 ease-out group-hover:w-full" />
            </button>
          ))}

          <div className="relative" ref={moreRef}>
            <button
              onClick={() => setMoreOpen((v) => !v)}
              className="relative flex items-center gap-1 text-sm text-slate-300 hover:text-white transition-colors duration-200"
              data-testid="nav-more-link"
              aria-expanded={moreOpen}
            >
              More
              <ChevronDown size={14} className={`transition-transform duration-200 ${moreOpen ? "rotate-180" : ""}`} />
            </button>
            <AnimatePresence>
              {moreOpen && (
                <motion.div
                  initial={{ opacity: 0, y: -6, scale: 0.98 }}
                  animate={{ opacity: 1, y: 0, scale: 1 }}
                  exit={{ opacity: 0, y: -6, scale: 0.98 }}
                  transition={{ duration: 0.2, ease: EASE }}
                  className="absolute top-full right-0 mt-3 w-52 rounded-xl border border-white/10 bg-void/95 backdrop-blur-xl p-2 shadow-2xl shadow-black/50"
                  data-testid="nav-more-menu"
                >
                  {MORE_LINKS.map((l) => {
                    const Icon = l.icon;
                    return (
                      <button
                        key={l.id || l.to}
                        onClick={() => handleLink(l)}
                        className="w-full flex items-center gap-3 text-left px-3.5 py-2.5 rounded-lg text-sm text-slate-300 hover:text-white hover:bg-white/5 transition-colors duration-200"
                        data-testid={`nav-more-${testId(l)}-link`}
                      >
                        <Icon size={15} className="text-slate-500" />
                        {l.label}
                      </button>
                    );
                  })}
                </motion.div>
              )}
            </AnimatePresence>
          </div>
        </div>

        <div className="flex items-center gap-4 shrink-0">
          {/* <ThemeToggle /> -- hidden for now, see the import comment above */}
          <button
            onClick={() => navigate("/login", { state: { from: location.pathname } })}
            className="hidden lg:inline-flex items-center justify-center rounded-full border border-white/15 px-4 py-2 text-sm font-medium text-slate-200 hover:text-white hover:border-white/30 hover:bg-white/5 transition-colors duration-200"
            data-testid="nav-login-btn"
          >
            Log In
          </button>
          <button
            onClick={() => navigate("/signup", { state: { from: location.pathname } })}
            className="hidden lg:inline-flex items-center justify-center rounded-full bg-sapphire px-4 py-2 text-sm font-semibold text-white hover:bg-sapphire-light transition-colors duration-200"
            data-testid="nav-signup-btn"
          >
            Sign Up
          </button>
          <button
            onClick={() => setOpen((v) => !v)}
            className="md:hidden text-white p-2"
            data-testid="nav-mobile-toggle"
            aria-label="Toggle menu"
          >
            {open ? <X size={22} /> : <Menu size={22} />}
          </button>
        </div>
      </nav>

      <AnimatePresence>
        {open && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.4, ease: EASE }}
            className="md:hidden overflow-hidden border-t border-white/5 bg-void/95 backdrop-blur-xl"
            data-testid="nav-mobile-menu"
          >
            <div className="w-full px-6 py-6 flex flex-col gap-4">
              {ALL_LINKS.map((l) => (
                <button
                  key={l.id || l.to}
                  onClick={() => handleLink(l)}
                  className="text-left text-base py-1 text-slate-200"
                  data-testid={`nav-mobile-${testId(l)}-link`}
                >
                  {l.label}
                </button>
              ))}
              <button
                onClick={() => { setOpen(false); navigate("/login", { state: { from: location.pathname } }); }}
                className="mt-2 w-full inline-flex items-center justify-center rounded-full border border-white/15 py-2.5 text-sm font-medium text-slate-200"
                data-testid="nav-mobile-login-btn"
              >
                Log In
              </button>
              <button
                onClick={() => { setOpen(false); navigate("/signup", { state: { from: location.pathname } }); }}
                className="w-full inline-flex items-center justify-center rounded-full bg-sapphire py-2.5 text-sm font-semibold text-white"
                data-testid="nav-mobile-signup-btn"
              >
                Sign Up
              </button>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </motion.header>
  );
};

export default Navbar;
