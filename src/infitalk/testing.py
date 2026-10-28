"""Test a bot without a server: a pretend gateway with one server, on your own computer.

    import pytest
    from infitalk.testing import TestServer
    from mybot import bot

    @pytest.mark.asyncio
    async def test_echo():
        async with TestServer() as srv:
            await srv.start(bot)
            answer = await srv.command("echo", text="hi")
            assert answer["content"] == "hi" and answer.get("public")

It answers every request like a server would (msgid, count, instance), checks the 3-second rule and dialogs
(labels, limits) like the real server, and lets the test play the people: commands, messages, buttons,
dialog events, suggestions, a server going to sleep and waking up.
"""
from __future__ import annotations

import asyncio
import itertools
import json
from typing import Any, Dict, List, Optional

try:
    from websockets.asyncio.server import serve as _serve
except ImportError:  # pragma: no cover
    from websockets import serve as _serve  # type: ignore[no-redef]

from .bot import Bot
from .models import User

ANSWER_OPS = ("respond", "defer", "dialog", "dialog_update", "dialog_close", "suggestions", "say", "edit")
TESTER = User(2, "Tester", "tester@infiartt.com", "everyone")


class BotDidNotAnswer(AssertionError):
    """The bot did not answer an interaction within 3 seconds (people would hear "<bot> did not answer")."""


class TestServer:
    __test__ = False  # not a pytest test class

    def __init__(self, *, server_id: int = 1, name: str = "Test server", bot_name: str = "testbot",
                 channels: Optional[List[Dict[str, Any]]] = None, intents: Optional[List[str]] = None):
        self.server_id, self.name, self.bot_name = server_id, name, bot_name
        self.channels = channels or [{"id": 1, "path": "/", "name": "Test server"},
                                     {"id": 2, "path": "/Music/", "name": "Music"}]
        self.intents = intents or ["mentions", "direct", "send", "manage_own", "speak", "dialogs", "commands"]
        self.sent: List[Dict[str, Any]] = []       # everything the bot sent (no heartbeats)
        self.menu: List[Dict[str, Any]] = []       # its last menu
        self.bot_channel = 0
        self._ws: Any = None
        self._server: Any = None
        self._task: Optional[asyncio.Task] = None
        self._changed = asyncio.Condition()
        self._ids = itertools.count(1000)
        self._seq = itertools.count(1)
        self._ready = asyncio.Event()
        self.url = ""

    async def __aenter__(self) -> "TestServer":
        self._server = await _serve(self._conn, "127.0.0.1", 0)
        port = next(iter(self._server.sockets)).getsockname()[1]
        self.url = f"ws://127.0.0.1:{port}/bot"
        return self

    async def __aexit__(self, *exc: Any) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass
        self._server.close()
        await self._server.wait_closed()

    # ---------- running a bot against it ----------

    async def start(self, bot: Bot, timeout: float = 5.0) -> Bot:
        """Run the bot against this server and wait until it is ready (menu sent, channel joined)."""
        bot.gateway = self.url
        if not bot.token.startswith("itw_"):
            bot.token = "itw_" + "0" * 40
        self._task = asyncio.ensure_future(bot.start())
        await asyncio.wait_for(self._ready.wait(), timeout)
        await asyncio.sleep(0.2)  # its on_ready and menu
        return bot

    # ---------- what the bot sent ----------

    async def next(self, op: str, timeout: float = 3.0, **match: Any) -> Dict[str, Any]:
        """The next thing the bot sends with this op (and these fields), not seen by next() before."""
        async def find() -> Dict[str, Any]:
            async with self._changed:
                while True:
                    for m in self.sent:
                        if m.get("op") == op and not m.get("_seen") and all(m.get(k) == v for k, v in match.items()):
                            m["_seen"] = True
                            return m
                    await self._changed.wait()
        return await asyncio.wait_for(find(), timeout)

    def said(self) -> List[str]:
        """Everything the bot wrote in channels (say)."""
        return [str(m.get("content")) for m in self.sent if m.get("op") == "say"]

    # ---------- playing the people ----------

    async def command(self, name: str, *, user: User = TESTER, channel: int = 1, final: bool = True,
                      **values: Any) -> Dict[str, Any]:
        """Use a command of the menu; returns the bot's answer (after a defer, the answer that follows)."""
        iid = next(self._ids)
        await self._event({"op": "command", "interaction": iid, "command": name, "channel": channel,
                           "user": _user(user), "values": {k: str(v) for k, v in values.items()}})
        return await self._answer(iid, final)

    async def click(self, msgid: int, action: str, value: str = "", *, user: User = TESTER, channel: int = 1,
                    final: bool = True) -> Dict[str, Any]:
        """Use a button or the choice under a bot message."""
        iid = next(self._ids)
        await self._event({"op": "action", "interaction": iid, "msgid": msgid, "channel": channel, "action": action,
                           "value": value, "user": _user(user)})
        return await self._answer(iid, final)

    async def press(self, dialog: Dict[str, Any], control: str, values: Optional[Dict[str, Any]] = None, *,
                    event: str = "button", user: User = TESTER, final: bool = True) -> Optional[Dict[str, Any]]:
        """An event in a dialog the bot opened (``dialog`` is its "dialog" message from next() or command())."""
        iid = next(self._ids)
        await self._event({"op": "dialog_event", "interaction": iid, "dialog": dialog["dialog"]["id"],
                           "instance": dialog["_instance"], "event": event, "control": control,
                           "values": values or {}, "user": _user(user), "channel": dialog.get("_channel", 1)})
        if event in ("close",):
            return None
        return await self._answer(iid, final)

    async def suggest(self, command: str, option: str, value: str, *, user: User = TESTER) -> List[Dict[str, str]]:
        iid = next(self._ids)
        await self._event({"op": "suggest", "interaction": iid, "command": command, "option": option, "value": value,
                           "user": _user(user)})
        answer = await self._answer(iid, True)
        return list(answer.get("choices") or [])

    async def form(self, form_id: int, values: Dict[str, Any], *, user: User = TESTER) -> Dict[str, Any]:
        iid = next(self._ids)
        await self._event({"op": "form", "interaction": iid, "form": form_id, "values": values, "user": _user(user),
                           "channel": 1})
        return await self._answer(iid, True)

    async def message(self, content: str, *, user: User = TESTER, channel: int = 1, mention: bool = True,
                      reply_to: int = 0) -> int:
        msgid = next(self._ids)
        await self._event({"op": "message", "channel": channel, "msgid": msgid, "user": _user(user), "content": content,
                           "reply_to": reply_to, "mention": mention})
        return msgid

    async def direct(self, content: str, *, user: User = TESTER) -> None:
        await self._event({"op": "direct", "user": _user(user), "content": content})

    async def member(self, *, user: User = TESTER, channel: int = 1, joined: bool = True) -> None:
        await self._event({"op": "member", "channel": channel, "user": _user(user), "joined": joined})

    async def sleep(self) -> None:
        """The server goes to sleep."""
        await self._send({"op": "server_sleeping", "server": self.server_id})

    async def wake(self) -> None:
        """The server wakes up: a new session, like a restart."""
        self._ready.clear()
        await self._send(self._ready_msg(resumed=False))
        await asyncio.sleep(0.2)

    # ---------- inside ----------

    async def _event(self, msg: Dict[str, Any]) -> None:
        await self._send({"server": self.server_id, "seq": next(self._seq), **msg})

    async def _send(self, msg: Dict[str, Any]) -> None:
        if self._ws is None:
            raise RuntimeError("no bot is connected; call start(bot) first")
        await self._ws.send(json.dumps(msg))

    async def _answer(self, iid: int, final: bool) -> Dict[str, Any]:
        try:
            first = await self.next_answer(iid, 3.0)
        except asyncio.TimeoutError:
            raise BotDidNotAnswer(f"the bot did not answer interaction {iid} within 3 seconds") from None
        if first.get("op") == "defer" and final:
            return await self.next_answer(iid, 15.0)
        return first

    async def next_answer(self, iid: int, timeout: float) -> Dict[str, Any]:
        async def find() -> Dict[str, Any]:
            async with self._changed:
                while True:
                    for m in self.sent:
                        if m.get("op") in ANSWER_OPS and m.get("interaction") == iid and not m.get("_answer_seen") \
                                and not m.get("_refused"):
                            m["_answer_seen"] = True
                            return m
                    await self._changed.wait()
        return await asyncio.wait_for(find(), timeout)

    def _ready_msg(self, resumed: bool) -> Dict[str, Any]:
        return {"op": "ready", "server": self.server_id, "protocol": 2, "session": "test-session",
                "heartbeat_interval": 30000, "resumed": resumed,
                "bot": {"name": self.bot_name, "userid": 4000, "channel": self.bot_channel, "everywhere": False},
                "audio": {"format": "s16le", "rate": 48000, "channels": 2},
                "intents": self.intents, "channels": self.channels}

    async def _conn(self, ws: Any) -> None:
        self._ws = ws
        await ws.send(json.dumps({"op": "hello", "gateway": 1, "heartbeat_interval": 30000}))
        async for text in ws:
            m = json.loads(text)
            op = m.get("op")
            if op == "heartbeat" and "server" not in m:
                await ws.send('{"op":"heartbeat_ack"}')
                continue
            if op == "identify":
                await ws.send(json.dumps({"op": "identified", "bot": {"id": 1, "name": self.bot_name},
                                          "servers": [{"server": self.server_id, "name": self.name, "awake": True}]}))
                await ws.send(json.dumps(self._ready_msg(resumed=False)))
                self._ready.set()
                continue
            answer = self._result(m)
            if answer.get("ok") is False:
                m["_refused"] = answer.get("error")  # a refused request answers nothing
            async with self._changed:
                self.sent.append(m)
                self._changed.notify_all()
            if m.get("ref") is not None:
                await ws.send(json.dumps({**answer, "server": self.server_id, "ref": m["ref"]}))

    def _result(self, m: Dict[str, Any]) -> Dict[str, Any]:
        op = m.get("op")
        if m.get("server") != self.server_id:
            return {"op": "result", "ok": False, "error": "unknown_server"}
        if op == "commands":
            self.menu = list(m.get("commands") or [])
            return {"op": "result", "ok": True, "count": len(self.menu)}
        if op in ("say", "respond") and not str(m.get("content", "")).strip() and not m.get("form"):
            return {"op": "result", "ok": False, "error": "empty"}
        if op == "say":
            return {"op": "result", "ok": True, "msgid": next(self._ids)}
        if op == "join":
            if m.get("everywhere"):
                return {"op": "result", "ok": False, "error": "not_approved"}
            target = m.get("channel")
            if target is None:
                target = next((c["id"] for c in self.channels if c["path"] == m.get("path")), None)
                if target is None:
                    return {"op": "result", "ok": False, "error": "no_channel"}
            self.bot_channel = int(target)
            return {"op": "result", "ok": True}
        if op == "audio" and int(m.get("channel") or self.bot_channel) != self.bot_channel:
            return {"op": "result", "ok": False, "error": "not_in_channel"}
        if op == "dialog":
            problem = _dialog_problem(m.get("dialog") or {})
            if problem:
                return {"op": "result", "ok": False, "error": "invalid_dialog", "message": problem}
            m["_instance"] = next(self._ids)
            m["_channel"] = 1
            return {"op": "result", "ok": True, "instance": m["_instance"]}
        if op == "allowed":
            return {"op": "result", "ok": True, "allowed": True}
        if op == "channel_info":
            return {"op": "result", "ok": True, "users": [], "name": "", "path": "/"}
        return {"op": "result", "ok": True}


def _user(u: User) -> Dict[str, Any]:
    return {"id": u.id, "nickname": u.nickname, "username": u.username, "level": u.level}


def _dialog_problem(d: Dict[str, Any]) -> str:
    count = 0

    def walk(controls: List[Dict[str, Any]]) -> str:
        nonlocal count
        for c in controls:
            count += 1
            if c.get("type") != "label" and not str(c.get("label", "")).replace("&", "").strip():
                return f"control {c.get('id')!r} has no label"
            if c.get("type") == "group":
                p = walk(c.get("controls") or [])
                if p:
                    return p
        return ""

    problem = walk(d.get("controls") or [])
    if problem:
        return problem
    if count > 100:
        return "more than 100 controls"
    if not str(d.get("title", "")).strip():
        return "no title"
    return ""


__all__ = ["TestServer", "TESTER", "BotDidNotAnswer"]
