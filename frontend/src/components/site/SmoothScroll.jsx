import { useEffect } from "react";

// Momentum smooth scrolling, loaded only when it can help: a fine pointer
// (mouse/trackpad) and no reduced-motion preference. Everyone else gets the
// browser's native scrolling, which on touch devices is better than any
// library's. The library itself is a separate chunk fetched after the page
// is idle, so it never competes with first paint.
export const SmoothScroll = ({ children }) => {
  useEffect(() => {
    const wantsMotion = !window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const finePointer = window.matchMedia("(pointer: fine)").matches;
    if (!wantsMotion || !finePointer) return undefined;

    let cancelled = false;
    let rafId;
    let lenis;
    let onVisibilityChange;

    const start = async () => {
      const { default: Lenis } = await import("lenis");
      if (cancelled) return;
      lenis = new Lenis({
        duration: 1.15,
        easing: (t) => Math.min(1, 1.001 - Math.pow(2, -10 * t)),
        smoothWheel: true,
      });
      window.__lenis = lenis;
      const raf = (time) => { lenis.raf(time); rafId = requestAnimationFrame(raf); };
      onVisibilityChange = () => {
        if (document.visibilityState === "visible") rafId = requestAnimationFrame(raf);
        else cancelAnimationFrame(rafId);
      };
      document.addEventListener("visibilitychange", onVisibilityChange);
      rafId = requestAnimationFrame(raf);
    };

    const idle = window.requestIdleCallback || ((fn) => setTimeout(fn, 1200));
    const cancelIdle = window.cancelIdleCallback || clearTimeout;
    const handle = idle(start, { timeout: 2500 });

    return () => {
      cancelled = true;
      cancelIdle(handle);
      if (onVisibilityChange) document.removeEventListener("visibilitychange", onVisibilityChange);
      cancelAnimationFrame(rafId);
      lenis?.destroy();
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
    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    el.scrollIntoView({ behavior: reduce ? "auto" : "smooth", block: "start" });
  }
};

export default SmoothScroll;
