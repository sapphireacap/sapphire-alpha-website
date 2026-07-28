"""
Lumen Agent -- the Stock Research Terminal's AI analyst (Phase 2). A
tool-use loop over the Anthropic Messages API: every tool is either a pure
Mongo read (already-ingested data, no guessing) or a Tavily search for
sector news. The system prompt's citation constraint is the hard guard
against hallucination, matching the original spec verbatim: only reference
values returned by tools, cite the source, say "data unavailable" rather
than estimate.

Graceful degradation, not a hard failure, when ANTHROPIC_API_KEY (or
TAVILY_API_KEY for the one news tool) isn't set -- this repo's established
convention for optional-feature env vars (see module docstring precedent:
GEMINI_API_KEY in ipo_routes.py).

Results are cached per-symbol in stock_agent_cache with a TTL (Mongo
expireAfterSeconds index on `expires_at`, created in server.py) so a page
view doesn't re-run the full tool-use loop (several LLM round-trips) every
time.
"""
import json
import logging
import os
from datetime import datetime, timedelta, timezone

import anthropic
import httpx

logger = logging.getLogger(__name__)

ANTHROPIC_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-5")
CACHE_TTL_HOURS = 6
MAX_TOOL_ROUNDS = 8  # hard cap so a stuck loop can't run away

TAVILY_SEARCH_URL = "https://api.tavily.com/search"
TAVILY_DOMAINS = ["economictimes.com", "moneycontrol.com", "livemint.com", "cnbctv18.com", "reuters.com"]

SYSTEM_PROMPT = (
    "You are Lumen Agent, an equity research assistant for Indian (NSE) stocks. "
    "You may only reference values returned by your tools. Every analytical bullet "
    "must include a source annotation naming the tool it came from. If a value is "
    "unavailable from your tools, state 'data unavailable' -- never estimate, "
    "interpolate, or hallucinate a number. Structure your response as short, "
    "sourced bullet points covering: price/technical context, valuation, growth, "
    "financial health, shareholding trends, and any relevant sector news found. "
    "This is research and education content only, not investment advice."
)

TOOLS = [
    {
        "name": "get_price_history",
        "description": "Historical price data, moving averages, ATH/ATL, and period returns for the stock being analyzed.",
        "input_schema": {
            "type": "object",
            "properties": {"period": {"type": "string", "enum": ["1M", "6M", "1Y", "3Y", "5Y"]}},
            "required": ["period"],
        },
    },
    {
        "name": "get_fundamentals",
        "description": "Valuation ratios, margins, growth rates, and balance-sheet health metrics for the stock being analyzed.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_shareholding",
        "description": "Promoter/FII/DII/public shareholding percentages over recent quarters, including promoter pledge if disclosed.",
        "input_schema": {
            "type": "object",
            "properties": {"quarters": {"type": "integer", "description": "How many recent quarters to return, default 8."}},
        },
    },
    {
        "name": "resolve_peers",
        "description": "Same-industry peer companies for comparison.",
        "input_schema": {
            "type": "object",
            "properties": {"top_n": {"type": "integer", "description": "How many peers to return, default 3."}},
        },
    },
    {
        "name": "get_sector_news",
        "description": "Recent news headlines for the stock's industry/sector from major Indian financial media.",
        "input_schema": {
            "type": "object",
            "properties": {"days": {"type": "integer", "description": "How many days back to search, default 30."}},
        },
    },
]


async def _tool_get_price_history(db, symbol: str, period: str = "1Y") -> dict:
    trading_day_windows = {"1M": 21, "6M": 126, "1Y": 252, "3Y": 756, "5Y": 1260}
    bars = await db.stock_prices_daily.find({"symbol": symbol}, {"_id": 0}).sort("date", 1).to_list(3000)
    window = trading_day_windows.get(period, 252)
    windowed = bars[-window:] if len(bars) > window else bars
    metrics = await db.stock_computed_metrics.find_one({"symbol": symbol}, {"_id": 0}) or {}
    return {
        "period": period,
        "bars_available": len(windowed),
        "first_date": windowed[0]["date"] if windowed else None,
        "last_date": windowed[-1]["date"] if windowed else None,
        "latest_close": windowed[-1]["close"] if windowed else None,
        "dma_50": metrics.get("dma_50"), "dma_200": metrics.get("dma_200"),
        "ath": metrics.get("ath"), "ath_date": metrics.get("ath_date"),
        "atl": metrics.get("atl"), "atl_date": metrics.get("atl_date"),
        "pct_from_ath": metrics.get("pct_from_ath"),
        "returns": {k: metrics.get(k) for k in
                    ("return_1d", "return_1w", "return_1m", "return_3m", "return_6m", "return_1y", "return_5y")},
    }


async def _tool_get_fundamentals(db, symbol: str) -> dict:
    doc = await db.stock_fundamentals.find_one({"symbol": symbol}, {"_id": 0})
    return doc or {"error": "data unavailable -- not yet ingested for this symbol"}


async def _tool_get_shareholding(db, symbol: str, quarters: int = 8) -> dict:
    rows = await db.stock_shareholding.find({"symbol": symbol}, {"_id": 0}).sort("quarter", -1).to_list(quarters)
    if not rows:
        return {"error": "data unavailable -- not yet ingested for this symbol"}
    return {"quarters": list(reversed(rows))}


async def _tool_resolve_peers(db, symbol: str, top_n: int = 3) -> dict:
    sm = await db.stock_symbol_master.find_one({"symbol": symbol}, {"_id": 0})
    if not sm or not sm.get("industry"):
        return {"error": "data unavailable -- symbol or its industry not found"}
    peers = await db.stock_symbol_master.find(
        {"industry": sm["industry"], "symbol": {"$ne": symbol}}, {"_id": 0, "symbol": 1, "company_name": 1}
    ).to_list(50)
    return {
        "industry": sm["industry"],
        "peers": peers[:top_n],
        "note": "Market-cap ranking not available yet (not ingested) -- listed in no particular order.",
    }


async def _tool_get_sector_news(db, symbol: str, days: int = 30) -> dict:
    api_key = os.environ.get("TAVILY_API_KEY")
    if not api_key:
        return {"error": "data unavailable -- sector news search is not configured"}
    sm = await db.stock_symbol_master.find_one({"symbol": symbol}, {"_id": 0, "industry": 1})
    industry = (sm or {}).get("industry") or symbol
    async with httpx.AsyncClient(timeout=20) as c:
        r = await c.post(TAVILY_SEARCH_URL, json={
            "api_key": api_key,
            "query": f"{industry} sector India stock market",
            "search_depth": "advanced",
            "max_results": 8,
            "include_domains": TAVILY_DOMAINS,
        })
    if r.status_code != 200:
        return {"error": f"news search failed (HTTP {r.status_code})"}
    data = r.json()
    return {"results": [
        {"title": x.get("title"), "url": x.get("url"), "snippet": x.get("content"), "published_date": x.get("published_date")}
        for x in data.get("results", [])
    ]}


async def _dispatch_tool(db, symbol: str, name: str, tool_input: dict) -> dict:
    handlers = {
        "get_price_history": lambda: _tool_get_price_history(db, symbol, **tool_input),
        "get_fundamentals": lambda: _tool_get_fundamentals(db, symbol),
        "get_shareholding": lambda: _tool_get_shareholding(db, symbol, **tool_input),
        "resolve_peers": lambda: _tool_resolve_peers(db, symbol, **tool_input),
        "get_sector_news": lambda: _tool_get_sector_news(db, symbol, **tool_input),
    }
    handler = handlers.get(name)
    if handler is None:
        return {"error": f"unknown tool '{name}'"}
    try:
        return await handler()
    except Exception as e:  # noqa: BLE001 -- one bad tool call must not kill the whole analysis
        logger.warning("Lumen Agent: tool %s failed for %s: %s", name, symbol, e)
        return {"error": f"tool call failed: {e}"}


async def run_agent_analysis(db, symbol: str, force: bool = False) -> dict:
    """{"configured": False, "reason": ...} if ANTHROPIC_API_KEY is unset --
    never raises for that case, the caller renders a clear "not configured"
    state instead of a crash. Otherwise returns {"configured": True,
    "cached": bool, "analysis": str, "tool_calls": [...], "generated_at":
    ...} -- tool_calls is the log the Agent Console panel renders
    progressively."""
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return {"configured": False, "reason": "ANTHROPIC_API_KEY is not set."}

    if not force:
        cached = await db.stock_agent_cache.find_one({"symbol": symbol}, {"_id": 0})
        if cached and cached.get("analysis_json"):
            return {**json.loads(cached["analysis_json"]), "cached": True}

    client = anthropic.AsyncAnthropic(api_key=api_key)

    messages = [{"role": "user", "content": f"Analyze {symbol}, an NSE-listed stock. Use your tools to gather real data before writing any conclusions."}]
    tool_calls_log = []

    for _ in range(MAX_TOOL_ROUNDS):
        response = await client.messages.create(
            model=ANTHROPIC_MODEL, max_tokens=2000, system=SYSTEM_PROMPT, tools=TOOLS, messages=messages,
        )
        messages.append({"role": "assistant", "content": response.content})

        if response.stop_reason != "tool_use":
            final_text = "".join(b.text for b in response.content if b.type == "text")
            result = {
                "configured": True, "cached": False, "analysis": final_text,
                "tool_calls": tool_calls_log, "generated_at": datetime.now(timezone.utc).isoformat(),
            }
            expires_at = datetime.now(timezone.utc) + timedelta(hours=CACHE_TTL_HOURS)
            await db.stock_agent_cache.update_one(
                {"symbol": symbol},
                {"$set": {"symbol": symbol, "analysis_json": json.dumps(result), "expires_at": expires_at,
                           "cached_at": datetime.now(timezone.utc).isoformat()}},
                upsert=True,
            )
            return result

        tool_results = []
        for block in response.content:
            if block.type != "tool_use":
                continue
            output = await _dispatch_tool(db, symbol, block.name, block.input)
            tool_calls_log.append({"tool": block.name, "input": block.input, "output": output})
            tool_results.append({"type": "tool_result", "tool_use_id": block.id, "content": json.dumps(output)})
        messages.append({"role": "user", "content": tool_results})

    return {
        "configured": True, "cached": False,
        "analysis": "Analysis stopped after reaching the tool-call limit without a final answer.",
        "tool_calls": tool_calls_log, "generated_at": datetime.now(timezone.utc).isoformat(),
    }


# ---------------------------------------------------------------------------
# The Crucible -- Bull vs. Bear debate mode (Phase 5). Per the spec: "Both
# personas share the same tool manifest and cached tool results -- they
# argue interpretation, not data." Implemented as ONE real data-gathering
# pass (the same pure tool functions above, called directly rather than
# through another tool-use loop) followed by 6 plain completions (3 rounds
# x 2 personas) that only ever see that already-fetched data plus the
# transcript so far -- cheaper and simpler than giving every debate turn
# its own tool-use loop, and just as faithful to "argue interpretation of
# the same facts." The Clarity Score (stock_terminal_scoring.py, already
# computed by the stock bundle route) is the spec's "quantitative
# adjudicator" -- rendered by the frontend alongside the transcript, not
# recomputed here.
# ---------------------------------------------------------------------------
DEBATE_ROUNDS = 3
DEBATE_MAX_TOKENS = 350

PERSONA_SUFFIX = {
    "BULL": (
        "You are arguing the investment BULL case for {symbol}. Present the strongest evidence for why this "
        "stock represents a compelling opportunity, based ONLY on the data provided below. Every claim must "
        "cite where it came from. You must acknowledge weaknesses but frame them constructively. "
        "Keep this turn to 2-3 sentences."
    ),
    "BEAR": (
        "You are arguing the investment BEAR case for {symbol}. Present the strongest evidence for caution or "
        "avoidance, based ONLY on the data provided below. Every claim must cite where it came from. You must "
        "acknowledge strengths but contextualise the risks. Keep this turn to 2-3 sentences."
    ),
}


async def _gather_debate_data(db, symbol: str) -> dict:
    return {
        "price_history": await _tool_get_price_history(db, symbol, "1Y"),
        "fundamentals": await _tool_get_fundamentals(db, symbol),
        "shareholding": await _tool_get_shareholding(db, symbol),
        "peers": await _tool_resolve_peers(db, symbol),
        "sector_news": await _tool_get_sector_news(db, symbol),
    }


async def run_debate(db, symbol: str) -> dict:
    """{"configured": False, "reason": ...} if ANTHROPIC_API_KEY is unset,
    same graceful-degradation contract as run_agent_analysis. Otherwise
    {"configured": True, "transcript": [{"round", "persona", "text"}, ...],
    "generated_at": ...} -- 6 entries (3 rounds x BULL/BEAR)."""
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return {"configured": False, "reason": "ANTHROPIC_API_KEY is not set."}

    data = await _gather_debate_data(db, symbol)
    data_blob = json.dumps(data, default=str)
    client = anthropic.AsyncAnthropic(api_key=api_key)

    transcript = []
    history_text = "(debate has not started yet)"
    for round_no in range(1, DEBATE_ROUNDS + 1):
        for persona in ("BULL", "BEAR"):
            system = (
                f"{SYSTEM_PROMPT}\n\n{PERSONA_SUFFIX[persona].format(symbol=symbol)}\n\n"
                f"Real data for {symbol} (JSON):\n{data_blob}"
            )
            user_content = f"Round {round_no} of {DEBATE_ROUNDS}. Debate so far:\n{history_text}\n\nGive your {persona} argument for this round."
            response = await client.messages.create(
                model=ANTHROPIC_MODEL, max_tokens=DEBATE_MAX_TOKENS, system=system,
                messages=[{"role": "user", "content": user_content}],
            )
            text = "".join(b.text for b in response.content if b.type == "text")
            transcript.append({"round": round_no, "persona": persona, "text": text})
            history_text += f"\n\n{persona} (Round {round_no}): {text}"

    return {"configured": True, "transcript": transcript, "generated_at": datetime.now(timezone.utc).isoformat()}
