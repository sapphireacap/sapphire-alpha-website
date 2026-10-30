// Every visitor-facing string on the homepage, nav, footer, contact form and
// legal pages lives here, so copy review and copy changes touch ONE file.
//
// Copy approved by the owner on 2026-10-31 (Phase 3 review document).
// Any string still containing the placeholder marker "[COPY PENDING]" fails
// the production build (scripts/check-copy.mjs), so unapproved text cannot
// ship by accident.

export const SITE = {
  name: "Sapphire Alpha Capital",
  url: "https://www.sapphirealphacapital.com",
  email: "care@sapphirealphacapital.com",
  year: 2026,
  social: [
    { label: "LinkedIn", href: "https://www.linkedin.com/company/sapphirealphacapital" },
    { label: "X / Twitter", href: "https://x.com/sapphireacap" },
    { label: "Instagram", href: "https://www.instagram.com/sapphireacap/" },
    { label: "Telegram", href: "https://t.me/sapphireacap" },
  ],
};

export const META = {
  title: "Sapphire Alpha Capital | Quantitative Market Research Tools",
  description:
    "Index bias, price levels, breadth, relative strength and options readings computed from exchange data, plus charting studios and a market dashboard.",
};

export const HERO = {
  headline: ["Built on Research.", "Driven by Alpha."],
  sub:
    "Sapphire Alpha Capital builds quantitative research tools for the capital markets. Each tool computes from exchange data and shows its method and its limits.",
  whatItDoes:
    "The Alpha Terminal puts index bias, key price levels, breadth, relative strength and options readings in one place.",
  ctaPrimary: "Open Alpha Terminal",
  ctaPrimaryNote: (liveCount) => `${liveCount} engines live`,
  ctaSecondary: "Sign up",
  method: {
    label: "Method",
    text:
      "Each engine computes independently from exchange data. None of them sees another's output, so agreement between them is evidence rather than an average.",
  },
  limits: {
    label: "Limits",
    text:
      "Nothing here forecasts price and nothing here is advice. Where an engine has no reading, it says so instead of estimating one.",
  },
};

export const PRODUCT = {
  label: "The product",
  heading: "Current readings from the app.",
  intro: "This is real output from the Alpha Terminal and the Market Dashboard, not a mockup.",
  indicesCaption: "Market Dashboard, headline indices",
  vectorCaption: "Index Vector, Nifty 50",
  asOf: "As of",
  labels: {
    bias: "Index Vector bias",
    spot: "Spot",
    bullishAbove: "Turns bullish above",
    bearishBelow: "Turns bearish below",
    none: "No reading",
  },
  openLabel: "Open Alpha Terminal",
};

export const ABOUT = {
  label: "About · What We Build",
  heading: "Precision at the intersection of data and markets.",
  intro:
    "Sapphire Alpha Capital is a research-first platform for systematic investing, financial markets and quantitative analysis. It is grounded in evidence rather than prediction.",
  pillars: [
    {
      no: "01", tag: "Research", title: "Stock Research",
      body: "Peter Tingle reviews a stock's technical and fundamental risk signals in one report. Momentum Investing ranks the market's universe by risk-adjusted return.",
    },
    {
      no: "02", tag: "Markets", title: "Market Research",
      body: "Market Breadth shows the share of a group trending bullish. Relative Strength compares every pair in a peer group. The Market Dashboard tracks indices, sectors, advances and declines, and institutional flows.",
    },
    {
      no: "03", tag: "Systems", title: "Rule-Based Signals",
      body: "Index Vector, Gamma Pulse and Exitline turn index, futures and option data into rule-based readings. Each runs on its own, and none uses another's output.",
    },
  ],
  doesNotLabel: "What this does not do",
  doesNot: "These tools do not forecast prices, recommend trades or give advice. When an engine has no reading, it says so.",
};

// Founder block: the owner's rules allow ONLY the name, optional links and
// this one line. No credentials, titles, degrees or awards. The block stays
// hidden until a real name is supplied (see About.jsx), so a placeholder can
// never render on the live site.
export const FOUNDER = {
  label: "Who is behind this",
  name: "[TODO: founder name]",
  links: [], // [{ label, href }]
  line: "8 years in markets, specialising in Nifty and Bank Nifty derivatives. Built the engines behind the terminal.",
};

export const CONTACT = {
  label: "Contact",
  heading: "Get in touch.",
  intro: "Ask about a tool, report a problem or suggest an improvement.",
  fields: {
    name: "Name",
    email: "Email",
    company: "Company",
    optional: "(optional)",
    message: "Message",
    messagePlaceholder: "How can we help?",
  },
  submit: "Send Message",
  sending: "Sending",
  success: "Message sent. We will reply to the email you gave.",
  error: `The message did not send. Try again, or email ${SITE.email}.`,
  rateLimited: "You have sent several messages in a short time. Please try again later.",
  errors: {
    name: "Please enter your name.",
    email: "Please enter a valid email address.",
    message: "Please write a message.",
  },
};

export const FOOTER = {
  blurb: "Research-first tools for systematic investing and market analysis, built on exchange data.",
  disclaimer:
    "Sapphire Alpha Capital provides research and analytical tools for educational and informational purposes. It is not a registered investment adviser or research analyst, and nothing here is investment advice.",
  rights: "All rights reserved.",
};

// Per-route <title> and meta description. `private` routes stay out of
// search results.
const T = (page) => `${page} | ${SITE.name}`;
export const ROUTE_META = {
  "/": { title: META.title, description: META.description },
  "/alpha-terminal": {
    title: T("Alpha Terminal"),
    description: "Engines for index bias, price levels, breadth, relative strength, options and swing setups, each showing its method and its limits.",
  },
  "/black-box": {
    title: T("The Black Box"),
    description: "The Black Box is Sapphire Alpha Capital's collection of systematic trading strategies, developed and validated internally.",
  },
  "/pricing": {
    title: T("Pricing"),
    description: "Pricing for P&F Studio, which charts NSE stocks and indices with a full Point & Figure pattern and indicator library.",
  },
  "/pnf-studio": {
    title: T("P&F Studio"),
    description: "Point & Figure charting for NSE stocks and indices, with the full pattern and indicator library on every chart.",
  },
  "/renko-studio": {
    title: T("Renko Studio"),
    description: "Renko charting from the same studio as P&F Studio, covered by the same subscription.",
  },
  "/market": {
    title: T("Market Dashboard"),
    description: "Indices, sectors, advances and declines, institutional flows and global indices in one view.",
  },
  "/ipos": {
    title: T("IPOs"),
    description: "Current and upcoming mainboard IPOs, with a short breakdown of each company's Red Herring Prospectus.",
  },
  "/research": {
    title: T("Research"),
    description: "A live pulse on the market: breadth, movers, and a route into the per-stock research page.",
  },
  "/privacy": { title: T("Privacy Policy"), description: "What Sapphire Alpha Capital collects when you use this site, why, and who handles it." },
  "/terms": { title: T("Terms of Use"), description: "The terms for using the Sapphire Alpha Capital website and its tools." },
  "/disclaimer": { title: T("Disclaimer"), description: "Sapphire Alpha Capital provides research tools for information only. It does not give investment advice." },
  "/lattice": { title: T("Lattice"), description: "", private: true },
  "/login": { title: T("Log In"), description: "", private: true },
  "/signup": { title: T("Sign Up"), description: "", private: true },
};
export const PRIVATE_PREFIXES = ["/admin33", "/login", "/signup", "/forgot-password", "/reset-password", "/verify-email", "/not-available", "/lattice", "/journal", "/alpha-terminal/pnf", "/alpha-terminal/renko"];

// Legal pages. Drafted in plain language from what the code actually does
// (what is stored, which services process it). FLAGGED FOR LEGAL REVIEW
// before being relied on. Deliberately absent, because the facts were not
// supplied: refund policy, governing law and jurisdiction, data-retention
// periods.
const LEGAL_UPDATED = "Last updated: October 2026";
export const LEGAL = {
  privacy: {
    title: "Privacy Policy",
    updated: LEGAL_UPDATED,
    intro:
      "This policy explains what Sapphire Alpha Capital collects when you use this website and its tools, why we collect it, and who else handles it.",
    sections: [
      {
        h: "What We Collect",
        p: "If you write to us, we collect your name, email address, company (optional) and message. If you create an account, we collect your name, email address, username and a hashed password. Paid tools are paid for through Razorpay, and we do not see or store your card details. Our servers also record technical data such as your IP address and browser type, for security and to keep the service running.",
      },
      {
        h: "How We Use It",
        p: "We use it to reply to your messages, run your account, give you access to paid tools, protect the service from abuse, and fix problems. We do not sell your personal data.",
      },
      {
        h: "Who Handles It",
        p: "We use these services to run the site: Vercel (website hosting), Render (application hosting), MongoDB Atlas (database), Resend (email) and Razorpay (payments). They process data only to provide those services.",
      },
      {
        h: "Cookies and Browser Storage",
        p: "A sign-in cookie and browser storage keep you signed in. We do not use advertising or analytics cookies, and we do not use session-recording tools.",
      },
      {
        h: "Your Choices",
        p: `You can ask us to access, correct or delete your personal data by emailing ${SITE.email}.`,
      },
    ],
  },
  terms: {
    title: "Terms of Use",
    updated: LEGAL_UPDATED,
    intro: "By using this website and its tools you agree to these terms.",
    sections: [
      { h: "Using the Site", p: "You may use the site and its tools for your own research. Do not misuse the site, try to gain unauthorised access, or interfere with how it runs." },
      { h: "Accounts", p: "You are responsible for keeping your sign-in details safe and for activity on your account." },
      { h: "Paid Tools", p: "Paid tools are billed as shown on the pricing page. You can cancel a subscription at any time." },
      { h: "Information Only", p: "Everything on the site is for educational and informational purposes. Nothing on it is investment advice or a recommendation to buy or sell." },
      { h: "Data", p: "Market data comes from public and third-party exchange sources. It can be delayed, incomplete or wrong. Check it before you rely on it." },
      { h: "Availability", p: "Tools may change, pause or be withdrawn. Some are still being built." },
      { h: "Intellectual Property", p: "All content, branding and design on this site belong to Sapphire Alpha Capital and may not be reproduced without permission." },
      { h: "Limitation of Liability", p: "To the fullest extent the law allows, Sapphire Alpha Capital is not liable for losses from using, or being unable to use, the site or its tools, including trading losses." },
      { h: "Changes", p: "We may update these terms from time to time. Continuing to use the site means you accept the updated terms." },
    ],
  },
  disclaimer: {
    title: "Disclaimer",
    updated: LEGAL_UPDATED,
    intro: "The information on this website is provided for general informational and educational purposes only.",
    sections: [
      { h: "Not Investment Advice", p: "Nothing on this site is investment, financial, legal or tax advice, or a recommendation to buy or sell any security or instrument." },
      { h: "Not a Registered Adviser", p: "Sapphire Alpha Capital is not a registered investment adviser or research analyst." },
      { h: "No Offer or Solicitation", p: "This site is not an offer or solicitation to invest in any fund, product or strategy. Sapphire Alpha Capital does not currently offer any investment product." },
      { h: "Readings, Not Forecasts", p: "Readings describe what the data shows at a point in time. They do not forecast price. Past results do not indicate future results." },
      { h: "Risk", p: "Trading and investing in financial markets involve risk, including the loss of your capital." },
      { h: "Data", p: "Data shown on the site may be delayed or incomplete." },
    ],
  },
};
