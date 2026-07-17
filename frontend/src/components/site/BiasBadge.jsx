export const BiasBadge = ({ bias, testid }) => {
  const map = {
    Bullish: { dot: "bg-emerald-400", text: "text-emerald-300", ring: "border-emerald-400/30 bg-emerald-400/10" },
    Bearish: { dot: "bg-red-400", text: "text-red-300", ring: "border-red-400/30 bg-red-400/10" },
    Neutral: { dot: "bg-slate-400", text: "text-slate-300", ring: "border-slate-400/25 bg-slate-400/10" },
  };
  const s = map[bias] || map.Neutral;
  return (
    <span
      className={`inline-flex items-center gap-2 rounded-full border px-3 py-1 text-xs font-medium ${s.ring} ${s.text}`}
      data-testid={testid}
    >
      <span className={`h-1.5 w-1.5 rounded-full ${s.dot}`} />
      {bias}
    </span>
  );
};

export default BiasBadge;
