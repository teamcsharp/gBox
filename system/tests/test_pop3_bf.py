import struct, pytest
from gbox.pop3_bf import parse_index, BFError


def mk(offs, count=None):
    h = bytearray(0x40 + 8 * len(offs))
    h[:4] = b"BIG\0"
    struct.pack_into("<III", h, 4, 0x26, count or len(offs), 5)
    for i, o in enumerate(offs):
        struct.pack_into("<II", h, 0x40 + 8 * i, 0x1000 + i, o)
    return bytes(h)


def test_ok():
    r = parse_index(mk([0x1000, 0x1800, 0x3000]), 0x4000)
    assert r["count"] == 3 and [e["span"] for e in r["entries"]] == [0x800, 0x1800, 0x1000]


def test_rejects():
    for h, s in [(mk([0x1000, 0x1000]), 0x4000), (mk([0x1001]), 0x4000),
                 (mk([0x1000]), 0x1000), (b"XXXX" + bytes(0x80), 0x4000),
                 (mk([0x1000], count=9), 0x4000)]:
        with pytest.raises(BFError):
            parse_index(h, s)
