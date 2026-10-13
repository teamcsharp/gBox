import struct
from pathlib import Path

import gbox.semantic
import gbox.tools as tools
from gbox.tools import PickPreviewIn


def _make_adapter():
    """Return a fake adapter whose read_memory returns deterministic bytes."""
    class FakeAdapter:
        name = "fake"

        def read_memory(self, addr, n):
            # Camera: eye=(0,0,0), target=(0,0,1) — little-endian floats.
            if n == 12:
                return struct.pack("<3f", 0.0, 0.0, (addr & 1) * 1.0)
            return bytes((i + (addr & 0xFF)) % 256 for i in range(n))

    return FakeAdapter()


def _stub_state(adapter, game):
    return {
        "profile": "test_profile",
        "entities": [
            {"class": "Soldier", "kind": "enemy", "entity_id": 7, "ptr": "0x80123456", "x": 0.0, "y": 12.0, "z": 20.0, "hp": 80, "room": 1},
            {"class": "Crate", "kind": "object", "entity_id": 12, "ptr": "0x80124000", "x": 10.0, "y": 0.0, "z": 30.0, "hp": None, "room": 1},
        ],
    }


def _stub_profiles():
    return [{
        "id": "test_profile",
        "title": "Test Game",
        "camera": {"eye": "0x1000", "target": "0x1010", "fov": 45},
        "evidence": {"entities": "0x80200000", "Soldier": {"struct_size": "0x200"}, "models": {}},
        "models": {"Soldier": ["enemy", "soldier.glb"]},
    }]


def test_pick_preview_hits_nearest_and_returns_ram_and_evidence(monkeypatch, tmp_path):
    adapter = _make_adapter()
    game = {"title": "Test Game", "platform": "ps2"}
    tools.SESSIONS["preview-test"] = (adapter, game)

    monkeypatch.setattr(tools, "_semantic_state", _stub_state)
    monkeypatch.setattr(gbox.semantic, "load_profiles", _stub_profiles)
    # Force the projection to place every entity exactly at the click so the test
    # does not depend on the math of the projection helper.
    monkeypatch.setattr(tools, "project_point", lambda eye, target, point, fov: (0.5, 0.5))

    try:
        out = tools.pick_preview(PickPreviewIn(session_id="preview-test", x=0.5, y=0.5, window_aspect=4 / 3), None)
    finally:
        tools.SESSIONS.pop("preview-test", None)

    res = out["result"]
    assert res["picked"]["class"] == "Soldier"
    assert res["picked"]["entity_id"] == 7
    assert res["picked"]["ptr"] == "0x80123456"
    assert res["hex"] is not None and len(res["hex"].split()) == 64
    assert res["evidence"]["Soldier"]["struct_size"] == "0x200"
    assert res["model"] == ["enemy", "soldier.glb"]
    assert any(o["class"] == "Crate" for o in res["others"])


def test_pick_preview_no_profile_returns_note(monkeypatch):
    adapter = _make_adapter()
    game = {"title": "Unprofiled Game", "platform": "ps2"}
    tools.SESSIONS["preview-empty"] = (adapter, game)
    monkeypatch.setattr(tools, "_semantic_state", lambda a, g: {"profile": None})

    try:
        out = tools.pick_preview(PickPreviewIn(session_id="preview-empty", x=0.5, y=0.5), None)
    finally:
        tools.SESSIONS.pop("preview-empty", None)

    assert out["result"]["picked"] is None
    assert "no camera mapping" in out["result"]["note"]
