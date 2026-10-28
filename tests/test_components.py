import pytest

from infitalk import (ActionButton, Actions, Button, Checkbox, Choice, Dialog, Field, Form, Group, InvalidComponent,
                      Label, ListBox, Select, Slider, TextInput)


def test_dialog_to_dict():
    d = Dialog("eq", "Equalizer", [
        Label("Pick a preset"),
        Slider("bass", "&Bass", 0, min=-12, max=12, step=1, unit="dB", notify=True),
        Select("preset", "&Preset", [Choice("flat", "Flat"), "pop"], value="flat"),
        ListBox("songs", "&Songs", ["a", "b"], multi=True, activate="play"),
        Group("more", "More", [Checkbox("loud", "&Loudness", True), TextInput("name", "&Name", maxlength=20)]),
        Button("play", "&Play", default=True),
        Button("close", "Close", close=True),
    ], focus="bass").to_dict()
    assert d["id"] == "eq" and d["focus"] == "bass"
    kinds = [c["type"] for c in d["controls"]]
    assert kinds == ["label", "slider", "select", "list", "group", "button", "button"]
    assert d["controls"][1] == {"type": "slider", "id": "bass", "label": "&Bass", "notify": True, "value": 0,
                                "min": -12, "max": 12, "step": 1, "unit": "dB"}
    assert d["controls"][2]["options"][1] == {"value": "pop", "label": "pop"}
    assert d["controls"][3]["items"][0]["value"] == "a" and d["controls"][3]["multi"] is True
    assert d["controls"][4]["controls"][0]["value"] is True
    assert d["controls"][6]["close"] is True


def test_controls_need_labels():
    with pytest.raises(InvalidComponent, match="needs a label"):
        Dialog("x", "X", [Button("ok", "")]).to_dict()
    with pytest.raises(InvalidComponent, match="needs a label"):
        Dialog("x", "X", [Group("g", "Group", [TextInput("t", "&")])]).to_dict()


def test_dialog_limits():
    with pytest.raises(InvalidComponent, match="at most 100"):
        Dialog("x", "X", [Button(f"b{i}", f"B {i}") for i in range(101)]).to_dict()
    with pytest.raises(InvalidComponent, match="at most 200"):
        Dialog("x", "X", [Select("s", "S", [str(i) for i in range(201)])]).to_dict()
    with pytest.raises(InvalidComponent, match="title"):
        Dialog("x", " ", [Button("b", "B")]).to_dict()
    with pytest.raises(InvalidComponent, match="control id"):
        Dialog("x", "X", [Button("has space", "B")]).to_dict()


def test_actions_and_form():
    assert Actions([ActionButton("yes", "Yes")]).to_dict() == {"buttons": [{"id": "yes", "label": "Yes"}]}
    with pytest.raises(InvalidComponent):
        Actions([ActionButton(str(i), "B") for i in range(6)])
    f = Form("Your name", [Field("name", "Name", required=True)]).to_dict()
    assert f == {"title": "Your name", "fields": [{"name": "name", "label": "Name", "type": "text", "required": True}]}
