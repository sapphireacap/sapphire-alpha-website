import { useCallback, useEffect, useRef, useState } from "react";
import axios from "axios";

/*
  One place every live price on the site comes from.

  Before this, "live" meant each chart calling setInterval and REFETCHING
  ITS WHOLE SERIES every 30s -- hundreds of bars re-sent to move one
  candle. That reads as a chart that redraws, not one that's alive.

  The pattern here is what broker terminals actually do: fetch the heavy
  series ONCE, then poll a tiny quote and mutate only the forming candle
  via lightweight-charts' series.update(). Bandwidth drops to a few bytes
  per tick and the last candle moves continuously.

  Deliberately polling, not a WebSocket. A socket needs a process that
  stays alive, and the backend currently spins down when idle -- a
  connection that drops every quiet spell is worse than a poll that always
  works. Everything below is written so a socket can replace the transport
  later without any caller changing: consumers see {price, prevClose,
  change, changePct, stale}, and where that comes from is this file's
  business alone.

  Politeness matters here because the upstreams are rate-limited (Dhan is
  ~1 req/s; Definedge's spot route carries a 2s server-side cache). So:
    - one shared timer per (market, symbol), not one per component
    - paused entirely while the tab is hidden
    - paused when the market is closed, since the number cannot move
*/

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;

// Fast enough to read as live, slow enough to respect a 2s server cache
// and a ~1 req/s upstream ceiling.
export const LIVE_POLL_MS = 2000;

/* ------------------------- shared subscription bus ------------------------ */
// Two components showing the same symbol share ONE request. Without this,
// a page with a chart plus a price header would double every upstream call.
const channels = new Map(); // key -> { subscribers:Set, timer, last }

const readQuote = async (market, symbol) => {
  // India's Exitline covers arbitrary NSE cash / futures / option
  // contracts, which /terminal/spot cannot resolve — it only knows the
  // three index keys. Those instruments come through as an object
  // carrying the same params /exitline/levels was called with.
  if (symbol && typeof symbol === "object") {
    const { data } = await axios.get(`${API}/exitline/quote`, { params: symbol });
    return { price: data?.ltp ?? null, change: null, changePct: null };
  }
  // India indices keep their own dedicated fast route (2s server cache).
  if (!market || market === "india") {
    const { data } = await axios.get(`${API}/terminal/spot`, { params: { index: symbol } });
    const price = data?.spot == null ? null : Number(String(data.spot).replace(/,/g, ""));
    return {
      price,
      change: data?.change == null ? null : Number(String(data.change).replace(/,/g, "")),
      changePct: data?.change_pct == null ? null : Number(data.change_pct),
    };
  }
  const { data } = await axios.get(`${API}/markets/${market}/quote`, { params: { symbol } });
  return {
    price: data?.price ?? null,
    change: data?.change ?? null,
    changePct: data?.change_pct ?? null,
  };
};

const channelFor = (key, market, symbol) => {
  let ch = channels.get(key);
  if (ch) return ch;
  ch = { subscribers: new Set(), timer: null, last: null };
  channels.set(key, ch);

  const tick = async () => {
    if (typeof document !== "undefined" && document.hidden) return;
    try {
      const quote = await readQuote(market, symbol);
      if (quote.price == null) return;
      ch.last = { ...quote, at: Date.now() };
      ch.subscribers.forEach((fn) => fn(ch.last));
    } catch {
      // A failed poll keeps the previous value rather than blanking the
      // display -- a transient upstream hiccup shouldn't erase a price.
    }
  };

  tick();
  ch.timer = setInterval(tick, LIVE_POLL_MS);
  return ch;
};

/**
 * Live price for one instrument.
 * `enabled: false` stops polling entirely (market closed, no symbol yet).
 */
export const useLivePrice = (market, symbol, { enabled = true } = {}) => {
  const [quote, setQuote] = useState(null);

  // An instrument descriptor is an object, so it can't key a Map by
  // identity — a new object every render would open a new channel each
  // time. Serialised so the same instrument always maps to one channel.
  const key = `${market || "india"}:${typeof symbol === "object" ? JSON.stringify(symbol) : symbol}`;

  useEffect(() => {
    if (!enabled || !symbol) return undefined;
    const ch = channelFor(key, market, symbol);
    if (ch.last) setQuote(ch.last);
    ch.subscribers.add(setQuote);
    return () => {
      ch.subscribers.delete(setQuote);
      if (ch.subscribers.size === 0) {
        clearInterval(ch.timer);
        channels.delete(key);
      }
    };
    // `market` and `symbol` are intentionally not dependencies: `symbol` may
    // be an instrument descriptor rebuilt on every render, which would
    // re-subscribe (and re-open an upstream poll) continuously. `key` is its
    // stable serialisation and changes exactly when the instrument does.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, enabled]);

  return quote;
};

/**
 * Folds a live price into the forming candle of a lightweight-charts
 * series, without touching the rest of the series.
 *
 * `bars` is only read to seed the forming candle the first time; after
 * that this mutates a local copy, so a live tick never triggers a
 * re-render of the chart's data. That is the whole point -- series.update()
 * on one candle is orders of magnitude cheaper than setData() on all of
 * them, and it's what makes the last candle move rather than jump.
 */
export const useLiveCandle = (seriesRef, bars, price, intervalMinutes = 5) => {
  const formingRef = useRef(null);

  useEffect(() => { formingRef.current = null; }, [bars, intervalMinutes]);

  useEffect(() => {
    const series = seriesRef?.current;
    if (!series || price == null || !bars || bars.length === 0) return;

    const last = bars[bars.length - 1];
    if (last?.time == null) return;

    // Which bucket does "now" belong to? If the clock has moved past the
    // last bar's bucket, this tick opens a NEW candle rather than
    // stretching the old one into a bar that spans two intervals.
    const bucket = intervalMinutes * 60;
    const nowSec = Math.floor(Date.now() / 1000);
    const lastBucketEnd = last.time + bucket;
    const isNewBucket = nowSec >= lastBucketEnd;

    let forming = formingRef.current;
    if (!forming || (isNewBucket && forming.time === last.time)) {
      forming = isNewBucket
        ? { time: lastBucketEnd, open: price, high: price, low: price, close: price }
        : { time: last.time, open: last.open, high: last.high, low: last.low, close: price };
    }

    forming = {
      ...forming,
      high: Math.max(forming.high, price),
      low: Math.min(forming.low, price),
      close: price,
    };
    formingRef.current = forming;

    try {
      series.update(forming);
    } catch {
      // The chart can be mid-teardown on a symbol/interval switch; a
      // dropped tick is not worth surfacing.
    }
  }, [seriesRef, bars, price, intervalMinutes]);
};
