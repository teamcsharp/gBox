"""Focused tests for gbox.re2psx_inventory (RE2 Dual Shock Edition PSX PLD format).

The PLD/PLW container and its MD1/EMR/EDD/TIM sections follow the layout
documented by the OpenBiohazard2 reference implementation (fileio/pld.go,
md1.go, emr.go, edd.go, tim.go).
"""

import struct

import pytest

from gbox.re2psx_inventory import (
    parse_edd,
    parse_emr,
    parse_md1,
    parse_tim,
    read_pld,
)


def _md1(num_obj: int) -> bytes:
    """Minimal MD1: num_obj=4 (2 objects), each list 2 verts/2 normals,
    3 triangles, and 1 quad in the quad header."""
    pairs = num_obj // 2
    hdr = struct.pack("<III", 0, 0, num_obj)
    obj_headers = bytearray()
    verts = bytearray()
    for i in range(pairs):
        vo, vc = len(verts) // 8, 2  # verts/normals are 8-byte each
        io = 0
        obj_headers += struct.pack("<7I", vo, vc, vo, vc, io, 3, 0)
        obj_headers += struct.pack("<7I", vo, vc, vo, vc, 0, 1, 0)
        verts += struct.pack("<4h", 1, 2, 3, 0) * 2
    return hdr + bytes(obj_headers) + bytes(verts)


def _tim() -> bytes:
    colors, cluts = 256, 3
    pal = bytes(2 * colors * cluts)
    img_hdr = struct.pack("<IHHHH", 0x0C + 384 * 256, 0, 0, 192, 256)
    pixels = bytes(384 * 256)
    return (
        struct.pack("<IIIHHHH", 0x10, 9, 0x60C, 0, 0x1E0, colors, cluts)
        + pal + img_hdr + pixels
    )


def _pld() -> bytes:
    # EDD: 3 animations; header (count=2, offset=0x0C) then per-anim headers
    edd = struct.pack("<HH", 2, 0x0C)
    edd += struct.pack("<HHHHHH", 3, 0x10, 1, 0x18, 2, 0x1C)
    edd += struct.pack("<III", 5, 6, 9) + struct.pack("<I", 9) + struct.pack("<II", 1, 0x7FFF)
    emr = struct.pack("<HHHH", 0x0C, 0x14, 2, 0x50) + bytes(8) + b"\xaa" * 8
    md1 = _md1(4)
    tim = _tim()
    body = edd + emr + md1 + tim
    # every offset in a PLD is absolute from the start of the file
    offs = [8 + 0, 8 + len(edd), 8 + len(edd) + len(emr),
            8 + len(edd) + len(emr) + len(md1)]
    directory = struct.pack("<4I", *offs)
    return struct.pack("<II", 8 + len(body), 4) + body + directory


def test_tim_header():
    t = parse_tim(_tim())
    assert t["bpp"] == 9
    assert t["w"] == 384 and t["h"] == 256
    assert t["colors"] == 256 and t["cluts"] == 3


def test_md1_counts():
    m = parse_md1(_md1(4))
    assert m["objects"] == 2 and m["num_obj"] == 4
    assert m["verts"] == 8 and m["normals"] == 8
    assert m["triangles"] == 6 and m["quads"] == 2


def test_emr_header():
    e = parse_emr(struct.pack("<HHHH", 0x0C, 0x14, 2, 0x50) + bytes(16))
    assert e["bones"] == 2 and e["elem_size"] == 0x50


def test_edd_tables():
    edd = struct.pack("<HH", 2, 0x0C)
    edd += struct.pack("<HHHHHH", 3, 0x10, 1, 0x18, 2, 0x1C)
    edd += struct.pack("<III", 5, 6, 9) + struct.pack("<I", 9) + struct.pack("<II", 1, 0x7FFF)
    e = parse_edd(edd)
    assert e["animations"] == 3 and e["table_entries"] == 6
    assert e["max_frame"] == 9


def test_pld_sections():
    p = read_pld(_pld())
    assert p["sections"] == [8, 48, 72, 228]
    assert p["md1"]["objects"] == 2
    assert p["emr"]["bones"] == 2
    assert p["tim"]["w"] == 384
    assert p["edd"]["animations"] == 3


def test_pld_bad_directory():
    with pytest.raises(ValueError):
        read_pld(b"\x00\x01\x00\x00\x05\x00\x00\x00xxxx")
