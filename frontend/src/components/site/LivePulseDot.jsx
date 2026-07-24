import { motion } from "framer-motion";

// Small pulsing dot for "Live" badges — framer-motion opacity loop rather
// than the CSS animate-ping/animate-pulse used elsewhere, per the Alpha
// Terminal redesign. `color` accepts any Tailwind bg-* class; defaults to
// emerald since that's the most common "live" signal on this page.
export const LivePulseDot = ({ color = "bg-emerald-400", size = "h-2 w-2", testid }) => (
  <motion.span
    className={`inline-block rounded-full ${color} ${size}`}
    animate={{ opacity: [1, 0.3, 1] }}
    transition={{ duration: 1.4, repeat: Infinity, ease: "easeInOut" }}
    data-testid={testid}
  />
);

export default LivePulseDot;
