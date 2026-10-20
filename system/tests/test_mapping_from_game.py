"""Fix a character's mapping from gameplay: the Retarget editor's Turn around (retarget_profile.turn_frame / turn_rig in
the shared retargets), Swap left <-> right (plain role overrides through apply_to_meta), the "mapped wrong" flags kept
beside the profiles, and the cast routes the pick whip resolves the donor in a slot with (gbox/builds.py)."""
import json

import numpy as np
import pytest

from gbox import retarget_profile as RP
from gbox import sm64_swap as S
from tests.test_builds import fixture, get
from tests.test_retarget_api import GID, client  # noqa: F401 - the API fixture
from tests.test_retarget_profile import JMAP, T, donor_rig

TURN = np.diag([-1.0, 1.0, -1.0])


# ---------------------------------------------------------------- Turn around

def test_turn_is_a_profile_flag_that_changes_the_fit():
    assert RP.normalize({"turn": True})["turn"] is True
    assert "turn" not in RP.normalize({"turn": "yes"}) and "turn" not in RP.normalize({"turn": False})
    assert not RP.is_identity({"turn": True}) and RP.is_identity({"turn": False})
    assert RP.digest({"turn": True}) != RP.digest({}) and RP.digest({"turn": True}) != ""
    meta = {"rig": {"roles": {"hip": "pelvis"}}, "retarget_profiles": {GID: {"*": {"turn": True}}}}
    assert RP.apply_to_meta(meta, GID)["rig"]["scale"]["profile"]["turn"] is True   # it reaches the writers
    B = np.eye(3)
    np.testing.assert_array_equal(RP.turn_frame(B, {"turn": True}), TURN)
    assert RP.turn_frame(B, {"head": 2}) is B and RP.turn_frame(B, None) is B


def _turned_target(tgt):
    return {**tgt, "T": np.asarray(tgt["T"], float) @ TURN.T}


@pytest.mark.parametrize("writer", ["sm64", "doa2"])
def test_turn_fits_a_slot_facing_the_other_way_like_a_front_facing_one(writer):
    """A slot skeleton facing -Z: with Turn around the fit is the front-facing fit turned with it, exactly."""
    from gbox.doa2_weighted_retarget import retarget as doa2
    fit = S.retarget if writer == "sm64" else doa2
    rig = donor_rig(weighted=writer == "doa2")
    tgt = {"T": T.copy(), "ground": 0.0, "head_h": 0.4}
    base, _ = fit(rig, tgt, None, JMAP)
    turned, rep = fit(rig, _turned_target(tgt), {"profile": {"turn": True}}, JMAP)
    assert rep["turned"] is True
    np.testing.assert_allclose(turned[0]["pos"], base[0]["pos"] @ TURN.T, atol=1e-9)
    np.testing.assert_allclose(turned[0]["nrm"], base[0]["nrm"] @ TURN.T, atol=1e-9)
    np.testing.assert_array_equal(turned[0]["J"], base[0]["J"])
    unturned, rep2 = fit(rig, _turned_target(tgt), None, JMAP)       # without it: the body is backwards on that slot
    assert "turned" not in rep2
    assert not np.allclose(unturned[0]["pos"], turned[0]["pos"], atol=1e-3)


def test_turn_keeps_the_donor_frame_of_joint_moves_unturned():
    rig = donor_rig()
    B, _ = RP.donor_frame(rig)
    moved, _ = RP.move_joints(rig, RP.normalize({"joints": {"l_fore": [0.05, 0, 0]}, "turn": True}))
    np.testing.assert_allclose(moved["joints"][JMAP["l_fore"]] - rig["joints"][JMAP["l_fore"]], np.array([0.1, 0, 0]) @ B, atol=1e-9)


def test_re4_retarget_turns_its_upright_rig_about_the_hip():
    rig = donor_rig()
    out = RP.turn_rig(rig, {"turn": True})
    hip = rig["joints"][JMAP["hip"]]
    np.testing.assert_allclose(out["joints"][JMAP["l_hand"]], [2 * hip[0] - T[JMAP["l_hand"]][0], T[JMAP["l_hand"]][1],
                                                           2 * hip[2] - T[JMAP["l_hand"]][2]])
    np.testing.assert_allclose(out["prims"][0]["nrm"], rig["prims"][0]["nrm"] @ TURN.T)
    assert RP.turn_rig(rig, {"head": 2}) is rig
    from gbox import re4gc_enemies as E
    assert "turn_rig" in E.retarget.__code__.co_names


# ---------------------------------------------------------------- Swap left <-> right

def test_swapped_sides_saved_as_role_overrides_reach_the_rig_in_any_order():
    roles = {"hip": "pelvis", "head": "head", "l_upper": "armL", "r_upper": "armR", "l_fore": "foreL", "r_fore": "foreR",
             "l_hand": "handL"}
    over = {"l_upper": "armR", "l_fore": "foreR", "l_hand": "", "r_upper": "armL", "r_fore": "foreL", "r_hand": "handL"}
    want = {"hip": "pelvis", "head": "head", "l_upper": "armR", "r_upper": "armL", "l_fore": "foreR", "r_fore": "foreL",
            "r_hand": "handL"}
    for order in (list(over), list(reversed(over))):
        meta = {"rig": {"roles": dict(roles)}, "retarget_profiles": {GID: {"fighter:kas": {"roles": {k: over[k] for k in order}}}}}
        assert RP.apply_to_meta(meta, GID, "fighter:KAS")["rig"]["roles"] == want


def test_a_rig_named_from_the_viewers_side_faces_backwards_until_swapped():
    """The collection's roles name each side's bone from the viewer's side (Wario in SoulCalibur II): the facing turns
    the body around. The editor's swap saves every l_/r_ role with its twin's bone; the build's roles come out right."""
    rig = donor_rig()
    twin = lambda r: (("r_" if r[0] == "l" else "l_") + r[2:]) if r[:2] in ("l_", "r_") else r   # noqa: E731
    wrong = {r: twin(r) for r in JMAP}                       # role -> bone name (bones are named for their real side)
    fix = {r: b for r, b in {r: twin(b) for r, b in wrong.items()}.items() if r[:2] in ("l_", "r_")}
    roles = RP.apply_to_meta({"rig": {"roles": wrong}, "retarget_profiles": {GID: {"*": {"roles": fix}}}}, GID)["rig"]["roles"]
    assert roles == {r: r for r in JMAP}
    as_rig = lambda named: {**rig, "roles": {r: JMAP[b] for r, b in named.items()}}       # noqa: E731
    np.testing.assert_array_equal(S.facing(as_rig(wrong))[2], [0, 0, -1])                # backwards
    np.testing.assert_array_equal(S.facing(as_rig(roles))[2], [0, 0, 1])                 # facing front again


# ---------------------------------------------------------------- "mapped wrong" flags

def test_flags_are_capped_keyed_by_slot_and_cleared_by_that_slots_save():
    meta = {}
    for i in range(25):
        RP.add_flag(meta, GID, "fighter:KAS:all", {"at": i, "session_id": "w1-s1", "note": f"n{i}" + "x" * 600})
    rows = RP.flags_of(meta, GID, "fighter:KAS")
    assert len(rows) == RP.FLAGS_KEEP == 20 and rows[0]["at"] == 5 and rows[-1]["at"] == 24 and len(rows[-1]["note"]) == 500
    RP.add_flag(meta, GID, "kas", {"note": "kept as the bare name"})
    RP.add_flag(meta, GID, "fighter:RYU", {"note": "ryu"})
    assert RP.flags_of(meta, GID, "fighter:KAS")[-1]["note"].startswith("n24")    # its own key first
    assert RP.resolve(meta, GID, "fighter:KAS") is None                           # a flag is no profile
    assert RP.clear_flags(meta, GID, "fighter:KAS") == 21
    assert RP.flags_of(meta, GID, "fighter:KAS") == [] and RP.flags_of(meta, GID, "fighter:RYU")
    assert RP.clear_flags(meta, GID, "") == 1 and "retarget_flags" not in meta   # the game-wide save answers all


def test_flag_route_shows_in_the_editor_view_until_the_slot_is_saved(client):  # noqa: F811
    r = client.post("/api/characters/amy/retarget_profile/flag",
                    json={"game_id": GID, "slot": "fighter:KAS", "session_id": "w1-s1", "note": "arms bend backwards"})
    assert r.status_code == 200 and r.json()["flagged"][-1]["note"] == "arms bend backwards"
    view = client.get(f"/api/characters/amy/retarget_profile?game_id={GID}&slot=fighter:KAS").json()
    assert view["flagged"][0]["session_id"] == "w1-s1" and view["profile"] is None and view["resolved"] is None
    assert client.get(f"/api/characters/amy/retarget_profile?game_id={GID}&slot=fighter:RYU").json()["flagged"] == []
    assert client.post("/api/characters/amy/retarget_profile/flag", json={"game_id": "nope"}).status_code == 422
    assert client.post("/api/characters/nobody/retarget_profile/flag", json={"game_id": GID}).status_code == 404
    saved = client.put("/api/characters/amy/retarget_profile",
                       json={"game_id": GID, "slot": "fighter:KAS", "profile": {"turn": True, "roles": {"l_upper": "armR"}}}).json()
    assert saved["flagged"] == [] and saved["profile"]["turn"] is True
    meta = json.loads((client.lib / "amy" / "meta.json").read_text())
    assert "retarget_flags" not in meta and meta["retarget_profiles"][GID]["fighter:kas"]["turn"] is True


# ---------------------------------------------------------------- the cast routes (pick whip: who is in this slot)

def test_build_cast_lists_the_slots_donors_without_failed_slots(tmp_path):
    from fastapi.testclient import TestClient
    cfg, app, store, h = fixture(tmp_path)
    with TestClient(app) as c:
        assert app.state.built_mods.wait(10)
        r = get(c, h, "/api/builds/g1/cast_g1_wrestlers/cast")
        assert r["mod"] == "cast_g1_wrestlers"
        assert r["rows"] == [{"slot": "neo", "slot_name": "neo", "donor": "kane", "donor_name": "Kane", "status": "built",
                              "build_slot": "neo"}]
        one = get(c, h, "/api/builds/g2/g2_hucast/cast")["rows"]
        assert one == [{"slot": "player", "slot_name": "player", "donor": "kane", "donor_name": "Kane", "status": "",
                        "build_slot": "player"}]
        assert get(c, h, "/api/builds/g1/no_such_build/cast")["rows"] == []


def test_session_cast_follows_the_build_the_session_shows(tmp_path):
    from fastapi.testclient import TestClient
    cfg, app, store, h = fixture(tmp_path)
    store.put("session", "w1-s1", {"session_id": "w1-s1", "game_id": "g1", "mod": "cast_g1_wrestlers~9f", "state": "running"})
    store.put("session", "w1-s2", {"session_id": "w1-s2", "game_id": "g1", "mod": "", "state": "running"})
    store.put("session", "w1-s3", {"session_id": "w1-s3", "game_id": "g2", "mod": "cast_g1_wrestlers",
                                   "live_mod": "g2_hucast", "state": "running"})
    with TestClient(app) as c:
        assert app.state.built_mods.wait(10)
        r = get(c, h, "/api/sessions/w1-s1/cast")                  # a staged copy is the same build
        assert r["mod"] == "cast_g1_wrestlers" and r["game_id"] == "g1" and r["rows"][0]["donor"] == "kane"
        assert get(c, h, "/api/sessions/w1-s2/cast") == {"session_id": "w1-s2", "game_id": "g1", "mod": "", "rows": [],
                                                          "note": "the original game: no build"}
        assert get(c, h, "/api/sessions/w1-s3/cast")["mod"] == "g2_hucast"   # a live hot-swap wins
        get(c, h, "/api/sessions/nope/cast", 404)


# ---------------------------------------------------------------- the writers' own cast records and profile slots

def test_cast_rows_read_soulcalibur2_pairs_and_doa2_rosters_under_their_profile_slots():
    from gbox import builds as B
    lib = {"get": lambda slug: {"name": slug.title()}}
    sc2 = {"cast": [["maxi:1", "wario"], ["taki:1", "luigi"], ["taki:2", "luigi"], ["taki:3", "sonic"]],
           "cast_names": {"taki": "Taki", "maxi": "Maxi"}}
    rows = B.cast_rows(sc2, None, lib)
    assert [(r["slot"], r["slot_name"], r["donor"], r["donor_name"]) for r in rows] == [
        ("fighter:maxi", "Maxi", "wario", "Wario"), ("fighter:taki", "Taki", "luigi", "Luigi"),
        ("fighter:taki", "Taki", "sonic", "Sonic")]                       # one row per donor a fighter's costumes use
    roster = B.cast_rows({"roster": [{"fighter": "KAS", "character": "luigi"}, {"fighter": "RYU", "character": "wario"}]},
                         None, lib)
    assert [(r["slot"], r["slot_name"], r["donor"]) for r in roster] == [("fighter:KAS", "Kasumi", "luigi"),
                                                                       ("fighter:RYU", "Ryu Hayabusa", "wario")]
    single = B.cast_rows({"character": "luigi", "report": {"fighter": "KAS", "costume": 1}}, None, lib)
    assert [(r["slot"], r["donor"]) for r in single] == [("fighter:KAS", "luigi")]   # not "player"
    plan = B.cast_rows({"cast": [{"slot": "fighter:taki:2", "character": "sonic", "status": "built"},
                                 {"slot": "ped:12", "character": "kane", "status": "built"}]}, None, lib)
    assert [(r["slot"], r["build_slot"]) for r in plan] == [("fighter:taki", "fighter:taki:2"), ("ped:12", "ped:12")]


def _sc2_library(tmp_path):
    lib = tmp_path / "characters"
    roles = {"hip": "pelvis", "head": "head", "l_upper": "armL", "r_upper": "armR"}
    for slug in ("wario", "sonic"):
        (lib / slug).mkdir(parents=True)
        meta = {"slug": slug, "name": slug.title(), "model": f"{slug}.glb", "rig": {"roles": dict(roles)},
                "source": {"game_title": "Mario"}}
        if slug == "wario":                    # the editor's Swap left <-> right + Turn around for Taki only
            meta["retarget_profiles"] = {GID: {"fighter:taki": {"roles": {"l_upper": "armR", "r_upper": "armL"},
                                                                "turn": True}}}
        (lib / slug / "meta.json").write_text(json.dumps(meta))
    return lib


def test_soulcalibur2_fits_each_fighter_slot_with_its_retarget_profile(tmp_path, monkeypatch):
    """SC2 re-read the raw meta.json for its donors, so no Retarget editor profile (swap, turn, proportions) reached its
    builds; profiled_donors resolves each fighter slot's profile and loads one rig per distinct fit."""
    from gbox import soulcalibur2_swap as W
    lib, loads = _sc2_library(tmp_path), []
    monkeypatch.setattr(W, "load_donor", lambda slug, glb, roles, name="", scale=None, source="":
                        loads.append((slug, dict(roles or {}), scale)) or W.Donor(slug, name, glb, roles, scale))
    donors = W.profiled_donors(lib, GID, {("taki", 0): "wario", ("taki", 1): "wario", ("maxi", 0): "wario",
                                          ("mina", 0): "sonic"})
    assert donors[("taki", 0)] is donors[("taki", 1)]                    # one rig per distinct fit
    taki, maxi = donors[("taki", 0)], donors[("maxi", 0)]
    assert taki.roles["l_upper"] == "armR" and taki.roles["r_upper"] == "armL"
    assert taki.scale["profile"]["turn"] is True
    assert maxi.roles["l_upper"] == "armL" and not maxi.scale                # Maxi has no profile: as it was
    assert sorted(s for s, _r, _sc in loads) == ["sonic", "wario", "wario"]


def test_soulcalibur2_cast_build_fits_the_profiled_metas_it_is_given(tmp_path, monkeypatch):
    from gbox import soulcalibur2_swap as W
    from gbox.config import Config
    lib = _sc2_library(tmp_path)
    monkeypatch.setenv("GBOX_CHARACTERS", str(lib))
    monkeypatch.setattr(W, "load_donor", lambda slug, glb, roles, name="", scale=None, source="":
                        W.Donor(slug, name, glb, roles, scale))
    monkeypatch.setattr("gbox.tools.rom_path", lambda g, cfg: tmp_path / "sc2.iso")
    seen = {}

    def stop(image, out_dir, plan, **kw):
        seen.update(plan)
        raise RuntimeError("stop before writing")
    monkeypatch.setattr(W, "build_image", stop)
    raw = json.loads((lib / "wario" / "meta.json").read_text())
    game = {"game_id": GID, "title": "Soul Calibur II", "platform": "gamecube", "source_paths": ["sc2.iso"],
            "format": "iso", "profile_id": "gc"}
    res = W.build_cast(Config(data_dir=tmp_path / "data", cache_dir=tmp_path / "cache"), game,
                       [("fighter:taki", RP.apply_to_meta(raw, GID, "fighter:taki")),
                        ("fighter:maxi", RP.apply_to_meta(raw, GID, "fighter:maxi"))], "sc2_cast_test")
    assert res["mod"] is None                                             # stopped before writing anything
    taki = next(d for (k, _c), d in seen.items() if k == "taki")
    maxi = next(d for (k, _c), d in seen.items() if k == "maxi")
    assert taki.roles["l_upper"] == "armR" and taki.scale["profile"]["turn"] is True
    assert maxi.roles["l_upper"] == "armL" and taki is not maxi
