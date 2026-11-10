import struct
import pytest
from gbox.formats.wmb_platinum import parse_wmb, skeleton_error, parse_meshes, export_obj


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


def _with_mesh(nv=8):
    buf = bytearray(_build(nv))
    base = len(buf)
    otab = base
    buf += struct.pack("<I", 0)             # one mesh at base+0
    mesh = base + 4
    buf += bytes(0x100)
    struct.pack_into("<III", buf, 0x50, 1, otab, mesh)
    buf[mesh + 0x20:mesh + 0x24] = b"body"
    struct.pack_into("<I", buf, mesh + 0x80, 0x20)           # 8-slot table, 1 batch
    struct.pack_into("<I", buf, mesh + 0x84, 0)
    b0 = mesh + 0x80 + 0x20
    buf += bytes(0x100)
    struct.pack_into("<I", buf, b0, 0)
    struct.pack_into("<5I", buf, b0 + 0x0c, 4, 8, 4, 0x80, 6)  # vs=4 ve=8 tri ioff ni=6
    struct.pack_into("<I", buf, b0 + 0x40, 2)
    buf[b0 + 0x44:b0 + 0x46] = bytes([1, 5])
    struct.pack_into("<6H", buf, b0 + 0x80, 0, 1, 2, 2, 1, 3)
    return bytes(buf)


def test_meshes_relative_indices_and_obj():
    b = _with_mesh()
    ms = parse_meshes(b)
    assert [m.name for m in ms] == ["body"]
    bt = ms[0].batches[0]
    assert bt.indices == [4, 5, 6, 6, 5, 7] and bt.bone_set == [1, 5]
    obj = export_obj(parse_wmb(b), ms)
    assert obj.count("\nf ") == 2 and "o body" in obj


def test_meshes_reject_oob_index():
    b = bytearray(_with_mesh())
    mesh = len(_build(8)) + 4
    struct.pack_into("<H", b, mesh + 0x80 + 0x20 + 0x80, 9)
    with pytest.raises(ValueError):
        parse_meshes(bytes(b))


def test_real_pl0000_if_present():
    import os
    d = os.environ.get("GBOX_B2_DIR")
    f = d and os.path.join(d, "pl0000_pl0000.wmb")
    if not f or not os.path.exists(f):
        pytest.skip("owned Bayonetta 2 extract not provided")
    b = open(f, "rb").read()
    w, ms = parse_wmb(b), parse_meshes(b)
    assert sum(len(x.indices) // 3 for m in ms for x in m.batches) == 23620
    assert {i for m in ms for x in m.batches for i in x.indices} == set(range(w.vertex_count))
