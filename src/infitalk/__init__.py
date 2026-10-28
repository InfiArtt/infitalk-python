"""InfiTalk bots in Python, by InfiArtt.

    from infitalk import Bot

    bot = Bot()  # token from INFITALK_TOKEN

    @bot.command("echo", "Repeat what you write")
    async def echo(ctx, text: str):
        await ctx.respond(text, public=True)

    bot.run()

Docs: https://infiartt.com/infitalk/developers
"""
from .audio import AudioPlayer, tone_pcm
from .bot import EVENTS, Bot, command, suggest
from .commands import Command
from .components import (ActionButton, Actions, ActionSelect, Button, Checkbox, Choice, Control, Dialog, Field,
                         Form, Group, Label, ListBox, NumberInput, RadioGroup, Select, Slider, TextInput)
from .context import (ActionContext, CommandContext, DialogEvent, DialogHandle, FormContext, Interaction,
                      SuggestContext)
from .errors import (InfiTalkError, InvalidComponent, InvalidToken, MissingPermission, RateLimited, Replaced,
                     ServerAsleep)
from .gateway import DEFAULT_GATEWAY
from .models import Channel, DirectMessage, MemberEvent, Message, SentMessage, Server, User

__version__ = "0.1.0"

__all__ = [
    "Bot", "command", "suggest", "EVENTS", "Command", "DEFAULT_GATEWAY", "__version__",
    "Server", "User", "Channel", "Message", "DirectMessage", "MemberEvent", "SentMessage",
    "Interaction", "CommandContext", "ActionContext", "FormContext", "SuggestContext", "DialogEvent", "DialogHandle",
    "Dialog", "Control", "Label", "TextInput", "NumberInput", "Slider", "Checkbox", "RadioGroup", "Select",
    "ListBox", "Button", "Group", "Choice", "Actions", "ActionButton", "ActionSelect", "Field", "Form",
    "AudioPlayer", "tone_pcm",
    "InfiTalkError", "MissingPermission", "RateLimited", "ServerAsleep", "InvalidToken", "Replaced",
    "InvalidComponent",
]
