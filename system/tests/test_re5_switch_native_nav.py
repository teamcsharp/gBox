"""RE5 Switch native navmesh reader (re5_switch_native_nav) on a synthetic 64-bit guest.

Lays out a minimal sAI -> cAIPathFinding -> rNavigationMesh chain with two triangles
sharing an edge, then verifies that read() decodes it into a re5_nav.NavMesh whose
A* route() walks through the shared-edge midpoint.

Pointer model follows re6_switch.navmesh: the navmesh record stores 32-bit pool
offsets for points/nodes/links; ``ptr_base`` (defaults to ``m.base``) is added to
each to form the full guest address.
"""
import struct

import pytest

from gbox.mercs.titles import re5_switch_native_nav as NAV
from gbox.mercs.titles import re5_nav

BASE = 0x3CA89C3000
HEAP = 0x5D00000000


class Guest:
    """Two-row guest memory like the other Switch tests (main image + heap)."""

    MAIN_SIZE, HEAP_SIZE = 0x2800000, 0x400000

    def __init__(self):
        self.regions = {BASE: bytearray(self.MAIN_SIZE), HEAP: bytearray(self.HEAP_SIZE)}
        self.next_heap = HEAP

    @property
    def base(self):
        return BASE

    def _region(self, a, n):
        for s, buf in self.regions.items():
            if s <= a and a + n <= s + len(buf):
                return s, buf
        raise ValueError(f"unmapped {a:#x}")

    def put(self, a, data: bytes):
        s, buf = self._region(a, len(data))
        buf[a - s:a - s + len(data)] = data

    def q(self, a, v):
        self.put(a, struct.pack("<Q", v))

    def i32(self, a, v):
        self.put(a, struct.pack("<I", v))

    def rd(self, a, n):
        s, buf = self._region(a, n)
        return bytes(buf[a - s:a - s + n])

    def alloc(self, n):
        a = self.next_heap
        self.next_heap += (n + 0xFFF) & ~0xFFF
        return a


def two_triangle_guest() -> tuple[Guest, int]:
    """sAI -> cAIPathFinding -> rNavigationMesh with two triangles sharing an edge.

    Triangle 0: vertices 0,1,2.  Triangle 1: vertices 1,3,2 (shares edge 1-2).
    The shared edge's midpoint is the expected A* waypoint.
    """
    g = Guest()

    # points: 4 vertices, 16 bytes each (x, y, z, pad)
    pts = g.alloc(4 * 16)
    for i, (x, y, z) in enumerate([(0, 0, 0), (100, 0, 0), (100, 0, 100), (0, 0, 100)]):
        g.put(pts + 16 * i, struct.pack("<3f", x, y, z))

    # vertex indices for each triangle (3 x u32)
    verts0 = g.alloc(12)
    g.put(verts0, struct.pack("<3I", 0, 1, 2))
    verts1 = g.alloc(12)
    g.put(verts1, struct.pack("<3I", 1, 3, 2))

    # links: triangle 0 has one link to triangle 1 across edge 0 (v0-v1);
    # triangle 1 has one link back to triangle 0 across edge 2 (v2-v0).
    # link record: neighbour u32, pad u32, edge u32, cost f32 (16 bytes)
    links0 = g.alloc(16)
    g.put(links0, struct.pack("<IIIf", 1, 0, 0, 1.0))
    links1 = g.alloc(16)
    g.put(links1, struct.pack("<IIIf", 0, 0, 2, 1.0))

    # nodes: 2 records, 0x20 bytes each
    # +0x10 vertex ptr (4B pool offset) + count (4B), +0x18 link ptr + count
    nodes = g.alloc(2 * 0x20)
    g.put(nodes + 0x00, bytes(0x10))                    # header pad
    g.i32(nodes + 0x10, verts0 - HEAP)                  # tri 0 vertex indices
    g.i32(nodes + 0x14, 3)                              # tri 0 vert count
    g.i32(nodes + 0x18, links0 - HEAP)                  # tri 0 links (pool offset)
    g.i32(nodes + 0x1C, 1)                              # tri 0 link count
    g.put(nodes + 0x20 + 0x00, bytes(0x10))
    g.i32(nodes + 0x20 + 0x10, verts1 - HEAP)           # tri 1 vertex indices
    g.i32(nodes + 0x20 + 0x14, 3)
    g.i32(nodes + 0x20 + 0x18, links1 - HEAP)           # tri 1 links
    g.i32(nodes + 0x20 + 0x1C, 1)

    # rNavigationMesh record -- 32-bit pool offsets like re6_switch.navmesh
    nav = g.alloc(0x100)
    g.put(nav + 0x00, bytes(NAV.NM_POINTS))              # header pad up to +0xA0
    g.i32(nav + NAV.NM_POINTS, pts - HEAP)               # points pool offset
    g.i32(nav + NAV.NM_NPOINTS, 4)
    g.i32(nav + NAV.NM_NODES, nodes - HEAP)              # nodes pool offset
    g.i32(nav + NAV.NM_NNODES, 2)

    # cAIPathFinding
    pf = g.alloc(0x40)
    g.put(pf + 0x00, bytes(NAV.PF_NAVMESH))
    g.q(pf + NAV.PF_NAVMESH, nav)

    # sAI singleton
    sai = g.alloc(0x40)
    g.put(sai + 0x00, bytes(NAV.AI_PATHFINDING))
    g.q(sai + NAV.AI_PATHFINDING, pf)

    return g, sai


# --- read() ------------------------------------------------------------------


def test_read_decodes_two_triangles():
    g, sai = two_triangle_guest()
    mesh = NAV.read(g, s_ai=sai, ptr_base=HEAP)
    assert mesh is not None
    assert len(mesh.points) == 4
    assert len(mesh.tris) == 2
    # triangle 0 = (0,1,2), triangle 1 = (1,3,2) -- winding differs but both share edge 1-2
    assert mesh.tris[0] == (0, 1, 2)
    assert mesh.tris[1] == (1, 3, 2)
    # each triangle has one link
    assert len(mesh.links[0]) == 1
    assert len(mesh.links[1]) == 1
    assert mesh.links[0][0][0] == 1      # tri 0 -> tri 1
    assert mesh.links[1][0][0] == 0      # tri 1 -> tri 0


def test_read_returns_none_without_sai():
    g, _ = two_triangle_guest()
    assert NAV.read(g) is None            # S_AI not set
    assert NAV.read(g, s_ai=0) is None    # invalid pointer
    assert NAV.read(g, s_ai=BASE + 0x100) is None   # unmapped


def test_read_uses_module_level_s_ai(monkeypatch):
    g, sai = two_triangle_guest()
    monkeypatch.setattr(NAV, "S_AI", sai)
    mesh = NAV.read(g, ptr_base=HEAP)
    assert mesh is not None and len(mesh.tris) == 2


def test_read_caches_by_source(monkeypatch):
    g, sai = two_triangle_guest()
    cache: dict = {}
    m1 = NAV.read(g, cache=cache, s_ai=sai, ptr_base=HEAP)
    assert m1 is not None
    # second call with same source returns the cached object
    m2 = NAV.read(g, cache=cache, s_ai=sai, ptr_base=HEAP)
    assert m2 is m1


# --- route() through the decoded mesh ----------------------------------------


def test_route_walks_the_shared_edge():
    g, sai = two_triangle_guest()
    mesh = NAV.read(g, s_ai=sai, ptr_base=HEAP)
    assert mesh is not None
    # start inside triangle 0 at (10, 0, 10), goal inside triangle 1 at (90, 0, 90)
    route = mesh.route((10.0, 0.0, 10.0), (90.0, 0.0, 90.0))
    assert route is not None
    # the route crosses the shared edge v1-v2 whose midpoint is (100, 0, 50);
    # with pull=False the waypoints are the edge midpoints then the goal
    route2 = mesh.route((10.0, 0.0, 10.0), (90.0, 0.0, 90.0), pull=False)
    assert route2 is not None
    # last waypoint is the goal itself
    assert route2[-1] == (90.0, 0.0, 90.0)


# --- find_sai() ----------------------------------------------------------------


def test_find_sai_locates_the_singleton():
    g, sai = two_triangle_guest()
    # place the sAI pointer inside main's statics region
    static_off = 0x1D00000
    g.q(BASE + static_off, sai)
    found = NAV.find_sai(g, BASE, statics_lo=static_off, statics_hi=static_off + 8)
    assert found == sai


def test_find_sai_returns_none_when_absent():
    g, _ = two_triangle_guest()
    found = NAV.find_sai(g, BASE, statics_lo=0x1D00000, statics_hi=0x1D00080)
    assert found is None


# --- navmesh_available() --------------------------------------------------------


def test_navmesh_available_reflects_s_ai():
    assert NAV.navmesh_available() is False
    original = NAV.S_AI
    try:
        NAV.S_AI = HEAP + 0x1000
        assert NAV.navmesh_available() is True
    finally:
        NAV.S_AI = original
