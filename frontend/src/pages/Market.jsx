import { useEffect } from "react";
import Navbar from "../components/site/Navbar";
import Footer from "../components/site/Footer";
import MarketDashboardTool from "./alphaterminal/MarketDashboard";

export default function Market() {
  useEffect(() => { window.scrollTo(0, 0); }, []);

  return (
    <>
      <Navbar />
      <main className="relative bg-void min-h-screen">
        <section className="relative pt-28 pb-10 md:pt-32 md:pb-14" data-testid="market-header">
          <div className="container-x">
            <h1 className="font-display font-normal tracking-[-0.015em] text-white text-4xl md:text-5xl leading-[0.95]">Market Assessment</h1>
            <p className="text-sm md:text-base text-slate-400 font-light mt-4 max-w-xl">
              Major and sector indices, market breadth, and the Nifty / Bank Nifty setup — updated every 5 minutes through the session.
            </p>
          </div>
        </section>
        <div className="container-x pb-24 md:pb-32">
          <MarketDashboardTool />
        </div>
      </main>
      <Footer />
    </>
  );
}
