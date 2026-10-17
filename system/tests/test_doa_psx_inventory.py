"""Focused tests for gbox.doa_psx_inventory (Dead or Alive USA PSX, SLUS-00606).

Synthetic fixtures only: the parsers must work on the in-file tables without
touching the owned disc image.
"""
import struct

from gbox import doa_psx_inventory as di


def _put_cstr(buf: bytearray, off: int, s: str) -> int:
    raw = s.encode("latin-1") + b"\x00"
    buf[off:off + len(raw)] = raw
    return (off + len(raw) + 3) & ~3


def test_exe_header_sony_variant():
    b = bytearray(0x60)
    b[0:8] = b"PS-X EXE"
    struct.pack_into("<4I", b, 0x10, 0x80010E44, 0, 0x80010000, 0x84800)
    h = di.exe_header(bytes(b))
    assert h["magic"] == "PS-X EXE"
    assert h["pc0"] == 0x80010E44
    assert h["t_addr"] == 0x80010000
    assert h["t_size"] == 0x84800
    assert h["loaded_span"] == (0x80010000, 0x80094800)


def test_exe_header_non_exe():
    h = di.exe_header(b"\x08\xf6\x06\x00" + b"\x00" * 0x20)
    assert h["magic"] is None
    assert h["size"] == 0x24


def test_block_table_stops_at_zero_pair():
    b = bytearray(0x800)
    for i, (size, ref) in enumerate(((0x100, 0x80027300), (0x200, 0x80040300),
                                     (0, 0), (0x999, 0x999))):
        struct.pack_into("<II", b, 8 * i, size, ref)
    tbl = di.block_table(bytes(b))
    assert tbl == [(0x100, 0x80027300), (0x200, 0x80040300)]


def test_roster_names_empty_slot_is_none():
    b = bytearray(0x1900)
    off = di.ROSTER_OFFSET
    off = _put_cstr(b, off, "AYANE")
    off = _put_cstr(b, off, "LEI-FANG")
    off = (off + 4 + 3) & ~3          # one empty slot (4 zero bytes)
    off = _put_cstr(b, off, "KASUMI")
    roster = di.roster_names(bytes(b))
    assert roster[0] == "AYANE"
    assert roster[1] == "LEI-FANG"
    assert roster[2] is None
    assert roster[3] == "KASUMI"


def test_gallery_records_and_stop():
    b = bytearray(di.GALLERY_OFFSET + 0x80)

    def rec(off, title, name):
        t = title.encode("latin-1") + b"\x00"
        b[off:off + len(t)] = t
        lab = (off + len(t) + 3) & ~3
        b[lab:lab + 7] = b"\\OMAKE\\"
        n = name.encode("latin-1") + b"\x00"
        b[lab + 7:lab + 7 + len(n)] = n
        return (lab + 7 + len(n) + 3) & ~3

    off = rec(di.GALLERY_OFFSET, "ZACK 3", "ZACK3.BMP;1")
    off = rec(off, "HAYABUSA", "RYU1.BMP;1")
    # a record whose label is not OMAKE ends the list
    t = b"PLAYER1\x00"
    b[off:off + len(t)] = t
    lab = (off + len(t) + 3) & ~3
    b[lab:lab + 7] = b"\\PLAYR\\"
    assert di.gallery(bytes(b)) == [("ZACK 3", "ZACK3.BMP;1"),
                                    ("HAYABUSA", "RYU1.BMP;1")]
