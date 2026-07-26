"""
Generic Renko brick-construction engine, shared by any Renko-based Black Box
strategy (currently Lumen SIP). Structurally distinct from the P&F engine in
blackbox_prism_alpha.py: P&F reverses only after a multi-box move within a
column; Renko has no separate reversal-count parameter — a single brick in
the opposite direction is enough to flip (confirmed against Definedge's own
Renko pattern docs: Two-Back/One-Back/Anchor-Bricks patterns all describe
single-brick reversal behavior).

Percentage bricks, DAILY-RESET (confirmed directly by the user, 2026-07-26):
the brick's rupee VALUE is recalculated once per trading day, as brick_pct
of that day's own OPENING price, and stays fixed for however many bricks
print while processing that day's bar. The next day's open produces a
fresh brick value. This replaced an earlier version that anchored a single
percentage ladder at the very first sample of the whole multi-year history
and never recalculated it — wrong: that makes brick size a function of
where the 10-year window happens to start, not of current price, and never
adapts as price drifts far from that starting point.
"""


def build_renko_bricks(bars: list, brick_pct: float) -> list:
    """bars: chronological [{ts|date, open, close, ...}, ...]. Samples each
    bar's close against a running Renko price level, stepping toward it in
    increments of THAT bar's own brick value (brick_pct * bar['open']).

    Returns a chronological list of brick dicts:
      {direction: 'up'|'down', level, open_price, close_price, ts}
    `level` is a simple running net-brick counter (+1 per up brick, -1 per
    down brick) — NOT a fixed percentage-ladder index (there isn't one
    anymore, since brick value itself changes day to day) — useful only as
    a monotonic reference for logging/display.
    """
    bars = [b for b in bars if b.get("close") and float(b["close"]) > 0]
    if len(bars) < 2:
        return []

    running_price = float(bars[0]["close"])
    bricks = []
    level = 0

    for bar in bars[1:]:
        brick_value = float(bar["open"]) * brick_pct
        if brick_value <= 0:
            continue
        price = float(bar["close"])
        ts = bar.get("ts") or bar.get("date")

        while True:
            if price >= running_price + brick_value:
                new_price = running_price + brick_value
                level += 1
                bricks.append({
                    "direction": "up",
                    "level": level,
                    "open_price": running_price,
                    "close_price": new_price,
                    "ts": ts,
                })
                running_price = new_price
            elif price <= running_price - brick_value:
                new_price = running_price - brick_value
                level -= 1
                bricks.append({
                    "direction": "down",
                    "level": level,
                    "open_price": running_price,
                    "close_price": new_price,
                    "ts": ts,
                })
                running_price = new_price
            else:
                break

    return bricks
