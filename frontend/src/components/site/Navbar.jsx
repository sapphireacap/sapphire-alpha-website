import { useCallback, useEffect, useId, useRef, useState } from "react";
import { Link, useLocation } from "react-router-dom";
import { Menu, X, ChevronDown } from "lucide-react";
import { useCurrentUser } from "../../lib/auth";
import AccountMenu from "./AccountMenu";
import SectionLink from "./SectionLink";
import LOGO from "../../assets/sac-logo-mark.svg";

// Every destination here is a real page. Journal is paused (it renders a
// placeholder), so it is not linked; it returns here when the page does.
// Market opens in its own tab: it is a full-screen terminal with no site
// chrome, so there is nothing to navigate "back" to inside that tab.
const PRIMARY = [
  { label: "Lattice", to: "/lattice" },
  { label: "Market", to: "/market", newTab: true },
  { group: "Charting", items: [
    { label: "P&F Studio", to: "/pnf-studio" },
    { label: "Renko Studio", to: "/renko-studio" },
  ] },
  { label: "Alpha Terminal", to: "/alpha-terminal" },
  { label: "The Black Box", to: "/black-box" },
  { label: "Pricing", to: "/pricing" },
  { group: "More", items: [
    { label: "IPOs", to: "/ipos" },
    { label: "Research", to: "/research" },
    { label: "About", id: "about" },
    { label: "Contact", id: "contact" },
  ] },
];

const slug = (l) => (l.label || l.group).toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/(^-|-$)/g, "");

const linkBase =
  "inline-flex min-h-[44px] min-w-[44px] items-center whitespace-nowrap text-sm md:text-base text-bone/85 hover:text-white transition-colors duration-200";

const NavLink = ({ item, className = linkBase, onNavigate, testPrefix = "nav" }) => {
  const common = { className, "data-testid": `${testPrefix}-${slug(item)}-link`, onClick: onNavigate };
  if (item.id) return <SectionLink id={item.id} onNavigate={onNavigate} className={className} data-testid={common["data-testid"]}>{item.label}</SectionLink>;
  if (item.newTab) {
    return (
      <a href={item.to} target="_blank" rel="noopener noreferrer" {...common}>
        {item.label}
        <span className="sr-only"> (opens in a new tab)</span>
      </a>
    );
  }
  return <Link to={item.to} {...common}>{item.label}</Link>;
};

// Disclosure dropdown: a button that toggles a list of links. Closes on
// Escape (returning focus to the button), on an outside click, and when
// keyboard focus leaves it.
const Dropdown = ({ group, items, align = "left" }) => {
  const [open, setOpen] = useState(false);
  const wrap = useRef(null);
  const btn = useRef(null);
  const panelId = useId();

  useEffect(() => {
    if (!open) return undefined;
    const onDown = (e) => { if (wrap.current && !wrap.current.contains(e.target)) setOpen(false); };
    const onKey = (e) => { if (e.key === "Escape") { setOpen(false); btn.current?.focus(); } };
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => { document.removeEventListener("mousedown", onDown); document.removeEventListener("keydown", onKey); };
  }, [open]);

  return (
    <div
      className="relative"
      ref={wrap}
      onBlur={(e) => { if (!wrap.current?.contains(e.relatedTarget)) setOpen(false); }}
    >
      <button
        ref={btn}
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        aria-controls={panelId}
        className={`${linkBase} gap-1`}
        data-testid={`nav-${slug({ group })}-link`}
      >
        {group}
        <ChevronDown size={14} aria-hidden="true" className={`transition-transform duration-200 ${open ? "rotate-180" : ""}`} />
      </button>
      {open && (
        <ul
          id={panelId}
          className={`absolute top-full mt-1 w-52 rounded-xl border border-white/15 bg-void/95 backdrop-blur-xl p-2 shadow-2xl shadow-black/50 ${align === "right" ? "right-0" : "left-0"}`}
          data-testid={`nav-${slug({ group })}-menu`}
        >
          {items.map((l) => (
            <li key={l.id || l.to}>
              <NavLink
                item={l}
                onNavigate={() => setOpen(false)}
                className="flex min-h-[44px] w-full items-center rounded-lg px-3.5 text-sm text-bone/85 hover:bg-white/5 hover:text-white transition-colors duration-200"
                testPrefix={`nav-${slug({ group })}`}
              />
            </li>
          ))}
        </ul>
      )}
    </div>
  );
};

export const Navbar = () => {
  const [scrolled, setScrolled] = useState(false);
  const [open, setOpen] = useState(false);
  const { pathname } = useLocation();
  const [user, refreshUser] = useCurrentUser();
  const menuId = useId();
  const toggle = useRef(null);

  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 8);
    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, []);

  useEffect(() => { setOpen(false); }, [pathname]);

  useEffect(() => {
    if (!open) return undefined;
    const onKey = (e) => { if (e.key === "Escape") { setOpen(false); toggle.current?.focus(); } };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open]);

  const close = useCallback(() => setOpen(false), []);
  const solid = scrolled || open;

  return (
    <header
      className={`fixed top-0 left-0 right-0 z-50 transition-[background-color,border-color,backdrop-filter] duration-300 border-b ${
        solid ? "bg-void/90 backdrop-blur-xl border-white/10" : "bg-gradient-to-b from-void/70 to-transparent border-transparent"
      }`}
      data-testid="site-navbar"
    >
      <div className="w-full max-w-7xl mx-auto px-6 md:px-10 lg:px-14 flex items-center justify-between gap-4 h-16 md:h-24">
        <SectionLink id="home" className="flex items-center gap-3.5 group shrink-0 min-h-[44px]" data-testid="nav-logo">
          <span className="logo-pill p-1 flex items-center justify-center shrink-0 transition-transform duration-300 group-hover:scale-105">
            <img src={LOGO} alt="" width="48" height="48" className="h-10 w-10 md:h-12 md:w-12 object-contain" />
          </span>
          <span className="flex flex-col leading-none text-left">
            <span className="font-display font-extrabold text-white text-[13px] sm:text-lg tracking-normal sm:tracking-tight whitespace-nowrap">SAPPHIRE ALPHA </span>
            <span className="font-mono-ui text-[9px] md:text-[10px] tracking-[0.3em] text-bone/75 uppercase mt-0.5">Capital</span>
          </span>
        </SectionLink>

        <nav aria-label="Primary" className="hidden xl:block">
          <ul className="flex items-center gap-5 lg:gap-8">
            {PRIMARY.map((item, i) => (
              <li key={item.group || item.to}>
                {item.group ? (
                  <Dropdown group={item.group} items={item.items} align={i === PRIMARY.length - 1 ? "right" : "left"} />
                ) : (
                  <NavLink item={item} />
                )}
              </li>
            ))}
          </ul>
        </nav>

        <div className="flex items-center gap-3 shrink-0">
          {user ? (
            <div className="hidden xl:block"><AccountMenu user={user} onUserChange={refreshUser} /></div>
          ) : (
            <>
              <Link
                to="/login" state={{ from: pathname }}
                className="hidden xl:inline-flex min-h-[44px] items-center justify-center rounded-full border border-white/20 px-5 text-sm md:text-base font-medium text-bone hover:text-white hover:border-white/40 hover:bg-white/5 transition-colors duration-200"
                data-testid="nav-login-btn"
              >
                Log In
              </Link>
              <Link
                to="/signup" state={{ from: pathname }}
                className="hidden xl:inline-flex min-h-[44px] items-center justify-center border border-bone bg-bone px-5 text-sm md:text-base font-semibold text-plate hover:bg-transparent hover:text-bone transition-colors duration-200"
                data-testid="nav-signup-btn"
              >
                Sign Up
              </Link>
            </>
          )}
          <button
            ref={toggle}
            type="button"
            onClick={() => setOpen((v) => !v)}
            aria-expanded={open}
            aria-controls={menuId}
            aria-label={open ? "Close menu" : "Open menu"}
            className="xl:hidden inline-flex h-11 w-11 items-center justify-center text-white"
            data-testid="nav-mobile-toggle"
          >
            {open ? <X size={22} aria-hidden="true" /> : <Menu size={22} aria-hidden="true" />}
          </button>
        </div>
      </div>

      {open && (
        <nav
          id={menuId}
          aria-label="Mobile"
          className="xl:hidden max-h-[calc(100svh-4rem)] overflow-y-auto border-t border-white/10 bg-void/95 backdrop-blur-xl"
          data-testid="nav-mobile-menu"
        >
          <ul className="w-full px-6 py-4">
            {PRIMARY.map((item) =>
              item.group ? (
                <li key={item.group} className="pt-3">
                  <p className="label-mono pb-1 pt-2">{item.group}</p>
                  <ul>
                    {item.items.map((l) => (
                      <li key={l.id || l.to}>
                        <NavLink
                          item={l} onNavigate={close}
                          className="flex min-h-[48px] w-full items-center pl-3 text-[15px] text-bone/85"
                          testPrefix={`nav-mobile-${slug({ group: item.group })}`}
                        />
                      </li>
                    ))}
                  </ul>
                </li>
              ) : (
                <li key={item.to}>
                  <NavLink item={item} onNavigate={close} className="flex min-h-[48px] w-full items-center text-base text-bone" testPrefix="nav-mobile" />
                </li>
              )
            )}
          </ul>
          <div className="px-6 pb-6 pt-2 flex flex-col gap-3">
            {user ? (
              <AccountMenu user={user} onUserChange={refreshUser} />
            ) : (
              <>
                <Link to="/login" state={{ from: pathname }} className="inline-flex min-h-[48px] items-center justify-center rounded-full border border-white/20 text-sm font-medium text-bone" data-testid="nav-mobile-login-btn">Log In</Link>
                <Link to="/signup" state={{ from: pathname }} className="inline-flex min-h-[48px] items-center justify-center border border-bone bg-bone text-sm font-semibold text-plate" data-testid="nav-mobile-signup-btn">Sign Up</Link>
              </>
            )}
          </div>
        </nav>
      )}
    </header>
  );
};

export default Navbar;
