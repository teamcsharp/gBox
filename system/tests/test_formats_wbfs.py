import struct

import pytest

from gbox.formats import disc
from gbox.formats.wbfs import WBFS


def make_wbfs(path, hd_s=9, wbfs_s=21):
    hd, ws = 1 << hd_s, 1 << wbfs_s
    n_wlba = -(-((143432 * 2) << 15) // ws)
    info_size = 0x100 + n_wlba * 2
    info_secs = -(-info_size // hd)
    hdr = bytearray(hd)
    hdr[:4] = b"WBFS"
    struct.pack_into(">I", hdr, 4, 100000)
    hdr[8], hdr[9] = hd_s, wbfs_s
    hdr[0x0C] = 1
    # logical disc: header at 0, partition table at 0x40000 -> 1 group-0 table at 0x40020 with 2 partitions
    disc = bytearray(ws)
    disc[:6] = b"R3ME01"
    disc[7] = 0
    struct.pack_into(">I", disc, 0x18, 0x5D1C9EA3)
    disc[0x20:0x20 + 14] = b"METROID PRIME\0"[:14]
    disc2 = bytearray(ws)  # WBFS sector 0 of logical disc holds 0..2MiB, which includes 0x40000
    disc2[:0x60] = disc[:0x60]
    struct.pack_into(">II", disc2, 0x40000, 2, 0x40020 >> 2)
    struct.pack_into(">II", disc2, 0x40020, 0x50000 >> 2, 1)
    struct.pack_into(">II", disc2, 0x40028, 0xF800000 >> 2, 0)
    info = bytearray(info_secs * hd)
    info[:0x100] = disc2[:0x100]
    struct.pack_into(">H", info, 0x100, 1)       # logical sector 0 -> physical sector 1 (sector 1 of file)
    # logical sector 1 absent -> zeros
    body = bytes(hdr) + bytes(info)
    body += bytes(ws - len(body) % ws)           # pad to a WBFS sector boundary
    assert len(body) == ws
    body += bytes(disc2)
    path.write_bytes(body)
    return path


def test_wbfs_header_partitions_and_zero_sectors(tmp_path):
    p = make_wbfs(tmp_path / "g.wbfs")
    w = WBFS(p)
    assert w.disc_header() == {"game_id": "R3ME01", "disc_number": 0, "revision": 0, "title": "METROID PRIME"}
    assert w.partitions() == [{"offset": 0x50000, "type": 1, "group": 0}, {"offset": 0xF800000, "type": 0, "group": 0}]
    assert w.read(1 << 21, 16) == bytes(16)      # absent sector reads as zeros
    assert len(w.read((1 << 21) - 8, 16)) == 16  # crosses a sector boundary
    w.close()


def test_listing_routes_wbfs(tmp_path):
    L = disc.listing(make_wbfs(tmp_path / "g.wbfs"))
    assert L.kind == "wii_wbfs" and L.files == []
    assert "R3ME01 METROID PRIME" in L.notes[0] and "type0@0xF800000" in L.notes[1]


def test_wbfs_rejects_bad_input(tmp_path):
    bad = tmp_path / "b.wbfs"
    bad.write_bytes(b"NOPE" + bytes(600))
    with pytest.raises(ValueError):
        WBFS(bad)
    trunc = tmp_path / "t.wbfs"
    trunc.write_bytes(make_wbfs(tmp_path / "x.wbfs").read_bytes()[:300])
    with pytest.raises(ValueError):
        WBFS(trunc)
