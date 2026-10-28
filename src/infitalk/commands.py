"""Commands of the bot's menu (Ctrl+Shift+P in InfiTalk).

The fields come from the handler's parameters:

    @bot.command("play", "Play a song or a link", category="Music")
    async def play(ctx, song: str = Field(label="Song or link", suggest=True), volume: int = 50): ...

``str`` is a text field, ``int``/``float`` a number, ``Literal["a", "b"]`` a choice; a parameter without a
default is required. Values arrive converted to the annotated type. ``permission`` says who may use it:
"everyone" (default), "moderator" (and admins) or "admin"; server admins can change that on infiartt.com.
"""
from __future__ import annotations

import inspect
import re
import typing
from typing import Any, Awaitable, Callable, Dict, List, Optional, Sequence

from .components import Field
from .errors import InvalidComponent

MAX_COMMANDS = 250
PERMISSIONS = ("everyone", "moderator", "admin")
_NAME = re.compile(r"^[a-z0-9_-]{1,32}$")

Handler = Callable[..., Awaitable[Any]]


def _field_for(param: inspect.Parameter, hint: Any) -> Field:
    given = param.default if isinstance(param.default, Field) else None
    f = given if given is not None else Field()
    f.name = param.name
    origin = typing.get_origin(hint)
    if origin is typing.Union:  # Optional[X]
        args = [a for a in typing.get_args(hint) if a is not type(None)]
        hint = args[0] if args else str
        origin = typing.get_origin(hint)
        if f.required is None:
            f.required = False
    if origin is typing.Literal:
        f.type = "choice"
        f.choices = [str(a) for a in typing.get_args(hint)]
    elif hint in (int, float) and f.type == "text":
        f.type = "number"
    if f.required is None:
        # required unless it has a default: a plain one, or Field(default=...)
        if given is not None:
            f.required = given.default is None
        else:
            f.required = param.default is inspect.Parameter.empty
    return f


def _convert(value: Any, hint: Any, name: str) -> Any:
    if value is None or value == "":
        return None
    if typing.get_origin(hint) is typing.Union:
        args = [a for a in typing.get_args(hint) if a is not type(None)]
        hint = args[0] if args else str
    try:
        if hint is int:
            return int(float(value))
        if hint is float:
            return float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{name}: {value!r} is not a number") from None
    return str(value) if hint in (str, inspect.Parameter.empty) else value


class Command:
    def __init__(self, name: str, description: str, handler: Optional[Handler] = None, *, category: str = "",
                 permission: str = "everyone", dialog: bool = False, fields: Sequence[Field] = ()):
        if not _NAME.match(name):
            raise InvalidComponent(f"command name {name!r} must be 1-32 lowercase letters, digits, _ or -")
        if permission not in PERMISSIONS:
            raise InvalidComponent(f"permission {permission!r} must be one of {PERMISSIONS}")
        self.name, self.description, self.category = name, description, category
        self.permission, self.dialog = permission, dialog
        self.handler = handler
        self.fields: List[Field] = list(fields)
        self.hints: Dict[str, Any] = {}
        self.defaults: Dict[str, Any] = {}
        self.suggesters: Dict[str, Handler] = {}
        if handler is not None and not fields:
            self._read_signature(handler)

    def _read_signature(self, handler: Handler) -> None:
        try:
            hints = typing.get_type_hints(handler)
        except Exception:  # pragma: no cover - unusual annotations
            hints = {}
        params = list(inspect.signature(handler).parameters.values())[1:]  # after ctx
        for p in params:
            if p.kind in (p.VAR_POSITIONAL, p.VAR_KEYWORD):
                continue
            hint = hints.get(p.name, str)
            self.hints[p.name] = hint
            f = _field_for(p, hint)
            self.fields.append(f)
            if isinstance(p.default, Field):
                self.defaults[p.name] = p.default.default
            elif p.default is not inspect.Parameter.empty:
                self.defaults[p.name] = p.default

    def suggest(self, field: str) -> Callable[[Handler], Handler]:
        """Suggestions while someone types in a field: the handler gets (ctx, value) and returns choices.

            @play.suggest("song")
            async def songs(ctx, value): return ["Kangen", "Separuh Nafas"]
        """
        names = {f.name for f in self.fields}
        if field not in names:
            raise InvalidComponent(f"command {self.name!r} has no field {field!r}")

        def wrap(fn: Handler) -> Handler:
            for f in self.fields:
                if f.name == field:
                    f.suggest = True
            self.suggesters[field] = fn
            return fn

        return wrap

    def arguments(self, values: Dict[str, Any]) -> Dict[str, Any]:
        out: Dict[str, Any] = {}
        for f in self.fields:
            v = _convert(values.get(f.name), self.hints.get(f.name, str), f.name)
            out[f.name] = self.defaults.get(f.name) if v is None else v
        return out

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {"name": self.name, "description": self.description}
        if self.category:
            d["category"] = self.category
        if self.permission != "everyone":
            d["permission"] = self.permission
        if self.dialog:
            d["dialog"] = True
        if self.fields:
            d["options"] = [f.to_dict() for f in self.fields]
        return d

    def __repr__(self) -> str:
        return f"<Command {self.name}>"


def menu(commands: Sequence[Command]) -> List[Dict[str, Any]]:
    if len(commands) > MAX_COMMANDS:
        raise InvalidComponent(f"{len(commands)} commands; at most {MAX_COMMANDS}")
    return [c.to_dict() for c in commands]
