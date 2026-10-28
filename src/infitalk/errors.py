"""Errors raised by the SDK.

Every refused request raises :class:`InfiTalkError` (or a subclass) with the error code the server or the
gateway sent, for example ``missing_permission`` or ``not_in_channel``. The codes are listed on
https://infiartt.com/dev-center/infitalk-bots#dev-limits.
"""
from __future__ import annotations

from typing import Any, Dict, Optional


class InfiTalkError(Exception):
    """A request was refused. ``code`` is the error code, ``data`` the whole answer."""

    def __init__(self, code: str, message: str = "", data: Optional[Dict[str, Any]] = None):
        self.code = code
        self.data = data or {}
        super().__init__(f"{code}: {message}" if message else code)


class MissingPermission(InfiTalkError):
    """The bot lacks a permission on that server (``permission`` says which one)."""

    @property
    def permission(self) -> str:
        return str(self.data.get("permission", ""))


class RateLimited(InfiTalkError):
    """Too many requests; ``retry_after`` is in seconds. The SDK already retried before raising this."""

    @property
    def retry_after(self) -> float:
        return float(self.data.get("retry_after", 1))


class ServerAsleep(InfiTalkError):
    """The server went to sleep; it gets a new ``on_ready`` when it wakes."""


class InvalidToken(InfiTalkError):
    """The token is not valid, was changed, or the bot was turned off. The bot stops."""


class Replaced(InfiTalkError):
    """The same bot connected from somewhere else, so this connection was closed. The bot stops."""


class InvalidComponent(ValueError):
    """A dialog, form or command is not valid (for example a control without a label)."""


_BY_CODE = {
    "missing_permission": MissingPermission,
    "rate_limited": RateLimited,
    "server_asleep": ServerAsleep,
    "invalid_token": InvalidToken,
}


def error_from(answer: Dict[str, Any]) -> InfiTalkError:
    code = str(answer.get("error") or "error")
    return _BY_CODE.get(code, InfiTalkError)(code, str(answer.get("message", "")), answer)
