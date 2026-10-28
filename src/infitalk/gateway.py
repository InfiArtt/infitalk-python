"""The connection to the InfiTalk bot gateway (wss://tt.infiartt.com/bot).

It identifies with the token, sends heartbeats, remembers the session and the last event of every server
so a short break loses nothing (resume), connects again after a break with growing waits, matches answers to
requests by ``ref``, and waits and retries when a request is rate limited. A changed token (4004) or the same
bot connecting somewhere else (4005) stops it.
"""
from __future__ import annotations

import asyncio
import itertools
import json
import logging
import random
from typing import Any, Awaitable, Callable, Dict, Tuple

from .errors import InfiTalkError, InvalidToken, RateLimited, Replaced, error_from

try:  # websockets 13 and newer
    from websockets.asyncio.client import connect as _connect
except ImportError:  # pragma: no cover
    from websockets import connect as _connect  # type: ignore[no-redef]
from websockets.exceptions import ConnectionClosed

DEFAULT_GATEWAY = "wss://tt.infiartt.com/bot"
log = logging.getLogger("infitalk")

Handler = Callable[[Dict[str, Any]], Awaitable[None]]


class Connection:
    def __init__(self, url: str, token: str, handler: Handler, on_closed: Callable[[int, str], Awaitable[None]],
                 *, request_timeout: float = 15.0, retries: int = 3):
        self.url, self.token = url, token
        self._handler, self._on_closed = handler, on_closed
        self.request_timeout, self.retries = request_timeout, retries
        self.resume: Dict[str, Dict[str, Any]] = {}  # server -> {"session", "seq"}
        self._ws: Any = None
        self._pending: Dict[str, asyncio.Future] = {}
        self._refs = itertools.count(1)
        self._stop = False
        self.connected = asyncio.Event()

    # ---------- sending ----------

    async def send(self, msg: Dict[str, Any]) -> None:
        """Send without waiting for an answer (audio); errors come back as on_error."""
        if self._ws is None:
            raise InfiTalkError("not_connected", "the gateway is not connected")
        await self._ws.send(json.dumps(msg, separators=(",", ":")))

    async def request(self, msg: Dict[str, Any]) -> Dict[str, Any]:
        """Send and wait for the answer; raises InfiTalkError when refused. Rate limits are waited out."""
        for attempt in range(self.retries + 1):
            ref = "py" + str(next(self._refs))
            fut: asyncio.Future = asyncio.get_running_loop().create_future()
            self._pending[ref] = fut
            try:
                await self.send({**msg, "ref": ref})
                answer = await asyncio.wait_for(fut, self.request_timeout)
            except asyncio.TimeoutError:
                raise InfiTalkError("timeout", f"no answer to {msg.get('op')} in {self.request_timeout} s") from None
            finally:
                self._pending.pop(ref, None)
            if answer.get("ok", True) is not False:
                return answer
            err = error_from(answer)
            if isinstance(err, RateLimited) and attempt < self.retries:
                await asyncio.sleep(err.retry_after)
                continue
            raise err
        raise InfiTalkError("rate_limited")  # pragma: no cover

    # ---------- the connection ----------

    async def run(self) -> None:
        """Connect, and again after every break, until stop() or a final close."""
        delay = 1.0
        while not self._stop:
            code, reason = 1006, "connection lost"
            try:
                code, reason = await self._session()
                delay = 1.0
            except (OSError, ConnectionClosed, asyncio.TimeoutError) as e:
                reason = str(e) or e.__class__.__name__
                log.warning("gateway: %s", reason)
            finally:
                self._ws = None
                self.connected.clear()
                for fut in self._pending.values():
                    if not fut.done():
                        fut.set_exception(InfiTalkError("disconnected", "the connection to the gateway dropped"))
                self._pending.clear()
            await self._on_closed(code, reason)
            if self._stop:
                break
            if code == 4004:
                raise InvalidToken("invalid_token", "the token is not valid any more, or the bot was turned off")
            if code == 4005:
                raise Replaced("replaced", "the same bot connected from somewhere else")
            wait = max(delay, 10.0) if code == 4008 else delay
            wait += random.uniform(0, wait / 4)
            log.info("gateway: closed (%s %s); connecting again in %.0f s", code, reason, wait)
            await asyncio.sleep(wait)
            delay = min(delay * 2, 30.0)

    async def _session(self) -> Tuple[int, str]:
        async with _connect(self.url, max_size=2 ** 21, open_timeout=15, ping_interval=None) as ws:
            self._ws = ws
            hello = json.loads(await asyncio.wait_for(ws.recv(), 15))
            every = float(hello.get("heartbeat_interval", 30000)) / 1000
            beat = asyncio.ensure_future(self._heartbeat(ws, every))
            try:
                await ws.send(json.dumps({"op": "identify", "token": self.token, "resume": self.resume}))
                try:
                    async for text in ws:
                        await self._receive(text)
                except ConnectionClosed:
                    pass
            finally:
                beat.cancel()
            return int(getattr(ws, "close_code", None) or 1006), str(getattr(ws, "close_reason", "") or "")

    async def _heartbeat(self, ws: Any, every: float) -> None:
        while True:
            await asyncio.sleep(max(1.0, every * 0.8))
            try:
                await ws.send('{"op":"heartbeat"}')
            except ConnectionClosed:
                return

    async def _receive(self, text: str) -> None:
        try:
            msg = json.loads(text)
        except ValueError:
            log.warning("gateway: a message that is not JSON")
            return
        if not isinstance(msg, dict):
            return
        server = msg.get("server")
        if server is not None and isinstance(msg.get("seq"), int) and str(server) in self.resume:
            self.resume[str(server)]["seq"] = msg["seq"]
        op = msg.get("op")
        if op == "identified":
            self.connected.set()
        elif op == "ready" and server is not None:
            old = self.resume.get(str(server), {})
            self.resume[str(server)] = {"session": msg.get("session", ""),
                                        "seq": old.get("seq", 0) if msg.get("resumed") else 0}
        elif op == "server_removed" and server is not None:
            self.resume.pop(str(server), None)
        elif op == "heartbeat_ack":
            return
        ref = msg.get("ref")
        if ref is not None and op == "result":
            fut = self._pending.get(str(ref))
            if fut is not None and not fut.done():
                fut.set_result(msg)
                return
        await self._handler(msg)

    async def stop(self) -> None:
        self._stop = True
        if self._ws is not None:
            await self._ws.close()

    @property
    def ws_open(self) -> bool:
        return self._ws is not None


__all__ = ["Connection", "DEFAULT_GATEWAY"]
