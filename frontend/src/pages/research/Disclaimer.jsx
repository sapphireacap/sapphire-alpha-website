const SEBI_DISCLAIMER =
  "Research & education only — not investment advice (SEBI). Lattice displays an analytical score, not a buy/sell recommendation.";

export default function Disclaimer() {
  return (
    <p
      className="text-xs font-light text-slate-500 leading-relaxed max-w-3xl mx-auto text-center mt-6"
      data-testid="research-sebi-disclaimer"
    >
      {SEBI_DISCLAIMER}
    </p>
  );
}
