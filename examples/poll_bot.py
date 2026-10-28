"""A poll with buttons under a message: everyone votes once, the message shows the count as it changes.

    INFITALK_TOKEN=itw_... python poll_bot.py
"""
from typing import Dict, Set

from infitalk import ActionButton, ActionContext, Actions, Bot, Field

bot = Bot()
votes: Dict[int, Dict[str, Set[int]]] = {}  # message id -> choice -> people
questions: Dict[int, str] = {}


def buttons() -> Actions:
    return Actions([ActionButton("yes", "Yes"), ActionButton("no", "No")])


def text(msgid: int) -> str:
    v = votes[msgid]
    return f"{questions[msgid]} Yes: {len(v['yes'])}, No: {len(v['no'])}."


@bot.command("poll", "Ask the channel a yes or no question", category="Fun")
async def poll(ctx, question: str = Field(label="Question")):
    sent = await ctx.say(f"{question} Yes: 0, No: 0.", actions=buttons())
    votes[sent.id] = {"yes": set(), "no": set()}
    questions[sent.id] = question


@bot.action("yes")
@bot.action("no")
async def vote(ctx: ActionContext):
    v = votes.get(ctx.message.id)
    if v is None:
        await ctx.respond("This poll is over.")
        return
    for choice in v.values():
        choice.discard(ctx.user.id)
    v[ctx.action].add(ctx.user.id)
    await ctx.edit_message(text(ctx.message.id), actions=buttons())


bot.run()
