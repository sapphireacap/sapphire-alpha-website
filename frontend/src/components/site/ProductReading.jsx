import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { ArrowUpRight } from "lucide-react";
import axios from "axios";
import IndexStrip from "@/pages/alphaterminal/marketAssessment/IndexStrip";
import "@/pages/alphaterminal/marketAssessment/terminal.css";
import { PRODUCT } from "@/content/homepage";
import Reveal from "./Reveal";

const API = `${process.env.REACT_APP_BACKEND_URL}/api/terminal`;
const fmt = (n) => (n == null ? PRODUCT.labels.none : Math.round(n).toLocaleString("en-IN"));

const BIAS_TONE = { Bullish: "text-emerald-300", Bearish: "text-red-300" };

// Real output only. The strip is the Market Dashboard's own IndexStrip
// component fed by its public live-headline route; the card renders the
// public Index Vector payload as returned. Nothing here is sample data: if
// either request fails the section is not shown at all, and it never
// invents a reading to fill the space.
export const ProductReading = () => {
  const ref = useRef(null);
  const [near, setNear] = useState(false);
  const [indices, setIndices] = useState(null);
  const [vector, setVector] = useState(null);
  const [indicesAsOf, setIndicesAsOf] = useState(null);
  const [failed, setFailed] = useState(false);
  const [wide, setWide] = useState(true);

  useEffect(() => {
    const el = ref.current;
    if (!el || !("IntersectionObserver" in window)) { setNear(true); return undefined; }
    const io = new IntersectionObserver(([e]) => { if (e.isIntersecting) { setNear(true); io.disconnect(); } }, { rootMargin: "400px" });
    io.observe(el);
    return () => io.disconnect();
  }, []);

  useEffect(() => {
    const mq = window.matchMedia("(min-width: 640px)");
    const on = () => setWide(mq.matches);
    on();
    mq.addEventListener("change", on);
    return () => mq.removeEventListener("change", on);
  }, []);

  useEffect(() => {
    if (!near) return undefined;
    let cancelled = false;
    // The stored Market Dashboard snapshot, not the live-headline route:
    // that one calls NSE on each request, which a public landing page
    // should not send visitor traffic to.
    Promise.all([
      axios.get(`${API}/market-dashboard/snapshot`),
      axios.get(`${API}/signal`, { params: { index: "NIFTY" } }),
    ])
      .then(([a, b]) => {
        const headline = a.data?.indices?.headline;
        if (!headline?.length) throw new Error("no index rows");
        if (!cancelled) { setIndices(headline); setIndicesAsOf(a.data.indices.as_of || null); setVector(b.data); }
      })
      .catch(() => { if (!cancelled) setFailed(true); });
    return () => { cancelled = true; };
  }, [near]);

  if (failed) return null;
  const rows = indices ? (wide ? indices : indices.slice(0, 3)) : [];

  return (
    <section id="product" ref={ref} aria-labelledby="product-heading" className="relative section-y" data-testid="product-section">
      <div className="container-x">
        <div className="grid grid-cols-1 lg:grid-cols-12 gap-12 lg:gap-16 items-start">
          <Reveal className="lg:col-span-4">
            <p className="label-mono mb-6">{PRODUCT.label}</p>
            <h2 id="product-heading" className="font-display font-normal tracking-[-0.015em] text-bone text-[2rem] md:text-5xl leading-[1.05]">
              {PRODUCT.heading}
            </h2>
            <p className="mt-6 text-base leading-relaxed text-bone/80">{PRODUCT.intro}</p>
            <Link
              to="/alpha-terminal"
              className="mt-8 inline-flex min-h-[44px] items-center gap-2 text-[15px] text-bone underline decoration-bone/40 underline-offset-[6px] hover:decoration-bone"
            >
              {PRODUCT.openLabel}
              <ArrowUpRight size={16} aria-hidden="true" />
            </Link>
          </Reveal>

          <div className="lg:col-span-8 mkt-terminal landing-product min-h-[22rem]" data-testid="product-panel">
            {indices && vector ? (
              <>
                <p className="px-3 pt-3 text-[11px] uppercase tracking-[0.14em] term-grey">{PRODUCT.indicesCaption}</p>
                <IndexStrip rows={rows} />
                {indicesAsOf && (
                  <p className="px-3 pt-2.5 text-[11px] uppercase tracking-[0.14em] term-grey">{PRODUCT.asOf} {indicesAsOf}</p>
                )}
                <div className="p-4 md:p-6">
                  <p className="text-[11px] uppercase tracking-[0.14em] term-grey">{PRODUCT.vectorCaption}</p>
                  <div className="mt-4 grid grid-cols-2 gap-x-6 gap-y-5 md:grid-cols-4">
                    <div>
                      <p className="term-label">{PRODUCT.labels.bias}</p>
                      <p className={`mt-1 text-2xl ${BIAS_TONE[vector.bias] || "text-bone"}`}>{vector.bias || PRODUCT.labels.none}</p>
                    </div>
                    <div>
                      <p className="term-label">{PRODUCT.labels.spot}</p>
                      <p className="mt-1 text-2xl text-white">{vector.spot ?? PRODUCT.labels.none}</p>
                    </div>
                    <div>
                      <p className="term-label">{PRODUCT.labels.bullishAbove}</p>
                      <p className="mt-1 text-2xl term-green">{fmt(vector.flip?.bullish?.flip_level)}</p>
                    </div>
                    <div>
                      <p className="term-label">{PRODUCT.labels.bearishBelow}</p>
                      <p className="mt-1 text-2xl term-red">{fmt(vector.flip?.bearish?.flip_level)}</p>
                    </div>
                  </div>
                  {vector.updated_label && (
                    <p className="mt-6 text-[11px] uppercase tracking-[0.14em] term-grey">
                      {PRODUCT.asOf} {vector.updated_label}
                    </p>
                  )}
                </div>
              </>
            ) : (
              <div className="h-[22rem]" aria-hidden="true" />
            )}
          </div>
        </div>
      </div>
    </section>
  );
};

export default ProductReading;
