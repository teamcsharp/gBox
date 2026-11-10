import struct
from gbox import sonic_heroes as sh
from gbox.formats import lz


def _chunk(t, p):
    return struct.pack("<III", t, len(p), 0x1003FFFF) + p


def test_unpack_roundtrip():
    clump = struct.pack("<III", 0x10, 4, 0x1400FFFF) + b"abcd"
    d = b"X.DFF".ljust(0x40, b"\0")
    body = _chunk(1, d.ljust(0x100, b"\0")) + _chunk(2, lz.prs_compress(clump))
    one = _chunk(0, body)
    out = sh.unpack(one)
    assert out == {"X.DFF": clump} and sh.is_clump(out["X.DFF"])
