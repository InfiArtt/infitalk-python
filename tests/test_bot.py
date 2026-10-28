import asyncio

import pytest

from infitalk import (ActionButton, Actions, Bot, Button, Dialog, DialogEvent, Field, Slider, TextInput, User,
                      command, suggest)
from infitalk.testing import BotDidNotAnswer, TestServer

TOKEN = "itw_" + "1" * 40


def make_bot() -> Bot:
    bot = Bot(token=TOKEN)

    @bot.command("echo", "Repeat", category="Fun")
    async def echo(ctx, text: str):
        await ctx.respond(text, public=True)

    @bot.command("add", "Add numbers")
    async def add(ctx, a: int, b: int = 1):
        await ctx.respond(str(a + b))

    @bot.command("slow", "Takes a while")
    async def slow(ctx):
        await asyncio.sleep(2.5)
        await ctx.respond("done")

    @bot.command("broken", "Fails")
    async def broken(ctx):
        raise RuntimeError("boom")

    @bot.command("eq", "Equalizer", dialog=True)
    async def eq(ctx):
        await ctx.dialog(Dialog("eq", "Equalizer", [Slider("bass", "&Bass", 0, min=-12, max=12),
                                                     Button("save", "&Save", default=True)]))

    @bot.dialog("eq")
    async def eq_events(ev: DialogEvent):
        await ev.update([Slider("bass", "&Bass", ev.value("bass"), min=-12, max=12)], announce="Saved")

    @bot.command("vote", "Vote")
    async def vote(ctx):
        await ctx.say("Vote now", actions=Actions([ActionButton("yes", "Yes")]))

    @bot.action("yes")
    async def yes(ctx):
        await ctx.edit_message("1 vote")

    @bot.command("song", "Song")
    async def song(ctx, name: str = Field(label="Name")):
        await ctx.respond(name)

    @song.suggest("name")
    async def names(ctx, value):
        return [n for n in ("Kangen", "Kamulah satu-satunya") if n.lower().startswith(value.lower())]

    @bot.event
    async def on_message(msg):
        if msg.mentions_me:
            await msg.reply(f"hi {msg.user}")

    return bot


async def test_menu_and_join_on_ready():
    async with TestServer() as srv:
        await srv.start(make_bot())
        assert [c["name"] for c in srv.menu] == ["echo", "add", "slow", "broken", "eq", "vote", "song"]
        assert srv.bot_channel == 1  # joined "/"


async def test_commands_answer_and_convert():
    async with TestServer() as srv:
        await srv.start(make_bot())
        a = await srv.command("echo", text="halo")
        assert a["op"] == "respond" and a["content"] == "halo" and a["public"] is True
        assert (await srv.command("add", a="2", b="3"))["content"] == "5"
        assert (await srv.command("add", a="lots"))["content"] == "a: 'lots' is not a number"


async def test_auto_defer_and_errors():
    async with TestServer() as srv:
        await srv.start(make_bot())
        assert (await srv.command("slow"))["content"] == "done"  # the defer came first
        assert any(m["op"] == "defer" for m in srv.sent)
        assert "went wrong" in (await srv.command("broken"))["content"]


async def test_no_answer_is_caught():
    bot = Bot(token=TOKEN, auto_defer=False)

    @bot.command("quiet", "Never answers")
    async def quiet(ctx):
        await asyncio.sleep(5)

    async with TestServer() as srv:
        await srv.start(bot)
        with pytest.raises(BotDidNotAnswer):
            await srv.command("quiet")


async def test_dialogs_buttons_suggestions_messages():
    async with TestServer() as srv:
        await srv.start(make_bot())
        dlg = await srv.command("eq")
        assert dlg["op"] == "dialog" and dlg["dialog"]["controls"][0]["type"] == "slider"
        upd = await srv.press(dlg, "save", {"bass": 4}, event="button")
        assert upd["op"] == "dialog_update" and upd["announce"] == "Saved" and upd["controls"][0]["value"] == 4

        said = await srv.command("vote")
        assert said["op"] == "say" and said["actions"]["buttons"][0]["id"] == "yes"
        edited = await srv.click(1234, "yes")
        assert edited["op"] == "edit" and edited["content"] == "1 vote" and edited["msgid"] == 1234

        choices = await srv.suggest("song", "name", "ka")
        assert [c["value"] for c in choices] == ["Kangen", "Kamulah satu-satunya"]

        await srv.message("hey @testbot", user=User(7, "Rafli"))
        reply = await srv.next("say", content="hi Rafli")
        assert reply["reply_to"] > 0


async def test_sleep_wake_and_class_style():
    seen = []

    class B(Bot):
        async def on_ready(self, server):
            seen.append(("ready", server.id))

        async def on_server_sleeping(self, server):
            seen.append(("sleeping", server.id))

        @command("ping", "Pong")
        async def ping(self, ctx):
            await ctx.respond("pong")

        @command("find", "Find")
        async def find(self, ctx, what: str):
            await ctx.respond(what)

        @suggest("find", "what")
        async def options(self, ctx, value):
            return ["one", "two"]

    async with TestServer() as srv:
        bot = await srv.start(B(token=TOKEN))
        assert (await srv.command("ping"))["content"] == "pong"
        assert [c["value"] for c in await srv.suggest("find", "what", "")] == ["one", "two"]
        await srv.sleep()
        await asyncio.sleep(0.2)
        assert not bot.servers[1].ready
        await srv.wake()
        assert bot.servers[1].ready and seen == [("ready", 1), ("sleeping", 1), ("ready", 1)]


async def test_bad_dialog_is_refused_like_the_server():
    bot = Bot(token=TOKEN)

    @bot.command("bad", "Bad dialog", dialog=True)
    async def bad(ctx):
        await ctx.server.request("dialog", interaction=ctx.id, dialog={"id": "b", "title": "B",
                                                                       "controls": [{"type": "text", "id": "t"}]})

    errors = []

    @bot.event
    async def on_error(error, where):
        errors.append(error.code if hasattr(error, "code") else str(error))

    async with TestServer() as srv:
        await srv.start(bot)
        answer = await srv.command("bad")
        assert errors == ["invalid_dialog"] and "went wrong" in answer["content"]
        with pytest.raises(Exception):
            Dialog("b", "B", [TextInput("t", "")]).to_dict()


async def test_audio_tone_is_paced_and_ends():
    bot = Bot(token=TOKEN)
    async with TestServer() as srv:
        await srv.start(bot)
        server = bot.servers[1]
        started = asyncio.get_running_loop().time()
        await server.player(1).tone(440, seconds=0.6)
        took = asyncio.get_running_loop().time() - started
        frames = [m for m in srv.sent if m["op"] == "audio"]
        assert len(frames) == 30 and frames[0]["channel"] == 1
        assert took >= 0.15  # real time minus what is sent ahead
        await srv.next("audio_end", channel=1)
