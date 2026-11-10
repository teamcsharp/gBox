import struct
import pytest
from gbox import puyotetris_inventory as pt


def _blob(w, h, fill=b"\0"):
    hdr = bytearray(0x80)
    hdr[0:4] = b"\x02\x02\x00\xff"
    hdr[4:8] = (w * h).to_bytes(4, "big")
    hdr[0x10:0x14] = (0x80).to_bytes(4, "big")
    hdr[0x14:0x18] = (w * h).to_bytes(4, "big")
    hdr[0x20:0x24] = struct.pack(">HH", w, h)
    return bytes(hdr) + fill * (w * h)


def test_header_and_dds():
    b = _blob(32, 16)
    assert pt.raw02_header(b)["width"] == 32
    assert pt.raw02_to_dds(b)[:4] == b"DDS "


def test_rejects_bad():
    with pytest.raises(ValueError):
        pt.raw02_header(_blob(32, 16)[:-1])
    with pytest.raises(ValueError):
        pt.raw02_header(b"NCIF" + bytes(200))


def test_decode_rgba():
    pytest.importorskip("PIL")
    im = pt.raw02_to_rgba(_blob(8, 8))
    assert im.size == (8, 8)
