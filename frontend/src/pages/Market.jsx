import { useEffect } from "react";
import MarketDashboardTool from "./alphaterminal/MarketDashboard";

// Full-screen terminal takeover, by request -- no site Navbar/Footer/page
// header chrome around it. HeaderBar's own "SAC" mark links back to the
// homepage, so there's still a way out without breaking the "entire
// screen is the tool" brief.
export default function Market() {
  useEffect(() => { window.scrollTo(0, 0); }, []);

  return (
    <main className="min-h-screen w-full">
      <MarketDashboardTool />
    </main>
  );
}
