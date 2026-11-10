import struct, os, pytest
from gbox import tetris_plus_inventory as t

def _tim4(w=4, h=2):
    pal = struct.pack("<16H", *([0, 0x7FFF, 0x001F] + [0] * 13))
    clut = struct.pack("<IHHHH", 12 + 32, 0, 481, 16, 1) + pal
    pix = bytes([0x21, 0x21]) * h  # w=4 px -> 2 bytes/row
    img = struct.pack("<IHHHH", 12 + len(pix), 640, 0, w // 4, h) + pix
    return struct.pack("<II", 0x10, 8) + clut + img

def test_scan_with_prefix_and_png():
    buf = b"\0\x7c\0" + _tim4() + b"junk" + _tim4()
    tims = t.scan_tims(buf)
    assert [x["off"] for x in tims][0] == 3 and len(tims) == 2
    assert (tims[0]["bpp"], tims[0]["width"], tims[0]["h"]) == (4, 4, 2)
    png = t.tim_to_png(buf, tims[0])
    assert png[:8] == b"\x89PNG\r\n\x1a\n" and b"IHDR" in png

def test_reject_bad():
    assert t.parse_tim(b"\x10\0\0\0\x08\0\0\0" + b"\xff" * 20) is None

def test_exe_header():
    d = b"PS-X EXE" + bytes(8) + struct.pack("<IIII", 0x80010000, 0, 0x80010000, 0x1000)
    assert t.exe_header(d)["pc"] == 0x80010000

DISC = "/mnt/gbox/hyperspin/Arcade/collections/Sony Playstation/roms/Tetris Plus (USA).chd"
@pytest.mark.skipif(not os.path.exists(DISC), reason="owned disc absent")
def test_real_boot_hash():
    m = t.inventory(DISC)
    assert m["boot"]["sha256"] == "2a99729c0573056d6e6b11bfc57f7a2114839774163c3048ebaf81e337cbe4c0"
    assert len(m["files"]) == 31
