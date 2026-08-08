import { Link } from "react-router-dom";
import Marquee from "react-fast-marquee";
import { Linkedin, Twitter, Instagram, Send } from "lucide-react";
import { scrollToId } from "./SmoothScroll";
import LOGO from "../../assets/sac-logo-mark.svg";

const NAV = [
  { label: "About", id: "about" },
  { label: "Research", id: "research" },
  { label: "The Black Box", to: "/black-box" },
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
    <footer className="relative pt-28 md:pt-36 border-t border-white/10 overflow-hidden" data-testid="site-footer">
      <div className="container-x">
        <div className="flex flex-col md:grid md:grid-cols-12 gap-x-8 gap-y-12 pb-24">
          <div className="md:col-span-4">
            <div className="flex items-center gap-3.5 mb-6">
              <span className="logo-pill p-1 flex items-center justify-center">
                <img src={LOGO} alt="Sapphire Alpha Capital" className="h-10 w-10 object-contain" />
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
                    className="h-11 w-11 rounded-full border border-white/10 flex items-center justify-center text-slate-400 hover:text-white hover:border-sapphire-light hover:bg-sapphire/10 hover:scale-105 transition-all duration-300"
                    data-testid={`social-${s.label.split(" ")[0].toLowerCase()}`}
                  >
                    <Icon size={16} />
                  </a>
                );
              })}
            </div>
          </div>

          <div className="flex gap-8 md:contents">
            <div className="flex-1 md:flex-none md:col-span-3 md:col-start-7">
              <p className="overline !text-slate-500 mb-7">Navigation</p>
              <ul className="space-y-4">
                {NAV.map((n) => (
                  <li key={n.id || n.to}>
                    {n.to ? (
                      <Link
                        to={n.to}
                        className="inline-block text-sm text-slate-400 hover:text-white hover:translate-x-0.5 transition-all duration-200"
                        data-testid={`footer-nav-${n.to.slice(1)}`}
                      >
                        {n.label}
                      </Link>
                    ) : (
                      <button
                        onClick={() => scrollToId(n.id)}
                        className="inline-block text-sm text-slate-400 hover:text-white hover:translate-x-0.5 transition-all duration-200"
                        data-testid={`footer-nav-${n.id}`}
                      >
                        {n.label}
                      </button>
                    )}
                  </li>
                ))}
              </ul>
            </div>

            <div className="flex-1 md:flex-none md:col-span-2 md:col-start-10">
              <p className="overline !text-slate-500 mb-7">Legal</p>
              <ul className="space-y-4">
                {LEGAL.map((l) => (
                  <li key={l.to}>
                    <Link
                      to={l.to}
                      className="inline-block text-sm text-slate-400 hover:text-white hover:translate-x-0.5 transition-all duration-200"
                      data-testid={`footer-legal-${l.to.slice(1)}`}
                    >
                      {l.label}
                    </Link>
                  </li>
                ))}
              </ul>
            </div>
          </div>
        </div>

        <div className="flex flex-col md:flex-row md:items-center md:justify-between gap-4 py-8 border-t border-white/10">
          <p className="font-mono-ui text-xs text-slate-500">© 2026 Sapphire Alpha Capital. All rights reserved.</p>
        </div>
      </div>

      <div className="relative select-none pointer-events-none py-4 md:py-6 border-t border-white/5">
        <Marquee speed={32} gradient={false} autoFill>
          <span className="marquee-text text-[16vw] md:text-[13vw] leading-none whitespace-nowrap">
            SAPPHIRE ALPHA CAPITAL
          </span>
          <span className="text-sapphire text-[10vw] md:text-[8vw] px-6 md:px-10">✦</span>
        </Marquee>
      </div>
    </footer>
  );
};

export default Footer;
