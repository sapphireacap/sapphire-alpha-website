import { useEffect, useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { Menu, X } from "lucide-react";
import { useNavigate, useLocation } from "react-router-dom";
import { scrollToId } from "./SmoothScroll";

const LOGO = "https://customer-assets-agu9un31.emergentagent.net/job_systematic-alpha-1/artifacts/oys5xiox_SAC%20Logo%202.1.png";

const links = [
  { label: "About", id: "about" },
  { label: "Research", id: "research" },
  { label: "Alpha Terminal", to: "/alpha-terminal" },
  { label: "Insights", id: "insights" },
  { label: "Investing", id: "investing" },
  { label: "Contact", id: "contact" },
];

export const Navbar = () => {
  const [scrolled, setScrolled] = useState(false);
  const [open, setOpen] = useState(false);
  const navigate = useNavigate();
  const location = useLocation();

  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 24);
    window.addEventListener("scroll", onScroll);
    return () => window.removeEventListener("scroll", onScroll);
  }, []);

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
    if (l.to) navigate(l.to);
    else goSection(l.id);
  };

  return (
    <motion.header
      initial={{ y: -80, opacity: 0 }}
      animate={{ y: 0, opacity: 1 }}
      transition={{ duration: 0.9, ease: [0.16, 1, 0.3, 1], delay: 0.2 }}
      className={`fixed top-0 left-0 right-0 z-50 transition-colors duration-500 ${
        scrolled ? "backdrop-blur-xl bg-void/70 border-b border-white/5" : "bg-transparent"
      }`}
      data-testid="site-navbar"
    >
      <nav className="container-x flex items-center justify-between gap-3 h-20">
        <button
          onClick={() => goSection("home")}
          className="flex items-center gap-3 group min-w-0"
          data-testid="nav-logo"
        >
          <span className="logo-pill p-1.5 flex items-center justify-center shrink-0">
            <img src={LOGO} alt="Sapphire Alpha Capital" className="h-7 w-7 object-contain" />
          </span>
          <span className="flex flex-col leading-none text-left">
            <span className="font-display font-extrabold text-white text-[13px] sm:text-[15px] tracking-normal sm:tracking-tight whitespace-nowrap">
              SAPPHIRE ALPHA
            </span>
            <span className="font-mono-ui text-[9px] tracking-[0.3em] text-sapphire-light uppercase mt-0.5">
              Capital
            </span>
          </span>
        </button>

        <div className="hidden md:flex items-center gap-9">
          {links.map((l) => {
            const isAlpha = l.to === "/alpha-terminal";
            return (
              <button
                key={l.id || l.to}
                onClick={() => handleLink(l)}
                className={`relative text-sm transition-colors duration-300 group ${
                  isAlpha ? "text-sapphire-light font-semibold alpha-glow" : "text-slate-300 hover:text-white"
                }`}
                data-testid={`nav-${l.id || l.to.slice(1)}-link`}
              >
                {isAlpha && (
                  <span className="absolute -right-2.5 -top-1 flex h-1.5 w-1.5">
                    <span className="absolute inline-flex h-full w-full rounded-full bg-sapphire-light opacity-75 animate-ping" />
                    <span className="relative inline-flex h-1.5 w-1.5 rounded-full bg-sapphire-light" />
                  </span>
                )}
                {l.label}
                <span
                  className={`absolute -bottom-1.5 left-0 h-px bg-sapphire-light transition-all duration-300 ${
                    isAlpha ? "w-full opacity-60" : "w-0 group-hover:w-full"
                  }`}
                />
              </button>
            );
          })}
        </div>

        <div className="flex items-center gap-3 shrink-0">
          <button
            onClick={() => goSection("waitlist")}
            className="btn-sapphire hidden sm:inline-flex !px-5 !py-2.5"
            data-testid="nav-get-notified-btn"
          >
            Get Notified
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
            transition={{ duration: 0.4, ease: [0.16, 1, 0.3, 1] }}
            className="md:hidden overflow-hidden border-t border-white/5 bg-void/95 backdrop-blur-xl"
            data-testid="nav-mobile-menu"
          >
            <div className="container-x py-6 flex flex-col gap-4">
              {links.map((l) => {
                const isAlpha = l.to === "/alpha-terminal";
                return (
                  <button
                    key={l.id || l.to}
                    onClick={() => handleLink(l)}
                    className={`text-left text-base py-1 flex items-center gap-2 ${
                      isAlpha ? "text-sapphire-light font-semibold alpha-glow" : "text-slate-200"
                    }`}
                    data-testid={`nav-mobile-${l.id || l.to.slice(1)}-link`}
                  >
                    <span className="relative flex h-1.5 w-1.5 shrink-0">
                      {isAlpha && (
                        <>
                          <span className="absolute inline-flex h-full w-full rounded-full bg-sapphire-light opacity-75 animate-ping" />
                          <span className="relative inline-flex h-1.5 w-1.5 rounded-full bg-sapphire-light" />
                        </>
                      )}
                    </span>
                    {l.label}
                  </button>
                );
              })}
              <button onClick={() => goSection("waitlist")} className="btn-sapphire mt-2 w-full">
                Get Notified
              </button>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </motion.header>
  );
};

export default Navbar;
