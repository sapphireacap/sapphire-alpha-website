import { lazy, Suspense, useEffect, useState } from "react";

const ParticleField = lazy(() => import("./ParticleField"));

// Deterministic PRNG so the server-rendered SVG and the client's first
// render are byte-identical (no hydration mismatch) and the picture is the
// same every build.
const mulberry32 = (a) => () => {
  a |= 0; a = (a + 0x6d2b79f5) | 0;
  let t = Math.imul(a ^ (a >>> 15), 1 | a);
  t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
  return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
};

const W = 1440, H = 900, COUNT = 64, MAX = 170;
const buildStatic = () => {
  const rnd = mulberry32(14748);
  const nodes = Array.from({ length: COUNT }, () => ({
    x: Math.round(rnd() * W), y: Math.round(rnd() * H), r: +(rnd() * 1.4 + 0.7).toFixed(2),
  }));
  const lines = [];
  for (let i = 0; i < nodes.length; i++) {
    for (let j = i + 1; j < nodes.length; j++) {
      const d = Math.hypot(nodes[i].x - nodes[j].x, nodes[i].y - nodes[j].y);
      if (d < MAX) lines.push({ a: nodes[i], b: nodes[j], o: +((1 - d / MAX) * 0.22).toFixed(3) });
    }
  }
  return { nodes, lines };
};
const STATIC = buildStatic();

const StaticField = ({ hidden }) => (
  <svg
    viewBox={`0 0 ${W} ${H}`}
    preserveAspectRatio="xMidYMid slice"
    className={`absolute inset-0 h-full w-full transition-opacity duration-700 ${hidden ? "opacity-0" : "opacity-100"}`}
    aria-hidden="true"
    focusable="false"
  >
    {STATIC.lines.map((l, i) => (
      <line key={i} x1={l.a.x} y1={l.a.y} x2={l.b.x} y2={l.b.y} stroke="rgb(67,126,235)" strokeOpacity={l.o} strokeWidth="0.7" />
    ))}
    {STATIC.nodes.map((n, i) => (
      <circle key={i} cx={n.x} cy={n.y} r={n.r} fill="rgb(120,165,245)" fillOpacity="0.7" />
    ))}
  </svg>
);

// The constellation is painted as static SVG with the HTML, so it costs no
// JavaScript and is there from the first frame. The animated canvas is a
// progressive enhancement: it is fetched only once the page is idle, and
// never for visitors who prefer reduced motion or have asked to save data.
export const Constellation = () => {
  const [live, setLive] = useState(false);

  useEffect(() => {
    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const saveData = navigator.connection?.saveData === true;
    if (reduce || saveData) return undefined;
    const idle = window.requestIdleCallback || ((fn) => setTimeout(fn, 1500));
    const cancel = window.cancelIdleCallback || clearTimeout;
    const h = idle(() => setLive(true), { timeout: 3000 });
    return () => cancel(h);
  }, []);

  return (
    <div className="absolute inset-0" aria-hidden="true">
      <StaticField hidden={live} />
      {live && (
        <Suspense fallback={null}>
          <ParticleField />
        </Suspense>
      )}
    </div>
  );
};

export default Constellation;
