import { useEffect, useRef, useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { Menu, X, ChevronDown, Ticket, NotebookText, LineChart, Mail, User } from "lucide-react";
import { useNavigate, useLocation } from "react-router-dom";
import { scrollToId } from "./SmoothScroll";
import { useCurrentUser } from "../../lib/auth";
import AccountMenu from "./AccountMenu";
import LOGO from "../../assets/sac-logo-mark.svg";
// Dark mode toggle is hidden for now (2026-08-03) -- ThemeToggle.jsx and
// ThemeContext are untouched, just not imported/rendered here. Re-add the
// import and drop `<ThemeToggle />` back into the actions cluster below
// to bring it back.
// import ThemeToggle from "./ThemeToggle";

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
  { label: "Market", to: "/market" },
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

export const Navbar = () => {
  const [scrolled, setScrolled] = useState(false);
  const [open, setOpen] = useState(false);
  const [moreOpen, setMoreOpen] = useState(false);
  const [chartingOpen, setChartingOpen] = useState(false);
  // Separate from the desktop dropdowns' chartingOpen/moreOpen above --
  // sharing that state would let a Charting/More group left open on
  // mobile stay open if the viewport is then resized to desktop (and
  // vice versa), popping open a dropdown nobody clicked.
  const [mobileChartingOpen, setMobileChartingOpen] = useState(false);
  const [mobileMoreOpen, setMobileMoreOpen] = useState(false);
  const moreRef = useRef(null);
  const chartingRef = useRef(null);
  const navigate = useNavigate();
  const location = useLocation();
  const [user, refreshUser] = useCurrentUser();

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
    if (l.comingSoon) return;
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
      <nav className="w-full max-w-7xl mx-auto px-6 md:px-10 lg:px-14 flex items-center justify-between gap-4 h-16 md:h-24">
        <button
          onClick={() => goSection("home")}
          className="flex items-center gap-3.5 group min-w-0"
          data-testid="nav-logo"
        >
          <span className="logo-pill p-1 flex items-center justify-center shrink-0 transition-transform duration-300 group-hover:scale-105">
            <img src={LOGO} alt="Sapphire Alpha Capital" className="h-10 w-10 md:h-12 md:w-12 object-contain" />
          </span>
          <span className="flex flex-col leading-none text-left">
            <span className="font-display font-extrabold text-white text-[13px] sm:text-lg tracking-normal sm:tracking-tight whitespace-nowrap">
              SAPPHIRE ALPHA
            </span>
            <span className="font-mono-ui text-[9px] md:text-[10px] tracking-[0.3em] text-bone/60 uppercase mt-0.5">
              Capital
            </span>
          </span>
        </button>

        {/* Every nav item stays on ONE line -- multi-word labels ("Alpha
            Terminal", "The Black Box") were wrapping to two lines and
            breaking the bar's alignment. whitespace-nowrap on each item
            plus a slightly tighter gap keeps the row single-line without
            shrinking the type. */}
        <div className="hidden md:flex items-center gap-6 lg:gap-8 md:text-base">
          {PRIMARY_LINKS.slice(0, 2).map((l) => (
            <button
              key={l.id || l.to}
              onClick={() => handleLink(l)}
              className="relative whitespace-nowrap text-sm md:text-base text-slate-300 hover:text-white transition-colors duration-200 group"
              data-testid={`nav-${testId(l)}-link`}
            >
              {l.label}
              <span className="absolute -bottom-1.5 left-0 h-px w-0 bg-sapphire-light transition-all duration-200 ease-out group-hover:w-full" />
            </button>
          ))}

          <div className="relative" ref={chartingRef}>
            <button
              onClick={() => setChartingOpen((v) => !v)}
              className="relative flex items-center gap-1 whitespace-nowrap text-sm md:text-base text-slate-300 hover:text-white transition-colors duration-200"
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

          {PRIMARY_LINKS.slice(2).map((l) =>
            l.comingSoon ? (
              <span
                key={l.id || l.to}
                className="group relative whitespace-nowrap text-sm md:text-base text-slate-500 cursor-not-allowed select-none"
                data-testid={`nav-${testId(l)}-link`}
              >
                {l.label}
                <span className="pointer-events-none absolute left-1/2 top-full mt-2 -translate-x-1/2 whitespace-nowrap rounded-full border border-white/10 bg-void px-2.5 py-1 text-[10px] uppercase tracking-wider text-slate-400 opacity-0 transition-opacity duration-150 group-hover:opacity-100">
                  Coming Soon
                </span>
              </span>
            ) : (
              <button
                key={l.id || l.to}
                onClick={() => handleLink(l)}
                className="relative whitespace-nowrap text-sm md:text-base text-slate-300 hover:text-white transition-colors duration-200 group"
                data-testid={`nav-${testId(l)}-link`}
              >
                {l.label}
                <span className="absolute -bottom-1.5 left-0 h-px w-0 bg-sapphire-light transition-all duration-200 ease-out group-hover:w-full" />
              </button>
            )
          )}

          <div className="relative" ref={moreRef}>
            <button
              onClick={() => setMoreOpen((v) => !v)}
              className="relative flex items-center gap-1 whitespace-nowrap text-sm md:text-base text-slate-300 hover:text-white transition-colors duration-200"
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
          {user ? (
            <div className="hidden lg:block">
              <AccountMenu user={user} onUserChange={refreshUser} />
            </div>
          ) : (
            <>
              <button
                onClick={() => navigate("/login", { state: { from: location.pathname } })}
                className="hidden lg:inline-flex items-center justify-center rounded-full border border-white/15 px-4 py-2 text-sm md:text-base font-medium text-slate-200 hover:text-white hover:border-white/30 hover:bg-white/5 transition-colors duration-200"
                data-testid="nav-login-btn"
              >
                Log In
              </button>
              <button
                onClick={() => navigate("/signup", { state: { from: location.pathname } })}
                className="hidden lg:inline-flex items-center justify-center border border-bone/70 bg-bone px-4 py-2 text-sm md:text-base font-medium text-plate hover:bg-transparent hover:text-bone transition-colors duration-200"
                data-testid="nav-signup-btn"
              >
                Sign Up
              </button>
            </>
          )}
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
              {PRIMARY_LINKS.slice(0, 2).map((l) => (
                <button
                  key={l.id || l.to}
                  onClick={() => handleLink(l)}
                  className="text-left text-base py-1 text-slate-200"
                  data-testid={`nav-mobile-${testId(l)}-link`}
                >
                  {l.label}
                </button>
              ))}

              <div>
                <button
                  type="button"
                  onClick={() => setMobileChartingOpen((v) => !v)}
                  className="w-full flex items-center justify-between text-left text-base py-1 text-slate-200"
                  aria-expanded={mobileChartingOpen}
                  data-testid="nav-mobile-charting-link"
                >
                  Charting
                  <ChevronDown size={16} className={`text-slate-500 transition-transform duration-200 ${mobileChartingOpen ? "rotate-180" : ""}`} />
                </button>
                <AnimatePresence initial={false}>
                  {mobileChartingOpen && (
                    <motion.div
                      initial={{ height: 0, opacity: 0 }}
                      animate={{ height: "auto", opacity: 1 }}
                      exit={{ height: 0, opacity: 0 }}
                      transition={{ duration: 0.25, ease: EASE }}
                      className="overflow-hidden"
                    >
                      <div className="flex flex-col gap-3 pl-4 pt-3">
                        {CHARTING_LINKS.map((l) => (
                          <button
                            key={l.to}
                            onClick={() => handleLink(l)}
                            className="text-left text-sm text-slate-400"
                            data-testid={`nav-mobile-charting-${testId(l)}-link`}
                          >
                            {l.label}
                          </button>
                        ))}
                      </div>
                    </motion.div>
                  )}
                </AnimatePresence>
              </div>

              {PRIMARY_LINKS.slice(2).map((l) => (
                <button
                  key={l.id || l.to}
                  onClick={() => handleLink(l)}
                  disabled={l.comingSoon}
                  className={`flex items-center gap-2 text-left text-base py-1 ${l.comingSoon ? "text-slate-500 cursor-not-allowed" : "text-slate-200"}`}
                  data-testid={`nav-mobile-${testId(l)}-link`}
                >
                  {l.label}
                  {/* No hover on touch devices -- unlike the desktop tooltip, mobile needs the "Coming Soon" text always visible */}
                  {l.comingSoon && (
                    <span className="text-[10px] uppercase tracking-wider text-slate-500 border border-white/10 rounded-full px-2 py-0.5">
                      Coming Soon
                    </span>
                  )}
                </button>
              ))}

              <div>
                <button
                  type="button"
                  onClick={() => setMobileMoreOpen((v) => !v)}
                  className="w-full flex items-center justify-between text-left text-base py-1 text-slate-200"
                  aria-expanded={mobileMoreOpen}
                  data-testid="nav-mobile-more-link"
                >
                  More
                  <ChevronDown size={16} className={`text-slate-500 transition-transform duration-200 ${mobileMoreOpen ? "rotate-180" : ""}`} />
                </button>
                <AnimatePresence initial={false}>
                  {mobileMoreOpen && (
                    <motion.div
                      initial={{ height: 0, opacity: 0 }}
                      animate={{ height: "auto", opacity: 1 }}
                      exit={{ height: 0, opacity: 0 }}
                      transition={{ duration: 0.25, ease: EASE }}
                      className="overflow-hidden"
                    >
                      <div className="flex flex-col gap-3 pl-4 pt-3">
                        {MORE_LINKS.map((l) => (
                          <button
                            key={l.id || l.to}
                            onClick={() => handleLink(l)}
                            className="text-left text-sm text-slate-400"
                            data-testid={`nav-mobile-more-${testId(l)}-link`}
                          >
                            {l.label}
                          </button>
                        ))}
                      </div>
                    </motion.div>
                  )}
                </AnimatePresence>
              </div>

              {user ? (
                <div className="mt-2">
                  <AccountMenu user={user} onUserChange={refreshUser} />
                </div>
              ) : (
                <>
                  <button
                    onClick={() => { setOpen(false); navigate("/login", { state: { from: location.pathname } }); }}
                    className="mt-2 w-full inline-flex items-center justify-center rounded-full border border-white/15 py-2.5 text-sm font-medium text-slate-200"
                    data-testid="nav-mobile-login-btn"
                  >
                    Log In
                  </button>
                  <button
                    onClick={() => { setOpen(false); navigate("/signup", { state: { from: location.pathname } }); }}
                    className="w-full inline-flex items-center justify-center border border-bone/70 bg-bone py-2.5 text-sm font-medium text-plate"
                    data-testid="nav-mobile-signup-btn"
                  >
                    Sign Up
                  </button>
                </>
              )}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </motion.header>
  );
};

export default Navbar;
