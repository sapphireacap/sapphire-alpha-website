import { useEffect } from "react";
import { useLocation } from "react-router-dom";
import Navbar from "@/components/site/Navbar";
import Hero from "@/components/site/Hero";
import ProductReading from "@/components/site/ProductReading";
import About from "@/components/site/About";
import Contact from "@/components/site/Contact";
import Footer from "@/components/site/Footer";
import Constellation from "@/components/site/Constellation";
import { scrollToId } from "@/components/site/SmoothScroll";

// Arriving at /#about (from the footer or nav of another page) should land
// on that section. The router does not scroll to hashes on its own.
const useHashScroll = () => {
  const { hash } = useLocation();
  useEffect(() => {
    if (!hash) return undefined;
    const id = hash.slice(1);
    const t = setTimeout(() => scrollToId(id), 80);
    return () => clearTimeout(t);
  }, [hash]);
};

export const Landing = () => {
  useHashScroll();
  return (
    // One continuous ground for the whole landing page. The constellation is
    // fixed behind every section rather than living inside the hero, so the
    // plate colour runs unbroken from the first viewport through the footer.
    <div className="relative bg-plate">
      <a href="#main" className="skip-link">Skip to main content</a>
      <div className="fixed inset-0 pointer-events-none" aria-hidden="true">
        <Constellation />
      </div>
      <Navbar />
      <main id="main" className="relative">
        <Hero />
        <ProductReading />
        <About />
        <Contact />
      </main>
      <Footer />
    </div>
  );
};

export default Landing;
