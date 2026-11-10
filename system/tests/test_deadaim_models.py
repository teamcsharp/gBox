import os
import struct

import pytest

from gbox.deadaim_models import parse_miz, miz_to_rgba, parse_fsc_header
from gbox.deadaim_fpk import parse_fpk


def _miz(w, h, bpp):
    pal = (0x400 if bpp == 8 else 0x40)
    pix = bytes(range(256)) * (w * h * bpp // 8 // 256 + 1)
    pix = pix[:w * h * bpp // 8]
    hd = bytearray(0x240)
    hd[0:4] = b"wZIM"
    struct.pack_into("<HH", hd, 0x2C, w, h)
    struct.pack_into("<I", hd, 0x4C, pal)
    return bytes(hd) + pix + bytes([1, 2, 3, 0x80]) * (pal // 4)


def test_miz_synthetic():
    t = parse_miz(_miz(16, 16, 8))
    assert (t["width"], t["height"], t["bpp"], t["pad"]) == (16, 16, 8, 0)
    assert len(miz_to_rgba(t)) == 16 * 16 * 4
    assert parse_miz(_miz(32, 32, 4))["bpp"] == 4


def test_fsc_synthetic():
    d = bytearray(0x100)
    d[0:4] = b"CSFg"
    d[0x0F:0x13] = b"CARM"
    d[0x14:0x1A] = b"x.ARM\0"[:6]
    struct.pack_into("<5I", d, 0x38, 0x4C, 0x80, 0x80, 0xC0, 0x100)
    h = parse_fsc_header(bytes(d))
    assert h["kind"] == "CARM" and h["size_matches"]


IMAGE = os.environ.get("DEADAIM_IMAGE_BIN", "")


@pytest.mark.skipif(not os.path.exists(IMAGE), reason="owned IMAGE.BIN not available")
def test_owned_zone_textures_and_shapes():
    f = open(IMAGE, "rb")

    def rd(o, n):
        f.seek(o)
        return f.read(n)
    top = parse_fpk(rd, 0, max_depth=0)
    counts = {"miz": 0, "fsc": 0}
    for z in top[1:3]:  # pc01a, pc02a zones
        for e in parse_fpk(rd, z["offset"], max_depth=4):
            if e["ext"] == "miz":
                t = parse_miz(rd(e["offset"], e["size"]))
                assert t["pad"] in range(0, 0x200) and len(miz_to_rgba(t)) == t["width"] * t["height"] * 4
                counts["miz"] += 1
            elif e["ext"] == "fsc":
                h = parse_fsc_header(rd(e["offset"], e["size"]))
                assert h["size_matches"] and h["sections"][0] == 0x4C
                counts["fsc"] += 1
    assert counts["miz"] > 100 and counts["fsc"] > 20
