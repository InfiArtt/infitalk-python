# infitalk: InfiTalk bots in Python

Make bots for [InfiTalk](https://infiartt.com/dev-center/infitalk-bots), the accessible voice chat of InfiArtt:
commands in the bot menu, dialogs that work with NVDA and JAWS, buttons under messages, forms, suggestions
while typing, and audio. One connection serves every server your bot was added to.

By InfiArtt. MIT license.

```
pip install infitalk
```

Python 3.10 or newer. The only package it needs is `websockets`.

## A first bot

1. Make a bot in your [developer space](https://infiartt.com/dev-center/me) on the InfiArtt Developer Center
   and copy its token (`itw_...`).
   The token is shown once; keep it secret.
2. Add the bot to a server you manage ("Add to a server" on the same page).
3. Run this with the token in `INFITALK_TOKEN`:

```python
from infitalk import Bot, Field

bot = Bot()  # the token comes from INFITALK_TOKEN

@bot.command("echo", "Repeat what you write", category="Fun")
async def echo(ctx, text: str = Field(label="Text")):
    await ctx.respond(text, public=True)

@bot.event
async def on_message(msg):
    if msg.mentions_me:
        await msg.reply(f"Hi {msg.user}!")

bot.run()
```

```
INFITALK_TOKEN=itw_... python bot.py
$env:INFITALK_TOKEN="itw_..."; python bot.py        # PowerShell
```

In InfiTalk, Ctrl+Shift+P opens the menu of the bots in your channel. The bot goes to the main channel
of each server when it is ready (`Bot(channel=None)` keeps it out until `server.join(...)`).

## Two ways to write a bot

Decorators, as above, for small bots. A class for bigger ones; the same event names become methods:

```python
from infitalk import Bot, command, suggest

class MusicBot(Bot):
    async def on_ready(self, server):
        await server.status("Ready")

    @command("play", "Play a song", category="Music")
    async def play(self, ctx, song: str):
        await ctx.respond(f"Playing {song}", public=True)

    @suggest("play", "song")
    async def songs(self, ctx, value):
        return ["Kangen", "Separuh Nafas"]

MusicBot().run()
```

## Commands

Fields come from the parameters: `str` is text, `int` and `float` are numbers, `Literal["a", "b"]` is a
choice, and a parameter without a default is required. Values arrive converted to the type.

```python
from typing import Literal
from infitalk import Field

@bot.command("play", "Play a song", category="Music", permission="moderator")
async def play(ctx, song: str = Field(label="Song or link"), mode: Literal["once", "loop"] = "once"):
    ...

@play.suggest("song")                 # suggestions while typing
async def song_names(ctx, value):
    return [s for s in SONGS if value.lower() in s.lower()]
```

`permission` is who may use it: `everyone` (the default), `moderator` (and admins) or `admin`. Server admins
can change that on infiartt.com, and people only see the commands they may use. `ctx.user.level` tells you
theirs.

**Answer within 3 seconds.** Every command, button and dialog event must be answered with `ctx.respond`,
`ctx.dialog`, `ctx.say`, `event.update` or `ctx.defer`, else the person hears that your bot did not answer.
The SDK sends "working on it" (`defer`) by itself when a handler takes longer than 2 seconds; you then have
15 minutes. When a handler fails before answering, the person hears a short apology and your `on_error` runs.

## Dialogs

```python
from infitalk import Dialog, Slider, Select, Choice, Button, DialogEvent

@bot.command("eq", "Equalizer", dialog=True)
async def eq(ctx):
    await ctx.dialog(Dialog("eq", "Equalizer", [
        Slider("bass", "&Bass", 0, min=-12, max=12, unit="dB", notify=True),
        Select("preset", "&Preset", [Choice("flat", "Flat"), Choice("pop", "Pop")]),
        Button("save", "&Save", default=True),
        Button("close", "Close", close=True),
    ], focus="bass"))

@bot.dialog("eq")
async def eq_events(event: DialogEvent):
    if event.control == "save":
        await event.update(announce=f"Bass {event.value('bass')} dB")
```

Controls: `Label`, `TextInput`, `NumberInput`, `Slider`, `Checkbox`, `RadioGroup`, `Select`, `ListBox`,
`Button`, `Group`. Every control except `Label` needs a label; `&` marks its Alt letter. The SDK checks the
same limits as the server (100 controls, 200 options, 64 KB) before sending.

## Buttons under a message

```python
from infitalk import Actions, ActionButton

@bot.command("poll", "Ask a question")
async def poll(ctx, question: str):
    await ctx.say(question, actions=Actions([ActionButton("yes", "Yes"), ActionButton("no", "No")]))

@bot.action("yes")
async def yes(ctx):
    await ctx.edit_message("Thanks for voting!")
```

## Audio

48 kHz stereo 16-bit PCM, paced in real time by the SDK. The bot must be in the channel.

```python
player = ctx.server.player(ctx.channel)
await ctx.server.join(ctx.channel)
await player.play_file("song.mp3", volume=0.5)   # needs ffmpeg
await player.tone(440, seconds=1)                # a quiet tone
await player.stop()
```

A bot may play in 2 channels per server at once. Keep the volume reasonable.

## Events

| Event | Gets |
|---|---|
| `on_connect` | the list of servers |
| `on_ready` | a `Server` that is awake (again) |
| `on_server_sleeping`, `on_server_added`, `on_server_removed` | a `Server` |
| `on_message` | a `Message` that names the bot (or every message with the "messages" permission) |
| `on_direct` | a private `DirectMessage` |
| `on_member` | a `MemberEvent` (someone joined or left a channel; "members" permission) |
| `on_command` | a `CommandContext` for commands without a handler |
| `on_action`, `on_form`, `on_suggest`, `on_dialog_event` | their context |
| `on_disconnect` | code, reason (the SDK connects again by itself) |
| `on_error` | the error and where it happened |
| `on_raw` | every message as it came |

A `Server` can `say`, `pm`, `join`, `leave`, `join_everywhere`, `status`, `channel_info`, `allowed` and
give a `player`. Servers sleep when nobody is on them; your bot gets `on_ready` again when they wake, and
does not keep them awake.

## Testing without a server

`infitalk.testing.TestServer` pretends to be the gateway with one server, on your computer. It answers like
a server, checks the 3-second rule and dialog labels, and plays the people:

```python
from infitalk.testing import TestServer

async def test_echo():
    async with TestServer() as srv:
        await srv.start(bot)
        answer = await srv.command("echo", text="hi")
        assert answer["content"] == "hi"
```

With `pytest` and `pytest-asyncio` (`pip install infitalk[test]`). See `tests/` for dialogs, buttons,
suggestions and audio.

## More

- Examples: `examples/echo_bot.py`, `examples/music_bot.py` (a class, a queue, a volume dialog),
  `examples/poll_bot.py` (buttons).
- The protocol, limits and error codes: https://infiartt.com/dev-center/infitalk-bots
- Send your bot to the catalog from My bots when it is ready; the InfiArtt team reviews it (it must work
  well with NVDA).
