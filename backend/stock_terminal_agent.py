"""
Lumen Agent -- the Stock Research Terminal's AI analyst (Phase 2). A
tool-use loop over Groq's chat completions API (OpenAI-compatible tool-
calling shape): every tool is either a pure Mongo read (already-ingested
data, no guessing) or a Tavily search for sector news. The system prompt's
citation constraint is the hard guard against hallucination, matching the
original spec verbatim: only reference values returned by tools, cite the
source, say "data unavailable" rather than estimate.

**Provider note**: the original spec (and this module's first version) was
built against the Anthropic Messages API. Switched to Groq per explicit
instruction once a real GROQ_API_KEY was provided but no real
ANTHROPIC_API_KEY was -- verified live against Groq's real API before
rewriting (tool_calls come back as `message.tool_calls[].function.{name,
arguments}` with `arguments` as a JSON *string*, not the dict Anthropic's
`tool_use` blocks give directly; `finish_reason == "tool_calls"` signals a
tool round instead of Anthropic's `stop_reason == "tool_use"`; the system
prompt is a normal first message in the `messages` list, not a separate
top-level `system` param; tool results go back as individual
`{"role": "tool", "tool_call_id", "content"}` messages, not one combined
`tool_result` content block). If a real Anthropic key is ever added
instead, this file would need converting back -- the pure tool functions
below (`_tool_get_*`) are provider-agnostic and wouldn't need to change.

Graceful degradation, not a hard failure, when GROQ_API_KEY (or
TAVILY_API_KEY for the one news tool) isn't set -- this repo's established
convention for optional-feature env vars (see module docstring precedent:
GEMINI_API_KEY in ipo_routes.py).

Results are cached per-symbol in stock_agent_cache with a TTL (Mongo
expireAfterSeconds index on `expires_at`, created in server.py) so a page
view doesn't re-run the full tool-use loop (several LLM round-trips) every
time.
"""
import asyncio
import json
import logging
import os
from datetime import datetime, timedelta, timezone

import groq
import httpx
from groq import AsyncGroq

logger = logging.getLogger(__name__)

GROQ_MODEL = os.environ.get("GROQ_MODEL", "openai/gpt-oss-120b")
CACHE_TTL_HOURS = 6
MAX_TOOL_ROUNDS = 8  # hard cap so a stuck loop can't run away
MALFORMED_TOOL_CALL_RETRIES = 2  # belt-and-suspenders retry on a malformed
                                   # tool-call generation. Directly measured
                                   # live with our real system prompt + full
                                   # 5-tool manifest: llama-3.3-70b-versatile
                                   # (the original default) only succeeded
                                   # 1/5 attempts here, consistently emitting
                                   # malformed <function=...> pseudo-XML or
                                   # jamming arguments into the tool name;
                                   # openai/gpt-oss-120b (also Groq-hosted)
                                   # was 5/5 in the same test, hence the
                                   # model switch above. This retry stays as
                                   # a safety net, not the primary fix.

TAVILY_SEARCH_URL = "https://api.tavily.com/search"
TAVILY_DOMAINS = ["economictimes.com", "moneycontrol.com", "livemint.com", "cnbctv18.com", "reuters.com"]
SNIPPET_MAX_CHARS = 400  # Tavily's "content" field is often a large raw
                          # scrape of the whole page, not a short snippet --
                          # measured live: 8 untrimmed results made up 91% of
                          # The Crucible's per-turn data blob (~16.5KB of an
                          # ~18KB total) and pushed a single debate run over
                          # Groq's 8000-tokens/minute limit in production
                          # (real 413 rate_limit_exceeded, not hypothetical).
                          # A citation only needs enough text to support the
                          # claim, not the full page.


def _truncate(text, max_chars):
    if not text or len(text) <= max_chars:
        return text
    return text[:max_chars].rsplit(" ", 1)[0] + "…"

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

# Groq/OpenAI-shaped tool manifest: {"type": "function", "function": {name,
# description, parameters}} -- "parameters" here is exactly what Anthropic
# calls "input_schema", same JSON Schema content either way.
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_price_history",
            "description": "Historical price data, moving averages, ATH/ATL, and period returns for the stock being analyzed.",
            "parameters": {
                "type": "object",
                "properties": {"period": {"type": "string", "enum": ["1M", "6M", "1Y", "3Y", "5Y"]}},
                "required": ["period"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_fundamentals",
            "description": "Valuation ratios, margins, growth rates, and balance-sheet health metrics for the stock being analyzed.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_shareholding",
            "description": "Promoter/FII/DII/public shareholding percentages over recent quarters, including promoter pledge if disclosed.",
            "parameters": {
                "type": "object",
                "properties": {"quarters": {"type": "integer", "description": "How many recent quarters to return, default 8."}},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "resolve_peers",
            "description": "Same-industry peer companies for comparison.",
            "parameters": {
                "type": "object",
                "properties": {"top_n": {"type": "integer", "description": "How many peers to return, default 3."}},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_sector_news",
            "description": "Recent news headlines for the stock's industry/sector from major Indian financial media.",
            "parameters": {
                "type": "object",
                "properties": {"days": {"type": "integer", "description": "How many days back to search, default 30."}},
            },
        },
    },
]


async def _tool_get_price_history(db, symbol: str, period: str = "1Y") -> dict:
    trading_day_windows = {"1M": 21, "6M": 126, "1Y": 252, "3Y": 756, "5Y": 1260}
    bars = await db.stock_prices_daily.find({"symbol": symbol}, {"_id": 0}).sort("date", 1).to_list(3000)
    window = trading_day_windows.get(period, 252)
    windowed = bars[-window:] if len(bars) > window else bars
    metrics = await db.stock_computed_metrics.find_one({"symbol": symbol}, {"_id": 0}) or {}

    def _pct_str(v):
        # Stored values ARE already percent (e.g. -0.23 means -0.23%, not
        # -23%). Formatting as an explicit "+x.xx%" string instead of a raw
        # float removes any unit ambiguity for the model -- confirmed live
        # that a raw float here got misread as a fraction needing x100
        # (the debate transcript reported a real -0.23% weekly move as a
        # fabricated-sounding "-22.7% decline", repeated across rounds).
        return f"{v:+.2f}%" if v is not None else None

    return {
        "period": period,
        "bars_available": len(windowed),
        "first_date": windowed[0]["date"] if windowed else None,
        "last_date": windowed[-1]["date"] if windowed else None,
        "latest_close": windowed[-1]["close"] if windowed else None,
        "dma_50": metrics.get("dma_50"), "dma_200": metrics.get("dma_200"),
        "ath": metrics.get("ath"), "ath_date": metrics.get("ath_date"),
        "atl": metrics.get("atl"), "atl_date": metrics.get("atl_date"),
        "pct_from_ath": _pct_str(metrics.get("pct_from_ath")),
        "returns": {k: _pct_str(metrics.get(k)) for k in
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
        {"title": x.get("title"), "url": x.get("url"), "snippet": _truncate(x.get("content"), SNIPPET_MAX_CHARS),
         "published_date": x.get("published_date")}
        for x in data.get("results", [])
    ]}


RATE_LIMIT_RETRIES = 3  # separate from MALFORMED_TOOL_CALL_RETRIES -- a 429
                         # is not a malformed-generation issue, it's Groq's
                         # real 8000-tokens/minute cap on the on_demand tier
                         # (confirmed live, 2026-08-05: Lattice v2's Forge/
                         # Temper/Vault chain called right after a 6-completion
                         # Crucible debate tripped it -- "Used 4196, Requested
                         # 4111" against the 8000 limit). The window is
                         # per-minute and resets on a rolling basis, so a
                         # short wait-and-retry is the right fix, same as the
                         # malformed-tool-call retry below.
RATE_LIMIT_DEFAULT_WAIT = 8.0  # seconds, used when the error gives no
                                # extractable wait time


def _rate_limit_wait_seconds(e: "groq.RateLimitError") -> float:
    """Groq returns a Retry-After header when present; fall back to parsing
    "try again in Xs" out of the error body, then a fixed default -- never
    raises, always returns something retryable."""
    try:
        header = e.response.headers.get("retry-after")
        if header:
            return float(header) + 0.5
    except Exception:  # noqa: BLE001
        pass
    try:
        import re
        m = re.search(r"try again in ([\d.]+)s", str(e))
        if m:
            return float(m.group(1)) + 0.5
    except Exception:  # noqa: BLE001
        pass
    return RATE_LIMIT_DEFAULT_WAIT


async def _create_completion(client: AsyncGroq, **kwargs):
    """client.chat.completions.create() with two independent retry budgets:
    a short retry on a malformed tool-call generation (see
    MALFORMED_TOOL_CALL_RETRIES docstring -- confirmed live to be a
    transient per-request issue, so a plain retry is the right fix) and a
    separate wait-and-retry on Groq's tokens-per-minute rate limit (see
    RATE_LIMIT_RETRIES docstring). Each exception type gets its own budget
    so a run that trips the rate limit once doesn't eat into the malformed-
    call budget, and vice versa."""
    malformed_attempts = 0
    rate_limit_attempts = 0
    while True:
        try:
            return await client.chat.completions.create(**kwargs)
        except groq.RateLimitError as e:
            rate_limit_attempts += 1
            if rate_limit_attempts > RATE_LIMIT_RETRIES:
                raise
            wait = _rate_limit_wait_seconds(e)
            logger.warning("Groq rate limit hit (attempt %d/%d), waiting %.1fs: %s",
                            rate_limit_attempts, RATE_LIMIT_RETRIES, wait, e)
            await asyncio.sleep(wait)
        except groq.BadRequestError as e:
            malformed_attempts += 1
            if malformed_attempts > MALFORMED_TOOL_CALL_RETRIES:
                raise
            logger.warning("Groq call failed (attempt %d/%d), likely a malformed tool-call generation: %s",
                            malformed_attempts, MALFORMED_TOOL_CALL_RETRIES, e)


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
    """{"configured": False, "reason": ...} if GROQ_API_KEY is unset --
    never raises for that case, the caller renders a clear "not configured"
    state instead of a crash. Otherwise returns {"configured": True,
    "cached": bool, "analysis": str, "tool_calls": [...], "generated_at":
    ...} -- tool_calls is the log the Agent Console panel renders
    progressively."""
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        return {"configured": False, "reason": "GROQ_API_KEY is not set."}

    if not force:
        cached = await db.stock_agent_cache.find_one({"symbol": symbol}, {"_id": 0})
        if cached and cached.get("analysis_json"):
            return {**json.loads(cached["analysis_json"]), "cached": True}

    client = AsyncGroq(api_key=api_key)

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": f"Analyze {symbol}, an NSE-listed stock. Use your tools to gather real data before writing any conclusions."},
    ]
    tool_calls_log = []

    for _ in range(MAX_TOOL_ROUNDS):
        response = await _create_completion(client, model=GROQ_MODEL, max_tokens=2000, messages=messages, tools=TOOLS)
        choice = response.choices[0]
        msg = choice.message

        if choice.finish_reason != "tool_calls" or not msg.tool_calls:
            result = {
                "configured": True, "cached": False, "analysis": msg.content or "",
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

        messages.append({"role": "assistant", "content": msg.content, "tool_calls": [tc.model_dump() for tc in msg.tool_calls]})
        for tc in msg.tool_calls:
            try:
                tool_input = json.loads(tc.function.arguments) if tc.function.arguments else {}
            except json.JSONDecodeError:
                tool_input = {}
            output = await _dispatch_tool(db, symbol, tc.function.name, tool_input)
            tool_calls_log.append({"tool": tc.function.name, "input": tool_input, "output": output})
            messages.append({"role": "tool", "tool_call_id": tc.id, "content": json.dumps(output)})

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
# openai/gpt-oss-120b is a reasoning model -- its `message.reasoning` field
# (chain-of-thought, NOT the answer) is billed out of the same max_tokens
# budget as `message.content`. Confirmed live: a bare-minimum unrelated
# prompt already used 70-100 reasoning tokens before answering; with this
# debate's much larger system prompt (persona instructions + the full real
# data-blob context), 350 wasn't enough -- BULL turns came back completely
# empty (all budget spent mid-reasoning) and BEAR turns were cut off
# mid-sentence. 1200 leaves real headroom for both.
DEBATE_MAX_TOKENS = 1200

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
    """{"configured": False, "reason": ...} if GROQ_API_KEY is unset, same
    graceful-degradation contract as run_agent_analysis. Otherwise
    {"configured": True, "transcript": [{"round", "persona", "text"}, ...],
    "generated_at": ...} -- 6 entries (3 rounds x BULL/BEAR)."""
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        return {"configured": False, "reason": "GROQ_API_KEY is not set."}

    data = await _gather_debate_data(db, symbol)
    data_blob = json.dumps(data, default=str)
    client = AsyncGroq(api_key=api_key)

    transcript = []
    history_text = "(debate has not started yet)"
    for round_no in range(1, DEBATE_ROUNDS + 1):
        for persona in ("BULL", "BEAR"):
            system = (
                f"{SYSTEM_PROMPT}\n\n{PERSONA_SUFFIX[persona].format(symbol=symbol)}\n\n"
                f"Real data for {symbol} (JSON):\n{data_blob}"
            )
            user_content = f"Round {round_no} of {DEBATE_ROUNDS}. Debate so far:\n{history_text}\n\nGive your {persona} argument for this round."
            response = await _create_completion(
                client, model=GROQ_MODEL, max_tokens=DEBATE_MAX_TOKENS,
                messages=[{"role": "system", "content": system}, {"role": "user", "content": user_content}],
            )
            text = response.choices[0].message.content or ""
            transcript.append({"round": round_no, "persona": persona, "text": text})
            history_text += f"\n\n{persona} (Round {round_no}): {text}"

    return {"configured": True, "transcript": transcript, "generated_at": datetime.now(timezone.utc).isoformat()}
