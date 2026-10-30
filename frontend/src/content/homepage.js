// Every visitor-facing string on the homepage, nav, footer and contact form
// lives here, so copy review and copy changes touch ONE file.
//
// Strings marked [COPY PENDING] are placeholders for the Phase 3 approval
// gate -- they exist so layout can be built and tested, and must never ship.
// scripts/check-copy.mjs fails the build if one is still present.

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
  title: "Sapphire Alpha Capital | Quantitative Research & Market Intelligence",
  description:
    "Research-driven financial technology platform offering quantitative analysis, market intelligence, advanced charting, and systematic trading tools.",
};

export const HERO = {
  headline: ["Built on Research.", "Driven by Alpha."],
  sub:
    "Sapphire Alpha Capital is building a quantitative research platform focused on research, technology and analytical tools for the capital markets. Currently under development. More to come.",
  whatItDoes: "[COPY PENDING] One plain sentence saying what the Alpha Terminal does.",
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
  heading: "[COPY PENDING] Heading for the live-reading section.",
  intro: "[COPY PENDING] One line saying these are real, current readings from the app.",
  indicesCaption: "[COPY PENDING] Caption for the index strip.",
  vectorCaption: "[COPY PENDING] Caption for the Index Vector reading.",
  asOf: "As of",
  labels: { bias: "Index Vector bias", spot: "Spot", bullishAbove: "Bullish above", bearishBelow: "Bearish below", none: "No reading" },
  unavailable: "[COPY PENDING] Shown when live data cannot be reached.",
  openLabel: "Open Alpha Terminal",
};

export const ABOUT = {
  label: "About · What We Build",
  heading: "Precision at the intersection of data and markets.",
  intro:
    "Sapphire Alpha Capital is a research-first platform focused on systematic investing, financial markets, and quantitative analysis — grounded in evidence rather than prediction.",
  pillars: [
    {
      no: "01", tag: "Research", title: "Investment Research",
      body: "Studying markets through data, evidence, and disciplined analysis to understand how prices move over time.",
    },
    {
      no: "02", tag: "Markets", title: "Market Research",
      body: "Exploring trends, sectors, macro developments, and market behaviour to uncover meaningful insights.",
    },
    {
      no: "03", tag: "Systems", title: "Systematic Investing",
      body: "Building rule-based investment frameworks that prioritize consistency, discipline, and repeatability.",
    },
  ],
  doesNotLabel: "What this does not do",
  doesNot: "[COPY PENDING] A plain line on what the tools do not do.",
};

// Founder block: hard rules allow ONLY the name and this one line. No
// credentials, titles, degrees or awards.
export const FOUNDER = {
  label: "Who is behind this",
  name: "[TODO: founder name]",
  links: [], // [{ label, href }] -- supplied by the owner
  line: "8 years in markets, specialising in Nifty and Bank Nifty derivatives. Built the engines behind the terminal.",
};

export const CONTACT = {
  label: "Contact",
  heading: "Let's build something meaningful.",
  intro:
    "Whether you're interested in our research, collaborations, or future initiatives, we'd love to hear from you.",
  fields: {
    name: "Name",
    email: "Email",
    company: "Company",
    optional: "(optional)",
    message: "Message",
    messagePlaceholder: "Tell us what you're interested in…",
  },
  submit: "Send Message",
  sending: "Sending",
  success: "Message sent. We'll be in touch shortly.",
  error: "Something went wrong. Please try again, or email us directly.",
  rateLimited: "Too many messages from this connection. Please try again in a few minutes.",
  errors: {
    name: "Please enter your name.",
    email: "Please enter a valid email address.",
    message: "Please write a message.",
  },
};

export const FOOTER = {
  blurb:
    "Building a research-first platform focused on systematic investing, financial markets, and quantitative analysis.",
  disclaimer: "[COPY PENDING] Footer disclaimer: not a registered adviser, not advice.",
  rights: "All rights reserved.",
};

// Per-route <title> and meta description. Titles are plain page names.
// Descriptions are [COPY PENDING] until approved. `private` routes are
// kept out of search results.
const T = (page) => `${page} | ${SITE.name}`;
const D = (page) => `[COPY PENDING] One-line description of ${page}.`;
export const ROUTE_META = {
  "/": { title: META.title, description: META.description },
  "/alpha-terminal": { title: T("Alpha Terminal"), description: D("the Alpha Terminal") },
  "/black-box": { title: T("The Black Box"), description: D("the Black Box") },
  "/pricing": { title: T("Pricing"), description: D("pricing") },
  "/pnf-studio": { title: T("P&F Studio"), description: D("P&F Studio") },
  "/renko-studio": { title: T("Renko Studio"), description: D("Renko Studio") },
  "/market": { title: T("Market Dashboard"), description: D("the Market Dashboard") },
  "/ipos": { title: T("IPOs"), description: D("the IPO dashboard") },
  "/research": { title: T("Research"), description: D("Research") },
  "/lattice": { title: T("Lattice"), description: D("Lattice"), private: true },
  "/privacy": { title: T("Privacy Policy"), description: D("the privacy policy") },
  "/terms": { title: T("Terms of Use"), description: D("the terms of use") },
  "/disclaimer": { title: T("Disclaimer"), description: D("the disclaimer") },
  "/login": { title: T("Log In"), description: D("log in"), private: true },
  "/signup": { title: T("Sign Up"), description: D("sign up"), private: true },
};
export const PRIVATE_PREFIXES = ["/admin33", "/login", "/signup", "/forgot-password", "/reset-password", "/verify-email", "/not-available", "/lattice", "/journal", "/alpha-terminal/pnf", "/alpha-terminal/renko"];
