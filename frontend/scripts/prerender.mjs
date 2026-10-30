// Build step: bake the landing page into build/index.html.
//
//   build/index.html  -> the prerendered landing page (served for "/")
//   build/app.html    -> the untouched SPA shell (vercel.json sends every
//                        other path here, so /pricing etc. never flash
//                        landing-page HTML before their own JS loads)
//   build/sitemap.xml -> regenerated with today's date
//
// Rendering uses react-dom/server on the real <Landing/> component,
// bundled with esbuild. No headless browser, so nothing here can be
// missing on the build machine.
import { build } from "esbuild";
import fs from "fs";
import path from "path";
import { fileURLToPath, pathToFileURL } from "url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const BUILD = path.join(root, "build");
const tmp = path.join(root, "node_modules", ".cache", "prerender");
fs.mkdirSync(tmp, { recursive: true });

const manifest = JSON.parse(fs.readFileSync(path.join(BUILD, "asset-manifest.json"), "utf8")).files;
const mediaUrl = (base) => {
  const hit = manifest[`static/media/${base}`];
  if (!hit) throw new Error(`asset-manifest has no ${base}`);
  return hit;
};

const stubPlugin = {
  name: "stub-assets",
  setup(b) {
    // Stylesheets are irrelevant to markup. Catch them by resolved file (a
    // package import like "@fontsource-variable/inter" only turns into a
    // .css path after resolution) so esbuild never parses their url()s.
    b.onLoad({ filter: /\.css$/ }, () => ({ contents: "", loader: "js" }));
    b.onLoad({ filter: /\.svg$/ }, (a) => ({
      contents: `export default ${JSON.stringify(mediaUrl(path.basename(a.path)))};`,
      loader: "js",
    }));
  },
};

const outfile = path.join(tmp, "entry.mjs");
await build({
  entryPoints: [path.join(root, "scripts", "prerender-entry.jsx")],
  outfile,
  bundle: true,
  platform: "node",
  format: "esm",
  jsx: "automatic",
  loader: { ".js": "jsx", ".png": "dataurl", ".jpg": "dataurl", ".jpeg": "dataurl", ".webp": "dataurl", ".gif": "dataurl", ".json": "json" },
  alias: { "@": path.join(root, "src") },
  plugins: [stubPlugin],
  define: {
    "process.env.NODE_ENV": '"production"',
    "process.env.REACT_APP_BACKEND_URL": JSON.stringify(process.env.REACT_APP_BACKEND_URL || ""),
  },
  banner: { js: "import { createRequire as __cr } from 'module'; const require = __cr(import.meta.url);" },
  logLevel: "error",
});

const mod = await import(pathToFileURL(outfile).href);
const { META, SITE, renderLanding } = mod;
const html = renderLanding();
if (!html.includes("<h1")) throw new Error("prerender produced no <h1>");

// ---- compose index.html ------------------------------------------------
const shellPath = path.join(BUILD, "index.html");
const shell = fs.readFileSync(shellPath, "utf8");
fs.writeFileSync(path.join(BUILD, "app.html"), shell);

const esc = (s) => s.replace(/&/g, "&amp;").replace(/"/g, "&quot;").replace(/</g, "&lt;");
const setTag = (doc, re, replacement) => {
  if (!re.test(doc)) throw new Error(`index.html is missing ${re}`);
  return doc.replace(re, () => replacement);
};

let page = shell;
page = setTag(page, /<title>.*?<\/title>/s, `<title>${esc(META.title)}</title>`);
page = setTag(page, /<meta name="description" content="[^"]*"\s*\/?>/, `<meta name="description" content="${esc(META.description)}" />`);
page = setTag(page, /<meta property="og:title" content="[^"]*"\s*\/?>/, `<meta property="og:title" content="${esc(META.title)}" />`);
page = setTag(page, /<meta property="og:description" content="[^"]*"\s*\/?>/, `<meta property="og:description" content="${esc(META.description)}" />`);
page = setTag(page, /<meta name="twitter:title" content="[^"]*"\s*\/?>/, `<meta name="twitter:title" content="${esc(META.title)}" />`);
page = setTag(page, /<meta name="twitter:description" content="[^"]*"\s*\/?>/, `<meta name="twitter:description" content="${esc(META.description)}" />`);

const jsonLd = [
  {
    "@context": "https://schema.org",
    "@type": "Organization",
    name: SITE.name,
    url: `${SITE.url}/`,
    logo: `${SITE.url}/android-chrome-512x512.png`,
    description: META.description,
    sameAs: SITE.social.map((s) => s.href),
    contactPoint: [{ "@type": "ContactPoint", contactType: "customer support", email: SITE.email }],
  },
  {
    "@context": "https://schema.org",
    "@type": "WebSite",
    name: SITE.name,
    url: `${SITE.url}/`,
    description: META.description,
    inLanguage: "en",
  },
];

const preload = ["bodoni-moda-latin-opsz-normal.woff2", "archivo-latin-wght-normal.woff2", "jetbrains-mono-latin-wght-normal.woff2"]
  .map((f) => `<link rel="preload" as="font" type="font/woff2" crossorigin href="${mediaUrl(f)}" />`)
  .join("\n        ");

const headExtra = `
        ${preload}
        <script type="application/ld+json">${JSON.stringify(jsonLd).replace(/</g, "\\u003c")}</script>
        <noscript><style>[data-reveal]{opacity:1!important;transform:none!important}</style></noscript>`;
page = setTag(page, /<\/head>/, `${headExtra}\n    </head>`);

page = setTag(page, /<div id="root"><\/div>/, `<div id="root" data-prerendered>${html}</div>`);
page = page.replace(/<noscript>You need to enable JavaScript to run this app\.<\/noscript>/, "");
fs.writeFileSync(shellPath, page);

// ---- sitemap -----------------------------------------------------------
const today = new Date().toISOString().slice(0, 10);
const paths = ["/", "/alpha-terminal", "/black-box", "/pricing", "/pnf-studio", "/renko-studio", "/market", "/ipos", "/research", "/privacy", "/terms", "/disclaimer"];
const urls = paths.map((p) => `  <url>\n    <loc>${SITE.url}${p === "/" ? "/" : p}</loc>\n    <lastmod>${today}</lastmod>\n  </url>`).join("\n");
fs.writeFileSync(path.join(BUILD, "sitemap.xml"), `<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n${urls}\n</urlset>\n`);

console.log(`prerender: index.html ${Buffer.byteLength(page)} bytes (${html.length} chars of markup), app.html, sitemap.xml (${paths.length} urls)`);
