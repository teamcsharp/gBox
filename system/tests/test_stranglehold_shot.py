"""Tests for the Stranglehold bullet-time interception helper."""
import pytest

from gbox import stranglehold
from gbox.registry import Ctx
from gbox.tools import ScriptPatchIn, LinkIn


class FakeConfig:
    runtime = "/tmp"


def ctx():
    return Ctx(FakeConfig(), job_id="test", worker="test")


def test_minimum_systems_includes_profile_systems():
    r = stranglehold.stranglehold_shot(stranglehold.StrangleholdShotIn(op="systems"), ctx())
    assert r["result"]["profile_id"] == "stranglehold-ps3-us"
    roles = {s["role"] for s in r["result"]["systems"]}
    assert "shot type" in roles
    assert "suspend point" in roles
    assert "presentation verdict" in roles
    assert "damage verdict" in roles
    assert "slow motion" in roles
    assert "aim state" in roles
    assert set(r["result"]["presets"]) == {"god", "god_hit", "god_miss", "hit", "miss", "off"}


def test_locate_delegates_to_script_patch(monkeypatch):
    calls = []
    def fake_script_patch(inp: ScriptPatchIn, _ctx):
        calls.append((inp.session_id, inp.op, inp.preset))
        return {"result": {"profile": "stranglehold-ps3-us", "active": "off",
                           "functions": {"rpa": "0x1000", "srd": "0x2000", "prd": "0x3000"},
                           "presets": {}}}
    monkeypatch.setattr("gbox.tools.script_patch", fake_script_patch)
    r = stranglehold.stranglehold_shot(stranglehold.StrangleholdShotIn(op="locate", session_id="s-1"), ctx())
    assert calls == [("s-1", "locate", "")]
    assert r["result"]["functions"]["rpa"] == "0x1000"


def test_arm_applies_god_preset(monkeypatch):
    calls = []
    def fake_script_patch(inp: ScriptPatchIn, _ctx):
        calls.append((inp.op, inp.preset))
        return {"result": {"profile": "stranglehold-ps3-us", "active": inp.preset,
                           "functions": {"rpa": "0x1000"}, "presets": {}}}
    monkeypatch.setattr("gbox.tools.script_patch", fake_script_patch)
    r = stranglehold.stranglehold_shot(stranglehold.StrangleholdShotIn(op="arm", session_id="s-1"), ctx())
    assert calls == [("preset", "god")]
    assert r["result"]["active"] == "god"


def test_fire_applies_verdict_preset(monkeypatch):
    calls = []
    def fake_script_patch(inp: ScriptPatchIn, _ctx):
        calls.append(inp.preset)
        return {"result": {"profile": "stranglehold-ps3-us", "active": inp.preset,
                           "functions": {"rpa": "0x1000"}, "presets": {}}}
    monkeypatch.setattr("gbox.tools.script_patch", fake_script_patch)
    r = stranglehold.stranglehold_shot(stranglehold.StrangleholdShotIn(op="fire", session_id="s-1", verdict="miss"), ctx())
    assert calls == ["miss"]
    assert r["result"]["verdict"] == "miss"


def test_link_delegates_to_game_link(monkeypatch):
    calls = []
    def fake_game_patch(inp: ScriptPatchIn, _ctx):
        return {"result": {"active": "off", "functions": {}, "presets": {}}}
    def fake_game_link(inp: LinkIn, _ctx):
        calls.append({k: getattr(inp, k) for k in ["op", "host", "guest", "trigger", "win", "lose", "on_win", "on_lose"]})
        return {"result": {"running": True, "state": "waiting", "rounds": 0, "history": [], "error": None}}
    monkeypatch.setattr("gbox.tools.script_patch", fake_game_patch)
    monkeypatch.setattr("gbox.tools.game_link", fake_game_link)
    trigger = {"address": "0x1234", "type": "u8", "eq": 1}
    win = {"address": "0x5678", "type": "u8", "eq": 1}
    lose = {"address": "0x9abc", "type": "u8", "eq": 1}
    r = stranglehold.stranglehold_shot(stranglehold.StrangleholdShotIn(
        op="link", session_id="host-1", guest_session_id="guest-1",
        trigger=trigger, win=win, lose=lose), ctx())
    assert len(calls) == 1
    c = calls[0]
    assert c["op"] == "start"
    assert c["host"] == "host-1"
    assert c["guest"] == "guest-1"
    assert c["trigger"]["address"] == "0x1234"
    assert c["on_win"] == "god_hit"
    assert c["on_lose"] == "god_miss"
    assert r["result"]["running"] is True


def test_link_requires_addresses():
    with pytest.raises(ValueError, match="trigger needs a memory watch address"):
        stranglehold.stranglehold_shot(stranglehold.StrangleholdShotIn(
            op="link", session_id="host-1", guest_session_id="guest-1"), ctx())
