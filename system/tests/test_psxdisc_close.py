"""PSXDisc.close / CHD.close regression: assimilate's disc probe (gbox/formats/disc.py)
calls disc.close() in a finally block; PSXDisc previously had no close() and fingerprint
jobs died with AttributeError('PSXDisc' object has no attribute 'close')."""
import struct

from gbox.psxdisc import CHD, PSXDisc


def _mode2_sector(user: bytes) -> bytearray:
    s = bytearray(2448)                       # 2352 sector + 96 subcode = one hunk
    s[15] = 2                                 # Mode 2 marker read by PSXDisc.data()
    s[24:24 + len(user)] = user
    return s


def _build_chd(path) -> None:
    hunk, n, hlen = 2448, 18, 0x6C
    h = bytearray(hlen)
    h[0:8] = b"MComprHD"
    struct.pack_into(">II", h, 8, hlen, 4)            # header length, version 4
    struct.pack_into(">III", h, 16, 0, 2, n)          # flags, compression=none, nhunks
    struct.pack_into(">QQ", h, 28, n, 0)              # logical bytes, meta
    struct.pack_into(">I", h, 44, hunk)               # hunkbytes -> 1 frame per hunk
    pvd = bytearray(2048)
    pvd[0:8] = b"\x01CD001\x01"
    root = bytearray(34)
    root[0] = 34
    struct.pack_into("<I", root, 2, 17)               # root extent LBA
    struct.pack_into("<I", root, 10, 2048)            # root size
    root[25] = 2                                      # directory flag
    root[32], root[33] = 1, 0                         # self record, name "\0"
    pvd[156:190] = root
    dird = bytearray(2048)                            # root dir: only self + parent
    dird[0:34] = root
    dird[34:68] = bytes(root[:33]) + b"\x01"
    hunks = [bytearray(hunk) for _ in range(n)]
    hunks[16] = _mode2_sector(bytes(pvd))
    hunks[17] = _mode2_sector(bytes(dird))
    data_off = hlen + 16 * n
    out = bytearray(h)
    for i in range(n):                                # uncompressed map entries (type 2)
        out += struct.pack(">QIHBB", data_off + i * hunk, 0, 0, 0, 2)
    for hk in hunks:
        out += hk
    path.write_bytes(out)


def test_psxdisc_construct_and_close(tmp_path):
    p = tmp_path / "mini.chd"
    _build_chd(p)
    d = PSXDisc(str(p))
    assert d.files == {}                      # ISO9660 walk completed on the synthetic disc
    d.close()
    assert d.chd.f.closed                     # underlying handle really closed
    d.close()                                 # idempotent: second call is a no-op
    assert d.chd.f.closed


def test_chd_close_idempotent(tmp_path):
    p = tmp_path / "mini.chd"
    _build_chd(p)
    c = CHD(str(p))
    assert len(c.sector(16)) == 2352
    c.close()
    c.close()
    assert c.f.closed
