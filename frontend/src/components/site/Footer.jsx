import { Link } from "react-router-dom";
import { Linkedin, Twitter, Instagram, Send } from "lucide-react";
import { scrollToId } from "./SmoothScroll";

const LOGO = "https://customer-assets-agu9un31.emergentagent.net/job_systematic-alpha-1/artifacts/oys5xiox_SAC%20Logo%202.1.png";

const NAV = [
  { label: "About", id: "about" },
  { label: "Research", id: "research" },
  { label: "Insights", id: "insights" },
  { label: "Investing", id: "investing" },
  { label: "Contact", id: "contact" },
];

const LEGAL = [
  { label: "Privacy Policy", to: "/privacy" },
  { label: "Terms of Use", to: "/terms" },
  { label: "Disclaimer", to: "/disclaimer" },
];

const SOCIAL = [
  { icon: Linkedin, label: "LinkedIn", href: "https://www.linkedin.com/company/sapphirealphacapital" },
  { icon: Twitter, label: "X / Twitter", href: "https://x.com/sapphireacap" },
  { icon: Instagram, label: "Instagram", href: "https://www.instagram.com/sapphireacap/" },
  { icon: Send, label: "Telegram", href: "https://t.me/sapphireacap" },
];

export const Footer = () => {
  return (
    <footer className="relative pt-24 md:pt-32 border-t border-white/10 overflow-hidden" data-testid="site-footer">
      <div className="container-x">
        <div className="grid grid-cols-12 gap-10 md:gap-8 pb-20">
          <div className="col-span-12 md:col-span-5">
            <div className="flex items-center gap-3 mb-6">
              <span className="logo-pill p-1.5 flex items-center justify-center">
                <img src={LOGO} alt="Sapphire Alpha Capital" className="h-7 w-7 object-contain" />
              </span>
              <span className="font-display font-extrabold text-white text-lg tracking-tight">SAPPHIRE ALPHA CAPITAL</span>
            </div>
            <p className="text-sm font-light text-slate-400 leading-relaxed max-w-sm">
              Building a research-first platform focused on systematic investing,
              financial markets, and quantitative analysis.
            </p>
            <div className="flex items-center gap-3 mt-8">
              {SOCIAL.map((s) => {
                const Icon = s.icon;
                return (
                  <a
                    key={s.label}
                    href={s.href || "#"}
                    target={s.href ? "_blank" : undefined}
                    rel={s.href ? "noopener noreferrer" : undefined}
                    aria-label={s.label}
                    className="h-10 w-10 rounded-full border border-white/10 flex items-center justify-center text-slate-400 hover:text-white hover:border-sapphire-light hover:bg-sapphire/10 transition-colors duration-300"
                    data-testid={`social-${s.label.split(" ")[0].toLowerCase()}`}
                  >
                    <Icon size={16} />
                  </a>
                );
              })}
            </div>
          </div>

          <div className="col-span-6 md:col-span-3 md:col-start-8">
            <p className="overline !text-slate-500 mb-6">Navigation</p>
            <ul className="space-y-3">
              {NAV.map((n) => (
                <li key={n.id}>
                  <button
                    onClick={() => scrollToId(n.id)}
                    className="text-sm text-slate-400 hover:text-white transition-colors"
                    data-testid={`footer-nav-${n.id}`}
                  >
                    {n.label}
                  </button>
                </li>
              ))}
            </ul>
          </div>

          <div className="col-span-6 md:col-span-2">
            <p className="overline !text-slate-500 mb-6">Legal</p>
            <ul className="space-y-3">
              {LEGAL.map((l) => (
                <li key={l.to}>
                  <Link
                    to={l.to}
                    className="text-sm text-slate-400 hover:text-white transition-colors"
                    data-testid={`footer-legal-${l.to.slice(1)}`}
                  >
                    {l.label}
                  </Link>
                </li>
              ))}
            </ul>
          </div>
        </div>

        <div className="flex flex-col md:flex-row md:items-center md:justify-between gap-4 py-8 border-t border-white/10">
          <p className="font-mono-ui text-xs text-slate-500">© 2026 Sapphire Alpha Capital. All rights reserved.</p>
        </div>
      </div>

      <div className="relative select-none pointer-events-none -mb-[2vw]">
        <p className="marquee-text text-center text-[15vw] leading-none whitespace-nowrap">SAPPHIRE ALPHA</p>
      </div>
    </footer>
  );
};

export default Footer;
