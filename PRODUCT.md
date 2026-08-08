# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

Primary: **global / international self-directed traders** — people who already trade actively and want systematic structure before committing to a position, rather than commentary, tips, or narrative.

Their job: get a structured, reproducible read on market conditions — regime, momentum, breadth, relative strength, options structure — and use it as confirmation or a caution flag around a decision they are already weighing.

Confirmed by the user (2026-08-08). Note the live tension recorded under Capabilities and Constraints: the audience is global, while today's research coverage is predominantly Indian (NSE) instruments. Future work must not imply coverage that does not exist.

## Product Purpose

A research terminal that turns raw market data into systematic, explainable reads. The site sells and delivers Alpha Terminal — a set of independent research modules (regime confirmation, intraday levels, momentum ranking, relative strength, breadth, options trend, market assessment, swing and positional screens) — plus a research section (Lattice), an IPO dashboard, and a trading journal.

Success, per the user: **paid conversion, but earned through credibility first.** Being taken seriously by sophisticated people is the precondition; signups follow from legitimacy, not from persuasion tactics.

## Positioning

**Institutional method at an accessible price.** Techniques normally locked inside professional desks and terminals — Point & Figure structure, multi-instrument confluence, breadth and pairwise relative-strength matrices, risk-adjusted momentum ranking — delivered to individual traders at retail cost.

This is the claim a neighboring product could not truthfully copy, because it rests on engines actually implemented here against real market data, not on repackaged charting widgets.

## Operating Context

- Traders arrive before or during a session, already holding a thesis, looking for confirmation or a reason to stand down.
- Modules are read as a sequence of independent checks, not a single verdict; several explicitly instruct the user to treat output as confirmation rather than an entry trigger.
- Data is session-bound: NSE market hours and the NSE holiday calendar govern freshness, and several modules are intraday.
- Some modules are periodic rather than live (swing screens sync on a multi-day cadence; positional/momentum reads are rebalance-style, not intraday).

## Capabilities and Constraints

**Built and live:** ~25 routes. Alpha Terminal directory plus per-module detail pages (data-driven from `frontend/src/pages/alphaterminal/modules.js`), P&F and Renko charting studios, Lattice research, IPO dashboard with GMP, trading journal, auth (signup/login/verify/reset), pricing, legal pages.

**Module availability is explicit and honest:** each module carries a `live` flag. Paused modules render a "Coming Soon" placeholder and make no API calls. Currently paused: Sharpe Dashboard, EWMA Scanner, Breakout Candidates.

**Payments — a real constraint:** Razorpay is wired for **P&F Studio access only**, not a site-wide subscription. It uses one-time Orders per billing cycle, not recurring subscriptions (the account's Subscriptions product is not activated). Pricing is USD ($49 / $79 / $109 monthly). **Live mode additionally requires Razorpay international payments to be enabled on the account** — test mode accepts USD without it. This directly gates the global audience above and is an open item, not a solved one.

**Coverage constraint:** research modules are predominantly NSE/Indian instruments (NIFTY, BANKNIFTY, FINNIFTY, Nifty 500). US indices, gold, forex and crypto surfaces exist but are narrower. Gold currently resolves through a futures proxy at 5-minute granularity, not true 1-minute spot.

**Open decision (2026-08-08):** the user has confirmed the **waitlist should be removed**. The homepage currently runs a `ComingSoon` waitlist section and a "Get Notified" hero CTA that scrolls to it; both reflect a pre-launch posture the product has outgrown.

## Brand Commitments

- Name: **Sapphire Alpha Capital**. Tagline in use: *Built on Research. Driven by Alpha.*
- Identity: navy (`#10305C`) diamond mark, `frontend/src/assets/sac-logo-mark.svg`, matching the favicon set. Established 2026-08-08 — do not replace.
- **Proprietary naming rule (binding):** never name the underlying methodology (e.g. Camarilla) or the data vendor in any public-facing UI, copy, or error message. Numbers and outputs stay visible; attribution and method names do not.
- **Voice (binding, pre-existing standard):** concise, confident, active. Banned outright — "empowering traders", "unlock your potential", "revolutionary", "next generation", "cutting edge", "one stop solution", emoji, fake urgency, fake testimonials, fake statistics, fake company history, keyword-stuffed SEO phrasing. Register targets Bloomberg / TradingView / Renaissance / Stripe / Linear — explicitly not a finance blog.

## Evidence on Hand

**Real:** live market data through a broker API; computed engine output across all live modules; a P&F engine validated against a published reference text rather than reverse-engineered from charts; real IPO GMP from two independent sources shown side by side without a synthesized consensus.

**Deliberately absent — future work must not fabricate these:**
- No public performance or track record. Historical performance was moved to an admin-only dashboard and the public site shows zero trading data by explicit decision; backend routes are admin-gated to match.
- No testimonials, no customer logos, no user counts, no AUM, no company history.
- No fabricated numbers of any kind — this discipline is enforced in the backend and extends to all frontend copy.

## Product Principles

1. **Credibility precedes conversion.** If a sophisticated reader would find a claim unearned, it costs more than it gains.
2. **Never fabricate evidence.** Absent proof is stated as absent; a placeholder never poses as data.
3. **Institutional method, retail access.** The differentiator is rigor made reachable, not features made numerous.
4. **Methodology visible, implementation protected.** Explain how a read is constructed and what it cannot tell you; never expose proprietary logic or vendor attribution.
5. **Confirmation, not prescription.** Modules inform a decision the trader owns; nothing here is advice or a trigger.

## Accessibility & Inclusion

No product-specific standard has been established by the user. The pre-existing code bar requires semantic HTML, accessible components, and responsive behavior across breakpoints. Dark theme is the shipped default; a light theme exists in the codebase but its toggle is currently hidden.
