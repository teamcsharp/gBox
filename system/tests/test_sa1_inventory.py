import struct

from gbox import sa1_inventory as sa1

KEY = sa1.KEY


def _exe():
    """Synthetic 1ST_READ: root -> child -> grandchild, root sibling; each node has a basic NJS_MODEL with one
    meshset whose material uses texture ids 3, 5, 0, 7."""
    buf = bytearray(0x2000)
    a = lambda off: KEY + off

    def model(at, pts_at, mset_at, mat_at, tex):
        struct.pack_into("<3f", buf, pts_at, 1.0, 2.0, 3.0)                         # one point
        struct.pack_into("<3I", buf, mat_at, 0xFFFFFFFF, 0, 0)
        struct.pack_into("<I", buf, mat_at + 12, 0x20000000 | tex)                   # attr_texId
        struct.pack_into("<HHIIIII", buf, mset_at, 0 << 14 | 0, 1, 0, 0, 0, 0, 0)    # type 0 (tris), material 0
        struct.pack_into("<IIiIIHH", buf, at, a(pts_at), 0, 1, a(mset_at), a(mat_at), 1, 1)
        struct.pack_into("<4f", buf, at + 0x18, 0, 0, 0, 1.5)

    def obj(at, mdl, child, sib):
        struct.pack_into("<II3f3i3fII", buf, at, 0x17, a(mdl), 0, 0, 0, 0, 0, 0, 1.0, 1.0, 1.0,
                         a(child) if child else 0, a(sib) if sib else 0)

    for i, tex in enumerate((3, 5, 0, 7)):
        model(0x800 + i * 0x100, 0x840 + i * 0x100, 0x860 + i * 0x100, 0x880 + i * 0x100, tex)
    obj(0x100, 0x800, 0x140, 0x1C0)      # root: child 0x140, sibling 0x1C0
    obj(0x140, 0x900, 0x180, 0)
    obj(0x180, 0xA00, 0, 0)
    obj(0x1C0, 0xB00, 0, 0)
    return bytes(buf)


def test_scan_finds_only_the_root_tree_with_parents_and_textures():
    trees = sa1.scan_trees(_exe(), min_nodes=2)
    assert len(trees) == 1
    t = trees[0]
    assert t["addr"] == f"0x{KEY + 0x100:08X}" and t["file_offset"] == 0x100
    assert t["nodes"] == 4 and t["models"] == 4 and t["points"] == 4 and t["meshsets"] == 4
    assert t["textures"] == [0, 3, 5, 7]
    assert sorted(t["parents"]) == [-1, -1, 0, 1]


def test_model_rejects_out_of_range_pointers():
    ex = sa1.Exe(_exe())
    assert ex.model(KEY + 0x800)["textures"] == [3]
    bad = bytearray(_exe())
    struct.pack_into("<I", bad, 0x800, 0x8D000000)                                 # points outside the exe
    assert sa1.Exe(bytes(bad)).model(KEY + 0x800) is None
    assert sa1.Exe(bytes(bad)).tree(KEY + 0x100) is None


def test_texture_fits_is_a_size_filter():
    t = {"textures": [0, 18]}
    assert sa1.texture_fits(t, {"SONIC": 28, "TIKAL": 18, "EGGMAN": 19}) == ["EGGMAN", "SONIC"]
    assert sa1.texture_fits({"textures": []}, {"A": 0}) == ["A"]


def test_classify_and_ip_header():
    assert sa1.classify("1ST_READ.BIN") == "executable"
    assert sa1.classify("SONICADV/SONIC.PRS") == "prs"
    assert sa1.classify("SONICADV/SET0100S.BIN") == "stage_layout"
    assert sa1.classify("SONICADV/PL_10B.BIN") == "stage_lighting"
    assert sa1.classify("SONICADV/K_SONIC.BIN") == "binary"
    assert sa1.classify("BG_MAIN.GIF") == "web_browser"
    hdr = (b"SEGA SEGAKATANA SEGA ENTERPRISES3B97 GD-ROM1/1   U      0601A10 MK-51000  V1.00519991005        "
           b"1ST_READ.BIN    SEGA ENTERPRISESSONIC ADVENTURE").ljust(256, b" ")
    ip = sa1.ip_info(hdr)
    assert ip["product"] == "MK-51000" and ip["version"] == "V1.005" and ip["date"] == "19991005"
    assert ip["boot"] == "1ST_READ.BIN" and ip["area"] == "U" and ip["title"] == "SONIC ADVENTURE"
