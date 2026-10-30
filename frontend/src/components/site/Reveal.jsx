import { motion } from "framer-motion";
import { EASE } from "../../lib/motion";

// Fade-up scroll reveal. Opacity and position only: a blur filter here used
// to leave text soft if the animation was interrupted or skipped. Reduced
// motion is handled in CSS (index.css, [data-reveal]) rather than in JS so
// the server-rendered and client-rendered markup are identical.
export const Reveal = ({ children, delay = 0, y = 24, className = "", ...rest }) => (
  <motion.div
    data-reveal
    initial={{ opacity: 0, y }}
    whileInView={{ opacity: 1, y: 0 }}
    viewport={{ once: true, amount: 0.1 }}
    transition={{ duration: 0.8, ease: EASE, delay }}
    className={className}
    {...rest}
  >
    {children}
  </motion.div>
);

export default Reveal;
