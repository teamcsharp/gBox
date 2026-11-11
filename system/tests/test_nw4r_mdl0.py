import os
import struct
import pytest
import gbox.formats.nw4r_mdl0 as nw
from gbox.formats.nw4r_mdl0 import Mdl0Error, parse_mdl0


def _group(items):
    """items: [(name, data_off_rel_group)] -> bytes; names stored after table."""
    n = len(items)
    hdr = 8 + 16 * (n + 1)
    strs = b""
    ents = [struct.pack(">HHHHII", 0xFFFF, 0, 0, 0, 0, 0)]
    for name, doff in items:
        raw = name.encode()
        pad = (-len(raw) - 1) % 4
        no = hdr + len(strs) + 4
        strs += struct.pack(">I", len(raw)) + raw + b"\0" * (1 + pad)
        ents.append(struct.pack(">HHHHII", 0, 0, 0, 0, no, doff))
    return struct.pack(">II", hdr + len(strs), n) + b"".join(ents) + strs


def make_mdl0():
    hdr_len = 0x10 + 14 * 4 + 4 + 0x40
    bone_g, vert_g = 0x100, 0x200
    bone_data, vert_data, vals = 0x300, 0x4C0, 0x540
    b = bytearray(0x600)
    b[:4] = b"MDL0"
    struct.pack_into(">II", b, 4, len(b), 11)
    offs = [0] * 14
    offs[1], offs[2] = bone_g, vert_g
    struct.pack_into(">14i", b, 0x10, *offs)
    name = b"\0\0\0\x03abc\0"
    b[0x5F0:0x5F0 + 8] = name
    struct.pack_into(">i", b, 0x48, 0x5F4)
    struct.pack_into(">IiIIIIII", b, 0x4C, 0x40, -0x4C, 1, 1, 3, 1, 0, 2)
    struct.pack_into(">6f", b, 0x4C + 0x28, -1, -2, -3, 1, 2, 3)
    g = _group([("root", bone_data - bone_g), ("arm", bone_data + 0xD0 - bone_g)])
    b[bone_g:bone_g + len(g)] = g
    for i, (nm, par, tr) in enumerate([("root", 0, (0, 0, 0)), ("arm", -0xD0, (1, 2, 3))]):
        o = bone_data + 0xD0 * i
        struct.pack_into(">8I", b, o, 0xD0, 0, 0, i, i, 0, 0, 0)
        struct.pack_into(">3f3f3f", b, o + 0x20, 1, 1, 1, 0, 0, 0, *tr)
        struct.pack_into(">5i", b, o + 0x5C, par, 0, 0, 0, 0)
    g = _group([("pos0", vert_data - vert_g)])
    b[vert_g:vert_g + len(g)] = g
    struct.pack_into(">7I", b, vert_data, 0x40, 0, vals - vert_data, 0, 0, 1, 4)
    struct.pack_into(">BBH", b, vert_data + 0x1C, 0, 12, 3)
    struct.pack_into(">9f", b, vals, 0, 0, 0, 1, 0, 0, 0, 1, 0)
    return bytes(b)


def test_synthetic_mdl0():
    m = parse_mdl0(make_mdl0())
    assert m["name"] == "abc" and m["version"] == 11
    assert (m["num_vertices"], m["num_faces"], m["num_bones"]) == (3, 1, 2)
    assert m["min"] == (-1, -2, -3) and m["max"] == (1, 2, 3)
    assert [x["name"] for x in m["bones"]] == ["root", "arm"]
    assert m["bones"][1]["parent"] == "root" and m["bones"][1]["trans"] == (1, 2, 3)
    v = m["verts"][0]
    assert v["count"] == 3 and v["values"][1] == (1.0, 0.0, 0.0)


def test_rejects_bad():
    with pytest.raises(Mdl0Error):
        parse_mdl0(b"XXXX" + bytes(64))
    d = bytearray(make_mdl0())
    d[8:12] = struct.pack(">I", 99)
    with pytest.raises(Mdl0Error):
        parse_mdl0(bytes(d))


@pytest.mark.skipif(not os.environ.get("OM_SAMUS_BRES"), reason="needs owned extracted BRES")
def test_real_samus_normal():
    b = open(os.environ["OM_SAMUS_BRES"], "rb").read()
    m = parse_mdl0(b, 0xF6E0)
    assert m["name"] == "samus_normal" and m["num_vertices"] == 14104
    assert len(m["bones"]) == 28 and len(m["verts"]) == 31 and len(m["objects"]) == 31
    assert m["bones"][3]["name"] == "MOTsamuslhip" and m["bones"][3]["parent"] == "MOTsamuships"


def test_parse_object_synthetic():
    o = bytearray(0x300)
    struct.pack_into(">8i", o, 0, 0x300, 0, -1, 0x4400, 2, 0x11, 0xE0, 0x80)
    struct.pack_into(">6i", o, 0x20, 0x68, 0x100, 0x100, 0x13C, 0x2A00, 0)
    struct.pack_into(">4i", o, 0x38, 0, 0, 8, 3)
    struct.pack_into(">4H", o, 0x48, 0, 0, 0xFFFF, 0xFFFF)
    struct.pack_into(">8H", o, 0x50, *[0xFFFF] * 8)
    struct.pack_into(">2i", o, 0x60, -1, 0x68)
    struct.pack_into(">I3H", o, 0x68, 3, 3, 7, 0xFFFF)
    ob = nw.parse_object(bytes(o), 0, "obj0")
    assert ob["face_count"] == 3 and ob["vertex_count"] == 8
    assert ob["bone_index"] == -1 and ob["bone_table"] == [3, 7, 0xFFFF]
    assert ob["vertex_group"] == 0 and ob["normal_group"] == 0
    assert ob["color_groups"] == [None, None]
    assert ob["decl_bytes"] == b"\x00" * 0xE0
    assert len(ob["code_bytes"]) == 0x300 - (0x24 + 0x13C)


def test_display_list_real_samus_normal():
    p = os.environ.get("OM_SAMUS_BRES")
    if not p or not os.path.exists(p):
        pytest.skip("OM_SAMUS_BRES not set")
    b = open(p, "rb").read()
    m = nw.parse_mdl0(b, 0xF6E0)
    dl = nw.decode_display_list(m)
    assert len(dl["objects"]) == 31
    assert dl["total_faces"] == 9980 == m["num_faces"]
    assert dl["consistent"]
    assert all(o["vertex_array"] is not None for o in dl["objects"])
    for o in dl["objects"]:
        if "bone_table" in o:
            assert isinstance(o["bone_table"], list)
