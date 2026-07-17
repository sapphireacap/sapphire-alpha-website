import { motion } from "framer-motion";

const EASE = [0.16, 1, 0.3, 1];

// Fade-up + blur scroll reveal. Wrap any block.
export const Reveal = ({ children, delay = 0, y = 40, className = "", ...rest }) => (
  <motion.div
    initial={{ opacity: 0, y, filter: "blur(10px)" }}
    whileInView={{ opacity: 1, y: 0, filter: "blur(0px)" }}
    viewport={{ once: true, margin: "-80px" }}
    transition={{ duration: 0.9, ease: EASE, delay }}
    className={className}
    {...rest}
  >
    {children}
  </motion.div>
);

export default Reveal;
