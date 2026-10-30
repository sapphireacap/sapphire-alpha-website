import { useEffect } from "react";
import { useLocation } from "react-router-dom";
import { META, ROUTE_META, PRIVATE_PREFIXES, SITE } from "@/content/homepage";

const setMeta = (selector, attr, value, create) => {
  let el = document.head.querySelector(selector);
  if (!el && create) { el = document.createElement(create.tag); Object.entries(create.attrs).forEach(([k, v]) => el.setAttribute(k, v)); document.head.appendChild(el); }
  if (el) el.setAttribute(attr, value);
};

// Keeps the document title, description, canonical URL, social tags and
// robots directive in step with the route. The landing page's own values
// are also written into the static HTML at build time (scripts/prerender)
// so crawlers that never run JavaScript see them too.
export const RouteMeta = () => {
  const { pathname } = useLocation();
  useEffect(() => {
    const clean = pathname.length > 1 ? pathname.replace(/\/+$/, "") : pathname;
    const m = ROUTE_META[clean] || { title: META.title, description: META.description };
    const isPrivate = m.private || PRIVATE_PREFIXES.some((p) => clean === p || clean.startsWith(`${p}/`));
    const url = `${SITE.url}${clean === "/" ? "/" : clean}`;

    document.title = m.title;
    setMeta('meta[name="description"]', "content", m.description, { tag: "meta", attrs: { name: "description" } });
    setMeta('link[rel="canonical"]', "href", url, { tag: "link", attrs: { rel: "canonical" } });
    setMeta('meta[property="og:title"]', "content", m.title, { tag: "meta", attrs: { property: "og:title" } });
    setMeta('meta[property="og:description"]', "content", m.description, { tag: "meta", attrs: { property: "og:description" } });
    setMeta('meta[property="og:url"]', "content", url, { tag: "meta", attrs: { property: "og:url" } });
    setMeta('meta[name="twitter:title"]', "content", m.title, { tag: "meta", attrs: { name: "twitter:title" } });
    setMeta('meta[name="twitter:description"]', "content", m.description, { tag: "meta", attrs: { name: "twitter:description" } });

    let robots = document.head.querySelector('meta[name="robots"]');
    if (isPrivate) {
      if (!robots) { robots = document.createElement("meta"); robots.setAttribute("name", "robots"); document.head.appendChild(robots); }
      robots.setAttribute("content", "noindex, nofollow");
    } else if (robots) {
      robots.remove();
    }
  }, [pathname]);
  return null;
};

export default RouteMeta;
