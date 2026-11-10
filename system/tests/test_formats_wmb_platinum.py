import struct
import pytest
from gbox.formats.wmb_platinum import parse_wmb, skeleton_error


def _build(nv=2, bad_parent=False):
    ov = 0xC0
    oe = ov + 32 * nv
    oh = oe + 16 * nv
    orp = oh + 16
    oab = orp + 48
    buf = bytearray(oab + 48)
    buf[:4] = b"WMB\0"
    struct.pack_into("<II", buf, 8, 0x4B40001F, nv)
    struct.pack_into("<II", buf, 0x18, ov, oe)
    struct.pack_into("<4I", buf, 0x30, 3, oh, orp, oab)
    struct.pack_into("<3h", buf, oh, -1, 0, 7 if bad_parent else 1)
    rel = [(0, 1, 0), (0, .5, 0), (.25, 0, 0)]
    ab = [(0, 1, 0), (0, 1.5, 0), (.25, 1.5, 0)]
    for i in range(3):
        struct.pack_into("<3f", buf, orp + 12 * i, *rel[i])
        struct.pack_into("<3f", buf, oab + 12 * i, *ab[i])
    for i in range(nv):
        struct.pack_into("<3f2e", buf, ov + 32 * i, i, 2.0, -1.0, 0.5, 0.25)
        buf[ov + 32 * i + 24:ov + 32 * i + 32] = bytes([2, 0, 0, 0, 255, 0, 0, 0])
    return bytes(buf)


def test_parse_and_skeleton():
    w = parse_wmb(_build())
    assert w.vertex_count == 2 and len(w.vertices) == 2
    assert w.vertices[1].pos == (1.0, 2.0, -1.0)
    assert w.vertices[0].uv == (0.5, 0.25)
    assert w.vertices[0].bone_idx[0] == 2 and sum(w.vertices[0].bone_w) == 255
    assert w.parents == [-1, 0, 1]
    assert skeleton_error(w) < 1e-6


def test_rejects():
    with pytest.raises(ValueError):
        parse_wmb(b"XXXX" + bytes(300))
    with pytest.raises(ValueError):
        parse_wmb(_build(bad_parent=True))
