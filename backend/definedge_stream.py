"""
Shared live-tick relay for Definedge Integrate's WebSocket feed
(`wss://trade.definedgesecurities.com/NorenWSTRTP/`) -- the ONE
persistent connection this whole backend process is allowed to hold
(Definedge's own documented limit: one connection at a time, 500 tokens
per connection). Every feature that wants live ticks (P&F Studio,
Index Vector) subscribes THROUGH this manager, never opens its own
socket -- that's what keeps the whole app under the 500-token cap
regardless of how many browser clients or features are watching.

Wire protocol reverse-engineered from Definedge's own official Python
client (github.com/Definedge-Securities/pyintegrate, integrate/ws.py) and
its own API docs page, since pyintegrate itself can't be installed here
(depends on twisted/autobahn, which need a C++ toolchain to build
`twisted-iocpsupport` on Windows -- a local-dev-only problem, irrelevant
on Render's Linux host, but avoided anyway by implementing directly on
top of the `websockets` package, which fits this codebase's asyncio/
FastAPI shape far better than pyintegrate's synchronous Twisted-callback
design):
  - Login frame (sent once connected): {"t":"c","uid":...,"actid":...,
    "source":"TRTP","susertoken":...} -- these three credentials come from
    the SAME REST OTP-verify response definedge_service.py already calls
    daily, previously discarded (see verify_otp()'s 2026-08-26 fix).
  - Login ack: {"t":"ck","s":"OK"|...}.
  - Subscribe/unsubscribe ticks: {"t":"t"|"u","k":"NSE|22#NFO|54321"}
    (exchange|token pairs, joined by "#"). Ack: {"t":"tk"|"uk"}.
  - Tick update (pushed whenever a subscribed token's price moves):
    {"t":"tf","e":"NSE","tk":"22","lp":"1234.50",...} -- ONLY fields that
    changed are present (confirmed on Definedge's own docs page), so a
    tick with no "lp" key is a real message (volume/OI moved, price
    didn't) and is silently skipped, not an error.

Deliberately does NOT implement order ("o") or depth ("d") subscriptions
-- neither P&F Studio nor Index Vector needs them; scope stays to what's
actually used.
"""
import asyncio
import json
import logging
from collections import defaultdict
from typing import Callable

import websockets

logger = logging.getLogger(__name__)

WS_URL = "wss://trade.definedgesecurities.com/NorenWSTRTP/"
MIN_BACKOFF_SECONDS = 2
MAX_BACKOFF_SECONDS = 60
NO_CREDENTIALS_RETRY_SECONDS = 30  # how often to re-check for a completed daily OTP login

TickCallback = Callable[[dict], None]


class DefinedgeStream:
    """One instance per backend process, started once at FastAPI startup
    (see server.py) and never per-request. `definedge` is the existing
    DefinedgeService instance -- reused for its session/credential
    storage, not a second auth path."""

    def __init__(self, definedge):
        self.definedge = definedge
        self._ws = None
        self._logged_in = False
        self._subscribers: dict[tuple[str, str], set[TickCallback]] = defaultdict(set)
        self._refcounts: dict[tuple[str, str], int] = defaultdict(int)
        self._task: asyncio.Task | None = None
        self._stopping = False

    def start(self) -> None:
        if self._task is None or self._task.done():
            self._stopping = False
            self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        self._stopping = True
        if self._ws is not None:
            await self._ws.close()
        if self._task is not None:
            try:
                await asyncio.wait_for(self._task, timeout=5)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                self._task.cancel()

    @property
    def connected(self) -> bool:
        return self._logged_in

    async def subscribe(self, exchange: str, token: str, callback: TickCallback) -> None:
        """Registers `callback` for every tick on (exchange, token). Only
        sends a real Definedge subscribe frame the first time this token
        goes from 0 -> 1 total subscribers across the whole process
        (refcounted) -- a second chart/tab watching the same instrument
        costs nothing extra upstream."""
        key = (exchange, str(token))
        self._subscribers[key].add(callback)
        self._refcounts[key] += 1
        if self._refcounts[key] == 1 and self._logged_in:
            await self._send_subscribe([key])

    async def unsubscribe(self, exchange: str, token: str, callback: TickCallback) -> None:
        key = (exchange, str(token))
        self._subscribers[key].discard(callback)
        if not self._subscribers[key]:
            del self._subscribers[key]
        if key in self._refcounts:
            self._refcounts[key] -= 1
            if self._refcounts[key] <= 0:
                del self._refcounts[key]
                if self._logged_in:
                    await self._send_unsubscribe([key])

    async def _run(self) -> None:
        backoff = MIN_BACKOFF_SECONDS
        while not self._stopping:
            creds = await self.definedge.ws_credentials()
            if not creds:
                logger.info("Definedge stream: no WS credentials yet (daily OTP login not done) — retrying.")
                await asyncio.sleep(NO_CREDENTIALS_RETRY_SECONDS)
                continue
            try:
                async with websockets.connect(WS_URL, ping_interval=10, ping_timeout=5) as ws:
                    self._ws = ws
                    await ws.send(json.dumps({
                        "t": "c", "uid": creds["uid"], "actid": creds["actid"],
                        "source": "TRTP", "susertoken": creds["susertoken"],
                    }))
                    backoff = MIN_BACKOFF_SECONDS
                    async for raw in ws:
                        self._handle_message(raw)
            except (websockets.exceptions.WebSocketException, OSError) as e:
                logger.warning("Definedge stream disconnected: %s", e)
            finally:
                self._ws = None
                self._logged_in = False
            if self._stopping:
                break
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, MAX_BACKOFF_SECONDS)

    def _handle_message(self, raw) -> None:
        try:
            msg = json.loads(raw)
        except ValueError:
            logger.warning("Definedge stream: malformed message, dropped.")
            return
        t = msg.get("t")
        if t == "ck":
            self._logged_in = msg.get("s") == "OK"
            if self._logged_in:
                logger.info("Definedge stream: logged in.")
                if self._refcounts:
                    asyncio.create_task(self._send_subscribe(list(self._refcounts.keys())))
            else:
                logger.error("Definedge stream: login rejected: %s", msg)
        elif t == "tf":
            if "lp" not in msg:
                return  # a real tick where price itself didn't change (only volume/OI) -- not an error
            key = (msg.get("e"), str(msg.get("tk")))
            for cb in list(self._subscribers.get(key, ())):
                try:
                    cb(msg)
                except Exception:  # noqa: BLE001 -- one bad subscriber must never kill the shared feed
                    logger.exception("Definedge stream: subscriber callback failed for %s", key)
        # "tk"/"uk" (subscribe/unsubscribe acks) are informational only, nothing to do with them.

    async def _send_subscribe(self, keys: list[tuple[str, str]]) -> None:
        if self._ws is None:
            return
        k = "#".join(f"{ex}|{tok}" for ex, tok in keys)
        await self._ws.send(json.dumps({"t": "t", "k": k}))

    async def _send_unsubscribe(self, keys: list[tuple[str, str]]) -> None:
        if self._ws is None:
            return
        k = "#".join(f"{ex}|{tok}" for ex, tok in keys)
        await self._ws.send(json.dumps({"t": "u", "k": k}))
