"""Dialogs, message buttons and forms, built from Python objects.

InfiTalk shows them as real Windows controls, so they work with NVDA and JAWS. Every control except
:class:`Label` needs a label; an ``&`` in a label gives its Alt letter (the client picks one when it is
missing or taken). :meth:`Dialog.validate` checks the same limits as the server, so mistakes show up while
you write the bot, not when someone opens the dialog.

    Dialog("eq", "Equalizer", [
        Slider("bass", "&Bass", min=-12, max=12, value=0, unit="dB", notify=True),
        Select("preset", "&Preset", [Choice("flat", "Flat"), Choice("pop", "Pop")]),
        Button("save", "&Save", default=True),
        Button("close", "Close", close=True),
    ], focus="bass")
"""
from __future__ import annotations

import json
import re
from typing import Any, Dict, Iterable, List, Optional, Sequence, Union

from .errors import InvalidComponent

MAX_CONTROLS = 100
MAX_OPTIONS = 200
MAX_JSON = 64 * 1024
_ID = re.compile(r"^[A-Za-z0-9_.-]{1,32}$")


class Choice:
    """One option of a radio group, select, list, message select or choice field."""

    def __init__(self, value: str, label: Optional[str] = None):
        self.value = str(value)
        self.label = str(label if label is not None else value)

    def to_dict(self) -> Dict[str, str]:
        return {"value": self.value, "label": self.label}


ChoiceLike = Union[Choice, str]


def _choices(items: Iterable[ChoiceLike]) -> List[Choice]:
    return [c if isinstance(c, Choice) else Choice(c) for c in items]


class Control:
    """Base of every dialog control."""

    type = ""

    def __init__(self, id: str, label: str = "", *, help: str = "", required: bool = False,
                 disabled: bool = False, notify: bool = False):
        self.id = id
        self.label = label
        self.help = help
        self.required = required
        self.disabled = disabled
        self.notify = notify  # send a "change" event as soon as the value changes

    def _base(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {"type": self.type, "id": self.id}
        if self.label:
            d["label"] = self.label
        if self.help:
            d["help"] = self.help
        for key in ("required", "disabled", "notify"):
            if getattr(self, key):
                d[key] = True
        return d

    def to_dict(self) -> Dict[str, Any]:
        return self._base()

    def _check(self, where: str) -> int:
        if not _ID.match(self.id or ""):
            raise InvalidComponent(f"{where}: control id {self.id!r} must be 1-32 letters, digits, _ . or -")
        if self.type != "label" and not str(self.label).replace("&", "").strip():
            raise InvalidComponent(f"{where}: control {self.id!r} needs a label (screen readers read it)")
        return 1


class Label(Control):
    """Text in the dialog, read by screen readers. Needs no label of its own."""

    type = "label"

    _next = 0

    def __init__(self, text: str, id: str = "", **kw: Any):
        if not id:
            Label._next += 1
            id = f"label{Label._next}"
        super().__init__(id, "", **kw)
        self.text = text

    def to_dict(self) -> Dict[str, Any]:
        return {**self._base(), "text": self.text}


class TextInput(Control):
    type = "text"

    def __init__(self, id: str, label: str, value: str = "", *, multiline: bool = False,
                 maxlength: Optional[int] = None, placeholder: str = "", **kw: Any):
        super().__init__(id, label, **kw)
        self.value, self.multiline, self.maxlength, self.placeholder = value, multiline, maxlength, placeholder

    def to_dict(self) -> Dict[str, Any]:
        d = self._base()
        if self.value:
            d["value"] = self.value
        if self.multiline:
            d["multiline"] = True
        if self.maxlength:
            d["maxlength"] = self.maxlength
        if self.placeholder:
            d["placeholder"] = self.placeholder
        return d


class _Ranged(Control):
    def __init__(self, id: str, label: str, value: Optional[float] = None, *, min: Optional[float] = None,
                 max: Optional[float] = None, step: Optional[float] = None, unit: str = "", **kw: Any):
        super().__init__(id, label, **kw)
        self.value, self.min, self.max, self.step, self.unit = value, min, max, step, unit

    def to_dict(self) -> Dict[str, Any]:
        d = self._base()
        for key in ("value", "min", "max", "step"):
            if getattr(self, key) is not None:
                d[key] = getattr(self, key)
        if self.unit:
            d["unit"] = self.unit
        return d


class NumberInput(_Ranged):
    type = "number"


class Slider(_Ranged):
    type = "slider"


class Checkbox(Control):
    type = "checkbox"

    def __init__(self, id: str, label: str, value: bool = False, **kw: Any):
        super().__init__(id, label, **kw)
        self.value = value

    def to_dict(self) -> Dict[str, Any]:
        return {**self._base(), "value": bool(self.value)}


class _WithOptions(Control):
    key = "options"

    def __init__(self, id: str, label: str, options: Sequence[ChoiceLike], value: Optional[str] = None, **kw: Any):
        super().__init__(id, label, **kw)
        self.options = _choices(options)
        self.value = value

    def to_dict(self) -> Dict[str, Any]:
        d = {**self._base(), self.key: [o.to_dict() for o in self.options]}
        if self.value is not None:
            d["value"] = self.value
        return d

    def _check(self, where: str) -> int:
        n = super()._check(where)
        if len(self.options) > MAX_OPTIONS:
            raise InvalidComponent(f"{where}: {self.id!r} has {len(self.options)} options; at most {MAX_OPTIONS}")
        return n


class RadioGroup(_WithOptions):
    type = "radio"


class Select(_WithOptions):
    type = "select"


class ListBox(_WithOptions):
    """A list; ``multi`` lets people pick several, ``activate`` names the button Enter presses."""

    type = "list"
    key = "items"

    def __init__(self, id: str, label: str, items: Sequence[ChoiceLike], value: Optional[str] = None, *,
                 multi: bool = False, activate: str = "", **kw: Any):
        super().__init__(id, label, items, value, **kw)
        self.multi, self.activate = multi, activate

    def to_dict(self) -> Dict[str, Any]:
        d = super().to_dict()
        if self.multi:
            d["multi"] = True
        if self.activate:
            d["activate"] = self.activate
        return d


class Button(Control):
    """``default``: Enter presses it; ``close``: it closes the dialog (no answer needed)."""

    type = "button"

    def __init__(self, id: str, label: str, *, default: bool = False, close: bool = False, **kw: Any):
        super().__init__(id, label, **kw)
        self.default, self.close = default, close

    def to_dict(self) -> Dict[str, Any]:
        d = self._base()
        if self.default:
            d["default"] = True
        if self.close:
            d["close"] = True
        return d


class Group(Control):
    """Controls under one heading."""

    type = "group"

    def __init__(self, id: str, label: str, controls: Sequence[Control], **kw: Any):
        super().__init__(id, label, **kw)
        self.controls = list(controls)

    def to_dict(self) -> Dict[str, Any]:
        return {**self._base(), "controls": [c.to_dict() for c in self.controls]}

    def _check(self, where: str) -> int:
        return super()._check(where) + sum(c._check(where) for c in self.controls)


def _count(controls: Sequence[Control], where: str) -> None:
    total = sum(c._check(where) for c in controls)
    if total > MAX_CONTROLS:
        raise InvalidComponent(f"{where}: {total} controls; at most {MAX_CONTROLS}")


class Dialog:
    """A dialog. The same ``id`` for the same person replaces the dialog that is open."""

    def __init__(self, id: str, title: str, controls: Sequence[Control], *, focus: str = ""):
        self.id, self.title, self.controls, self.focus = id, title, list(controls), focus

    def validate(self) -> "Dialog":
        if not _ID.match(self.id or ""):
            raise InvalidComponent(f"dialog id {self.id!r} must be 1-32 letters, digits, _ . or -")
        if not self.title.strip():
            raise InvalidComponent(f"dialog {self.id!r} needs a title")
        _count(self.controls, f"dialog {self.id!r}")
        size = len(json.dumps(self.to_dict(validate=False)))
        if size > MAX_JSON:
            raise InvalidComponent(f"dialog {self.id!r} is {size} bytes; at most {MAX_JSON}")
        return self

    def to_dict(self, validate: bool = True) -> Dict[str, Any]:
        if validate:
            self.validate()
        d: Dict[str, Any] = {"id": self.id, "title": self.title, "controls": [c.to_dict() for c in self.controls]}
        if self.focus:
            d["focus"] = self.focus
        return d


def controls_to_list(controls: Sequence[Control], where: str = "dialog update") -> List[Dict[str, Any]]:
    _count(controls, where)
    return [c.to_dict() for c in controls]


# ---------- buttons and a choice on a message ----------

class ActionButton:
    def __init__(self, id: str, label: str):
        self.id, self.label = id, label

    def to_dict(self) -> Dict[str, str]:
        return {"id": self.id, "label": self.label}


class ActionSelect:
    def __init__(self, id: str, label: str, options: Sequence[ChoiceLike]):
        self.id, self.label, self.options = id, label, _choices(options)

    def to_dict(self) -> Dict[str, Any]:
        return {"id": self.id, "label": self.label, "options": [o.to_dict() for o in self.options]}


class Actions:
    """Up to 5 buttons and one choice (up to 25 options) under a bot message (Ctrl+D in InfiTalk)."""

    def __init__(self, buttons: Sequence[ActionButton] = (), select: Optional[ActionSelect] = None):
        if len(buttons) > 5:
            raise InvalidComponent("a message has at most 5 buttons")
        if select is not None and len(select.options) > 25:
            raise InvalidComponent("a message choice has at most 25 options")
        for b in buttons:
            if not b.label.strip():
                raise InvalidComponent(f"button {b.id!r} needs a label")
        self.buttons, self.select = list(buttons), select

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {}
        if self.buttons:
            d["buttons"] = [b.to_dict() for b in self.buttons]
        if self.select is not None:
            d["select"] = self.select.to_dict()
        return d


# ---------- fields of commands and forms ----------

FIELD_TYPES = ("text", "number", "choice")


class Field:
    """A field of a command or a form. As a default value of a command parameter it sets its label and more:

        @bot.command("play", "Play a song")
        async def play(ctx, song: str = Field(label="Song or link", suggest=True)): ...
    """

    def __init__(self, name: str = "", label: str = "", type: str = "text", *, required: Optional[bool] = None,
                 choices: Sequence[ChoiceLike] = (), suggest: bool = False, default: Any = None):
        if type not in FIELD_TYPES:
            raise InvalidComponent(f"field type {type!r} must be one of {FIELD_TYPES}")
        self.name, self.label, self.type = name, label, type
        self.required = required
        self.choices = [c.value if isinstance(c, Choice) else str(c) for c in choices]
        self.suggest, self.default = suggest, default

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {"name": self.name, "label": self.label or self.name.replace("_", " ").capitalize(),
                             "type": self.type}
        if self.required:
            d["required"] = True
        if self.choices:
            d["choices"] = self.choices
        if self.suggest:
            d["suggest"] = True
        return d


class Form:
    """A small form sent with an answer (``ctx.respond(..., form=Form(...))``); filled in, it comes back as on_form."""

    def __init__(self, title: str, fields: Sequence[Field]):
        self.title, self.fields = title, list(fields)

    def to_dict(self) -> Dict[str, Any]:
        for f in self.fields:
            if not f.name:
                raise InvalidComponent("every form field needs a name")
        return {"title": self.title, "fields": [f.to_dict() for f in self.fields]}
