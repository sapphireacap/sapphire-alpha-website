import { Link } from "react-router-dom";
import { Linkedin, Twitter, Instagram, Send } from "lucide-react";
import { SITE, FOOTER } from "@/content/homepage";
import SectionLink from "./SectionLink";
import LOGO from "../../assets/sac-logo-mark.svg";

const NAV = [
  { label: "About", id: "about" },
  { label: "Alpha Terminal", to: "/alpha-terminal" },
  { label: "The Black Box", to: "/black-box" },
  { label: "Pricing", to: "/pricing" },
  { label: "Contact", id: "contact" },
];

const LEGAL = [
  { label: "Privacy Policy", to: "/privacy" },
  { label: "Terms of Use", to: "/terms" },
  { label: "Disclaimer", to: "/disclaimer" },
];

const ICONS = { LinkedIn: Linkedin, "X / Twitter": Twitter, Instagram, Telegram: Send };

const linkClass =
  "inline-flex min-h-[44px] min-w-[44px] items-center text-sm text-bone/75 hover:text-white transition-colors duration-200";

export const Footer = () => (
  <footer className="relative pt-24 md:pt-32 overflow-hidden" data-testid="site-footer">
    <div className="container-x">
      <div className="flex flex-col md:grid md:grid-cols-12 gap-x-8 gap-y-12 pb-16">
        <div className="md:col-span-5">
          <div className="flex items-center gap-3.5 mb-6">
            <span className="logo-pill p-1 flex items-center justify-center">
              <img src={LOGO} alt="" width="40" height="40" className="h-10 w-10 object-contain" />
            </span>
            <span className="font-display font-extrabold text-white text-lg tracking-tight">SAPPHIRE ALPHA CAPITAL</span>
          </div>
          <p className="text-sm font-light text-bone/75 leading-relaxed max-w-sm">{FOOTER.blurb}</p>
          <a
            href={`mailto:${SITE.email}`}
            className="mt-5 inline-flex min-h-[44px] items-center font-mono-ui text-sm text-sapphire-light hover:text-white transition-colors duration-200"
            data-testid="footer-email"
          >
            {SITE.email}
          </a>
          <ul className="flex items-center gap-3 mt-4">
            {SITE.social.map((s) => {
              const Icon = ICONS[s.label];
              return (
                <li key={s.label}>
                  <a
                    href={s.href}
                    target="_blank"
                    rel="noopener noreferrer"
                    aria-label={s.label}
                    className="h-11 w-11 rounded-full border border-white/15 flex items-center justify-center text-bone/75 hover:text-white hover:border-sapphire-light hover:bg-sapphire/10 transition-colors duration-200"
                    data-testid={`social-${s.label.split(" ")[0].toLowerCase()}`}
                  >
                    <Icon size={16} aria-hidden="true" />
                  </a>
                </li>
              );
            })}
          </ul>
        </div>

        <nav aria-label="Footer" className="flex gap-8 md:contents">
          <div className="flex-1 md:flex-none md:col-span-3 md:col-start-7">
            <p className="label-mono mb-4">Navigation</p>
            <ul>
              {NAV.map((n) => (
                <li key={n.id || n.to}>
                  {n.to ? (
                    <Link to={n.to} className={linkClass} data-testid={`footer-nav-${n.to.slice(1)}`}>{n.label}</Link>
                  ) : (
                    <SectionLink id={n.id} className={linkClass} data-testid={`footer-nav-${n.id}`}>{n.label}</SectionLink>
                  )}
                </li>
              ))}
            </ul>
          </div>

          <div className="flex-1 md:flex-none md:col-span-3 md:col-start-10">
            <p className="label-mono mb-4">Legal</p>
            <ul>
              {LEGAL.map((l) => (
                <li key={l.to}>
                  <Link to={l.to} className={linkClass} data-testid={`footer-legal-${l.to.slice(1)}`}>{l.label}</Link>
                </li>
              ))}
            </ul>
          </div>
        </nav>
      </div>

      <div className="border-t border-white/10 py-8 space-y-4">
        <p className="max-w-3xl text-xs leading-relaxed text-bone/70" data-testid="footer-disclaimer">{FOOTER.disclaimer}</p>
        <p className="font-mono-ui text-xs text-bone/70">
          © {SITE.year} {SITE.name}. {FOOTER.rights}
        </p>
      </div>
    </div>
  </footer>
);

export default Footer;
