"""RE6 Switch (MTF) body writer tests. The RomFS-dependent tests skip when the operator's extraction is absent."""
from __future__ import annotations

import os
import zlib
from pathlib import Path

import numpy as np
import pytest

from gbox import mt_arc, mt_model, re6_switch_models as S

ROMFS = Path(os.environ.get("GBOX_RE6_SWITCH_ROMFS", r"C:\_tools\gBox\.tmp\re6sw_romfs"))
needs_romfs = pytest.mark.skipif(not (ROMFS / "nativeNXx64" / "arc" / "NX").is_dir(),
                                 reason="the extracted RE6 Switch RomFS is not present")
LIB = Path(os.environ.get("GBOX_CHARACTER_LIBRARY", r"D:\gBox\cache\characters"))


NX = ROMFS / "nativeNXx64" / "arc" / "NX"
#: a donor the game host's library holds (the Smash Ultimate / Brawl donors live on another machine)
HOST_DONOR = "melee_mario"


def _model(archive: bytes) -> mt_model.ModFile:
    arc = mt_arc.parse(archive)
    _, _, raw = S._find_model(arc)
    return mt_model.parse_mod(raw)


def _stub_mod(bones: int, vertices: int = 3) -> bytes:
    """A MOD header as far as `model_entries` reads it: magic, the bone count at +6, the vertex count at +12."""
    raw = bytearray(0x60)
    raw[:4] = b"MOD\0"
    raw[4] = 211
    raw[6:8] = bones.to_bytes(2, "little")
    raw[12:16] = vertices.to_bytes(4, "little")
    return bytes(raw)


def _stub_arc(entries: list[tuple[str, bytes]]) -> mt_arc.Arc:
    return mt_arc.Arc(version=7, entries=[mt_arc.Entry(name=name, hash=0, tag=0, size=len(data), offset=0,
                                                       data=zlib.compress(data)) for name, data in entries])


def test_the_body_is_the_skinned_mod_whatever_the_entry_order():
    """Entry order must not pick the model: an effect MOD listed first is never the body, and the MRL is the one
    that shares the body's name."""
    body, effect = _stub_mod(54, 25784), _stub_mod(0, 104)
    mrl = b"MRL\0" + bytes(36)
    arc = _stub_arc([("effect\\mod\\000c\\md000c_02", mrl), ("effect\\mod\\000c\\md000c_02", effect),
                     ("data\\chara\\pl\\pl0000\\model\\pl0000", mrl), ("data\\chara\\pl\\pl0000\\model\\pl0000", body),
                     ("effect\\mod\\008c\\md008c", _stub_mod(0, 48))])
    rows = S.model_entries(arc)
    assert [(row["index"], row["bones"], row["vertices"], row["mrl"]) for row in rows] == [
        (1, 0, 104, 0), (3, 54, 25784, 2), (4, 0, 48, -1)]
    index, mrl_index, raw = S._find_model(arc)
    assert (index, mrl_index, raw) == (3, 2, body)
    # two skinned parts in one archive: the larger skeleton is the body, the first wins a tie
    arc = _stub_arc([("a\\cs_pl0001", _stub_mod(5)), ("a\\cs_pl0000", _stub_mod(86)), ("a\\cs_pl0002", _stub_mod(86))])
    assert S._find_model(arc)[0] == 1
    with pytest.raises(S.SwitchModelError):
        S._find_model(_stub_arc([("x\\y", b"MRL\0" + bytes(36))]))


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
                                    source_roles=meta["rig"]["roles"], bind_mode="reposition")
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
    payload, receipt = S.build_body(path.read_bytes(), source, source_roles=meta["rig"]["roles"], height=180.0,
                                    bind_mode="reposition")
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


@pytest.mark.skipif(not (LIB / "sonic_ssbu").is_dir(), reason="sonic_ssbu is not in the library")
@needs_romfs
def test_keep_bind_leaves_the_native_skeleton_unchanged():
    """The live fix (2026-11-09): the native bind pose is left byte-identical and the fitted surface is authored in it,
    so the title's own animations still find every joint where they expect it."""
    from gbox import characters

    meta = characters.get(LIB, "sonic_ssbu")
    source = LIB / "sonic_ssbu" / meta["model"]
    path = S.body_arcs(ROMFS)[("leon", "Usa")]
    native = _model(path.read_bytes())
    payload, receipt = S.build_body(path.read_bytes(), source, source_roles=meta["rig"]["roles"], height=180.0)
    model = _model(payload)
    assert receipt["bind_mode"] == "keep"
    assert receipt["pose_mode"] == "native_bind_kept"
    assert model.bone_world() == native.bone_world()
    assert model.bone_table()["parents"] == native.bone_table()["parents"]
    assert abs(receipt["fitted_height"] - 180.0) < 1e-3


# --- roster integrity: which MOD, which skeleton, which material ---------------------

@needs_romfs
def test_every_body_slot_holds_one_skinned_body_with_its_own_skeleton():
    """The 36..89 bone counts are each costume's own skeleton, not a wrong MOD: one skinned MOD a slot (the other
    MODs are skeleton-less effect models), found by its skeleton and not by entry order, all 18 role ids present."""
    bodies = S.body_arcs(ROMFS)
    bones = {}
    for slot, path in bodies.items():
        report = S.slot_report(path.read_bytes())
        assert report["skinned_models"] == 1, slot
        assert "\\chara\\" in report["entry"] and "\\model\\" in report["entry"], slot
        assert len(report["roles"]) == 18, slot
        arc = mt_arc.parse(path.read_bytes())
        assert arc.entries[report["mrl_index"]].name == report["entry"], slot
        assert all(row["bones"] == 0 and "effect" in row["name"] for row in report["models"]
                   if row["index"] != report["entry_index"]), slot
        bones[slot] = report["bones"]
    assert bones[("leon", "Usa")] == 54
    if ("leon", "Asia") in bones and ("leon", "Omake02") in bones:
        assert (bones[("leon", "Asia")], bones[("leon", "Omake02")]) == (45, 36)
    if ("piers", "Canon") in bones:
        assert bones[("piers", "Canon")] == 89
        assert S.slot_report(bodies[("piers", "Canon")].read_bytes())["roots"] == 5
    if len(bones) == 51:
        assert (min(bones.values()), max(bones.values())) == (36, 89) and len(set(bones.values())) == 18


@needs_romfs
def test_blank_arc_blanks_every_skinned_model_of_an_accessory_head():
    path = NX / "uPl00AcHeadLeonUsa.arc"
    if not path.is_file():
        pytest.skip("the accessory-head archive is not present")
    native = S.model_entries(mt_arc.parse(path.read_bytes()))
    assert [row["bones"] for row in native] == [86, 5, 25] and all(row["vertices"] > 1000 for row in native)
    blanked = mt_arc.parse(S.blank_arc(path.read_bytes()))
    rows = S.model_entries(blanked)
    assert [(row["index"], row["name"], row["bones"]) for row in rows] == [
        (row["index"], row["name"], row["bones"]) for row in native]
    assert all(row["vertices"] == 3 and row["meshes"] == 1 for row in rows)      # the first one alone used to be
    original = mt_arc.parse(path.read_bytes())
    touched = {row["index"] for row in native}
    assert [e.name for e in blanked.entries] == [e.name for e in original.entries]
    assert all(a.data == b.data for i, (a, b) in enumerate(zip(original.entries, blanked.entries))
               if i not in touched)
    with pytest.raises(S.SwitchModelError):
        S.blank_arc(mt_arc.build(_stub_arc([("effect\\mod\\x", _stub_mod(0))])))


@needs_romfs
def test_body_materials_name_what_a_donor_mesh_samples():
    bodies = S.body_arcs(ROMFS)
    usa = bodies[("leon", "Usa")]
    assert S.body_materials(_model(usa.read_bytes())) == ["pl_cloth", "pl_base2", "pl_cloth1", "pl_base1", "pl_skin"]
    sets = [path.name for path in S.texture_set_arcs(ROMFS, usa)]
    assert sets[0] == "uPlTex0000_0.arc" and all(name.startswith("uPlTex0000_") for name in sets)
    if ("leon", "Asia") in bodies:
        asia = bodies[("leon", "Asia")]
        assert S.body_materials(_model(asia.read_bytes()))[0] == "pl_skin1"
        assert S.texture_set_arcs(ROMFS, asia)[0].name == "uPlTex0010_0.arc"
    if ("leon", "Omake00") in bodies:                           # an extra costume carries its textures itself
        assert S.texture_set_arcs(ROMFS, bodies[("leon", "Omake00")]) == [bodies[("leon", "Omake00")]]


@needs_romfs
def test_the_donor_material_is_vetted_not_assumed():
    """Material 0 is an alpha-tested patch material on some bodies; the donor takes an opaque, undisplaced one."""
    bodies = S.body_arcs(ROMFS)
    usa = S.donor_material(ROMFS, bodies[("leon", "Usa")])
    assert (usa["index"], usa["name"], usa["vetted"]) == (1, "pl_base2", True)   # 0 is the displaced jacket
    assert usa["albedo"] == "pl0000_00shats_BM" and usa["function"] == "FAlbedoMap2"
    if (NX / "uPlTex0010_0.arc").is_file():
        asia = S.donor_material(ROMFS, bodies[("leon", "Asia")])
        assert (asia["index"], asia["name"], asia["albedo"]) == (0, "pl_skin1", "pl0010_20_vest_BM")
    for slot, texture_set in ((("helena", "Usa"), "uPlTex0100_0.arc"), (("chris", "Asia"), "uPlTex0200_0.arc")):
        if slot not in bodies or not (NX / texture_set).is_file():
            continue
        assert S.body_materials(_model(bodies[slot].read_bytes()))[0] == "pl_nuki"
        chosen = S.donor_material(ROMFS, bodies[slot])
        assert chosen["vetted"] and chosen["index"] == 1 and chosen["name"] != "pl_nuki" and chosen["opaque"]


def test_an_unknown_texture_set_leaves_material_zero_unvetted(tmp_path):
    """Without the costume's texture-set archive there is nothing to vet against: index 0, and the receipt says so."""
    root = tmp_path / "nativeNXx64" / "arc" / "NX"
    root.mkdir(parents=True)
    body = root / "uPl00LeonUsa.arc"
    body.write_bytes(mt_arc.build(_stub_arc([("data\\chara\\pl\\pl0000\\model\\pl0000", _stub_mod(54))])))
    chosen = S.donor_material(tmp_path, body)
    assert chosen["index"] == 0 and chosen["vetted"] is False and "not in this RomFS" in chosen["why"]


@needs_romfs
def test_material_texture_changes_touch_only_the_donor_materials_albedo():
    from PIL import Image

    from gbox import re6_switch_tex as X

    usa = S.body_arcs(ROMFS)[("leon", "Usa")]
    changes, report = S.material_texture_changes(ROMFS, usa, Image.new("RGB", (64, 64), (0, 0, 255)))
    arcs = S.texture_set_arcs(ROMFS, usa)
    assert sorted(changes) == sorted(f"romfs/nativeNXx64/arc/NX/{path.name}" for path in arcs)
    assert [row["material"] for row in report] == ["pl_cloth"] * len(arcs)
    assert report[0]["texture"].endswith("pl0000_00jacket_BM")
    assert report[0]["function"] == "FColorMaskAlbedoMapModulate"
    if len(arcs) > 1:                                           # the dirt variants bind their own albedo
        assert report[1]["texture"].endswith("pl0000_70jacket_d1_BM")
    for path, row in zip(arcs, report):
        native = mt_arc.parse(path.read_bytes())
        built = mt_arc.parse(changes[f"romfs/nativeNXx64/arc/NX/{path.name}"]["bytes"])
        assert [e.name for e in native.entries] == [e.name for e in built.entries]
        differing = [i for i, (a, b) in enumerate(zip(native.entries, built.entries)) if a.data != b.data]
        assert differing == [row["entry"]]                      # head, hair, hands, shirt, blood mask: untouched
        before = X.from_arc_entry(native.entries[row["entry"]])
        after = X.from_arc_entry(built.entries[row["entry"]])
        assert (after.format, after.width, after.height, after.mips) == (0x2B, before.width, before.height,
                                                                         before.mips)
        rgb, alpha = after.albedo()
        assert np.abs(rgb.astype(int) - (0, 0, 255)).max() <= 6 and (alpha == 255).all()
        assert built.entries[row["entry"]].tag & 0xFFFFFF == len(after.data)
    with pytest.raises(S.SwitchModelError):
        S.material_texture_changes(ROMFS, usa, Image.new("RGB", (8, 8)), material_index=9)


def test_texture_changes_leave_the_shared_blood_mask_alone(tmp_path, monkeypatch):
    """`pl_Blood_BM` is the mask of the colour-mask materials, not an albedo: the blunt route must not repaint it."""
    from PIL import Image

    from gbox import re6_switch_tex as X, skin_swap

    root = tmp_path / "nativeNXx64" / "arc" / "NX"
    root.mkdir(parents=True)
    blank = X.pack_tex(0x2B, 8, 8, [bytes(64), bytes(16)])
    arc = _stub_arc([("data\\chara\\pl\\pl0000\\model\\pl0000_00jacket_BM", blank),
                     ("data\\chara\\textures\\pl_Blood_BM", blank)])
    (root / "uPlTex0000_0.arc").write_bytes(mt_arc.build(arc))
    monkeypatch.setitem(skin_swap.CHARACTER_ARCS, S.TITLE_ID, {"leon": "nativeNXx64/arc/NX/uPl00LeonUsa.arc"})
    atlas = Image.new("RGB", (8, 8), (255, 128, 0))
    changes = S.texture_changes(tmp_path, "leon", atlas)
    built = mt_arc.parse(changes["romfs/nativeNXx64/arc/NX/uPlTex0000_0.arc"]["bytes"])
    jacket, blood = (X.from_arc_entry(entry) for entry in built.entries)
    assert np.abs(jacket.albedo()[0].astype(int) - (255, 128, 0)).max() <= 6
    assert blood.data == blank
    everything = mt_arc.parse(S.texture_changes(tmp_path, "leon", atlas, shared=True)[
        "romfs/nativeNXx64/arc/NX/uPlTex0000_0.arc"]["bytes"])
    assert X.from_arc_entry(everything.entries[1]).data != blank


@pytest.mark.skipif(not (LIB / HOST_DONOR).is_dir(), reason="the host-library donor is not present")
@needs_romfs
def test_a_host_library_donor_keeps_the_native_skeleton():
    """The same keep-bind property as the Smash Ultimate test above, with a donor the game host actually holds."""
    from gbox import characters

    meta = characters.get(LIB, HOST_DONOR)
    path = S.body_arcs(ROMFS)[("leon", "Usa")]
    native = _model(path.read_bytes())
    payload, receipt = S.build_body(path.read_bytes(), LIB / HOST_DONOR / meta["model"],
                                    source_roles=meta["rig"]["roles"], material_index=1)
    model = _model(payload)
    assert (receipt["bind_mode"], receipt["pose_mode"], receipt["material"]) == ("keep", "native_bind_kept",
                                                                               "pl_base2")
    assert model.block(0) == native.block(0)                    # the whole bone block, byte for byte
    assert model.bone_world() == native.bone_world()
    meshes = model.meshes()
    assert len(meshes) == 1 and meshes[0]["material_index"] == 1
    assert model.header()["vertex_count"] == receipt["vertex_count"] > 1000
    assert len(model.triangles()) == receipt["triangle_count"] == 5908
    assert abs(receipt["fitted_height"] - 180.0) < 1e-3 and receipt["live_verified"] is False
    native_arc, built_arc = mt_arc.parse(path.read_bytes()), mt_arc.parse(payload)
    assert all(a.data == b.data for i, (a, b) in enumerate(zip(native_arc.entries, built_arc.entries))
               if i != receipt["model_entry"])


@pytest.mark.skipif(not (LIB / "doapp_lei_fang_1_59c55e95af61abbe").is_dir(), reason="the DOA donor is not present")
@needs_romfs
def test_a_rig_without_neck_or_clavicles_binds_when_the_skeleton_is_kept():
    """Dead or Alive rigs resolve 15 of the 18 roles. Keeping the native bind needs no neck anchor; moving the
    joints does, and still refuses."""
    from gbox import characters

    slug = "doapp_lei_fang_1_59c55e95af61abbe"
    meta = characters.get(LIB, slug)
    roles = meta["rig"]["roles"]
    assert sorted(set(S.ROLE_IDS) - set(roles)) == ["l_clav", "neck", "r_clav"]
    path = S.body_arcs(ROMFS)[("leon", "Usa")]
    payload, receipt = S.build_body(path.read_bytes(), LIB / slug / meta["model"], source_roles=roles)
    assert receipt["pose_mode"] == "native_bind_kept" and "neck" not in receipt["roles"]
    assert _model(payload).block(0) == _model(path.read_bytes()).block(0)
    assert receipt["skin"]["discarded_influences"] == 0
    with pytest.raises(S.SwitchModelError, match="neck"):
        S.build_body(path.read_bytes(), LIB / slug / meta["model"], source_roles=roles, bind_mode="reposition")


@pytest.mark.skipif(not (LIB / "ff7_earith").is_dir(), reason="the FF7 donor is not present")
@needs_romfs
def test_a_donor_without_index_buffers_is_authored():
    """FF7's field models draw unindexed triangles; that used to end the build with a KeyError."""
    from gbox import characters

    meta = characters.get(LIB, "ff7_earith")
    vertices, triangles = S._source_geometry(LIB / "ff7_earith" / meta["model"])
    assert len(triangles) == 1101 and max(max(t) for t in triangles) < len(vertices)
    path = S.body_arcs(ROMFS)[("leon", "Usa")]
    payload, receipt = S.build_body(path.read_bytes(), LIB / "ff7_earith" / meta["model"],
                                    source_roles=meta["rig"]["roles"])
    assert receipt["triangle_count"] == 1101 and len(_model(payload).triangles()) == 1101


@pytest.mark.skipif(not ((LIB / HOST_DONOR).is_dir() and (LIB / "mgs2_snake_7473dc814d0cf869").is_dir()),
                    reason="the T-pose and arms-down donors are not present")
@needs_romfs
def test_a_donor_resting_out_of_the_native_bind_pose_is_reposed():
    """Keeping the bind leaves the donor in its own rest pose. MGS2's Snake rests with his arms down, 90 degrees
    from Leon's T-posed bind; `pose` turns his limbs into it and still leaves the native skeleton untouched."""
    from gbox import characters

    path = S.body_arcs(ROMFS)[("leon", "Usa")]
    native = path.read_bytes()
    mario = characters.get(LIB, HOST_DONOR)
    assert S.pose_deviation(native, LIB / HOST_DONOR / mario["model"], mario["rig"]["roles"])["max_degrees"] < 5.0
    slug = "mgs2_snake_7473dc814d0cf869"
    meta = characters.get(LIB, slug)
    source = LIB / slug / meta["model"]
    gap = S.pose_deviation(native, source, meta["rig"]["roles"])
    assert abs(gap["max_degrees"] - 90.0) < 1.0 and gap["max_degrees"] > S.POSE_TOLERANCE_DEGREES
    assert gap["segments"]["l_thigh>l_shin"] < 10.0               # the legs already agree; the arms do not
    kept, kept_receipt = S.build_body(native, source, source_roles=meta["rig"]["roles"])
    posed, receipt = S.build_body(native, source, source_roles=meta["rig"]["roles"], bind_mode="pose")
    assert (receipt["bind_mode"], receipt["pose_mode"]) == ("pose", "native_bind_posed")
    assert set(receipt["bind"]["segments"]) == set(S.POSE_SEGMENTS)
    assert _model(posed).block(0) == _model(native).block(0) == _model(kept).block(0)
    assert abs(receipt["fitted_height"] - 180.0) < 1e-3 and not receipt["height_clamped"]
    assert receipt["vertex_count"] == kept_receipt["vertex_count"]
    assert receipt["triangle_count"] == kept_receipt["triangle_count"] == 2872

    def span(archive):
        points = np.asarray(_model(archive).positions(0))
        return float(points[:, 0].max() - points[:, 0].min())

    assert span(posed) > 2.0 * span(kept) and span(posed) > 120.0  # arms out to the sides now
    with pytest.raises(S.SwitchModelError):
        S.build_body(native, source, source_roles=meta["rig"]["roles"], bind_mode="stretch")
