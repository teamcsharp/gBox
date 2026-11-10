"""Focused tests for the Fare Wars PSP POL*.BIN model reader (request #2453)."""
import hashlib
import os
import struct

import numpy as np
import pytest

from gbox.cso import CSO
from gbox.fare_wars_binc import OWNED_CSO_REL
from gbox.fare_wars_pol import FLT_MAX, ge_layout, mesh_vertices, parse_pol, strip_triangles

OWNED_ROOT = os.environ.get("GBOX_HYPERSPIN_ROOT", "/mnt/gbox/hyperspin/Arcade")
# (byte offset in the owned CSO's ISO, size, sha256) from the streamed inventory manifest
OWNED = {
    "POLPP1A.BIN": (162107392, 19304, "b23a2677736beb41875f23af53396910fe737b3ec98400dedbe11721878514bd", (47, 31, 148)),
    "POLPP2A.BIN": (162193408, 21508, "685eb8f7e03aca10e6c2750cc551e287a0be465c981741ba501fd1190a17cf8e", (47, 32, 170)),
}


def _owned(name):
    path = os.path.join(OWNED_ROOT, OWNED_CSO_REL)
    if not os.path.exists(path):
        pytest.skip(f"owned image not mounted: {path}")
    off, size, sha, _ = OWNED[name]
    with CSO(path) as c:
        c.seek(off)
        data = c.read(size)
    assert hashlib.sha256(data).hexdigest() == sha
    return data


def _synthetic():
    # 2 slots (one empty), 1 mesh, 1 strip of 4 u8-uv vertices at the cube-corner extremes
    empty = struct.pack("<HHI6f", 0, 0, 0, FLT_MAX, FLT_MAX, FLT_MAX, -FLT_MAX, -FLT_MAX, -FLT_MAX)
    slot = struct.pack("<HHI6f", 0, 1, 0, 0, 0, 0, 2, 2, 2)
    mesh = struct.pack("<5I6f", 0, 1, 0xFFFFFFFF, 0xFFFFFFFF, 0, 0, 0, 0, 2, 2, 2)
    vo = 16 + 64 + 44 + 16
    strip = struct.pack("<IHHII", 0x72, 4, 0x121, 4, 0)
    verts = b"".join(struct.pack("<2B4b3h", 0, 0, 0, 0, 127, 0, x, y, z)
                     for x, y, z in [(-32767, -32767, -32767), (32767, -32767, 0), (-32767, 32767, 0), (32767, 32767, 32767)])
    return struct.pack("<4I", 2, 1, 1, vo) + empty + slot + mesh + strip + verts


def test_synthetic_roundtrip_and_decode():
    b = _synthetic()
    p = parse_pol(b)
    assert p.slots[0].empty and not p.slots[1].empty and p.slots[1].first_mesh == 0
    P, N, U, sizes = mesh_vertices(b, p, 0)
    assert sizes == [4]
    assert np.allclose(P.min(0), [0, 0, 0]) and np.allclose(P.max(0), [2, 2, 2])
    assert strip_triangles(4, 4) == [(0, 1, 2), (2, 1, 3)]


def test_rejects_bad_tables_and_unknown_vtype():
    b = bytearray(_synthetic())
    bad = bytes(b[:12]) + struct.pack("<I", 999) + bytes(b[16:])
    with pytest.raises(ValueError):
        parse_pol(bad)
    b[16 + 64 + 44 + 6:16 + 64 + 44 + 8] = struct.pack("<H", 0x0FFF)
    with pytest.raises(ValueError):
        parse_pol(bytes(b))
    assert ge_layout(0x121)[0] == 12 and ge_layout(0x123)[0] == 20


@pytest.mark.parametrize("name", sorted(OWNED))
def test_owned_driver_models_decode_to_their_bboxes(name):
    b = _owned(name)
    p = parse_pol(b)
    assert (len(p.slots), len(p.meshes), len(p.strips)) == OWNED[name][3]
    assert p.vertex_end == len(b)
    for i, m in enumerate(p.meshes):
        P, N, U, sizes = mesh_vertices(b, p, i)
        span = (np.array(m.bmax) - np.array(m.bmin)).max() or 1.0  # POLPP2A has a zero-extent mesh
        assert np.abs(P.min(0) - m.bmin).max() / span < 2e-3
        assert np.abs(P.max(0) - m.bmax).max() / span < 2e-3
        assert sum(sizes) == len(P)
