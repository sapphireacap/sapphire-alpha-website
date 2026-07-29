"""
Cost model shared by the backtest harness and the live/paper engine -- one
implementation, so a trade's reported net P&L can never be computed two
different ways. Pure functions, no I/O.

Every rate lives in `config["costs"]` (blackbox_options_config.py) --
nothing hardcoded here. Slippage is modeled as a PRICE adjustment (buys
fill worse/higher, sells fill worse/lower) applied before P&L is computed;
brokerage/STT/exchange/SEBI/GST are modeled as separate cash cost line
items on top. Gross and net are both returned so callers can report them
separately, per explicit instruction ("Report gross and net separately").
"""

def apply_slippage(price: float, order_side: str, costs_cfg: dict) -> float:
    """order_side: 'buy' or 'sell' -- the ACTUAL order placed (a short
    leg's entry is a 'sell' order even though the position itself is
    'short'). Buys fill slightly higher, sells fill slightly lower."""
    adj = price * costs_cfg["slippage_pct"]
    return price + adj if order_side == "buy" else price - adj


def _order_costs(notional: float, order_side: str, costs_cfg: dict) -> float:
    stt = notional * costs_cfg["stt_sell_pct"] if order_side == "sell" else 0.0
    exch = notional * costs_cfg["exchange_txn_pct"]
    sebi = notional * costs_cfg["sebi_fee_pct"]
    brokerage = costs_cfg["brokerage_per_lot"]
    gst = (brokerage + exch) * costs_cfg["gst_pct"]
    return brokerage + stt + exch + sebi + gst


def evaluate_trade_costs(legs: list, lot_size: int, costs_cfg: dict) -> dict:
    """legs: [{"side": "long"|"short", "entry_price": float, "exit_price": float,
    "lots": int}, ...] -- one entry per option leg in the trade (a single
    long option for Convexity Window; short-ATM + long-2xOTM for Gamma
    Backspread).

    Returns {"gross_pnl", "net_pnl", "total_costs", "legs": [...per-leg
    detail with effective fill prices...]}."""
    gross_pnl = 0.0
    net_pnl = 0.0
    total_costs = 0.0
    leg_detail = []

    for leg in legs:
        side = leg["side"]
        qty = lot_size * leg["lots"]
        entry_order_side = "buy" if side == "long" else "sell"
        exit_order_side = "sell" if side == "long" else "buy"
        direction = 1 if side == "long" else -1

        eff_entry = apply_slippage(leg["entry_price"], entry_order_side, costs_cfg)
        eff_exit = apply_slippage(leg["exit_price"], exit_order_side, costs_cfg)

        leg_gross = (leg["exit_price"] - leg["entry_price"]) * qty * direction
        leg_net_of_slippage = (eff_exit - eff_entry) * qty * direction

        entry_costs = _order_costs(eff_entry * qty, entry_order_side, costs_cfg)
        exit_costs = _order_costs(eff_exit * qty, exit_order_side, costs_cfg)
        leg_costs = entry_costs + exit_costs

        gross_pnl += leg_gross
        net_pnl += leg_net_of_slippage - leg_costs
        total_costs += leg_costs
        leg_detail.append({
            "side": side, "lots": leg["lots"], "entry_price": leg["entry_price"], "exit_price": leg["exit_price"],
            "effective_entry_price": eff_entry, "effective_exit_price": eff_exit,
            "gross_pnl": leg_gross, "costs": leg_costs,
        })

    return {"gross_pnl": gross_pnl, "net_pnl": net_pnl, "total_costs": total_costs, "legs": leg_detail}
