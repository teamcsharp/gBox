"""Analysis-stage format probe tests for RE Survivor 2 - Code: Veronica MDL models."""
import json
import os
import struct
from pathlib import Path

from gbox.gs2_mdl import (
    embedded_tim2, mdl_header, mdl_name, nested_mdl, ninja_vertex_census,
    probe, walk_ninja_polys, walk_ninja_verts,
)

DISC = Path(os.environ.get("GBOX_GS2_DISC", "/home/ehm_eckx/gbox-cache/ps2/5ec1d297cb44b3ea/disc.iso"))


def _mdl(u32=0, marker=0xBC, const=0x10, typ=1, tail=b""):
    return struct.pack("<I", u32) + b"MDL" + bytes([marker]) + struct.pack("<HH", const, typ) + tail


def test_mdl_header():
    h = mdl_header(_mdl(u32=0x4A8, typ=2))
    assert h == {"u32": 0x4A8, "marker": 0xBC, "const": 0x10, "type": 2}
    assert mdl_header(_mdl(marker=0xAC, typ=1))["marker"] == 0xAC
    assert mdl_header(b"NOTMDL......") is None
    assert mdl_header(b"") is None


def test_mdl_name():
    # names sit in 8-byte slots; put one at 0x28
    d = _mdl(typ=2) + b"\x00" * (0x28 - 12) + b"Shell_1\x00"
    assert mdl_name(d) == "Shell_1"


def test_embedded_tim2_and_nested():
    d = b"\x00" * 0x20 + b"TIM2" + b"\x00" * 8 + b"MDL\xad\x10\x00"
    assert embedded_tim2(d) == 0x20
    assert nested_mdl(d) == [0x2C]


def test_walk_ninja_polys_material_tiny_end():
    # material (0x13, 4 shorts) + tiny texture id 64 (0x08) + end
    stream = (struct.pack("<BBH", 0x13, 0x25, 4) + b"\x00" * 8 +
              struct.pack("<BBH", 0x08, 0x00, 64) +
              struct.pack("<BB", 0xFF, 0x00))
    r = walk_ninja_polys(stream, 0)
    assert r["texture_id"] == 64
    assert r["strips"] == 0 and r["triangles"] == 0


def test_walk_ninja_polys_strip():
    # one strip of 3 vertices (a triangle) with UVs, typ 0x42
    n, hdr = 3, 1
    strip_data = struct.pack("<h", n) + b"".join(
        struct.pack("<H", i) + struct.pack("<hh", i * 10, i * 20) for i in range(n))
    size = (2 + len(strip_data)) // 2  # hdr(2) + strip data, in shorts
    stream = struct.pack("<BBHH", 0x42, 0x00, size, hdr) + strip_data + struct.pack("<BB", 0xFF, 0)
    r = walk_ninja_polys(stream, 0)
    assert r["triangles"] == 1 and r["strips"] == 1


def test_walk_ninja_verts_vn():
    # one VN (0x29) vertex chunk: 2 verts x 24 bytes (pos 3f + nrm 3f)
    count, stride = 2, 24
    size = (count * stride + 4) // 4
    head = struct.pack("<I", 0x29 | (size << 16)) + struct.pack("<I", count << 16)
    verts = b"".join(struct.pack("<6f", 0.1, 0.2, 0.3, 0.0, 0.0, 1.0) for _ in range(count))
    stream = head + verts + struct.pack("<I", 0xFF)
    r = walk_ninja_verts(stream, 0)
    assert r["vertices"] == 2 and r["types"] == [0x29]


def _mdl_entries():
    """Yield (name, bytes) for every MDL entry, or skip when the disc is not staged."""
    import pytest
    from gbox.gta_rw import iso_files
    if not DISC.exists():
        pytest.skip(f"disc not staged: {DISC}")
    with open(DISC, "rb") as f:
        files = iso_files(f)
        manifest = json.load(open("/home/ehm_eckx/gbox-cache/ps2/5ec1d297cb44b3ea/gs2_manifest.json"))
        def rd(lba, e):
            f.seek(lba * 2048 + e["off"])
            return f.read(e["size"])
        sys_lba = manifest["containers"]["afs"]["SYSTEM.AFS"][0]
        tsu_lba = manifest["containers"]["afs"]["TSUIKA.AFS"][0]
        for e in manifest["afs"]["SYSTEM.AFS"]["mdl"]:
            yield f"SYSTEM/{e['i']}", rd(sys_lba, e)
        for e in manifest["afs"]["TSUIKA.AFS"]["mdl"]:
            yield f"TSUIKA/{e['i']}", rd(tsu_lba, e)


def test_probe_all_94_census():
    from collections import Counter
    entries = list(_mdl_entries())
    assert len(entries) == 94
    markers, types, names = Counter(), Counter(), set()
    no_tim2 = set()
    for path, d in entries:
        h = mdl_header(d)
        assert h is not None, path
        markers[h["marker"]] += 1
        types[h["type"]] += 1
        nm = mdl_name(d)
        if nm:
            names.add(nm)
        if embedded_tim2(d) is None:
            no_tim2.add(path)
    assert markers == {0xBC: 88, 0xAC: 6}
    assert types == {1: 11, 2: 7, 3: 44, 4: 17, 5: 10, 6: 4, 7: 1}
    # 87/94 embed a TIM2; the 7 without are the multi-part Shell_1 body part and the
    # six TSUIKA "MDL\\xac" variant models that share a texture bank.
    assert no_tim2 == {"SYSTEM/15", "TSUIKA/2", "TSUIKA/3", "TSUIKA/4",
                       "TSUIKA/5", "TSUIKA/6", "TSUIKA/7"}
    for expected in ("Shell_1", "cl02", "ch03", "STU_05", "BR_93R", "PYTHON",
                     "Ingram", "bowgun", "SPAS12", "AK47S", "M79", "knife"):
        assert expected in names, expected


def test_walk_shell_1_ninja_stream():
    import pytest
    from gbox.gta_rw import iso_files
    if not DISC.exists():
        pytest.skip(f"disc not staged: {DISC}")
    with open(DISC, "rb") as f:
        files = iso_files(f)
        manifest = json.load(open("/home/ehm_eckx/gbox-cache/ps2/5ec1d297cb44b3ea/gs2_manifest.json"))
        sys_lba = manifest["containers"]["afs"]["SYSTEM.AFS"][0]
        e = next(x for x in manifest["afs"]["SYSTEM.AFS"]["mdl"] if x["i"] == 1)
        f.seek(sys_lba * 2048 + e["off"])
        d = f.read(e["size"])
    # type-2 "Shell_1": polygon list at 0x44, first node's vertex list at 0x100
    r = walk_ninja_polys(d, 0x44)
    assert r["strips"] == 3 and r["triangles"] == 20
    v = walk_ninja_verts(d, 0x100)
    assert v["vertices"] == 12 and v["types"] == [0x29]
    census = ninja_vertex_census(d)
    assert sum(c["count"] for c in census) == 402  # ten vertex lists across the node tree
    assert all(c["stride"] == 24 for c in census if c["type"] == 0x29)  # VN = pos 3f + nrm 3f
