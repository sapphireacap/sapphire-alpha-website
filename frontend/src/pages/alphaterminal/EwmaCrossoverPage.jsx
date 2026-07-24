import { useEffect } from "react";
import { LineChart } from "lucide-react";
import QuantLabToolShell from "./QuantLabToolShell";
import EwmaCrossoverTool from "./EwmaCrossover";

export default function EwmaCrossoverPage() {
  useEffect(() => { window.scrollTo(0, 0); }, []);
  return (
    <QuantLabToolShell
      title="EWMA Crossover"
      description="Fast/slow EWMA crossover backtest vs. buy-and-hold, on any NSE/BSE/NFO/BFO symbol."
      icon={LineChart}
    >
      <EwmaCrossoverTool />
    </QuantLabToolShell>
  );
}
