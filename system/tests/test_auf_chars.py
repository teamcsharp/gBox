"""Tests for gbox.auf_chars: 007 Agent Under Fire GC characters collected into the library (characters op=collect).

Synthetic tests reuse test_auf_swap's level package (entity scripts, body + head models, textures, shaders) and tiny
GameCube disc image, so the roster -> extraction calls, the head merge, the library frame, the entry meta and the
cast-swap donor gate are pinned without the game. The owned-disc tests run where the GCZ is cached (GBOX_AUF_GCZ or
~/gBox_alt/gbox-cache/gc/<game>/source.gcz) and skip elsewhere.
"""
import os
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from gbox import auf_chars as A
from gbox import auf_gcm as G
from gbox import auf_ngc as N
from gbox import auf_swap as S
from gbox import characters as C
from test_auf_swap import gc_image, level_package

GCZ = os.environ.get("GBOX_AUF_GCZ", os.path.expanduser("~/gBox_alt/gbox-cache/gc/65b7187589166b26/source.gcz"))
GAME = {"game_id": S.GAME_ID, "title": "007 - Agent Under Fire (USA)", "platform": "gamecube"}


# ----------------------------------------------------------------------------------------------- roster

def test_roster_is_every_body_as_a_collectable_character():
    ros = A.roster()
    assert [r["key"] for r in ros] == [r["slot"][len("model:"):] for r in S.roster()]     # same bodies, same order
    assert len(ros) == len(S.NAMES) == len({r["slug"] for r in ros})
    for r in ros:
        assert r["kind"] == "character" and r["slug"] == f"auf_{r['key']}" and r["name"] == S.NAMES[r["key"]][0]
        assert r["slot"] == f"model:{r['key']}" and r["role"] == S.NAMES[r["key"]][1]
        assert r["level"] in r["levels"] and r["key"] in S.level_keys()[r["level"]]
        assert set(S.MEN[r["key"]].split()) <= set(r["aliases"]) and r["key"] in r["aliases"]
    by = {r["key"]: r for r in ros}
    # the 16 multiplayer characters, named by their mp_player_<name> scripts (classname DeathmatchPlayer)
    assert {k for k, r in by.items() if r["multiplayer"]} == set(S.MP_KEYS)
    assert by["griffin_body"]["mp_names"] == ["griffen"] and "griffen" in by["griffin_body"]["aliases"]
    assert by["zero_body"]["mp_names"] == ["bloch"] and by["zero_body"]["classnames"] == ["DeathmatchPlayer"]
    assert by["bond_tux"]["classnames"] == ["DeathmatchPlayer", "Player", "actor"]
    # one representative level per body: a mission level when there is one, else the first multiplayer map
    assert by["bond_tux"]["level"] == "alp1_1" and by["zero_body"]["level"] == "dm1"
    assert by["vip_body"]["level"] == "dmescort" and by["griffin_body"]["level"] == "emstel_1"


def test_dedicated_reader_collects_characters_and_the_writer_keeps_its_slots():
    from gbox import char_coverage as CC
    name, test, roster, _run = next(d for d in C.DEDICATED if d[0] == "auf")
    assert test("007 - agent under fire (usa)", "gamecube") and roster() == A.roster()
    ex, ros = CC.extractor_for(GAME)
    assert ex == "auf" and len(ros) == len(S.NAMES)                    # collectable now (kind character)
    assert all(r["kind"] == "slot" and r["collect"] is False for r in S.roster())
    slots = CC.cast_slots(GAME)
    assert slots[0]["slot"] == "player" and len(slots) == len(S.cast_slots())
    assert C.reader_version("auf") == A.READER_VERSION >= 2
    assert C.reader_status({"auf_reader": A.READER_VERSION}, "auf")["stale"] is False
    assert C.reader_status({}, "auf")["stale"] is True                 # an entry from before v2 is re-extracted


def test_pick_prefers_high_lod_and_mission_entities():
    c = S.Character
    cast = [c("models/mp_player_x.men", "deathmatchplayer", "x", ["a/x_l.gcm"], ["h/x_head_l.gcm"]),
            c("models/actor_x2.men", "actor", "x", ["a/x_h.gcm", "a/x_m.gcm", "a/x_l.gcm"], ["h/x_head_h.gcm"]),
            c("models/actor_x1.men", "actor", "x", ["a/x_h.gcm", "a/x_l.gcm"], ["h/x_head_h.gcm"]),
            c("models/bond.men", "player", "y", ["a/y_h.gcm"], [])]
    assert A.pick(cast, "x").men == "models/actor_x1.men" and A.pick(cast, "z") is None
    assert A._best_lod(cast[1].bodies) == "a/x_h.gcm" and A.lod_of("a/twins_mp.gcm") == ""


# ----------------------------------------------------------------------------------------------- the model

def test_head_merge_moves_the_head_onto_the_body_skeleton():
    def bone(i, parent, h, pos):
        return {"index": i, "parent": parent, "hash": h, "rot": np.eye(3).tolist(), "world_pos": list(pos)}
    body = {"bones": [bone(0, -1, 0xA, (0, 0, 0)), bone(1, 0, 0xB, (0, 0, 80))],
            "positions": [[0, 0, 0], [1, 0, 0], [0, 1, 0]], "normals": [[0, 0, 1]] * 3, "uvs": [[0, 0]] * 3,
            "joints": [[0, 0]] * 3, "weights": [[1.0, 0.0]] * 3, "faces": [(0, 1, 2, 0)], "shaders": [0x11]}
    # the head model's own rest pose sits 5 units lower; face bone 0xF hangs off the head, 0xE is an unused root
    head = {"bones": [bone(0, -1, 0xA, (0, 0, 0)), bone(1, 0, 0xB, (0, 0, 75)), bone(2, 1, 0xF, (2, 0, 78)),
                      bone(3, -1, 0xE, (0, 0, 0))],
            "positions": [[0, 0, 76], [1, 0, 76], [0, 1, 79]], "normals": [[0, 0, 1]] * 3, "uvs": [[0.5, 0.5]] * 3,
            "joints": [[1, 1], [1, 1], [2, 1]], "weights": [[1.0, 0.0], [1.0, 0.0], [0.7, 0.3]],
            "faces": [(0, 1, 2, 0), (2, 1, 0, 1)], "shaders": [0x21, 0x22]}
    m = A.merge_head(body, head, fallback=1)
    P = np.asarray(m["positions"])
    assert np.allclose(P[3:5, 2], 81) and np.isclose(P[5, 2], 84)
    assert m["joints"][3:] == [[1, 1], [1, 1], [1, 1]] and m["weights"][5] == [1.0, 0.0]
    assert m["faces"][1:] == [(3, 4, 5, 1), (5, 4, 3, 2)] and m["shaders"] == [0x11, 0x21, 0x22]
    head["joints"][0] = [3, 3]                          # a vertex on a bone the body lacks needs the fallback
    with pytest.raises(ValueError):
        A.merge_head(body, head)


def test_export_is_rigged_textured_and_in_the_library_frame(tmp_path):
    pkg = N.NgcPackage(level_package())
    r = A.extract_body(pkg, "body", tmp_path / "auf_body.glb", "Body")
    assert r["body"] == "models/actors/test/body_l.gcm" and r["head"] == "models/actors/actorheads/head_l.gcm"
    assert r["classname"] == "DeathmatchPlayer" and r["animations"] == "mp_player_male" and r["lod"] == "l"
    body_tris = len(N.mesh(pkg.read(r["body"]))["faces"])
    assert r["triangles"] > body_tris and r["textures"] >= 2 and len(r["roles"]) == 18
    gl = C._load(r["path"])[0]
    assert len(gl["materials"]) == r["sections"] and all("baseColorTexture" in m["pbrMetallicRoughness"]
                                                         for m in gl["materials"])
    assert all(m.get("alphaMode", "OPAQUE") == "OPAQUE" for m in gl["materials"])
    rig = C.rig_from_gltf(r["path"], r["roles"])
    J, ro = np.asarray(rig["joints"]), rig["roles"]
    assert J[ro["head"], 1] > J[ro["chest"], 1] > J[ro["hip"], 1] > J[ro["l_foot"], 1]   # +Y up
    assert J[ro["l_hand"], 0] > 0 > J[ro["r_hand"], 0]                                    # left +X
    toe = [i for i, p in enumerate(rig["parent"]) if p == ro["l_foot"]][0]
    assert J[toe, 2] > J[ro["l_foot"], 2]                                                  # toes toward +Z


# ----------------------------------------------------------------------------------------------- collect

def _collect_env(monkeypatch, tmp_path, image, entries=None):
    monkeypatch.setattr(C, "_game", lambda ctx, inp: GAME)
    monkeypatch.setattr(C, "library_root", lambda cfg: tmp_path / "lib")
    monkeypatch.setattr(C, "_rom", lambda ctx, g: image)
    if entries is not None:
        monkeypatch.setattr(A, "roster", lambda: entries)
    calls = []
    real = A.extract_body
    monkeypatch.setattr(A, "extract_body", lambda pkg, key, out, name="": calls.append((key, out.name))
                        or real(pkg, key, out, name))
    return SimpleNamespace(config=SimpleNamespace(cache=str(tmp_path / "cache")), progress=lambda *a: None), calls


def test_collect_extracts_every_roster_body_with_meta_and_roles(monkeypatch, tmp_path):
    from gbox import cast_swap as CS, doa2_weighted_retarget as WR
    A._level.cache_clear()
    image = gc_image(tmp_path / "auf.iso", {"maps/dm1.ngc": level_package(), "opening.bnr": b"x" * 64})
    entries = [{"key": "body", "slug": "auf_body", "name": "Body", "kind": "character", "aliases": ["Body", "body"],
                "role": "bot", "slot": "model:body", "men": ["mp_player_test"], "multiplayer": True,
                "mp_names": ["test"], "level": "dm1"},
               {"key": "other", "slug": "auf_other", "name": "Other", "kind": "character", "aliases": ["Other"],
                "role": "npc", "slot": "model:other", "men": ["mp_player_other"], "level": "dm1"}]
    ctx, calls = _collect_env(monkeypatch, tmp_path, image, entries)
    res = C.collect(ctx, C.CharIn(op="collect", game_id=GAME["game_id"]))
    assert calls == [("body", "auf_body.glb"), ("other", "auf_other.glb")]
    assert res["status"] == "complete" and res["collected"] == res["retargetable"] == res["characters"] == 2
    assert res["extractor"] == "auf" and res["reader_version"] == A.READER_VERSION
    assert res["slots"][0]["slot"] == "player"                                  # the writer's cast menu is kept
    root = tmp_path / "lib"
    metas = [C.get(root, e["slug"]) for e in res["entries"]]
    m = metas[0]
    assert m["auf_reader"] == A.READER_VERSION and m["auf_slot"] == "model:body" and m["auf_level"] == "dm1"
    assert m["auf_classname"] == "DeathmatchPlayer" and m["auf_men"] == "models/mp_player_test.men"
    assert m["auf_multiplayer"] is True and m["auf_mp_names"] == ["test"] and m["kind"] == "character"
    assert m["source"]["files"][0] == "maps/dm1.ngc:models/actors/test/body_l.gcm"
    assert m["extraction_tool"].startswith("gbox.auf_chars") and m["rig"]["skinned"]
    roles = m["rig"]["roles"]
    assert set(roles) == set(G.auto_roles(N.skeleton(N.NgcPackage(level_package()).read(
        "models/actors/test/body_l.gcm")))) and "hip" in roles
    # the cast swap's donor gate (roles, hip, model check, reader version) and the retarget rig accept them
    donors, refused, _ = CS.gate(metas, root)
    assert [d["slug"] for d in donors] == ["auf_body", "auf_other"] and refused == []
    assert all(CS.retarget_check(x, root) is None for x in metas)
    assert {"hip", "head"} <= WR.load_rig(root / m["slug"] / m["model"], roles)["roles"].keys()
    # collected once: a second run finds them in the collection
    again = C.collect(ctx, C.CharIn(op="collect", game_id=GAME["game_id"]))
    assert len(calls) == 2 and {e["status"] for e in again["entries"]} == {"in_collection"}


def test_entry_without_its_body_in_the_level_fails_alone(monkeypatch, tmp_path):
    A._level.cache_clear()
    image = gc_image(tmp_path / "auf.iso", {"maps/dm1.ngc": level_package()})
    entries = [{"key": "body", "slug": "auf_body", "name": "Body", "kind": "character", "aliases": [], "level": "dm1"},
               {"key": "ghost", "slug": "auf_ghost", "name": "Ghost", "kind": "character", "aliases": [],
                "level": "dm1"}]
    ctx, _calls = _collect_env(monkeypatch, tmp_path, image, entries)
    res = C.collect(ctx, C.CharIn(op="collect", game_id=GAME["game_id"]))
    assert res["status"] == "partial" and res["collected"] == 1
    bad = res["entries"][1]
    assert bad["status"] == "failed" and "ghost" in bad["error"]


# ----------------------------------------------------------------------------------------------- owned disc

@pytest.mark.skipif(not os.path.exists(GCZ), reason="owned AUF GCZ not cached")
def test_owned_every_body_has_an_entity_in_its_level():
    A._level.cache_clear()
    by_level = {}
    for e in A.roster():
        by_level.setdefault(e["level"], []).append(e["key"])
    for lv, keys in sorted(by_level.items()):
        cast = S.level_cast(N.NgcPackage(A.level_bytes(Path(GCZ), lv)))
        for k in keys:
            c = A.pick(cast, k)
            assert c is not None and A._best_lod(c.bodies), (lv, k)


@pytest.mark.skipif(not os.path.exists(GCZ), reason="owned AUF GCZ not cached")
def test_owned_collect_bond_a_multiplayer_body_and_a_headless_body(monkeypatch, tmp_path):
    from gbox import cast_swap as CS, doa2_weighted_retarget as WR
    A._level.cache_clear()
    keep = {"bond_tux", "zero_body", "malprave_gown"}
    entries = [e for e in A.roster() if e["key"] in keep]
    ctx, calls = _collect_env(monkeypatch, tmp_path, Path(GCZ), entries)
    res = C.collect(ctx, C.CharIn(op="collect", game_id=GAME["game_id"]))
    assert res["status"] == "complete" and res["retargetable"] == 3 and len(calls) == 3
    root = tmp_path / "lib"
    metas = {e["slug"]: C.get(root, e["slug"]) for e in res["entries"]}
    bond = metas["auf_bond_tux"]
    assert bond["auf_level"] == "alp1_1" and bond["auf_classname"] == "Player" and bond["auf_lod"] == "h"
    assert bond["source"]["files"][:2] == ["maps/alp1_1.ngc:models/actors/bond/bond_tux_h.gcm",
                                           "maps/alp1_1.ngc:models/actors/actorheads/bond_head_h.gcm"]
    assert bond["stats"]["triangles"] == 806 + 650 and bond["stats"]["textures"] >= 4      # body + head
    assert metas["auf_zero_body"]["auf_classname"] == "DeathmatchPlayer" and metas["auf_zero_body"]["auf_mp_names"] == ["bloch"]
    assert metas["auf_malprave_gown"]["auf_head_sha1"] is None                             # her head is in the body
    donors, refused, _ = CS.gate(list(metas.values()), root)
    assert len(donors) == 3 and refused == []
    for m in metas.values():
        rig = WR.load_rig(root / m["slug"] / m["model"], m["rig"]["roles"])
        J = rig["joints"]
        assert J[rig["roles"]["head"], 1] - J[rig["roles"]["l_foot"], 1] > 60          # standing, native units
