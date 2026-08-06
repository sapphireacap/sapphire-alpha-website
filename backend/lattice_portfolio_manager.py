"""
The Vault -- Lattice's Portfolio Manager agent. Final authority: reads
The Forge's proposal, The Temper's risk verdict, and The Strata's record
of how similar past decisions actually played out, and produces the
FINAL decision. This is the reflection/memory mechanism TradingAgents
describes -- past realized outcomes are read here, before the decision,
not just logged after it.

Deliberately PURE, like run_forge/run_temper -- no persistence, no I/O
beyond the Groq call. Opening/closing an actual paper position from this
decision is the caller's job (lattice_memory.py's open_position/
close_position, invoked from lattice_routes.py), the same separation
pnf_chart.build_chart and relative_strength_matrix.py already keep
between pure computation and the I/O layer around it.

Only genuinely calls Groq when there's something to weigh: a proposal
The Temper already REJECTed, or a Forge HOLD, is finalized
deterministically with no LLM call -- there's nothing left to decide. A
SELL is approved directly (closing an already-risk-checked position
needs no new judgment). Only a Temper-approved/adjusted BUY reaches the
LLM, since that's the one case where a past lesson (e.g. "the last two
paper trades in this sector on a similar bullish thesis both stopped
out") could still argue against a proposal that technically cleared risk
limits.
"""
import json
import logging
import os
from datetime import datetime, timezone

from groq import AsyncGroq

from stock_terminal_agent import GROQ_MODEL, _create_completion

logger = logging.getLogger(__name__)

VAULT_MAX_TOKENS = 1000

SYSTEM_PROMPT = (
    "You are The Vault, Lattice's portfolio manager agent for a paper (simulated) "
    "equity portfolio. A proposed BUY has already cleared risk-management limits -- "
    "your job is the final call, informed by how similar past decisions on this "
    "symbol or sector actually played out. You may approve, reduce further, or "
    "reject entirely based on the lessons provided. If there are no relevant past "
    "lessons, approve at the risk-approved size unless the debate/reasoning itself "
    "gives you a genuine reason not to.\n\n"
    "Respond with ONLY a single JSON object, no other text: "
    '{"final_action": "BUY"|"REJECTED", '
    '"final_position_size_pct": number|null (only if final_action is BUY), '
    '"reasoning": string (1-3 sentences, cite any lesson that influenced this call)}.'
)


def _finalize(action: str, size_pct: float | None, reasoning: str) -> dict:
    return {"final_action": action, "final_position_size_pct": size_pct, "reasoning": reasoning}


async def run_vault(db, symbol: str, forge_decision: dict, temper_verdict: dict, lessons: list) -> dict:
    """Always returns {"configured": True, "decision": {...}, "generated_at":
    ...} -- deterministic paths (REJECT-from-Temper, Forge HOLD, SELL) never
    need a "not configured" state since no Groq call happens; only the
    genuinely-reviewed BUY path can degrade to a deterministic approval if
    GROQ_API_KEY is unset, same pattern as The Temper."""
    action = forge_decision.get("action", "HOLD")
    verdict = temper_verdict.get("verdict", "REJECT")

    if action == "SELL":
        decision = _finalize("SELL", None, "Closing an already-open, previously risk-checked position -- approved directly.")
        return {"configured": True, "decision": decision, "generated_at": datetime.now(timezone.utc).isoformat()}

    if action == "HOLD" or verdict == "REJECT":
        reasoning = temper_verdict.get("reasoning") if verdict == "REJECT" else "The Forge proposed no action."
        decision = _finalize("REJECTED", None, reasoning or "No action proposed.")
        return {"configured": True, "decision": decision, "generated_at": datetime.now(timezone.utc).isoformat()}

    # action == "BUY" and verdict in ("APPROVE", "ADJUST") -- the one path
    # that genuinely needs judgment over real memory.
    approved_pct = temper_verdict.get("adjusted_position_size_pct") or forge_decision.get("position_size_pct") or 0

    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        decision = _finalize("BUY", approved_pct, "GROQ_API_KEY not set -- approved at the risk-approved size, no reflection review performed.")
        return {"configured": True, "decision": decision, "generated_at": datetime.now(timezone.utc).isoformat()}

    context = {
        "symbol": symbol,
        "forge_decision": forge_decision,
        "temper_verdict": temper_verdict,
        "approved_position_size_pct": approved_pct,
        "past_lessons": lessons,
    }
    client = AsyncGroq(api_key=api_key)
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": f"Data (JSON):\n{json.dumps(context, default=str)}\n\nRespond with the JSON decision now."},
    ]
    response = await _create_completion(
        client, model=GROQ_MODEL, max_tokens=VAULT_MAX_TOKENS, messages=messages,
        response_format={"type": "json_object"},
    )
    raw = response.choices[0].message.content or "{}"
    try:
        decision = json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("The Vault: malformed JSON response for %s: %r", symbol, raw)
        decision = _finalize("BUY", approved_pct, "The Vault returned a malformed response; approved at the risk-approved size.")

    if decision.get("final_action") not in ("BUY", "REJECTED"):
        decision = _finalize("BUY", approved_pct, "Invalid final_action from The Vault; approved at the risk-approved size.")
    # Never trust the model to raise the size above what The Temper approved.
    size = decision.get("final_position_size_pct")
    if decision.get("final_action") == "BUY" and (size is None or size > approved_pct):
        decision["final_position_size_pct"] = approved_pct

    return {"configured": True, "decision": decision, "generated_at": datetime.now(timezone.utc).isoformat()}
