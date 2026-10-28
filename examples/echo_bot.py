"""The smallest useful bot: a menu with echo, a dialog, a quiet tone, and a reply when someone names it.

    pip install infitalk
    INFITALK_TOKEN=itw_... python echo_bot.py      (PowerShell: $env:INFITALK_TOKEN="itw_..."; python echo_bot.py)
"""
from infitalk import Bot, Button, Dialog, DialogEvent, Field, TextInput

bot = Bot()


@bot.command("echo", "Repeat what you write", category="Fun")
async def echo(ctx, text: str = Field(label="Text")):
    await ctx.respond(text, public=True)


@bot.command("hello", "Open a small dialog", category="Fun", dialog=True)
async def hello(ctx):
    await ctx.dialog(Dialog("hello", "Hello", [
        TextInput("name", "&Your name", ctx.user.nickname, maxlength=40),
        Button("greet", "&Greet me", default=True),
        Button("cancel", "Cancel", close=True),
    ], focus="name"))


@bot.dialog("hello")
async def hello_events(event: DialogEvent):
    if event.event == "button" and event.control == "greet":
        await event.respond(f"Hello, {event.value('name') or event.user.nickname}!")
        await event.close()


@bot.command("tone", "Play a quiet tone in your channel for one second", category="Sound")
async def tone(ctx):
    await ctx.respond("Playing a quiet tone for one second.")
    await ctx.server.join(ctx.channel)  # audio needs the bot in that channel
    await ctx.server.player(ctx.channel).tone(440, seconds=1)


@bot.event
async def on_message(msg):
    if msg.mentions_me:
        await msg.reply(f"Hi {msg.user}, try my menu with Ctrl+Shift+P.")


bot.run()
