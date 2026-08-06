"""
The Strata -- Lattice's memory system. Owns the paper portfolio's actual
position lifecycle (open -> mark-to-market -> close) and the realized-
outcome record The Vault reads before every new decision.

Modeled on three existing precedents in this codebase, combined:
  - momentum_track_record.py's capture/evaluate/summarize shape (idempotent
    entry capture, later evaluation, aggregate stats) -- but that's a
    single-day model (enter ~9:40am, evaluate at that day's 15:30 close).
    Lattice's positions are multi-day (The Forge proposes a holding
    horizon in days, not a same-session exit), so evaluation here is a
    periodic check against stop/target/horizon instead of one fixed
    end-of-day evaluation.
  - blackbox_prism_alpha.py's open/closed position lifecycle with a live-
    checked stop/target -- same mechanics, force-close condition changed
    from "session end" to "holding horizon elapsed."
  - blackbox_lumen_sip.py's _walk_portfolio cash-ledger style -- real
    rupee amounts moved in/out of a cash balance on open/close, not
    percentages recomputed against a moving total on every read. Position
    size is still expressed as a PERCENT OF STARTING CAPITAL when The
    Forge/Temper/Vault reason about it (simpler for an LLM to reason
    about), but the moment a position actually opens, that percent is
    converted once into a fixed rupee amount and cash is debited/credited
    like a real ledger from then on.

Long-only, by design: The Forge's own system prompt only ever proposes
BUY (open) or SELL (close an existing long) -- never a short. Matches
every other equity-only strategy already on this platform (Swing Picks,
Lumen SIP's "no leverage").

Disclosed simplification: position size is a percent of STARTING capital,
not current total portfolio value -- avoids a circular mark-to-market
dependency (computing "current total value" would itself require pricing
every other open position) for a paper portfolio where the distinction
doesn't materially change what's being tested. Restorable to a
compounding model later if that becomes worth the complexity.
"""
import logging
import uuid
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

DEFAULT_STARTING_CAPITAL = 1_000_000  # ₹10L paper capital -- an arbitrary
                                        # but clean round number; nothing
                                        # about the pipeline's logic depends
                                        # on this specific value.
DEFAULT_MAX_HOLDING_DAYS = 30  # safety net only -- used when a BUY somehow
                                # reaches here with holding_horizon_days
                                # unset (a malformed-Forge-response fallback
                                # case), so a position can never stay open
                                # forever by construction.


async def get_or_init_portfolio_state(db) -> dict:
    state = await db.lattice_portfolio_state.find_one({"id": "current"}, {"_id": 0})
    if state:
        return state
    state = {
        "id": "current", "starting_capital": DEFAULT_STARTING_CAPITAL,
        "cash": DEFAULT_STARTING_CAPITAL, "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.lattice_portfolio_state.update_one({"id": "current"}, {"$set": state}, upsert=True)
    return state


async def live_price(definedge, master, symbol: str):
    """Best-effort live NSE price -- returns None on any resolution/fetch
    failure rather than raising, same fail-open convention
    momentum_track_record.py's capture_entries already uses for the same
    kind of live quote lookup."""
    try:
        resolved = definedge.resolve_symbol(master, "NSE", symbol)
        if not resolved:
            return None
        return await definedge.equity_quote("NSE", resolved["token"])
    except Exception as e:  # noqa: BLE001
        logger.warning("The Strata: could not fetch live price for %s: %s", symbol, e)
        return None


async def log_decision(db, symbol: str, trail: dict) -> str:
    """Writes the complete audit trail for one pipeline run to
    lattice_decisions, regardless of outcome -- including HOLD/REJECTED
    runs. Returns the new decision's id."""
    decision_id = str(uuid.uuid4())
    doc = {
        "id": decision_id, "symbol": symbol,
        "run_at": datetime.now(timezone.utc).isoformat(),
        **trail,
    }
    await db.lattice_decisions.insert_one(doc)
    return decision_id


async def open_position(db, definedge, symbol: str, industry, decision_id: str, forge_decision: dict, final_position_size_pct: float) -> dict:
    """Captures a real live entry price, converts the proposed percent-of-
    starting-capital into a fixed rupee amount, debits cash by that
    amount, and writes the new open position. Idempotent is NOT needed
    here the way momentum_track_record.capture_entries needs it (that's
    called from an external once-a-day sync that could double-fire; this
    is only ever called once per pipeline run, from lattice_routes.py)."""
    master = await definedge._get_all_master()
    entry_price = await live_price(definedge, master, symbol)
    if entry_price is None:
        return {"opened": False, "reason": f"Could not fetch a live price for {symbol}."}

    state = await get_or_init_portfolio_state(db)
    capital_allocated = state["starting_capital"] * (final_position_size_pct / 100)
    if capital_allocated > state["cash"]:
        # Shouldn't happen -- The Temper already checked available cash --
        # but a stale read or a race with another open is possible, and
        # this must never let cash go negative.
        return {"opened": False, "reason": f"Insufficient paper cash: need {capital_allocated:.0f}, have {state['cash']:.0f}."}

    position_id = str(uuid.uuid4())
    holding_horizon_days = forge_decision.get("holding_horizon_days") or DEFAULT_MAX_HOLDING_DAYS
    doc = {
        "id": position_id, "symbol": symbol, "industry": industry, "status": "open",
        "entry_price": entry_price, "entry_date": datetime.now(timezone.utc).date().isoformat(),
        "capital_allocated": capital_allocated, "position_size_pct": final_position_size_pct,
        "stop_loss_pct": forge_decision.get("stop_loss_pct"), "target_pct": forge_decision.get("target_pct"),
        "holding_horizon_days": holding_horizon_days,
        "decision_id": decision_id,
        "exit_price": None, "exit_date": None, "exit_reason": None,
        "realized_pnl_pct": None, "exit_value": None,
    }
    await db.lattice_positions.insert_one(doc)
    await db.lattice_portfolio_state.update_one(
        {"id": "current"},
        {"$set": {"cash": state["cash"] - capital_allocated, "updated_at": datetime.now(timezone.utc).isoformat()}},
    )
    doc.pop("_id", None)
    return {"opened": True, "position": doc}


async def close_position(db, position: dict, exit_price: float, exit_reason: str) -> dict:
    """Realizes P&L, credits cash, marks the position closed. `position`
    must be an already-fetched open-position doc (caller already has it
    from check_open_positions or a manual admin close)."""
    realized_pnl_pct = (exit_price - position["entry_price"]) / position["entry_price"] * 100
    exit_value = position["capital_allocated"] * (1 + realized_pnl_pct / 100)

    await db.lattice_positions.update_one(
        {"id": position["id"]},
        {"$set": {
            "status": "closed", "exit_price": exit_price,
            "exit_date": datetime.now(timezone.utc).date().isoformat(),
            "exit_reason": exit_reason, "realized_pnl_pct": realized_pnl_pct, "exit_value": exit_value,
        }},
    )
    state = await get_or_init_portfolio_state(db)
    await db.lattice_portfolio_state.update_one(
        {"id": "current"},
        {"$set": {"cash": state["cash"] + exit_value, "updated_at": datetime.now(timezone.utc).isoformat()}},
    )
    return {"closed": True, "realized_pnl_pct": realized_pnl_pct, "exit_value": exit_value}


async def check_open_positions(db, definedge) -> dict:
    """For every open position, fetches a live price and closes it if the
    stop, target, or holding horizon has been reached. Safe to call
    repeatedly (already-closed positions are untouched) -- this is what
    the daily cron (and its admin -now twin) calls."""
    open_positions = await db.lattice_positions.find({"status": "open"}, {"_id": 0}).to_list(500)
    if not open_positions:
        return {"checked": 0, "closed": 0, "failed": 0}

    master = None
    checked, closed, failed = 0, 0, 0
    today = datetime.now(timezone.utc).date()
    for p in open_positions:
        checked += 1
        try:
            if master is None:
                master = await definedge._get_all_master()
            price = await live_price(definedge, master, p["symbol"])
            if price is None:
                failed += 1
                continue

            stop_price = p["entry_price"] * (1 - p["stop_loss_pct"] / 100) if p.get("stop_loss_pct") is not None else None
            target_price = p["entry_price"] * (1 + p["target_pct"] / 100) if p.get("target_pct") is not None else None
            days_held = (today - datetime.strptime(p["entry_date"], "%Y-%m-%d").date()).days

            exit_reason = None
            if stop_price is not None and price <= stop_price:
                exit_reason = "stop"
            elif target_price is not None and price >= target_price:
                exit_reason = "target"
            elif days_held >= (p.get("holding_horizon_days") or DEFAULT_MAX_HOLDING_DAYS):
                exit_reason = "horizon"

            if exit_reason:
                await close_position(db, p, price, exit_reason)
                closed += 1
        except Exception as e:  # noqa: BLE001
            logger.warning("The Strata: failed to check position %s (%s): %s", p.get("id"), p.get("symbol"), e)
            failed += 1

    return {"checked": checked, "closed": closed, "failed": failed}


async def get_lessons(db, symbol: str = None, industry: str = None, limit: int = 5) -> list:
    """Recently closed positions for this symbol (preferred) or industry,
    with their realized outcome and the reasoning that led to them -- what
    The Vault actually reflects on. Symbol-specific lessons take priority
    over sector-wide ones; a caller wanting both should call twice."""
    query = {"status": "closed"}
    if symbol:
        query["symbol"] = symbol
    elif industry:
        query["industry"] = industry
    else:
        return []
    return await db.lattice_positions.find(query, {"_id": 0}).sort("exit_date", -1).limit(limit).to_list(limit)


async def get_portfolio_summary(db, definedge) -> dict:
    """Starting capital, live cash, mark-to-market invested value, total
    realized P&L, win rate, and the open/closed position lists -- feeds
    LatticeHome's stats grid."""
    state = await get_or_init_portfolio_state(db)
    open_positions = await db.lattice_positions.find({"status": "open"}, {"_id": 0}).to_list(500)
    closed_positions = await db.lattice_positions.find({"status": "closed"}, {"_id": 0}).sort("exit_date", -1).to_list(1000)

    master = None
    invested_value = 0.0
    for p in open_positions:
        try:
            if master is None:
                master = await definedge._get_all_master()
            price = await live_price(definedge, master, p["symbol"])
        except Exception:  # noqa: BLE001
            price = None
        if price is not None:
            unrealized_pnl_pct = (price - p["entry_price"]) / p["entry_price"] * 100
            current_value = p["capital_allocated"] * (1 + unrealized_pnl_pct / 100)
        else:
            unrealized_pnl_pct, current_value = None, p["capital_allocated"]
        p["current_price"] = price
        p["unrealized_pnl_pct"] = unrealized_pnl_pct
        invested_value += current_value

    total_value = state["cash"] + invested_value
    realized_pnl_rupees = sum((p.get("exit_value") or p["capital_allocated"]) - p["capital_allocated"] for p in closed_positions)
    wins = sum(1 for p in closed_positions if (p.get("realized_pnl_pct") or 0) > 0)

    return {
        "starting_capital": state["starting_capital"],
        "cash": state["cash"],
        "invested_value": invested_value,
        "total_value": total_value,
        "total_return_pct": (total_value - state["starting_capital"]) / state["starting_capital"] * 100,
        "realized_pnl_rupees": realized_pnl_rupees,
        "win_rate": (wins / len(closed_positions)) if closed_positions else None,
        "open_positions": open_positions,
        "closed_positions": closed_positions[:50],
        "total_closed": len(closed_positions),
    }
