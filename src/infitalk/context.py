"""Interactions: someone used the bot's menu, a button, a form, a dialog, or is typing in a field.

Every interaction must be answered within 3 seconds (respond, defer, dialog or an update of a dialog), else
the person hears that the bot did not answer. The SDK sends ``defer`` by itself after 2 seconds when a
handler is still busy (``Bot(auto_defer=False)`` turns that off); after a defer the answer may come for
15 minutes.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict, List, Optional, Sequence, Union

from .components import Actions, Choice, ChoiceLike, Control, Dialog, Form, controls_to_list
from .models import SentMessage, Server, User

if TYPE_CHECKING:  # pragma: no cover
    from .commands import Command


class Interaction:
    """Base of every interaction: ``server``, ``user`` (with ``level``), ``channel`` and its number ``id``."""

    def __init__(self, server: Server, raw: Dict[str, Any]):
        self.server = server
        self.raw = raw
        self.id = int(raw.get("interaction") or 0)
        self.user = User.from_dict(raw.get("user"))
        self.channel = int(raw.get("channel") or 0)
        self.answered = False
        self.deferred = False

    async def respond(self, content: str = "", *, public: bool = False, form: Optional[Form] = None) -> None:
        """An answer for this person only, or for the channel with ``public=True``; may carry a form."""
        fields: Dict[str, Any] = {"interaction": self.id, "content": content}
        if public:
            fields["public"] = True
        if form is not None:
            fields["form"] = form.to_dict()
        self.answered = True
        await self.server.request("respond", **fields)

    reply = respond

    async def defer(self) -> None:
        """"Working on it": the person hears that the bot is working; answer within 15 minutes."""
        if self.answered or self.deferred:
            return
        self.deferred = True
        await self.server.request("defer", interaction=self.id)

    async def dialog(self, dialog: Dialog) -> "DialogHandle":
        """Open a dialog for this person. The same dialog id replaces the open one."""
        self.answered = True
        answer = await self.server.request("dialog", interaction=self.id, dialog=dialog.to_dict())
        return DialogHandle(self.server, int(answer.get("instance") or 0), dialog.id)

    async def say(self, content: str, *, actions: Optional[Actions] = None) -> SentMessage:
        """A message in the channel that also answers this interaction."""
        self.answered = True
        fields: Dict[str, Any] = {"content": content, "channel": self.channel, "interaction": self.id}
        if actions is not None:
            fields["actions"] = actions.to_dict()
        answer = await self.server.request("say", **fields)
        return SentMessage(self.server, self.channel, int(answer.get("msgid") or 0))


class CommandContext(Interaction):
    """Someone used a command of the menu. ``values`` holds the fields as they were sent (text)."""

    def __init__(self, server: Server, raw: Dict[str, Any], command: Optional["Command"] = None):
        super().__init__(server, raw)
        self.name = str(raw.get("command") or "")
        self.values: Dict[str, Any] = dict(raw.get("values") or {})
        self.command = command


class ActionContext(Interaction):
    """A button or the choice under a bot message was used: ``action`` (its id) and ``value``."""

    def __init__(self, server: Server, raw: Dict[str, Any]):
        super().__init__(server, raw)
        self.message = SentMessage(server, self.channel, int(raw.get("msgid") or 0))
        self.action = str(raw.get("action") or "")
        self.value = str(raw.get("value") or "")

    async def edit_message(self, content: str, *, actions: Optional[Actions] = None) -> None:
        """Change the message the button is on; this answers the interaction."""
        self.answered = True
        await self.message.edit(content, actions=actions, interaction=self.id)


class FormContext(Interaction):
    """A form the bot sent was filled in: ``values``."""

    def __init__(self, server: Server, raw: Dict[str, Any]):
        super().__init__(server, raw)
        self.form = int(raw.get("form") or 0)
        self.values: Dict[str, Any] = dict(raw.get("values") or {})


class SuggestContext(Interaction):
    """Someone is typing in a field with ``suggest``: answer with up to 25 choices."""

    def __init__(self, server: Server, raw: Dict[str, Any]):
        super().__init__(server, raw)
        self.command = str(raw.get("command") or "")
        self.option = str(raw.get("option") or "")
        self.value = str(raw.get("value") or "")

    async def suggest(self, choices: Sequence[ChoiceLike]) -> None:
        self.answered = True
        items = [c if isinstance(c, Choice) else Choice(c) for c in list(choices)[:25]]
        await self.server.request("suggestions", interaction=self.id, choices=[c.to_dict() for c in items])


class DialogHandle:
    """An open dialog of one person: update it in place or close it."""

    def __init__(self, server: Server, instance: int, dialog_id: str = ""):
        self.server, self.instance, self.dialog_id = server, instance, dialog_id

    async def update(self, controls: Sequence[Control] = (), *, remove: Sequence[str] = (), title: str = "",
                     focus: str = "", announce: str = "", interaction: Optional[int] = None) -> None:
        """Controls with an id that is there replace it, others are added at the end; ``announce`` is read
        by the screen reader."""
        fields: Dict[str, Any] = {"instance": self.instance}
        if controls:
            fields["controls"] = controls_to_list(controls)
        if remove:
            fields["remove"] = list(remove)
        if title:
            fields["title"] = title
        if focus:
            fields["focus"] = focus
        if announce:
            fields["announce"] = announce
        if interaction:
            fields["interaction"] = interaction
        await self.server.request("dialog_update", **fields)

    async def close(self) -> None:
        await self.server.request("dialog_close", instance=self.instance)


class DialogEvent(Interaction):
    """Something happened in a dialog: ``event`` is button, change, submit or close; ``control`` and ``values``.
    A close after 15 idle minutes has ``reason`` "expired" and needs no answer."""

    def __init__(self, server: Server, raw: Dict[str, Any]):
        super().__init__(server, raw)
        self.dialog_id = str(raw.get("dialog") or "")
        self.instance = int(raw.get("instance") or 0)
        self.event = str(raw.get("event") or "")
        self.control = str(raw.get("control") or "")
        self.values: Dict[str, Any] = dict(raw.get("values") or {})
        self.reason = str(raw.get("reason") or "")
        self.handle = DialogHandle(server, self.instance, self.dialog_id)
        if self.event == "close" or self.id == 0:
            self.answered = True  # nothing to answer

    async def update(self, controls: Sequence[Control] = (), **kw: Any) -> None:
        """Change the dialog; this answers the event."""
        self.answered = True
        await self.handle.update(controls, interaction=self.id, **kw)

    async def close(self) -> None:
        self.answered = True
        await self.handle.close()

    def value(self, control: str, default: Any = None) -> Any:
        return self.values.get(control, default)


AnyInteraction = Union[CommandContext, ActionContext, FormContext, SuggestContext, DialogEvent]
__all__: List[str] = ["Interaction", "CommandContext", "ActionContext", "FormContext", "SuggestContext",
                      "DialogEvent", "DialogHandle"]
