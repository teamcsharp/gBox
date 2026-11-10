"""RE4 Switch room collision -> stage floor mesh (gbox.re4_switch_nav) and the mesh the bot routes on
(gbox.mercs.titles.re4_nav): the Switch layouts read as the GameCube's, the builder on a synthetic grid, routes,
crossings, units, line of sight, the stage picker, and the four committed stage files."""
import math
import struct

import pytest

import re4_nav_fixture as F
from gbox import re4_navmap as N
from gbox import re4_switch_nav as B
from gbox.mercs.titles import re4_nav, re5_nav


# --- the Switch files in the GameCube layout ---

def _switch_sat(V, T, normals, attrs) -> bytes:
    """A Switch-layout SAT: 80 01 79 ff, body at 8, little-endian tables (edge vectors zero)."""
    nv, nn, nt = len(V), len(normals), len(T)
    ne = 3 * nt
    body = struct.pack("<10H", 0x20, nv, nn, ne, 0, nt, 0, 0, 0, 0)
    floats = [c for v in V for c in v] + [c for n in normals for c in n] + [0.0] * (3 * ne)
    tris = b"".join(struct.pack("<10H", a, b, c, n, 0, 0, 0, 0, hi, lo) for (a, b, c), n, (hi, lo) in
                    zip(T, range(nt), attrs))
    return b"\x80\x01" + struct.pack("<HI", 0xFF79, 8) + body + struct.pack(f"<{len(floats)}f", *floats) + tris + bytes(32)


def test_a_switch_sat_reads_as_the_gamecube_sat():
    V = [(0.0, 0.0, 0.0), (1000.0, 0.0, 0.0), (0.0, 0.0, 1000.0), (0.0, 1000.0, 0.0)]
    T = [(0, 2, 1), (0, 1, 3)]
    normals = [(0.0, 1.0, 0.0), (0.0, 0.0, -1.0)]
    col = N.sat_read(B.sat_to_gc(_switch_sat(V, T, normals, [(0x4000, 0), (0xE000, 0x20)])))
    assert col["verts"].tolist() == [list(v) for v in V]
    assert col["tris"].tolist() == [list(t) for t in T]
    assert col["normals"][:, 1].tolist() == [1.0, 0.0]
    assert [int(a) for a in col["attr"]] == [0x40000000, 0xE0000020]       # hi << 16 | lo, as on the GameCube


def test_a_switch_sat_is_refused_when_its_magic_is_not_measured():
    with pytest.raises(B.NavBuildError):
        B.sat_to_gc(b"\x00" * 64)


def test_switch_aev_and_ita_entries_read_as_the_gamecube_events():
    aev = bytearray(b"AEV\0" + struct.pack("<HH", 0x104, 1) + bytes(8) + bytes(B.AEV_BYTES))
    e = 16
    struct.pack_into("<2f", aev, e + 0x0C, 0.0, 1000.0)
    struct.pack_into("<8f", aev, e + 0x18, 0, 0, 100, 0, 100, 100, 0, 100)
    aev[e + 0x39], aev[e + 0x3A], aev[e + 0x3C] = 0x10, 7, 2               # a ladder, index 7, the action button
    struct.pack_into("<4f", aev, e + 0x70, 19197.0, 0.0, -6751.3, -0.3927)
    struct.pack_into("<b", aev, e + 0x80, 9)
    ita = bytearray(b"ITA\0" + struct.pack("<HH", 0x105, 1) + bytes(8) + bytes(B.ITA_BYTES))
    struct.pack_into("<3f", ita, e + 0x70, -22781.6, 31.0, -2687.9)
    struct.pack_into("<3H", ita, e + 0x94, 0x73, 60, 90)                    # Time Bonus, 90 s
    events = N.room_events(N.events_read(B.events_to_gc(bytes(aev), b"AEV\0"), b"AEV\0"),
                           N.events_read(B.events_to_gc(bytes(ita), b"ITA\0"), b"ITA\0"))
    ladder = next(x for x in events if x["kind"] == "ladder")
    assert ladder["pos"] == [19197.0, 0.0, -6751.3] and ladder["rungs"] == 9 and ladder["top"][1] == 9000.0
    assert ladder["trigger"] == "action" and ladder["index"] == 7
    bonus = next(x for x in events if x["kind"] == "time_bonus")
    assert bonus["pos"] == [-22781.6, 31.0, -2687.9] and bonus["seconds"] == 90


def test_a_switch_set_list_reads_as_the_gamecube_list():
    row = bytearray(32)
    row[1], row[2] = 0x16, 3
    struct.pack_into("<H", row, 8, 1000)
    struct.pack_into("<3h", row, 0x0C, -313, 7, 2150)
    struct.pack_into("<H", row, 0x18, 0x400)
    got = N.esl_read(B.esl_to_gc(bytes(row)), 0x400)
    assert got[0]["em"] == 0x16 and got[0]["hp"] == 1000 and got[0]["pos"] == [-3130.0, 70.0, 21500.0]


# --- the builder on the synthetic stage ---

def test_the_mesh_covers_exactly_the_walkable_cells_and_shares_whole_edges():
    m = F.mesh_dict()
    pts, tris = m["points"], m["tris"]
    area = sum(abs((pts[b][0] - pts[a][0]) * (pts[c][2] - pts[a][2]) - (pts[c][0] - pts[a][0]) * (pts[b][2] - pts[a][2]))
               / 2 for a, b, c in tris)
    assert m["stats"]["walkable_cells"] == F.NX * F.NZ - (F.NZ - len(F.DOOR)) - F.WALL_X + 25
    assert area == pytest.approx(m["stats"]["walkable_cells"] * F.CELL ** 2)
    edges = {}
    for t, tri in enumerate(tris):
        for e in range(3):
            key = tuple(sorted((tri[e], tri[(e + 1) % 3])))
            edges.setdefault(key, []).append(t)
    assert max(len(v) for v in edges.values()) <= 2
    # no T-junction: no vertex lies inside another triangle's edge (re5_nav links need shared vertex indices)
    for (a, b) in edges:
        ax, az, bx, bz = pts[a][0], pts[a][2], pts[b][0], pts[b][2]
        length2 = (bx - ax) ** 2 + (bz - az) ** 2
        for k, p in enumerate(pts):
            if k in (a, b) or abs(p[1] - pts[a][1]) > 1:
                continue
            cross = (bx - ax) * (p[2] - az) - (bz - az) * (p[0] - ax)
            along = (p[0] - ax) * (bx - ax) + (p[2] - az) * (bz - az)
            assert not (abs(cross) < 1e-6 and 0 < along < length2), (a, b, k)


def test_heights_come_from_the_floor_and_the_platform_is_its_own_storey():
    m = F.mesh_dict()
    ys = sorted({round(p[1]) for p in m["points"]})
    assert ys == [0, 3000]


def test_the_fence_and_the_ladder_become_crossings_with_their_own_portals():
    m = F.mesh_dict()
    vaults = [c for c in m["crossings"] if c["kind"] == "vault"]
    ladders = [c for c in m["crossings"] if c["kind"] == "ladder"]
    assert len(vaults) == 2                                    # one per rectangle pair, both ways across the fence
    for c in vaults:
        assert 800 <= c["portal"][2] <= 1000                   # on the fence strip
        assert {c["approach"][2] < 800, c["landing"][2] > 1000} in ({True}, {False})
        assert c["edge"] >= 3 and c["verified"] is False
    up = next(c for c in ladders if c["direction"] == "up")
    assert up["approach"][1] == 0 and up["landing"][1] == F.PLATFORM_Y
    assert up["portal"][2] == pytest.approx(F.LADDER["pos"][2] + B.LADDER_REACH)      # toward the ladder (facing +z)
    assert {c["direction"] for c in ladders} == {"up", "down"}
    assert len({c["edge"] for c in m["crossings"]}) == len(m["crossings"])


# --- the mesh (mm) ---

def test_a_route_through_the_door_keeps_off_the_jambs_and_never_crosses_the_wall():
    m = F.mesh()
    r = m.route((1000.0, 0.0, 2600.0), (5000.0, 0.0, 2600.0), clearance=350.0)
    assert r is not None and r[-1] == (5000.0, 0.0, 2600.0)
    door = [q for q in r if 2990 <= q[0] <= 3210]
    assert door and all(abs(q[2] - 1900.0) < 1.0 for q in door)    # a 600 mm door: crossed at its middle
    pts = [(1000.0, 0.0, 2600.0)] + list(r)
    for a, b in zip(pts, pts[1:]):                           # every 50 mm of the path on the floor
        n = max(1, int(math.dist(a, b) / 50))
        for k in range(n + 1):
            x, z = a[0] + (b[0] - a[0]) * k / n, a[2] + (b[2] - a[2]) * k / n
            assert m.floor_y(x, z, 0.0) is not None, (x, z)


def test_the_fence_is_crossed_by_a_traversal_and_the_platform_by_the_ladder():
    m = F.mesh()
    r = m.route((1000.0, 0.0, 400.0), (1000.0, 0.0, 2400.0), clearance=350.0)
    hops = [q for q in r if isinstance(q, re5_nav.Traversal)]
    assert len(hops) == 1
    assert hops[0].approach[2] < 800 < 1000 < hops[0][2] and 800 <= hops[0].portal[2] <= 1000
    r = m.route((4500.0, 0.0, 1500.0), (4500.0, F.PLATFORM_Y, 3300.0), clearance=350.0)
    hop = next(q for q in r if isinstance(q, re5_nav.Traversal))
    assert hop.approach[1] == 0.0 and hop[1] == F.PLATFORM_Y and r[-1][1] == F.PLATFORM_Y
    # refused (route(avoid=)), the platform has no other way up
    assert m.route((4500.0, 0.0, 1500.0), (4500.0, F.PLATFORM_Y, 3300.0), avoid=[hop.portal]) is None


def test_floor_membership_is_in_mm_with_re5s_tolerances():
    m = F.mesh()
    assert m.member((1130.0, 30.0, 2370.0)) is not None             # 3 cm over the floor
    assert m.member((1130.0, 600.0, 2370.0)) is None                # 60 cm over it (re5_nav: 40 cm)
    assert m.member((3100.0, 0.0, 1000.0)) is None                  # inside the wall
    assert m.find((4500.0, 3050.0, 3300.0), floor_only=True) is not None
    assert m.floor_y(4500.0, 3300.0, 2500.0) == pytest.approx(F.PLATFORM_Y)
    assert m.floor_y(4500.0, 3300.0, 100.0) == pytest.approx(0.0)


def test_clear_segment_is_the_shot_line_against_the_walls():
    m = F.mesh()
    assert m.clear_segment((1000.0, 0.0, 1900.0), (5000.0, 0.0, 1900.0))      # through the door
    assert not m.clear_segment((1000.0, 0.0, 1000.0), (5000.0, 0.0, 1000.0))  # through the wall
    assert m.clear_segment((1000.0, 0.0, 400.0), (1000.0, 0.0, 2000.0))       # over the 1 m fence, chest high
    blocker = re4_nav.Mesh(m.points, m.tris, walls=[[3000, 0, 3000, 4000, 0, 2600, re4_nav.BLOCKER_BIT]])
    assert blocker.clear_segment((1000.0, 0.0, 1000.0), (5000.0, 0.0, 1000.0))  # an invisible blocker passes shots


def test_route_lengths_and_the_rim_only_clearance():
    m = F.mesh()
    d = m.route_length((500.0, 0.0, 3500.0), (2500.0, 0.0, 3500.0))
    assert d == pytest.approx(2000.0)                             # open floor: the straight line
    r = m.route((500.0, 0.0, 3500.0), (2500.0, 0.0, 3500.0), clearance=350.0)
    assert r == [(2500.0, 0.0, 3500.0)] or len(r) <= 2            # no corner pinned on an inner rectangle vertex


def test_the_picker_takes_a_hint_then_the_floor_and_keeps_its_stage(tmp_path):
    import json
    (tmp_path / "r400.json").write_text(json.dumps(F.stage_json("r400")))
    (tmp_path / "r402.json").write_text(json.dumps(F.stage_json("r402", shift=100000.0)))
    pick = re4_nav.Picker(tmp_path, rooms=("r400", "r402"))
    assert pick.pick({"room": 0x0402}).room == "r402"
    pick = re4_nav.Picker(tmp_path, rooms=("r400", "r402"))
    on400 = {"player": {"pos": (1100.0, 0.0, 2350.0)}}
    on402 = {"player": {"pos": (101100.0, 0.0, 2350.0)}}
    assert pick.pick(on400).room == "r400"
    for _ in range(re4_nav.SWITCH_MISSES - 1):                    # a few frames off its floor: the stage holds
        assert pick.pick(on402).room == "r400"
    assert pick.pick(on402).room == "r402"
    assert pick.pick({"player": None}).room == "r402"             # no player: the stage in force
    assert re4_nav.room_of("Castle") == "r402" and re4_nav.room_of(3) == "r404" and re4_nav.room_of(0x0300) is None
    snap = {"stage_name": "Village", "nav": None}
    re4_nav.attach(snap, re4_nav.Picker(tmp_path, rooms=("r400",)))
    assert snap["nav"].room == "r400" and snap["nav"].units == "mm"


# --- the four committed stage files ---

@pytest.mark.parametrize("room", sorted(re4_nav.ROOMS))
def test_the_committed_stage_meshes_load_and_hold_one_playable_floor(room):
    data = __import__("json").loads((re4_nav.DATA_DIR / f"{room}.json").read_text(encoding="utf-8"))
    assert data["format"] == B.FORMAT and data["units"] == "mm" and data["stage"] == re4_nav.ROOMS[room]
    m = re4_nav.from_json(data)
    assert len(m.points) == data["counts"]["points"] and len(m.tris) == data["counts"]["tris"]
    assert len(m.crossing_rows) == data["counts"]["crossings"] and len(m.walls) == data["counts"]["walls"]
    sizes = {}
    for i in range(len(m.tris)):
        sizes[m.component(i)] = sizes.get(m.component(i), 0) + 1
    assert max(sizes.values()) >= 0.99 * len(m.tris)                # the playable floor is one piece
    big = max(sizes, key=sizes.get)
    members = [i for i in range(len(m.tris)) if m.component(i) == big]
    a, b = members[0], members[-1]
    assert m.route(m.centre[a], m.centre[b], clearance=350.0) is not None
    lo = data["bounds"]
    assert all(lo["x"][0] <= p[0] <= lo["x"][1] and lo["z"][0] <= p[2] <= lo["z"][1] for p in m.points[:50])
