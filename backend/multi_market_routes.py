"""Multi-market module routes — one router serving every module for every
non-India market segment.

Route shape is /markets/{market}/{module}, so adding a market later is an
entry in market_adapters.ADAPTERS and nothing here changes at all.

Caching follows the pattern the US and India routes already established,
and it is not optional on this backend: the Render instance is on the free
512MB plan and has OOM-crashed under load before (2026-08-11). Anything
that walks a whole universe -- Breadth, Momentum Investing, Momentum
Leaders, Sharpe -- is therefore computed by a cron/admin-triggered
BackgroundTask and served from Mongo, never computed inside a user
request. Per-symbol modules (Exitline, EWMA, Gamma Pulse, Index Vector,
Peter Tingle) are cheap enough to compute live, exactly as their India and
US counterparts already do.

Every route returns the same {available: false, reason} shape for a module
that genuinely cannot run in a given market, rather than a 404 or an empty
success -- the UI renders that reason on the Coming Soon card, so a user
is told what is actually missing.
"""
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request

import multi_market_engine as eng
from market_adapters import AdapterError, get_adapter

logger = logging.getLogger(__name__)

RANKING_CACHE = "market_module_rankings"

# Every module the Alpha Terminal directory shows, by slug, with the
# per-market runner. `None` means "no formula exists in this codebase"
# (see multi_market_engine.NO_FORMULA) rather than "not built yet".
UNIVERSE_MODULES = {
    "momentum-investing": eng.momentum_investing,
    "momentum-engine": eng.momentum_leaders,
    "sharpe-dashboard": eng.sharpe,
}


def _adapter_or_404(market: str):
    try:
        return get_adapter(market)
    except AdapterError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


def _blocked(adapter, slug: str) -> dict | None:
    """The reason a module can't run here, if any -- either no formula
    exists at all, or this market lacks the instrument it needs."""
    if slug in eng.NO_FORMULA:
        return {"available": False, "module": slug, "reason": eng.NO_FORMULA[slug]}
    reason = adapter.unavailable.get(slug)
    if reason:
        return {"available": False, "module": slug, "reason": reason}
    return None


def create_multi_market_router(db, get_current_admin, cron_secret: str) -> APIRouter:
    router = APIRouter(prefix="/markets", tags=["markets"])

    def _require_cron(request: Request):
        if not cron_secret or request.headers.get("X-Cron-Key") != cron_secret:
            raise HTTPException(status_code=401, detail="Invalid cron key")

    # ---------------------------------------------------------------- meta --
    @router.get("/{market}/modules")
    async def module_availability(market: str):
        """Per-market availability for every module slug the directory
        renders. The frontend uses this to decide which cards open and
        what a locked card's tooltip says."""
        adapter = _adapter_or_404(market)
        slugs = ["index-vector", "exitline", "peter-tingle", "relative-strength", "breadth-indicator",
                 "options-trend-scanner", "swing-picks", "momentum-investing", "momentum-engine",
                 "sharpe-dashboard", "ewma-scanner", "breakout-candidates"]
        out = {}
        for slug in slugs:
            blocked = _blocked(adapter, slug)
            out[slug] = blocked or {"available": True, "module": slug}
        return {"market": adapter.market_id, "label": adapter.label,
                "supports_options": adapter.supports_options,
                "groups": adapter.groups(), "modules": out}

    @router.get("/{market}/universe")
    async def universe(market: str):
        adapter = _adapter_or_404(market)
        rows = await adapter.universe(db)
        return {"market": adapter.market_id, "total": len(rows), "rows": rows}

    @router.get("/{market}/search")
    async def search(market: str, q: str = "", limit: int = 25):
        """`company_name` is aliased onto `label` because the shared
        Exitline symbol picker reads that field — same contract as the US
        search route it was written against."""
        adapter = _adapter_or_404(market)
        rows = await adapter.search(db, q, limit)
        return [{**r, "company_name": r.get("company_name") or r.get("label")} for r in rows]

    # ------------------------------------------------------------ Exitline --
    @router.get("/{market}/exitline")
    async def exitline(market: str, symbol: str, interval: int = 5):
        adapter = _adapter_or_404(market)
        try:
            return await eng.exitline(adapter, db, symbol, interval)
        except AdapterError as e:
            raise HTTPException(status_code=502, detail=str(e)) from e

    # ------------------------------------------------------------- Breadth --
    @router.get("/{market}/breadth/groups")
    async def breadth_groups(market: str):
        """{key, label} pairs — the exact shape the shared BreadthTool
        component already expects from the India/US breadth endpoints, so
        that one component serves every market with no branching in it."""
        adapter = _adapter_or_404(market)
        return {"groups": [{"key": g, "label": g} for g in adapter.groups()]}

    @router.get("/{market}/breadth")
    async def breadth(market: str, group: str = None):
        adapter = _adapter_or_404(market)
        group = group or adapter.groups()[0]
        return await eng.breadth_read(adapter, db, group)

    @router.post("/{market}/breadth/admin/refresh")
    async def breadth_refresh_cron(market: str, request: Request, background_tasks: BackgroundTasks,
                                    group: str = None):
        _require_cron(request)
        adapter = _adapter_or_404(market)
        groups = [group] if group else adapter.groups()
        background_tasks.add_task(_safe_breadth_refresh, adapter, groups)
        return {"status": "started", "market": adapter.market_id, "groups": groups}

    @router.post("/{market}/breadth/admin/refresh-now")
    async def breadth_refresh_admin(market: str, background_tasks: BackgroundTasks,
                                     group: str = None, admin: dict = Depends(get_current_admin)):
        adapter = _adapter_or_404(market)
        groups = [group] if group else adapter.groups()
        background_tasks.add_task(_safe_breadth_refresh, adapter, groups)
        return {"status": "started", "market": adapter.market_id, "groups": groups}

    async def _safe_breadth_refresh(adapter, groups: list):
        """Groups run SEQUENTIALLY, one at a time.

        Not a style choice: firing every group as its own parallel task
        meant an 11-sector US pass held eleven groups' direction maps and
        ~55 concurrent HTTP fetches at once, on a 512MB instance with a
        documented OOM history. Sequential keeps peak memory at one
        group's worth regardless of how many groups a market has, which
        is what lets a single cron job cover a whole market safely."""
        for group in groups:
            try:
                await eng.breadth_refresh(adapter, db, group)
            except Exception as e:  # noqa: BLE001 — one group must not sink the rest, or the process
                logger.warning("Breadth refresh failed (%s/%s): %s", adapter.market_id, group, e)

    # ---------------------------------------------------- Relative Strength --
    @router.get("/{market}/relative-strength/groups")
    async def relative_strength_groups(market: str):
        adapter = _adapter_or_404(market)
        return {"groups": [{"key": g, "label": g} for g in adapter.groups()]}

    @router.get("/{market}/relative-strength/matrix")
    async def relative_strength_matrix(market: str, group: str = None, box_pcts: str = "0.25,1,3"):
        """Same signature and same response shape as the India route's
        /terminal/relative-strength/matrix, including the book's default
        short/medium/long-term box sizes -- see eng.relative_strength."""
        adapter = _adapter_or_404(market)
        group = group or adapter.groups()[0]
        tokens = [t.strip() for t in box_pcts.split(",") if t.strip()]
        try:
            values = [float(t) for t in tokens]
        except ValueError:
            raise HTTPException(status_code=400, detail="box_pcts must be comma-separated numbers.")
        if not values:
            raise HTTPException(status_code=400, detail="Provide at least one box_pct.")
        try:
            return await eng.relative_strength(adapter, db, group, values)
        except AdapterError as e:
            raise HTTPException(status_code=502, detail=str(e)) from e

    # ------------------------------------------- Universe-ranking modules ---
    @router.get("/{market}/{slug}/top")
    async def ranking_top(market: str, slug: str, limit: int = 20):
        """Cached read for the three universe-walking modules. Never
        computes inline -- see the module docstring on why."""
        adapter = _adapter_or_404(market)
        if slug not in UNIVERSE_MODULES:
            raise HTTPException(status_code=404, detail=f"Unknown module '{slug}'.")
        blocked = _blocked(adapter, slug)
        if blocked:
            return blocked
        doc = await db[RANKING_CACHE].find_one(
            {"market": adapter.market_id, "module": slug}, {"_id": 0})
        if not doc:
            return {"available": True, "has_data": False, "market": adapter.market_id,
                    "module": slug, "rows": [],
                    "reason": "This ranking hasn't been computed yet — it refreshes on a schedule."}
        doc["rows"] = doc.get("rows", [])[:limit]
        doc["has_data"] = True
        doc["available"] = True
        return doc

    async def _safe_ranking_refresh(adapter, slugs: list):
        """Same sequential discipline as _safe_breadth_refresh — all three
        rankings walk the full universe, so running them concurrently would
        triple peak memory for no wall-clock benefit worth having here."""
        for slug in slugs:
            try:
                runner = UNIVERSE_MODULES[slug]
                result = await runner(adapter, db, limit=250)
                await db[RANKING_CACHE].update_one(
                    {"market": adapter.market_id, "module": slug},
                    {"$set": {"market": adapter.market_id, "module": slug,
                               "rows": result["rows"],
                               "methodology": result.get("methodology"),
                               "risk_free_rate": result.get("risk_free_rate"),
                               "computed_at": datetime.now(timezone.utc).isoformat()}},
                    upsert=True,
                )
            except Exception as e:  # noqa: BLE001
                logger.warning("Ranking refresh failed (%s/%s): %s", adapter.market_id, slug, e)

    @router.post("/{market}/rankings/admin/refresh")
    async def rankings_refresh_cron(market: str, request: Request, background_tasks: BackgroundTasks):
        _require_cron(request)
        adapter = _adapter_or_404(market)
        started = [s for s in UNIVERSE_MODULES if not _blocked(adapter, s)]
        background_tasks.add_task(_safe_ranking_refresh, adapter, started)
        return {"status": "started", "market": adapter.market_id, "modules": started}

    @router.post("/{market}/rankings/admin/refresh-now")
    async def rankings_refresh_admin(market: str, background_tasks: BackgroundTasks,
                                      admin: dict = Depends(get_current_admin)):
        adapter = _adapter_or_404(market)
        started = [s for s in UNIVERSE_MODULES if not _blocked(adapter, s)]
        background_tasks.add_task(_safe_ranking_refresh, adapter, started)
        return {"status": "started", "market": adapter.market_id, "modules": started}

    # -------------------------------------------------------- EWMA Scanner --
    @router.get("/{market}/ewma")
    async def ewma(market: str, symbol: str, fast: int = 20, slow: int = 50):
        adapter = _adapter_or_404(market)
        try:
            return await eng.ewma(adapter, db, symbol, fast, slow)
        except AdapterError as e:
            raise HTTPException(status_code=422, detail=str(e)) from e

    @router.post("/{market}/ewma-crossover")
    async def ewma_crossover(market: str, payload: dict):
        """POST twin of the GET above, speaking the India route's exact
        request and response contract ({symbol, fast_span, slow_span} in;
        found/reason/resolved_symbol out) so the shared EwmaCrossoverTool
        component can point here unchanged. Returns found:false rather than
        an error status for "not enough history", same as India — the
        component renders that as an empty state, not a failure."""
        adapter = _adapter_or_404(market)
        symbol = (payload.get("symbol") or "").strip()
        if not symbol:
            raise HTTPException(status_code=422, detail="symbol is required.")
        try:
            fast = int(payload.get("fast_span") or 20)
            slow = int(payload.get("slow_span") or 50)
        except (TypeError, ValueError):
            raise HTTPException(status_code=422, detail="fast_span/slow_span must be integers.")
        try:
            result = await eng.ewma(adapter, db, symbol, fast, slow)
        except AdapterError as e:
            return {"found": False, "reason": str(e)}
        return {"found": True, "resolved_symbol": result["symbol"], "cached": False, **result}

    # ---------------------------------------------------------- Gamma Pulse --
    @router.get("/{market}/gamma-pulse")
    async def gamma_pulse(market: str, symbol: str = None):
        adapter = _adapter_or_404(market)
        blocked = _blocked(adapter, "options-trend-scanner")
        if blocked:
            return blocked
        symbol = symbol or (adapter.option_underlyings() or [None])[0]
        if not symbol:
            raise HTTPException(status_code=422, detail="No option underlying available.")
        try:
            return await eng.gamma_pulse(adapter, db, symbol)
        except AdapterError as e:
            raise HTTPException(status_code=502, detail=str(e)) from e

    @router.get("/{market}/options-trend/scan")
    async def options_trend_scan(market: str):
        """Universe scan in the India route's shape — see
        eng.gamma_pulse_scan. Blocked markets return the same
        {available:false, reason} envelope every other module uses."""
        adapter = _adapter_or_404(market)
        blocked = _blocked(adapter, "options-trend-scanner")
        if blocked:
            return blocked
        try:
            return await eng.gamma_pulse_scan(adapter, db)
        except AdapterError as e:
            raise HTTPException(status_code=502, detail=str(e)) from e

    @router.get("/{market}/option-underlyings")
    async def option_underlyings(market: str):
        adapter = _adapter_or_404(market)
        return {"market": adapter.market_id, "symbols": adapter.option_underlyings()}

    # ---------------------------------------------------------- Index Vector --
    @router.get("/{market}/index-vector")
    async def index_vector(market: str, symbol: str = None):
        adapter = _adapter_or_404(market)
        blocked = _blocked(adapter, "index-vector")
        if blocked:
            return blocked
        symbol = symbol or (adapter.option_underlyings() or [None])[0]
        if not symbol:
            raise HTTPException(status_code=422, detail="No index underlying available.")
        try:
            return await eng.index_vector(adapter, db, symbol)
        except AdapterError as e:
            raise HTTPException(status_code=502, detail=str(e)) from e

    # ---------------------------------------------------------- Peter Tingle --
    @router.get("/{market}/peter-tingle")
    async def peter_tingle(market: str, symbol: str):
        adapter = _adapter_or_404(market)
        blocked = _blocked(adapter, "peter-tingle")
        if blocked:
            return blocked
        try:
            return await eng.peter_tingle(adapter, db, symbol)
        except AdapterError as e:
            raise HTTPException(status_code=502, detail=str(e)) from e

    return router
