# Sapphire Alpha Capital — PRD

## Original Problem Statement
Premium, minimal, modern coming-soon website for Sapphire Alpha Capital, a quantitative research & financial markets platform under development. Dark theme (navy/black/white + sapphire blue), smooth animations, glassmorphism, subtle gradients, clean typography. Institutional/trustworthy like Renaissance, Two Sigma, Jane Street, Bloomberg, Stripe. Abstract finance visuals (no stock trader photos). Sections: Hero, Coming Soon, About, Research, Market Insights, Systematic Investing, Contact, footer with social + legal.

## User Choices
- Contact form: store submissions + send email (yes)
- Waitlist: capture + store email signups (yes)
- Logo provided (SAC hex monogram); legal pages authored by us; social links blank
- Directive: award-worthy motion — kinetic hero masked reveal, numbered manifesto chapters, editorial marquee, framer-motion + lenis smooth scroll, subtle parallax

## Architecture
- Backend: FastAPI + MongoDB (Motor). Endpoints: POST /api/waitlist, GET /api/waitlist/count, POST /api/contact. Email via Emergent-managed Resend (async, non-blocking).
- Frontend: React 19 + Tailwind + framer-motion + lenis + react-fast-marquee + custom canvas ParticleField. shadcn sonner for toasts.
- Fonts: Cabinet Grotesk (display), Satoshi (body), JetBrains Mono. Colors: void #030408, sapphire #1F5FD0.

## Implemented (2026-01)
- Kinetic hero with masked line-by-line reveal, parallax, particle network, live data readout
- Coming Soon waitlist module (dedup 409, count display, toasts)
- About/Pillars (01/02/03), numbered Manifesto chapters, Research hex node diagram, Market Insights bento, Systematic Investing framework + terminal readout
- Contact form (stores + emails), Footer (social + nav + legal wordmark), Legal pages /privacy /terms /disclaimer
- Fully responsive incl. mobile nav. Tested 100% backend + frontend (iteration_1).

## Backlog / Next
- P1: Real social URLs, favicon/OG image, actual research/blog content hub
- P2: Analytics events on waitlist/contact conversion; admin view for signups
- P2: SEO metadata + sitemap

## Update (2026-01) — Alpha Terminal + Admin
- New nav item "Alpha Terminal" (between Research & Insights) -> /alpha-terminal
- Alpha Terminal page: hero (LIVE ALPHA TERMINAL, static "Updated: Today, 09:30 AM IST"), Momentum Leaders table (Ticker, Company, Momentum Score, Volume, Bias badges) seeded NVDA/CRWD/PLTR; 3 "Coming Soon" scanner placeholders (Relative Strength, Breakout, Positional); proprietary disclaimer below table.
- Admin at /admin (not in nav): JWT Bearer auth (single admin seeded from env), CRUD + drag-drop reorder + Save/Cancel; changes persist to MongoDB and reflect on public page instantly.
- Backend: /api/auth/login, /api/auth/me, /api/terminal/scanners, /api/terminal/stocks (GET/POST/PUT/DELETE), /api/terminal/stocks/reorder/apply. Brute-force lockout. Future scanners activate by adding data via admin.
- Tested: 20/20 backend + all frontend flows pass (iteration_5).
- Also added: favicons (from SAC logo, transparent), title "Sapphire Alpha Capital", meta description "Built on Research. Driven by Alpha", OG/Twitter cards + og-image.png.

## Update (2026-01) — Straddle Compass (Nifty bias) + Accordion
- New indicator "Straddle Compass" on /alpha-terminal: shows Nifty BULLISH/BEARISH/NEUTRAL derived from ATM+200 & ATM-200 straddle P&F trends (falling +200 & rising -200 => Bullish; opposite => Bearish). Box 0.5% / 3-box reversal labels.
- Backend: db.nifty_signal (id=current); GET /api/terminal/signal (public), PUT /api/terminal/signal (admin, auto-derives bias when Neutral). Seeded default.
- Admin: SignalPanel to set spot/atm/legs/trend/note manually (Phase 1). Live immediately.
- Scanner sections converted to shadcn Accordion (Momentum open by default; others collapse to Coming Soon on click).
- Tested iteration_9: 8/8 backend + all frontend pass.
- PENDING Phase 2: live Definedge Integrate API automation (needs API creds). API notes: auth api_token+api_secret; historical 1-min OHLC at https://data.definedgesecurities.com/sds/history/NFO/{token}/minute/{from}/{to}; must map ATM CE/PE tokens from master file, compute straddle=CE+PE, build P&F (0.5% box, 3-box=~3% reversal), derive bias. Needs scheduler during market hours.
