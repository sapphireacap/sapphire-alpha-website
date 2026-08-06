"""
The Temper -- Lattice's Risk Manager agent. Stress-tests The Forge's
proposal against portfolio-level risk before it's allowed through.

Combines deterministic caps with LLM judgment the same way Clarity Score
does (stock_terminal_scoring.py): hard numeric limits (position size,
sector concentration, available cash) are never left to the model's
discretion -- they're plain Python, applied first. The LLM is only asked
a genuinely judgment-dependent question (does this new position crowd
too heavily into an existing thesis / correlated bet already open), and
only when there's actually something to weigh -- a SELL (reduces risk)
or HOLD (no new risk) is approved deterministically with no LLM call at
all, matching the "reason once, don't reason without cause" discipline
The Crucible and The Forge already follow.
"""
import json
import logging
import os
from datetime import datetime, timezone

from groq import AsyncGroq

from stock_terminal_agent import GROQ_MODEL, _create_completion

logger = logging.getLogger(__name__)

TEMPER_MAX_TOKENS = 800

MAX_POSITION_PCT = 20   # no single symbol above 20% of paper capital
MAX_SECTOR_PCT = 40     # no single industry above 40% of paper capital

SYSTEM_PROMPT = (
    "You are The Temper, Lattice's risk management agent for a paper (simulated) "
    "equity portfolio. A proposed BUY has already passed hard position-size and "
    "sector-concentration limits -- your job is the judgment call those limits "
    "can't make: does this new position crowd too heavily into an existing open "
    "thesis (same sector, same directional bet, correlated names)? You may only "
    "REDUCE the proposed size, never increase it.\n\n"
    "Respond with ONLY a single JSON object, no other text: "
    '{"verdict": "APPROVE"|"ADJUST"|"REJECT", '
    '"adjusted_position_size_pct": number|null (only set if verdict is ADJUST, must '
    "be less than the proposed size), "
    '"reasoning": string (1-3 sentences)}.'
)


def _deny(reasoning: str) -> dict:
    return {"verdict": "REJECT", "adjusted_position_size_pct": None, "reasoning": reasoning}


def _approve(reasoning: str, adjusted_pct: float | None = None) -> dict:
    return {
        "verdict": "ADJUST" if adjusted_pct is not None else "APPROVE",
        "adjusted_position_size_pct": adjusted_pct,
        "reasoning": reasoning,
    }


async def run_temper(db, symbol: str, industry: str | None, forge_decision: dict,
                     open_positions: list, portfolio_state: dict) -> dict:
    """{"configured": True, "verdict": {...}, "generated_at": ...} always --
    unlike The Forge/Crucible, deterministic checks mean this never needs a
    "not configured" state for a HOLD/SELL/rejected-on-hard-limits BUY (no
    Groq call made at all in those cases); a genuinely LLM-reviewed ADJUST/
    APPROVE still degrades to a deterministic APPROVE if GROQ_API_KEY is
    unset, since the hard caps alone are still a real, valid risk check."""
    action = forge_decision.get("action", "HOLD")
    proposed_pct = forge_decision.get("position_size_pct") or 0

    if action != "BUY":
        # Closing or not opening a position never increases risk -- nothing
        # for a risk reviewer to weigh.
        return {"configured": True, "verdict": _approve(f"{action} does not add portfolio risk; no review needed."),
                "generated_at": datetime.now(timezone.utc).isoformat()}

    # --- Hard deterministic caps, applied before any LLM call -----------
    existing_pct = sum(p.get("position_size_pct") or 0 for p in open_positions)
    sector_pct = sum(p.get("position_size_pct") or 0 for p in open_positions if p.get("industry") == industry) if industry else 0
    cash_pct_available = 100 - existing_pct

    capped_pct = min(proposed_pct, MAX_POSITION_PCT, cash_pct_available)
    if industry and sector_pct + capped_pct > MAX_SECTOR_PCT:
        capped_pct = max(0, MAX_SECTOR_PCT - sector_pct)

    if capped_pct <= 0:
        reason = (
            f"No room to open this position: existing exposure is already {existing_pct:.1f}% of paper capital"
            + (f", sector ({industry}) exposure is {sector_pct:.1f}% (cap {MAX_SECTOR_PCT}%)." if industry else ".")
        )
        return {"configured": True, "verdict": _deny(reason), "generated_at": datetime.now(timezone.utc).isoformat()}

    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        # Hard caps alone are a real, valid risk check -- degrade to a
        # deterministic approval at the capped size rather than blocking
        # the whole pipeline on a missing key for the qualitative half only.
        verdict = _approve("GROQ_API_KEY not set -- approved at the deterministic cap, no qualitative review performed.", capped_pct) \
            if capped_pct < proposed_pct else _approve("Deterministic caps satisfied; GROQ_API_KEY not set, no qualitative review performed.")
        return {"configured": True, "verdict": verdict, "generated_at": datetime.now(timezone.utc).isoformat()}

    context = {
        "symbol": symbol, "industry": industry,
        "proposed_position_size_pct": capped_pct,
        "forge_reasoning": forge_decision.get("reasoning"),
        "open_positions": open_positions,
        "portfolio_state": portfolio_state,
        "existing_total_exposure_pct": existing_pct,
        "existing_sector_exposure_pct": sector_pct,
    }
    client = AsyncGroq(api_key=api_key)
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": f"Data (JSON):\n{json.dumps(context, default=str)}\n\nRespond with the JSON verdict now."},
    ]
    response = await _create_completion(
        client, model=GROQ_MODEL, max_tokens=TEMPER_MAX_TOKENS, messages=messages,
        response_format={"type": "json_object"},
    )
    raw = response.choices[0].message.content or "{}"
    try:
        verdict = json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("The Temper: malformed JSON response for %s: %r", symbol, raw)
        verdict = _approve(f"The Temper returned a malformed response; approved at the deterministic cap ({capped_pct:.1f}%).", capped_pct)

    if verdict.get("verdict") not in ("APPROVE", "ADJUST", "REJECT"):
        verdict = _approve(f"Invalid verdict from The Temper; approved at the deterministic cap ({capped_pct:.1f}%).", capped_pct)
    # Never trust the model to raise the size above the deterministic cap.
    adj = verdict.get("adjusted_position_size_pct")
    if adj is not None and adj > capped_pct:
        verdict["adjusted_position_size_pct"] = capped_pct

    return {"configured": True, "verdict": verdict, "generated_at": datetime.now(timezone.utc).isoformat()}
