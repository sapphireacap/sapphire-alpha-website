"""
The Forge -- Lattice's Trader agent. Turns The Crucible's completed Bull
vs Bear debate, plus the deterministic Clarity Score and Fracture Scan,
into ONE concrete paper-trading proposal: action, position size, stop-
loss, target, holding horizon, reasoning.

Single Groq completion, not a tool-use loop -- same "gather once, reason
once" efficiency The Crucible already uses (stock_terminal_agent.py's
run_debate): The Forge reasons over data already gathered by earlier
stages, it never fetches anything itself.

Stop-loss/target are proposed as PERCENTAGES off entry, not absolute
prices -- The Forge has no live price at proposal time (the real entry
price is only captured when a position actually opens, in
lattice_memory.py), so a percentage is the only honest unit here; an
absolute price would risk the model inventing a plausible-looking but
wrong number.

Structured output via Groq's JSON mode (response_format={"type":
"json_object"}) -- verified live against openai/gpt-oss-120b (the same
model stock_terminal_agent.py already uses) before relying on it: 3/3
clean, valid JSON on a representative prompt. A defensive json.loads
fallback still guards against a malformed response, same discipline
_dispatch_tool already applies to tool-call arguments.
"""
import json
import logging
import os
from datetime import datetime, timezone

from groq import AsyncGroq

from stock_terminal_agent import GROQ_MODEL, _create_completion

logger = logging.getLogger(__name__)

FORGE_MAX_TOKENS = 1200  # openai/gpt-oss-120b is a reasoning model whose
                          # chain-of-thought shares this budget with the
                          # answer -- same headroom stock_terminal_agent.py's
                          # DEBATE_MAX_TOKENS already needed for a similarly
                          # sized system prompt + data context.

VALID_ACTIONS = ("BUY", "SELL", "HOLD")

SYSTEM_PROMPT = (
    "You are The Forge, Lattice's trading agent for Indian (NSE) equities. You read "
    "a completed Bull vs Bear debate, a deterministic Clarity Score, and a deterministic "
    "red-flag scan, and turn them into ONE concrete paper-trading proposal. You do not "
    "gather new data -- only reason over what is given to you. If a position is already "
    "open in this symbol, you may only propose SELL (close it) or HOLD (leave it open) -- "
    "never a second BUY into an existing position.\n\n"
    "Respond with ONLY a single JSON object, no other text, matching this exact schema: "
    '{"action": "BUY"|"SELL"|"HOLD", '
    '"position_size_pct": number (0-100, percent of paper capital to commit; 0 if HOLD), '
    '"stop_loss_pct": number|null (percent below entry for a BUY, or above entry for a '
    'SELL to close against; null if HOLD), '
    '"target_pct": number|null (percent above entry for a BUY, or below entry for a SELL; '
    'null if HOLD), '
    '"holding_horizon_days": integer|null (expected days to hold before re-evaluating; '
    'null if HOLD), '
    '"reasoning": string (2-4 sentences, must cite specific points from the debate, '
    'score, or flags that drove this call)}. '
    "This is a paper/simulated trade for research and education purposes only -- never "
    "real capital, never investment advice."
)


def _fallback_decision(reason: str) -> dict:
    return {
        "action": "HOLD", "position_size_pct": 0, "stop_loss_pct": None,
        "target_pct": None, "holding_horizon_days": None, "reasoning": reason,
    }


async def run_forge(db, symbol: str, debate: dict, scorecard: dict, red_flags: list,
                    open_position: dict | None) -> dict:
    """{"configured": False, "reason": ...} if GROQ_API_KEY is unset or the
    debate itself isn't configured -- same graceful-degradation contract as
    run_agent_analysis/run_debate. Otherwise {"configured": True,
    "decision": {...matching the schema above...}, "generated_at": ...}."""
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        return {"configured": False, "reason": "GROQ_API_KEY is not set."}
    if not debate.get("configured"):
        return {"configured": False, "reason": "Debate data is not available."}

    context = {
        "symbol": symbol,
        "debate_transcript": debate.get("transcript", []),
        "clarity_score": scorecard,
        "red_flags": red_flags,
        "already_open_position": open_position,
    }
    client = AsyncGroq(api_key=api_key)
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": f"Data for {symbol} (JSON):\n{json.dumps(context, default=str)}\n\nRespond with the JSON proposal now."},
    ]
    response = await _create_completion(
        client, model=GROQ_MODEL, max_tokens=FORGE_MAX_TOKENS, messages=messages,
        response_format={"type": "json_object"},
    )
    raw = response.choices[0].message.content or "{}"
    try:
        decision = json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("The Forge: malformed JSON response for %s: %r", symbol, raw)
        decision = _fallback_decision("The Forge returned a malformed response; defaulting to HOLD.")

    if decision.get("action") not in VALID_ACTIONS:
        logger.warning("The Forge: invalid action %r for %s, defaulting to HOLD.", decision.get("action"), symbol)
        decision = _fallback_decision(f"The Forge proposed an invalid action; defaulting to HOLD. Raw reasoning: {decision.get('reasoning', '')}")

    return {"configured": True, "decision": decision, "generated_at": datetime.now(timezone.utc).isoformat()}
