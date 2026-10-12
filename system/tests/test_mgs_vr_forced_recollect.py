"""Forced re-extract of the VR Missions Snake through collect() (#1364).

With an EMPTY library, collect() must take the Linux route of characters._mgs_vr_run: pick an online Windows worker that
has the characters tool, dispatch characters op=mgs_vr_decode, download the receipt artifact mgs-vr-snake.glb, read the
body roles with mgs_vr_snake_roles, add the entry and report it verified and retargetable. A worker whose decode fails
falls through to the next one; with no Windows worker the entry fails instead of being added without a rig.

Live acceptance of the same chain on the deployed runtime (run 4): decode job 12c73294f6bf4b45 on JAYBUILTFINALE,
receipt a572c029ffcb45cc -> GLB d92d171d...fa89 (byte-identical to the library), 16 roles equal to the library meta,
verify_entry ok, collect retargetable 1/1. Only the library GLB is needed here; no API, worker or game session is used.
"""
import hashlib
import json
import types
from pathlib import Path

import pytest

from gbox import characters as C

LIB_GLB = Path("/home/ehm_eckx/gbox-cache/characters/mgs_vr_snake/mgs_vr_snake.glb")
GLB_SHA = "d92d171ddeee7a1eddf82e27976caab62ba3a5183c1654007d706d232ac2fa89"
GAME = {"game_id": "afd2fc507bb69843", "title": "Metal Gear Solid - VR Missions", "platform": "psx"}
WORKERS = [
    {"id": "spark", "os": "linux", "online": True, "tools": ["characters", "a", "b", "c", "d"]},
    {"id": "off", "os": "windows", "online": False, "tools": ["characters", "a", "b", "c", "d"]},
    {"id": "nochar", "os": "windows", "online": True, "tools": ["a", "b", "c", "d"]},
    {"id": "win_big", "os": "windows", "online": True, "tools": ["characters", "a", "b"]},
    {"id": "win_small", "os": "windows", "online": True, "tools": ["characters"]},
]

pytestmark = pytest.mark.skipif(not LIB_GLB.is_file(), reason="library VR Missions Snake GLB is not on this node")


def _collect(monkeypatch, tmp_path, workers, failing=()):
    """Run the real collect() with the decode dispatch and the API answered from the library GLB."""
    glb = LIB_GLB.read_bytes()
    dispatched, calls = [], []

    def api(ctx, method, path, **kw):
        calls.append((method, path))
        if path == "/api/workers":
            return [dict(w) for w in workers]
        if path.startswith("/api/receipts/"):
            return {"artifacts": [{"name": "preview.png", "sha256": "p"},
                                  {"name": "mgs-vr-snake.glb", "sha256": "glbsha"}]}
        if path == "/api/artifacts/glbsha":
            return glb
        raise AssertionError(f"unexpected API call {method} {path}")

    def job(ctx, tool, inp, worker=None, limit=900):
        dispatched.append((tool, dict(inp), worker))
        if worker in failing:
            return {"state": "failed", "error": "decoder crashed", "receipt_id": None}
        return {"state": "succeeded", "receipt_id": "r-" + worker}

    monkeypatch.setenv("GBOX_CHARACTERS", str(tmp_path / "characters"))
    monkeypatch.setattr(C, "HOST_OS", "linux")
    monkeypatch.setattr(C, "_api", api)
    monkeypatch.setattr(C, "_job", job)
    monkeypatch.setattr(C, "_game", lambda ctx, inp: dict(GAME))
    ctx = types.SimpleNamespace(config=types.SimpleNamespace(cache=tmp_path / "cache"), progress=lambda p, m: None)
    res = C.collect(ctx, C.CharIn(op="collect", game_id=GAME["game_id"]))
    return res, dispatched, calls, tmp_path / "characters"


def test_forced_recollect_extracts_a_retargetable_snake(monkeypatch, tmp_path):
    assert hashlib.sha256(LIB_GLB.read_bytes()).hexdigest() == GLB_SHA
    res, dispatched, calls, root = _collect(monkeypatch, tmp_path, WORKERS)
    assert (res["status"], res["collected"], res["total"], res["retargetable"]) == ("complete", 1, 1, 1)
    entry = res["entries"][0]
    assert (entry["slug"], entry["status"], entry["verified"], entry["retargetable"]) == \
        ("mgs_vr_snake", "extracted", True, True)
    # one decode, on the online Windows worker with the characters tool that has the most tools
    assert dispatched == [("characters", {"op": "mgs_vr_decode", "game_id": GAME["game_id"]}, "win_big")]
    assert ("GET", "/api/receipts/r-win_big") in calls
    meta = C.get(root, "mgs_vr_snake")
    copied = root / "mgs_vr_snake" / meta["model"]
    assert hashlib.sha256(copied.read_bytes()).hexdigest() == GLB_SHA
    roles = meta["rig"]["roles"]
    assert len(roles) == 16 and roles == C.mgs_vr_snake_roles(LIB_GLB)
    lib_meta = LIB_GLB.with_name("meta.json")
    if lib_meta.is_file():                       # the deployed library entry carries the same 16 roles
        assert roles == json.loads(lib_meta.read_text())["rig"]["roles"]
    assert meta["source"]["files"][2] == "0_0.dar:39213.kmd"
    assert C.verify_entry(root, meta)["ok"]
    assert not (tmp_path / "cache" / "characters_build" / "extract" / "mgs_vr_snake").exists()


def test_failed_decode_falls_through_to_the_next_windows_worker(monkeypatch, tmp_path):
    res, dispatched, calls, root = _collect(monkeypatch, tmp_path, WORKERS, failing={"win_big"})
    assert [w for _, _, w in dispatched] == ["win_big", "win_small"]
    assert ("GET", "/api/receipts/r-win_small") in calls
    assert (res["status"], res["retargetable"]) == ("complete", 1)
    assert len(C.get(root, "mgs_vr_snake")["rig"]["roles"]) == 16


def test_without_a_windows_decoder_the_entry_fails_instead_of_an_unrigged_add(monkeypatch, tmp_path):
    res, dispatched, calls, root = _collect(monkeypatch, tmp_path, WORKERS[:3])
    assert dispatched == []
    assert (res["status"], res["collected"], res["retargetable"]) == ("partial", 0, 0)
    entry = res["entries"][0]
    assert entry["status"] == "failed" and not entry["retargetable"]
    assert "No Windows worker could decode the VR Missions Snake model" in entry["error"]
    assert not (root / "mgs_vr_snake" / "meta.json").exists()
