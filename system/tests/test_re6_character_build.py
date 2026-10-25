"""RE6's existing Xbox 360 file writer: fit propagation and explicit target selection.

The native-output fixture is synthetic. It exercises glTF loading, the real retarget,
MOD encoding/decoding and ARC compression, without a game, emulator or donor library.
"""
from pathlib import Path
from types import SimpleNamespace
import copy
import struct

import numpy as np
import pytest

from gbox import characters as C, re6, re6_models as M, re6_tool as T


def ctx(tmp_path):
    return SimpleNamespace(config=SimpleNamespace(cache=tmp_path), progress=lambda *a: None,
                           artifact=lambda *a, **kw: None)


def donor():
    return {"slug": "sonic", "name": "Sonic", "rig": {"roles": {"hip": "hip", "head": "head"}}}


def inp(**kw):
    return SimpleNamespace(**({"slot": "player", "target": "", "scale": {}, "session_id": "",
                              "rebuild": False, "launch": False} | kw))


def test_build_uses_explicit_target_costume_and_saved_fit_for_product_and_preview(tmp_path, monkeypatch):
    meta = donor()
    meta["retarget_profiles"] = {re6.GAME_ID: {"player": {"head": 1.3, "roles": {"head": "new_head"}}}}
    original = copy.deepcopy(meta)
    calls = []
    monkeypatch.setattr(T, "base", lambda *a: tmp_path)
    monkeypatch.setattr(T, "fetch_model", lambda *a: tmp_path / "donor.gltf")

    def swap(base, model, roles, target, costume, slug, preview=None, scale=None):
        calls.append((roles, target, costume, preview, scale))
        return {"files": {f"{target}-{costume}": b"native"}, "triangles": 1, "hidden_parts": [], "notes": []}

    monkeypatch.setattr(M, "build_swap", swap)
    written = []
    monkeypatch.setattr(T, "build_mod_folder", lambda cfg, name, files, meta: written.append(meta) or {"mod": name})
    result = T.build_character(ctx(tmp_path), meta, "ChRiS", "europe")
    assert result["target"] == "chris" and result["costumes"] == ["Europe"]
    assert result["mod"].startswith("re6_sonic_chris_Europe_fit")
    assert written[0]["target"] == "chris"
    assert len(calls) == 2 and calls[1][3] is not None
    for roles, target, costume, preview, scale in calls:
        assert (target, costume) == ("chris", "Europe")
        assert roles["head"] == "new_head" and scale["profile"]["head"] == 1.3
    assert meta == original


def test_use_preserves_target_and_scale_without_inventing_active_target(tmp_path, monkeypatch):
    monkeypatch.setattr(C, "HOST_OS", "windows")
    monkeypatch.setattr(T, "mod_dir", lambda cfg, name: tmp_path / name)
    calls, records = [], []
    monkeypatch.setattr(T, "build_character", lambda *a, **kw: calls.append((a, kw)) or {"mod": "built"})
    monkeypatch.setattr(C, "_api", lambda *a, **kw: records.append((a, kw)))
    result = T.use(ctx(tmp_path), donor(), {"game_id": re6.GAME_ID}, inp(target="Chris", scale={"head": 1.2}))
    assert result["target"] == "chris" and result["mod"].startswith("re6_sonic_chris_fit")
    assert calls[0][0][2] == "chris" and calls[0][1]["scale"] == {"head": 1.2}
    assert "Chris" in result["replaces"] and "Leon" not in result["replaces"]
    assert "Chris" in records[0][1]["json"]["notes"]
    assert result["requires_relaunch"] and result["realtime"] is False


def test_windows_handoff_preserves_explicit_target_and_fit(tmp_path, monkeypatch):
    monkeypatch.setattr(C, "HOST_OS", "linux")
    monkeypatch.setattr(T, "mod_dir", lambda cfg, name: tmp_path / name)
    monkeypatch.setattr(C, "_api", lambda *a, **kw: [{"id": "windows", "os": "windows", "online": True}])
    sent = []
    monkeypatch.setattr(C, "_job", lambda c, tool, args, node, timeout:
                        sent.append(args) or {"output": {"result": {"target": args["target"]}}})
    result = T.use(ctx(tmp_path), donor(), {"game_id": re6.GAME_ID}, inp(target="ada", scale={"head": .9}))
    assert result["target"] == "ada" and sent[0]["target"] == "ada"
    assert sent[0]["scale"] == {"head": .9} and sent[0]["launch"] is False


def test_relaunch_keeps_requested_target_even_when_session_metadata_names_another(tmp_path, monkeypatch):
    monkeypatch.setattr(C, "HOST_OS", "windows")
    monkeypatch.setattr(C, "_session", lambda *a: {"session_id": "windows-old", "game_id": re6.GAME_ID,
                                                  "mod": "re6_other", "character": "leon"})
    monkeypatch.setattr(T, "mod_dir", lambda cfg, name: tmp_path / name)
    monkeypatch.setattr(T, "build_character", lambda *a, **kw: {"mod": "built"})
    jobs = []

    def api(c, method, path, **kw):
        if path == "/api/jobs":
            jobs.append(kw["json"])
            return {"id": "launch"}
        return {"state": "succeeded", "output": {"session_id": "windows-new"}}

    monkeypatch.setattr(C, "_api", api)
    result = T.use(ctx(tmp_path), donor(), {"game_id": re6.GAME_ID},
                   inp(target="sherry", launch=True, session_id="windows-old"))
    assert result["target"] == "sherry" and "sherry" in jobs[0]["input"]["mod"]
    assert jobs[0]["input"]["node"] == "windows"
    assert "Sherry" in result["message"] and "Choose sherry" in result["message"]
    assert "Leon" not in result["message"]


def test_all_costumes_and_explicit_scale_override_are_preserved_in_build(tmp_path, monkeypatch):
    meta = donor()
    meta["retarget_profiles"] = {re6.GAME_ID: {"player": {"head": 1.1}}}
    calls = []
    monkeypatch.setattr(T, "base", lambda *a: tmp_path)
    monkeypatch.setattr(T, "fetch_model", lambda *a: tmp_path / "donor.gltf")

    def swap(*args, **kw):
        calls.append((args[3], args[4], kw["scale"]))
        return {"files": {}, "triangles": 1, "hidden_parts": [], "notes": []}

    monkeypatch.setattr(M, "build_swap", swap)
    monkeypatch.setattr(T, "build_mod_folder", lambda cfg, name, files, meta: {"mod": name})
    result = T.build_character(ctx(tmp_path), meta, "ada", scale={"profile": {"head": 1.4}})
    assert result["costumes"] == M.CHARACTERS["ada"]["costumes"]
    assert [c[1] for c in calls[:-1]] == M.CHARACTERS["ada"]["costumes"]
    assert all(c[0] == "ada" and c[2]["profile"]["head"] == 1.4 for c in calls)


def test_default_target_and_fit_cache_identity_are_explicit():
    assert T._character_choice("")[0] == "leon"
    assert T._character_mod_name(donor(), "leon") == "re6_sonic"
    a = donor()
    a["rig"]["scale"] = {"profile": {"head": 1.2}}
    b = copy.deepcopy(a)
    b["rig"]["scale"]["profile"]["head"] = 1.4
    assert T._character_mod_name(a, "chris") != T._character_mod_name(b, "chris")
    assert T._character_mod_name(a, "chris", "Asia") != T._character_mod_name(a, "chris", "Europe")


@pytest.mark.parametrize("target,costume", [("agent", ""), ("chris", "Usa")])
def test_invalid_native_target_or_costume_fails_before_disc_io(tmp_path, monkeypatch, target, costume):
    monkeypatch.setattr(T, "base", lambda *a: pytest.fail("must validate before disc I/O"))
    with pytest.raises(ValueError):
        T.build_character(ctx(tmp_path), donor(), target, costume)


def test_capabilities_does_not_start_watcher_or_claim_realtime_support(tmp_path, monkeypatch):
    monkeypatch.setattr(T, "ensure_watcher", lambda *a: pytest.fail("static capabilities started a watcher"))
    result = T.re6_tool(T.Re6In(op="capabilities"), ctx(tmp_path))["result"]
    support = result["character_replacement"]
    assert result["platform"] == "xbox360" and result["backend"] == "xenia"
    assert support["build_mod"] and support["relaunch"] and support["requires_relaunch"]
    assert support["realtime"] is False and support["active_target_detection"] is False
    assert support["animation_retarget"] is False
    assert {t["id"] for t in support["targets"]} == set(M.CHARACTERS)
    assert set(result["unsupported_platforms"]) == {"pc", "ps3", "ps4"}


def test_combined_build_forwards_player_and_enemy_profiles(tmp_path, monkeypatch):
    meta = donor()
    meta["retarget_profiles"] = {re6.GAME_ID: {"player": {"head": 1.1}, "enemies": {"head": 1.2},
                                                "enemy:zombie_male": {"head": 1.3}}}
    monkeypatch.setattr(T, "base", lambda *a: tmp_path)
    monkeypatch.setattr(T, "_meta", lambda *a: meta)
    monkeypatch.setattr(T, "fetch_model", lambda *a: tmp_path / "donor.gltf")
    monkeypatch.setattr(M, "propagate", lambda base, files: files)
    monkeypatch.setattr(T, "build_mod_folder", lambda cfg, name, files, meta: {"mod": name})
    calls = []

    def player_swap(*args, **kw):
        calls.append(("player", kw["scale"]["profile"]["head"]))
        return {"files": {}}

    def enemy_swap(base, family, *args, **kw):
        calls.append((family, kw["scale"]["profile"]["head"]))
        return {"files": {}, "models": [], "textures": 0}

    monkeypatch.setattr(M, "build_swap", player_swap)
    monkeypatch.setattr(M, "build_enemy_swap", enemy_swap)
    T.build_combined(ctx(tmp_path), {"zombie_male": "sonic", "zombie_female": "sonic"}, player="sonic")
    assert calls == [("player", 1.1)] * len(M.CHARACTERS["leon"]["costumes"]) + [
        ("zombie_male", 1.3), ("zombie_female", 1.2)]
    assert "scale" not in meta["rig"]


def _native_fixture(tmp_path):
    from tests.test_retarget_profile import donor_rig, POS
    from gbox.melee_models import write_gltf

    rig = donor_rig(weighted=True)
    joints = []
    for parent, p in zip(rig["parent"], rig["joints"]):
        world = np.eye(4)
        world[:3, 3] = p
        joints.append({"parent": parent, "world": world})
    model = tmp_path / "donor.gltf"
    write_gltf(model, joints, rig["prims"], joint_names=rig["names"])

    # A small but valid native skeleton and MOD, containing every role the player writer requires.
    m = M.Mod.__new__(M.Mod)
    roles = list(M.RE6_ROLE_IDS)
    positions = {r: np.asarray(POS.get(r, POS["hip"]), float) * 80 for r in roles}
    positions["pelvis"] = positions["hip"]
    m.bones = [[M.RE6_ROLE_IDS[r], 255, 0, 0, 0., 0., *positions[r]] for r in roles]
    m.local = np.tile(np.eye(4), (len(roles), 1, 1))
    for i, r in enumerate(roles):
        m.local[i, 3, :3] = positions[r]
    m.inv = np.tile(np.eye(4), (len(roles), 1, 1))
    m.remap, m.groups, m.ng = bytes(256), bytes(32), 1
    m.mat_hashes, m.info, m.tail = [0x12345678], bytearray(64), b""
    seed = {"pos": np.array([[0., 80, 0], [10., 80, 0], [0., 90, 0]]),
            "nrm": np.tile([0., 0, 1], (3, 1)), "uv": np.zeros((3, 2)),
            "J": np.zeros((3, 4), int), "tris": np.array([[0, 1, 2]])}
    native = M.write_body(m, [seed], 0, 1, 65015)
    name = r"data\chara\pl\pl0200\model\pl0200"
    arc = re6.Arc(struct.pack(">4sHH", b"\0CRA", 7, 0))
    arc.put(name, "mod", native)
    directory = M.arc_dir(tmp_path)
    directory.mkdir(parents=True)
    (directory / "uPl02ChrisEurope.arc").write_bytes(arc.build())
    return model, {r: r for r in rig["roles"]}, name, native


def test_profile_changes_real_native_writer_output_without_changing_target_skeleton(tmp_path):
    model, roles, name, native = _native_fixture(tmp_path)
    args = (tmp_path, model, roles, "chris", "Europe", "synthetic_donor")
    plain = M.build_swap(*args)
    fitted = M.build_swap(*args, scale={"profile": {"head": 1.3, "torso_width": 1.2}})
    path = "nativeXenon/arc/X360/uPl02ChrisEurope.arc"
    assert set(plain["files"]) == {path} == set(fitted["files"])
    assert plain["files"][path] != fitted["files"][path]
    a = M.Mod(re6.Arc(plain["files"][path]).get(name))
    b = M.Mod(re6.Arc(fitted["files"][path]).get(name))
    assert a.ntri == b.ntri > 0
    assert np.max(np.abs(a.decode(a.prims[0])["pos"] - b.decode(b.prims[0])["pos"])) > 1.0
    np.testing.assert_allclose(a.world(), M.Mod(native).world())
    np.testing.assert_allclose(b.world(), M.Mod(native).world())


def test_enemy_profile_reaches_real_native_writer(tmp_path, monkeypatch):
    model, roles, name, native = _native_fixture(tmp_path)
    monkeypatch.setattr(M, "enemy_models", lambda *a: [("uPl02ChrisEurope", name)])
    monkeypatch.setattr(M, "_index", lambda *a: {})
    args = (tmp_path, "zombie_male", model, roles, "synthetic_donor")
    plain = M.build_enemy_swap(*args)
    fitted = M.build_enemy_swap(*args, scale={"profile": {"head": 1.3}})
    key = "nativeXenon/arc/X360/uPl02ChrisEurope.arc"
    a = M.Mod(re6.Arc(plain["files"][key]).get(name))
    b = M.Mod(re6.Arc(fitted["files"][key]).get(name))
    assert np.max(np.abs(a.decode(a.prims[0])["pos"] - b.decode(b.prims[0])["pos"])) > 1.0
