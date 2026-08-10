import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { ArrowLeft } from "lucide-react";

// Ticks its own clock every second, independent of the 1-minute data
// poll -- isolated in a leaf component so the second-hand doesn't
// re-render the whole dashboard.
const Clock = () => {
  const [now, setNow] = useState(new Date());
  useEffect(() => {
    const id = setInterval(() => setNow(new Date()), 1000);
    return () => clearInterval(id);
  }, []);
  const parts = new Intl.DateTimeFormat("en-GB", {
    timeZone: "Asia/Kolkata", day: "2-digit", month: "short",
    hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false,
  }).formatToParts(now);
  const get = (type) => parts.find((p) => p.type === type)?.value || "";
  return <span>{`${get("day")} ${get("month")} ${get("hour")}:${get("minute")}:${get("second")} IST`}</span>;
};

const HeaderBar = ({ live }) => (
  <div className="flex items-center justify-between px-3 py-2 border-b term-panel-head" style={{ borderColor: "var(--term-border)" }} data-testid="mkt-header-bar">
    <div className="flex items-center gap-3 text-[13px]">
      <Link
        to="/"
        className="flex items-center gap-1.5 px-2 py-1 border term-amber hover:brightness-125 transition-[filter]"
        style={{ borderColor: "var(--term-amber)" }}
        title="Back to Sapphire Alpha Capital"
        data-testid="mkt-home-link"
      >
        <ArrowLeft size={13} />
        <span className="font-bold">SAC HOME</span>
      </Link>
      <span className="term-cyan">&lt;MKT&gt;</span>
      <span className="term-grey">MARKET ASSESSMENT</span>
    </div>
    <div className="flex items-center gap-3 text-[11px]">
      <span className="flex items-center gap-1.5">
        <span className={`h-1.5 w-1.5 rounded-full ${live ? "term-green" : "term-grey"}`} style={{ background: live ? "var(--term-green)" : "var(--term-grey)" }} />
        <span className={live ? "term-green" : "term-grey"}>LIVE</span>
      </span>
      <span className={live ? "term-green" : "term-grey"}>{live ? "NSE OPEN" : "NSE CLOSED"}</span>
      <span className="term-grey"><Clock /></span>
    </div>
  </div>
);

export default HeaderBar;
