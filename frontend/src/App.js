import "@/App.css";
import { useEffect, lazy, Suspense } from "react";
import { BrowserRouter, Routes, Route } from "react-router-dom";
import { Toaster } from "sonner";

import { ThemeProvider, useTheme } from "@/contexts/ThemeContext";
import SmoothScroll from "@/components/site/SmoothScroll";
import Navbar from "@/components/site/Navbar";
import Hero from "@/components/site/Hero";
import ParticleField from "@/components/site/ParticleField";
import PausedFeature from "@/components/site/PausedFeature";
import About from "@/components/site/About";
import NotAvailablePage from "@/components/site/NotAvailablePage";
import Contact from "@/components/site/Contact";
import Footer from "@/components/site/Footer";
import LegalPage from "@/components/site/LegalPage";
import NotFound from "@/components/site/NotFound";
import LoadingBar from "@/components/site/LoadingBar";
import { installAuthInterceptor, RequirePnfAccess, RequireAuth } from "@/lib/auth";
import { TRADER_TOKEN_KEY } from "@/pages/Auth";

// Everything below is only needed once a visitor navigates to that specific
// route, so it's code-split out of the initial bundle instead of shipping
// the trading terminal / chart studios / admin panel to every landing-page
// visitor up front.
const AlphaTerminal = lazy(() => import("@/pages/AlphaTerminal"));
const BlackBox = lazy(() => import("@/pages/BlackBox"));
const BlackBoxStrategyDetail = lazy(() => import("@/pages/BlackBoxStrategyDetail"));
const ModuleDetail = lazy(() => import("@/pages/alphaterminal/ModuleDetail"));
const PnfWorkspace = lazy(() => import("@/pages/alphaterminal/PnfWorkspace"));
const PnfStudio = lazy(() => import("@/pages/PnfStudio"));
const RenkoChart = lazy(() => import("@/pages/alphaterminal/RenkoChart"));
const RenkoStudio = lazy(() => import("@/pages/RenkoStudio"));
const Ipos = lazy(() => import("@/pages/Ipos"));
const IpoDetail = lazy(() => import("@/pages/IpoDetail"));
const Pricing = lazy(() => import("@/pages/Pricing"));
const Aurora = lazy(() => import("@/pages/research/Aurora"));
const FacetView = lazy(() => import("@/pages/research/FacetView"));
const LatticeHome = lazy(() => import("@/pages/lattice/LatticeHome"));
const LatticeRun = lazy(() => import("@/pages/lattice/LatticeRun"));
const Market = lazy(() => import("@/pages/Market"));
const Admin = lazy(() => import("@/pages/Admin"));
const SignupPage = lazy(() => import("@/pages/Auth").then((m) => ({ default: m.SignupPage })));
const LoginPage = lazy(() => import("@/pages/Auth").then((m) => ({ default: m.LoginPage })));
const ForgotPasswordPage = lazy(() => import("@/pages/Auth").then((m) => ({ default: m.ForgotPasswordPage })));
const ResetPasswordPage = lazy(() => import("@/pages/Auth").then((m) => ({ default: m.ResetPasswordPage })));
const VerifyEmailPage = lazy(() => import("@/pages/Auth").then((m) => ({ default: m.VerifyEmailPage })));

const Landing = () => (
  // One continuous ground for the whole landing page. The particle field is
  // fixed behind every section rather than living inside the hero, so the
  // plate colour runs unbroken from the first viewport through the footer
  // instead of seaming where the hero ends.
  <div className="relative bg-plate">
    <div className="fixed inset-0 pointer-events-none" aria-hidden="true">
      <ParticleField />
    </div>
    <Navbar />
    <main className="relative">
      <Hero />
      <About />
      <Contact />
    </main>
    <Footer />
  </div>
);

const AppShell = () => {
  useEffect(() => { installAuthInterceptor(); }, []);
  const { theme } = useTheme();
  const isDark = theme === "dark";

  return (
    <div className="App bg-void text-white">
      <div className="grain" />
      <BrowserRouter>
        <SmoothScroll>
          <Suspense fallback={<LoadingBar />}>
          <Routes>
            <Route path="/" element={<Landing />} />
            <Route path="/alpha-terminal" element={<AlphaTerminal />} />
            <Route path="/black-box" element={<BlackBox />} />
            <Route path="/black-box/:slug" element={<BlackBoxStrategyDetail />} />
            {/* Must precede the /:slug route below — otherwise "pnf" is
                swallowed as a module slug and never reaches this page.
                Paid-access gated (see RequirePnfAccess) -- /pnf-studio is
                the marketing/subscribe page anyone lacking access lands on. */}
            <Route path="/alpha-terminal/pnf" element={<RequirePnfAccess><PnfWorkspace /></RequirePnfAccess>} />
            <Route path="/pnf-studio" element={<PnfStudio />} />
            {/* Same reasoning as /alpha-terminal/pnf above: must precede
                the /:slug route or "renko" gets swallowed as a module slug. */}
            <Route path="/alpha-terminal/renko" element={<RequirePnfAccess><RenkoChart /></RequirePnfAccess>} />
            <Route path="/renko-studio" element={<RenkoStudio />} />
            <Route path="/alpha-terminal/:slug" element={<ModuleDetail />} />
            {/* Shared placeholder for every nav entry that isn't public yet
                (P&F Studio, Log In / Sign Up) -- see NotAvailablePage. */}
            <Route path="/not-available" element={<NotAvailablePage />} />
            <Route path="/pricing" element={<Pricing />} />
            <Route path="/ipos" element={<Ipos />} />
            <Route path="/ipos/:id" element={<IpoDetail />} />
            {/* Research (Aurora/FacetView) restored 2026-08-05 -- was paused
                2026-07-29 to cut backend memory/load, re-enabled alongside
                the new Lattice pipeline which depends on the same
                stock_terminal backend infra. */}
            <Route path="/research" element={<Aurora />} />
            <Route path="/research/:symbol" element={<FacetView />} />
            <Route path="/lattice" element={<RequireAuth tokenKey={TRADER_TOKEN_KEY} loginPath="/login"><LatticeHome /></RequireAuth>} />
            <Route path="/lattice/:symbol" element={<RequireAuth tokenKey={TRADER_TOKEN_KEY} loginPath="/login"><LatticeRun /></RequireAuth>} />
            <Route path="/market" element={<Market />} />
            <Route path="/admin33" element={<Admin />} />
            <Route path="/signup" element={<SignupPage />} />
            <Route path="/login" element={<LoginPage />} />
            <Route path="/forgot-password" element={<ForgotPasswordPage />} />
            <Route path="/reset-password" element={<ResetPasswordPage />} />
            <Route path="/verify-email" element={<VerifyEmailPage />} />
            {/* Trade Journal paused 2026-07-29 to cut backend memory/load --
                real JournalLayout/Dashboard/TradeEntry/TradeLog/Reviews
                components untouched below, just not routed to right now.
                Swap back to the commented block below to restore. */}
            <Route path="/journal/*" element={<PausedFeature title="Trade Journal" description="The Trade Journal is temporarily paused. It'll be back online shortly." />} />
            {/* <Route path="/journal" element={<JournalLayout />}>
              <Route index element={<Dashboard />} />
              <Route path="new" element={<TradeEntry />} />
              <Route path="trades" element={<TradeLog />} />
              <Route path="reviews" element={<Reviews />} />
            </Route> */}
            <Route path="/privacy" element={<LegalPage page="privacy" />} />
            <Route path="/terms" element={<LegalPage page="terms" />} />
            <Route path="/disclaimer" element={<LegalPage page="disclaimer" />} />
            <Route path="*" element={<NotFound />} />
          </Routes>
          </Suspense>
        </SmoothScroll>
      </BrowserRouter>
      <Toaster
        position="bottom-right"
        theme={theme}
        toastOptions={{
          style: isDark
            ? { background: "#0A0D18", border: "1px solid rgba(255,255,255,0.1)", color: "#fff", fontFamily: "'Inter', sans-serif" }
            : { background: "#ffffff", border: "1px solid rgba(10,15,31,0.1)", color: "#0a0f1f", fontFamily: "'Inter', sans-serif" },
        }}
      />
    </div>
  );
};

function App() {
  return (
    <ThemeProvider>
      <AppShell />
    </ThemeProvider>
  );
}

export default App;
