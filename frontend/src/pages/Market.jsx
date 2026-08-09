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
