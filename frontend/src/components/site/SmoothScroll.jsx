import { useEffect } from "react";
import Lenis from "lenis";

// Momentum smooth scrolling wrapper. Exposes lenis on window for anchor jumps.
export const SmoothScroll = ({ children }) => {
  useEffect(() => {
    const lenis = new Lenis({
      duration: 1.15,
      easing: (t) => Math.min(1, 1.001 - Math.pow(2, -10 * t)),
      smoothWheel: true,
      touchMultiplier: 1.6,
    });
    window.__lenis = lenis;

    let rafId;
    const raf = (time) => {
      lenis.raf(time);
      rafId = requestAnimationFrame(raf);
    };

    // Pause the rAF loop while the tab is backgrounded -- no point driving
    // scroll physics for a page nobody is looking at.
    const onVisibilityChange = () => {
      if (document.visibilityState === "visible") {
        rafId = requestAnimationFrame(raf);
      } else {
        cancelAnimationFrame(rafId);
      }
    };
    document.addEventListener("visibilitychange", onVisibilityChange);
    rafId = requestAnimationFrame(raf);

    return () => {
      document.removeEventListener("visibilitychange", onVisibilityChange);
      cancelAnimationFrame(rafId);
      lenis.destroy();
      window.__lenis = null;
    };
  }, []);

  return children;
};

export const scrollToId = (id) => {
  const el = document.getElementById(id);
  if (!el) return;
  if (window.__lenis) {
    window.__lenis.scrollTo(el, { offset: -80, duration: 1.4 });
  } else {
    el.scrollIntoView({ behavior: "smooth" });
  }
};

export default SmoothScroll;
