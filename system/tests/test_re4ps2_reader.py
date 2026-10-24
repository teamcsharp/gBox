"""RE4 PS2 (#1321) reader tests: PS2 GS swizzle, CLUT, BIN mesh parse, TPL decode, GLB export."""
import json
import os
import struct
from pathlib import Path

import pytest

from gbox import re4ps2_reader as r

RE = Path(os.environ.get("GBOX_RE4PS2_RE", str(Path.home() / "gBox_alt/gbox-cache/109d8ee7747a7dd8/re")))
ISO = Path(os.environ.get("GBOX_RE4PS2_ISO",
                          str(Path.home() / "gBox_alt/gbox-cache/modbase/109d8ee7747a7dd8/Resident Evil 4 (USA).iso")))


def test_unswizzle_8_roundtrip():
    # a 16x8 texture whose swizzled layout we know: block 0 col 0 is pixels (0..63)
    w, h = 16, 8
    linear = bytes(range(w * h))
    swz = bytearray(w * h)
    for y in range(h):
        for x in range(w):
            bx, px = divmod(x, 8)
            by, py = divmod(y, 8)
            col, in_col = divmod(bx, 4)
            block = (col * (h >> 3) + by) * 4 + in_col
            swz[block * 64 + py * 8 + px] = linear[y * w + x]
    assert bytes(r._unswizzle(bytes(swz), w, h, 8)) == linear


def test_clut_deswizzle():
    # 16 colours in CLUT4 storage: 8 real + 8 pad, then 8 real + 8 pad
    pal = bytearray(128)
    for i in range(16):
        struct.pack_into("<I", pal, (i % 8 + (i // 8) * 16) * 4, 0x80000000 | (i << 16) | (i << 8) | i)
    clut = r._clut(bytes(pal), 16)
    assert [c[0] for c in clut] == list(range(16))
    assert all(c[3] == 0x80 for c in clut)


def test_bin_mesh_partition_and_glb():
    b = bytearray(b"\xcd" * 0x300)
    struct.pack_into("<HHI", b, 0, 0x30, 8, 0x50)   # header, bone table at 0x50
    b[9] = 2                                          # 2 bones
    struct.pack_into("<HI", b, 0xA, 1, 0x100)         # 1 object, table at 0x100
    struct.pack_into("<4I", b, 0x1C, 0x70, 0, 0, 0x30)
    struct.pack_into("<3f4x3f", b, 0x30, 0, 0, 0, 1, 1, 1)
    struct.pack_into("<BB2x3f", b, 0x50, 0, 0xFF, 0, 0, 0)
    struct.pack_into("<BB2x3f", b, 0x60, 1, 0, 0, 16, 0)   # bone1 +16y
    struct.pack_into("<12xI", b, 0x100, 0x140)             # object -> packet 0x140
    # packet: 16-byte bone list, then weight table (V4-32 n=4 -> 2 skin), param (n=1), verts (V4-16 n=3)
    b[0x140:0x150] = bytes(range(16))
    o = 0x150
    struct.pack_into("<4I", b, o, 0x10000004, 0, 0x01000404, 0x6C048000)   # UNPACK V4-32 n=4
    struct.pack_into("<4I", b, o + 16, 0, 0, 1, 0)                        # skin0 bones
    struct.pack_into("<4f", b, o + 32, 1.0, 0.0, 0.0, 0.0)                # skin0 w
    struct.pack_into("<4I", b, o + 48, 8, 0, 0, 0)                        # skin1 bones
    struct.pack_into("<4f", b, o + 64, 0.5, 0.5, 0.0, 0.0)                # skin1 w
    o += 16 + 4 * 16
    struct.pack_into("<4I", b, o, 0x10000001, 0, 0x01000404, 0x6C018020)  # param V4-32 n=1
    o += 16
    b[o] = 1                                                                 # triangle count 1
    struct.pack_into("<f", b, o + 12, 1.0 / 16.0)
    o += 16
    struct.pack_into("<4I", b, o, 0x60000003, 0, 0x01000404, 0x6D038021)  # REF V4-16 n=3
    struct.pack_into("<12h", b, o + 16, 0, 0, 0, 0, 16, 0, 0, 0, 0, 16, 0, 0)  # a triangle
    m = r.bin_mesh(bytes(b))
    assert len(m["bones"]) == 2 and m["bones"][0]["parent"] == 0xFF
    obj = m["objects"][0]
    assert len(obj["parts"]) == 1 and obj["parts"][0]["param"]["triangle_count"] == 1
    assert [e["bones"][0] for e in obj["parts"][0]["skin"]] == [0, 8]   # weight table survives param qword
    assert obj["parts"][0]["skin"][1]["weights"][:2] == [0.5, 0.5]
    assert obj["parts"][0]["vertices"] == [(0, 0, 0, 0), (16, 0, 0, 0), (0, 16, 0, 0)]
    glb = r.to_glb(bytes(b))
    assert glb[:4] == b"glTF"
    g = json.loads(glb[12 + 8:12 + 8 + struct.unpack_from("<I", glb, 12)[0]])
    assert len(g["nodes"]) == 3 and g["nodes"][1]["translation"] == [0.0, 16.0, 0.0]
    mesh_node = next(i for i, n in enumerate(g["nodes"]) if "mesh" in n)
    assert mesh_node in g["scenes"][0]["nodes"]           # mesh is actually in the scene
    assert g["meshes"][0]["primitives"][0]["attributes"]["POSITION"] == 0


def test_rgb565_linear():
    w = h = 8
    img = struct.pack("<64H", *([0xF800] * 64))          # pure red, linear
    t = r._decode_texture(img, {"w": w, "h": h, "format": 4, "image_offset": 0, "palette_offset": 0})
    assert t["rgba"][:4] == bytes((0xF8, 0, 0, 255)) and t["rgba"][-4:] == bytes((0xF8, 0, 0, 255))


@pytest.mark.skipif(not (RE / "pl00.dat").exists(), reason="owned RE4 PS2 pl00.dat not staged")
def test_owned_leon_reader():
    from gbox import re4ps2_model as m
    pack = (RE / "pl00.dat").read_bytes()
    bin_bytes = m.slot_bytes(pack, 0)
    tpl_bytes = m.slot_bytes(pack, 1)
    mesh = r.bin_mesh(bin_bytes)
    assert len(mesh["bones"]) == 119
    assert len(mesh["objects"]) == 7
    objs = mesh["objects"]
    assert [o["packet"] for o in objs] == [0x870, 0x3070, 0xB090, 0x11030, 0x117A0, 0x13600, 0x156A0]
    assert len(objs[0]["parts"]) == 7                       # the body has 7 mesh parts
    total = sum(len(o["parts"]) for o in objs)
    assert total == 64
    for o in objs:
        for p in o["parts"]:
            assert p["param"]["triangle_count"] * 3 == len(p["vertices"])
            assert abs(p["param"]["scale"] - 1.0 / 16.0) < 1e-7
    tex = r.decode_tpl(tpl_bytes)
    assert len(tex) == 8 and {t["format_name"] for t in tex} == {"C4"}
    assert tex[0]["w"] == 256 and tex[0]["h"] == 128 and len(tex[0]["rgba"]) == 256 * 128 * 4
    glb = r.to_glb(bin_bytes, tpl_bytes)
    assert glb[:4] == b"glTF"
    g = json.loads(glb[12 + 8:12 + 8 + struct.unpack_from("<I", glb, 12)[0]])
    assert len(g["nodes"]) == 120 and any("mesh" in n for n in g["nodes"])
    npos = g["meshes"][0]["primitives"][0]["attributes"]["POSITION"]
    assert g["accessors"][npos]["count"] > 500   # 864 vertices across the 7 parts
    json.dumps(g)


@pytest.mark.skipif(not ISO.exists(), reason="owned RE4 PS2 disc image not cached")
def test_dedicated_roster_and_extract(tmp_path):
    import hashlib
    from gbox import re4ps2_inventory as inv
    pack = inv.read_char_dat(str(ISO), "pl00")
    assert len(pack) == 1_102_208 and hashlib.sha256(pack).hexdigest().startswith("9abfd8b0")
    ros = r.roster()
    assert len(ros) == 107 and ros[0]["name"] == "Leon (default costume)" and ros[0]["slug"] == "re4ps2_pl00"

    class _Ctx:
        class _Cfg:
            cache = str(Path.home() / "gBox_alt/gbox-cache")
        config = _Cfg()

        def progress(self, *_a, **_k):
            pass

    res = r.extract_run(_Ctx(), {"game_id": "109d8ee7747a7dd8", "source_paths": [str(ISO)]}, ros[0], tmp_path)
    assert (tmp_path / "model.glb").is_file() and (tmp_path / "tex0.png").is_file()
    assert res["tool"] == "gbox.re4ps2_reader" and res["source_files"] == ["pl00.dat"]
    # the DEDICATED table routes this title+platform to the new reader
    from gbox import characters as CH
    assert next(n for n, test, _ro, _run in CH.DEDICATED if test("resident evil 4", "ps2")) == "re4_ps2"
