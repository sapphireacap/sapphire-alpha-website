import { useState, useEffect } from "react";
import axios from "axios";
import { Loader2 } from "lucide-react";
import "./marketAssessment/terminal.css";
import HeaderBar from "./marketAssessment/HeaderBar";
import IndexStrip from "./marketAssessment/IndexStrip";
import SectorPanel from "./marketAssessment/SectorPanel";
import BreadthPanel from "./marketAssessment/BreadthPanel";
import IndexSetupPanel from "./marketAssessment/IndexSetupPanel";
import IntradayBreadthPanel from "./marketAssessment/IntradayBreadthPanel";
import MultiAssetReturnsPanel from "./marketAssessment/MultiAssetReturnsPanel";
import TickerBar from "./marketAssessment/TickerBar";
import GlobalIndicesPanel from "./marketAssessment/GlobalIndicesPanel";
import SectorsInActionPanel from "./marketAssessment/SectorsInActionPanel";
import GainersLosersPanel from "./marketAssessment/GainersLosersPanel";
import OiBuildupPanel from "./marketAssessment/OiBuildupPanel";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;

// NSE cash session: 09:15-15:30 IST, weekdays. The backend snapshot itself
// only moves during this window (market-dashboard-refresh.yml's cron is
// weekdays-only, 09:15-15:30 IST) -- polling outside it would just hit the
// same cached doc repeatedly, so this gates the interval below rather than
// running it unconditionally.
//
// Uses Intl's own IANA timezone database rather than manual
// getTimezoneOffset() arithmetic -- the original manual-offset version
// (now.getTime() + (330 + now.getTimezoneOffset())*60000) silently
// double-counts the visitor's own local offset whenever it isn't 0
// (UTC), confirmed live: on an IST-local browser (offset -330), 330 +
// (-330) = 0, so it read the UTC clock AS IF it were already IST --
// shifting the computed "now" back by a full 5.5 hours and showing
// "NSE OPEN" at 15:49 IST, an hour past the real 15:30 close.
const isSessionLive = () => {
  const parts = new Intl.DateTimeFormat("en-US", {
    timeZone: "Asia/Kolkata", weekday: "short", hour: "2-digit", minute: "2-digit", hour12: false,
  }).formatToParts(new Date());
  const get = (type) => parts.find((p) => p.type === type)?.value;
  if (get("weekday") === "Sat" || get("weekday") === "Sun") return false;
  const minuteOfDay = parseInt(get("hour"), 10) * 60 + parseInt(get("minute"), 10);
  return minuteOfDay >= 9 * 60 + 15 && minuteOfDay <= 15 * 60 + 30;
};

// The headline strip polls its own dedicated fast route rather than
// waiting on the minute-scale snapshot below -- that snapshot's refresh
// cadence lives on an external cron (see market-dashboard-refresh.yml)
// this page has no visibility into, so the top ticker used to sit stale
// for however long that cron was actually firing. 5s is fast enough to
// read as live while staying well clear of the backend's own 4s cache.
const LIVE_HEADLINE_POLL_MS = 5000;

const MarketDashboardTool = () => {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const [liveHeadline, setLiveHeadline] = useState(null);
  const [liveTicks, setLiveTicks] = useState({});

  useEffect(() => {
    let cancelled = false;

    const load = (isInitial) => {
      axios.get(`${API}/terminal/market-dashboard/snapshot`)
        .then((snap) => {
          if (cancelled) return;
          setData(snap.data);
          setError(false);
        })
        .catch(() => { if (!cancelled) setError(true); })
        .finally(() => { if (!cancelled && isInitial) setLoading(false); });
    };

    load(true);

    // Polls every minute while the NSE cash session is live, self-stopping
    // the moment it isn't -- re-checked on every tick rather than just once
    // at mount, so a tab left open through the 15:30 close stops polling
    // instead of hitting the same cached snapshot forever.
    const id = setInterval(() => {
      if (!isSessionLive()) return;
      load(false);
    }, 60000);

    return () => { cancelled = true; clearInterval(id); };
  }, []);

  useEffect(() => {
    let cancelled = false;

    const loadHeadline = () => {
      axios.get(`${API}/terminal/market-dashboard/live-headline`)
        .then(({ data: d }) => { if (!cancelled && d?.headline?.length) setLiveHeadline(d.headline); })
        .catch(() => {}); // Keep the last good headline rather than blanking the strip.
    };

    loadHeadline();
    const id = setInterval(() => {
      if (!isSessionLive()) return;
      loadHeadline();
    }, LIVE_HEADLINE_POLL_MS);

    return () => { cancelled = true; clearInterval(id); };
  }, []);

  // Live Dhan-socket ticks (see backend/market_dashboard_stream.py) for the
  // ~20 indices Dhan's master resolves -- additive on top of the polls
  // above, which stay exactly as they are as the fallback if this drops.
  // NIFTY CONSUMER DURABLES has no Dhan equivalent and always falls
  // through to the snapshot/live-headline values untouched.
  useEffect(() => {
    let ws;
    let cancelled = false;
    let retryTimer;

    const connect = () => {
      if (cancelled) return;
      const wsBase = (process.env.REACT_APP_BACKEND_URL || "").replace(/^http/, "ws");
      ws = new WebSocket(`${wsBase}/api/terminal/market-dashboard/stream`);
      ws.onmessage = (event) => {
        try {
          const tick = JSON.parse(event.data);
          if (!tick?.index) return;
          setLiveTicks((prev) => ({ ...prev, [tick.index]: tick }));
        } catch {
          // Ignore a malformed frame -- next tick corrects it.
        }
      };
      ws.onclose = () => { if (!cancelled) retryTimer = setTimeout(connect, 5000); };
      ws.onerror = () => ws.close();
    };

    connect();
    return () => { cancelled = true; clearTimeout(retryTimer); ws?.close(); };
  }, []);

  const withLiveTicks = (rows) => rows?.map((row) => {
    const tick = liveTicks[row.index];
    return tick ? { ...row, last: tick.last, change: tick.change ?? row.change, change_pct: tick.change_pct ?? row.change_pct } : row;
  });

  const indices = data?.indices;
  const live = isSessionLive();
  const headlineRows = withLiveTicks(liveHeadline || indices?.headline);
  const sectorRows = withLiveTicks(indices?.sectors);
  const vixTick = liveTicks["INDIA VIX"];
  const vix = vixTick && indices?.vix ? { last: vixTick.last, change_pct: vixTick.change_pct ?? indices.vix.change_pct } : indices?.vix;

  if (loading) {
    return (
      <div className="mkt-terminal min-h-screen w-full flex items-center justify-center gap-3 text-[13px]" style={{ color: "var(--term-grey)" }}>
        <Loader2 className="animate-spin" size={16} /> Loading market dashboard…
      </div>
    );
  }
  if (error || !data) {
    return (
      <div className="mkt-terminal min-h-screen w-full flex items-center justify-center text-[13px]" style={{ color: "var(--term-grey)" }}>
        Market Dashboard hasn't been computed yet — check back shortly.
      </div>
    );
  }

  return (
    <div className="mkt-terminal min-h-screen w-full text-[13px]" data-testid="market-dashboard-tool">
      <HeaderBar live={live} />
      <TickerBar />

      {headlineRows?.length ? <IndexStrip rows={headlineRows} /> : (
        <div className="p-6 text-center term-grey text-[11px]">Index levels unavailable.</div>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-[1.35fr_1fr] border-b" style={{ borderColor: "var(--term-border)" }}>
        <div className="border-b lg:border-b-0 lg:border-r" style={{ borderColor: "var(--term-border)" }}>
          {sectorRows?.length ? <SectorPanel rows={sectorRows} /> : (
            <div className="p-6 text-center term-grey text-[11px]">Sector performance unavailable.</div>
          )}
        </div>
        <div>
          <div className="border-b" style={{ borderColor: "var(--term-border)" }}>
            {indices ? (
              <BreadthPanel
                advances={indices.market_advances}
                declines={indices.market_declines}
                unchanged={indices.market_unchanged}
                weekHigh={data.week_hilo?.high}
                weekLow={data.week_hilo?.low}
                vix={vix}
              />
            ) : (
              <div className="p-6 text-center term-grey text-[11px]">Breadth unavailable.</div>
            )}
          </div>
          <IndexSetupPanel />
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-[1.35fr_1fr] border-b" style={{ borderColor: "var(--term-border)" }}>
        <div className="border-b lg:border-b-0 lg:border-r" style={{ borderColor: "var(--term-border)" }}>
          <SectorsInActionPanel sectors={sectorRows} />
        </div>
        <div className="grid grid-cols-1 sm:grid-cols-2">
          <GlobalIndicesPanel rows={data.global_indices} />
          <div className="border-t sm:border-t-0 sm:border-l" style={{ borderColor: "var(--term-border)" }}>
            <GainersLosersPanel />
          </div>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 border-b" style={{ borderColor: "var(--term-border)" }}>
        <div className="border-b lg:border-b-0 lg:border-r" style={{ borderColor: "var(--term-border)" }}>
          <IntradayBreadthPanel />
        </div>
        <div>
          <MultiAssetReturnsPanel />
        </div>
      </div>

      <div className="border-b" style={{ borderColor: "var(--term-border)" }}>
        <OiBuildupPanel />
      </div>
    </div>
  );
};

export default MarketDashboardTool;
