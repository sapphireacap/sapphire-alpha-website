import { Link, useLocation } from "react-router-dom";
import { scrollToId } from "./SmoothScroll";

// A real <a href="/#id">. Middle-click, copy-link and no-JS all work. When
// the visitor is already on the landing page it scrolls smoothly instead of
// reloading; from any other page it navigates to the landing page and the
// browser jumps to the hash.
export const SectionLink = ({ id, onNavigate, children, ...rest }) => {
  const { pathname } = useLocation();
  const onClick = (e) => {
    if (e.metaKey || e.ctrlKey || e.shiftKey || e.button !== 0) return;
    onNavigate?.();
    if (pathname === "/") {
      e.preventDefault();
      scrollToId(id);
      window.history.replaceState(null, "", `/#${id}`);
    }
  };
  return (
    <Link to={`/#${id}`} onClick={onClick} {...rest}>
      {children}
    </Link>
  );
};

export default SectionLink;
