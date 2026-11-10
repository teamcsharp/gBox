"""RE6 Switch enemy cast: the group-aware writer and the build plan, on synthetic data only.

No game archive or library file is read. The class body mirrors what was measured on the J'avo / zombie archives
(2026-11-10): RE6 global bone ids, a T-posed humanoid, no record of mesh type 0xFFFF (RE6's records are 0xFDF7 /
0x1020), a torso, an upper-chest piece and a shirt that cover the chest band, a belt that is too small, legs and a head
that do not reach it, a `Shadow` group, a far-only group, the table sorted by material, mesh ids 1..n.
"""
import json
import struct
import zlib

import numpy as np
import pytest
from PIL import Image

from gbox import mt_arc, mt_model, mtf_author, re5_enemy_writer as R5, re6_enemy_cast as C
from gbox import re6_switch_enemies as E, re6_switch_models as M, re6_switch_tex as T

COMPRESSION = np.diag([400., 400., 400., 1.])
COMPRESSION[3, :3] = (-150., -10., -150.)
FULL, ONE = 0x2000D414, 0x18B0FAA8
MOD_HASH, MRL_HASH, TEX_HASH = 0x58A15856, 0x2749C8A8, 0x241F5DEB
BODY = "data\\chara\\em\\em1000\\model\\em1000"
ALBEDO = "data\\chara\\em\\em1000\\model\\em1000_body_BM"
SHIRT = "data\\chara\\em\\em1000\\model\\em1000_shirt_BM"
MATERIALS = ("em1000_Head", "em1000_ID2_Body", "em1000_Shirt", "em1000_Shadow")


def skeleton():
    """(name, RE6 global bone id, parent, bind position): a 182 cm T-pose with the hip as the one root."""
    bones = [("hip", 1, None, (0., 100., 0.)), ("chest", 2, "hip", (0., 130., 0.)), ("neck", 3, "chest", (0., 155., 0.)),
             ("head", 4, "neck", (0., 168., 0.))]
    for side, sign, base in (("r", -1, 5), ("l", 1, 10)):
        bones += [(f"{side}_clav", base, "chest", (6. * sign, 148., 0.)),
                  (f"{side}_upper", base + 1, f"{side}_clav", (18. * sign, 148., 0.)),
                  (f"{side}_fore", base + 2, f"{side}_upper", (45. * sign, 148., 0.)),
                  (f"{side}_hand", base + 3, f"{side}_fore", (72. * sign, 148., 0.))]
    for side, sign, base in (("r", -1, 16), ("l", 1, 20)):
        bones += [(f"{side}_thigh", base, "hip", (10. * sign, 95., 0.)),
                  (f"{side}_shin", base + 1, f"{side}_thigh", (10. * sign, 52., 0.)),
                  (f"{side}_foot", base + 2, f"{side}_shin", (10. * sign, 8., 0.))]
    return bones


def bone_block(bones):
    index = {name: i for i, (name, *_) in enumerate(bones)}
    headers, local, inverse = b"", b"", b""
    for name, animation, parent, point in bones:
        headers += bytes((animation, 255 if parent is None else index[parent], 0, 0)) + bytes(20)
        world, relative = np.eye(4), np.eye(4)
        world[3, :3] = point
        relative[3, :3] = np.subtract(point, bones[index[parent]][3]) if parent else point
        local += struct.pack("<16f", *relative.ravel())
        inverse += struct.pack("<16f", *(COMPRESSION @ np.linalg.inv(world)).ravel())
    return headers + local + inverse + bytes(256)


def grid(y0, y1, x=20., n=110):
    cols = 10
    rows = (n + cols - 1) // cols
    return [(-x + 2 * x * (k % cols) / (cols - 1), y0 + (y1 - y0) * (k // cols) / max(rows - 1, 1), 0.)
            for k in range(n)]


def pack(fmt, points, bone):
    transform = tuple(COMPRESSION.ravel())
    if fmt == FULL:
        data = bytearray(mt_model.pack_vertices(
            [{"position": p, "normal": (0., 0., 1.), "uv": (.5, .5), "bones": [bone, 0, 0, 0], "weights": [0., 0.]}
             for p in points], FULL, 28, position_transform=transform))
        for i in range(len(points)):
            struct.pack_into("<h", data, i * 28 + 6, 32767)
        return bytes(data)
    return mt_model.pack_vertices([{"position": p, "normal": (0., 0., 1.), "uv": (.5, .5), "bones": [bone]}
                                   for p in points], ONE, 20, position_transform=transform)


def rows(bones):
    """Native records in table order (sorted by material), all with RE6's 0xFDF7 mesh type."""
    b = {name: i for i, (name, *_) in enumerate(bones)}
    return [
        dict(group=151, material=0, lod=1, fmt=FULL, bone=b["head"], points=grid(158., 185., 8.)),
        dict(group=3, material=1, lod=1, fmt=FULL, bone=b["chest"], points=grid(95., 160.)),
        dict(group=3, material=1, lod=2, fmt=ONE, bone=b["chest"], points=grid(95., 160., n=12)),
        dict(group=6, material=1, lod=1, fmt=FULL, bone=b["r_thigh"], points=grid(0., 95., 8.)),
        dict(group=403, material=1, lod=1, fmt=FULL, bone=b["chest"], points=grid(122., 156.)),
        dict(group=410, material=1, lod=252, fmt=ONE, bone=b["chest"], points=grid(100., 160., n=20)),
        dict(group=206, material=2, lod=1, fmt=FULL, bone=b["chest"], points=grid(80., 160., 25.)),
        dict(group=227, material=2, lod=1, fmt=FULL, bone=b["hip"], points=grid(100., 140., n=40)),
        dict(group=132, material=3, lod=255, fmt=FULL, bone=b["chest"], points=grid(100., 160.)),
    ]


GROUPS = (3, 6, 132, 151, 206, 227, 403, 410)


def class_mod(bones=None):
    bones = bones or skeleton()
    table = rows(bones)
    records, vertices, words, envelopes = b"", b"", [], b""
    for number, row in enumerate(table):
        stride = 28 if row["fmt"] == FULL else 20
        offset = len(vertices)
        vertices += pack(row["fmt"], row["points"], row["bone"])
        strip = list(range(len(row["points"])))
        record = bytearray(56)
        struct.pack_into("<HHI", record, 0, 0xFDF7, len(row["points"]),
                         row["group"] | row["material"] << 12 | row["lod"] << 24)
        record[8:12] = bytes((33 if row["fmt"] == FULL else 9, 0, stride, 4))
        struct.pack_into("<II", record, 0x0C, 0, offset)
        struct.pack_into(">I", record, 0x14, row["fmt"])
        struct.pack_into("<III", record, 0x18, len(words), len(strip), 0)
        record[0x25] = 1
        struct.pack_into("<HHH", record, 0x26, number + 1, 0, len(row["points"]) - 1)
        record[0x2C:0x38] = bytes([0xA0 + number]) * 12
        records += record
        words += strip + [0xFFFF]
        envelopes += mtf_author.pack_weight_bound(row["bone"], row["points"])
    indices = struct.pack(f"<{len(words)}H", *words) + bytes(len(words) % 2 * 2)
    tail = struct.pack("<12f", 0, 95, 0, 120, -80, 0, -20, 0, 80, 182, 20, 0) + struct.pack(
        "<5I", 500, 1000, 3, 0, len(table))
    group_block = b"".join(struct.pack("<I12x4f", group, 0, 100, 0, 60) for group in GROUPS)
    material_block = b"".join(name.encode().ljust(128, b"\0") for name in MATERIALS)
    blocks = (bone_block(bones), group_block, material_block, records + envelopes, vertices, indices)
    offsets = [0x28 + 56 + len(tail)]
    for block in blocks:
        offsets.append(offsets[-1] + len(block))
    out = mt_model.MOD_MAGIC + bytes((211, 0)) + struct.pack("<3H", len(bones), len(table), len(MATERIALS))
    out += struct.pack("<3I2I2I", sum(len(r["points"]) for r in table), len(words), 9, len(vertices), 0, len(GROUPS), 0)
    out += struct.pack("<7Q", *offsets) + tail + b"".join(blocks) + bytes(4)
    return out


def albedo_tex(size=64, colour=(90, 90, 90)):
    image = Image.new("RGB", (size, size), colour)
    levels = [T.encode_albedo(image.resize((max(1, size >> m),) * 2)) for m in range(size.bit_length())]
    return T.pack_tex(0x2B, size, size, levels)


def class_arc():
    contents = [(ALBEDO, TEX_HASH, albedo_tex()), (SHIRT, TEX_HASH, albedo_tex(32, (200, 20, 20))),
                (BODY, MRL_HASH, b"MRL\0" + bytes(60)), ("sound\\se\\em\\em1000\\walk", 0x79C47B59, b"\x02\0\0\0walk"),
                (BODY, MOD_HASH, class_mod())]
    entries = [mt_arc.Entry(name=n, hash=h, tag=0x40000000 | len(d), size=0, offset=0, data=zlib.compress(d, 6))
               for n, h, d in contents]
    return mt_arc.build(mt_arc.Arc(7, entries))


@pytest.fixture
def donor(tmp_path, monkeypatch):
    """An 18-role T-posed donor through the real loaders' seams: a triangle on every joint, a chest box with depth,
    soles on y 0. In donor units (about a tenth of a centimetre scale)."""
    joints = {"hip": (0., 9.5, 0.), "spine": (0., 12.4, 0.), "neck": (0., 14.8, 0.), "head": (0., 16.0, 0.)}
    for side, sign in (("l", 1.), ("r", -1.)):
        joints |= {f"clav_{side}": (.6 * sign, 14.1, 0.), f"arm_{side}": (1.7 * sign, 14.1, 0.),
                   f"fore_{side}": (4.3 * sign, 14.1, 0.), f"hand_{side}": (6.9 * sign, 14.1, 0.),
                   f"leg_{side}": (1. * sign, 9., 0.), f"knee_{side}": (1. * sign, 5., 0.),
                   f"foot_{side}": (1. * sign, .8, 0.)}
    parent = {"spine": "hip", "neck": "spine", "head": "neck"}
    for side in "lr":
        parent |= {f"clav_{side}": "spine", f"arm_{side}": f"clav_{side}", f"fore_{side}": f"arm_{side}",
                   f"hand_{side}": f"fore_{side}", f"leg_{side}": "hip", f"knee_{side}": f"leg_{side}",
                   f"foot_{side}": f"knee_{side}"}
    names = list(joints)
    nodes = [{"name": n, "children": [names.index(c) for c, p in parent.items() if p == n]} for n in names]
    world = []
    for n in names:
        matrix = np.eye(4)
        matrix[:3, 3] = joints[n]
        world.append(matrix)
    vertices, triangles = [], []

    def triangle(corners):
        triangles.append(tuple(range(len(vertices), len(vertices) + 3)))
        for point, joint in corners:
            vertices.append({"position": point, "normal": (0., 0., 1.), "uv": (.25, .25),
                             "source_joints": (names.index(joint),), "source_weights": (1.,)})
    for n, (x, y, z) in joints.items():
        triangle([((x + .3, y, z), n), ((x, y + .3, z), n), ((x, y, z + .3), n)])
    for z in (-1., 1.):                                              # the chest: 2 units deep
        triangle([((-1.2, 10., z), "spine"), ((1.2, 10., z), "spine"), ((0., 14., z), "spine")])
    for side, sign in (("l", 1.), ("r", -1.)):
        foot = f"foot_{side}"
        triangle([((.7 * sign, 0., -.3), foot), ((1.3 * sign, 0., -.3), foot), ((1. * sign, 0., .9), foot)])
    roles = {"hip": "hip", "chest": "spine", "neck": "neck", "head": "head"}
    for side in "lr":
        roles |= {f"{side}_clav": f"clav_{side}", f"{side}_upper": f"arm_{side}", f"{side}_fore": f"fore_{side}",
                  f"{side}_hand": f"hand_{side}", f"{side}_thigh": f"leg_{side}", f"{side}_shin": f"knee_{side}",
                  f"{side}_foot": f"foot_{side}"}
    source = tmp_path / "donor.glb"
    source.write_bytes(b"synthetic donor")
    from gbox import characters
    monkeypatch.setattr(characters, "_load", lambda _: ({"nodes": nodes}, None, None, world))
    return source, roles, ([dict(v) for v in vertices], list(triangles))


def choice(index=1, albedo=ALBEDO):
    return {"index": index, "name": MATERIALS[index], "albedo": albedo, "size": [64, 64], "function": "FColorMaskAlbedoMap"}


# --- the class body ------------------------------------------------------------------------------------------------

def test_the_carriers_are_the_groups_that_cover_the_chest():
    model = mt_model.parse_mod(class_mod())
    table = E.group_table(model)
    assert table[3]["y"] == [95.0, 160.0] and table[3]["lod_masks"] == [1, 2]
    carriers = E.carrier_groups(model, table=table)
    # torso (spans the band), upper chest (covers 59 % of it), shirt; not the belt (40 vertices), the legs, the head,
    # the Shadow group or the far-only group
    assert carriers["groups"] == [3, 206, 403]
    assert carriers["shadow_groups"] == [132]
    assert carriers["band_cm"] == [round(.62 * 182, 1), round(.75 * 182, 1)]
    assert carriers["carriers"][403]["cover"] >= E.CARRIER_OVERLAP


def test_the_short_position_formats_decode_inside_the_box():
    model = mt_model.parse_mod(class_mod())
    data = bytearray(model.raw)
    record = model.meshes()[1]
    struct.pack_into(">I", data, model.header()["offsets"]["meshes"] + 56 + 0x14, 0x23305964)
    patched = mt_model.parse_mod(bytes(data))
    assert patched.positions(1) == []                              # mt_model does not list the format
    points = E.record_points(patched, 1)
    assert len(points) == record["vertex_count"]
    assert np.allclose(points, model.positions(1), atol=0.05)


def test_a_standing_t_pose_passes_the_humanoid_gate_and_a_crouch_does_not():
    arc = mt_arc.parse(class_arc())
    gate = E.humanoid_gate(arc, "uEm1000")
    assert gate["passed"], gate["codes"]
    crouched = [(n, a, p, (x, y * .5, z) if n.startswith(("l_", "r_")) and "hand" in n else (x, y, z))
                for n, a, p, (x, y, z) in skeleton()]
    crouched = [(n, a, p, (x * .1, y, z) if "hand" in n else (x, y, z)) for n, a, p, (x, y, z) in crouched]
    entries = [mt_arc.Entry(name=BODY, hash=MOD_HASH, tag=0, size=0, offset=0, data=zlib.compress(class_mod(crouched)))]
    gate = E.humanoid_gate(mt_arc.parse(mt_arc.build(mt_arc.Arc(7, entries))), "uEm1000")
    assert not gate["passed"] and any("T-pose" in code for code in gate["codes"])


def test_the_class_body_is_the_mod_named_after_the_class():
    small = class_mod()
    big = class_mod(skeleton() + [(f"extra{i}", 30 + i, "head", (0., 170. + i, 0.)) for i in range(5)])
    entries = [mt_arc.Entry(name="data\\chara\\em\\em1370\\model\\em1370", hash=MOD_HASH, tag=0, size=0, offset=0,
                            data=zlib.compress(big)),
               mt_arc.Entry(name="data\\chara\\em\\em3200\\model\\em3200", hash=MOD_HASH, tag=0, size=0, offset=0,
                            data=zlib.compress(small))]
    arc = mt_arc.parse(mt_arc.build(mt_arc.Arc(7, entries)))
    assert E.class_body(arc, "uEm3200")[0] == 1                    # its own model, not the larger pupa
    assert M._find_model(arc)[0] == 0
    assert any("largest" in code for code in E.humanoid_gate(arc, "uEm3200")["codes"])


# --- materials -----------------------------------------------------------------------------------------------------

def _row(name, *, albedo=ALBEDO, blend="BSSolid", transparency="FTransparency", function="FColorMaskAlbedoMap",
         colour=(1., 1., 1.), diffuse=(1., 1., 1.), blend_map=""):
    return {"name_hash": zlib.crc32(name.encode()) ^ 0xFFFFFFFF, "blend": blend,
            "functions": {"FTransparency": transparency, "FAlbedo": function, "FVertexDisplacement": "FVertexDisplacement"},
            "slots": {"tAlbedoMap": albedo, "tAlbedoBlendMap": blend_map},
            "constants": {"CBColorMask": {"fColorMaskThreshold": [0.] * 4, "fColorMaskOffset": [0.] * 4,
                                          "fColorMaskColor": list(colour) + [1.], "fColorMask2Color": [1.] * 4},
                          "CBMaterial": {"fDiffuseColor": list(diffuse)}}}


def test_the_material_choice_takes_an_opaque_uncoloured_unshared_albedo(monkeypatch):
    monkeypatch.setattr(E, "MIN_ALBEDO_TEXELS", 16)              # the fixture's albedos are 64x64 and 32x32
    arc = mt_arc.parse(class_arc())
    model = mt_model.parse_mod(class_mod())
    rows_by_name = {"em1000_Head": _row("em1000_Head", transparency="FTransparencyAlpha"),
                    "em1000_ID2_Body": _row("em1000_ID2_Body"),
                    "em1000_Shirt": _row("em1000_Shirt", albedo=SHIRT, colour=(.2, .3, .9)),
                    "em1000_Shadow": _row("em1000_Shadow", albedo=None)}
    monkeypatch.setattr(E, "_material_rows", lambda a, m: {r["name_hash"]: r for r in rows_by_name.values()})
    pick = E.donor_material_choice(arc, model, 2)
    assert (pick["index"], pick["albedo"], pick["size"], pick["mask"]) == (1, ALBEDO, [64, 64], "neutral")
    why = {row["name"]: row["why"] for row in pick["refused"]}
    assert "not opaque" in why["em1000_Head"] and "not the blood overlay" in why["em1000_Shirt"]
    # a shared albedo is refused by default and decided by the path check when one is given
    with pytest.raises(E.EnemyError) as refused:
        E.donor_material_choice(arc, model, 2, others={ALBEDO: ["uEm5200"]})
    assert any("also loaded from uEm5200" in row["why"] for row in refused.value.refused)
    pick = E.donor_material_choice(arc, model, 2, path_check=lambda p: (True, None, ["uEm5200"]))
    assert pick["shared_with"] == ["uEm5200"]
    # a dark diffuse colour and a blood overlay
    rows_by_name["em1000_ID2_Body"] = _row("em1000_ID2_Body", diffuse=(.075, .025, .025))
    rows_by_name["em1000_Shirt"] = _row("em1000_Shirt", albedo=SHIRT, colour=(.1125, .0375, .0375),
                                        blend_map="data\\chara\\textures\\Upper_blood_CH_BM")
    pick = E.donor_material_choice(arc, model, 2)
    assert pick["index"] == 2 and pick["mask"].startswith("blood")
    assert "dark diffuse" in {row["name"]: row["why"] for row in pick["refused"]}["em1000_ID2_Body"]


def test_the_masks_and_the_transparency_ranking():
    assert E._neutral_mask(_row("x")["constants"]) and not E._neutral_mask(_row("x", colour=(.1, 0, 0))["constants"])
    assert E._blood_mask(_row("x", colour=(.1125, .0375, .0375), blend_map="Body_blood_CH_BM"))
    assert not E._blood_mask(_row("x", colour=(.1, .3, .9), blend_map="Body_blood_CH_BM"))     # blue is no blood
    assert not E._blood_mask(_row("x", colour=(.1125, .0375, .0375), blend_map="em_detail"))
    assert E.OPAQUE_AT_REST[0] == "FTransparency" and "FTransparencyAlpha" not in E.OPAQUE_AT_REST


# --- the fit gate --------------------------------------------------------------------------------------------------

def box(w, h, d, floor=0.):
    return {"min": {"x": -w / 2, "y": floor, "z": -d / 2}, "max": {"x": w / 2, "y": floor + h, "z": d / 2}}


@pytest.mark.parametrize("fitted,code", [
    (box(170, 230, 40), "tall"), (box(170, 140, 40), "short"), (box(170, 180, 7.6), "flat"),
    (box(170, 180, 40, floor=30), "floats"), (box(170, 180, 40, floor=-30), "sinks"),
    (box(330, 180, 40), "wide"), (box(250, 180, 40), "wide"), (box(170, 180, 160), "deep"),
    (box(200, 180, 190), "box")])
def test_the_fit_gate_names_every_failure(fitted, code):
    native = box(173, 181, 40)
    report = E.fit_report(native, fitted, rest_degrees=2., skin_bones=18, kind="character", vertices=3000)
    assert not report["passed"] and code in report["codes"]


def test_a_fitted_person_passes_and_the_other_refusals_are_coded():
    native = box(173, 181, 40)
    good = E.fit_report(native, box(180, 181, 38, floor=2.), rest_degrees=4., skin_bones=18, kind="character",
                        vertices=4000, shape={"codes": [], "joint_span": .8})
    assert good["passed"] and good["ratios"]["height"] == 1.0 and good["codes"] == []
    bad = E.fit_report(native, box(180, 181, 38), rest_degrees=35., skin_bones=2, kind="weapon", vertices=40000,
                       shape={"codes": ["exploded"], "joint_span": .1})
    assert set(bad["codes"]) >= {"stretched", "few_bones", "prop", "heavy", "exploded"}


def test_the_donor_shape_finds_a_standing_rig_and_an_exploded_one(donor):
    source, roles, geometry = donor
    shape = E.donor_shape(source, roles, geometry)
    assert shape["codes"] == [] and shape["joint_span"] > .8
    far = ([dict(v) for v in geometry[0]] + [{"position": (0., 800., 0.), "normal": (0, 1, 0), "uv": (0, 0),
                                               "source_joints": (0,), "source_weights": (1.,)}], geometry[1])
    assert "exploded" in E.donor_shape(source, roles, far)["codes"]
    swapped = dict(roles, l_hand=roles["r_hand"], r_hand=roles["l_hand"])
    assert "rig" in E.donor_shape(source, swapped, geometry)["codes"]


def test_a_transparent_texel_takes_its_neighbours_colour_not_its_own():
    rgba = np.zeros((64, 64, 4), np.uint8)
    rgba[..., :3] = (255, 0, 255)                                    # garbage under alpha 0
    rgba[:, :32] = (20, 140, 40, 255)                               # opaque green on the left
    out = np.asarray(E.opaque_atlas(Image.fromarray(rgba, "RGBA")))
    assert out.shape == (64, 64, 3)
    assert np.abs(out[:, 40].astype(int) - (20, 140, 40)).max() < 3  # bled green, no magenta
    solid = Image.new("RGBA", (8, 8), (1, 2, 3, 255))
    assert np.array_equal(np.asarray(E.opaque_atlas(solid)), np.full((8, 8, 3), (1, 2, 3), np.uint8))


# --- the writer ----------------------------------------------------------------------------------------------------

def test_the_re5_graft_takes_an_explicit_template_when_no_record_is_0xffff():
    native = mt_model.parse_mod(class_mod())
    with pytest.raises(R5.EnemyWriterError, match="no native four-weight record"):
        R5._template(native.meshes())
    points = [(-20., 0., 0.), (20., 0., 0.), (0., 180., 0.), (0., 100., 30.)]
    vertices = [{"position": p, "normal": (0., 0., 1.), "uv": (.1, .2), "bones": [1], "weights": [1.]} for p in points]
    built = mtf_author.build_one_mesh(native, vertices, [(0, 1, 2), (1, 3, 2)], material_index=1, template_index=1,
                                      four_weights=True)
    donor = mt_model.parse_mod(built)
    with pytest.raises(R5.EnemyWriterError, match="outside the native table"):
        R5.graft_pieces(native, [(donor, [3], 1)], template=99)
    result, report = R5.graft_pieces(native, [(donor, [3, 206], 1)], template=1)
    model = mt_model.parse_mod(result)
    added = [i for i, r in enumerate(model.meshes()) if r["mesh_type"] == 0xFFFF]
    assert report["template_record"] == 1 and len(added) == 2
    start = model.header()["offsets"]["meshes"]
    assert all(model.raw[start + 56 * i + 0x2C:start + 56 * i + 56] == bytes([0xA1]) * 12 for i in added)


def test_build_class_dresses_the_carriers_and_verify_reads_it_back(donor):
    source, roles, geometry = donor
    native = class_arc()
    carriers = [3, 206, 403]
    atlas = Image.new("RGB", (256, 256), (30, 60, 200))
    payload, receipt = E.build_class(native, "uEm1000", source, roles, choice=choice(), carriers=carriers,
                                     geometry=geometry, atlas=atlas)
    assert receipt["fit"]["passed"] and receipt["bind_mode"] == "keep" and receipt["pose_mode"] == "native_bind_kept"
    assert receipt["carrier_groups"] == carriers and receipt["graft"]["donor_records"] == 3
    assert receipt["template_record"] == 1                         # the torso's LOD-0 four-weight record
    assert receipt["fit"]["native"]["height_cm"] == 182.0 and receipt["fit"]["ratios"]["height"] == pytest.approx(1, abs=.01)
    check = E.verify_class(native, payload, "uEm1000", carriers=carriers, material_index=1, albedos=(ALBEDO,))
    assert check["donor_records"] == 3 and check["native_records"] == 9
    before, after = mt_arc.parse(native), mt_arc.parse(payload)
    assert [i for i, (a, b) in enumerate(zip(before.entries, after.entries)) if a.data != b.data] == [0, 4]
    # the albedo now decodes to the atlas colour through the Y'CbCr model, same size and mips
    rgb, opacity = T.from_arc_entry(after.entries[0]).albedo(0)
    assert np.abs(rgb.reshape(-1, 3).mean(0) - (30, 60, 200)).max() < 12 and opacity.min() > 250
    model = mt_model.parse_mod(E._raw(after.entries[4]))
    donors = [r for r in model.meshes() if r["mesh_type"] == 0xFFFF]
    assert sorted(r["group_index"] for r in donors) == carriers and {r["level_of_detail"] for r in donors} == {0xFF}
    # tampering is caught
    broken = bytearray(E._raw(after.entries[4]))
    off = model.header()["offsets"]["bones"]
    broken[off + 30] ^= 0xFF
    entries = list(after.entries)
    entries[4] = mt_arc.Entry(name=entries[4].name, hash=entries[4].hash, tag=entries[4].tag, size=0, offset=0,
                              data=zlib.compress(bytes(broken)))
    with pytest.raises(E.EnemyError, match="skeleton"):
        E.verify_class(native, mt_arc.build(mt_arc.Arc(7, entries)), "uEm1000", carriers=carriers, material_index=1,
                       albedos=(ALBEDO,))
    with pytest.raises(E.EnemyError, match="carriers"):
        E.verify_class(native, payload, "uEm1000", carriers=[3], material_index=1, albedos=(ALBEDO,))


def test_build_class_refuses_a_donor_that_does_not_fit(donor):
    source, roles, geometry = donor
    flat = ([v | {"position": (v["position"][0], v["position"][1], 0.)} for v in geometry[0]], geometry[1])
    with pytest.raises(E.DonorRefused) as refused:
        E.build_class(class_arc(), "uEm1000", source, roles, choice=choice(), carriers=[3], geometry=flat, atlas=None)
    assert "flat" in refused.value.report["codes"]
    with pytest.raises(E.DonorRefused) as heavy:
        E.build_class(class_arc(), "uEm1000", source, roles, choice=choice(), carriers=[3, 206, 403],
                      geometry=geometry, atlas=None, vertex_budget=10)
    assert "heavy" in heavy.value.report["codes"]


# --- the plan ------------------------------------------------------------------------------------------------------

def test_placements_coload_and_conflicts():
    sets = {"s1213Soft": {"stage": "s1203", "stage_name": "Mining the Depths", "mode": "no_mercy",
                          "census": {"uEm5000": 159, "uEm5060": 54}, "refs": {"uSm1537": 12}},
            "s1217Soft": {"stage": "s1207", "stage_name": "Rooftop Mission", "mode": "no_mercy",
                          "census": {"uEm5200": 112, "uEm5000": 46}, "refs": {}},
            "s1203Soft": {"stage": "s1203", "stage_name": "Mining the Depths", "mode": "mercenaries",
                          "census": {"uEm5000": 77}, "refs": {}}}
    assert C.placements(sets) == {"uEm5000": 205, "uEm5200": 112, "uEm5060": 54}
    existing = {"uEm5000", "uEm5060", "uEm5200", "uEm5000Helmet", "uSm1537", "uPl00LeonUsa", "uEm5000Base",
                "s1203", "s1213Soft", "s1207", "s1217Soft", "s1203Soft", "uEm1000"}
    loaded = C.coload(sets, existing)
    assert {"uEm5060", "uEm5200", "uEm5000Helmet", "uSm1537", "uPl00LeonUsa", "uEm5000Base"} <= loaded["uEm5000"]
    assert "uEm5060" not in loaded["uEm5200"] and "uEm1000" not in loaded["uEm5000"]
    family = C.family_subs({"uEm4300", "uEm5000", "s1207"},
                           {"uEm4301Pipe", "uEm4300", "uEm5005", "uEm5000Axe", "uEm5100Cap", "s1207Soft"})
    assert family == {"uEm4301Pipe", "uEm5000Axe", "s1207Soft"}      # not the plain class uEm5005, not 51xx
    index = {"a_BM": {"uEm5000", "uEm5200"}, "b_BM": {"uEm5000"}, "c_BM": {"uEm5000", "uEm1000"}}
    assert C.conflicts(index, loaded["uEm5000"], "uEm5000") == {"a_BM": ["uEm5200"]}


def test_a_shared_path_is_usable_only_when_every_loadable_copy_is_dressed():
    index = {"m_body_BM": {"uEm5000", "uEm5200", "uEm5181"}, "own_BM": {"uEm5000"}}
    loaded = {"uEm5000": {"uEm5000", "uEm5200", "uEm5060"}, "uEm5200": {"uEm5200", "uEm5000", "uEm5181"},
              "uEm5181": {"uEm5181", "uEm5200"}}
    paths = C.Paths(index, loaded, {"uEm5000", "uEm5200"})
    ok, why, _ = paths.check("uEm5000")("m_body_BM")
    assert not ok and "uEm5181" in why                              # 5200 can load beside an undressed 5181
    paths.dressed.add("uEm5181")
    ok, why, shared = paths.check("uEm5000")("m_body_BM")
    assert ok and shared == ["uEm5181", "uEm5200"]
    paths.claims["m_body_BM"] = "uEm5200"
    ok, why, _ = paths.check("uEm5000")("m_body_BM")
    assert not ok and "claimed by uEm5200" in why
    assert paths.check("uEm5000")("own_BM")[0]


def test_shared_atlases_and_the_consistency_check(tmp_path):
    folder = tmp_path / "NX"
    folder.mkdir()
    for cls in ("uEm5000", "uEm5200"):
        entries = [mt_arc.Entry(name=ALBEDO, hash=TEX_HASH, tag=0, size=0, offset=0, data=zlib.compress(albedo_tex()))]
        (folder / f"{cls}.arc").write_bytes(mt_arc.build(mt_arc.Arc(7, entries)))
    written = {"uEm5000": {"archive": "uEm5000.arc"}, "uEm5200": {"archive": "uEm5200.arc"}}
    assignments = {ALBEDO: {"class": "uEm5200", "donor": "toni", "atlas": Image.new("RGB", (64, 64), (200, 30, 30))}}
    shared = C.share_atlases(folder, assignments, written)
    assert list(shared) == ["uEm5000"] and shared["uEm5000"][0]["donor"] == "toni"
    rgb, _ = T.from_arc_entry(mt_arc.parse((folder / "uEm5000.arc").read_bytes()).entries[0]).albedo(0)
    assert np.abs(rgb.reshape(-1, 3).mean(0) - (200, 30, 30)).max() < 12
    sets = {"s1217Soft": {"stage": "s1207", "census": {"uEm5200": 1, "uEm5000": 1}, "refs": {}}}
    index = {ALBEDO: {"uEm5000", "uEm5200"}}
    assert C.consistency(sets, set(index[ALBEDO]), index, assignments, {"uEm5000", "uEm5200"}) == []
    stale = C.consistency(sets, set(index[ALBEDO]), index, assignments, {"uEm5200"})
    assert stale and stale[0]["native_copies"] == ["uEm5000"]


def _meta(slug, name, game, kind="character"):
    return {"slug": slug, "name": name, "kind": kind, "model": f"{slug}.glb", "source": {"game_title": game},
            "rig": {"skinned": True, "roles": {}}}


def test_the_donor_order_drops_rejects_players_props_and_second_costumes(monkeypatch, tmp_path):
    from gbox import re6_switch_cast
    pool = [_meta("toni_a", "Toni Cipriani (mask)", "GTA LCS"), _meta("toni_b", "Toni Cipriani (shirt)", "GTA LCS"),
            _meta("g8", "G8 Germany", "007 AUF"), _meta("gun", "Pistol", "007 AUF", kind="weapon"),
            _meta("bad", "Huge", "Game X"), _meta("ok1", "Tank (costume 2) (Def Jam PS2)", "Def Jam"),
            _meta("ok2", "Sheva Alomar", "RE5")]
    monkeypatch.setattr(re6_switch_cast, "donor_pool", lambda library, tier="full": list(pool))
    order, skipped = C.candidates(tmp_path, seed=1, refused={"bad": "too wide"}, exclude=("g8",))
    slugs = [m["slug"] for m in order]
    assert "bad" not in slugs and "g8" not in slugs and "gun" not in slugs
    assert len([s for s in slugs if s.startswith("toni")]) == 1
    assert skipped == {"donor_rejects": 1, "already a player in the base build": 1, "library kind 'weapon'": 1,
                       "another costume of a character already drawn": 1}
    assert C.candidates(tmp_path, seed=1, refused={"bad": "x"}, exclude=("g8",))[0] == order        # seeded
    assert C.base_name(pool[5]) == "tank" and C.base_name(pool[0]) == C.base_name(pool[1]) == "toni cipriani"


def test_the_reject_list_is_read_in_its_own_format(tmp_path):
    path = tmp_path / "donor_rejects.json"
    path.write_text(json.dumps({"format": 1, "titles": {
        "all": {"pistol": {"reason": "not a character"}},
        "re6": {"wide_guy": {"reason": "3.3 m wide"}, "player_only": {"reason": "x", "roles": ["player"]}},
        "re4": {"re4_only": {"reason": "y"}}}}), encoding="utf-8")
    got = C.rejected(path)
    assert set(got) == {"pistol", "wide_guy"} and "3.3 m wide" in got["wide_guy"]
    assert C.rejected(tmp_path / "missing.json") == {}


def test_the_manifest_lists_the_base_build_unchanged_then_the_enemies(tmp_path):
    base, out = tmp_path / "base", tmp_path / "out"
    for rel in ("exefs/main", "romfs/nativeNXx64/arc/NX/s1200.arc", "romfs/nativeNXx64/arc/NX/uPl00LeonUsa.arc"):
        (base / rel).parent.mkdir(parents=True, exist_ok=True)
        (base / rel).write_bytes(b"x")
    (base / ".gbox-mod.json").write_text("{}")
    (out / "romfs/nativeNXx64/arc/NX").mkdir(parents=True)
    (out / "romfs/nativeNXx64/arc/NX/uEm1000.arc").write_bytes(b"y")
    (out / "receipt.json").write_text("{}")
    changes = C.manifest(out, base)
    assert sorted(changes) == ["exefs/main", "romfs/nativeNXx64/arc/NX/s1200.arc",
                               "romfs/nativeNXx64/arc/NX/uEm1000.arc", "romfs/nativeNXx64/arc/NX/uPl00LeonUsa.arc"]
    assert changes["exefs/main"] == {"from": str((base / "exefs/main").resolve())}
    assert changes["romfs/nativeNXx64/arc/NX/uEm1000.arc"]["from"].endswith("uEm1000.arc")
    (base / "romfs/nativeNXx64/arc/NX/uEm1000.arc").write_bytes(b"z")
    with pytest.raises(ValueError, match="in the base build too"):
        C.manifest(out, base)
