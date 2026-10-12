import json
import os
import struct
from pathlib import Path

import pytest

from gbox import merc3d_mod as mm

REAL_MOD = Path(os.path.expanduser("~/gbox-cache/3ds/0ed22ae742e1b56b/inventory/pl0000.mod"))

# pl0000 (Chris): the joint ids of the 20-bone table == the mesh joint-id set.
PL0000_JOINTS = [0x00, 0x01, 0x02, 0x14, 0x18, 0x1C, 0x28, 0x2F, 0x30, 0x37,
                 0x38, 0x3C, 0x3D, 0x40, 0x46, 0x50, 0x53, 0x54, 0x58, 0x60]


def _mod(bones=2, meshes=2, verts=4, idx_total=8):
    """Synthetic MOD v229 in the pinned layout: 20B header, 11-u32 offset table at 0x14,
    bones (0x20), materials (0x80), meshes (0x30), vertices (36B), u16 indices."""
    b_off, n_b = 0x40, bones
    m_off, n_m = b_off + n_b * 0x20, 1
    s_off, n_s = m_off + n_m * 0x80, meshes
    v_off = s_off + n_s * 0x30
    v_end = v_off + verts * 36
    i_off = v_end
    buf = bytearray(i_off + idx_total * 2)
    buf[:4] = mm.MAGIC
    struct.pack_into("<HHHHII", buf, 4, 229, bones, meshes, 1, verts, idx_total)
    struct.pack_into("<11I", buf, 0x14, 0x39FD, verts * 36, 0, bones, 1, 0x80,
                     b_off, m_off, s_off, v_off, i_off)
    for i in range(bones):
        o = b_off + i * 0x20
        struct.pack_into("<4I", buf, o, i, 0x441487B5 + i, 0xC4B4C401 + i, 0)
        struct.pack_into("<I", buf, o + 0x1C, 0x7F800000)
    buf[m_off:m_off + 0x80] = b"mat0\x00".ljust(0x80, b"\x00")
    # mesh 0: 2 verts @0, joint 0, indices [0,1,2] header + [1,3,2]
    o = s_off
    struct.pack_into("<6H5I", buf, o, 0xEFDF, 2, 0, 1, 0x21, 0x424, 0, 0, 0xF606F017, 0, 3)
    buf[o + 0x20:o + 0x30] = bytes(16)
    # mesh 1: 2 verts @2, joint 1, 2-index header [0,1], no extra indices
    o = s_off + 0x30
    struct.pack_into("<6H5I", buf, o, 0xEFDF, 2, 1, 1, 0x121, 0x424, 2, 0, 0xF606F017, 6, 0)
    buf[o + 0x20:o + 0x30] = bytes(16)
    for k in range(verts):
        o = v_off + k * 36
        struct.pack_into("<3f", buf, o, 0.1 + k, 0.2 + k, 0.01 * k)
        struct.pack_into("<2h", buf, o + 12, int(0.25 * 32768), int(0.75 * 32768))
        struct.pack_into("<2f", buf, o + 16, 0.5, 0.5)
        struct.pack_into("<I", buf, o + 24, 0x4DB20801)
        struct.pack_into("<2h", buf, o + 28, int(-0.5 * 32768), int(-0.5 * 32768))
        struct.pack_into("<I", buf, o + 32, (64 << 16) | (k % bones))
    idx = struct.pack("<8H", 0, 1, 2, 1, 3, 2, 0, 1)
    buf[i_off:i_off + len(idx)] = idx
    return bytes(buf)


def test_mod_rejects_garbage():
    with pytest.raises(mm.ModError):
        mm.Mod(b"\0" * 64)
    with pytest.raises(mm.ModError):
        mm.Mod(mm.MAGIC + struct.pack("<HHHHII", 1, 0, 0, 0, 0, 0) + b"\0" * 40)


def test_synthetic_mod_roundtrip():
    m = mm.Mod(_mod())
    assert m.version == 229 and m.bone_count == 2 and m.mesh_count == 2 and m.material_count == 1
    assert m.vertex_count == 4 and m.index_count == 8
    assert (m.bone_off, m.mat_off, m.mesh_off, m.vtx_off, m.idx_off) == (0x40, 0x80, 0x100, 0x160, 0x1F0)
    assert [b.joint for b in m.bones] == [0, 1] and m.materials == ["mat0"]
    assert m.meshes[0].vertex_count == 2 and m.meshes[0].joint == 0 and m.meshes[0].fmt == 0x21
    assert m.meshes[1].vertex_start == 2 and m.meshes[1].index_start == 6
    assert {x.header for x in m.meshes} == {2, 3}           # strip headers tiled
    v = m.vertex(m.meshes[0], 0)
    assert v.pos == pytest.approx((0.1, 0.2, 0.0), abs=1e-6) and v.uv0 == (0.25, 0.75) and v.uv1 == (0.5, 0.5)
    assert v.bone2 == 0 and v.weight2 == 64
    assert m.indices(m.meshes[0]) == [0, 1, 2, 1, 3, 2]
    out = m.obj(m.meshes[0])
    assert "v 0.100000 0.200000 0.000000" in out and "vt 0.250000 0.750000" in out
    json.dumps(m.summary())


@pytest.mark.skipif(not REAL_MOD.exists(), reason="owned pl0000.mod not extracted")
def test_owned_pl0000_mod():
    m = mm.Mod(REAL_MOD.read_bytes())
    assert (m.version, m.bone_count, m.mesh_count, m.material_count) == (229, 20, 46, 5)
    assert (m.vertex_count, m.index_count) == (13449, 27624)
    assert (m.vtx_off, m.vtx_size, m.idx_off) == (0x1B20, 0x76344, 0x77E64)
    assert [b.joint for b in m.bones] == PL0000_JOINTS
    assert all(b.pad == 0 and b.pos == (0.0, 0.0, 0.0) and b.tail == 0x7F800000 for b in m.bones)
    assert sorted({x.header for x in m.meshes}) == [2, 3]
    assert sum(x.vertex_count for x in m.meshes) == 13449
    assert m.meshes[-1].index_start + m.meshes[-1].header + m.meshes[-1].index_count == 27624
    v = m.vertex(m.meshes[0], 0)
    assert v.pos == (0.38539400696754456, 0.5808894634246826, 0.020524559542536736)
    assert v.uv0 == pytest.approx((9243 / 32768, 32630 / 32768), abs=1e-6)
    assert v.uv1 == (0.391357421875, 0.50146484375)
    assert v.u24 == 0x4DB20801 and v.pair == (-30431 / 32768, -32485 / 32768)
    assert (v.bone2, v.weight2) == (1, 0)
    obj = m.obj(m.meshes[0])
    assert obj.count("\nv ") == 2747 and obj.count("\nf ") > 0
    json.dumps(m.summary())
