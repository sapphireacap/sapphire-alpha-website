import Marquee from "react-fast-marquee";

const WORDS = [
  "QUANTITATIVE RESEARCH",
  "SYSTEMATIC INVESTING",
  "MARKET STRUCTURE",
  "EVIDENCE DRIVEN",
  "ALPHA",
];

export const EditorialMarquee = () => {
  return (
    <section
      className="relative border-y border-white/5 py-8 md:py-12 bg-void overflow-hidden"
      data-testid="marquee-section"
      aria-hidden="true"
    >
      <Marquee speed={28} gradient gradientColor="#030408" gradientWidth={120} autoFill>
        {WORDS.map((w, i) => (
          <span key={i} className="flex items-center">
            <span className="marquee-text text-4xl md:text-6xl px-8 whitespace-nowrap">{w}</span>
            <span className="text-sapphire text-3xl md:text-5xl px-2">✦</span>
          </span>
        ))}
      </Marquee>
    </section>
  );
};

export default EditorialMarquee;
