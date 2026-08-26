"""API for the Relative Strength Matrix — public, no auth, same tier as
Alpha Terminal's other live modules (Index Vector, Exitline, Momentum
Leaders). See relative_strength_matrix.py for the actual computation and
relative_strength_groups.py for the fixed sector baskets.

/matrix-start + /matrix-status is a job/poll pair (same shape as
server.py's EOD-refresh-all admin panel) so the frontend can show REAL
percent-complete instead of a fabricated animation. This matters because
compute_ranking is synchronous, CPU-bound pure Python with no awaits in
its inner loop -- for a 250-symbol group that's ~31k pairs x 3 box sizes,
enough real work that running it directly inside a request handler would
freeze the whole single-process event loop (including this endpoint's own
status polls) for the entire duration. Instead the job runs the fetch
phase as normal async I/O, then hands the compute phase to a worker
thread via asyncio.to_thread -- the event loop stays free to serve
/matrix-status polls throughout, and the progress counter the worker
thread increments (a plain int in the job dict) is safe to read from the
main thread under the GIL without a lock."""
import asyncio
import csv
import io
import logging
import time
import uuid
from datetime import datetime

import httpx
from fastapi import APIRouter, HTTPException, Depends

import relative_strength_matrix as rsm
import yahoo_finance_client as yf
from definedge_service import IST, DefinedgeError
from relative_strength_groups import GROUPS, get_group

BROWSER_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)
_index_csv_cache: dict = {}  # csv_url -> (date_str, list[str]) — per-day TTL, same as swing_reversal_routes._nifty500_cache


async def _fetch_index_csv(csv_url: str) -> list:
    """Symbol list for one NSE index-constituent CSV, cached per calendar
    day (index reconstitutions happen a few times a year, not intraday).
    Generalises swing_reversal_routes._fetch_nifty500_list to any of NSE's
    ind_<index>list.csv files, since the Relative Strength Matrix now
    needs several of them (Nifty 50/100/Midcap 100/Smallcap 250), not just
    Nifty 500."""
    today = datetime.now(IST).strftime("%Y-%m-%d")
    cached = _index_csv_cache.get(csv_url)
    if cached and cached[0] == today:
        return cached[1]
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.get(csv_url, headers={"User-Agent": BROWSER_USER_AGENT})
    if r.status_code != 200:
        raise DefinedgeError(f"Index constituent list fetch failed (HTTP {r.status_code}).")
    symbols = []
    for row in csv.DictReader(io.StringIO(r.text)):
        symbol = (row.get("Symbol") or "").strip()
        if symbol:
            symbols.append(symbol)
    _index_csv_cache[csv_url] = (today, symbols)
    return symbols

logger = logging.getLogger(__name__)

CACHE_COLLECTION = "rs_daily_closes"
# The hand-curated sector baskets are 8-14 symbols, so firing every
# closes-fetch at once was never a problem. The new broad-market groups
# (Nifty 100, Smallcap 250) are large enough that unbounded concurrency
# would mean 100-250 simultaneous live Definedge calls, each holding a
# 20-year daily-bar response in memory at once — exactly the kind of
# concurrent-fetch spike that caused this app's own OOM crash-loop
# elsewhere (see server.py's EOD_REFRESH_STAGGER_SECONDS history). Capped
# here instead of staggered with real delays, since these are read
# requests a user is actively waiting on, not a background job.
_FETCH_CONCURRENCY = 10
# The box grid is an ABSOLUTE grid (pnf_engine.py rule 8) so the current
# LEVEL never depends on how much history is loaded, but the current
# DIRECTION does - it's whatever direction the last reversal set, and a 3%
# (or even 1%) box on a ratio chart can go years between reversals. A
# truncated window that starts mid-swing locks in a fabricated "first
# column" (rule 4: only 1 box needed to open a column, not a full reversal)
# that may never get corrected before "today", producing a direction that
# diverges from Definedge's own chart (which uses full available history).
# 20y comfortably covers a 3-box reversal at 3% for these liquid bank
# stocks and costs nothing extra - daily_history() just returns whatever
# actually exists if the instrument is younger.
YEARS_BACK = 20

# In-memory job store for /matrix-start + /matrix-status. Deliberately not
# in Mongo -- a job is a few seconds to at most ~1-2 minutes of scratch
# progress state for one visitor's one request, not something that needs
# to survive a restart or be queried by anything else. Pruned opportunistically
# (_prune_jobs) rather than on a timer, since traffic on this module is low
# enough that a dict of a few live/recent jobs is never a memory concern.
_jobs: dict = {}
_JOB_TTL_SECONDS = 600


def _prune_jobs():
    cutoff = time.time() - _JOB_TTL_SECONDS
    for jid in [j for j, v in _jobs.items() if v["created_at"] < cutoff]:
        _jobs.pop(jid, None)


def create_relative_strength_router(db, definedge, get_current_user) -> APIRouter:
    # Alpha Terminal access rule: only Index Vector and Exitline are open to
    # signed-out visitors; every other module needs an account. Enforced on
    # the server too, since these endpoints are directly callable.
    require_user = Depends(get_current_user)

    router = APIRouter(prefix="/terminal/relative-strength", tags=["relative-strength"])
    fetch_semaphore = asyncio.Semaphore(_FETCH_CONCURRENCY)

    @router.get("/groups")
    async def groups(user: dict = require_user):
        # Dynamic (csv_url) groups don't carry a fixed `symbols` list —
        # their constituents are only known after the day's NSE CSV fetch,
        # which /matrix does lazily. The frontend group selector only
        # reads key/label, never this field.
        return {"groups": [
            {"key": k, "label": v["label"], "symbols": v.get("symbols", [])} for k, v in GROUPS.items()
        ]}

    async def _closes_for_nse(symbol: str, master) -> dict | None:
        """{date: close} for one NSE symbol, cached in Mongo once today's
        own close is actually in it — a 8-12 symbol group means every
        matrix request costs that many live Definedge calls otherwise,
        and nothing about a day's already-closed daily bar changes
        intraday.

        Freshness is keyed on whether TODAY's date is actually a key in
        the cached closes, not on when the cache was last written —
        Definedge's day-history only grows a TODAY row once that day's
        candle is finalised (same gap pnf_chart.py's _with_live_bar works
        around for the single-symbol chart), so a request made before
        market close would otherwise lock in a version missing today's
        close for the rest of the day, even after the market closes.

        Also keyed on YEARS_BACK itself (stored as `years_back` on the
        doc) — a cache written under an older, shorter window would
        otherwise look "fresh" forever (today's close doesn't stop being
        in it) and never pick up the wider history a YEARS_BACK bump
        requires. Docs from before this field existed (`years_back`
        missing) are treated as stale too.

        Returns None (never raises) on a resolve/fetch failure instead of
        aborting the whole request — a hand-curated 8-12 symbol sector
        basket was never expected to have a bad symbol in it (and if it
        did, that WAS worth surfacing loudly), but the new broad-market
        groups run 50-250 constituents sourced from a live NSE CSV, where
        an occasional delisted/renamed symbol not yet in Definedge's
        master is expected, not exceptional — the matrix should compute
        over whichever constituents actually resolve rather than failing
        entirely for the other 249."""
        today = datetime.now(IST).date().isoformat()
        doc = await db[CACHE_COLLECTION].find_one({"symbol": symbol})
        if doc and today in doc.get("closes", {}) and doc.get("years_back") == YEARS_BACK:
            return doc["closes"]

        found = definedge.resolve_symbol(master, "NSE", symbol)
        if not found:
            logger.warning("Relative Strength: could not resolve %s, skipping.", symbol)
            return None
        try:
            bars = await definedge.daily_history("NSE", found["token"], years=YEARS_BACK)
        except DefinedgeError as e:
            logger.warning("Daily history fetch failed for %s, skipping: %s", symbol, e)
            return None
        closes = {b["date"]: b["close"] for b in bars}
        await db[CACHE_COLLECTION].update_one(
            {"symbol": symbol},
            {"$set": {"symbol": symbol, "last_fetched_date": today, "years_back": YEARS_BACK, "closes": closes}},
            upsert=True,
        )
        return closes

    async def _closes_for_yahoo(symbol: str) -> dict:
        """{date: close} for one US equity ticker via Yahoo Finance —
        Definedge carries no US market data at all (same reason
        pnf_routes.py's US Indices segment uses Yahoo instead). Caching
        is yahoo_finance_client.equity_bars()'s own job (same
        accumulate-forever-per-day pattern already proven for US
        Indices), not duplicated here."""
        try:
            bars = await yf.equity_bars(db, symbol)
        except yf.YahooFinanceError as e:
            logger.warning("Yahoo fetch failed for %s: %s", symbol, e)
            raise HTTPException(status_code=502,
                                detail="Chart data is temporarily unavailable — please try again shortly.")
        return {b["date"]: b["close"] for b in bars}

    async def _resolve_closes(cfg: dict, job: dict | None):
        """Symbol list + {date: close} per symbol for one group. `job`, if
        given, gets its phase/done/total updated live as each symbol
        resolves — the fetch phase is real async I/O, so these updates
        land while the event loop is free to serve a concurrent status
        poll."""
        if cfg.get("csv_url"):
            try:
                symbols = await _fetch_index_csv(cfg["csv_url"])
            except DefinedgeError:
                raise HTTPException(status_code=502,
                                    detail="Index constituent list is temporarily unavailable — please try again shortly.")
        else:
            symbols = cfg["symbols"]

        if job is not None:
            job["phase"] = "fetching"
            job["done"] = 0
            job["total"] = len(symbols)

        async def _bounded(coro):
            async with fetch_semaphore:
                result = await coro
                if job is not None:
                    job["done"] += 1
                return result

        source = cfg.get("source", "NSE")
        if source == "YAHOO":
            closes_maps = await asyncio.gather(*[_bounded(_closes_for_yahoo(s)) for s in symbols])
        else:
            try:
                master = await definedge._get_all_master()
            except DefinedgeError:
                raise HTTPException(status_code=502,
                                    detail="Chart data is temporarily unavailable — please try again shortly.")
            closes_maps = await asyncio.gather(*[_bounded(_closes_for_nse(s, master)) for s in symbols])

        # Symbols that failed to resolve/fetch (_closes_for_nse returns
        # None rather than raising — see its docstring) are dropped here
        # rather than plugged into the matrix as empty data. Only matters
        # for the broad-market csv_url groups in practice; the hand-curated
        # sector baskets are pre-verified so this is normally a no-op there.
        resolved_pairs = [(s, c) for s, c in zip(symbols, closes_maps) if c]
        symbols = [s for s, _ in resolved_pairs]
        per_symbol = dict(resolved_pairs)
        if len(symbols) < 2:
            raise HTTPException(status_code=502, detail="Not enough resolvable instruments in this group right now.")
        return symbols, per_symbol

    def _build_response(group: str, cfg: dict, symbols: list, per_symbol: dict,
                        tokens: list, values: list, label_by_value: dict, job: dict | None):
        """Pure assembly + the actual (CPU-bound) compute_ranking call.
        Safe to run inside asyncio.to_thread — touches no async/db state,
        only reads closes already fetched and writes progress ints into
        `job` (plain dict, GIL-safe for the main thread to read)."""
        # NOT truncated to a group-wide date intersection — rsm.compute_matrix
        # aligns each PAIR to its own common dates. A group-wide intersection
        # here would clip every pair's history down to the group's youngest
        # listing (e.g. BANDHANBNK, 2018), starving pairs of two long-listed
        # stocks (e.g. HDFCBANK vs PNB) of history they actually have for no
        # reason connected to that pair. See relative_strength_matrix.py's
        # module docstring for what this did and didn't turn out to fix when
        # checked live.
        common_dates = sorted(set.intersection(*(set(c.keys()) for c in per_symbol.values())))
        if len(common_dates) < 2:
            raise HTTPException(status_code=400, detail="Not enough overlapping price history for this group yet.")

        if job is not None:
            job["phase"] = "computing"
            job["done"] = 0
            job["total"] = (len(symbols) * (len(symbols) - 1) // 2) * len(values)
            on_pair = lambda: job.__setitem__("done", job["done"] + 1)
        else:
            on_pair = None

        result = rsm.compute_ranking(symbols, per_symbol, values, on_pair=on_pair)

        return {
            "group": group,
            "label": cfg["label"],
            "symbols": symbols,
            "as_of": common_dates[-1],
            "history_from": common_dates[0],
            "box_pcts": tokens,
            "matrices": {
                label_by_value[bp]: {"grid": m["grid"], "scores": m["scores"]}
                for bp, m in result["matrices"].items()
            },
            "ranking": [
                {"symbol": r["symbol"],
                 "scores": {label_by_value[bp]: sc for bp, sc in r["scores"].items()},
                 "total": r["total"]}
                for r in result["ranking"]
            ],
        }

    def _parse_group_and_boxes(group: str, box_pcts: str):
        cfg = get_group(group)
        if not cfg:
            raise HTTPException(status_code=404,
                                detail=f"Unknown group '{group}'. Must be one of {', '.join(GROUPS)}.")
        tokens = [t.strip() for t in box_pcts.split(",") if t.strip()]
        try:
            values = [float(t) for t in tokens]
        except ValueError:
            raise HTTPException(status_code=400, detail="box_pcts must be comma-separated numbers.")
        if not values:
            raise HTTPException(status_code=400, detail="Provide at least one box_pct.")
        return cfg, tokens, values, dict(zip(values, tokens))

    @router.get("/matrix")
    async def matrix(group: str, box_pcts: str = "0.25,1,3", user: dict = require_user):
        """Full multi-box-size matrix + ranking for one fixed group,
        computed synchronously. Box sizes default to the book's own
        short/medium/long-term convention (0.25% / 1% / 3%) — pass a
        different comma-separated list to override. Kept for any direct
        caller that doesn't need progress; the frontend tool itself uses
        /matrix-start + /matrix-status instead (see module docstring)."""
        cfg, tokens, values, label_by_value = _parse_group_and_boxes(group, box_pcts)
        symbols, per_symbol = await _resolve_closes(cfg, job=None)
        return _build_response(group, cfg, symbols, per_symbol, tokens, values, label_by_value, job=None)

    @router.post("/matrix-start")
    async def matrix_start(group: str, box_pcts: str = "0.25,1,3", user: dict = require_user):
        """Kicks off the same computation as /matrix as a background job
        and returns a job_id immediately — poll /matrix-status with it for
        real phase/percent-complete plus the final result."""
        cfg, tokens, values, label_by_value = _parse_group_and_boxes(group, box_pcts)
        _prune_jobs()
        job_id = uuid.uuid4().hex
        job = {"status": "running", "phase": "resolving", "done": 0, "total": 0,
              "result": None, "error": None, "created_at": time.time()}
        _jobs[job_id] = job

        async def _run():
            try:
                symbols, per_symbol = await _resolve_closes(cfg, job=job)
                payload = await asyncio.to_thread(
                    _build_response, group, cfg, symbols, per_symbol, tokens, values, label_by_value, job,
                )
                job["result"] = payload
                job["status"] = "done"
            except HTTPException as e:
                job["error"] = e.detail
                job["status"] = "error"
            except Exception as e:  # noqa: BLE001 -- a job must never hang the poller on an unexpected error
                logger.exception("Relative Strength job %s failed", job_id)
                job["error"] = "Something went wrong computing this matrix — please try again."
                job["status"] = "error"

        # Reference kept on the job dict itself -- asyncio only holds a
        # weak reference to a bare create_task() result, so without this
        # the task could be garbage-collected mid-run.
        job["_task"] = asyncio.create_task(_run())
        return {"job_id": job_id}

    @router.get("/matrix-status")
    async def matrix_status(job_id: str, user: dict = require_user):
        job = _jobs.get(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Unknown or expired job.")
        percent = round(100 * job["done"] / job["total"]) if job["total"] else 0
        return {
            "status": job["status"], "phase": job["phase"],
            "done": job["done"], "total": job["total"], "percent": percent,
            "result": job["result"], "error": job["error"],
        }

    return router
