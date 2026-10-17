"""gbox.sm64_decomp without the game or any third-party file: a synthetic actor in the decomp's C layout (Mario's
20-part skeleton, a Fast64 "skinned" seam, a matcap material, a decal texture) goes through the reader, gets all 18
body roles, is written as a donor GLB and imported through the Blender round trip (`characters op=add`) as a ready
donor that the cast swap's gate accepts; plus the binary (ROM) geo walker and the ROM layout scan."""
import struct
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from gbox import blender_roundtrip as RT, cast_swap as CS, characters as C, replacement_readiness as RR
from gbox import sm64_decomp as D
from gbox.retarget_profile import ROLES

# Mario's skeleton (part index, parent part, translation, has a mesh): +Y up, the character's left on +X
PARTS = [(0, None, (0, 0, 0), False), (1, 0, (0, 80, 0), True), (2, 1, (0, 30, 0), True), (3, 2, (0, 30, 0), True),
         (4, 2, (12, 25, 0), False), (5, 4, (0, 0, 0), True), (6, 5, (15, 0, 0), True), (7, 6, (15, 0, 0), True),
         (8, 2, (-12, 25, 0), False), (9, 8, (0, 0, 0), True), (10, 9, (-15, 0, 0), True), (11, 10, (-15, 0, 0), True),
         (12, 1, (10, -5, 0), False), (13, 12, (0, 0, 0), True), (14, 13, (0, -35, 0), True), (15, 14, (0, -35, 0), True),
         (16, 1, (-10, -5, 0), False), (17, 16, (0, 0, 0), True), (18, 17, (0, -35, 0), True), (19, 18, (0, -35, 0), True)]
CUBE = [(-1, -1, -1), (1, -1, -1), (1, 1, -1), (-1, 1, -1), (-1, -1, 1), (1, -1, 1), (1, 1, 1), (-1, 1, 1)]
FACES = [(0, 2, 1), (0, 3, 2), (4, 5, 6), (4, 6, 7), (0, 1, 5), (0, 5, 4), (3, 7, 6), (3, 6, 2), (0, 4, 7), (0, 7, 3),
         (1, 2, 6), (1, 6, 5)]


def _vtx(name, pts, size=6, st=(0, 0)):
    rows = []
    for x, y, z in pts:
        n = np.array([x, y, z], float)
        n = n / (np.linalg.norm(n) or 1) * 120
        rows.append("{{{%d, %d, %d}, 0, {%d, %d}, {%d, %d, %d, 255}}}" % (x * size, y * size, z * size, st[0], st[1],
                                                                         int(n[0]) & 0xFF, int(n[1]) & 0xFF, int(n[2]) & 0xFF))
    return f"Vtx {name}[{len(pts)}] = {{\n\t" + ",\n\t".join(rows) + "\n};\n"


def actor(d: Path) -> Path:
    """A synthetic actor folder: model.inc.c + geo.inc.c + two PNG textures."""
    from PIL import Image
    d.mkdir(parents=True, exist_ok=True)
    Image.new("RGBA", (16, 16), (10, 20, 200, 255)).save(d / "body.rgba32.png")       # a flat 'matcap'
    eye = np.zeros((8, 8, 4), np.uint8)
    eye[..., :3], eye[..., 3] = (250, 250, 250), 255
    eye[2:6, 2:6, :3] = (0, 0, 0)
    Image.fromarray(eye, "RGBA").save(d / "eye.rgba32.png")
    m = ["Lights1 test_skin_lights = gdSPDefLights1(\n\t0x7F, 0x53, 0x37,\n\t0xFE, 0xA7, 0x6E, 0x28, 0x28, 0x28);\n",
         'Gfx test_body_rgba32_aligner[] = {gsSPEndDisplayList()};\nu8 test_body_rgba32[] = "actors/test/body.rgba32";\n',
         'u8 test_eye_rgba32[] = "actors/test/eye.rgba32";\n',
         "Gfx mat_skin[] = {\n\tgsDPPipeSync(),\n\tgsDPSetCombineLERP(0, 0, 0, SHADE, 0, 0, 0, ENVIRONMENT, 0, 0, 0, SHADE, 0, 0, 0, ENVIRONMENT),\n"
         "\tgsSPTexture(65535, 65535, 0, 0, 1),\n\tgsSPSetLights1(test_skin_lights),\n\tgsSPEndDisplayList(),\n};\n",
         "Gfx mat_body[] = {\n\tgsDPSetCombineLERP(0, 0, 0, TEXEL0, 0, 0, 0, ENVIRONMENT, 0, 0, 0, TEXEL0, 0, 0, 0, ENVIRONMENT),\n"
         "\tgsSPSetGeometryMode(G_TEXTURE_GEN),\n\tgsSPTexture(16319, 16319, 0, 0, 1),\n"
         "\tgsDPSetTextureImage(G_IM_FMT_RGBA, G_IM_SIZ_32b, 16, test_body_rgba32),\n"
         "\tgsDPSetTile(G_IM_FMT_RGBA, G_IM_SIZ_32b, 4, 0, 0, 0, G_TX_WRAP | G_TX_NOMIRROR, 4, 0, G_TX_WRAP | G_TX_NOMIRROR, 4, 0),\n"
         "\tgsDPSetTileSize(0, 0, 0, 60, 60),\n\tgsSPEndDisplayList(),\n};\n"
         "Gfx mat_revert_body[] = {\n\tgsSPClearGeometryMode(G_TEXTURE_GEN),\n\tgsSPEndDisplayList(),\n};\n",
         "Gfx mat_eye[] = {\n\tgsDPSetCombineLERP(0, 0, 0, TEXEL0, 0, 0, 0, ENVIRONMENT, 0, 0, 0, TEXEL0, 0, 0, 0, ENVIRONMENT),\n"
         "\tgsSPTexture(65535, 65535, 0, 0, 1),\n\tgsDPSetTextureImage(G_IM_FMT_RGBA, G_IM_SIZ_32b, 8, test_eye_rgba32),\n"
         "\tgsDPSetTile(G_IM_FMT_RGBA, G_IM_SIZ_32b, 2, 0, 0, 0, 0, 3, 0, 0, 3, 0),\n\tgsDPSetTileSize(0, 0, 0, 28, 28),\n"
         "\tgsSPEndDisplayList(),\n};\n"]
    for k, _parent, _t, mesh in PARTS:
        if not mesh or k == 6:
            continue
        m.append(_vtx(f"part{k}_vtx", CUBE, st=(128, 128)))
        tris = "\n".join(f"\tgsSP1Triangle({a}, {b}, {c}, 0)," for a, b, c in FACES)
        mat = "mat_eye" if k == 3 else "mat_body" if k == 1 else "mat_skin"
        m.append(f"Gfx part{k}_tri[] = {{\n\tgsSPVertex(part{k}_vtx + 0, 8, 0),\n{tris}\n\tgsSPEndDisplayList(),\n}};\n"
                 f"Gfx part{k}_mesh[] = {{\n\tgsSPDisplayList({mat}),\n\tgsSPDisplayList(part{k}_tri),\n"
                 + ("\tgsSPDisplayList(mat_revert_body),\n" if k == 1 else "") + "\tgsSPEndDisplayList(),\n};\n")
    # the forearm: a Fast64 skinned seam - the elbow ring is loaded under the upper arm's matrix (slots 0-3), the
    # forearm's own vertices go to slots 4-7, and its triangles use both
    m.append(_vtx("seam_vtx", [(-1, -1, -1), (-1, 1, -1), (-1, 1, 1), (-1, -1, 1)]))
    m.append(_vtx("fore_vtx", [(1, -1, -1), (1, 1, -1), (1, 1, 1), (1, -1, 1)]))
    m.append("Gfx part6_skinned[] = {\n\tgsSPDisplayList(mat_skin),\n\tgsSPVertex(seam_vtx + 0, 4, 0),\n"
             "\tgsSPEndDisplayList(),\n};\n")
    m.append("Gfx part6_mesh[] = {\n\tgsSPDisplayList(mat_skin),\n\tgsSPVertex(fore_vtx + 0, 4, 4),\n"
             "\tgsSP2Triangles(0, 4, 5, 0, 0, 5, 1, 0),\n\tgsSP2Triangles(1, 5, 6, 0, 1, 6, 2, 0),\n"
             "\tgsSP2Triangles(2, 6, 7, 0, 2, 7, 3, 0),\n\tgsSP2Triangles(3, 7, 4, 0, 3, 4, 0, 0),\n"
             "\tgsSP2Triangles(4, 7, 6, 0, 4, 6, 5, 0),\n\tgsSPEndDisplayList(),\n};\n")
    (d / "model.inc.c").write_text("\n".join(m))
    kids = {}
    for k, parent, _t, _m in PARTS:
        kids.setdefault(parent, []).append(k)

    def emit(k, depth):
        _k, _p, t, mesh = PARTS[k]
        tab = "\t" * depth
        dl = f"part{k}_mesh" if mesh else "NULL"
        out = [f"{tab}GEO_ANIMATED_PART(LAYER_OPAQUE, {t[0]}, {t[1]}, {t[2]}, {dl}),"]
        sub = kids.get(k, [])
        if sub or k == 5:
            out.append(f"{tab}GEO_OPEN_NODE(),")
            if k == 5:
                out.append(f"{tab}\tGEO_DISPLAY_LIST(LAYER_OPAQUE, part6_skinned),")
            for c in sub:
                out += emit(c, depth + 1)
            out.append(f"{tab}GEO_CLOSE_NODE(),")
        return out
    body = "\n".join(emit(0, 4))
    geo = ("#include \"src/game/envfx_snow.h\"\n\nconst GeoLayout test_body[] = {\n\tGEO_NODE_START(),\n\tGEO_OPEN_NODE(),\n"
           f"{body}\n\tGEO_CLOSE_NODE(),\n\tGEO_RETURN(),\n}};\n"
           "const GeoLayout test_geo[] = {\n\tGEO_NODE_START(),\n\tGEO_OPEN_NODE(),\n\t\tGEO_SHADOW(1, 180, 100),\n"
           "\t\tGEO_OPEN_NODE(),\n\t\t\tGEO_SCALE(LAYER_FORCE, 16384),\n\t\t\tGEO_OPEN_NODE(),\n"
           "\t\t\t\tGEO_SWITCH_CASE(0, geo_switch_test),\n\t\t\t\tGEO_OPEN_NODE(),\n\t\t\t\t\tGEO_BRANCH(1, test_body),\n"
           "\t\t\t\tGEO_CLOSE_NODE(),\n\t\t\tGEO_CLOSE_NODE(),\n\t\tGEO_CLOSE_NODE(),\n\tGEO_CLOSE_NODE(),\n\tGEO_END(),\n};\n")
    (d / "geo.inc.c").write_text(geo)
    return d


@pytest.fixture
def test_actor(tmp_path):
    return actor(tmp_path / "test")


def test_c_actor_parses_into_mario_skeleton_with_smooth_normals_and_one_cache_seam(test_actor):
    model, joints = D.pack_character(test_actor, "test", geo="test_geo")
    assert sum(1 for j in model["joints"] if j["part"] is not None) == 20
    # the geo scale (0.25) and metres: the hip part sits 80 units up -> 0.2 m
    hip = next(j for j in model["joints"] if j["part"] == 1)
    assert np.allclose(hip["world"][3, :3], [0, 0.2, 0])
    for p in model["prims"]:                                  # every lit vertex keeps a unit normal
        assert np.allclose(np.linalg.norm(p["N"], axis=1), 1, atol=1e-3)
    seam = [p for p in model["prims"] if any(len({int(p["J"][i]) for i in t}) == 2 for t in p["T"])]
    assert seam, "the forearm's triangles join vertices of two joints (the elbow seam stays closed)"
    up = next(k for k, j in enumerate(model["joints"]) if j["part"] == 5)
    fore = next(k for k, j in enumerate(model["joints"]) if j["part"] == 6)
    joined = {int(j) for p in seam for t in p["T"] for j in p["J"][t]}
    assert {up, fore} <= joined


def test_texgen_material_becomes_its_matcap_colour_and_decals_stay_textures(test_actor):
    model, _ = D.pack_character(test_actor, "test", geo="test_geo")
    mats = model["materials"]
    body = next(m for m in mats if m["texgen"])
    assert body["image"] is None and np.allclose(body["colour"][:3], np.array([10, 20, 200]) / 255, atol=0.01)
    eye = next(m for m in mats if m["image"] is not None)
    assert eye["image"].shape == (8, 8, 4) and not eye["texgen"]
    skin = next(m for m in mats if m["mode"] == "shade")
    assert np.allclose(skin["colour"][:3], np.array([0xFE, 0xA7, 0x6E]) / 255, atol=0.01)   # the light's diffuse


def test_finish_maps_all_18_roles_without_moving_a_vertex(test_actor):
    model, _ = D.pack_character(test_actor, "test", geo="test_geo")
    before = np.concatenate([p["P"] for p in model["prims"]]).copy()
    model, roles = D.finish(model, "mario")
    assert set(roles) == set(ROLES) and len(set(roles.values())) == 18
    after = np.concatenate([p["P"] for p in model["prims"]])
    assert np.allclose(after - after[:, 1].min() * np.array([0, 1, 0]), before - before[:, 1].min() * np.array([0, 1, 0]))
    J = model["joints"]
    w = {r: J[j]["world"][3, :3] for r, j in roles.items()}
    assert w["l_upper"][0] > 0 > w["r_upper"][0]              # left on +X
    assert w["head"][1] == w["neck"][1] > w["chest"][1] > w["hip"][1] > w["l_foot"][1]   # head at the neck (head base)
    assert abs(w["l_clav"][0]) < abs(w["l_upper"][0])         # the clavicle has length: pulled toward the chest
    assert J[roles["head"]]["parent"] == roles["neck"]
    assert after[:, 1].min() == pytest.approx(0, abs=1e-6)   # stands on y = 0


def test_split_head_anchors_the_head_joint_at_the_neck_not_the_head_centre():
    """#1816: a centre-anchored synthetic head joint shifts the retarget's head-height reference (head joint Y) up to
    the head centre, so the DOA2/SM64 fit maps the head centre onto the target's neck and sinks the head into the
    shoulders. The head joint must sit at the neck (the head's base) like native donors."""
    W = np.eye(4)
    W[3, :3] = (0.0, 1.4, 0.0)                          # the neck pivot (SM64 head part), 1.4 m up
    # a tall head: geometry from y=1.4 (base) to y=2.0 (top), centred ~1.7
    P = np.array([[0, 1.4, 0], [0, 2.0, 0], [0.2, 1.7, 0]], np.float32)
    model = {"joints": [{"parent": None, "world": np.eye(4), "part": 0},
                        {"parent": 0, "world": W, "part": 3, "name": "head"}],
             "prims": [{"P": P, "N": np.zeros((3, 3)), "UV": np.zeros((3, 2)), "J": np.array([1, 1, 1], np.int64),
                        "T": np.array([[0, 1, 2]], np.int64), "mat": 0}],
             "materials": [{"colour": [1, 1, 1, 1], "image": None, "texgen": False, "mode": "shade", "name": "m0"}]}
    head = D.split_head(model, 1)
    neck_pos = model["joints"][1]["world"][3, :3]
    head_pos = model["joints"][head]["world"][3, :3]
    assert head_pos[1] == neck_pos[1]                    # head anchored at the neck, not the head centre (~1.7)
    assert model["joints"][head]["parent"] == 1
    assert (model["prims"][0]["J"] == head).all()        # the head geometry rides the head joint


def test_mirrored_skeleton_gets_its_sides_swapped():
    world = {1: np.array([-0.2, 1, 0]), 2: np.array([0.2, 1, 0])}
    assert D.mirror_sides({"l_upper": 1, "r_upper": 2, "hip": 0}, world) == {"r_upper": 1, "l_upper": 2, "hip": 0}
    assert D.mirror_sides({"l_upper": 2, "r_upper": 1}, world) == {"l_upper": 2, "r_upper": 1}


def test_skirt_legs_blend_the_dress_between_hip_and_legs():
    # a cone 'dress' on the hip joint: legs are added, weights sum to 1, the waist stays on the hip
    ang = np.linspace(0, 2 * np.pi, 16, endpoint=False)
    rings = [(y, r) for y, r in ((1.0, 0.1), (0.6, 0.2), (0.2, 0.3), (0.0, 0.32))]
    P = np.array([(r * np.cos(a), y, r * np.sin(a)) for y, r in rings for a in ang], np.float32)
    T = np.array([(i, i + 1, i + 16) for i in range(len(P) - 17)])
    W = np.eye(4)
    W[3, :3] = (0, 1.0, 0)
    model = {"joints": [{"parent": None, "world": np.eye(4), "part": 0}, {"parent": 0, "world": W, "part": 1}],
             "prims": [{"P": P, "N": np.zeros_like(P), "UV": np.zeros((len(P), 2), np.float32), "J": np.ones(len(P), np.int64),
                        "T": T, "mat": 0}], "materials": [{"colour": [1, 1, 1, 1], "image": None, "texgen": False,
                                                            "mode": "shade", "name": "m0"}]}
    roles = D.add_skirt_legs(model, 1)
    assert set(roles) == {"l_thigh", "l_shin", "l_foot", "r_thigh", "r_shin", "r_foot"}
    p = model["prims"][0]
    assert np.allclose(p["W4"].sum(1), 1)
    hem_left = np.where((P[:, 1] == 0.0) & (P[:, 0] > 0.25))[0]
    assert all(roles["l_shin"] in p["J4"][i] for i in hem_left)
    waist = np.where(P[:, 1] >= 1.0)[0]
    assert all(p["J4"][i][0] == 1 and p["W4"][i][0] == 1 for i in waist)
    lf, rf = model["joints"][roles["l_foot"]]["world"][3], model["joints"][roles["r_foot"]]["world"][3]
    assert lf[0] > 0 > rf[0]


@pytest.fixture
def lib(tmp_path, monkeypatch):
    root = tmp_path / "characters"
    root.mkdir()
    monkeypatch.setenv("GBOX_CHARACTERS", str(root))
    ctx = SimpleNamespace(config=SimpleNamespace(cache=str(tmp_path / "cache")), progress=lambda *a, **k: None,
                          artifact=lambda *a, **k: None, server=None, headers={})
    return root, ctx


def test_donor_glb_imports_through_the_blender_round_trip_as_a_ready_donor(test_actor, lib, tmp_path):
    root, ctx = lib
    model, _ = D.pack_character(test_actor, "test", geo="test_geo")
    model, roles = D.finish(model, "mario")
    info = {"pack": "Test pack", "url": "https://example.invalid/pack", "licence": "test licence: local use only",
            "attribution": "test modellers", "character": "mario", "donor_group": "mario", "donor_quality": "hd",
            "name": "Mario (HD, test)", "game_title": "Test pack (Super Mario 64 HD models)"}
    glb = D.to_glb(model, roles, tmp_path / "mario_hd.glb", name="mario", source_info=info)
    gl, _ = RT.attachments.read_gltf(glb)
    named = {n["extras"]["gbox_role"]: n["name"] for n in gl["nodes"] if "gbox_role" in (n.get("extras") or {})}
    assert set(named) == set(ROLES)                           # the Blender add-on's role bones
    # characters op=add, the same call POST /api/characters/blender/import queues (no rig_roles: read from extras)
    res = C.add_model(ctx, C.CharIn(op="add", character="mario_hd", path=str(glb), auto_rig=False))
    meta = C.get(root, res["entry"]["slug"])
    assert res["mode"] == "new" and meta["slug"] == "mario_hd" and meta["name"] == "Mario (HD, test)"
    assert meta["rig"]["roles"] == named and meta["licence"] == "test licence: local use only"
    assert meta["attribution"] == "test modellers" and meta["donor_group"] == "mario" and meta["character"] == "mario"
    assert meta["source"]["game_title"] == "Test pack (Super Mario 64 HD models)"
    assert meta["source"]["url"] == "https://example.invalid/pack"
    meta = RR.ensure(root, meta, force=True)
    rd = meta["readiness"]
    assert rd["status"] == "ready" and rd["rig"]["roles_mapped"] == 18 and not rd["rig"]["roles_absent"]
    assert rd["facing"]["facing"] == "+Z" and rd["model"]["up"] == "+Y"
    assert CS.retarget_check(meta, root) is None              # the cast swap's donor gate
    donors, refused, _ = CS.gate([meta], root)
    assert [m["slug"] for m in donors] == ["mario_hd"] and not refused


# ---------------------------------------------------------------- binary geo layouts and the ROM scan

def _geo_bin(cmds: list[bytes]) -> bytes:
    return b"".join(cmds)


def test_binary_geo_reopens_the_last_node_after_a_close_like_the_game():
    # part0 { part1 { } { part2 } } part3 : Yoshi's head reopens after its switch's close
    part = lambda x: struct.pack(">BBhhhI", 0x13, 1, x, 0, 0, 0)          # noqa: E731
    o, c = b"\x04\x00\x00\x00", b"\x05\x00\x00\x00"
    geo = _geo_bin([part(0), o, part(1), o, c, o, part(2), c, part(3), c, b"\x01\x00\x00\x00"])
    mem = D.SegMem({0x0C: geo})
    tree = D.build_tree(D.geo_cmds_rom(mem, 0x0C000000))
    p0 = tree["children"][0]
    assert [n["t"][0] for n in p0["children"]] == [1, 3]
    assert [n["t"][0] for n in p0["children"][0]["children"]] == [2]


def test_rom_layout_finds_the_segment_loads_and_marios_animation_table():
    rom = bytearray(0x10000)
    rom[0x100:0x10C] = struct.pack(">BBHII", 0x18, 0x0C, 0x04, 0x2000, 0x3000)    # LOAD_MIO0 seg 4
    rom[0x2000:0x2004] = b"MIO0"
    rom[0x10C:0x118] = struct.pack(">BBHII", 0x17, 0x0C, 0x17, 0x3000, 0x3400)    # LOAD_RAW seg 0x17
    rom[0x8000:0x8010] = struct.pack(">IIII", 0xD1, 0, 8 + 0xD1 * 8, 0x40)          # Mario's DMA table
    lay = D.rom_layout(bytes(rom))
    assert lay["seg04"] == (0x2000, 0x3000) and lay["seg17"] == (0x3000, 0x3400) and lay["mario_anims"] == 0x8000


def test_c_animation_channels_pose_the_parts():
    vals = np.array([0, 0, 0, 0x4000, 0, 0], np.int64)
    idx = np.array([1, 0, 1, 0, 1, 0, 1, 3, 1, 1, 1, 2] * 1, np.int64)   # root xyz, then part 0 rx ry rz
    rots = D.rots_from_channels(D.anim_channels(vals, idx))
    assert rots == [(0x4000, 0, 0)]


def test_sm64_reader_roster_adds_the_decomp_donors_to_mario():
    rd = next(r for r in C.DEDICATED if r[0] == "sm64")
    slugs = [e["slug"] for e in rd[2]()]
    assert slugs[0] == "mario" and {"sm64_mario", "sm64_peach", "sm64_toad", "sm64_yoshi", "sm64_bowser"} <= set(slugs)
