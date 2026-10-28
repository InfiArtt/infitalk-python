"""People, channels, servers and messages as the bot sees them."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Union

from .components import Actions

if TYPE_CHECKING:  # pragma: no cover
    from .audio import AudioPlayer
    from .bot import Bot

LEVELS = ("everyone", "moderator", "admin")


@dataclass
class User:
    """Someone on a server. ``level`` is everyone, moderator or admin (on that server)."""

    id: int
    nickname: str = ""
    username: str = ""
    level: str = "everyone"

    @classmethod
    def from_dict(cls, d: Optional[Dict[str, Any]]) -> "User":
        d = d or {}
        return cls(int(d.get("id") or 0), str(d.get("nickname") or ""), str(d.get("username") or ""),
                   str(d.get("level") or "everyone"))

    @property
    def is_moderator(self) -> bool:
        """A moderator or an admin of this server."""
        return self.level in ("moderator", "admin")

    @property
    def is_admin(self) -> bool:
        return self.level == "admin"

    @property
    def is_infiartt(self) -> bool:
        """Signed in with an InfiArtt account (name@infiartt.com)."""
        return self.username.endswith("@infiartt.com")

    def __str__(self) -> str:
        return self.nickname or self.username or f"#{self.id}"


@dataclass
class Channel:
    id: int
    path: str = ""
    name: str = ""

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "Channel":
        return cls(int(d.get("id") or 0), str(d.get("path") or ""), str(d.get("name") or ""))


ChannelRef = Union[int, str, Channel]


def _channel_fields(channel: Optional[ChannelRef]) -> Dict[str, Any]:
    """A channel by number, by path ("/Music/") or as a Channel."""
    if channel is None:
        return {}
    if isinstance(channel, Channel):
        return {"channel": channel.id}
    if isinstance(channel, str):
        return {"path": channel}
    return {"channel": int(channel)}


class Server:
    """A server the bot was added to. Everything the bot does there goes through this object."""

    def __init__(self, bot: "Bot", id: int, name: str = "", awake: bool = False):
        self._bot = bot
        self.id = id
        self.name = name
        self.awake = awake
        self.ready = False
        self.session: str = ""
        self.user_id = 0       # the bot's own user id on this server
        self.channel_id = 0    # the channel it is in (0 = none)
        self.everywhere = False
        self.intents: List[str] = []
        self.channels: Dict[int, Channel] = {}
        self._players: Dict[int, "AudioPlayer"] = {}

    def __repr__(self) -> str:
        return f"<Server {self.id} {self.name!r} {'ready' if self.ready else 'asleep'}>"

    def channel(self, ref: ChannelRef) -> Optional[Channel]:
        """A channel the bot may see, by number or path."""
        if isinstance(ref, Channel):
            return ref
        if isinstance(ref, str):
            return next((c for c in self.channels.values() if c.path == ref), None)
        return self.channels.get(int(ref))

    async def request(self, op: str, **fields: Any) -> Dict[str, Any]:
        """Any request of the bot protocol on this server; raises InfiTalkError when refused."""
        return await self._bot._request(self.id, op, fields)

    # ---------- channels and presence ----------

    async def join(self, channel: ChannelRef) -> None:
        """Go to a channel (number, path or Channel)."""
        await self.request("join", **_channel_fields(channel))

    async def leave(self) -> None:
        await self.request("join", channel=0)

    async def join_everywhere(self) -> None:
        """Be in every channel at once (needs the "everywhere" approval of the server)."""
        await self.request("join", everywhere=True)
        self.everywhere = True

    async def status(self, text: str, *, channel: Optional[ChannelRef] = None, mode: Optional[int] = None) -> None:
        """Status text such as "Playing: ...", for one channel or everywhere ("" = the normal status)."""
        fields: Dict[str, Any] = {"text": text, **_channel_fields(channel)}
        if mode is not None:
            fields["mode"] = mode
        await self.request("status", **fields)

    async def channel_info(self, channel: ChannelRef) -> Dict[str, Any]:
        """{"name", "path", "users": [...]}: who is in a channel."""
        return await self.request("channel_info", **_channel_fields(channel))

    # ---------- messages ----------

    async def say(self, content: str, *, channel: Optional[ChannelRef] = None, reply_to: Optional[int] = None,
                  actions: Optional[Actions] = None) -> "SentMessage":
        """A message in a channel (its own channel when none is given)."""
        fields: Dict[str, Any] = {"content": content, **_channel_fields(channel)}
        if reply_to:
            fields["reply_to"] = reply_to
        if actions is not None:
            fields["actions"] = actions.to_dict()
        answer = await self.request("say", **fields)
        return SentMessage(self, int(fields.get("channel") or self.channel_id), int(answer.get("msgid") or 0))

    async def pm(self, user: Union[int, User], content: str) -> None:
        """A private message, only to someone who wrote to the bot or named it in the last 10 minutes."""
        await self.request("pm", user=user.id if isinstance(user, User) else int(user), content=content)

    async def allowed(self, user: Union[int, User], command: str) -> bool:
        """May this person use that command here (for commands typed in the chat)?"""
        answer = await self.request("allowed", user=user.id if isinstance(user, User) else int(user), command=command)
        return bool(answer.get("allowed"))

    # ---------- audio ----------

    def player(self, channel: ChannelRef) -> "AudioPlayer":
        """The audio player of one channel here (one stream per channel; 2 per server through the gateway)."""
        from .audio import AudioPlayer
        ch = self.channel(channel)
        cid = ch.id if ch else int(channel) if not isinstance(channel, (str, Channel)) else 0
        if not cid:
            raise ValueError(f"unknown channel {channel!r}")
        if cid not in self._players:
            self._players[cid] = AudioPlayer(self, cid)
        return self._players[cid]


@dataclass
class SentMessage:
    """A message the bot wrote: it may edit or delete it."""

    server: Server
    channel: int
    id: int

    async def edit(self, content: str, *, actions: Optional[Actions] = None, interaction: Optional[int] = None) -> None:
        fields: Dict[str, Any] = {"msgid": self.id, "content": content}
        if actions is not None:
            fields["actions"] = actions.to_dict()
        if interaction:
            fields["interaction"] = interaction
        await self.server.request("edit", **fields)

    async def delete(self) -> None:
        await self.server.request("delete", msgid=self.id)


@dataclass
class Message:
    """A message the bot heard: one that names it (intent "mentions") or any message (intent "messages")."""

    server: Server
    channel: int
    id: int
    user: User
    content: str
    reply_to: int = 0
    mention: bool = False
    raw: Dict[str, Any] = field(default_factory=dict, repr=False)

    @property
    def mentions_me(self) -> bool:
        return self.mention

    async def reply(self, content: str, *, actions: Optional[Actions] = None) -> SentMessage:
        return await self.server.say(content, channel=self.channel, reply_to=self.id, actions=actions)


@dataclass
class DirectMessage:
    """A private message to the bot."""

    server: Server
    user: User
    content: str
    raw: Dict[str, Any] = field(default_factory=dict, repr=False)

    async def reply(self, content: str) -> None:
        await self.server.pm(self.user, content)


@dataclass
class MemberEvent:
    """Someone joined (``joined``) or left a channel the bot may see (intent "members")."""

    server: Server
    channel: int
    user: User
    joined: bool
    raw: Dict[str, Any] = field(default_factory=dict, repr=False)
