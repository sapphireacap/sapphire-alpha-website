import "@/App.css";
import { useEffect } from "react";
import { BrowserRouter, Routes, Route } from "react-router-dom";
import { Toaster } from "sonner";

import { ThemeProvider, useTheme } from "@/contexts/ThemeContext";
import SmoothScroll from "@/components/site/SmoothScroll";
import Navbar from "@/components/site/Navbar";
import Hero from "@/components/site/Hero";
import ComingSoon from "@/components/site/ComingSoon";
import PausedFeature from "@/components/site/PausedFeature";
import About from "@/components/site/About";
import NotAvailablePage from "@/components/site/NotAvailablePage";
import Contact from "@/components/site/Contact";
import Footer from "@/components/site/Footer";
import LegalPage from "@/components/site/LegalPage";
import NotFound from "@/components/site/NotFound";
import AlphaTerminal from "@/pages/AlphaTerminal";
import BlackBox from "@/pages/BlackBox";
import ModuleDetail from "@/pages/alphaterminal/ModuleDetail";
import PnfChart from "@/pages/alphaterminal/PnfChart";
import PnfStudio from "@/pages/PnfStudio";
import Ipos from "@/pages/Ipos";
import IpoDetail from "@/pages/IpoDetail";
import Pricing from "@/pages/Pricing";
import Aurora from "@/pages/research/Aurora";
import FacetView from "@/pages/research/FacetView";
import LatticeHome from "@/pages/lattice/LatticeHome";
import LatticeRun from "@/pages/lattice/LatticeRun";
import Admin from "@/pages/Admin";
import { SignupPage, LoginPage, ForgotPasswordPage, ResetPasswordPage, VerifyEmailPage } from "@/pages/Auth";
import { installAuthInterceptor, RequirePnfAccess } from "@/lib/auth";
import JournalLayout from "@/pages/journal/JournalLayout";
import Dashboard from "@/pages/journal/Dashboard";
import TradeEntry from "@/pages/journal/TradeEntry";
import TradeLog from "@/pages/journal/TradeLog";
import Reviews from "@/pages/journal/Reviews";

const Landing = () => (
  <>
    <Navbar />
    <main className="relative">
      <Hero />
      <About />
      <ComingSoon />
      <Contact />
    </main>
    <Footer />
  </>
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
          <Routes>
            <Route path="/" element={<Landing />} />
            <Route path="/alpha-terminal" element={<AlphaTerminal />} />
            <Route path="/black-box" element={<BlackBox />} />
            {/* Must precede the /:slug route below — otherwise "pnf" is
                swallowed as a module slug and never reaches this page.
                Paid-access gated (see RequirePnfAccess) -- /pnf-studio is
                the marketing/subscribe page anyone lacking access lands on. */}
            <Route path="/alpha-terminal/pnf" element={<RequirePnfAccess><PnfChart /></RequirePnfAccess>} />
            <Route path="/pnf-studio" element={<PnfStudio />} />
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
            <Route path="/lattice" element={<LatticeHome />} />
            <Route path="/lattice/:symbol" element={<LatticeRun />} />
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
