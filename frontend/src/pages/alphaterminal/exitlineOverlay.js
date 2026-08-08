import axios from "axios";
import { TRADER_TOKEN_KEY } from "../Auth";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;
const authHeaders = () => ({ headers: { Authorization: `Bearer ${localStorage.getItem(TRADER_TOKEN_KEY)}` } });

// Exitline levels only exist for NSE/FUT/OPT — the Definedge master file
// doesn't carry the derivative/cash listings for any other segment. The
// P&F and Renko charting platforms also cover US indices, Commodities, and
// Crypto, where this overlay has nothing to plot.
export const EXITLINE_SEGMENTS = ["NSE", "FUT", "OPT"];

// Mirrors Exitline.jsx exactly — same "Sapphire Levels" convention (never
// the underlying methodology name, see the proprietary-naming rule), same
// subset of the 11 computed levels, same colors. Kept in one place so the
// charting platform and the standalone Exitline module can never drift
// apart from each other.
export const EXITLINE_VISIBLE_LEVELS = ["H5", "H4", "H3", "Pivot", "L3", "L4"];
export const EXITLINE_LEVEL_COLORS = {
  H5: "#F87171", H4: "#F87171", H3: "#F87171",
  Pivot: "#22D3EE",
  L3: "#34D399", L4: "#34D399",
};
export const EXITLINE_DISPLAY_LABELS = { H5: "S5", H4: "S4", H3: "S3", Pivot: "PZ", L3: "V3", L4: "V4" };

// The endpoint also returns its own intraday `chart` array (built from the
// `interval` query param) — unused here, since the charting platform
// already has its own chart from the P&F/Renko engine. 5 is an arbitrary
// valid value, same default the standalone Exitline page opens with.
const LEVELS_QUERY_INTERVAL = 5;

export async function fetchExitlineLevels({ segment, symbol, expiry, strike, optionType }) {
  const { data } = await axios.get(`${API}/exitline/levels`, {
    params: {
      segment, symbol, interval: LEVELS_QUERY_INTERVAL,
      ...(segment === "FUT" || segment === "OPT" ? { expiry } : {}),
      ...(segment === "OPT" ? { strike, option_type: optionType } : {}),
    },
    ...authHeaders(),
  });
  return data; // { levels: {H5, H4, ..., L5}, ltp, prev_date, zone, sl, tp, ... }
}

// Inverse of the backend's price_at(level, anchor) in box_pct (percent)
// mode — the only mode this platform's charting UI exposes. Works from just
// two neighbouring grid points (always exactly 1 level apart, since
// `grid.levels` is every integer level from min to max) rather than
// threading anchor_price/box_pct through as separate props, and the same
// two-point log-ratio both interpolates within the rendered grid and
// extrapolates beyond it — which real Exitline levels routinely need, since
// H5/L5 (and often H4/L4 in a trending session) sit outside today's traded
// range by design; that IS the breakout-zone signal.
export function priceToFractionalLevel(price, gridLevels) {
  if (!gridLevels || gridLevels.length < 2 || price == null) return null;
  const n = gridLevels.length;
  let lo;
  let hi;
  if (price >= gridLevels[n - 1].price) { lo = gridLevels[n - 2]; hi = gridLevels[n - 1]; }
  else if (price <= gridLevels[0].price) { lo = gridLevels[0]; hi = gridLevels[1]; }
  else {
    for (let k = 0; k < n - 1; k += 1) {
      if (price >= gridLevels[k].price && price <= gridLevels[k + 1].price) {
        lo = gridLevels[k]; hi = gridLevels[k + 1];
        break;
      }
    }
  }
  if (!lo || !hi || hi.price <= 0 || lo.price <= 0 || hi.price === lo.price) return null;
  const frac = Math.log(price / lo.price) / Math.log(hi.price / lo.price);
  return lo.level + frac * (hi.level - lo.level);
}

// A new trading day's bars starting mid-column-series — used to draw
// session dividers on intraday charts. `startLabel` is each column/swing's
// own start_label, which for intraday bars is "YYYY-MM-DD HH:MM" (see
// pnf_chart.py's _bar_label / renko_chart.py's equivalent); the first 10
// characters are the calendar date regardless of interval or instrument.
// Takes a plain accessor rather than assuming a field name so it works
// against both P&F's `columns` and Renko's `swings`.
export function findSessionBoundaries(series, getStartLabel = (c) => c.start_label) {
  const bounds = [];
  let lastDate = null;
  for (const item of series) {
    const label = getStartLabel(item);
    const date = label ? label.slice(0, 10) : null;
    if (date && date !== lastDate) {
      if (lastDate !== null) bounds.push({ index: item.index, date });
      lastDate = date;
    }
  }
  return bounds;
}

// Session dividers only mean anything on a real intraday timeframe — a
// daily/weekly/monthly column's start_label is a single calendar date per
// column already, so "day boundary" and "column boundary" would be the
// same line drawn redundantly on every column. Defined as "not one of the
// three roll-up intervals" rather than an enumerated intraday list, so it
// can't silently drift out of sync with either chart's own interval keys.
const NON_INTRADAY = new Set(["daily", "weekly", "monthly"]);
export const isIntradayInterval = (interval) => !NON_INTRADAY.has(interval);
