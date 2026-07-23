"""
Sapphire trading journal — Phase 1 data model.

Schema only, no routes/indexes wired up yet (that's Phase 2, which imports
these models and creates the collections/indexes in server.py's on_startup,
following the existing pattern used for users/terminal_stocks).

Conventions carried over from the rest of server.py: string UUID `id`
(uuid4), ISO-string timestamps, `model_config = ConfigDict(extra="ignore")`.

Money/risk fields use Python's `Decimal` here (native Pydantic v2 support).
At the Mongo I/O boundary (Phase 2) these get wrapped as bson.Decimal128 on
write (`Decimal128(str(value))`) and unwrapped via `.to_decimal()` on read —
Motor does not do this conversion automatically.

Index plan (created in Phase 2, listed here as the single source of truth):
  trades:    user_id, entry_time, setup_tag, strategy_family,
             compound (user_id, entry_time), status
  reviews:   compound (user_id, period_start), period_type
  playbooks: user_id
"""
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field


# ---------------------------------------------------------------------------
# trades
# ---------------------------------------------------------------------------
class TradeLeg(BaseModel):
    leg_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    strike: Optional[Decimal] = None          # None for futures/equity legs
    option_type: Optional[str] = None         # "CE" | "PE" | None
    expiry: Optional[str] = None              # ISO date; needed for Greeks/IV time-to-expiry
    side: str                                 # "buy" | "sell"
    qty: int
    entry_price: Decimal
    exit_price: Optional[Decimal] = None
    entry_time: str
    exit_time: Optional[str] = None


class LegGreeks(BaseModel):
    leg_id: str
    delta: Decimal
    theta: Decimal
    vega: Decimal


class AdjustmentLogEntry(BaseModel):
    timestamp: str
    note: str


class Trade(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    user_id: str

    # -- classification ---------------------------------------------------
    instrument: str                            # "NIFTY" | "BANKNIFTY" | ticker
    strategy_family: str                       # e.g. "straddle_sell", "iron_condor", "directional_ce", "directional_pe", "futures"
    direction: str                              # "long" | "short" | "neutral"
    status: str = "open"                        # "open" | "closed" | "partial"

    legs: List[TradeLeg] = []

    # -- timing & risk ------------------------------------------------------
    entry_time: str                              # earliest leg entry, denormalized for fast range queries
    exit_time: Optional[str] = None              # latest leg exit, denormalized
    planned_stop: Optional[Decimal] = None
    actual_stop: Optional[Decimal] = None
    planned_target: Optional[Decimal] = None
    position_size: Decimal
    initial_risk: Decimal
    realized_pnl: Optional[Decimal] = None        # None while open
    r_multiple: Optional[Decimal] = None          # realized_pnl / initial_risk, computed on close
    commissions: Decimal = Decimal("0")
    slippage: Decimal = Decimal("0")
    days_to_expiry_at_entry: Optional[int] = None

    # -- decision context (why, not just what) -----------------------------
    setup_tag: Optional[str] = None               # from users.setup_tags
    thesis: str = ""
    signals_present: List[str] = []               # checked against a Playbook's signals
    planned_vs_actual_entry_deviation: bool = False
    attachment_ids: List[str] = []                 # GridFS file ids

    # -- psychology (structured tags, not just free text) -------------------
    pre_trade_emotion: Optional[str] = None        # from users.emotion_tags
    rule_adherence: Optional[bool] = None
    rule_broken: Optional[str] = None
    post_trade_note: Optional[str] = None
    sleep_hours: Optional[Decimal] = None           # opt-in
    physical_state: Optional[str] = None            # opt-in

    # -- options-specific context --------------------------------------------
    # Computed in Phase 2 via Black-Scholes/IV-solver against Definedge's raw
    # price data — Definedge itself provides no Greeks/IV. india_vix_at_entry
    # is additionally blocked on identifying VIX's Definedge token.
    iv_at_entry: Optional[Decimal] = None
    iv_percentile_at_entry: Optional[Decimal] = None   # only meaningful once we've accumulated our own IV history baseline
    india_vix_at_entry: Optional[Decimal] = None
    greeks_at_entry: List[LegGreeks] = []
    theta_pnl_attributed: Optional[Decimal] = None
    directional_pnl_attributed: Optional[Decimal] = None
    adjustment_log: List[AdjustmentLogEntry] = []
    straddle_regime_at_entry: Optional[str] = None      # pulled from nifty_signal.bias at entry_time

    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


# ---------------------------------------------------------------------------
# reviews
# ---------------------------------------------------------------------------
class ReviewKPIs(BaseModel):
    win_rate: Decimal
    profit_factor: Decimal
    expectancy_r: Decimal
    max_drawdown_r: Decimal
    avg_win_r: Decimal
    avg_loss_r: Decimal
    rule_adherence_rate: Decimal
    trade_count: int
    low_sample_size: bool                       # true when trade_count < 20 — the UI must never show a 3-trade win rate with 200-trade confidence


class Review(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    user_id: str
    period_type: str                             # "weekly" | "monthly"
    period_start: str
    period_end: str
    kpis: ReviewKPIs
    emotion_distribution: dict = {}               # {emotion_tag: count}
    reflection: str = ""
    auto_generated: bool = True
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


# ---------------------------------------------------------------------------
# playbooks
# ---------------------------------------------------------------------------
class Playbook(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    user_id: str
    name: str
    strategy_family: Optional[str] = None          # optional link to a specific strategy
    signals: List[str] = []                        # the checklist trade.signals_present gets checked against
    rules: List[str] = []                          # the trader's own rules, referenced by rule_broken
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


# Defaults seeded onto a user's document at signup (Phase 2 wires this in) —
# documented here since they're part of this schema's design, not floating
# magic values in the signup handler.
DEFAULT_SETUP_TAGS = ["Trend", "Reversal", "Breakout", "Range"]
DEFAULT_EMOTION_TAGS = ["calm", "confident", "anxious", "FOMO", "revenge", "bored"]
