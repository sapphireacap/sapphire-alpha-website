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
