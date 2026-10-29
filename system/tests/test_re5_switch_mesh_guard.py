"""RE5 Switch mesh_guard: the left stick's way probed on the nav mesh before he walks into a wall.

A two-triangle mesh (like test_re5_switch_native_nav's) with a wall on one side:
the bot holding lup toward the wall is steered to the clear way; the bot holding
lup along the open floor is left alone.
"""
import math
import struct

from gbox.mercs.titles import re5_switch_wall as W
from gbox.mercs.titles import re5_nav


class _Guest:
    """Minimal guest memory for the mesh_guard tests (two triangles, one wall)."""

    def __init__(self):
        self.base = 0x3CA89C3000
        self.heap = 0x5D00000000
        self.regions = {self.base: bytearray(0x2800000), self.heap: bytearray(0x400000)}
        self.next_heap = self.heap

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


def _two_triangle_mesh() -> re5_nav.NavMesh:
    """Two triangles sharing the diagonal edge from (500,0) to (0,500):
    tri 0 = (0,1,2) with vertices (0,0),(500,0),(0,500) - the lower-left half;
    tri 1 = (1,3,2) with vertices (500,0),(500,500),(0,500) - the upper-right half.
    The shared edge 1-2 (v1-v2 of tri 0, v2-v0 of tri 1) is open; the outer edges are walls."""
    g = _Guest()
    pts = g.alloc(4 * 16)
    for i, (x, y, z) in enumerate([(0, 0, 0), (500, 0, 0), (0, 0, 500), (500, 0, 500)]):
        g.put(pts + 16 * i, struct.pack("<3f", x, y, z))
    verts0 = g.alloc(12)
    g.put(verts0, struct.pack("<3I", 0, 1, 2))
    verts1 = g.alloc(12)
    g.put(verts1, struct.pack("<3I", 1, 3, 2))
    # tri 0 = (0,1,2): edge 1 = v1-v2 = (500,0)-(0,500), shared with tri 1
    # tri 1 = (1,3,2): edge 2 = v2-v0 = (0,500)-(500,0), shared with tri 0
    links0 = g.alloc(16)
    g.put(links0, struct.pack("<IIIf", 1, 0, 1, 1.0))       # tri 0 -> tri 1 across edge 1 (v1-v2)
    links1 = g.alloc(16)
    g.put(links1, struct.pack("<IIIf", 0, 0, 2, 1.0))       # tri 1 -> tri 0 across edge 2 (v2-v0)
    nodes = g.alloc(2 * 0x20)
    g.put(nodes + 0x00, bytes(0x10))
    g.i32(nodes + 0x10, verts0 - g.heap)
    g.i32(nodes + 0x14, 3)
    g.i32(nodes + 0x18, links0 - g.heap)
    g.i32(nodes + 0x1C, 1)
    g.put(nodes + 0x20 + 0x00, bytes(0x10))
    g.i32(nodes + 0x20 + 0x10, verts1 - g.heap)
    g.i32(nodes + 0x20 + 0x14, 3)
    g.i32(nodes + 0x20 + 0x18, links1 - g.heap)
    g.i32(nodes + 0x20 + 0x1C, 1)
    points = [struct.unpack("<3f", g.rd(pts + 16 * i, 12)) for i in range(4)]
    tris = [(0, 1, 2), (1, 3, 2)]
    links = [[(1, 1, 1.0)], [(0, 2, 1.0)]]
    return re5_nav.NavMesh(points, tris, links)


class _Bot:
    """Minimal bot stub for mesh_guard."""

    def __init__(self):
        self.stats = {}
        self.in_hold = False
        self.down = False
        self.doing = "walk"


def _snap(mesh, pos, rot=0.0, yaw=0.0):
    return {
        "player": {"pos": pos, "rot": rot},
        "camera": {"yaw": yaw},
        "navmesh": mesh,
        "mercenaries_phase": 1,  # PHASE_PLAYING
    }


# --- mesh_guard ----------------------------------------------------------------


def test_mesh_guard_steers_off_the_wall():
    """Holding lup straight at a mesh boundary (no shared edge) turns to a clear way."""
    mesh = _two_triangle_mesh()
    bot = _Bot()
    # At (100, 0, 100) inside tri 0 (x+z=200 < 500).  With yaw=pi, lup = -Z (south, toward z=0 wall).
    snap = _snap(mesh, (100.0, 0.0, 100.0), rot=0.0, yaw=math.pi)
    action = {"hold": ("lup",)}
    out = W.mesh_guard(bot, snap, action)
    # The straight way (-Z, toward edge 0-1 at z=0) is a wall; mesh_guard should steer.
    assert out["hold"] != ("lup",)
    assert bot.stats.get("mesh_steers", 0) >= 1


def test_mesh_guard_leaves_open_floor_alone():
    """Holding lup along the open floor (toward the shared edge) is not touched."""
    mesh = _two_triangle_mesh()
    bot = _Bot()
    # At (100, 0, 100) inside tri 0.  With yaw=pi/4, lup = northeast, toward the shared edge (open).
    snap = _snap(mesh, (100.0, 0.0, 100.0), rot=0.0, yaw=math.pi / 4)
    action = {"hold": ("lup",)}
    out = W.mesh_guard(bot, snap, action)
    assert out["hold"] == ("lup",)
    assert bot.stats.get("mesh_steers", 0) == 0


def test_mesh_guard_no_mesh_no_crash():
    """No navmesh in the snap: the action passes through unchanged."""
    bot = _Bot()
    snap = _snap(None, (100.0, 0.0, 100.0))
    action = {"hold": ("lup",)}
    out = W.mesh_guard(bot, snap, action)
    assert out["hold"] == ("lup",)


def test_mesh_guard_aiming_not_steered():
    """ZL/ZR (aiming) is never steered."""
    mesh = _two_triangle_mesh()
    bot = _Bot()
    snap = _snap(mesh, (100.0, 0.0, 100.0), rot=0.0, yaw=math.pi)
    action = {"hold": ("lup", "zl")}
    out = W.mesh_guard(bot, snap, action)
    assert out["hold"] == ("lup", "zl")


def test_mesh_guard_not_playing():
    """Outside PHASE_PLAYING the guard is off."""
    mesh = _two_triangle_mesh()
    bot = _Bot()
    snap = _snap(mesh, (100.0, 0.0, 100.0))
    snap["mercenaries_phase"] = 0  # intro
    action = {"hold": ("lup",)}
    out = W.mesh_guard(bot, snap, action)
    assert out["hold"] == ("lup",)


def test_mesh_guard_blocked_when_no_clear_way():
    """When every turn is still a wall, mesh_blocked is counted and the action passes."""
    # A single small triangle: every edge is a wall, and the probe (150cm) always leaves it.
    pts = [(0, 0, 0), (100, 0, 0), (50, 0, 100)]
    tris = [(0, 1, 2)]
    links = [[]]
    mesh = re5_nav.NavMesh(pts, tris, links)
    bot = _Bot()
    snap = _snap(mesh, (50.0, 0.0, 50.0), rot=0.0, yaw=0.0)
    action = {"hold": ("lup",)}
    out = W.mesh_guard(bot, snap, action)
    assert bot.stats.get("mesh_blocked", 0) == 1
    assert out["hold"] == ("lup",)


# --- stick_heading ----------------------------------------------------------------


def test_stick_heading_cardinals():
    assert W.stick_heading(("lup",), 0.0) == 0.0
    assert W.stick_heading(("lup",), math.pi / 2) == math.pi / 2
    assert W.stick_heading(("lleft",), 0.0) == math.pi / 2
    assert W.stick_heading(("ldown",), 0.0) == math.pi
    assert W.stick_heading(("lright",), 0.0) == -math.pi / 2


def test_stick_heading_diagonal():
    h = W.stick_heading(("lleft", "lup"), 0.0)
    assert abs(h - math.pi / 4) < 1e-9


def test_stick_heading_no_stick():
    assert W.stick_heading((), 0.0) is None
    assert W.stick_heading(("zl",), 0.0) is None
