import React from "react";
import { createRoot, hydrateRoot } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import "@fontsource-variable/bodoni-moda/opsz.css";
import "@fontsource-variable/archivo";
import "@fontsource-variable/jetbrains-mono";
import "@/index.css";
import App from "@/App";
import { installChunkErrorReload } from "@/lib/chunkErrorReload";

installChunkErrorReload();

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 60_000,
      refetchOnWindowFocus: false,
    },
  },
});

const tree = (
  <React.StrictMode>
    <QueryClientProvider client={queryClient}>
      <App />
    </QueryClientProvider>
  </React.StrictMode>
);

// The landing page ships prerendered (scripts/prerender.mjs) so its copy is
// in the first HTML. Hydrate it rather than rebuilding it. Every other URL is
// served the empty app shell, which mounts normally.
const container = document.getElementById("root");
if (container.hasAttribute("data-prerendered") && window.location.pathname === "/") {
  hydrateRoot(container, tree);
} else {
  container.removeAttribute("data-prerendered");
  createRoot(container).render(tree);
}
