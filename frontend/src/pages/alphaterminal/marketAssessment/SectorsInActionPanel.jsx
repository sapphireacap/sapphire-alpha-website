// Bullish/Bearish split by "Strength" -- % of each sector index's own
// constituents that are advancing (advances / (advances+declines+unchanged)),
// derived straight from the sector rows the snapshot already carries
// (each row already has its own advances/declines/unchanged from NSE's
// allIndices response -- see market_dashboard_engine.py's _shape_index_row).
// No separate data source, no proprietary vendor grouping -- Nifty's own
// classic sector indices only.
const TOP_N = 3;

// NSE's allIndices response returns advances/declines/unchanged as
// strings, not numbers (confirmed live) -- Number() them explicitly, or
// `+` silently concatenates ("9"+"6"+"0" -> "960") instead of adding.
const strengthOf = (row) => {
  const adv = Number(row.advances) || 0;
  const dec = Number(row.declines) || 0;
  const unch = Number(row.unchanged) || 0;
  const total = adv + dec + unch;
  return total ? (adv / total) * 100 : null;
};

const shortLabel = (index) => (index || "").replace(/^NIFTY /, "");

const SectorsInActionPanel = ({ sectors }) => {
  const withStrength = (sectors || [])
    .map((s) => ({ ...s, strength: strengthOf(s) }))
    .filter((s) => s.strength != null)
    .sort((a, b) => b.strength - a.strength);

  const bullish = withStrength.slice(0, TOP_N);
  const bearish = withStrength.slice(-TOP_N).reverse();

  const Row = ({ s, color }) => (
    <div className="flex items-center justify-between px-3 py-1.5 text-[11px] border-b" style={{ borderColor: "var(--term-border)" }}>
      <span style={{ color: "var(--term-text)" }}>{shortLabel(s.index)}</span>
      <span style={{ color }}>{s.strength.toFixed(1)}%</span>
    </div>
  );

  return (
    <div data-testid="mkt-sectors-in-action-panel">
      <div className="px-3 py-1.5 term-panel-head">SECTORS IN ACTION</div>
      {withStrength.length ? (
        <div className="grid grid-cols-2">
          <div>
            <div className="px-3 py-1 text-[10px] uppercase tracking-wider term-green border-b" style={{ borderColor: "var(--term-border)" }}>Bullish</div>
            {bullish.map((s) => <Row key={s.index} s={s} color="var(--term-green)" />)}
          </div>
          <div className="border-l" style={{ borderColor: "var(--term-border)" }}>
            <div className="px-3 py-1 text-[10px] uppercase tracking-wider term-red border-b" style={{ borderColor: "var(--term-border)" }}>Bearish</div>
            {bearish.map((s) => <Row key={s.index} s={s} color="var(--term-red)" />)}
          </div>
        </div>
      ) : (
        <div className="p-4 text-center term-grey text-[11px]">Sector data unavailable.</div>
      )}
    </div>
  );
};

export default SectorsInActionPanel;
