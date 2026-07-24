import { useEffect } from "react";
import { Gauge } from "lucide-react";
import QuantLabToolShell from "./QuantLabToolShell";
import SharpeDashboardTool from "./SharpeDashboard";

export default function SharpeDashboardPage() {
  useEffect(() => { window.scrollTo(0, 0); }, []);
  return (
    <QuantLabToolShell
      title="Sharpe Dashboard"
      description="Sharpe, Sortino, and max drawdown across the Nifty 500 — compare picks or view the top ranked."
      icon={Gauge}
    >
      <SharpeDashboardTool />
    </QuantLabToolShell>
  );
}
