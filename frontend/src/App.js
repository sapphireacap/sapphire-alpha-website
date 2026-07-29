import "@/App.css";
import { useEffect } from "react";
import { BrowserRouter, Routes, Route } from "react-router-dom";
import { Toaster } from "sonner";

import { ThemeProvider, useTheme } from "@/contexts/ThemeContext";
import SmoothScroll from "@/components/site/SmoothScroll";
import Navbar from "@/components/site/Navbar";
import Hero from "@/components/site/Hero";
import EditorialMarquee from "@/components/site/EditorialMarquee";
import ComingSoon from "@/components/site/ComingSoon";
import PausedFeature from "@/components/site/PausedFeature";
import About from "@/components/site/About";
import Manifesto from "@/components/site/Manifesto";
import Research from "@/components/site/Research";
import Investing from "@/components/site/Investing";
import Contact from "@/components/site/Contact";
import Footer from "@/components/site/Footer";
import LegalPage from "@/components/site/LegalPage";
import NotFound from "@/components/site/NotFound";
import AlphaTerminal from "@/pages/AlphaTerminal";
import BlackBox from "@/pages/BlackBox";
import StrategyDetail from "@/pages/blackbox/StrategyDetail";
import ModuleDetail from "@/pages/alphaterminal/ModuleDetail";
import Ipos from "@/pages/Ipos";
import IpoDetail from "@/pages/IpoDetail";
import Aurora from "@/pages/research/Aurora";
import FacetView from "@/pages/research/FacetView";
import Admin from "@/pages/Admin";
import { SignupPage, LoginPage, ForgotPasswordPage, ResetPasswordPage, VerifyEmailPage } from "@/pages/Auth";
import { installAuthInterceptor } from "@/lib/auth";
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
      <EditorialMarquee />
      <ComingSoon />
      <About />
      <Manifesto />
      <Research />
      <Investing />
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
            <Route path="/black-box/:slug" element={<StrategyDetail />} />
            <Route path="/alpha-terminal/:slug" element={<ModuleDetail />} />
            <Route path="/ipos" element={<Ipos />} />
            <Route path="/ipos/:id" element={<IpoDetail />} />
            {/* Research (Aurora/FacetView) paused 2026-07-29 to cut backend
                memory/load -- real components untouched below, just not
                routed to right now. Swap back to <Aurora />/<FacetView />
                to restore. */}
            <Route path="/research" element={<PausedFeature title="Research" description="The Research terminal is temporarily paused. It'll be back online shortly." />} />
            <Route path="/research/:symbol" element={<PausedFeature title="Research" description="The Research terminal is temporarily paused. It'll be back online shortly." />} />
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
            ? { background: "#0A0D18", border: "1px solid rgba(255,255,255,0.1)", color: "#fff", fontFamily: "'Satoshi', sans-serif" }
            : { background: "#ffffff", border: "1px solid rgba(10,15,31,0.1)", color: "#0a0f1f", fontFamily: "'Satoshi', sans-serif" },
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
