"""Audio: 48 kHz stereo signed 16-bit little-endian PCM, sent in real time in 20 ms pieces.

    player = server.player(channel)          # one stream per channel
    await server.join(channel)               # the bot must be in that channel
    await player.play_file("song.mp3", volume=0.5)   # needs ffmpeg on the PATH
    await player.tone(440, seconds=1)        # a quiet test tone
    await player.stop()                      # at once (skip, stop)

The server turns it into the channel's Opus. Listeners have their own volume for bots, but keep it reasonable.
Through the gateway a bot may play in 2 channels per server at once.
"""
from __future__ import annotations

import array
import asyncio
import base64
import math
import shutil
import sys
import time
from typing import TYPE_CHECKING, AsyncIterator, Iterable, Optional, Union

if TYPE_CHECKING:  # pragma: no cover
    from .models import Server

RATE = 48000
CHANNELS = 2
SAMPLE_BYTES = 2
FRAME_MS = 20
FRAME_BYTES = RATE * CHANNELS * SAMPLE_BYTES * FRAME_MS // 1000  # 3840
AHEAD = 0.4  # seconds sent ahead of real time (the server keeps up to 3)

PcmSource = Union[bytes, Iterable[bytes], AsyncIterator[bytes]]


def scale(pcm: bytes, volume: float) -> bytes:
    """Change the loudness of PCM (1.0 = as it is)."""
    if volume == 1.0:
        return pcm
    samples = array.array("h")
    samples.frombytes(pcm[: len(pcm) - len(pcm) % 2])
    if sys.byteorder == "big":  # pragma: no cover
        samples.byteswap()
    for i, s in enumerate(samples):
        v = int(s * volume)
        samples[i] = 32767 if v > 32767 else -32768 if v < -32768 else v
    if sys.byteorder == "big":  # pragma: no cover
        samples.byteswap()
    return samples.tobytes()


def tone_pcm(freq: float = 440.0, seconds: float = 1.0, volume: float = 0.03) -> bytes:
    """A sine tone; quiet by default (about -30 dB)."""
    amp = int(32767 * max(0.0, min(volume, 1.0)))
    out = array.array("h")
    for i in range(int(RATE * seconds)):
        v = int(math.sin(2 * math.pi * freq * i / RATE) * amp)
        out.append(v)
        out.append(v)
    if sys.byteorder == "big":  # pragma: no cover
        out.byteswap()
    return out.tobytes()


async def _pieces(source: PcmSource) -> AsyncIterator[bytes]:
    """Any source cut into whole 20 ms frames."""
    rest = b""

    async def chunks() -> AsyncIterator[bytes]:
        if isinstance(source, (bytes, bytearray)):
            yield bytes(source)
        elif hasattr(source, "__aiter__"):
            async for c in source:  # type: ignore[union-attr]
                yield c
        else:
            for c in source:  # type: ignore[union-attr]
                yield c

    async for chunk in chunks():
        rest += chunk
        while len(rest) >= FRAME_BYTES:
            yield rest[:FRAME_BYTES]
            rest = rest[FRAME_BYTES:]
    if rest:
        yield rest + b"\0" * (FRAME_BYTES - len(rest))


class AudioPlayer:
    """Plays into one channel of one server. Starting something new stops what plays."""

    def __init__(self, server: "Server", channel: int):
        self.server, self.channel = server, channel
        self._task: Optional[asyncio.Task] = None
        self.volume = 1.0

    @property
    def playing(self) -> bool:
        return self._task is not None and not self._task.done()

    async def play(self, source: PcmSource, *, volume: Optional[float] = None, wait: bool = True) -> None:
        """Play PCM (bytes, an iterable or an async iterable of bytes). ``wait=False`` returns at once."""
        await self.stop()
        self._task = asyncio.ensure_future(self._send(source, self.volume if volume is None else volume))
        if wait:
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def play_file(self, path_or_url: str, *, volume: Optional[float] = None, wait: bool = True,
                        ffmpeg: str = "ffmpeg") -> None:
        """Play a file or a link that ffmpeg can open."""
        exe = shutil.which(ffmpeg) or ffmpeg
        proc = await asyncio.create_subprocess_exec(
            exe, "-nostdin", "-loglevel", "error", "-i", path_or_url, "-f", "s16le", "-ac", str(CHANNELS),
            "-ar", str(RATE), "-", stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)

        async def read() -> AsyncIterator[bytes]:
            assert proc.stdout is not None
            try:
                while True:
                    data = await proc.stdout.read(FRAME_BYTES * 10)
                    if not data:
                        break
                    yield data
            finally:
                if proc.returncode is None:
                    proc.kill()
                await proc.wait()

        await self.play(read(), volume=volume, wait=wait)

    async def tone(self, freq: float = 440.0, seconds: float = 1.0, *, volume: float = 0.03) -> None:
        await self.play(tone_pcm(freq, seconds, volume), volume=1.0)

    async def stop(self, *, drop: bool = True) -> None:
        """Stop now (``drop``) or let the buffered audio play out (``drop=False``)."""
        task, self._task = self._task, None
        if task is not None and not task.done():
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass
            await self._end(drop)

    async def _end(self, drop: bool) -> None:
        try:
            await self.server.request("audio_end", channel=self.channel, **({"drop": True} if drop else {}))
        except Exception:
            pass

    async def _send(self, source: PcmSource, volume: float) -> None:
        start = time.monotonic()
        sent = 0.0
        async for frame in _pieces(source):
            # keep at most AHEAD seconds in front of real time
            wait = start + sent - AHEAD - time.monotonic()
            if wait > 0:
                await asyncio.sleep(wait)
            await self.server._bot._send_fast(self.server.id, {
                "op": "audio", "channel": self.channel,
                "pcm": base64.b64encode(scale(frame, volume)).decode("ascii")})
            sent += FRAME_MS / 1000
        await self._end(False)


__all__ = ["AudioPlayer", "scale", "tone_pcm", "RATE", "CHANNELS", "FRAME_BYTES"]
