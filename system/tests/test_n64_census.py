import struct
import zlib
import pytest
from gbox.formats import n64_census as n


def _rom():
    b = bytearray(0x200000)
    b[0:4] = b"\x80\x37\x12\x40"
    b[0x20:0x2F] = b"Ready to Rumble"
    b[0x3B:0x3F] = b"N22E"
    b[0x100000:0x100000 + 0] = b""
    comp = zlib.compress(b"A" * 500)
    b[0x150000:0x150000 + len(comp)] = comp
    b[0x160000:0x160004] = b"Yaz0"
    return bytes(b)


def test_v64_roundtrip():
    z = _rom()
    v = bytearray(z)
    v[0::2], v[1::2] = z[1::2], z[0::2]
    out, order = n.normalize(bytes(v))
    assert order == "v64" and out == z


def test_n64_le_words():
    z = _rom()
    le = bytearray(len(z))
    for k in range(4):
        le[k::4] = z[3 - k::4]
    out, order = n.normalize(bytes(le))
    assert order == "n64" and out == z


def test_header_and_census():
    z = _rom()
    h = n.header(z)
    assert h["title"] == "Ready to Rumble" and h["game_code"] == "N22E"
    c = n.census(z)
    assert c["ZLIB-789C"]["count"] == 1 and c["ZLIB-789C"]["first_offsets"] == ["0x150000"]
    assert c["Yaz0"]["first_offsets"] == ["0x160000"]


def test_rejects_bad():
    with pytest.raises(ValueError):
        n.normalize(b"\0\0\0\0" * 8)
    with pytest.raises(ValueError):
        n.header(b"\x80\x37\x12\x40")
    with pytest.raises(ValueError):
        n.crc(b"\0" * 100)
