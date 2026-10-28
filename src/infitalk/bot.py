"""The Bot: events, commands, dialogs and buttons, with decorators or a subclass.

Decorators, for small bots:

    bot = Bot()                                   # token from INFITALK_TOKEN

    @bot.command("echo", "Repeat what you write")
    async def echo(ctx, text: str):
        await ctx.respond(text, public=True)

    @bot.event
    async def on_message(msg):
        if msg.mentions_me:
            await msg.reply("Hi!")

    bot.run()

A subclass, for bigger ones (the same names, as methods):

    class MusicBot(Bot):
        async def on_ready(self, server): ...
        async def on_dialog_event(self, event): ...

Events: on_connect(servers), on_disconnect(code, reason), on_ready(server), on_server_sleeping(server),
on_server_added(server), on_server_removed(server), on_message(msg), on_direct(msg), on_member(event),
on_command(ctx) (commands without a handler), on_action(ctx), on_form(ctx), on_suggest(ctx),
on_dialog_event(event), on_error(error, where), on_raw(msg) (everything, as it came).
"""
from __future__ import annotations

import asyncio
import inspect
import logging
import os
import sys
from typing import Any, Awaitable, Callable, Dict, List, Optional, Sequence, TypeVar

from .commands import Command, Handler, menu
from .components import Field
from .context import ActionContext, CommandContext, DialogEvent, FormContext, Interaction, SuggestContext
from .errors import InfiTalkError, InvalidToken, Replaced
from .gateway import DEFAULT_GATEWAY, Connection
from .models import Channel, DirectMessage, MemberEvent, Message, Server

log = logging.getLogger("infitalk")
F = TypeVar("F", bound=Callable[..., Awaitable[Any]])

EVENTS = ("connect", "disconnect", "ready", "server_sleeping", "server_added", "server_removed", "message",
          "direct", "member", "command", "action", "form", "suggest", "dialog_event", "error", "raw")


class Bot:
    """An InfiTalk bot.

    token        the bot's token (itw_...); default: the INFITALK_TOKEN environment variable
    gateway      the gateway address; default wss://tt.infiartt.com/bot (INFITALK_GATEWAY)
    channel      the channel it goes to when a server is ready and it is in none ("/" = the main one;
                 None = stay out until join())
    auto_defer   send "working on it" by itself when a handler takes more than 2 seconds
    sync_commands  send the menu of registered commands to every server when it is ready
    """

    def __init__(self, token: Optional[str] = None, *, gateway: Optional[str] = None, channel: Optional[str] = "/",
                 auto_defer: bool = True, sync_commands: bool = True):
        self.token = token or os.environ.get("INFITALK_TOKEN", "")
        self.gateway = gateway or os.environ.get("INFITALK_GATEWAY", DEFAULT_GATEWAY)
        self.start_channel = channel
        self.auto_defer = auto_defer
        self.sync_commands = sync_commands
        self.name = ""
        self.id = 0
        self.servers: Dict[int, Server] = {}
        self.commands: Dict[str, Command] = {}
        self._listeners: Dict[str, List[Callable[..., Awaitable[Any]]]] = {e: [] for e in EVENTS}
        self._dialogs: Dict[str, Handler] = {}
        self._actions: Dict[str, Handler] = {}
        self._forms: Dict[str, Handler] = {}
        self._conn: Optional[Connection] = None
        self._tasks: "set[asyncio.Task]" = set()
        # commands and suggestions written as methods of a subclass (@command, @suggest)
        members = [m for _, m in inspect.getmembers(type(self)) if callable(m)]
        for member in members:
            spec = getattr(member, "__infitalk_command__", None)
            if spec is not None:
                self.add_command(Command(spec["name"], spec["description"], getattr(self, member.__name__),
                                         **spec["options"]))
        for member in members:
            target = getattr(member, "__infitalk_suggest__", None)
            if target is not None:
                cmd = self.commands.get(target[0])
                if cmd is None:
                    raise ValueError(f"@suggest names the command {target[0]!r}, which this bot does not have")
                cmd.suggest(target[1])(getattr(self, member.__name__))

    # ---------- registering ----------

    def event(self, fn: F) -> F:
        """Register a listener by its name: on_message, on_ready, on_command, ..."""
        name = fn.__name__[3:] if fn.__name__.startswith("on_") else fn.__name__
        if name not in EVENTS:
            raise ValueError(f"unknown event {fn.__name__!r}; known: " + ", ".join("on_" + e for e in EVENTS))
        self._listeners[name].append(fn)
        return fn

    def listen(self, name: str) -> Callable[[F], F]:
        """Register a listener for an event by name (several per event are fine)."""
        name = name[3:] if name.startswith("on_") else name

        def wrap(fn: F) -> F:
            if name not in EVENTS:
                raise ValueError(f"unknown event {name!r}")
            self._listeners[name].append(fn)
            return fn

        return wrap

    def command(self, name: str, description: str = "", *, category: str = "", permission: str = "everyone",
                dialog: bool = False, fields: Sequence[Field] = ()) -> Callable[[Handler], Command]:
        """A command of the menu; its fields come from the handler's parameters (see infitalk.commands)."""

        def wrap(fn: Handler) -> Command:
            cmd = Command(name, description or (inspect.getdoc(fn) or "").split("\n")[0], fn, category=category,
                          permission=permission, dialog=dialog, fields=fields)
            self.add_command(cmd)
            return cmd

        return wrap

    def add_command(self, cmd: Command) -> None:
        self.commands[cmd.name] = cmd

    def dialog(self, dialog_id: str) -> Callable[[F], F]:
        """Events of one dialog (by its id): the handler gets a DialogEvent."""

        def wrap(fn: F) -> F:
            self._dialogs[dialog_id] = fn
            return fn

        return wrap

    def action(self, action_id: str) -> Callable[[F], F]:
        """A button or choice (by its id) under a bot message: the handler gets an ActionContext."""

        def wrap(fn: F) -> F:
            self._actions[action_id.lower()] = fn
            return fn

        return wrap

    # ---------- running ----------

    def run(self) -> None:
        """Run until Ctrl+C (or until the token stops working)."""
        if not logging.getLogger().handlers:
            logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
        try:
            asyncio.run(self.start())
        except KeyboardInterrupt:
            pass
        except (InvalidToken, Replaced) as e:
            log.error("%s", e)
            sys.exit(1)

    async def start(self) -> None:
        if not self.token.startswith("itw_"):
            raise InvalidToken("invalid_token", "set the token (itw_...) with Bot(token=...) or INFITALK_TOKEN")
        self._conn = Connection(self.gateway, self.token, self._handle, self._closed)
        try:
            await self._conn.run()
        finally:
            for t in list(self._tasks):
                t.cancel()

    async def close(self) -> None:
        if self._conn is not None:
            await self._conn.stop()

    async def wait_until_connected(self) -> None:
        while self._conn is None:
            await asyncio.sleep(0.05)
        await self._conn.connected.wait()

    def server(self, server_id: int) -> Optional[Server]:
        return self.servers.get(int(server_id))

    # ---------- for Server and AudioPlayer ----------

    async def _request(self, server_id: int, op: str, fields: Dict[str, Any]) -> Dict[str, Any]:
        if self._conn is None:
            raise InfiTalkError("not_connected", "the bot is not running")
        return await self._conn.request({"server": server_id, "op": op, **fields})

    async def _send_fast(self, server_id: int, msg: Dict[str, Any]) -> None:
        if self._conn is None:
            raise InfiTalkError("not_connected", "the bot is not running")
        await self._conn.send({"server": server_id, **msg})

    # ---------- dispatching ----------

    def _spawn(self, coro: Awaitable[Any]) -> None:
        task = asyncio.ensure_future(coro)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _emit(self, name: str, *args: Any) -> None:
        """The subclass method on_<name> (when it has one) and every registered listener."""
        targets: List[Callable[..., Awaitable[Any]]] = []
        method = getattr(type(self), "on_" + name, None)
        if method is not None and method is not getattr(Bot, "on_" + name, None):
            targets.append(getattr(self, "on_" + name))
        targets.extend(self._listeners[name])
        for fn in targets:
            try:
                await fn(*args)
            except Exception as e:  # noqa: BLE001 - a bot keeps running
                if name == "error":
                    log.exception("on_error failed")
                else:
                    await self._report(e, f"on_{name}")

    async def _report(self, error: BaseException, where: str) -> None:
        if self._listeners["error"] or getattr(type(self), "on_error", None) is not Bot.on_error:
            await self._emit("error", error, where)
        else:
            log.error("%s: %s", where, error, exc_info=error)

    def _handles(self, name: str) -> bool:
        method = getattr(type(self), "on_" + name, None)
        return bool(self._listeners[name]) or (method is not None and method is not getattr(Bot, "on_" + name, None))

    def _server_of(self, msg: Dict[str, Any]) -> Optional[Server]:
        sid = msg.get("server")
        return self.servers.get(int(sid)) if sid is not None else None

    async def _closed(self, code: int, reason: str) -> None:
        for s in self.servers.values():
            s.ready = False
            for p in s._players.values():
                if p._task is not None:
                    p._task.cancel()
        await self._emit("disconnect", code, reason)

    async def _handle(self, msg: Dict[str, Any]) -> None:
        # the state changes here, in the order the events came; the handlers run as tasks
        server = self._apply(msg)
        self._spawn(self._route(msg, server))

    def _apply(self, msg: Dict[str, Any]) -> Optional[Server]:
        op = msg.get("op")
        server = self._server_of(msg)
        if op == "identified":
            self.id = int(msg["bot"]["id"])
            self.name = str(msg["bot"]["name"])
            known = {}
            for s in msg.get("servers", []):
                srv = self.servers.get(int(s["server"])) or Server(self, int(s["server"]))
                srv.name, srv.awake = str(s.get("name", "")), bool(s.get("awake"))
                known[srv.id] = srv
            self.servers = known
            log.info("signed in as %s; servers: %s", self.name,
                     ", ".join(f"{s.name} ({'awake' if s.awake else 'asleep'})" for s in known.values()) or "none")
        elif op == "ready" and server is not None:
            bot = msg.get("bot") or {}
            server.ready = server.awake = True
            server.session = str(msg.get("session") or "")
            server.user_id = int(bot.get("userid") or 0)
            server.channel_id = int(bot.get("channel") or 0)
            server.everywhere = bool(bot.get("everywhere"))
            server.intents = [str(i) for i in msg.get("intents") or []]
            server.channels = {c.id: c for c in (Channel.from_dict(x) for x in msg.get("channels") or [])}
        elif op == "server_sleeping" and server is not None:
            server.ready = server.awake = False
        elif op == "server_added":
            server = Server(self, int(msg["server"]), str(msg.get("name", "")), bool(msg.get("awake")))
            self.servers[server.id] = server
        elif op == "server_removed" and server is not None:
            self.servers.pop(server.id, None)
        return server

    async def _route(self, msg: Dict[str, Any], server: Optional[Server]) -> None:
        await self._emit("raw", msg)
        op = msg.get("op")
        if op == "identified":
            await self._emit("connect", list(self.servers.values()))
        elif op == "ready" and server is not None:
            await self._ready(server, msg)
        elif op in ("server_sleeping", "server_added", "server_removed") and server is not None:
            await self._emit(str(op), server)
        elif server is None:
            if op == "result" and msg.get("ok") is False:
                await self._report(InfiTalkError(str(msg.get("error")), "", msg), "gateway")
            elif op == "closed":
                log.warning("closed by the server: %s", msg.get("reason"))
        elif op == "message":
            await self._emit("message", Message(server, int(msg.get("channel") or 0), int(msg.get("msgid") or 0),
                                                _user(msg), str(msg.get("content") or ""),
                                                int(msg.get("reply_to") or 0), bool(msg.get("mention")), msg))
        elif op == "direct":
            await self._emit("direct", DirectMessage(server, _user(msg), str(msg.get("content") or ""), msg))
        elif op == "member":
            await self._emit("member", MemberEvent(server, int(msg.get("channel") or 0), _user(msg),
                                                   bool(msg.get("joined", True)), msg))
        elif op == "command":
            cmd = self.commands.get(str(msg.get("command") or ""))
            ctx = CommandContext(server, msg, cmd)
            if cmd and cmd.handler:
                await self._interaction(ctx, self._run_command(ctx))
            elif self._handles("command"):
                await self._interaction(ctx, self._emit("command", ctx))
            else:
                await ctx.respond(f"This bot has no command {ctx.name!r} any more.")
        elif op == "suggest":
            await self._suggest(SuggestContext(server, msg))
        elif op == "action":
            ctx = ActionContext(server, msg)
            fn = self._actions.get(ctx.action)
            await self._interaction(ctx, fn(ctx) if fn else self._emit("action", ctx))
        elif op == "form":
            ctx = FormContext(server, msg)
            await self._interaction(ctx, self._emit("form", ctx))
        elif op == "dialog_event":
            ev = DialogEvent(server, msg)
            fn = self._dialogs.get(ev.dialog_id)
            await self._interaction(ev, fn(ev) if fn else self._emit("dialog_event", ev))
        elif op == "result" and msg.get("ok") is False:
            await self._report(InfiTalkError(str(msg.get("error")), f"server {server.id}", msg), "server")
        elif op == "closed":
            log.warning("server %s closed the bot: %s", server.id, msg.get("reason"))

    async def _ready(self, server: Server, msg: Dict[str, Any]) -> None:
        resumed = bool(msg.get("resumed"))
        log.info("server %s (%s) ready%s", server.id, server.name, " (resumed)" if resumed else "")
        if self.sync_commands and self.commands and not resumed:
            try:
                await server.request("commands", commands=menu(list(self.commands.values())))
            except InfiTalkError as e:
                await self._report(e, f"sending the menu to server {server.id}")
        if self.start_channel and not resumed and not server.channel_id and not server.everywhere:
            try:
                await server.join(self.start_channel)
                ch = server.channel(self.start_channel)
                server.channel_id = ch.id if ch else server.channel_id
            except InfiTalkError as e:
                await self._report(e, f"joining {self.start_channel} on server {server.id}")
        await self._emit("ready", server)

    async def _run_command(self, ctx: CommandContext) -> None:
        cmd = ctx.command
        assert cmd is not None and cmd.handler is not None
        try:
            args = cmd.arguments(ctx.values)
        except ValueError as e:
            await ctx.respond(str(e))
            return
        await cmd.handler(ctx, **args)

    async def _suggest(self, ctx: SuggestContext) -> None:
        cmd = self.commands.get(ctx.command)
        fn = cmd.suggesters.get(ctx.option) if cmd else None
        try:
            if fn is None:
                await self._emit("suggest", ctx)
                return
            choices = await fn(ctx, ctx.value)
            if not ctx.answered:
                await ctx.suggest(choices or [])
        except Exception as e:  # noqa: BLE001
            await self._report(e, f"suggestions for {ctx.command}.{ctx.option}")

    async def _interaction(self, ctx: Interaction, work: Awaitable[Any]) -> None:
        """Run a handler; "working on it" after 2 seconds; a short apology when it fails unanswered."""
        timer = None
        if self.auto_defer and not ctx.answered:
            async def later() -> None:
                await asyncio.sleep(2.0)
                if not ctx.answered:
                    try:
                        await ctx.defer()
                    except InfiTalkError:
                        pass
            timer = asyncio.ensure_future(later())
        try:
            await work
        except Exception as e:  # noqa: BLE001
            await self._report(e, f"{type(ctx).__name__} {getattr(ctx, 'name', '') or ''}".strip())
            if not ctx.answered:
                try:
                    await ctx.respond("Something went wrong. Please try again later.")
                except InfiTalkError:
                    pass
        finally:
            if timer is not None:
                timer.cancel()

    # ---------- default events (a subclass overrides them) ----------

    async def on_error(self, error: BaseException, where: str) -> None:
        log.error("%s: %s", where, error, exc_info=error)


def _user(msg: Dict[str, Any]) -> "Any":
    from .models import User
    return User.from_dict(msg.get("user"))


def command(name: str, description: str = "", *, category: str = "", permission: str = "everyone",
            dialog: bool = False) -> Callable[[F], F]:
    """A command as a method of a Bot subclass:

        class MyBot(Bot):
            @command("ping", "Answer pong")
            async def ping(self, ctx): await ctx.respond("pong")
    """

    def wrap(fn: F) -> F:
        fn.__infitalk_command__ = {"name": name, "description": description or (inspect.getdoc(fn) or "").split("\n")[0],
                                   "options": {"category": category, "permission": permission, "dialog": dialog}}
        return fn

    return wrap


def suggest(command_name: str, field: str) -> Callable[[F], F]:
    """Suggestions for a field of a command, as a method of a Bot subclass; it returns the choices:

        @suggest("play", "song")
        async def songs(self, ctx, value): return ["Kangen", "Separuh Nafas"]
    """

    def wrap(fn: F) -> F:
        fn.__infitalk_suggest__ = (command_name, field)
        return fn

    return wrap
