from typing import Literal, Optional

import pytest

from infitalk import Bot, Command, Field, InvalidComponent, command


async def handler(ctx, song: str, volume: int = 50, mode: Literal["once", "loop"] = "once",
                  note: Optional[str] = None, who: str = Field(label="Who", suggest=True)):
    pass


def test_fields_from_signature():
    c = Command("play", "Play", handler, category="Music", permission="moderator")
    d = c.to_dict()
    assert d["name"] == "play" and d["category"] == "Music" and d["permission"] == "moderator"
    opts = {o["name"]: o for o in d["options"]}
    assert opts["song"] == {"name": "song", "label": "Song", "type": "text", "required": True}
    assert opts["volume"]["type"] == "number" and "required" not in opts["volume"]
    assert opts["mode"]["type"] == "choice" and opts["mode"]["choices"] == ["once", "loop"]
    assert "required" not in opts["note"]
    assert opts["who"] == {"name": "who", "label": "Who", "type": "text", "required": True, "suggest": True}


def test_values_are_converted():
    c = Command("play", "Play", handler)
    args = c.arguments({"song": "Kangen", "volume": "70", "who": "me"})
    assert args == {"song": "Kangen", "volume": 70, "mode": "once", "note": None, "who": "me"}
    with pytest.raises(ValueError, match="not a number"):
        c.arguments({"song": "x", "volume": "loud"})


def test_names_and_permissions_are_checked():
    with pytest.raises(InvalidComponent):
        Command("Play Now", "x")
    with pytest.raises(InvalidComponent):
        Command("play", "x", permission="owner")


def test_commands_as_methods():
    class B(Bot):
        @command("ping", "Answer pong", category="Test")
        async def ping(self, ctx, times: int = 1):
            pass

    b = B(token="itw_" + "0" * 40)
    assert b.commands["ping"].to_dict() == {"name": "ping", "description": "Answer pong", "category": "Test",
                                            "options": [{"name": "times", "label": "Times", "type": "number"}]}
