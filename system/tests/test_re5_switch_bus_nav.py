"""RE5 Switch: out of the bus (Public Assembly, live 2026-11-09 21:30 UTC: the operator's mark 5 m east of the bus's back
wall, the bot ran the bus's length east and west for two minutes - 471,50,-273 -> 68,50,-88 -> 503,50,-282 -> 82,50,-90
... - and never took its door; "the character is stuck in the bus again", "the bot should never stand still").

The stage's own mesh (system/tests/fixtures/tactical_map/BLUS30491-public-assembly.stage.json: the PS3 and the Switch
layouts are the same points, triangles and walls - only the key's title differs) says what the bus is: ten floor
triangles at y 48-51 (an interior 7.6 m long and 2.5 m wide, its axis heading 120 deg), closed by walls at both short
ends, with ONE opening on the mesh - the 63 cm edge (475,50,-97)-(529,48,-130) on its north side, 2.2 m from the east
end, from which two ramp triangles (centres y 35 and y 21) step 43 cm down to the ground (y 7) through a 25 cm outer edge
(524,7,-65)-(547,7,-75). The two "H" marks of the tactical map near the bus are not its doors: they are the steep faces
that climb from the ground onto the bus ROOF (y 300): (264, 68, y -1..299) and (724, -306, y 45..304).

Here the walker is driven tick by tick on that mesh (and on a synthetic bus whose doors are action links) by a
kinematic player: the sticks move him the way the bot's own model assumes (forward along his facing at a walk, B a run,
the right stick turning him at TURN_SPEED_DEG_S, the left stick's other directions a step that way), the mesh's floor
is where he can stand, its wall edges stop him (he slides), and an action link shows the game's prompt at its portal
and lands him on the other floor when it is pressed. A model, not the game: what it reproduces is the bot's own
reasoning, not RE5's collision."""
import json
import math
from pathlib import Path

import pytest

from gbox.mercs.titles import re5_switch as R
from gbox.mercs.titles import re5_switch_prompt
from gbox.mercs.titles.re5_nav import NavMesh

STAGE = Path(__file__).parent / "fixtures" / "tactical_map" / "BLUS30491-public-assembly.stage.json"
BUS_TRIS = (731, 817, 732, 733, 658, 659, 657, 734, 735, 730)          # the interior, west to east
DOOR_EDGE = ((475.0, 50.0, -97.0), (529.0, 48.0, -130.0))               # the only opening on the mesh
GOAL_EAST = (989.0, 50.0, -441.0)                                        # the operator's mark, 21:30:34 UTC
DT = 1.0 / 30.0
WALK, RUN, BACK = 170.0, 400.0, 110.0                                    # cm/s (the run: 3.9 m in 1 s in the goal log)
_STAGE_MESH = None


def stage_mesh() -> NavMesh:
    """The whole Public Assembly mesh from the tactical layout: links are its shared edges that are not walls."""
    global _STAGE_MESH
    if _STAGE_MESH is None:
        d = json.loads(STAGE.read_text(encoding="utf-8"))
        P, T, W = d["points"], d["tris"], d["walls"]
        pts = [(float(P[i]), float(P[i + 1]), float(P[i + 2])) for i in range(0, len(P), 3)]
        tris = [(T[i], T[i + 1], T[i + 2]) for i in range(0, len(T), 3)]
        walls = {frozenset((W[i], W[i + 1])) for i in range(0, len(W), 2)}
        _STAGE_MESH = NavMesh(pts, tris, links_of(pts, tris, walls))
    return _STAGE_MESH


def links_of(pts, tris, walls=frozenset()) -> list:
    by_edge = {}
    for i, t in enumerate(tris):
        for e in range(3):
            by_edge.setdefault(frozenset((t[e], t[(e + 1) % 3])), []).append(i)
    links = [[] for _ in tris]
    for i, t in enumerate(tris):
        for e in range(3):
            key = frozenset((t[e], t[(e + 1) % 3]))
            if key in walls:
                continue
            links[i] += [(j, e, 0.0) for j in by_edge[key] if j != i]
    return links


def bus_with_links(west="usable", east="usable") -> tuple:
    """A synthetic bus: a 250 x 800 cm floor at y 50 along +x, a door at each short end that is an action link of the
    mesh (a steep face 40 cm long dropping 150 cm to the ground, as the game's ledges are drawn), the ground at y -100
    around. `west` / `east`: "usable" (the game shows its prompt there), "majini" (the AI's link only: no prompt, no
    way through), "wall" (no door). -> (mesh, links) with links [{"portal", "landing", "usable"}] for the World."""
    pts, tris = [], []

    def quad(a, b, c, d):
        base = len(pts)
        pts.extend([a, b, c, d])
        tris.append((base, base + 1, base + 2))
        tris.append((base, base + 2, base + 3))
        return len(tris) - 2, len(tris) - 1
    # the interior: four quads along x, so the mesh has corners to pull a route round
    for i in range(4):
        x0, x1 = i * 200.0, (i + 1) * 200.0
        quad((x0, 50.0, 0.0), (x1, 50.0, 0.0), (x1, 50.0, 250.0), (x0, 50.0, 250.0))
    links = []
    for side, kind in (("west", west), ("east", east)):
        if kind == "wall":
            continue
        xin = 0.0 if side == "west" else 800.0
        d = -1.0 if side == "west" else 1.0
        xout = xin + d * 40.0
        # the steep face: the bus's end edge (y 50) down to the ground's edge (y -100), 40 cm out
        quad((xin, 50.0, 0.0), (xin, 50.0, 250.0), (xout, -100.0, 250.0), (xout, -100.0, 0.0))
        # the ground beyond: 6 m of floor
        quad((xout, -100.0, 0.0), (xout, -100.0, 250.0), (xout + d * 600.0, -100.0, 250.0), (xout + d * 600.0, -100.0, 0.0))
        links.append({"portal": (xin, 50.0, 125.0), "landing": (xout + d * 60.0, -100.0, 125.0),
                      "usable": kind == "usable", "side": side})
    # the ground round the bus's south side joins the two ends (the other door is a real way round)
    quad((-640.0, -100.0, 0.0), (-40.0, -100.0, 0.0), (-40.0, -100.0, -300.0), (-640.0, -100.0, -300.0))
    quad((-40.0, -100.0, 0.0), (840.0, -100.0, 0.0), (840.0, -100.0, -300.0), (-40.0, -100.0, -300.0))
    quad((840.0, -100.0, 0.0), (1440.0, -100.0, 0.0), (1440.0, -100.0, -300.0), (840.0, -100.0, -300.0))
    # weld shared vertices (quads were built with their own copies)
    index, merged, remap = {}, [], {}
    for i, p in enumerate(pts):
        key = tuple(round(v, 3) for v in p)
        if key not in index:
            index[key] = len(merged)
            merged.append(p)
        remap[i] = index[key]
    tris = [tuple(remap[v] for v in t) for t in tris]
    return NavMesh(merged, tris, links_of(merged, tris)), links


def seg_dist(x, z, a, b) -> float:
    ax, az, bx, bz = a[0], a[2], b[0], b[2]
    dx, dz = bx - ax, bz - az
    L2 = dx * dx + dz * dz
    t = 0.0 if L2 == 0 else max(0.0, min(1.0, ((x - ax) * dx + (z - az) * dz) / L2))
    return math.hypot(x - (ax + t * dx), z - (az + t * dz))


class World:
    """The kinematic player on a NavMesh (see the module docstring)."""

    def __init__(self, mesh: NavMesh, pos, rot=0.0, links=(), prompt_r=90.0):
        self.mesh, self.pos, self.rot = mesh, list(pos), rot
        self.links, self.prompt_r = list(links), prompt_r
        self.prompt = None
        self.level_changes, self.presses = 0, 0
        self.t = 0.0
        self.walls = {}
        for i, t in enumerate(mesh.tris):
            if mesh.steep[i]:
                continue
            for e in range(3):
                a, b = mesh.points[t[e]], mesh.points[t[(e + 1) % 3]]
                shared = any(0 <= v < len(mesh.tris) and not mesh.steep[v]
                             and {t[e], t[(e + 1) % 3]} <= set(mesh.tris[v]) for v, _, _ in mesh.links[i])
                if shared:
                    continue
                for gx in range(int(math.floor(min(a[0], b[0]) / 400.0)), int(math.floor(max(a[0], b[0]) / 400.0)) + 1):
                    for gz in range(int(math.floor(min(a[2], b[2]) / 400.0)), int(math.floor(max(a[2], b[2]) / 400.0)) + 1):
                        self.walls.setdefault((gx, gz), []).append((a, b))

    def snap(self) -> dict:
        return {"player": {"ptr": 0x5D00001000, "pos": tuple(self.pos), "rot": self.rot, "hp": 1000, "hp_max": 1000,
                           "motion": 0, "aim_pitch": None},
                "enemies": [], "inventory": [], "kills": 0, "nav": self.mesh, "prompt": self.prompt,
                "laser": {"from": (0, 0, 0), "at": (0, 0, 0), "up": False}}

    def _free(self, x, z) -> bool:
        cell = (int(math.floor(x / 400.0)), int(math.floor(z / 400.0)))
        for gx in (cell[0] - 1, cell[0], cell[0] + 1):
            for gz in (cell[1] - 1, cell[1], cell[1] + 1):
                for a, b in self.walls.get((gx, gz), ()):
                    if seg_dist(x, z, a, b) < 1.0:
                        return False
        return True

    def _move(self, dx, dz) -> bool:
        for cx, cz in ((dx, dz), (dx, 0.0), (0.0, dz)):
            if cx == 0.0 and cz == 0.0:
                continue
            x, z = self.pos[0] + cx, self.pos[2] + cz
            tri = self.mesh.find((x, self.pos[1], z), floor_only=True, height_slack=60.0)
            if tri is None or not self._free(x, z):
                continue
            # no crossing a wall edge in one step either (the segment from here to there)
            mid = ((self.pos[0] + x) / 2, (self.pos[2] + z) / 2)
            if not self._free(*mid):
                continue
            self.pos = [x, self.mesh._height(tri, x, z), z]
            return True
        return False

    def step(self, hold) -> None:
        hold = set(hold or ())
        self.t += DT
        if self.prompt is not None and set(self.prompt["keys"]) <= hold:
            link = self.prompt["link"]
            self.pos, self.prompt = list(link["landing"]), None
            self.level_changes += 1
            self.presses += 1
            return
        if "rleft" in hold:
            self.rot = R.wrap(self.rot + math.radians(R.TURN_SPEED_DEG_S) * DT)
        if "rright" in hold:
            self.rot = R.wrap(self.rot - math.radians(R.TURN_SPEED_DEG_S) * DT)
        f = (1 if "lup" in hold else 0) - (1 if "ldown" in hold else 0)
        s = (1 if "lleft" in hold else 0) - (1 if "lright" in hold else 0)
        if f or s:
            h = self.rot + math.atan2(s, f)
            speed = RUN if (f > 0 and not s and "b" in hold) else BACK if f < 0 else WALK
            self._move(speed * DT * math.sin(h), speed * DT * math.cos(h))
        self.prompt = None
        for link in self.links:
            if not link["usable"]:
                continue
            px, py, pz = link["portal"]
            d = math.hypot(px - self.pos[0], pz - self.pos[2])
            facing = abs(R.wrap(R.heading(px - self.pos[0], pz - self.pos[2]) - self.rot))
            if d <= self.prompt_r and facing <= math.radians(70) and abs(py - self.pos[1]) <= 60.0:
                self.prompt = {"token": "press:y", "keys": ("y",), "button": 0x8000, "kind": re5_switch_prompt.KIND_PLAYER,
                               "mode": 1, "priority": 0, "key_index": 1, "label": 58, "owner": 0, "target": 0, "count": 1,
                               "link": link}
                break


def bot(clock) -> R.Bot:
    b = R.Bot(stats={}, clock=lambda: clock[0])
    b._round_started = b._round_t0 = 0.0
    b._start_facing_done = True
    return b


def mark(b, pos, now=0.0) -> None:
    """The operator's double click: a point goal."""
    g = b._goals()
    b.receive_map_goal({"round": g.round, "id": "bus-test", "kind": "point", "entity_id": 0, "pos": list(pos),
                        "label": "Go to the marked spot"})
    b._goals().received_at = now


def in_bus(mesh, pos) -> bool:
    tri = mesh.find(pos, floor_only=True, height_slack=60.0)
    return tri in BUS_TRIS


def drive(b, clock, world, ticks, until=None) -> dict:
    """Tick the bot on the world until `until(world)` or `ticks` run out. -> the trace: positions a tick, the ends of
    the bus visited (the west end x < 150, the east end x > 450 on the real bus), ticks taken, exited."""
    xs, holds, ends, last_end = [], [], [], None
    for k in range(ticks):
        clock[0] = k * DT
        snap = world.snap()
        act = b.tick(snap)
        world.step(act.get("hold"))
        xs.append(tuple(round(v) for v in world.pos))
        holds.append(",".join(act.get("hold") or ()))
        if until is not None and until(world):
            return {"ticks": k + 1, "done": True, "pos": xs, "holds": holds, "ends": ends}
        end = "W" if world.pos[0] < 150 else "E" if world.pos[0] > 450 else None
        if end is not None and end != last_end:
            ends.append((k, end))
            last_end = end
    return {"ticks": ticks, "done": False, "pos": xs, "holds": holds, "ends": ends}


@pytest.fixture(autouse=True)
def _quiet(monkeypatch, tmp_path):
    monkeypatch.setattr(R, "PS3_BRAIN", False)
    monkeypatch.setattr(R, "HEAL_ENABLED", False)
    monkeypatch.setattr(R, "MINES", False)
    monkeypatch.setattr(R, "DOOR_FILE", tmp_path / "door_spots.json")
    monkeypatch.setattr(R, "MAP_GOAL_LOG", tmp_path / "map-goals.log")


# --- the geometry, measured ---------------------------------------------------------------------------------------
def test_the_bus_on_the_stage_mesh_has_one_opening_and_the_H_marks_are_roof_climbs():
    mesh = stage_mesh()
    assert len(mesh.tris) == 2187 and sum(mesh.steep) == 151
    for pos in ((471.0, 50.0, -273.0), (503.0, 50.0, -282.0)):
        assert mesh.member(pos) == 734                         # the east end the bot kept returning to
    for pos in ((68.0, 50.0, -88.0), (82.0, 50.0, -90.0)):
        assert mesh.member(pos) == 732                         # ... and the west end
    inside = set(BUS_TRIS)
    openings = set()
    for i in BUS_TRIS:
        for v, edge, _ in mesh.links[i]:
            if v not in inside:
                openings.add((i, v, tuple(round(c) for c in mesh._portal(i, edge))))
    assert openings == {(657, 579, (502, 49, -114))}          # one door, on the north side near the east end
    assert all(abs(mesh.centre[i][1] - 50) < 3 for i in BUS_TRIS)
    assert round(mesh.centre[579][1]) == 35 and round(mesh.centre[578][1]) == 21   # the ramp down to the ground (y 7)
    assert not mesh.steep[579] and not mesh.steep[578]        # a plain floor crossing for route(): no Traversal
    # the roof climbs the tactical map draws as H: steep faces from the ground to y ~300, not into the bus
    assert mesh.steep[477] and mesh.steep[480]
    assert [round(mesh.points[v][1]) for v in mesh.tris[477]] == [299, -1, -1]
    assert [round(mesh.points[v][1]) for v in mesh.tris[480]] == [304, 47, 45]
    route = mesh.route((471.0, 50.0, -273.0), GOAL_EAST)
    assert route is not None and not any(hasattr(q, "approach") for q in route)
    assert tuple(round(v) for v in route[0]) == (547, 7, -75)   # out through the door's outer corner first
    assert mesh.route_length((471.0, 50.0, -273.0), GOAL_EAST) > 1.4 * math.dist((471.0, 50.0, -273.0), GOAL_EAST)


def test_the_funnel_keeps_its_corners_off_a_narrow_doors_jambs():
    from gbox.mercs.titles.re5_nav import shrink_portal
    a, b = DOOR_EDGE
    assert shrink_portal(a, b, 0.0) == (a, b)
    left, right = shrink_portal(a, b, 35.0)                   # 63 cm wide: both ends at the middle
    assert left == right and tuple(round(v) for v in left) == (502, 49, -114)
    left, right = shrink_portal((0.0, 0.0, 0.0), (200.0, 0.0, 0.0), 35.0)
    assert left == (35.0, 0.0, 0.0) and right == (165.0, 0.0, 0.0)
    mesh = stage_mesh()
    plain = [tuple(round(v) for v in q) for q in mesh.route((300.0, 50.0, -170.0), GOAL_EAST)]
    clear = [tuple(round(v) for v in q) for q in mesh.route((300.0, 50.0, -170.0), GOAL_EAST, clearance=35.0)]
    jambs = {(475, 50, -97), (529, 48, -130), (524, 7, -65), (547, 7, -75)}
    assert plain[0] in jambs                                   # main: the first corner is a jamb
    assert not jambs & set(clear)                              # with clearance: no corner on a jamb ...
    assert {(502, 49, -114), (536, 7, -70)} & set(clear)       # ... the door crossed at its middle


# --- the walker, before and after ----------------------------------------------------------------------------------
MAIN = {"MESH_LOOKAHEAD": False, "MESH_CORNER_CLEARANCE_CM": 0.0, "WALL_ROUTE_YIELD": False, "WALL_GOV_GOAL": False}
MIDDLE = ((300.0, 50.0, -170.0), 120.0)


def run_bus(monkeypatch, start, rot_deg, flags=None, ticks=30 * 60):
    for k, v in (flags or {}).items():
        monkeypatch.setattr(R, k, v)
    mesh = stage_mesh()
    clock = [0.0]
    b = bot(clock)
    w = World(mesh, start, rot=math.radians(rot_deg))
    mark(b, GOAL_EAST)
    tr = drive(b, clock, w, ticks, until=lambda w: not in_bus(mesh, w.pos))
    return b, w, tr


def longest_stand(tr) -> int:
    """The longest run of ticks with no left-stick key held (the right stick alone, or nothing)."""
    best = run = 0
    for hold in tr["holds"]:
        if set(hold.split(",")) & {"lup", "ldown", "lleft", "lright", "y", "a"}:
            run = 0
        else:
            run += 1
            best = max(best, run)
    return best


def test_main_from_the_bus_middle_never_reaches_the_door_the_corner_is_reached_through_the_wall(monkeypatch):
    """Main (97d538b8, the mark driving without the wall governor): the route's first corner is the door's outer
    jamb (547,7,-75); from inside the bus he counts it reached (MESH_WP_CM) a metre south of the door and aims at the
    next corner (825,50,-215) - through the bus's north-east wall - for a minute; the never-stand backstop steps him
    back and the route sends him into the wall again. He never leaves."""
    b, w, tr = run_bus(monkeypatch, *MIDDLE, flags=MAIN)
    assert not tr["done"] and tr["ticks"] == 1800
    assert b.stats.get("stand_breaks", 0) >= 8                 # a step back every few seconds, 12 in the minute
    assert all(450 <= x <= 720 for x, _y, _z in tr["pos"][30:])   # the east part of the bus, against its wall
    assert b.stats["mesh_follows"] > 1000                      # the guard "following the route" into the wall


def test_main_as_at_2130_with_the_wall_governor_stands_turning_for_seconds(monkeypatch):
    """The configuration of the live failure (the wall governor still applied to the mark): the trail recovery
    reverses him, then its retry window holds the stick off while the right stick turns him - two seconds standing,
    which the operator forbids - and the door is found only by luck, 8.8 s in on this model (never, live)."""
    b, w, tr = run_bus(monkeypatch, *MIDDLE, flags={**MAIN, "WALL_GOV_GOAL": True})
    assert longest_stand(tr) >= 45                             # 1.5 s and more with no stick
    # (the live share's governor of 2026-10-31, merged in later, backs off along the travel heading: fewer hits, same stand)
    assert b.stats["wall_hits"] + b.stats["wall_preempts"] >= 1
    assert tr["ticks"] >= 120                                 # (several times the fix's 34)


@pytest.mark.parametrize("start,rot_deg,limit", [
    ((300.0, 50.0, -170.0), 120.0, 60),                        # the middle, facing the back: 34 ticks
    ((503.0, 50.0, -282.0), 110.0, 60),                        # the east end he kept returning to: 34
    ((620.0, 50.0, -260.0), 60.0, 60),                         # against the back wall: 31
    ((471.0, 50.0, -273.0), -60.0, 75),                        # facing the wrong way: 49
    ((68.0, 50.0, -88.0), 120.0, 90),                          # the west end: 57 (the whole bus to walk)
    ((0.0, 50.0, 20.0), -60.0, 120),                           # the west end, facing its wall: 88
])
def test_with_the_fix_he_is_out_of_the_bus_within_three_seconds_and_never_stands(monkeypatch, start, rot_deg, limit):
    b, w, tr = run_bus(monkeypatch, start, rot_deg)
    assert tr["done"] and tr["ticks"] <= limit, (tr["ticks"], tr["holds"][-10:])
    mesh = stage_mesh()
    assert mesh.find(tuple(w.pos), floor_only=True) in (579, 578) or w.pos[1] < 30   # on the ramp or the ground
    assert not b.stats.get("stand_breaks") and not b.stats.get("wall_preempts")
    # (a brush along the bus wall may stall him once on this model: it yields to the route, never the trail)
    assert b.stats.get("wall_hits", 0) <= 1 and b.stats.get("wall_route_yields", 0) == b.stats.get("wall_hits", 0)
    assert longest_stand(tr) <= 12                             # the stick never off for more than 0.4 s
    assert b.stats.get("mesh_lookahead_holds", 0) >= 1 or start[0] < 100   # the corner held until the way is open
    assert all("b" not in h.split(",") or "lup" in h.split(",") for h in tr["holds"])   # no B without the stick forward
    assert b.stats.get("quick_turns", 0) == 0


def test_near_the_mark_but_behind_the_bus_wall_the_mesh_still_steers(monkeypatch):
    """The straight line used to take over within NAV_DIRECT_R (3 m) - here the mark is 2.2 m from the west end,
    through its wall: the route out of the door is kept."""
    mesh = stage_mesh()
    b = bot([0.0])
    b._mesh = mesh
    p = {"pos": (68.0, 50.0, -88.0), "rot": 0.0}
    goal = (-150.0, 0.0, -100.0)                               # on the ground west of the bus
    assert math.hypot(goal[0] - 68.0, goal[2] + 88.0) < R.NAV_DIRECT_R
    b._approach(p, goal, 0.0, link=True)
    assert b.stats.get("nav_near_walled") == 1 and b.stats.get("mesh_routes") == 1 and not b.stats.get("nav_direct_ticks")
    monkeypatch.setattr(R, "MESH_LOOKAHEAD", False)
    b2 = bot([0.0])
    b2._mesh = mesh
    b2._approach(p, goal, 0.0, link=True)
    assert b2.stats.get("nav_direct_ticks") == 1               # main: the line, into the wall


def test_a_wall_met_while_the_route_steers_is_a_short_step_back_not_a_walk_back_along_the_trail(monkeypatch):
    from gbox.mercs.titles import re5_switch_wall as W
    clock = [0.0]
    b = bot(clock)
    b._mesh = object()                                        # (a mesh is read: the push can be counted)
    monkeypatch.setattr(b, "_tick", lambda s, now: {"hold": ("lup", "b")})
    snap = lambda pos: {"player": {"ptr": 1, "pos": pos, "rot": 0.0, "hp": 1000, "hp_max": 1000, "motion": 0},
                        "enemies": [], "inventory": []}
    for k in range(5):                                        # a trail east, then the wall
        clock[0] = k * DT
        b._mesh_wp = (0.0, 1000.0, clock[0])                   # the route steers north every tick
        b.tick(snap((-80.0 + 20.0 * k, 0.0, 0.0)))
    holds = []
    for k in range(5, 125):                                   # four seconds against the wall
        clock[0] = k * DT
        b._mesh_wp = (0.0, 1000.0, clock[0])
        holds.append(b.tick(snap((0.0, 0.0, 0.0)))["hold"])
    assert b.stats["wall_hits"] >= 3 and b.stats.get("wall_route_yields", 0) == b.stats["wall_hits"]
    assert all(h for h in holds), "never a tick with nothing held"
    recs = [h for h in holds if "ldown" in h]
    assert recs and all("rleft" not in h and "rright" not in h for h in recs)   # the back-step, no turning round
    assert all("rleft" not in h and "rright" not in h for h in holds)           # ... and no turn to a reverse heading
    assert any("lup" in h for h in holds[20:])                 # the route pushes again after each step back
    assert b.stats.get("mesh_crossing_pushes", 0) >= 3
    assert b.stats.get("mesh_crossings_refused", 0) >= 1        # MESH_CROSSING_PUSHES of them: the crossing refused
    assert b.stats.get("wall_preempts", 0) == 0                  # the memory's preempt does not stop a routed push
    assert W._state(b)["trail"]                                  # (the trail is kept for the walks the route does not steer)


# --- doors that are action links ------------------------------------------------------------------------------------
def run_links(monkeypatch, west, east, ticks=30 * 40, flags=None):
    for k, v in (flags or {}).items():
        monkeypatch.setattr(R, k, v)
    mesh, links = bus_with_links(west=west, east=east)
    clock = [0.0]
    b = bot(clock)
    w = World(mesh, (400.0, 50.0, 125.0), rot=math.radians(90), links=links)
    goal = (1400.0, -100.0, 125.0)
    mark(b, goal)
    closed = ("unavailable", "completed", "expired")
    tr = drive(b, clock, w, ticks, until=lambda w: (b._goals().goal or {}).get("state") in closed)
    return b, w, tr


def test_a_links_foot_is_reached_the_prompt_is_pressed_and_the_landing_is_confirmed(monkeypatch):
    b, w, tr = run_links(monkeypatch, "usable", "usable")
    assert tr["done"] and tr["ticks"] <= 60 and w.level_changes == 1 and w.presses == 1
    assert b.stats["mesh_links_tried"] == 1 and b.stats["mesh_links_taken"] == 1 and b.stats["level_changes"] == 1
    assert b.stats["prompts_taken"] == 1 and not b.stats.get("mesh_links_refused")
    assert b._goals().goal["state"] == "completed"


def test_a_door_the_game_never_opens_is_refused_and_the_other_door_is_taken(monkeypatch):
    b, w, tr = run_links(monkeypatch, "usable", "majini")
    assert tr["done"] and b._goals().goal["state"] == "completed", b.stats.get("nav_status")
    assert w.level_changes == 1 and b.stats["mesh_links_refused"] >= 1 and b.stats["mesh_links_taken"] == 1
    assert "800,50,125" in b.stats["mesh_refused_last"] or b.stats.get("mesh_crossings_refused")
    assert tr["ticks"] <= 30 * 20                              # the east tried MESH_LINK_TRY_S, then the way round
    assert longest_stand(tr) <= 12
    assert b.stats["wall_hits"] >= 1 and not b.stats.get("wall_preempts")


def test_a_region_with_no_usable_exit_says_so_and_closes_the_mark_instead_of_looping(monkeypatch):
    b, w, tr = run_links(monkeypatch, "majini", "majini")
    assert tr["done"] and tr["ticks"] <= 30 * 20 and w.level_changes == 0
    assert b._goals().goal["state"] == "unavailable"
    assert b.stats["nav_status"].startswith("no usable exit from this floor region")
    assert b.stats["mesh_links_refused"] == 2 and b.stats.get("mesh_no_exit") == 1 and b.stats.get("map_goals_no_exit") == 1
    assert longest_stand(tr) <= 12


def test_a_refused_crossing_is_forgotten_after_a_while():
    b = bot([0.0])
    mesh, _ = bus_with_links()
    b._mesh = mesh
    b._mesh_refuse(mesh, (800.0, 50.0, 125.0), 10.0, "test")
    assert b._mesh_avoid(mesh, 11.0) == [(800.0, 50.0, 125.0)]
    assert b._mesh_avoid(mesh, 10.0 + R.MESH_AVOID_S + 1.0) == []
