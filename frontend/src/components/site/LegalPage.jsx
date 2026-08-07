import { useEffect } from "react";
import { Link } from "react-router-dom";
import { ArrowLeft } from "lucide-react";

const LOGO = "https://customer-assets-agu9un31.emergentagent.net/job_systematic-alpha-1/artifacts/oys5xiox_SAC%20Logo%202.1.png";

const CONTENT = {
  privacy: {
    title: "Privacy Policy",
    updated: "Last updated: January 2026",
    intro:
      "Sapphire Alpha Capital (\"we\", \"us\") is committed to protecting the privacy of visitors to our website. This policy explains what information we collect and how we use it while our platform is under development.",
    sections: [
      { h: "Information We Collect", p: "We collect the email address you provide when joining our waitlist, and the name, email, company, and message you submit through our contact form. We do not collect payment or sensitive financial information at this time." },
      { h: "How We Use Information", p: "We use the information solely to notify you about platform availability, respond to your enquiries, and share relevant research updates. We do not sell or rent your personal data to third parties." },
      { h: "Data Storage & Security", p: "Submitted information is stored securely and access is limited to authorised personnel. We apply reasonable technical and organisational measures to protect it." },
      { h: "Your Rights", p: "You may request access to, correction of, or deletion of your personal data at any time by emailing contact@sapphirealphacapital.com." },
      { h: "Cookies", p: "Our site uses only essential cookies required for basic functionality. We do not use advertising or third-party tracking cookies." },
    ],
  },
  terms: {
    title: "Terms of Use",
    updated: "Last updated: January 2026",
    intro:
      "By accessing this website you agree to these Terms of Use. The site is a preview of a platform currently under development and is provided on an \"as is\" basis.",
    sections: [
      { h: "Use of the Site", p: "You may browse the site and submit your details via the waitlist or contact form. You agree not to misuse the site, attempt unauthorised access, or interfere with its operation." },
      { h: "Intellectual Property", p: "All content, branding, and design on this site are the property of Sapphire Alpha Capital and may not be reproduced without permission." },
      { h: "No Warranty", p: "The site and any information on it are provided without warranties of any kind. Features described are in development and subject to change." },
      { h: "Limitation of Liability", p: "To the fullest extent permitted by law, Sapphire Alpha Capital shall not be liable for any damages arising from the use of, or inability to use, this website." },
      { h: "Changes", p: "We may update these terms from time to time. Continued use of the site constitutes acceptance of the revised terms." },
    ],
  },
  disclaimer: {
    title: "Disclaimer",
    updated: "Last updated: January 2026",
    intro:
      "The information on this website is provided for general informational and educational purposes only.",
    sections: [
      { h: "Not Investment Advice", p: "Nothing on this site constitutes investment, financial, legal, or tax advice, or a recommendation to buy or sell any security or financial instrument." },
      { h: "No Offer or Solicitation", p: "This site does not constitute an offer or solicitation to invest in any fund, product, or strategy. Sapphire Alpha Capital is not currently offering any investment product." },
      { h: "Forward-Looking Statements", p: "Descriptions of methodology, signals, and frameworks are illustrative and representative of our research approach — not indicative of live or future performance." },
      { h: "Risk", p: "Investing in financial markets involves risk, including the possible loss of principal. Past performance is not indicative of future results." },
    ],
  },
};

export const LegalPage = ({ page }) => {
  const data = CONTENT[page];
  useEffect(() => {
    window.scrollTo(0, 0);
  }, [page]);

  if (!data) return null;

  return (
    <div className="min-h-screen bg-void grid-bg" data-testid={`legal-${page}`}>
      <div className="container-x py-16 md:py-24 max-w-3xl">
        <div className="flex items-center justify-between mb-16">
          <Link to="/" className="inline-flex items-center gap-2 text-slate-400 hover:text-white transition-colors text-sm" data-testid="legal-back-link">
            <ArrowLeft size={16} /> Back to home
          </Link>
          <span className="logo-pill p-1.5 flex items-center justify-center">
            <img src={LOGO} alt="Sapphire Alpha Capital" className="h-6 w-6 object-contain" />
          </span>
        </div>

        <p className="overline mb-4">Legal</p>
        <h1 className="font-display font-black tracking-tighter text-white text-4xl md:text-6xl mb-3">{data.title}</h1>
        <p className="font-mono-ui text-xs text-slate-500 mb-12">{data.updated}</p>
        <p className="text-base md:text-lg font-light text-slate-300 leading-relaxed mb-14">{data.intro}</p>

        <div className="space-y-10">
          {data.sections.map((s) => (
            <div key={s.h}>
              <h2 className="font-display text-xl md:text-2xl font-bold text-white mb-3">{s.h}</h2>
              <p className="text-base font-light text-slate-400 leading-relaxed">{s.p}</p>
            </div>
          ))}
        </div>

        <div className="mt-20 pt-8 border-t border-white/10">
          <p className="font-mono-ui text-xs text-slate-600">© 2026 Sapphire Alpha Capital. All rights reserved.</p>
        </div>
      </div>
    </div>
  );
};

export default LegalPage;
