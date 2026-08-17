import { useState } from "react";
import { LayoutGrid, Rows2, Square } from "lucide-react";
import PnfChart from "./PnfChart";

/*
  Multi-chart layout for P&F Studio — TradingView-style 1/2/4 grid.

  PnfChart already owns its ENTIRE state internally (symbol, interval, box
  size, every overlay toggle) and takes no props from a parent to function,
  so four independent charts needed no state lifting or refactor — this
  file is purely a grid around four instances of a component that already
  worked standalone.

  All four cells stay MOUNTED at all times; layout only changes which are
  VISIBLE (via CSS) and how the grid divides. TradingView does the same:
  switching from a 4-up back to a 1-up does not re-plot the chart that was
  hidden, because it was never unmounted. The alternative -- conditionally
  rendering only the visible count -- would throw away each hidden chart's
  data/instrument/zoom on every layout switch, which reads as the tool
  forgetting what you were looking at.
*/

const LAYOUTS = [
  { key: "1", label: "1 Chart", icon: Square, cells: 1 },
  { key: "2", label: "2 Charts", icon: Rows2, cells: 2 },
  { key: "4", label: "4 Charts", icon: LayoutGrid, cells: 4 },
];

// Tailwind needs literal class strings (no dynamic template interpolation
// makes it into the build), so the grid shape per layout is spelled out
// rather than computed from `cells`.
const GRID_CLASS = {
  1: "grid-cols-1 grid-rows-1",
  2: "grid-cols-2 grid-rows-1",
  4: "grid-cols-2 grid-rows-2",
};

const LayoutPicker = ({ active, onChange }) => (
  <div
    className="flex items-center gap-1 rounded-lg border border-white/10 bg-[#0B1220] p-1"
    role="tablist"
    aria-label="Chart layout"
    data-testid="pnf-layout-picker"
  >
    {LAYOUTS.map(({ key, label, icon: Icon }) => (
      <button
        key={key}
        type="button"
        role="tab"
        aria-selected={active === key}
        title={label}
        onClick={() => onChange(key)}
        className={`h-7 w-7 flex items-center justify-center rounded-md transition-colors ${
          active === key ? "bg-sapphire-light/90 text-white" : "text-slate-500 hover:text-slate-300"
        }`}
        data-testid={`pnf-layout-${key}`}
      >
        <Icon size={14} />
      </button>
    ))}
  </div>
);

const PnfWorkspace = () => {
  const [layout, setLayout] = useState("1");
  const cellCount = LAYOUTS.find((l) => l.key === layout)?.cells || 1;

  return (
    <div className="h-[100dvh] w-screen overflow-hidden bg-[#060B14] text-white flex flex-col">
      <div className="shrink-0 flex items-center justify-end gap-2 px-3 py-1.5 border-b border-white/10 bg-[#0B1220]">
        <LayoutPicker active={layout} onChange={setLayout} />
      </div>

      <div className={`flex-1 min-h-0 grid ${GRID_CLASS[cellCount]}`} data-testid="pnf-workspace-grid">
        {[0, 1, 2, 3].map((i) => (
          <div
            key={`pnf-cell-${i}`}
            // Cells beyond the current layout's count stay mounted (see
            // module docstring) but are removed from layout AND painting,
            // so a hidden chart costs no space and no compositing.
            className={`min-w-0 min-h-0 overflow-hidden ${
              i < cellCount ? "block" : "hidden"
            } ${i % 2 === 0 && cellCount > 1 ? "border-r border-white/10" : ""} ${
              i < 2 && cellCount > 2 ? "border-b border-white/10" : ""
            }`}
            data-testid={`pnf-cell-${i}`}
          >
            <PnfChart embedded />
          </div>
        ))}
      </div>
    </div>
  );
};

export default PnfWorkspace;
