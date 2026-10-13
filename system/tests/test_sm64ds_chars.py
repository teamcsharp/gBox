"""Super Mario 64 DS reader (gbox.sm64ds_chars) and the shared Nitro formats (gbox.formats.nitro), on synthetic data:
LZ77/LZ10/LZ11, the FNT + NARC + cartridge file system, every DS texel format, GX display lists (matrix slots,
triangles / quads / strips, the vertex commands), a two-bone BMD -> rigged, textured GLB with roles, the DEDICATED
registration and the fingerprinter's NDS listing; then the owned ROM (skipped without it)."""
import os
import struct
from pathlib import Path

import numpy as np
import pytest

from gbox import characters as C, sm64ds_chars as S, uap
from gbox.formats import nitro

GID = "917483267d246594"


# ---------------------------------------------------------------- codecs and containers

def test_lz77_tag_and_lz10_literal_round_trip():
    data = bytes(range(256)) * 3 + b"tail"
    packed = nitro.lz10_literal(data)
    assert packed[:4] == b"LZ77" and nitro.is_compressed(packed)
    assert nitro.decompress(packed) == data
    bare = nitro.lz10_literal(data, magic=False)
    assert nitro.lz10_decompress(bare) == data and nitro.decompress(bare) == bare      # untagged: left alone
    assert nitro.decompress(b"BMD raw") == b"BMD raw"           # untagged payloads pass through


def test_lz11_back_references():
    # 'ab' literals, then a 2-byte token: length 6 (ind 5 -> 6), displacement 2 -> "abababab"
    stream = bytes([0x11, 8, 0, 0, 0b00100000, ord("a"), ord("b"), 0x50, 0x01])
    assert nitro.lz11_decompress(stream) == b"abababab"
    assert nitro.decompress(b"LZ77" + stream + b"\0\0\0") == b"abababab"


def test_fnt_narc_and_directory_ids():
    files = {"data/player/mario_model.bmd": nitro.lz10_literal(b"M" * 40), "data/player/x.bca": b"anim",
             "data/enemy/koopa/koopa_model.bmd": b"K" * 12, "root.bin": b"r"}
    fnt, order = nitro.build_fnt(list(files))
    names = nitro.parse_fnt(fnt, len(order))
    assert sorted(names.values()) == sorted(files) and [names[i] for i in range(len(order))] == order
    members = dict(nitro.narc(nitro.build_narc(files)))
    assert members == files
    with pytest.raises(ValueError):
        nitro.narc(b"NOPE" + b"\0" * 32)


def _rom(files: dict[str, bytes], gamecode=b"ASME") -> bytes:
    fnt, order = nitro.build_fnt(list(files))
    body = bytearray(b"\0" * 0x200)
    fat = bytearray()
    for p in order:
        start = len(body)
        body += files[p]
        fat += struct.pack("<II", start, len(body))
        body += b"\xff" * (-len(body) % 4)
    fnt_off = len(body)
    body += fnt + b"\xff" * (-len(fnt) % 4)
    fat_off = len(body)
    body += fat
    body[0:12] = b"S.MARIO64DS\0"
    body[12:16] = gamecode
    struct.pack_into("<4I", body, 0x40, fnt_off, len(fnt), fat_off, len(fat))
    return bytes(body)


def test_nitro_rom_reads_paths_and_decompresses():
    rom = nitro.NitroROM(_rom({"data/a.bin": nitro.lz10_literal(b"hello"), "b.txt": b"plain"}))
    assert rom.gamecode == "ASME" and rom.paths() == ["b.txt", "data/a.bin"]
    assert rom.read("DATA/A.BIN") == b"hello" and rom.read("b.txt") == b"plain"
    with pytest.raises(KeyError):
        rom.raw("missing")


def test_disc_listing_lists_a_ds_rom(tmp_path):
    from gbox.formats import disc
    p = tmp_path / "game.nds"
    p.write_bytes(_rom({"ARCHIVE/arc0.narc": nitro.build_narc({"x": b"1"}), "data/m.bmd": nitro.lz10_literal(b"z" * 64)}))
    L = disc.listing(p)
    assert L.kind == "nitrofs" and {f["path"] for f in L.files} == {"ARCHIVE/arc0.narc", "data/m.bmd"}
    heads = {f["path"]: f["head"] for f in L.files}
    assert heads["ARCHIVE/arc0.narc"][:4] == b"NARC" and heads["data/m.bmd"][:4] == b"LZ77"


# ---------------------------------------------------------------- textures

PAL = struct.pack("<4H", 0x0000, 0x001F, 0x03E0, 0x7C00)            # black, red, green, blue (BGR555)


def test_teximage_fields():
    p = (5 << 26) | (2 << 20) | (3 << 23) | (1 << 16) | (1 << 18) | (1 << 29)
    t = nitro.teximage(p)
    assert (t["format"], t["width"], t["height"], t["repeat_s"], t["flip_s"], t["color0_transparent"]) == \
           (5, 32, 64, True, True, True)


def test_palette_formats_and_colour0():
    px = nitro.decode_texture(2, 4, 1, bytes([0b11100100]), PAL, color0_transparent=True)     # 2bpp: 0 1 2 3
    assert px[0, :, :3].tolist() == [[0, 0, 0], [255, 0, 0], [0, 255, 0], [0, 0, 255]]
    assert px[0, :, 3].tolist() == [0, 255, 255, 255]
    px = nitro.decode_texture(3, 2, 1, bytes([0x21]), PAL)                                   # 4bpp, low nibble first
    assert px[0, 0, :3].tolist() == [255, 0, 0] and px[0, 1, :3].tolist() == [0, 255, 0]
    px = nitro.decode_texture(4, 2, 1, bytes([3, 1]), PAL)
    assert px[0, 0, :3].tolist() == [0, 0, 255] and px[0, 0, 3] == 255


def test_alpha_and_direct_formats():
    a3i5 = nitro.decode_texture(1, 2, 1, bytes([(7 << 5) | 1, (0 << 5) | 2]), PAL)
    assert a3i5[0, 0].tolist() == [255, 0, 0, 255] and a3i5[0, 1, 3] == 0
    a5i3 = nitro.decode_texture(6, 1, 1, bytes([(31 << 3) | 3]), PAL)
    assert a5i3[0, 0].tolist() == [0, 0, 255, 255]
    direct = nitro.decode_texture(7, 2, 1, struct.pack("<2H", 0x801F, 0x03E0))
    assert direct[0, 0].tolist() == [255, 0, 0, 255] and direct[0, 1, 3] == 0


def _w(r, g, b):
    """5-bit channels -> a BGR555 word."""
    return r | g << 5 | b << 10


def _x(v):
    """A 5-bit channel widened like the hardware does (bit copy)."""
    return v << 3 | v >> 2


@pytest.mark.parametrize("mode,expect", [
    (0, [[255, 0, 0, 255], [0, 255, 0, 255], [0, 0, 255, 255], [None, None, None, 0]]),
    # interpolated colours blend the 5-bit fields and truncate (GBATEK; melonDS): (31 + 0) / 2 = 15 -> 123
    (1, [[255, 0, 0, 255], [0, 255, 0, 255], [123, 123, 0, 255], [None, None, None, 0]]),
    (2, [[255, 0, 0, 255], [0, 255, 0, 255], [0, 0, 255, 255], [255, 255, 255, 255]]),
    # (5 * 31 + 3 * 0) / 8 = 19 -> 156, (3 * 31) / 8 = 11 -> 90
    (3, [[255, 0, 0, 255], [0, 255, 0, 255], [156, 90, 0, 255], [90, 156, 0, 255]]),
])
def test_4x4_compressed_modes(mode, expect):
    pal = struct.pack("<4H", 0x001F, 0x03E0, 0x7C00, 0x7FFF)
    texels = struct.pack("<I", sum(k << (2 * k) for k in range(4)))  # first row: indices 0 1 2 3, rest 0
    px = nitro.decode_texture(5, 4, 4, texels, pal, palette_index=struct.pack("<H", mode << 14))
    for k, want in enumerate(expect):
        got = px[0, k].tolist()
        assert got[3] == want[3]
        if want[0] is not None:
            assert got[:3] == want[:3], (mode, k, got)


def test_4x4_mode3_known_colours_all_channels():
    c0, c1 = _w(20, 10, 4), _w(4, 26, 30)
    pal = struct.pack("<2H", c0, c1)
    texels = struct.pack("<I", 0b11_10_01_00)                       # row 0: 0 1 2 3
    px = nitro.decode_texture(5, 4, 4, texels, pal, palette_index=struct.pack("<H", 3 << 14))
    mix = lambda a, b: [_x((a[i] * 5 + b[i] * 3) // 8) for i in range(3)]
    a, b = (20, 10, 4), (4, 26, 30)
    assert px[0, 0, :3].tolist() == [_x(v) for v in a]
    assert px[0, 1, :3].tolist() == [_x(v) for v in b]
    assert px[0, 2, :3].tolist() == mix(a, b)
    assert px[0, 3, :3].tolist() == mix(b, a)
    assert px[..., 3].min() == 255                                  # mode 3 has no transparent texel


def test_4x4_texel_order_block_order_and_palette_offset():
    """8x8 = 2x2 blocks. Each block's u32 holds one row per byte, the leftmost texel in the low two bits; blocks run
    row-major; a block's palette offset counts 4-byte steps (two colours), so offset n starts at colour 2n."""
    colours = [_w(31, 0, 0), _w(0, 31, 0), _w(0, 0, 31), _w(31, 31, 0),            # offset 0: c0..c3
               _w(0, 31, 31), _w(31, 0, 31), _w(8, 8, 8), _w(16, 16, 16)]          # offset 2 starts at colour 4
    pal = struct.pack("<8H", *colours)
    # block 0: row y holds index y in every column except x == y (index 3); blocks 1..3 all index 0
    rows = [sum((3 if x == y else y) << (2 * x) for x in range(4)) for y in range(4)]
    blk0 = rows[0] | rows[1] << 8 | rows[2] << 16 | rows[3] << 24
    texels = struct.pack("<4I", blk0, 0, 0, 0)
    pidx = struct.pack("<4H", 2 << 14, 1 << 14 | 1, 2 << 14 | 2, 2 << 14 | 3)
    px = nitro.decode_texture(5, 8, 8, texels, pal, palette_index=pidx)
    for y in range(4):
        for x in range(4):
            want = colours[3 if x == y else y]
            assert px[y, x, :3].tolist() == [_x(want & 31), _x(want >> 5 & 31), _x(want >> 10 & 31)], (x, y)
    assert px[0, 4, :3].tolist() == [0, 0, 255]                     # block 1 (top right), offset 1 -> colour 2
    assert px[4, 0, :3].tolist() == [0, 255, 255]                   # block 2 (bottom left), offset 2 -> colour 4
    assert px[4, 4, :3].tolist() == [_x(8)] * 3                     # block 3, offset 3 -> colour 6


def test_4x4_flat_region_decodes_flat():
    """A flat colour stays one colour whatever the indices say, in every mode where c0 == c1."""
    flat = _w(5, 6, 10)
    pal = struct.pack("<4H", flat, flat, flat, flat)
    rng = np.random.default_rng(1)
    texels = rng.integers(0, 2 ** 32, 16, dtype=np.uint64).astype("<u4").tobytes()
    for mode in (2, 3):
        px = nitro.decode_texture(5, 16, 16, texels, pal, palette_index=struct.pack("<16H", *[mode << 14] * 16))
        assert len(np.unique(px.reshape(-1, 4), axis=0)) == 1, mode


def test_screen_door_score():
    opaque = np.full((8, 8, 4), 255, np.uint8)
    assert nitro.screen_door(opaque) == 0.0
    cut = opaque.copy()
    cut[:, :3, 3] = 0                                               # a solid cut-out margin
    door = opaque.copy()
    door[(np.indices((8, 8)).sum(0) % 2) == 0, 3] = 0               # every other texel dropped
    assert nitro.screen_door(cut) < 0.15 < 0.4 < nitro.screen_door(door)


def test_texture_errors():
    with pytest.raises(ValueError):
        nitro.decode_texture(3, 8, 8, b"\0" * 4, PAL)                # short texels
    with pytest.raises(ValueError):
        nitro.decode_texture(3, 2, 1, b"\0", b"")                    # palette format without a palette


# ---------------------------------------------------------------- GX display lists

def v16(x, y, z):
    f = lambda v: int(round(v * 4096)) & 0xFFFF
    return (0x23, [f(x) | f(y) << 16, f(z)])


def test_gx_triangles_quads_strips_and_slots():
    dl = nitro.gx_pack([
        (0x14, [0]), (0x40, [0]), (0x22, [(16 * 4) | (8 * 16) << 16]), v16(0, 0, 0), v16(1, 0, 0), v16(0, 1, 0),
        (0x41, []),
        (0x14, [3]), (0x40, [1]), v16(0, 0, 1), v16(1, 0, 1), v16(1, 1, 1), v16(0, 1, 1), (0x41, []),
        (0x40, [2]), v16(0, 0, 2), (0x25, [0x1000]), (0x28, [8 | (8 << 10)]), (0x27, [0x1000 | 0x2000 << 16]),
        (0x41, []),
        (0x40, [3]), v16(0, 0, 3), (0x24, [(1 << 6) & 0x3FF]), (0x26, [0x1000 | 0x3000 << 16]), v16(1, 1, 3),
        (0x41, []),
    ])
    g = nitro.decode_display_list(dl)
    assert len(g["tris"]) == 1 + 2 + 2 + 2
    assert g["slot"][:3] == [0, 0, 0] and g["slot"][3:7] == [3, 3, 3, 3]
    assert g["uv"][0] == (4.0, 8.0)
    assert g["pos"][1] == (1.0, 0.0, 0.0)
    strip = g["pos"][7:11]
    assert strip[1] == (1.0, 0.0, 2.0)                              # VTX_XY (x low, y high) keeps z
    assert strip[2] == pytest.approx((1 + 8 / 4096, 8 / 4096, 2.0))  # VTX_DIFF adds raw 4.12 units
    assert strip[3] == pytest.approx((1 + 8 / 4096, 1.0, 2.0))      # VTX_YZ keeps x
    assert g["tris"][3] == (7, 8, 9) and g["tris"][4] == (9, 8, 10)  # strip winding alternates
    assert g["pos"][12] == (1.0, 0.0, 0.0) and g["pos"][13] == (1.0, 0.0, 3.0)   # VTX_10 (4.6), VTX_XZ keeps y
    assert g["commands"]["VTX_16"] == 10


def test_gx_rejects_unknown_and_truncated():
    with pytest.raises(ValueError):
        nitro.gx_commands(struct.pack("<I", 0x99))
    with pytest.raises(ValueError):
        nitro.gx_commands(struct.pack("<I", 0x23))


# ---------------------------------------------------------------- BMD

def build_bmd(*, shift=0) -> bytes:
    """Two bones (root, 'face_1' 2 units up, rotated 90 degrees about Y), one 4x4 pal16 texture, one material, one
    display list with a triangle on each bone's matrix slot."""
    names = b"root\0face_1\0mat\0tex\0pal\0"
    dl = nitro.gx_pack([(0x14, [0]), (0x40, [0]), (0x22, [0]), v16(0, 0, 0), (0x22, [4 * 16]), v16(1, 0, 0),
                        (0x22, [4 * 16 << 16]), v16(0, 1, 0), (0x41, []),
                        (0x14, [1]), (0x40, [0]), v16(0, 0, 0), v16(1, 0, 0), v16(0, 1, 0), (0x41, [])])
    tex = bytes([0x21] * 8)                                                 # 4x4 pal16
    pal = PAL + b"\0" * 24
    hdr = 0x3C
    off = {}
    blob = bytearray(b"\0" * hdr)

    def put(key, data, align=4):
        while len(blob) % align:
            blob.append(0)
        off[key] = len(blob)
        blob.extend(data)
    put("names", names)
    put("pairs_m", bytes([0]))
    put("pairs_d", bytes([0]))
    put("mtx", bytes([0, 1]))
    put("gx", dl)
    put("tex", tex)
    put("pal", pal)
    put("tmap", struct.pack("<2H", 0, 1))
    n = lambda s: off["names"] + names.index(s)
    bones = bytearray()
    bones += struct.pack("<IIhHi3i3hH3i4I", 0, n(b"root\0"), 0, 1, 0, 4096, 4096, 4096, 0, 0, 0, 0, 0, 0, 0,
                         1, off["pairs_m"], off["pairs_d"], 0)
    bones += struct.pack("<IIhHi3i3hH3i4I", 1, n(b"face_1\0"), -1, 0, 0, 4096, 4096, 4096, 0, 1024, 0, 0,
                         0, 2 * 4096, 0, 0, 0, 0, 0)
    put("bones", bytes(bones))
    put("dldesc", struct.pack("<4I", 2, off["mtx"], len(dl), off["gx"]))
    put("dls", struct.pack("<II", 1, off["dldesc"]))
    put("texs", struct.pack("<IIIHHI", n(b"tex\0"), off["tex"], len(tex), 4, 4, (3 << 26) | (1 << 29)))
    put("pals", struct.pack("<IIII", n(b"pal\0"), off["pal"], len(pal), 0xFFFFFFFF))
    put("mats", struct.pack("<IIIiiHHiiIIII", n(b"mat\0"), 0, 0, 4096, 4096, 0, 0, 0, 0, 0x30000, 0x1F0081, 0, 0))
    struct.pack_into("<15I", blob, 0, shift, 2, off["bones"], 1, off["dls"], 1, off["texs"], 1, off["pals"], 1,
                     off["mats"], off["tmap"], 0, 0, 0)
    return bytes(blob)


def test_parse_bmd_fields():
    b = S.parse_bmd(build_bmd(shift=1))
    assert b["scale"] == 2 and [x["name"] for x in b["bones"]] == ["root", "face_1"]
    assert b["bones"][1]["parent"] == 0 and b["bones"][1]["rotation"][1] == pytest.approx(np.pi / 2)
    assert b["bones"][0]["pairs"] == [(0, 0)] and b["display_lists"][0]["transforms"] == [0, 1]
    assert b["transform_bone"] == [0, 1] and b["textures"][0]["width"] == 4
    assert b["materials"][0]["texture"] == 0 and b["materials"][0]["scale"] == (1.0, 1.0)
    with pytest.raises(ValueError):
        S.parse_bmd(b"\0" * 8)


def test_bmd_vertices_follow_their_bone_and_scale_shift():
    m = S.Model()
    m.add_bmd(S.parse_bmd(build_bmd(shift=1)))
    p = m.prims[0]
    assert p["bone"].tolist() == [0, 0, 0, 1, 1, 1]
    assert p["pos"][1] == pytest.approx([2, 0, 0])                 # bone 0: identity, shift scales the vertex
    assert p["pos"][3] == pytest.approx([0, 2, 0])                 # bone 1 sits 2 up; translations are not scaled
    assert p["pos"][4] == pytest.approx([0, 2, -2])                # ... and turns +X into -Z (Ry 90 degrees)
    assert p["uv"][1] == pytest.approx([1, 0]) and p["uv"][2] == pytest.approx([0, 1])
    assert m.materials["mat"]["png"][:4] == b"\x89PNG"


def test_bmd_to_glb_is_rigged_and_textured(tmp_path):
    m = S.Model()
    m.add_bmd(S.parse_bmd(build_bmd()))
    man = S.to_manifest(m, "t", {"files": []}, tmp_path)
    (tmp_path / "t.glb").write_bytes(uap.to_glb(man, tmp_path))
    st = C.model_stats(tmp_path / "t.glb")
    assert st["triangles"] == 2 and st["textures"] == 1
    assert st["rig"]["skinned"] and st["rig"]["joint_names"] == ["root", "face_1"]
    assert not uap.validate(man, tmp_path)


def _two_texture_bmd(names=("head_1", "head_2")) -> dict:
    """A parsed-BMD stand-in: two 8x8 direct-colour textures, the second a screen-door stipple (Luigi's vanish head),
    and a material that names the stipple."""
    solid = struct.pack("<64H", *[0x8000 | _w(20, 12, 6)] * 64)
    door = struct.pack("<64H", *[(0x8000 if (i // 8 + i % 8) % 2 else 0) | _w(20, 12, 6) for i in range(64)])
    raw = solid + door
    param = 7 << 26
    return {"raw": raw, "palettes": [],
            "textures": [{"name": names[0], "data": 0, "size": 128, "width": 8, "height": 8, "param": param},
                         {"name": names[1], "data": 128, "size": 128, "width": 8, "height": 8, "param": param}],
            "materials": [{"name": "mat_head", "texture": 1, "palette": None}]}


def test_screen_door_material_takes_its_opaque_sibling():
    bmd = _two_texture_bmd()
    tex, _pal, note = S.pick_texture(bmd, bmd["materials"][0])
    assert tex == 0 and note["texture_substituted"]["drawn"] == "head_1"
    tex, _pal, note = S.pick_texture(bmd, bmd["materials"][0], "head_1")          # named outright (CHARACTERS)
    assert tex == 0 and note["texture_substituted"]["reason"].startswith("state variant")
    with pytest.raises(ValueError):
        S.pick_texture(bmd, bmd["materials"][0], "nope")
    lone = _two_texture_bmd(("solid", "door"))                                      # no sibling: kept, flagged
    tex, _pal, note = S.pick_texture(lone, lone["materials"][0])
    assert tex == 1 and note["screen_door"] > S.SCREEN_DOOR
    assert S.CHARACTERS["luigi"]["textures"] == {"head:mat_head": "luigi_head_1"}


def test_head_attach_chest_insert_and_facing(monkeypatch):
    body = build_bmd()

    class FakeRom:
        def read(self, path):
            return body

        def where(self, path):
            return path
    monkeypatch.setitem(S.CHARACTERS, "synthetic", {
        "name": "Synthetic", "aliases": [], "body": "body.bmd", "head": "head.bmd", "chest": ["face_1"],
        "roles": {"hip": "root", "chest": "chest", "head": "head:root"}})
    model, roles, files = S.build(FakeRom(), "synthetic")
    assert roles == {"hip": "root", "chest": "chest", "head": "head:root"}
    assert files == ["body.bmd", "head.bmd"]
    hr = model.names.index("head:root")
    assert model.parent[hr] == model.names.index("face_1")
    assert model.parent[model.names.index("face_1")] == model.names.index("chest")
    order = model.order()
    assert all(order.index(model.parent[i]) < order.index(i) for i in order if model.parent[i] >= 0)


def test_face_z_turns_left_to_plus_x():
    m = S.Model()
    m.names, m.parent = ["l", "r"], [-1, -1]
    a, b = np.eye(4), np.eye(4)
    a[:3, 3], b[:3, 3] = [0, 0, -1], [0, 0, 1]                      # left on -Z: a model facing -X
    m.world = [a, b]
    m.prims = [{"pos": np.array([[0.0, 0, -1]])}]
    m.face_z(0, 1)
    assert m.world[0][:3, 3] == pytest.approx([1, 0, 0]) and m.prims[0]["pos"][0] == pytest.approx([1, 0, 0])


def test_roster_and_dedicated_registration():
    rows = S.roster()
    slugs = [r["slug"] for r in rows]
    assert len(slugs) == len(set(slugs)) and all(s.startswith("sm64ds_") for s in slugs)
    assert {"sm64ds_mario", "sm64ds_luigi", "sm64ds_wario", "sm64ds_yoshi", "sm64ds_peach", "sm64ds_toad",
            "sm64ds_bowser"} <= set(slugs)
    humanoid = {k for k, c in S.CHARACTERS.items() if {"hip", "chest", "head", "l_hand", "r_foot"} <= set(c["roles"])}
    assert {"mario", "luigi", "wario", "yoshi", "peach", "bowser"} <= humanoid
    for k, c in S.CHARACTERS.items():
        partial = set(S.SM64_ROLES) - set(c["roles"])
        assert not partial or c.get("absent"), f"{k}: partial rig without a reason"
    pick = lambda t, p: next((n for n, test, _r, _run in C.DEDICATED if test(t, p)), None)
    assert pick("super mario 64 ds (usa)", "nds") == "sm64ds"
    assert pick("super mario 64 (usa)", "n64") == "sm64"
    assert C.reader_version("sm64ds") == S.READER_VERSION


# ---------------------------------------------------------------- the owned ROM

def _owned() -> Path | None:
    cands = [os.environ.get("GBOX_SM64DS_ROM"), f"D:/gBox/cache/{GID}/rom/0037 - Super Mario 64 DS (U)(Trashman).nds",
             f"D:/gBox/cache/{GID}/Super Mario 64 DS (USA).7z",
             "/mnt/gbox/hyperspin/Arcade/collections/Nintendo DS/roms/Super Mario 64 DS (USA).7z"]
    for c in cands:
        try:
            if c and Path(c).is_file():
                return Path(c)
        except OSError:
            continue
    return None


@pytest.mark.skipif(_owned() is None, reason="owned Super Mario 64 DS ROM not on this node")
def test_owned_rom_cast(tmp_path):
    rom = S.SM64DSRom(S.load_rom(_owned()))
    assert rom.sha256 == S.ROM_SHA256
    for key in ("mario", "yoshi", "peach", "bowser", "toad", "luigi"):
        glb = S.export(None, tmp_path / key, key, rom=rom)
        st = C.model_stats(glb)
        assert st["triangles"] > 200 and st["rig"]["skinned"] and st["textures"] >= 1, key
        roles = S.CHARACTERS[key]["roles"]
        names = st["rig"]["joint_names"]
        assert all(n in names for n in roles.values()), key
    mario = S.build(rom, "mario")[0]
    w = {n: mario.world[i][:3, 3] for i, n in enumerate(mario.names)}
    assert w["arm_l1"][0] > 0 > w["arm_r1"][0] and w["face_1"][1] > w["spin"][1] > w["skl_root"][1] > w["ankle_l1"][1]


@pytest.mark.skipif(_owned() is None, reason="owned Super Mario 64 DS ROM not on this node")
def test_owned_rom_no_character_draws_a_screen_door_texture():
    """Luigi's head material names his vanish texture (luigi_head_2, 66 % of its texels transparent in a stipple); the
    reader draws luigi_head_1. No collected material may be a stipple."""
    rom = S.SM64DSRom(S.load_rom(_owned()))
    luigi = S.build(rom, "luigi")[0]
    head = luigi.materials["head:mat_head"]
    assert head["texture"] == "luigi_head_1" and head["source"]["texture_substituted"]["bmd_names"] == "luigi_head_2"
    for key in S.CHARACTERS:
        model = S.build(rom, key)[0]
        for name, mat in model.materials.items():
            assert "screen_door" not in mat["source"], (key, name)
