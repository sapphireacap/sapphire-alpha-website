// Every route in App.js is code-split with React.lazy(). A browser tab
// left open across a Vercel deploy has old HTML pointing at hashed chunk
// filenames the new build no longer serves -- clicking into any
// not-yet-visited route (Login included: LoginPage is itself a lazy
// chunk) throws a dynamic-import failure that no ErrorBoundary here
// catches, so the click just silently does nothing until a hard refresh
// picks up the new index.html. This is the standard fix: reload once,
// automatically, the moment that specific failure is seen.
const RELOAD_FLAG = "sac_chunk_reload_once";

const isChunkLoadError = (message) => {
  if (!message) return false;
  return /Loading chunk [\w.-]+ failed|Failed to fetch dynamically imported module|Importing a module script failed|error loading dynamically imported module/i.test(message);
};

const reloadOnce = () => {
  // Guards against a reload loop if the deploy itself is genuinely broken
  // (not just stale) -- one automatic retry, then leave it to the user.
  if (sessionStorage.getItem(RELOAD_FLAG)) return;
  sessionStorage.setItem(RELOAD_FLAG, "1");
  window.location.reload();
};

export const installChunkErrorReload = () => {
  window.addEventListener("error", (e) => { if (isChunkLoadError(e?.message)) reloadOnce(); });
  window.addEventListener("unhandledrejection", (e) => { if (isChunkLoadError(e?.reason?.message)) reloadOnce(); });

  // The bundle that's running right now clearly loaded fine -- clear the
  // flag shortly after mount so a LATER deploy (same tab, still open)
  // still gets its own one automatic reload rather than being silently
  // skipped because an earlier, unrelated deploy already used it up.
  setTimeout(() => sessionStorage.removeItem(RELOAD_FLAG), 5000);
};
