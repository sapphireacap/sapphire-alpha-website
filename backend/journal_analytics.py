"""
Trading journal analytics + review generation. Mounted under /journal by
server.py (same factory pattern as journal_routes.py, for the same reason —
avoids a circular import with server.py).

All KPIs are computed in R-multiples, never raw currency, per the brief.
"""
import uuid
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from pymongo import ReturnDocument

from journal_utils import to_mongo, from_mongo

IST = timezone(timedelta(hours=5, minutes=30))
LOW_SAMPLE_THRESHOLD = 20


def _compute_kpis(trades: list) -> dict:
    r_values = [from_mongo(t["r_multiple"]) for t in trades if t.get("r_multiple") is not None]
    trade_count = len(r_values)
    if trade_count == 0:
        return {
            "win_rate": Decimal("0"), "profit_factor": Decimal("0"), "expectancy_r": Decimal("0"),
            "max_drawdown_r": Decimal("0"), "avg_win_r": Decimal("0"), "avg_loss_r": Decimal("0"),
            "rule_adherence_rate": Decimal("0"), "trade_count": 0, "low_sample_size": True,
        }

    wins = [r for r in r_values if r > 0]
    losses = [r for r in r_values if r < 0]
    gross_win = sum(wins) if wins else Decimal("0")
    gross_loss = abs(sum(losses)) if losses else Decimal("0")

    # Max drawdown on the cumulative-R equity curve, ordered by exit_time
    # (id as a stable tie-breaker for same-timestamp exits). This reflects
    # *realized* order, not true capital-at-risk sequencing for concurrent
    # positions — a documented simplification, not full precision.
    ordered = sorted(
        (t for t in trades if t.get("r_multiple") is not None),
        key=lambda t: (t.get("exit_time") or "", t.get("id", "")),
    )
    cum = peak = max_dd = Decimal("0")
    for t in ordered:
        cum += from_mongo(t["r_multiple"])
        peak = max(peak, cum)
        max_dd = max(max_dd, peak - cum)

    adherence_set = [t.get("rule_adherence") for t in trades if t.get("rule_adherence") is not None]

    return {
        "win_rate": Decimal(len(wins)) / Decimal(trade_count),
        "profit_factor": (gross_win / gross_loss) if gross_loss else Decimal("0"),
        "expectancy_r": sum(r_values) / Decimal(trade_count),
        "max_drawdown_r": -max_dd,
        "avg_win_r": (gross_win / Decimal(len(wins))) if wins else Decimal("0"),
        "avg_loss_r": (sum(losses) / Decimal(len(losses))) if losses else Decimal("0"),
        "rule_adherence_rate": (Decimal(sum(1 for a in adherence_set if a)) / Decimal(len(adherence_set))) if adherence_set else Decimal("0"),
        "trade_count": trade_count,
        "low_sample_size": trade_count < LOW_SAMPLE_THRESHOLD,
    }


def _normalize_date(date_str: str) -> str:
    """Canonical YYYY-MM-DD IST calendar date — used as part of the reviews
    upsert key, since a free-form string would risk silent duplicate docs
    for the same period under different timestamp formats."""
    dt = datetime.fromisoformat(date_str)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=IST)
    return dt.astimezone(IST).strftime("%Y-%m-%d")


class ReviewGenerateRequest(BaseModel):
    period_type: str  # "weekly" | "monthly"
    period_start: Optional[str] = None
    period_end: Optional[str] = None


class ReviewUpdateRequest(BaseModel):
    reflection: str


def create_analytics_router(db, get_current_user) -> APIRouter:
    router = APIRouter(prefix="/journal")

    @router.get("/analytics")
    async def get_analytics(
        setup_tag: Optional[str] = None,
        strategy_family: Optional[str] = None,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
        day_of_week: Optional[int] = None,  # 0=Monday .. 6=Sunday
        hour_from: Optional[int] = None,
        hour_to: Optional[int] = None,
        user: dict = Depends(get_current_user),
    ):
        query = {"user_id": user["id"], "status": "closed"}
        if setup_tag:
            query["setup_tag"] = setup_tag
        if strategy_family:
            query["strategy_family"] = strategy_family
        if date_from or date_to:
            rng = {}
            if date_from:
                rng["$gte"] = date_from
            if date_to:
                rng["$lte"] = date_to
            query["entry_time"] = rng

        trades = await db.trades.find(query, {"_id": 0}).to_list(length=10000)

        if day_of_week is not None or hour_from is not None or hour_to is not None:
            filtered = []
            for t in trades:
                try:
                    dt = datetime.fromisoformat(t["entry_time"])
                except Exception:  # noqa: BLE001
                    continue
                if day_of_week is not None and dt.weekday() != day_of_week:
                    continue
                if hour_from is not None and dt.hour < hour_from:
                    continue
                if hour_to is not None and dt.hour > hour_to:
                    continue
                filtered.append(t)
            trades = filtered

        return from_mongo(_compute_kpis(trades))

    @router.post("/reviews/generate")
    async def generate_review(payload: ReviewGenerateRequest, user: dict = Depends(get_current_user)):
        now_ist = datetime.now(IST)
        if payload.period_type == "weekly":
            default_start = now_ist - timedelta(days=now_ist.weekday())
            default_end = default_start + timedelta(days=6)
        elif payload.period_type == "monthly":
            default_start = now_ist.replace(day=1)
            next_month = (default_start.replace(day=28) + timedelta(days=4)).replace(day=1)
            default_end = next_month - timedelta(days=1)
        else:
            raise HTTPException(status_code=400, detail="period_type must be 'weekly' or 'monthly'.")

        period_start = _normalize_date(payload.period_start) if payload.period_start else default_start.strftime("%Y-%m-%d")
        period_end = _normalize_date(payload.period_end) if payload.period_end else default_end.strftime("%Y-%m-%d")

        query = {
            "user_id": user["id"],
            "status": "closed",
            "entry_time": {"$gte": period_start, "$lte": f"{period_end}T23:59:59"},
        }
        trades = await db.trades.find(query, {"_id": 0}).to_list(length=10000)
        kpis = _compute_kpis(trades)

        emotion_dist = {}
        for t in trades:
            tag = t.get("pre_trade_emotion")
            if tag:
                emotion_dist[tag] = emotion_dist.get(tag, 0) + 1

        now = datetime.now(timezone.utc).isoformat()
        review_doc = {
            "user_id": user["id"],
            "period_type": payload.period_type,
            "period_start": period_start,
            "period_end": period_end,
            "kpis": to_mongo(kpis),
            "emotion_distribution": emotion_dist,
            "auto_generated": True,
            "updated_at": now,
        }

        existing = await db.reviews.find_one({"user_id": user["id"], "period_type": payload.period_type, "period_start": period_start})
        if existing:
            await db.reviews.update_one({"id": existing["id"]}, {"$set": review_doc})
            review_doc["id"] = existing["id"]
            review_doc["reflection"] = existing.get("reflection", "")
            review_doc["created_at"] = existing.get("created_at", now)
        else:
            review_doc["id"] = str(uuid.uuid4())
            review_doc["reflection"] = ""
            review_doc["created_at"] = now
            await db.reviews.insert_one(review_doc)
            review_doc.pop("_id", None)  # insert_one mutates the dict in-place with a non-JSON-serializable ObjectId

        return from_mongo(review_doc)

    @router.get("/reviews")
    async def list_reviews(period_type: Optional[str] = None, user: dict = Depends(get_current_user)):
        query = {"user_id": user["id"]}
        if period_type:
            query["period_type"] = period_type
        cursor = db.reviews.find(query, {"_id": 0}).sort("period_start", -1)
        reviews = [from_mongo(r) for r in await cursor.to_list(length=200)]
        return {"reviews": reviews}

    @router.put("/reviews/{review_id}")
    async def update_review(review_id: str, payload: ReviewUpdateRequest, user: dict = Depends(get_current_user)):
        result = await db.reviews.find_one_and_update(
            {"id": review_id, "user_id": user["id"]},
            {"$set": {"reflection": payload.reflection, "updated_at": datetime.now(timezone.utc).isoformat()}},
            return_document=ReturnDocument.AFTER,
            projection={"_id": 0},
        )
        if result is None:
            raise HTTPException(status_code=404, detail="Review not found.")
        return from_mongo(result)

    return router
