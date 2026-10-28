"""A small music bot written as a class: play files from a folder (ffmpeg needed), a queue, a volume dialog
with a slider, suggestions while typing, and a command only moderators may use.

    INFITALK_TOKEN=itw_... MUSIC_DIR=./music python music_bot.py
"""
import asyncio
import os
from collections import defaultdict
from pathlib import Path
from typing import Dict, List

from infitalk import (Bot, Button, CommandContext, Dialog, DialogEvent, Field, Label, Server, Slider, command,
                      suggest)

MUSIC = Path(os.environ.get("MUSIC_DIR", "music"))
KINDS = (".mp3", ".ogg", ".wav", ".flac", ".m4a")


class MusicBot(Bot):
    def __init__(self) -> None:
        super().__init__()
        self.queues: Dict[int, List[Path]] = defaultdict(list)  # per server
        self.volume: Dict[int, float] = defaultdict(lambda: 0.5)

    def songs(self) -> List[Path]:
        return sorted(p for p in MUSIC.glob("*") if p.suffix.lower() in KINDS)

    async def on_ready(self, server: Server) -> None:
        await server.status("Ready: use my menu (Ctrl+Shift+P)")

    @command("play", "Play a song from the music folder", category="Music")
    async def play(self, ctx: CommandContext, song: str = Field(label="Song")) -> None:
        found = next((p for p in self.songs() if song.lower() in p.stem.lower()), None)
        if found is None:
            await ctx.respond(f"No song like {song!r}.")
            return
        self.queues[ctx.server.id].append(found)
        await ctx.respond(f"Added {found.stem}.", public=True)
        if not ctx.server.player(ctx.channel).playing:
            await ctx.server.join(ctx.channel)
            asyncio.ensure_future(self.play_queue(ctx.server, ctx.channel))

    @suggest("play", "song")
    async def song_names(self, ctx, value: str) -> List[str]:
        return [p.stem for p in self.songs() if value.lower() in p.stem.lower()][:25]

    async def play_queue(self, server: Server, channel: int) -> None:
        player = server.player(channel)
        while self.queues[server.id]:
            song = self.queues[server.id].pop(0)
            await server.status(f"Playing: {song.stem}", channel=channel)
            await player.play_file(str(song), volume=self.volume[server.id])
        await server.status("", channel=channel)

    @command("stop", "Stop and clear the queue", category="Music", permission="moderator")
    async def stop(self, ctx: CommandContext) -> None:
        self.queues[ctx.server.id].clear()
        await ctx.server.player(ctx.channel).stop()
        await ctx.respond("Stopped.", public=True)

    @command("volume", "Change the volume", category="Music", dialog=True)
    async def volume_dialog(self, ctx: CommandContext) -> None:
        await ctx.dialog(Dialog("volume", "Volume", [
            Label("Changes apply to the next song."),
            Slider("level", "&Volume", min=0, max=100, step=5, unit="%", value=round(self.volume[ctx.server.id] * 100)),
            Button("save", "&Save", default=True),
            Button("close", "Close", close=True),
        ], focus="level"))

    async def on_dialog_event(self, event: DialogEvent) -> None:
        if event.dialog_id == "volume" and event.control == "save":
            self.volume[event.server.id] = max(0, min(100, int(event.value("level", 50)))) / 100
            await event.update(announce=f"Volume {int(self.volume[event.server.id] * 100)} percent")


if __name__ == "__main__":
    MusicBot().run()
