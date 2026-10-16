import struct
from pathlib import Path

import pytest

from gbox import time_stalkers as ts

GDI = Path.home() / "gbox-cache" / "dc" / ts.GAME_ID / "disc.gdi"


def _node(pos, scl=(1.0, 1.0, 1.0), link=0, offs=(0, 0)):
    return struct.pack("<2I3f3i3fI", *offs, *pos, 0, 16384, 0, *scl, link)


def _man(variant="plain", nodes=2):
    head = (b"" if variant == "plain" else b"\xff" * 4) + ts.SIG + (b"" if variant == "plain" else b"\xff" * 4)
    body = struct.pack("<I", nodes) + b"".join(_node((0.0, -4.2 * i, 1.0), link=i) for i in range(nodes))
    motion_at = 4 + len(head) + len(body)
    motions = b"M1" * 8 + b"M2" * 8
    table = [0] * ts.SLOTS
    table[0], table[70] = motion_at, motion_at + 16
    table_off = motion_at + len(motions)
    return struct.pack("<I", table_off) + head + body + motions + struct.pack(f"<{ts.SLOTS}I", *table)


def test_parse_man_plain_reads_nodes_and_slots():
    h = ts.parse_man(_man())
    assert h["variant"] == "plain" and h["node_field"] == 2
    assert [n["pos"][1] for n in h["nodes"]] == [0.0, pytest.approx(-4.2)]
    assert h["nodes"][1]["ang"] == [0, 16384, 0] and h["nodes"][1]["link"] == 1
    assert sorted(h["slots"]) == [0, 70] and h["bad_slots"] == []
    assert h["table"] == h["size"] - 512


def test_parse_man_ff_variant_and_rejects_bad_table():
    h = ts.parse_man(_man("ff", nodes=3))
    assert h["variant"] == "ff" and len(h["nodes"]) == 3
    bad = bytearray(_man())
    struct.pack_into("<I", bad, 0, 8)
    with pytest.raises(ValueError, match="size-512"):
        ts.parse_man(bytes(bad))


def test_parse_man_keeps_unproven_node_field_raw():
    d = bytearray(_man())
    struct.pack_into("<I", d, 16, 0x209)          # a packed value, not a node count that fits before the motions
    h = ts.parse_man(bytes(d))
    assert h["node_field"] == 0x209 and h["nodes"] is None


def _obj(names):
    blob = b""
    for n in names:
        s = n.encode() + b"\0"
        blob += s + b"\xff" * (-len(s) % 4)
    data = b"\x14\0\0\0" * 6
    trailer = 20 + len(blob) + len(data)
    tail = struct.pack("<I2f4I", 0x118, 18.0, 6.0, 0x1c8, 1, 2, 0)
    return struct.pack("<2I", trailer, 0) + ts.SIG + blob + data + tail


def test_parse_obj_reads_texture_names_and_trailer():
    h = ts.parse_obj(_obj(["s_fuku_f", "s_sodeL", "swd_boots"]))
    assert h["textures"] == ["s_fuku_f", "s_sodeL", "swd_boots"]
    assert h["trailer_floats"] == [18.0, 6.0] and h["trailer_words"][0] == 0x118
    with pytest.raises(ValueError):
        ts.parse_obj(b"\0" * 64)


def _pvm(names, flags=0x109):
    ent = b"".join(struct.pack("<H", i) + n.encode().ljust(28, b"\0") + struct.pack("<I", 1000 + i)
                   for i, n in enumerate(names))
    return b"PVMH" + struct.pack("<I2H", 4 + len(ent), flags, len(names)) + ent


def test_pvm_names_and_label():
    assert ts.pvm_names(_pvm(["s_fuku_f", "swd1", "swd_boots"])) == ["s_fuku_f", "swd1", "swd_boots"]
    assert ts._label(["s_fuku_f", "swd_boots", "swd_earL"]) == "swd"
    with pytest.raises(ValueError):
        ts.pvm_names(b"GBIX" + b"\0" * 12)


def test_classify_roles():
    assert ts.classify("LANDERS/MANDATA/MAN00000.BIN") == "character_skeleton_motion"
    assert ts.classify("LANDERS/MANDATA/OBJ000.BIN") == "object_mesh"
    assert ts.classify("LANDERS/MANDATA/OBJ000.PVM") == "object_textures"
    assert ts.classify("LANDERS/MANDATA/OBJ086.TEX") == "object_texture"
    assert ts.classify("LANDERS/SAYMANDATA/LADY_01.PVR") == "portrait"
    assert ts.classify("1ST_READ.BIN") == "executable"
    assert ts.classify("LANDERS/EFCTCAMERA/X.NJM") == "effect_camera_motion"


def test_ip_meta_requires_katana_header():
    ip = bytearray(b" " * 256)
    ip[:16] = b"SEGA SEGAKATANA "
    ip[0x40:0x48] = b"MK-51011"
    ip[0x60:0x6c] = b"1ST_READ.BIN"
    assert ts.ip_meta(bytes(ip))["product"] == "MK-51011"
    with pytest.raises(ValueError):
        ts.ip_meta(b"\0" * 256)


@pytest.mark.skipif(not GDI.exists(), reason="owned Time Stalkers GD-ROM not unpacked on this node")
def test_owned_disc_inventory():
    inv = ts.inventory(GDI, ts.SOURCE_CHD_SHA256)
    s = inv["summary"]
    assert inv["ip_bin"]["product"] == "MK-51011" and inv["ip_bin"]["boot"] == "1ST_READ.BIN"
    assert inv["executables"]["1ST_READ.BIN"]["sha256"].startswith("a9fa66b6bcc482df")
    assert inv["executables"]["MAIN.BIN"]["sha256"].startswith("62d4c0fd6ba77427")
    assert "%s\\man%03d%02d.BIN" in inv["loader_formats"] and "%s\\obj%03d.pvm" in inv["loader_formats"]
    assert (s["man_files"], s["character_ids"], s["object_meshes"], s["object_pvms"], s["object_tex"]) == (484, 193, 191, 175, 14)
    assert s["errors"] == []
    assert inv["characters"]["000"]["00"]["nodes"] == 18
    assert inv["objects"]["000"]["label"] == "swd" and inv["objects"]["000"]["pvm_matches_mesh"] is True
    sword = inv["objects"]["000"]["bin"]
    assert sword["parts"] == 24 and sword["models"] >= 20 and sword["texlist"]["count"] == 19
    assert 0x29 in sword["vertex_types"] and sword["verts"] > 0


def test_parse_obj_reads_texlist_and_chunk_parts():
    head = struct.pack("<2I", 128, 0) + ts.SIG + b"a_tex\0\xff\xff"            # names_end = 28
    texnames = struct.pack("<3I", 20, 0, 0)                                    # NJS_TEXNAME at 28
    texlist = struct.pack("<2I", 28, 1)                                        # NJS_TEXLIST at 40
    vlist = struct.pack("<BBHHH", 0x29, 0, 7, 0, 1) + struct.pack("<6f", 0, 1, 0, 0, 1, 0) + b"\xff\0\0\0"  # at 48
    plist = b"\xff\0\0\0"                                                      # at 84
    model = struct.pack("<2I4f", 48, 84, 0.0, 1.0, 0.0, 2.0)                   # NJS_CNK_MODEL at 88
    arrays = struct.pack("<4I", 0, 88, 0, 0)                                   # full parts at 112, twins at 120
    tail = struct.pack("<I2f4I", 0x118, 18.0, 6.0, 40, 112, 120, 0)            # trailer at 128
    data = head + texnames + texlist + vlist + plist + model + arrays + tail
    assert len(head + texnames + texlist + vlist + plist + model + arrays) == 128
    h = ts.parse_obj(data)
    assert h["textures"] == ["a_tex"] and h["texlist"] == {"textures": 28, "count": 1}
    assert len(h["parts"]) == 2 and h["parts"][0] == {"model": None, "twin": None}
    m = h["parts"][1]["model"]
    assert (m["vtype"], m["verts"], m["radius"], m["vlist"], m["plist"]) == (0x29, 1, 2.0, 48, 84)
    assert h["parts"][1]["twin"] is None
    assert ts.cnk_model(data, 20) is None                                      # texture-name bytes are no model


def _obj_with_tris():
    """A tiny OBJ: one part whose vlist has 3 vertices and whose plist draws them as one 0x40 strip."""
    head = struct.pack("<2I", 196, 0) + ts.SIG + b"tex\0\xff\xff\xff\xff"          # names_end = 28
    texnames = struct.pack("<3I", 20, 0, 0)
    texlist = struct.pack("<2I", 28, 1)
    vlist = struct.pack("<BBHHH", 0x29, 0, 19, 0, 3) + b"".join(struct.pack("<6f", 0, 0, 0, 0, 1, 0)
                                                                  for _ in range(3)) + b"\xff\0\0\0"   # at 48, 84 bytes
    plist = struct.pack("<HH", 8 | (0x34 << 8), 0) + struct.pack("<HH", 0x40 | (0x12 << 8), 5) \
        + struct.pack("<Hh3H", 1, 3, 0, 1, 2) + struct.pack("<2H", 0xFF, 0) + b"\0\0"           # at 132, pads to 156
    model = struct.pack("<2I4f", 48, 132, 0.0, 0.0, 0.0, 1.0)                    # at 156
    arrays = struct.pack("<4I", 0, 156, 0, 0)                                   # at 180, 188
    tail = struct.pack("<I2f4I", 0x118, 18.0, 6.0, 40, 180, 188, 0)              # trailer at 196
    data = head + texnames + texlist + vlist + plist + model + arrays + tail
    assert len(data) == 196 + 28 and data[196:196 + 28] == tail                   # trailer offset is exact
    return data


def test_obj_nj_decodes_strip_geometry():
    nj, h, stats = ts.decode_obj_geometry(_obj_with_tris())
    assert len(h["parts"]) == 2 and h["textures"] == ["tex"]
    assert stats[0]["tris"] == 0 and stats[1] == {"verts": 3, "vtype": 0x29, "tris": 1, "tex_ids": [0]}
    assert nj.tris[0][0][0][2]["pos"] == [0.0, 0.0, 0.0]
    out = ts.obj_wavefront(nj, h["textures"])
    assert "o tex0_tex" in out and "f 1//1 2//2 3//3" in out and "vn 0.00000 1.00000 0.00000" in out


def test_man_link_chains_follow_link_low_bytes():
    nodes = [{"link": 1}, {"link": 2}, {"link": 0}, {"link": 0xFF}]           # 0->1->2 cycle + a terminator
    assert ts.man_link_chains(nodes) == [[0, 1, 2, "cycle"], [3, 255]]


@pytest.mark.skipif(not GDI.exists(), reason="owned Time Stalkers GD-ROM not unpacked on this node")
def test_owned_disc_obj000_geometry_decode():
    from gbox.gdrom import GDRom

    g = GDRom(GDI)
    data = g.read("LANDERS/MANDATA/OBJ000.BIN")
    nj, h, stats = ts.decode_obj_geometry(data)
    assert len(h["parts"]) == 24 and len(stats) == 24
    assert sum(s["tris"] for s in stats) == 3233 and len(nj.tris) == 19        # 19 texture groups = texlist count
    assert stats[2]["verts"] == 322 and stats[1]["tris"] == 66
    assert len(nj.vbuf) > 300
    # the B array holds vertex-only (0x22) twins of the parts: usually decimated, but not strictly hulls
    assert all(p["twin"] is None or p["twin"]["vtype"] == 0x22 for p in h["parts"])
    assert all(p["model"] is None or p["model"]["vtype"] == 0x29 for p in h["parts"])
    out = ts.obj_wavefront(nj, h["textures"])
    assert "o tex0_s_fuku_f" in out and "o tex1_s_fuku_r" in out and out.count("\nf ") == 3233
    assert "vn " in out and "vt " in out                                     # normals and UV strips decoded


def test_main_bin_strings_finds_loader_formats():
    blob = (b"pad\x00" + b"%s\\man%03d%02d.BIN" + b"\x00tail"
            b"%s\\obj%03d.BIN" + b"\x00\x00" + b"obj%03d.tex" + b"\x00\x00\x00"
            b"%s\\obj%03d.pvm" + b"\x00\x00" + b"\\landers\\ManData" + b"\x00")
    got = ts.main_bin_strings(blob)
    assert got["man_bin"] == blob.index(b"%s\\man%03d%02d.BIN")
    assert got["obj_bin"] == blob.index(b"%s\\obj%03d.BIN")
    assert got["obj_pvm"] == blob.index(b"%s\\obj%03d.pvm")
    assert got["obj_tex"] == blob.index(b"obj%03d.tex")
    assert got["man_root"] == blob.index(b"\\landers\\ManData")


def test_sh4_movl_xrefs_resolves_literal_pool():
    # mov.l @(0,pc),r1 (0xD1 0x00) at file offset 0 reads the literal at ((0+4)&~3) = 4
    data = struct.pack("<H", 0xD100) + b"\x00\x00" + struct.pack("<I", 0x8C011000) + b"\x00" * 8
    assert ts.sh4_movl_xrefs(data, 4) == [0]
    assert ts.sh4_movl_xrefs(data, 8) == []  # nothing targets offset 8


def test_sh4_absolute_refs_modal_bucket_is_link_base():
    data = struct.pack("<4I", 0x8C010200, 0x8C01FF00, 0x8C020000, 0x8C010000)
    refs = ts.sh4_absolute_refs(data)
    assert refs["8c010000"] == 3 and refs["8c020000"] == 1


@pytest.mark.skipif(not GDI.exists(), reason="owned Time Stalkers GD-ROM not unpacked on this node")
def test_owned_disc_main_bin_loaders():
    d = Path.home() / "gbox-cache" / "time_stalkers" / "MAIN.BIN"
    if not d.exists():
        pytest.skip("MAIN.BIN not copied locally")
    data = d.read_bytes()
    s = ts.main_bin_strings(data)
    assert s["man_bin"] == 0x17CED0 and s["obj_bin"] == 0x17CEA4
    assert s["obj_pvm"] == 0x17CEC0 and s["obj_tex"] == 0x17CEB4
    assert s["man_root"] in (0x17CDB9, 0x17CDCA)
    refs = ts.sh4_absolute_refs(data)
    assert max(refs, key=refs.get) == "8c010000" and refs["8c010000"] > 1000


@pytest.mark.skipif(not GDI.exists(), reason="owned Time Stalkers GD-ROM not unpacked on this node")
def test_owned_disc_man00000_link_chains():
    from gbox.gdrom import GDRom

    g = GDRom(GDI)
    d = g.read("LANDERS/MANDATA/MAN00000.BIN")
    nodes = ts.parse_man(d)["nodes"]
    chains = ts.man_link_chains(nodes)
    assert [0, 12, 13, 9, 16, 3, 6, 19] in chains                            # chain ends at 19 (>= 18 nodes)
    assert any(c[-1] == "cycle" and set(c[:-1]) == {4, 5} for c in chains)   # the shin/hip pair is a 2-cycle
    # the same skeleton in a different motion bank keeps the node count but rewires the chains
    d1 = g.read("LANDERS/MANDATA/MAN00001.BIN")
    nodes1 = ts.parse_man(d1)["nodes"]
    assert len(nodes1) == 18 and ts.man_link_chains(nodes1) != chains
