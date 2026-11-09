"""RE6 Switch (MTF) body writer tests. The RomFS-dependent tests skip when the operator's extraction is absent."""
from __future__ import annotations

import os
import zlib
from pathlib import Path

import pytest

from gbox import mt_arc, mt_model, re6_switch_models as S

ROMFS = Path(os.environ.get("GBOX_RE6_SWITCH_ROMFS", r"C:\_tools\gBox\.tmp\re6sw_romfs"))
needs_romfs = pytest.mark.skipif(not (ROMFS / "nativeNXx64" / "arc" / "NX").is_dir(),
                                 reason="the extracted RE6 Switch RomFS is not present")
LIB = Path(os.environ.get("GBOX_CHARACTER_LIBRARY", r"D:\gBox\cache\characters"))


def _model(archive: bytes) -> mt_model.ModFile:
    arc = mt_arc.parse(archive)
    _, _, raw = S._find_model(arc)
    return mt_model.parse_mod(raw)


@needs_romfs
def test_body_arcs_cover_the_nine_slots_and_costumes():
    bodies = S.body_arcs(ROMFS)
    characters = {character for character, _costume in bodies}
    assert {"leon", "helena", "chris", "piers", "jake", "sherry", "ada"} <= characters
    assert len(bodies) >= 40
    assert bodies[("leon", "Usa")].name == "uPl00LeonUsa.arc"
    assert bodies[("leon", "Omake00")].name == "uPl00LeonOmake00.arc"
    # head/hand/accessory-head/texture archives are never body arcs, whatever the character number
    assert not any("head" in path.name.lower() or "hand" in path.name.lower() or "tex" in path.name.lower()
                   for path in bodies.values())


@needs_romfs
def test_every_native_body_slot_maps_the_measured_roles():
    buildable = S.buildable_slots(ROMFS)
    assert len(buildable) == len(S.body_arcs(ROMFS))
    for slot, path in buildable.items():
        model = _model(path.read_bytes())
        roles = S.roles_for(model)
        assert len(roles) == 18, slot


@needs_romfs
def test_roles_come_from_the_measured_bone_ids():
    path = S.body_arcs(ROMFS)[("leon", "Usa")]
    model = _model(path.read_bytes())
    roles = S.roles_for(model)
    assert roles["hip"] == 1 and roles["chest"] == 2 and roles["neck"] == 3 and roles["head"] == 4
    assert roles["r_clav"] == 5 and roles["l_clav"] == 14
    assert roles["r_thigh"] == 42 and roles["l_thigh"] == 47
    assert len(roles) == 18


@needs_romfs
def test_blank_arc_keeps_the_skeleton_and_one_triangle():
    path = S.archive_root(ROMFS) / "uPl00HeadLeonUsa.arc"
    original = _model(path.read_bytes())
    blanked = S.blank_arc(path.read_bytes())
    model = _model(blanked)
    header = model.header()
    assert header["vertex_count"] == 3 and header["mesh_count"] == 1
    assert header["bone_count"] == original.header()["bone_count"]
    assert model.bone_table()["parents"] == original.bone_table()["parents"]
    assert mt_arc.parse(blanked).entries[0].name == mt_arc.parse(path.read_bytes()).entries[0].name


@pytest.mark.skipif(not (LIB / "sonic_ssbu").is_dir(), reason="sonic_ssbu is not in the library")
@needs_romfs
def test_a_textured_body_uses_the_donor_atlas():
    from gbox import characters

    meta = characters.get(LIB, "sonic_ssbu")
    source = LIB / "sonic_ssbu" / meta["model"]
    atlas = S.donor_atlas(source)
    assert atlas.size == (1024, 1024)
    body = S.body_arcs(ROMFS)[("leon", "Usa")]
    payload, receipt = S.build_body(body.read_bytes(), source, source_roles=meta["rig"]["roles"], textures=True)
    assert receipt["vertex_count"] > 1000 and receipt["triangle_count"] == 8094
    model = _model(payload)
    assert model.header()["bone_count"] == 54
    assert model.bone_table()["parents"] == _model(body.read_bytes()).bone_table()["parents"]


@pytest.mark.skipif(not (LIB / "shulk_ssbu").is_dir(), reason="shulk_ssbu is not in the library")
@needs_romfs
def test_a_multiple_root_skeleton_falls_back_to_native():
    """Piers' Canon arc has more than one root: the measured joint move cannot run, the native skeleton is kept."""
    from gbox import characters

    meta = characters.get(LIB, "shulk_ssbu")
    body = S.body_arcs(ROMFS)[("piers", "Canon")]
    payload, receipt = S.build_body(body.read_bytes(), LIB / "shulk_ssbu" / meta["model"],
                                    source_roles=meta["rig"]["roles"])
    assert receipt["pose_mode"] == "native_skeleton"
    assert "single native root" in receipt["skeleton_fallback"]
    model = _model(payload)
    assert model.header()["bone_count"] == _model(body.read_bytes()).header()["bone_count"]
    assert receipt["vertex_count"] > 1000


@pytest.mark.skipif(not (LIB / "sonic_ssbu").is_dir(), reason="sonic_ssbu is not in the library")
@needs_romfs
def test_a_donor_body_is_authored_on_the_native_skeleton():
    from gbox import characters

    meta = characters.get(LIB, "sonic_ssbu")
    source = LIB / "sonic_ssbu" / meta["model"]
    path = S.body_arcs(ROMFS)[("leon", "Usa")]
    original = _model(path.read_bytes())
    payload, receipt = S.build_body(path.read_bytes(), source, source_roles=meta["rig"]["roles"], height=180.0)
    model = _model(payload)
    header = model.header()
    assert receipt["pose_mode"] == "source_proportions"
    assert abs(receipt["fitted_height"] - 180.0) < 1e-3
    assert header["bone_count"] == original.header()["bone_count"] == 54
    assert model.bone_table()["parents"] == original.bone_table()["parents"]
    assert header["vertex_count"] == receipt["vertex_count"]
    # one 4-short index group per triangle, as the measured Switch index layout writes them
    assert header["face_count"] == receipt["triangle_count"] * 4
    assert receipt["archive_sha256"]
    assert receipt["live_verified"] is False
    # the native MRL entry is untouched
    assert [e.name for e in mt_arc.parse(payload).entries] == [e.name for e in mt_arc.parse(path.read_bytes()).entries]
