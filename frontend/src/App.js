import "@/App.css";
import { useEffect } from "react";
import { BrowserRouter, Routes, Route } from "react-router-dom";
import { Toaster } from "sonner";

import SmoothScroll from "@/components/site/SmoothScroll";
import Navbar from "@/components/site/Navbar";
import Hero from "@/components/site/Hero";
import EditorialMarquee from "@/components/site/EditorialMarquee";
import ComingSoon from "@/components/site/ComingSoon";
import About from "@/components/site/About";
import Manifesto from "@/components/site/Manifesto";
import Research from "@/components/site/Research";
import MarketInsights from "@/components/site/MarketInsights";
import Investing from "@/components/site/Investing";
import Contact from "@/components/site/Contact";
import Footer from "@/components/site/Footer";
import LegalPage from "@/components/site/LegalPage";
import AlphaTerminal from "@/pages/AlphaTerminal";
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
      <MarketInsights />
      <Investing />
      <Contact />
    </main>
    <Footer />
  </>
);

function App() {
  useEffect(() => { installAuthInterceptor(); }, []);

  return (
    <div className="App bg-void text-white">
      <div className="grain" />
      <BrowserRouter>
        <SmoothScroll>
          <Routes>
            <Route path="/" element={<Landing />} />
            <Route path="/alpha-terminal" element={<AlphaTerminal />} />
            <Route path="/admin" element={<Admin />} />
            <Route path="/signup" element={<SignupPage />} />
            <Route path="/login" element={<LoginPage />} />
            <Route path="/forgot-password" element={<ForgotPasswordPage />} />
            <Route path="/reset-password" element={<ResetPasswordPage />} />
            <Route path="/verify-email" element={<VerifyEmailPage />} />
            <Route path="/journal" element={<JournalLayout />}>
              <Route index element={<Dashboard />} />
              <Route path="new" element={<TradeEntry />} />
              <Route path="trades" element={<TradeLog />} />
              <Route path="reviews" element={<Reviews />} />
            </Route>
            <Route path="/privacy" element={<LegalPage page="privacy" />} />
            <Route path="/terms" element={<LegalPage page="terms" />} />
            <Route path="/disclaimer" element={<LegalPage page="disclaimer" />} />
          </Routes>
        </SmoothScroll>
      </BrowserRouter>
      <Toaster
        position="bottom-right"
        theme="dark"
        toastOptions={{
          style: {
            background: "#0A0D18",
            border: "1px solid rgba(255,255,255,0.1)",
            color: "#fff",
            fontFamily: "'Satoshi', sans-serif",
          },
        }}
      />
    </div>
  );
}

export default App;
