import { toneColor } from "./terminalTheme";

const fmtSigned = (n, digits = 2) => (n == null ? "—" : `${n >= 0 ? "+" : ""}${Number(n).toFixed(digits)}`);

// Compact row-based replacement for the old 400px vertical bar chart:
// one row per sector, thin zero-centered bar growing left (red) or
// right (green) from a center baseline, so all ~13 sectors fit in
// roughly a third of the old chart's height.
const SectorPanel = ({ rows }) => {
  const sorted = [...rows].sort((a, b) => (b.change_pct ?? 0) - (a.change_pct ?? 0));
  const maxAbs = Math.max(0.1, ...sorted.map((r) => Math.abs(r.change_pct ?? 0)));

  return (
    <div className="flex flex-col h-full" data-testid="mkt-sector-panel">
      <div className="px-3 py-1.5 term-panel-head">SECTOR PERFORMANCE</div>
      <div className="flex-1">
        {sorted.map((r) => {
          const pct = r.change_pct ?? 0;
          const widthPct = (Math.abs(pct) / maxAbs) * 50;
          return (
            <div key={r.index} className="flex items-center gap-2 px-3 py-1 border-b" style={{ borderColor: "var(--term-border)" }} data-testid={`mkt-sector-row-${r.index}`}>
              <span className="term-label w-[168px] shrink-0 truncate text-left">{r.index}</span>
              <div className="relative flex-1 h-2" style={{ background: "var(--term-panel-head)" }}>
                <div className="absolute top-0 bottom-0 left-1/2 w-px" style={{ background: "var(--term-border)" }} />
                <div
                  className="absolute top-0 bottom-0"
                  style={{
                    background: toneColor(pct),
                    width: `${widthPct}%`,
                    left: pct >= 0 ? "50%" : `${50 - widthPct}%`,
                  }}
                />
              </div>
              <span className="text-[11px] w-14 shrink-0 text-right" style={{ color: toneColor(pct) }}>{fmtSigned(pct)}%</span>
            </div>
          );
        })}
      </div>
    </div>
  );
};

export default SectorPanel;
