import useFlash from "./useFlash";
import { toneClass } from "./terminalTheme";

const fmt = (n, digits = 2) => (n == null ? "—" : Number(n).toLocaleString("en-IN", { maximumFractionDigits: digits, minimumFractionDigits: digits }));
const fmtSigned = (n, digits = 2) => (n == null ? "—" : `${n >= 0 ? "+" : ""}${fmt(n, digits)}`);

const IndexCell = ({ row }) => {
  const flash = useFlash(row.last);
  return (
    <div className={`px-3 py-2.5 border-r last:border-r-0 ${flash}`} style={{ borderColor: "var(--term-border)" }} data-testid={`mkt-index-cell-${row.index}`}>
      <p className="term-label truncate">{row.index}</p>
      <p className="text-[15px] mt-0.5" style={{ color: "var(--term-text)" }}>{fmt(row.last, row.last > 1000 ? 0 : 2)}</p>
      <p className={`text-[11px] mt-0.5 ${toneClass(row.change_pct)}`}>
        {fmtSigned(row.change)} ({fmtSigned(row.change_pct)}%)
      </p>
    </div>
  );
};

const IndexStrip = ({ rows }) => (
  <div className="grid border-b" style={{ gridTemplateColumns: `repeat(${rows.length}, minmax(0, 1fr))`, borderColor: "var(--term-border)" }} data-testid="mkt-index-strip">
    {rows.map((r) => <IndexCell key={r.index} row={r} />)}
  </div>
);

export default IndexStrip;
