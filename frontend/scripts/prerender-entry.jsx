import { renderToString } from "react-dom/server";
import { StaticRouter } from "react-router-dom";
import { ThemeProvider } from "@/contexts/ThemeContext";
import { AppShell } from "@/App";

export * from "@/content/homepage";

// The exact tree the browser hydrates (index.js -> App), with the router
// swapped for a StaticRouter pinned to "/".
export const renderLanding = () =>
  renderToString(
    <ThemeProvider>
      <AppShell Router={StaticRouter} routerProps={{ location: "/" }} />
    </ThemeProvider>,
  );
