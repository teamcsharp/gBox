import io
import os
import struct

import pytest

from gbox import doa5lr_lfmo as L

# Header bytes copied from the owned message.bin / message.lnk (BLJM61258).
BIN_HEAD = bytes.fromhex("4c464d4f00000001000005860000002000000028"
                         "0000427000004" "27e00000000")


def make_pair(n=3):
    names = b"x.order\0" + b"".join(b"N%d\0" % i for i in range(n))
    idx_off = 0x28
    names_off = idx_off + 12 * n
    order = names_off
    first = order + 8
    b = bytearray(struct.pack(">4s6I", L.LFMO_MAGIC, 1, n, 0x20, idx_off, order, first)) + b"\0" * 12
    for i in range(n):
        b += struct.pack(">III", 0, i, first + sum(len(b"N%d\0" % j) for j in range(i)))
    b += names
    sizes = [0x30, 0x800, 5]
    offs, o = [], 0x800
    for s in sizes[:n]:
        offs.append(o)
        o += (s + 0x7FF) // 0x800 * 0x800
    lnk = bytearray(struct.pack(">4sIIIQQ", b"TEST", 0, 0, n, o, 0x800))
    for off, s in zip(offs, sizes):
        lnk += struct.pack(">4Q", off, s, s, 0)
    lnk += b"\0" * (o - len(lnk))
    for off, s in zip(offs, sizes):
        lnk[off:off + s] = bytes([off >> 11 & 255]) * s
    return bytes(b), bytes(lnk)


def test_real_header_fields():
    assert BIN_HEAD[:4] == b"LFMO"
    ver, count, hdr, idx = struct.unpack(">4I", BIN_HEAD[4:20])
    assert (ver, count, hdr, idx) == (1, 0x586, 0x20, 0x28)


def test_roundtrip_pair(tmp_path):
    b, l = make_pair()
    (tmp_path / "t.bin").write_bytes(b)
    (tmp_path / "t.lnk").write_bytes(l)
    p = L.open_pair(tmp_path / "t.bin", tmp_path / "t.lnk")
    assert p["count"] == 3 and p["tag"] == "TEST" and p["order_name"] == "x.order"
    assert [e["offset"] for e in p["entries"]] == [0x800, 0x1000, 0x1800]
    with open(tmp_path / "t.lnk", "rb") as f:
        assert L.read_member(f, p["entries"][2]) == bytes([3]) * 5


def test_rejects_bad():
    b, l = make_pair()
    with pytest.raises(L.LfmoError):
        L.parse_bin(b"XXXX" + b[4:])
    with pytest.raises(L.LfmoError):
        L.parse_bin(b[:0x30])
    bad = bytearray(l)
    bad[0x20 + 8] = 1  # misaligned? offset low byte
    with pytest.raises(L.LfmoError):
        L.parse_lnk(io.BytesIO(bytes(bad)), 3, len(bad))
    with pytest.raises(L.LfmoError):
        L.parse_lnk(io.BytesIO(l), 4, len(l))


OWNED = os.environ.get("DOA5LR_USRDIR")


@pytest.mark.skipif(not OWNED, reason="set DOA5LR_USRDIR to the extracted PS3_GAME/USRDIR")
@pytest.mark.parametrize("name,count", [("message", 1414), ("chara_rtm", 368)])
def test_owned_build(name, count):
    p = L.open_pair(os.path.join(OWNED, name + ".bin"), os.path.join(OWNED, name + ".lnk"))
    assert p["count"] == count
