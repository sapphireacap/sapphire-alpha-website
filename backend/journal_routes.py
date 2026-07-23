"""
Trading journal CRUD — trades. Mounted under /journal by server.py.

Built as a factory (`create_journal_router`) rather than importing `db`/
`get_current_user`/etc. from server.py directly, since server.py needs to
import *this* module to mount the router — a direct cross-import would be
circular. server.py calls the factory with its own already-constructed
globals once they're all defined.
"""
import asyncio
import logging
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Depends, Request
from pydantic import BaseModel
from pymongo import ReturnDocument

from journal_models import Trade, TradeLeg
from journal_utils import to_mongo, from_mongo
from pricing import implied_vol, greeks as bs_greeks, RISK_FREE_RATE

logger = logging.getLogger(__name__)
IST = timezone(timedelta(hours=5, minutes=30))


class TradeCreateRequest(BaseModel):
    instrument: str
    strategy_family: str
    direction: str
    legs: List[TradeLeg] = []
    entry_time: str
    planned_stop: Optional[Decimal] = None
    actual_stop: Optional[Decimal] = None
    planned_target: Optional[Decimal] = None
    position_size: Decimal
    initial_risk: Decimal
    commissions: Decimal = Decimal("0")
    slippage: Decimal = Decimal("0")
    setup_tag: Optional[str] = None
    thesis: str = ""
    signals_present: List[str] = []
    pre_trade_emotion: Optional[str] = None
    rule_adherence: Optional[bool] = None
    rule_broken: Optional[str] = None
    post_trade_note: Optional[str] = None
    sleep_hours: Optional[Decimal] = None
    physical_state: Optional[str] = None


class TradeUpdateRequest(BaseModel):
    status: Optional[str] = None
    legs: Optional[List[TradeLeg]] = None
    exit_time: Optional[str] = None
    planned_stop: Optional[Decimal] = None
    actual_stop: Optional[Decimal] = None
    planned_target: Optional[Decimal] = None
    position_size: Optional[Decimal] = None
    initial_risk: Optional[Decimal] = None
    commissions: Optional[Decimal] = None
    slippage: Optional[Decimal] = None
    setup_tag: Optional[str] = None
    thesis: Optional[str] = None
    signals_present: Optional[List[str]] = None
    planned_vs_actual_entry_deviation: Optional[bool] = None
    pre_trade_emotion: Optional[str] = None
    rule_adherence: Optional[bool] = None
    rule_broken: Optional[str] = None
    post_trade_note: Optional[str] = None
    sleep_hours: Optional[Decimal] = None
    physical_state: Optional[str] = None
    adjustment_log_append: Optional[str] = None  # convenience: append one note rather than resend the whole log


def _to_utc_iso(ts: str) -> str:
    """Normalize an arbitrary-offset ISO timestamp to UTC ISO — needed before
    comparing against nifty_signal_history.updated_at (always stored in UTC),
    since raw string comparison across differing timezone offsets does not
    sort chronologically."""
    try:
        dt = datetime.fromisoformat(ts)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=IST)
        return dt.astimezone(timezone.utc).isoformat()
    except Exception:  # noqa: BLE001
        return ts


async def _enrich_trade(db, definedge, trade_id: str, user_id: str, legs: list, entry_time: str):
    """Background best-effort enrichment — runs after the trade is already
    saved and the API has responded. Never raises; any failure just leaves
    the auto-fill fields null, same as if Definedge weren't connected."""
    try:
        if not definedge.configured():
            return
        conn = await definedge.status()
        if not conn.get("connected"):
            return

        entry_utc = _to_utc_iso(entry_time)
        spot_result, vix_value, history_doc = await asyncio.gather(
            definedge.spot_quote(),
            definedge.vix_quote(),
            db.nifty_signal_history.find_one({"updated_at": {"$lte": entry_utc}}, sort=[("updated_at", -1)]),
            return_exceptions=True,
        )

        updates = {}

        if isinstance(vix_value, (int, float)):
            updates["india_vix_at_entry"] = Decimal(str(round(vix_value, 2)))

        regime = history_doc.get("bias") if isinstance(history_doc, dict) else None
        if regime is None:
            current = await db.nifty_signal.find_one({"id": "current"})
            if current:
                regime = current.get("bias")
        if regime:
            updates["straddle_regime_at_entry"] = regime

        spot = None
        if isinstance(spot_result, dict):
            try:
                spot = float(str(spot_result.get("spot", "")).replace(",", ""))
            except (ValueError, AttributeError):
                spot = None

        if spot is not None and legs:
            ivs, greeks_list = [], []
            for leg in legs:
                strike, option_type = leg.get("strike"), leg.get("option_type")
                expiry, entry_price = leg.get("expiry"), leg.get("entry_price")
                if not (strike and option_type and expiry and entry_price):
                    continue
                try:
                    expiry_dt = datetime.fromisoformat(expiry)
                    if expiry_dt.tzinfo is None:
                        expiry_dt = expiry_dt.replace(hour=15, minute=30, tzinfo=IST)  # NSE close
                    T = (expiry_dt - datetime.now(IST)).total_seconds() / (365 * 24 * 3600)
                except Exception:  # noqa: BLE001
                    continue
                iv = implied_vol(float(entry_price), spot, float(strike), T, RISK_FREE_RATE, option_type)
                if iv is None:
                    continue
                ivs.append(iv)
                g = bs_greeks(spot, float(strike), T, RISK_FREE_RATE, iv, option_type)
                if g:
                    greeks_list.append({
                        "leg_id": leg.get("leg_id"),
                        "delta": Decimal(str(round(g["delta"], 4))),
                        "theta": Decimal(str(round(g["theta"], 4))),
                        "vega": Decimal(str(round(g["vega"], 4))),
                    })
            if ivs:
                updates["iv_at_entry"] = Decimal(str(round(sum(ivs) / len(ivs), 4)))
            if greeks_list:
                updates["greeks_at_entry"] = greeks_list

        if updates:
            updates["updated_at"] = datetime.now(timezone.utc).isoformat()
            await db.trades.update_one({"id": trade_id, "user_id": user_id}, {"$set": to_mongo(updates)})
    except Exception as e:  # noqa: BLE001 — must never surface to the client, trade already saved
        logger.warning(f"Trade enrichment failed for {trade_id}: {e}")


def create_journal_router(db, get_current_user, log_audit_event, definedge) -> APIRouter:
    router = APIRouter(prefix="/journal")

    @router.post("/trades", status_code=201)
    async def create_trade(payload: TradeCreateRequest, request: Request, user: dict = Depends(get_current_user)):
        trade = Trade(user_id=user["id"], **payload.model_dump())

        # days_to_expiry_at_entry, from the earliest leg with an expiry set
        expiries = [leg.expiry for leg in payload.legs if leg.expiry]
        if expiries:
            try:
                entry_dt = datetime.fromisoformat(payload.entry_time)
                nearest_expiry = min(datetime.fromisoformat(e) for e in expiries)
                trade.days_to_expiry_at_entry = (nearest_expiry.date() - entry_dt.date()).days
            except Exception:  # noqa: BLE001
                pass

        doc = trade.model_dump()
        await db.trades.insert_one(to_mongo(doc))
        await log_audit_event(request, user["id"], "journal_entry_created", trade_id=doc["id"])

        legs_for_enrichment = [leg.model_dump() for leg in payload.legs]
        asyncio.create_task(_enrich_trade(db, definedge, doc["id"], user["id"], legs_for_enrichment, payload.entry_time))

        return from_mongo(doc)

    @router.get("/trades")
    async def list_trades(
        setup_tag: Optional[str] = None,
        strategy_family: Optional[str] = None,
        status: Optional[str] = None,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
        user: dict = Depends(get_current_user),
    ):
        query = {"user_id": user["id"]}
        if setup_tag:
            query["setup_tag"] = setup_tag
        if strategy_family:
            query["strategy_family"] = strategy_family
        if status:
            query["status"] = status
        if date_from or date_to:
            rng = {}
            if date_from:
                rng["$gte"] = date_from
            if date_to:
                rng["$lte"] = date_to
            query["entry_time"] = rng

        capped_limit = min(max(limit, 1), 200)
        cursor = db.trades.find(query, {"_id": 0}).sort("entry_time", -1).skip(max(offset, 0)).limit(capped_limit)
        trades = [from_mongo(t) for t in await cursor.to_list(length=capped_limit)]
        total = await db.trades.count_documents(query)
        return {"trades": trades, "total": total, "limit": capped_limit, "offset": offset}

    @router.get("/trades/{trade_id}")
    async def get_trade(trade_id: str, user: dict = Depends(get_current_user)):
        trade = await db.trades.find_one({"id": trade_id, "user_id": user["id"]}, {"_id": 0})
        if trade is None:
            raise HTTPException(status_code=404, detail="Trade not found.")
        return from_mongo(trade)

    @router.put("/trades/{trade_id}")
    async def update_trade(trade_id: str, payload: TradeUpdateRequest, request: Request, user: dict = Depends(get_current_user)):
        updates = payload.model_dump(exclude_unset=True, exclude={"adjustment_log_append"})

        if payload.adjustment_log_append is not None:
            await db.trades.update_one(
                {"id": trade_id, "user_id": user["id"]},
                {"$push": {"adjustment_log": {"timestamp": datetime.now(timezone.utc).isoformat(), "note": payload.adjustment_log_append}}},
            )

        # On close, compute realized_pnl / r_multiple from the legs (client
        # must send the updated legs with exit_price/exit_time populated).
        if updates.get("status") == "closed":
            legs = updates.get("legs")
            if legs:
                pnl = Decimal("0")
                for leg in legs:
                    exit_price = leg.get("exit_price")
                    if exit_price is None:
                        continue
                    entry_price, qty = leg["entry_price"], leg["qty"]
                    leg_pnl = (exit_price - entry_price) if leg["side"] == "buy" else (entry_price - exit_price)
                    pnl += leg_pnl * qty
                updates["realized_pnl"] = pnl
                existing = await db.trades.find_one({"id": trade_id, "user_id": user["id"]}, {"initial_risk": 1})
                if existing and existing.get("initial_risk"):
                    initial_risk = from_mongo(existing["initial_risk"])
                    if initial_risk:
                        updates["r_multiple"] = pnl / initial_risk

        if not updates:
            raise HTTPException(status_code=400, detail="No fields to update.")

        updates["updated_at"] = datetime.now(timezone.utc).isoformat()
        result = await db.trades.find_one_and_update(
            {"id": trade_id, "user_id": user["id"]},
            {"$set": to_mongo(updates)},
            return_document=ReturnDocument.AFTER,
            projection={"_id": 0},
        )
        if result is None:
            raise HTTPException(status_code=404, detail="Trade not found.")
        await log_audit_event(request, user["id"], "journal_entry_updated", trade_id=trade_id)
        return from_mongo(result)

    @router.delete("/trades/{trade_id}")
    async def delete_trade(trade_id: str, request: Request, user: dict = Depends(get_current_user)):
        result = await db.trades.delete_one({"id": trade_id, "user_id": user["id"]})
        if result.deleted_count == 0:
            raise HTTPException(status_code=404, detail="Trade not found.")
        await log_audit_event(request, user["id"], "journal_entry_deleted", trade_id=trade_id)
        return {"status": "deleted"}

    return router
