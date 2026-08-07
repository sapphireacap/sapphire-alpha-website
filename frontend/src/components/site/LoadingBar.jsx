import "./LoadingBar.css";

// Standard loading indicator for the site -- a slim top progress bar with a
// drifting particle/comet trail, matching the sapphire/space visual language
// used elsewhere (ParticleField, void background). Use this for any
// route-level Suspense fallback or full-section async load. For inline
// loads (a card/table body refreshing), use <LoadingBar inline /> instead
// of a bare spinner.
export const LoadingBar = ({ inline = false, label }) => {
  if (inline) {
    return (
      <div className="sac-loadingbar sac-loadingbar--inline" role="status" aria-label={label || "Loading"}>
        <div className="sac-loadingbar__track">
          <span className="sac-loadingbar__comet" />
          <span className="sac-loadingbar__spark sac-loadingbar__spark--1" />
          <span className="sac-loadingbar__spark sac-loadingbar__spark--2" />
          <span className="sac-loadingbar__spark sac-loadingbar__spark--3" />
        </div>
        {label && <span className="sac-loadingbar__label">{label}</span>}
      </div>
    );
  }

  return (
    <div className="sac-loadingbar sac-loadingbar--fixed" role="status" aria-label={label || "Loading"}>
      <div className="sac-loadingbar__track">
        <span className="sac-loadingbar__comet" />
        <span className="sac-loadingbar__spark sac-loadingbar__spark--1" />
        <span className="sac-loadingbar__spark sac-loadingbar__spark--2" />
        <span className="sac-loadingbar__spark sac-loadingbar__spark--3" />
      </div>
    </div>
  );
};

export default LoadingBar;
