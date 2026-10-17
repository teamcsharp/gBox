"""SM64 Mario body roles (#1370).

gbox.sm64_mario writes Mario's 20 geo-layout animated parts as glTF joints j00..j19 in the order gbox.sm64_swap.MARIO
indexes, but the reader never reported rig.roles, so collect() called the verified Mario "not retargetable". These tests
cover the role reader (names, tree, frame), the backfill of an entry collected before roles existed, and, when the
owned EU ROM is on this node, that Mario retargets onto his own skeleton as the identity.
"""
import json
from pathlib import Path

import numpy as np
import pytest

from gbox import characters as C
from gbox import sm64_swap as sw

EXPECTED = {"hip": "j01", "chest": "j02", "head": "j03", "l_upper": "j05", "l_fore": "j06", "l_hand": "j07",
            "r_upper": "j09", "r_fore": "j10", "r_hand": "j11", "l_thigh": "j13", "l_shin": "j14", "l_foot": "j15",
            "r_thigh": "j17", "r_shin": "j18", "r_foot": "j19"}
# Mario's joint tree and world positions in the standing idle (anim 197), read from the owned
# Super Mario 64 (Europe) (En,Fr,De) ROM (NSMP, sha1 4ac5721683d0e0b6bbb561b58a71740845dceea9).
PARENT = [-1, 0, 1, 2, 2, 4, 5, 6, 2, 8, 9, 10, 1, 12, 13, 14, 1, 16, 17, 18]
WORLD = [(0, 0, 0), (0, 0, 0), (0, 68, 1.1), (0, 152.8, 20.5),
         (79, 135.5, 6.3), (79, 135.5, 6.3), (137, 114.6, -14.2), (153.6, 74.1, 26.9),
         (-79, 136.5, 6.5), (-79, 136.5, 6.5), (-136.1, 110.7, -10.6), (-150, 79.7, 38.9),
         (42, 13.1, -7.8), (42, 13.1, -7.8), (83.6, -63, 12.1), (62.5, -125.3, -0.2),
         (-42, 13.1, -7.8), (-42, 13.1, -7.8), (-78.7, -58.5, 30.1), (-73.4, -125.1, 24.6)]
ROM = Path("/home/ehm_eckx/gbox-cache/66062703301f4969/rom.z64")


def _gltf(d: Path, world=WORLD, parent=PARENT, name="sm64_mario.gltf") -> Path:
    """A skeleton-only glTF shaped like gbox.sm64_mario's output (node matrices, one skin over j00..j19)."""
    nodes = []
    for k, w in enumerate(world):
        t = np.asarray(w, float) - (np.asarray(world[parent[k]], float) if parent[k] >= 0 else 0)
        m = np.eye(4)
        m[:3, 3] = t
        nodes.append({"name": f"j{k:02d}", "matrix": m.T.reshape(16).tolist()})
    for k, p in enumerate(parent):
        if p >= 0:
            nodes[p].setdefault("children", []).append(k)
    nodes.append({"name": "mario", "skin": 0})
    gl = {"asset": {"version": "2.0"}, "scene": 0, "scenes": [{"nodes": [0, len(nodes) - 1]}], "nodes": nodes,
          "skins": [{"joints": list(range(len(world)))}], "buffers": [], "bufferViews": [], "accessors": []}
    path = d / name
    path.write_text(json.dumps(gl))
    return path


def test_roles_follow_the_sm64_swap_joint_order(tmp_path):
    roles = C.sm64_mario_roles(_gltf(tmp_path))
    assert roles == EXPECTED
    assert roles == {r: f"j{k:02d}" for r, k in sw.MARIO.items()}


def test_mirrored_mario_is_refused(tmp_path):
    mirrored = [(-x, y, z) for x, y, z in WORLD]
    with pytest.raises(ValueError, match=r"left \+X"):
        C.sm64_mario_roles(_gltf(tmp_path, mirrored))


def test_rewired_hand_is_refused(tmp_path):
    parent = list(PARENT)
    parent[7] = 2                                          # left hand hung on the torso, not the forearm
    with pytest.raises(ValueError, match="l_hand under l_fore"):
        C.sm64_mario_roles(_gltf(tmp_path, parent=parent))


def test_other_skeleton_is_refused(tmp_path):
    with pytest.raises(ValueError, match="20-joint"):
        C.sm64_mario_roles(_gltf(tmp_path, WORLD[:19], PARENT[:19]))


def test_backfill_adds_roles_to_a_verified_entry_once(tmp_path):
    root = tmp_path / "lib"
    d = root / "mario_66062703301f4969"
    d.mkdir(parents=True)
    model = _gltf(d)
    meta = C.put_meta(root, {"slug": d.name, "name": "Mario", "model": model.name,
                             "rig": {"skinned": True, "joints": 20}})
    assert C.backfill_roles(root, "melee", meta) == meta    # no role reader for that extractor: untouched
    out = C.backfill_roles(root, "sm64", meta)
    assert out["rig"] == {"skinned": True, "joints": 20, "roles": EXPECTED}
    assert json.loads((d / "meta.json").read_text())["rig"]["roles"] == EXPECTED
    assert C.backfill_roles(root, "sm64", out) is out       # already mapped: no rewrite


def test_backfill_leaves_a_refused_model_unmapped(tmp_path):
    root = tmp_path / "lib"
    d = root / "mario_x"
    d.mkdir(parents=True)
    model = _gltf(d, [(-x, y, z) for x, y, z in WORLD])
    meta = C.put_meta(root, {"slug": d.name, "name": "Mario", "model": model.name, "rig": {"joints": 20}})
    assert C.backfill_roles(root, "sm64", meta) == meta
    assert "roles" not in json.loads((d / "meta.json").read_text())["rig"]


def test_collect_reports_the_existing_mario_retargetable_without_reextracting(tmp_path, monkeypatch):
    root = tmp_path / "lib"
    d = root / "mario_66062703301f4969"
    d.mkdir(parents=True)
    model = _gltf(d)
    C.put_meta(root, {"slug": d.name, "name": "Mario", "model": model.name, "rig": {"skinned": True, "joints": 20}})
    game = {"game_id": "66062703301f4969", "title": "Super Mario 64 (Europe) (En,Fr,De)", "platform": "n64"}
    entry = {"key": "MARIO", "slug": d.name, "name": "Mario", "kind": "character", "aliases": ["SM64 Mario"]}

    def reextract(*_a):
        raise AssertionError("a verified entry was re-extracted")
    monkeypatch.setattr(C, "_game", lambda ctx, inp: game)
    monkeypatch.setattr(C, "library_root", lambda cfg=None: root)
    monkeypatch.setattr(C, "dedicated_entries", lambda cfg, g, name, roster: [dict(entry)])
    monkeypatch.setattr(C, "verify_entry", lambda r, m: {"ok": True})
    monkeypatch.setattr(C, "_doa2_needs_refresh", lambda ctx, g, m: False)
    monkeypatch.setattr(C, "DEDICATED", [("sm64", lambda t, p: "super mario 64" in t and p == "n64", None, reextract)])

    class Ctx:
        config = None

        def progress(self, *_a):
            pass
    res = C.collect(Ctx(), None)
    assert (res["status"], res["collected"], res["retargetable"]) == ("complete", 1, 1)
    assert res["entries"][0]["retargetable"] is True and res["entries"][0]["message"] == ""
    assert json.loads((d / "meta.json").read_text())["rig"]["roles"] == EXPECTED


@pytest.mark.skipif(not ROM.is_file(), reason="owned Super Mario 64 (Europe) ROM is not on this node")
def test_mario_retargets_onto_himself_as_the_identity(tmp_path):
    from gbox import n64_rom
    from gbox import sm64_mario as sm
    rom = n64_rom.read(ROM)
    out = tmp_path / "sm64_mario.gltf"
    sm.to_gltf(sm.extract(rom, anim=sw.ANIM), out)
    roles = C.sm64_mario_roles(out)
    assert roles == EXPECTED
    rig = sw.load_rig(out, roles)
    tgt = sw.mario_target(rom)
    assert np.abs(rig["joints"] - tgt["T"]).max() < 1e-3
    prims, rep = sw.retarget(rig, tgt)
    assert rep["facing"] == [[1, 0, 0], [0, 1, 0], [0, 0, 1]]
    assert (rep["scale"], rep["shoulder_widen"], rep["head_scale"]) == (1.0, 1.0, 1.0)
    assert set(rep["limb_stretch"].values()) == {1.0} and len(rep["roles_used"]) == 15
    before = np.concatenate([p["pos"] for p in rig["prims"]])
    after = np.concatenate([p["pos"] for p in prims])
    assert np.abs(before - after).max() < 1e-3
    owner = np.concatenate([p["owner"] for p in rig["prims"]])
    joint = np.concatenate([p["J"][:, 0] for p in prims])
    limbs = ~np.isin(owner, [1, 2])                        # retarget splits the torso between hip and chest by height
    assert (owner[limbs] == joint[limbs]).all()
