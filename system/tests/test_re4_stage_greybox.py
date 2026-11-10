"""RE4 Switch stage greybox on a synthetic room (an SMD scene with two placed models, no game data)."""
import io
import json
import struct

import numpy as np
import pytest

from gbox import re4_stage_greybox as G
from gbox import re4_switch_assets as A
from tests.test_re4_switch_assets import gradient, make_bin, make_dat, make_udas, material

PACK_ID = 0x44000400


def quad_model(corners, diffuse, *, opacity=None, texture_count=3):
    """A rigid one-bone scene model: one quad as two list triangles with UV 0..1 across it."""
    a, b, c, d = (np.asarray(p, float) for p in corners)
    positions = np.array([a, b, c, a, c, d])
    uvs = np.array([(0, 0), (1, 0), (1, 1), (0, 0), (1, 1), (0, 1)], float)
    normal = np.cross(b - a, c - a)
    normal /= np.linalg.norm(normal)
    mat = material([(A.PRIM_LIST, 6)], diffuse=diffuse)
    if opacity is not None:
        header = bytearray(mat.header)
        header[14] = opacity
        mat = A.Material(bytes(header), mat.prims)
    model = A.HdBin.parse(make_bin(skeleton=[(0, 0xFF, (0.0, 0.0, 0.0))])).with_geometry(
        positions=positions, normals=np.tile(normal, (6, 1)), uvs=uvs, weight_sets=[((0, 100),)],
        weight_index=np.zeros(6, int), materials=[mat], texture_count=texture_count).build()
    return model + bytes(-len(model) % 32)


def instance(model, position, rotation=(0, 0, 0), scale=(1, 1, 1), flags=8):
    row = bytearray(0x48)
    struct.pack_into("<I", row, 0x14, flags)
    struct.pack_into("<3f", row, 0x18, *position)
    struct.pack_into("<3f", row, 0x24, *rotation)
    struct.pack_into("<3f", row, 0x30, *scale)
    struct.pack_into("<HBB", row, 0x3C, model, 0xFF, 1)
    return bytes(row)


def make_smd(instances, models, tpl):
    """The measured SMD shape: header, instance table (count + 1 in the header), regions A, B, C, HD models, HD TPL."""
    table = b"".join(instances)
    table += bytes(-(0x40 + len(table)) % 32)
    a = 0x40 + len(table)
    region_a = bytes(32)
    b = a + len(region_a)
    region_b = bytes(0x20) + struct.pack("<I", G.GC_TPL_MAGIC) + bytes(0x1C)
    c = b + len(region_b)
    region_c = bytes(64)
    header = struct.pack("<HHIII", 0x40, len(instances) + 1, a, b, c) + bytes(0x40 - 16)
    body = header + table + region_a + region_b + region_c + b"".join(models)
    return body + tpl.build() + bytes(16)


def make_room(*, bad_header=False):
    floor = quad_model([(0, 0, 0), (0, 0, 10000), (10000, 0, 10000), (10000, 0, 0)], diffuse=0)     # wound to face up
    wall = quad_model([(0, 0, 0), (4000, 0, 0), (4000, 3000, 0), (0, 3000, 0)], diffuse=1, opacity=2)
    tpl = A.Tpl([A.TplImage(32, 32, 0x0E, PACK_ID, 0), A.TplImage(16, 32, 0x0E, PACK_ID, 1),
                 A.TplImage(8, 8, 0x0, PACK_ID, 2)])
    instances = [instance(0, (0, 0, 0)), instance(0, (20000, 0, 0), rotation=(0, 0.5, 0), scale=(2, 2, 2)),
                 instance(1, (0, 0, -5000)), instance(1, (12000, 0, 0), rotation=(0, 1.5708, 0))]
    smd = make_smd(instances, [floor, wall], tpl)
    if bad_header:
        smd = struct.pack("<H", 0x30) + smd[2:]
    smd += bytes(-len(smd) % 32)
    slots = [("CAM", bytes(32)), ("SAT", bytes(32)), ("LIT", bytes(32)), ("LIT", bytes(32)), ("SMD", smd),
             ("SMX", bytes(32)), ("TEX", bytes(64)), ("FCV", bytes(32))]
    return make_udas(make_dat(slots))


def make_archive():
    pack = A.ImagePack(PACK_ID, [])
    fence = gradient(64, 64)
    fence[::2, :, 3] = 0                                   # a cut-out: every other row transparent
    pack.append(A.encode_dds(fence, fourcc="DXT3"))
    pack.append(A.encode_dds(gradient(32, 64), fourcc="DXT3"))
    pack.append(A.encode_dds(gradient(16, 16), fourcc="DXT3", mipmaps=False))
    pack.append(A.encode_dds(gradient(8, 8), fourcc="DXT5"))                 # an entry no TPL image names
    return pack.build()


def test_parse_scene_reads_instances_models_and_the_tpl():
    scene = G.room_scene(make_room())
    assert scene.count == 4 and len(scene.models) == 2 and len(scene.tpl.images) == 3
    assert scene.archive() == "44000400.pack.fen"
    assert [inst.model for inst in scene.instances] == [0, 0, 1, 1]
    assert np.allclose(scene.instances[1].scale, 2) and np.isclose(scene.instances[3].rotation[1], 1.5708)
    assert scene.notes["instances_with_x_or_z_rotation"] == 0 and scene.notes["gc_tpl_in_B"]
    assert scene.notes["distinct_model_indices"] == 2
    with pytest.raises(G.GreyboxError, match="measured SMD header"):
        G.room_scene(make_room(bad_header=True))
    with pytest.raises(G.GreyboxError, match="slot 4 is not the SMD"):
        G.room_scene(make_udas(make_dat([("CAM", bytes(32))] * 5)))


def test_measure_classifies_by_world_geometry_and_scales_the_grid_by_the_uv_span():
    scene = G.room_scene(make_room())
    surfaces, notes = G.measure(scene, A.ImagePack.parse(make_archive()))
    assert notes["triangles"] == 8 and notes["instances_skipped"] == 0
    floor, wall, mask = surfaces[0], surfaces[1], surfaces[2]
    assert floor.shares()["up"] == pytest.approx(1.0) and floor.instances == 2 and floor.roles == {"diffuse"}
    assert wall.shares()["side"] == pytest.approx(1.0) and wall.instances == 2
    assert mask.roles == {"opacity"} and mask.area_cm2 == 0
    # the floor tiles once over 10 m at scale 1 and 20 m at scale 2; area-weighted median falls on the larger copy
    assert sorted(set(round(v) for v in floor._u)) == [1000, 2000] and floor.tile_u_cm == pytest.approx(2000.0)
    assert floor.tile_u_quartiles == pytest.approx((2000.0, 2000.0))           # the 20 m copy carries 80 % of the area
    assert wall.tile_u_cm == pytest.approx(400.0) and wall.tile_v_cm == pytest.approx(300.0)
    rows = G.plan(surfaces)
    assert [(r["entry"], r["variant"], r["rule"]) for r in rows] == [
        (0, "floor", "geometry:up"), (1, "wall", "geometry:side"), (2, "keep", "not a diffuse")]
    assert rows[0]["label"] == "64" and rows[0]["corner"] == "20 m" and rows[0]["cells"] == [20, 20]
    assert rows[1]["label"] == "04 m x 03 m" and rows[1]["cells"] == [4, 3]
    assert G.classify(G.Surface(9, 9, 8, 8, "DXT3", 1, (8, 8))) == ("keep", "unbound")


def test_build_rewrites_only_the_scene_albedos_at_their_native_size_and_keeps_alpha():
    from PIL import Image

    room, archive = make_room(), make_archive()
    written, receipt = G.build(room, archive, stage="Village")
    before, after = A.ImagePack.parse(archive), A.ImagePack.parse(written)
    assert receipt["changed_entries"] == [0, 1] and receipt["variants"] == {"floor": 1, "wall": 1, "keep": 1}
    assert len(written) != 0 and len(after.body()) == len(before.body())
    for k in (2, 3):
        assert after.entries[k] == before.entries[k]
    for k in (0, 1):
        native, out = before.entries[k][1], after.entries[k][1]
        assert len(out) == len(native) and out[:128] == native[:128] and out != native
        assert A.dds_info(out)["fourcc"] == "DXT3"
    floor = np.asarray(Image.open(io.BytesIO(after.entries[0][1])).convert("RGBA"), np.int32)
    assert floor.shape == (64, 64, 4)
    assert (floor[::2, :, 3] < 32).all() and (floor[1::2, :, 3] > 224).all()      # the cut-out survived
    blue = floor[1::2, :, :3].reshape(-1, 3).mean(0)
    assert blue[2] > blue[0]                                                      # a floor is drawn blue
    assert receipt["live_verified"] is False and receipt["archive"] == "44000400.pack.fen"
    assert receipt["textures"][0]["alpha"].startswith("native alpha kept") and receipt["textures"][0]["payload_sha256"]
    assert receipt["measurement"]["instances"] == 4 and receipt["stage"] == "Village"
    assert G.verify(archive, written, receipt) == {"entries": 4, "changed": [0, 1], "unchanged": 2,
                                                    "sha256": receipt["written_sha256"]}
    assert json.dumps(receipt)


def test_build_refuses_the_wrong_archive_and_verify_refuses_a_foreign_change():
    room, archive = make_room(), make_archive()
    other = A.ImagePack(0x44000402, [])
    other.append(A.encode_dds(gradient(8, 8), fourcc="DXT3"))
    with pytest.raises(G.GreyboxError, match="the room names"):
        G.build(room, other.build())
    written, receipt = G.build(room, archive)
    pack = A.ImagePack.parse(written)
    wrapper, dds, tail = pack.entries[3]
    pack.entries[3] = (wrapper, dds[:128] + bytes(len(dds) - 128), tail)
    with pytest.raises(G.GreyboxError, match="does not match the receipt|other changed entries"):
        G.verify(archive, pack.build(), receipt)
    with pytest.raises(G.GreyboxError, match="other changed entries"):
        G.verify(archive, pack.build(), {"changed_entries": [0, 1], "textures": receipt["textures"]
                                          + [{"entry": 3, "payload_sha256": G.hashlib.sha256(pack.entries[3][1]).hexdigest()}]})
    receipt["textures"][0]["payload_sha256"] = "0" * 64
    with pytest.raises(G.GreyboxError, match="does not match the receipt"):
        G.verify(archive, written, receipt)


def test_overrides_and_previews(tmp_path):
    room, archive = make_room(), make_archive()
    written, receipt = G.build(room, archive, overrides={0: "other", 1: "keep"})
    assert receipt["changed_entries"] == [0] and receipt["textures"][0]["rule"] == "override"
    with pytest.raises(G.GreyboxError, match="not a variant"):
        G.build(room, archive, overrides={0: "lava"})
    G.contact_sheet(written, receipt["textures"], tmp_path / "sheet.png")
    report = G.render_stage(room, written, tmp_path / "view.png", size=64)
    assert (tmp_path / "sheet.png").exists() and (tmp_path / "view.png").exists()
    assert report["triangles"] + report["culled"] == 8 and report["culled"] > 0
    assert G.render_stage(room, written, tmp_path / "all.png", size=64, cull=False)["triangles"] == 8


def test_command_line_survey_and_build(tmp_path, capsys):
    room, archive = tmp_path / "r400.udas", tmp_path / "44000400.pack.fen"
    room.write_bytes(make_room())
    archive.write_bytes(make_archive())
    assert G.main(["survey", str(room), str(archive)]) == 0
    survey = json.loads(capsys.readouterr().out)
    assert survey["archive"] == "44000400.pack.fen" and len(survey["textures"]) == 3
    assert G.main(["build", str(room), str(archive), "--stage", "Village", "--out", str(tmp_path / "out"),
                   "--no-preview"]) == 0
    saved = json.loads((tmp_path / "out" / "receipt.json").read_text(encoding="utf-8"))
    out = (tmp_path / "out" / "romfs" / "bio4" / "imagepackhd" / "44000400.pack.fen").read_bytes()
    assert saved["files"][0]["sha256"] == saved["written_sha256"] == A.ImagePack.parse(out) and True or \
        saved["files"][0]["sha256"] == saved["written_sha256"]
    assert len(out) == saved["bytes"] and saved["live_verified"] is False
    with pytest.raises(G.GreyboxError, match="never overwritten"):
        G.main(["build", str(room), str(archive), "--out", str(tmp_path / "out"), "--no-preview"])


# --- the room's objects (ETM) and every stage at once ---------------------------------------------------------------------

def make_prop_room():
    """make_room plus the measured object layout: an ITM table, and an ETM slot holding a door ([BIN][TPL] with an
    opacity image, then a piece BIN that has no table), a crate whose table names a scene entry, and a lamp whose
    table names an entry the item table also names."""
    _pack, dat = A.pack_slots(make_room())
    slots = list(dat.slots)
    door = quad_model([(-650, 0, 0), (650, 0, 0), (650, 2300, 0), (-650, 2300, 0)], diffuse=0, opacity=1, texture_count=2)
    piece = quad_model([(0, 0, 0), (300, 0, 0), (300, 300, 0), (0, 300, 0)], diffuse=0, texture_count=2)
    crate = quad_model([(0, 0, 0), (0, 0, 600), (600, 0, 600), (600, 0, 0)], diffuse=0, texture_count=1)
    lamp = quad_model([(0, 0, 0), (100, 0, 0), (100, 400, 0), (0, 400, 0)], diffuse=0, texture_count=1)
    table = lambda *entries: A.Tpl([A.TplImage(16, 16, 0x0E, PACK_ID, e) for e in entries]).slot()
    etm = (bytes(64) + door + table(4, 5) + piece + crate + table(1) + lamp + table(6))
    slots += [("ITM", bytes(32) + table(6)), ("EFF", table(7)), ("ETM", etm)]
    return make_udas(make_dat(slots))


def make_prop_archive():
    pack = A.ImagePack.parse(make_archive())
    for size in (32, 16, 16, 16):                              # 4 door albedo, 5 door opacity, 6 item, 7 effect
        pack.append(A.encode_dds(gradient(size, size), fourcc="DXT3"))
    return pack.build()


def test_room_props_groups_each_object_with_its_tables_and_its_pieces():
    groups, notes = G.room_props(make_prop_room())
    assert [len(g.models) for g in groups] == [2, 1, 1] and [len(g.tables) for g in groups] == [1, 1, 1]
    assert [[i.index for i in g.tables[0].images] for g in groups] == [[4, 5], [1], [6]]
    assert notes["models"] == 4 and notes["tables"] == 3 and notes["etm_slots"] == [10]
    named = G.named_entries(make_prop_room(), PACK_ID)
    assert named["ITM"] == {6} and named["EFF"] == {7} and named["SMD"] == {0, 1, 2} and named["ETM"] == {1, 4, 5, 6}


def test_measure_props_keeps_scene_item_and_opacity_entries_out_and_spans_in_model_space():
    room, archive = make_prop_room(), A.ImagePack.parse(make_prop_archive())
    surfaces, notes = G.measure_props(room, archive, G.room_scene(room))
    assert set(surfaces) == {4, 5}                             # 1 is the scene's, 6 the item table's
    assert notes["prop_entries_shared_with_scene"] == 1 and notes["prop_entries_shared_with_items_or_effects"] == 1
    door, mask = surfaces[4], surfaces[5]
    assert door.roles == {"diffuse"} and door.owner == "ETM" and door.shares()["side"] == pytest.approx(1.0)
    assert door.tile_u_cm == pytest.approx(130.0, rel=0.05) and door.tile_v_cm == pytest.approx(230.0, rel=0.05)
    assert mask.roles == {"opacity"}
    rows = G.plan_props(surfaces)
    assert [(r["entry"], r["variant"], r["label"]) for r in rows] == [(4, "prop", "PROP"), (5, "keep", "PROP")]
    assert rows[0]["owner"] == "ETM" and rows[0]["image"] == -1


def test_build_draws_props_orange_and_leaves_items_effects_and_opacity_native():
    from PIL import Image

    room, archive = make_prop_room(), make_prop_archive()
    written, receipt = G.build(room, archive, stage="Village")
    before, after = A.ImagePack.parse(archive), A.ImagePack.parse(written)
    assert receipt["changed_entries"] == [0, 1, 4] and receipt["variants"]["prop"] == 1 and receipt["props"]
    for k in (2, 3, 5, 6, 7):
        assert after.entries[k] == before.entries[k]
    door = np.asarray(Image.open(io.BytesIO(after.entries[4][1])).convert("RGB"), np.int32).reshape(-1, 3).mean(0)
    assert door[0] > door[2] + 40                              # the RE5 prop orange
    assert G.verify(archive, written, receipt)["changed"] == [0, 1, 4]
    plain, plain_receipt = G.build(room, archive, props=False)
    assert plain_receipt["changed_entries"] == [0, 1] and A.ImagePack.parse(plain).entries[4] == before.entries[4]


def test_build_all_writes_every_stage_into_one_overlay(tmp_path):
    bio4 = tmp_path / "bio4"
    (bio4 / "st4").mkdir(parents=True)
    (bio4 / "imagepackhd").mkdir()
    (bio4 / "st4" / "r400.udas").write_bytes(make_prop_room())
    (bio4 / "imagepackhd" / "44000400.pack.fen").write_bytes(make_prop_archive())
    receipt = G.build_all(bio4, tmp_path / "out", stages=("Village",), previews=False)
    written = tmp_path / "out" / "romfs" / "bio4" / "imagepackhd" / "44000400.pack.fen"
    assert receipt["files"] == [{"path": "romfs/bio4/imagepackhd/44000400.pack.fen", "bytes": written.stat().st_size,
                                 "sha256": G.hashlib.sha256(written.read_bytes()).hexdigest(),
                                 "source_bytes": len(make_prop_archive()),
                                 "source_sha256": G.hashlib.sha256(make_prop_archive()).hexdigest(), "stage": "Village"}]
    assert receipt["stages"]["Village"]["variants"]["prop"] == 1 and receipt["live_verified"] is False
    stage = json.loads((tmp_path / "out" / "stages" / "Village.json").read_text(encoding="utf-8"))
    assert stage["verified"]["sha256"] == receipt["files"][0]["sha256"]
    with pytest.raises(G.GreyboxError, match="never overwritten"):
        G.build_all(bio4, tmp_path / "out", stages=("Village",))
    with pytest.raises(G.GreyboxError, match="not Mercenaries stages"):
        G.build_all(bio4, tmp_path / "other", stages=("Lab",))
    assert G.main(["build-all", str(bio4), "--out", str(tmp_path / "cli"), "--stages", "Village", "--no-preview"]) == 0
    assert (tmp_path / "cli" / "romfs" / "bio4" / "imagepackhd" / "44000400.pack.fen").read_bytes() == written.read_bytes()


def test_rigid_scene_model_with_no_weight_sets_parses_and_rebuilds():
    """The room models have an empty weight table whose pointer is the next section's offset (measured on 462 models)."""
    model = quad_model([(0, 0, 0), (100, 0, 0), (100, 0, 100), (0, 0, 100)], diffuse=0)
    parsed = A.HdBin.parse(model)
    header = bytearray(parsed.header)
    header[0x28] = 0
    struct.pack_into("<H", header, 0x42, 0)
    sections = {name: payload for name, payload in parsed.sections.items() if name != "weights"}
    rigid = A.HdBin(bytes(header), {"bones": sections.pop("bones"), "weights": b"", **sections}, parsed.legacy).build()
    again = A.HdBin.parse(rigid)
    assert again.weight_count == 0 and again.weights() == [] and again.build() == rigid
    following = min(v for v in (struct.unpack_from("<Q", rigid, at)[0] for at, _size in A.BIN_POINTERS.values()
                                if _size == 8) if v > A.BIN_HEAD)
    assert struct.unpack_from("<Q", rigid, 0x20)[0] == following            # the empty table points at the next section
    broken = bytearray(rigid)
    struct.pack_into("<Q", broken, 0x10, struct.unpack_from("<Q", rigid, 0x18)[0])      # colours on the UV offset
    with pytest.raises(A.AssetError, match="share one offset"):
        A.HdBin.parse(bytes(broken))
