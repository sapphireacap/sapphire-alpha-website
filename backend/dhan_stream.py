"""
Shared live-tick relay for Dhan's v2 Live Market Feed WebSocket
(`wss://api-feed.dhan.co`) -- the counterpart to definedge_stream.py, used
by P&F Studio's PRIMARY bar source (pnf_routes.py resolves India symbols
via Dhan first, Definedge only as a fallback -- see that file's own
comment on why: Dhan reaches 4+ years of minute history where Definedge
hard-400s past ~6 months).

Wire protocol reverse-engineered from Dhan's own official Python client
(github.com/dhan-oss/DhanHQ-py, src/dhanhq/marketfeed.py) -- NOT
installed as a dependency (its `MarketFeed` class is a blocking,
thread-per-connection design built around its own event loop, which
doesn't fit this already-async FastAPI process), implemented directly
on `websockets` instead, same approach as definedge_stream.py:
  - Connect: `wss://api-feed.dhan.co?version=2&token=<access_token>&
    clientId=<client_id>&authType=2` -- auth is IN THE URL, no separate
    login frame (unlike Definedge's post-connect "t":"c" frame).
  - Subscribe (JSON): {"RequestCode":15,"InstrumentCount":N,
    "InstrumentList":[{"ExchangeSegment":"NSE_EQ"|"IDX_I"|"NSE_FNO"|...,
    "SecurityId":"..."}]} -- RequestCode 15 = Ticker (LTP only, which is
    all a live P&F bar needs -- matches pnf_chart._with_live_bar's
    existing use of a plain LTP quote). Max 100 instruments per message
    (batched below). Unsubscribe = RequestCode 16 (subscribe code + 1).
  - Responses are BINARY, dispatched on the first byte: 2=Ticker,
    3=Depth, 4=Quote, 5=OI, 6=PrevClose, 7=Status, 8=Full, 50=Disconnect.
    Ticker unpacks as `<BHBIfI` (16 bytes): [response_code, msg_length,
    exchange_segment(int), security_id(int), LTP(float32), LTT(epoch)].
  - Disconnect codes worth knowing: 807 = access token expired (this
    module re-fetches one via dhan_auth.get_access_token(db, force=True)
    and reconnects -- Dhan's own token cache/refresh, not duplicated
    here), 805 = too many connections (a real cap: 5 per client ID,
    5000 instruments each -- generous vs. Definedge's 1-connection/500-
    token limit, refcounting here is about avoiding redundant upstream
    load, not staying under a tight ceiling).

Same shape as definedge_stream.py: one shared connection, refcounted
subscribe/unsubscribe, reconnect with backoff, in-process pub/sub to
whichever features/browser sockets asked for a given (exchange_segment,
security_id).
"""
import asyncio
import json
import logging
import os
import struct
from collections import defaultdict
from typing import Callable

import websockets

import dhan_auth

logger = logging.getLogger(__name__)

WS_URL = "wss://api-feed.dhan.co"
MIN_BACKOFF_SECONDS = 2
MAX_BACKOFF_SECONDS = 60
NO_CREDENTIALS_RETRY_SECONDS = 30

REQUEST_CODE_TICKER = 15
TICKER_RESPONSE_BYTE = 2
DISCONNECT_RESPONSE_BYTE = 50
DISCONNECT_REASON = {
    805: "too many active connections",
    806: "not subscribed to Data APIs",
    807: "access token expired",
    808: "invalid client ID",
    809: "authentication failed",
}

TickCallback = Callable[[dict], None]


class DhanStream:
    """One instance per backend process. `db` is reused for
    dhan_auth.get_access_token()'s own token cache -- this module never
    stores or refreshes credentials itself."""

    def __init__(self, db):
        self.db = db
        self._ws = None
        self._connected = False
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
        return self._connected

    async def subscribe(self, exchange_segment: str, security_id: str, callback: TickCallback) -> None:
        key = (exchange_segment, str(security_id))
        self._subscribers[key].add(callback)
        self._refcounts[key] += 1
        if self._refcounts[key] == 1 and self._connected:
            await self._send_subscribe([key])

    async def unsubscribe(self, exchange_segment: str, security_id: str, callback: TickCallback) -> None:
        key = (exchange_segment, str(security_id))
        self._subscribers[key].discard(callback)
        if not self._subscribers[key]:
            del self._subscribers[key]
        if key in self._refcounts:
            self._refcounts[key] -= 1
            if self._refcounts[key] <= 0:
                del self._refcounts[key]
                if self._connected:
                    await self._send_subscribe([key], unsub=True)

    async def _run(self) -> None:
        backoff = MIN_BACKOFF_SECONDS
        force_token = False
        while not self._stopping:
            if not dhan_auth.configured():
                logger.info("Dhan stream: not configured (missing DHAN_CLIENT_ID/PIN/TOTP) — retrying.")
                await asyncio.sleep(NO_CREDENTIALS_RETRY_SECONDS)
                continue
            try:
                token = await dhan_auth.get_access_token(self.db, force=force_token)
                force_token = False
                client_id = os.environ["DHAN_CLIENT_ID"].strip()
                url = f"{WS_URL}?version=2&token={token}&clientId={client_id}&authType=2"
                async with websockets.connect(url, ping_interval=10, ping_timeout=5) as ws:
                    self._ws = ws
                    self._connected = True
                    backoff = MIN_BACKOFF_SECONDS
                    if self._refcounts:
                        await self._send_subscribe(list(self._refcounts.keys()))
                    async for raw in ws:
                        force_token = self._handle_message(raw) or force_token
            except (websockets.exceptions.WebSocketException, OSError, dhan_auth.DhanAuthError) as e:
                logger.warning("Dhan stream disconnected: %s", e)
            finally:
                self._ws = None
                self._connected = False
            if self._stopping:
                break
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, MAX_BACKOFF_SECONDS)

    def _handle_message(self, raw: bytes) -> bool:
        """Returns True if the token should be force-refreshed before the
        next reconnect attempt (i.e. the server disconnected us for an
        expired token)."""
        if not raw or len(raw) < 1:
            return False
        first_byte = raw[0]
        if first_byte == DISCONNECT_RESPONSE_BYTE:
            code = struct.unpack("<H", raw[8:10])[0] if len(raw) >= 10 else None
            reason = DISCONNECT_REASON.get(code, f"code {code}")
            logger.warning("Dhan stream: server disconnected us (%s).", reason)
            return code == 807
        if first_byte == TICKER_RESPONSE_BYTE:
            if len(raw) < 16:
                return False
            _, _, exchange_segment, security_id, ltp, _ = struct.unpack("<BHBIfI", raw[0:16])
            # Dhan's ticker packet carries exchange_segment as the NUMERIC
            # code (0=IDX_I, 1=NSE_EQ, 2=NSE_FNO, ...), but subscribe/refcount
            # keys everywhere else in this module use the STRING form
            # ("NSE_EQ" etc, matching dhan_master.resolve()'s own shape) --
            # translate here so a caller's callback lookup actually matches
            # what it subscribed with.
            seg_str = _EXCHANGE_SEGMENT_BY_CODE.get(exchange_segment)
            if seg_str is None:
                return False
            key = (seg_str, str(security_id))
            for cb in list(self._subscribers.get(key, ())):
                try:
                    cb({"ltp": ltp, "exchange_segment": seg_str, "security_id": str(security_id)})
                except Exception:  # noqa: BLE001 -- one bad subscriber must never kill the shared feed
                    logger.exception("Dhan stream: subscriber callback failed for %s", key)
        return False

    async def _send_subscribe(self, keys: list[tuple[str, str]], unsub: bool = False) -> None:
        if self._ws is None:
            return
        code = REQUEST_CODE_TICKER + (1 if unsub else 0)
        for i in range(0, len(keys), 100):  # Dhan's own documented per-message cap
            batch = keys[i:i + 100]
            message = {
                "RequestCode": code,
                "InstrumentCount": len(batch),
                "InstrumentList": [{"ExchangeSegment": seg, "SecurityId": sid} for seg, sid in batch],
            }
            await self._ws.send(json.dumps(message))


# Numeric exchange-segment code -> string form, per Dhan's own client
# (dhanhq.marketfeed.MarketFeed.get_exchange_segment).
_EXCHANGE_SEGMENT_BY_CODE = {
    0: "IDX_I", 1: "NSE_EQ", 2: "NSE_FNO", 3: "NSE_CURRENCY",
    4: "BSE_EQ", 5: "MCX_COMM", 7: "BSE_CURRENCY", 8: "BSE_FNO",
}
