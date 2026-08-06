"""
API for Lattice v2 -- public, no auth, same tier as every other Alpha
Terminal/Research module (this platform's own convention: "nothing here
should be public by accident" applies to what's EXPOSED, not to reading
research output, same posture stock_terminal_routes.py already takes).

POST /run/{symbol} chains the full pipeline in one request: Lumen Agent
-> The Crucible -> The Forge -> The Temper -> The Vault -> The Strata.
Every stage after the debate reuses already-gathered data, no repeated
tool-use loops -- matches the "gather once, reason many times" discipline
The Crucible itself established.
"""
import logging

from fastapi import APIRouter, Depends, HTTPException, Request

import lattice_memory as memory
from lattice_portfolio_manager import run_vault
from lattice_risk import run_temper
from lattice_trader import run_forge
from stock_terminal_agent import run_agent_analysis, run_debate
from stock_terminal_scoring import compute_scorecard, scan_red_flags

logger = logging.getLogger(__name__)

LUMEN_SUMMARY_MAX_CHARS = 2000  # trimmed before logging into lattice_decisions
                                  # -- the full analysis is already cached
                                  # separately in stock_agent_cache, no need
                                  # to duplicate the whole thing here.


def create_lattice_router(db, definedge, get_current_admin, cron_secret: str) -> APIRouter:
    router = APIRouter(prefix="/lattice")

    @router.post("/run/{symbol}")
    async def run_pipeline(symbol: str):
        """Runs the full chain for one symbol and returns every stage's
        output, for LatticeRun's trail view. If the final decision is BUY,
        this opens a real paper position (real live entry price via
        Definedge); if SELL, it closes the existing one. Every run is
        logged to lattice_decisions regardless of outcome."""
        symbol = symbol.strip().upper()
        master_doc = await db.stock_symbol_master.find_one({"symbol": symbol}, {"_id": 0})
        if not master_doc:
            raise HTTPException(status_code=404, detail=f"{symbol} is not in the ingested universe yet.")
        industry = master_doc.get("industry")

        metrics = await db.stock_computed_metrics.find_one({"symbol": symbol}, {"_id": 0})
        fundamentals = await db.stock_fundamentals.find_one({"symbol": symbol}, {"_id": 0})
        shareholding = await db.stock_shareholding.find({"symbol": symbol}, {"_id": 0}).sort("quarter", 1).to_list(12)
        red_flags = scan_red_flags(fundamentals, master_doc, shareholding)
        scorecard = await compute_scorecard(db, symbol, fundamentals, metrics, master_doc, red_flags)

        analysis = await run_agent_analysis(db, symbol)
        debate = await run_debate(db, symbol)

        existing_position = await db.lattice_positions.find_one({"symbol": symbol, "status": "open"}, {"_id": 0})
        all_open_positions = await db.lattice_positions.find({"status": "open"}, {"_id": 0}).to_list(500)
        portfolio_state = await memory.get_or_init_portfolio_state(db)

        forge = await run_forge(db, symbol, debate, scorecard, red_flags, existing_position)
        temper = await run_temper(db, symbol, industry, forge["decision"], all_open_positions, portfolio_state)

        lessons = await memory.get_lessons(db, symbol=symbol, limit=5)
        if not lessons and industry:
            lessons = await memory.get_lessons(db, industry=industry, limit=5)
        vault = await run_vault(db, symbol, forge["decision"], temper["verdict"], lessons)

        lumen_summary = (analysis.get("analysis") or "")[:LUMEN_SUMMARY_MAX_CHARS] if analysis.get("configured") else None
        decision_id = await memory.log_decision(db, symbol, {
            "lumen_analysis_summary": lumen_summary,
            "debate_transcript": debate.get("transcript", []),
            "clarity_score": scorecard,
            "red_flags": red_flags,
            "forge_decision": forge.get("decision"),
            "temper_verdict": temper.get("verdict"),
            "vault_final_decision": vault.get("decision"),
            "resulted_in_position_id": None,
        })

        final_action = vault["decision"].get("final_action")
        position_result = None
        if final_action == "BUY":
            position_result = await memory.open_position(
                db, definedge, symbol, industry, decision_id,
                forge["decision"], vault["decision"].get("final_position_size_pct") or 0,
            )
            if position_result.get("opened"):
                await db.lattice_decisions.update_one(
                    {"id": decision_id}, {"$set": {"resulted_in_position_id": position_result["position"]["id"]}},
                )
        elif final_action == "SELL" and existing_position:
            master = await definedge._get_all_master()
            price = await memory.live_price(definedge, master, symbol)
            if price is not None:
                close_result = await memory.close_position(db, existing_position, price, "manual")
                position_result = {"closed": True, **close_result}
            else:
                position_result = {"closed": False, "reason": f"Could not fetch a live price for {symbol}."}

        return {
            "symbol": symbol, "decision_id": decision_id,
            "lumen_agent": analysis, "crucible": debate,
            "clarity_score": scorecard, "red_flags": red_flags,
            "forge": forge, "temper": temper, "vault": vault,
            "position_result": position_result,
        }

    @router.get("/decisions/{decision_id}")
    async def get_decision(decision_id: str):
        doc = await db.lattice_decisions.find_one({"id": decision_id}, {"_id": 0})
        if not doc:
            raise HTTPException(status_code=404, detail="Decision not found.")
        return doc

    @router.get("/portfolio")
    async def portfolio():
        return await memory.get_portfolio_summary(db, definedge)

    @router.get("/positions")
    async def positions(status: str = None):
        query = {"status": status} if status in ("open", "closed") else {}
        return await db.lattice_positions.find(query, {"_id": 0}).sort("entry_date", -1).to_list(500)

    async def _evaluate() -> dict:
        return await memory.check_open_positions(db, definedge)

    @router.post("/admin/evaluate-positions")
    async def evaluate_positions_cron(request: Request):
        if not cron_secret or request.headers.get("X-Cron-Key") != cron_secret:
            raise HTTPException(status_code=401, detail="Invalid cron key")
        return await _evaluate()

    @router.post("/admin/evaluate-positions-now")
    async def evaluate_positions_admin(admin: dict = Depends(get_current_admin)):
        return await _evaluate()

    return router
