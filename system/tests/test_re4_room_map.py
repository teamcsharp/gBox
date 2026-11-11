"""The RE4 Switch room map (#9342, checked: gbox.re4_switch_room_map; read by gbox.mercs.titles.re4_room_map) and the
bot's use of it (re4_switch.ROOM_MAP): walks along the floor, steps toward a wall refused, no shots through walls.

Synthetic rooms first (mm, y up, heading atan2(dx, dz)), then the real tables in gbox/data/re4_switch_room_map against
#9342's JSON, the stage meshes (gbox/data/re4_switch_nav) and live RAM positions read 2026-11-10 on lilspark."""
import json
import math
import random
from pathlib import Path

import pytest

from gbox.mercs.titles import re4_nav
from gbox.mercs.titles import re4_room_map as R
from gbox.mercs.titles import re4_switch as D

DOC = Path(__file__).resolve().parents[1] / "docs" / "research" / "re4-switch-mercs-collision.json"


# --- synthetic rooms ----------------------------------------------------------------------------------------------------
def room(walls, *, size=40, void=(), origin=(-5000.0, -5000.0)):
    """A 10 m x 10 m floor of 250 mm cells round the origin (size cells a side), `void` cells (row, col) without floor."""
    rows = [[0 if (r, c) in void else 1 for c in range(size)] for r in range(size)]
    return R.RoomMap.from_mask("r400", origin, 250.0, rows, walls)


ACROSS = (-3000.0, 1000.0, 3000.0, 1000.0, 0.0, 3000.0, 0)    # a 6 m wall across +z, 1 m in front of the origin


def test_a_walk_across_a_wall_is_refused_and_one_along_it_is_not():
    rm = room([ACROSS])
    assert "a wall" in rm.walk_block((0.0, 0.0, 0.0), (0.0, 0.0, 2000.0))
    assert rm.walk_clear((0.0, 0.0, 0.0), (2000.0, 0.0, 0.0)), "along it, 1 m off"
    assert rm.walk_clear((0.0, 0.0, 0.0), (0.0, 0.0, -2000.0)), "away from it"
    assert rm.walk_clear((0.0, 0.0, 0.0), (4900.0, 0.0, 1050.0)), "past its end, 347 mm off the corner"
    assert "brushes" in rm.walk_block((0.0, 0.0, 0.0), (4800.0, 0.0, 1300.0)), "181 mm off the corner: his body hits it"
    assert rm.walk_clear((0.0, 0.0, 800.0), (2000.0, 0.0, 800.0), end_r=0.0), "along it, 200 mm off: no nearer"
    assert not rm.walk_clear((0.0, 0.0, 600.0), (2000.0, 0.0, 850.0), end_r=0.0), "closing on it to 150 mm"


def test_only_a_wall_within_his_body_height_stops_a_walk():
    beam = (-3000.0, 1000.0, 3000.0, 1000.0, 2200.0, 3500.0, 0)       # above his head
    below = (-3000.0, 1000.0, 3000.0, 1000.0, -2500.0, -100.0, 0)     # the storey under his floor
    low = (-3000.0, 1000.0, 3000.0, 1000.0, 0.0, 1100.0, 0)           # a 1.1 m wall: in his way
    assert R.RoomMap.from_mask("r400", (-5000, -5000), 250.0, [[1] * 40] * 40, [beam]).walk_clear(
        (0.0, 0.0, 0.0), (0.0, 0.0, 2000.0))
    assert room([below]).walk_clear((0.0, 0.0, 0.0), (0.0, 0.0, 2000.0))
    assert not room([low]).walk_clear((0.0, 0.0, 0.0), (0.0, 0.0, 2000.0))
    assert room([low]).walk_clear((0.0, 1500.0, 0.0), (0.0, 1500.0, 2000.0)), "standing 1.5 m higher it is below him"


def test_a_low_wall_stops_the_walk_but_not_the_shot_over_it():
    rm = room([(-3000.0, 1000.0, 3000.0, 1000.0, 0.0, 1100.0, 0)])
    assert not rm.walk_clear((0.0, 0.0, 0.0), (0.0, 0.0, 3000.0))
    assert rm.sight_clear((0.0, 0.0, 0.0), (0.0, 0.0, 3000.0)), "his gun at 1.45 m, the chest at 1.2 m: over it"
    tall = room([ACROSS])
    assert tall.sight_block((0.0, 0.0, 0.0), (0.0, 0.0, 3000.0))[0][:4] == ACROSS[:4]


def test_an_invisible_blocker_stops_him_but_not_a_shot():
    rm = room([(-3000.0, 1000.0, 3000.0, 1000.0, 0.0, 3000.0, 1)])
    assert not rm.walk_clear((0.0, 0.0, 0.0), (0.0, 0.0, 2000.0))
    assert rm.sight_clear((0.0, 0.0, 0.0), (0.0, 0.0, 2000.0))


def test_the_edge_of_the_floor_and_a_walk_ending_against_a_wall_are_refused():
    void = {(r, c) for r in range(28, 40) for c in range(40)}         # no floor from z = +2000 on
    rm = room([], void=void)
    assert "off the floor" in rm.walk_block((0.0, 0.0, 0.0), (0.0, 0.0, 3000.0))
    assert rm.walk_clear((0.0, 0.0, 0.0), (0.0, 0.0, 1500.0))
    walled = room([ACROSS])
    assert "brushes" in walled.walk_block((0.0, 0.0, 0.0), (0.0, 0.0, 800.0)), "800 mm on is 200 mm from the wall"
    assert "ends" in walled.walk_block((0.0, 0.0, 0.0), (0.0, 0.0, 800.0), body_r=0.0)
    assert walled.walk_clear((0.0, 0.0, 0.0), (0.0, 0.0, 800.0), end_r=0.0, body_r=0.0)
    assert walled.walk_clear((0.0, 0.0, 0.0), (0.0, 0.0, 600.0)), "400 mm short of it"
    assert room([], void={(20, 20)}).walk_clear((-100.0, 0.0, 100.0), (-1000.0, 0.0, 100.0)), \
        "the cell he stands in is never the floor's edge"


def test_the_computed_hash_cell():
    rm = room([ACROSS], void={(0, 0)})
    assert rm.blocked_cell(-4900.0, -4900.0, 0.0), "no floor"
    assert rm.blocked_cell(100.0, 1000.0, 0.0), "the wall runs through it"
    assert not rm.blocked_cell(100.0, 1000.0, 3500.0), "standing above the wall's top"
    assert not rm.blocked_cell(100.0, 500.0, 0.0), "beside it"


def test_the_table_format_round_trips():
    with pytest.raises(ValueError):
        R.from_json({"format": "something else"})
    rm = R.load("r403")
    assert rm is not None and rm.room == "r403" and rm.stage == "Base" and rm.walls


def test_the_builder_rules_on_a_synthetic_collision():
    """gbox.re4_switch_room_map on a made-up SAT: a 4 m x 4 m floor quad at y 0, one 2 m wall face across x = 1000
    (normal +x), one 0.5 m kerb (not tall: no wall); the floor mask packs the way the room map reads it."""
    np = pytest.importorskip("numpy")
    from gbox import re4_switch_room_map as B
    verts = np.array([[-2000, 0, -2000], [2000, 0, -2000], [2000, 0, 2000], [-2000, 0, 2000],      # the floor
                      [1000, 0, -1000], [1000, 0, 1000], [1000, 2000, 1000], [1000, 2000, -1000],  # the wall
                      [-1500, 0, -1000], [-1500, 0, 1000], [-1500, 500, 1000]], float)            # the kerb
    tris = np.array([[0, 2, 1], [0, 3, 2], [4, 5, 6], [4, 6, 7], [8, 9, 10]])
    normals = np.array([[0, 1, 0], [0, 1, 0], [1, 0, 0], [1, 0, 0], [1, 0, 0]], float)
    col = {"verts": verts, "tris": tris, "normals": normals, "attr": np.array([0, 0, 0, 0x400, 0], np.uint32)}
    floor = B.floor_mask(col, (-2500, -2500), 20, 20, 250.0)
    walls = B.wall_triangles(col)
    assert len(walls) == 2 and all(abs(w[0] - 1000) < 1e-6 and abs(w[2] - 1000) < 1e-6 for w in walls)
    assert {B.seg_key(w) for w in walls} == {((1000, -1000), (1000, 1000))}, "the quad's two halves: one segment"
    rm = R.from_json({"format": R.FORMAT, "room": "r400", "grid": {"origin_mm": [-2500, -2500], "cell_mm": 250.0,
                      "cols": 20, "rows": 20, "floor": B.pack_mask(floor)},
                      "walls": [[*walls[0][:4], 0, 2000, 0]]})
    assert rm.floor_at(0.0, 0.0) and rm.floor_at(1900.0, -1900.0) and not rm.floor_at(-2400.0, 0.0)
    assert int(floor.sum()) == 16 * 16 and B.crossed_cells([walls[0][:4]], (-2500, -2500), 20, 20)[10, 14]
    assert not rm.walk_clear((0.0, 0.0, 0.0), (1800.0, 0.0, 0.0)) and rm.walk_clear((0.0, 0.0, 0.0), (0.0, 0.0, 1500.0))


# --- the bot (re4_switch.ROOM_MAP) ---------------------------------------------------------------------------------------
def snap(enemies=(), pos=(0.0, 0.0, 0.0), rot=0.0, rm=None, **extra):
    return {"player": {"pos": tuple(pos), "rot": rot, "hp": 1000, "hp_max": 1000, "ptr": 1},
            "enemies": [{"ptr": 100 + i, "hp": 400, "hp_max": 400, "class": 0xAE7050, "pos": tuple(p)}
                        for i, p in enumerate(enemies)], "room_map": rm, **extra}


def test_an_escape_runs_along_the_floor_never_through_the_wall_behind_him(monkeypatch):
    behind = (-3000.0, -1000.0, 3000.0, -1000.0, 0.0, 3000.0, 0)       # a wall 1 m behind him
    rm = room([behind])
    s = snap([(0.0, 0.0, 600.0), (300.0, 0.0, 600.0), (-300.0, 0.0, 600.0)], rm=rm)   # a swarm in front
    b = D.Bot(stats={}, director=False)
    goal = b._escape_goal(s["player"], b._live(s["player"], s["enemies"]), s)
    assert goal is not None and rm.walk_clear(s["player"]["pos"], goal)
    monkeypatch.setattr(D, "ROOM_MAP", False)
    blind = D.Bot(stats={}, director=False)
    goal = blind._escape_goal(s["player"], blind._live(s["player"], s["enemies"]), s)
    assert not rm.walk_clear(s["player"]["pos"], goal), "the rollback: straight back, through it"


def test_no_shot_through_a_wall_without_a_stage_mesh(monkeypatch):
    rm = room([ACROSS])
    s = snap([(0.0, 0.0, 3000.0)], rm=rm)
    assert not D.Bot._line_of_sight_ok(s["player"], s["enemies"][0], s)
    assert D.Bot._line_of_sight_ok(s["player"], {"pos": (2000.0, 0.0, 0.0)}, s)
    monkeypatch.setattr(D, "ROOM_MAP", False)
    assert D.Bot._line_of_sight_ok(s["player"], s["enemies"][0], s), "the rollback: no geometry, no gate"


class Walk:
    """RE4's tank controls over a room map: the left stick turns him, up walks him - and a wall stops him (a step that
    would cross one is not taken: he pushes against it). Aiming, he stands."""
    TURN_RATE, AIM_RATE, WALK_MM_S = 2.5, 1.5, 3000.0
    BODY_MM = 150.0                                               # his body's half width here (RE4's: not measured)

    def __init__(self, rm, enemies, pos=(0.0, 0.0, 0.0), rot=0.0):
        self.rm, self.pos, self.rot = rm, list(pos), rot
        self.enemies = [{"ptr": 100 + i, "hp": 400, "hp_max": 400, "class": 0xAE7050, "pos": tuple(p)}
                        for i, p in enumerate(enemies)]
        self.pushed = []
        self.shots = []                                           # per shot: was its line clear of the walls

    def snap(self):
        return {"player": {"pos": tuple(self.pos), "rot": self.rot, "hp": 1000, "hp_max": 1000, "ptr": 1},
                "enemies": [dict(e) for e in self.enemies], "room_map": self.rm}

    def apply(self, act, dt):
        hold, tap = set(act.get("hold") or ()), act.get("tap")
        if D.AIM_BTN in hold:                                     # he stands; the right stick turns the aim
            keys = hold | ({tap} if tap else set())
            rate = self.AIM_RATE * (0.3 * dt if tap in ("rleft", "rright") else dt)
            self.rot += rate * (("rleft" in keys) - ("rright" in keys))
            if tap == D.FIRE_BTN:
                live = [e for e in self.enemies if e["hp"] > 0]
                self.shots.append(all(self.rm.sight_clear(tuple(self.pos), e["pos"]) for e in live))
                if live and self.shots[-1]:
                    live[0]["hp"] = max(0, live[0]["hp"] - 200)
            self.pushed.append(False)
            return
        if set(D.QUICK_TURN) <= hold:
            self.rot += math.pi * dt / 0.5
        self.rot += self.TURN_RATE * dt * (("lleft" in hold) - ("lright" in hold))
        pushed = False
        if "lup" in hold:
            step = self.WALK_MM_S * dt * (1.5 if D.RUN_BTN in hold else 1.0)
            end = (self.pos[0] + step * math.sin(self.rot), self.pos[1], self.pos[2] + step * math.cos(self.rot))
            if self.rm.wall_crossed(tuple(self.pos), end) or self.rm.wall_near(end, self.BODY_MM):
                pushed = True                                     # his body against it: no ground
            else:
                self.pos[0], self.pos[2] = end[0], end[2]
        self.pushed.append(pushed)


def play(bot, game, seconds, dt=0.05):
    for k in range(int(round(seconds / dt))):
        game.apply(bot.tick(game.snap(), now=k * dt), dt)


def test_he_goes_round_a_wall_the_room_map_knows_never_into_it_nor_shooting_it(monkeypatch):
    """The live shape: a Ganado behind a wall and no stage mesh to route round it. The fight walks at him (no clear
    shot): every step toward the wall is refused before his body reaches it, he goes round its end and shoots from the
    open side - never into the wall. The rollback stands and shoots the wall."""
    rm = room([ACROSS])
    game = Walk(rm, [(0.0, 0.0, 3000.0)])
    b = D.Bot(stats={}, director=False)
    play(b, game, 10.0)
    assert b.stats.get("room_map_steps_refused", 0) >= 1 and b.stats["room_map"] == "r400"
    assert sum(game.pushed) == 0, "never against it"
    assert game.pos[2] > 1000.0 and game.shots and all(game.shots), "round its end, every shot on a clear line"
    monkeypatch.setattr(D, "ROOM_MAP", False)
    blind = Walk(rm, [(0.0, 0.0, 3000.0)])
    play(D.Bot(stats={}, director=False), blind, 10.0)
    assert blind.shots and not any(blind.shots), "the rollback: no geometry, every shot into the wall"


def test_a_never_stand_step_goes_along_the_room_maps_floor():
    rm = room([(-3000.0, 900.0, 3000.0, 900.0, 0.0, 3000.0, 0), (-600.0, -3000.0, -600.0, 3000.0, 0.0, 3000.0, 0)])
    s = snap([], rm=rm)                                              # walled ahead and on the -x side: +x is open
    b = D.Bot(stats={}, director=False)
    act, k = None, 0
    while b.stats["stand_breaks"] == 0 and k < 100:                   # nobody on the map: the sweep, standing
        act, k = b.tick(s, now=0.1 * k), k + 1
    goal = b._stand["goal"]
    assert b.doing == "step" and goal is not None and rm.walk_clear(s["player"]["pos"], goal) and goal[0] > 0


class Steering:
    """A walker that steered this tick toward (x, z) (re4_walk.Walker's wp / now / at_link)."""

    def __init__(self, x, z, at_link=False):
        self.wp, self.now, self.at_link = (x, z, 7.0), 7.0, at_link


def test_the_routes_way_round_is_a_turn_and_a_crossing_is_left_to_the_walker():
    rm = room([ACROSS])
    b = D.Bot(stats={}, director=False)
    p = {"pos": (0.0, 0.0, 300.0), "rot": 0.0}
    act = {"hold": {"lup"}}
    assert "a wall" in b._room_ahead(p, act, {"room_map": rm}), "nobody steering: refused"
    b.walker = Steering(2500.0, 300.0)                                # the route's point off to his right, clear
    turned = b._room_ahead(p, act, {"room_map": rm})
    assert isinstance(turned, dict) and "lup" not in turned["hold"] and b.stats["room_map_route_turns"] == 1
    b.walker = Steering(0.0, 2500.0, at_link=True)                    # a crossing through it: the walker's own
    assert b._room_ahead(p, act, {"room_map": rm}) is None
    b.walker = Steering(0.0, 2500.0)                                  # a route through the wall: refused
    assert isinstance(b._room_ahead(p, act, {"room_map": rm}), str)


# --- the wall's tangent (the operator 2026-11-10: the bot "is still turning back and forth and is stuck in the same
# room"; a bot_trace of session 25385f8f4...: the unwall sent a pure sideways stick) -----------------------------------
def test_the_refusing_wall_is_named_and_its_tangents_given():
    rm = room([ACROSS])
    why, wall = rm.walk_block_detail((0.0, 0.0, 0.0), (0.0, 0.0, 2000.0))
    assert "a wall" in why and wall == ACROSS
    assert rm.walk_block_detail((0.0, 0.0, 0.0), (0.0, 0.0, -800.0)) is None
    assert rm.walk_block((0.0, 0.0, 0.0), (0.0, 0.0, 2000.0)) == why, "the reason alone, as before"
    assert rm.span_mm() == pytest.approx(10000.0)
    assert {round(math.degrees(h), 3) for h in rm.tangents(ACROSS)} == {90.0, -90.0}, "along the wall, both ways"


def test_the_unwalls_probe_and_step_are_scaled_to_the_room():
    small = room([ACROSS])                                            # a 10 m x 10 m room
    big = R.RoomMap.from_mask("r400", (-5000.0, -5000.0), 250.0, [[1] * 160] * 160, [ACROSS])   # 40 m a side
    b = D.Bot(stats={}, director=False)
    assert b._room_reach(small, set()) == pytest.approx(800.0), "the small room: the floor's 800 mm"
    assert b._room_reach(big, set()) == pytest.approx(1600.0), "the arena: 4 % of its side, not the floor's"
    assert b._room_reach(big, {"lup", D.RUN_BTN}) == pytest.approx(1600.0)
    assert b._unwall_reach(small) == pytest.approx(D.UNWALL_MM)
    assert b._unwall_reach(big) == pytest.approx(D.ROOM_UNWALL_MAX_MM), "the step along the wall, capped"


def test_the_unwall_turns_to_the_walls_tangent_and_pushes_forward_along_it():
    """Not a pure sideways stick across the room: the way off the wall is the wall's own tangent - he turns to it, then
    the stick goes forward along the wall (the walker's route no longer turns him back into it)."""
    rm = room([ACROSS])
    game = Walk(rm, [(0.0, 0.0, 3000.0)])
    b = D.Bot(stats={}, director=False)
    turn_only, run, forward, along_x, off_z = 0, 0, 0, 0.0, 0.0
    for k in range(200):                                             # 10 s: round the wall and onto the shot
        act = b.tick(game.snap(), now=k * 0.05)
        if b.doing == "unwall":
            hold = set(act.get("hold") or ())
            if hold & {"lleft", "lright"} and "lup" not in hold:
                run += 1
                turn_only = max(turn_only, run)
            else:
                run = 0
            forward += "lup" in hold
            if (b.__dict__.get("_uc_unwall") or {}).get("mode") == "tangent":
                along_x, off_z = max(along_x, game.pos[0]), max(off_z, abs(game.pos[2]))
        game.apply(act, 0.05)
    assert b.stats.get("unwall_tangents", 0) >= 1 and b.stats.get("unwall_tangent_steps", 0) >= 1
    assert turn_only <= int(0.8 / 0.05), "a turn to the tangent, not a spell of turning on the spot"
    assert forward >= 8, "then the stick forward along it"
    assert along_x > 3000.0 and off_z < 900.0, "along the wall, past its end"
    assert sum(game.pushed) == 0 and game.shots and all(game.shots), "never against it, every shot clear"


def test_the_unwalls_side_is_held_not_flipped_within_the_hold():
    rm = room([ACROSS])
    b = D.Bot(stats={}, director=False)
    b._uc_control_at = 0.0
    b._wall_core({"pos": (0.0, 0.0, 300.0), "rot": 0.0}, {"hold": {"lup"}}, {"player": {"pos": (0.0, 0.0, 300.0),
                                                                                    "rot": 0.0}, "room_map": rm}, 0.05)
    side = b.__dict__["_uc_unwall_side"]
    assert side and abs(abs(side["h"]) - math.pi / 2) < 1e-6, "a tangent of the wall"
    # a look from a facing nearer the other hand, inside the hold: the same hand, not the other
    tries = b._unwall_tries(0.2, -math.pi / 2 + 0.2, rm, ACROSS, True)
    assert b.__dict__["_uc_unwall_side"]["h"] == side["h"]
    assert tries is None or all(abs(math.radians(d) - (side["h"] - (-math.pi / 2 + 0.2))) > math.radians(10)
                                for d in tries), "the other tangent is not tried first"
    assert D.UNWALL_SIDE_HOLD_S == pytest.approx(0.8)


def test_no_unwall_on_the_mesh_walkers_own_route_leg():
    """ROOM_LEGS extended to the unwall: a route leg the mesh's floor reaches straight from him is left to the walker -
    a wall ahead never starts a tangent detour on it."""
    rm = room([ACROSS])
    b = D.Bot(stats={}, director=False)
    w = Steering(0.0, 2500.0)
    w.leg = {"at": w.now, "open": True, "keys": ("lup",), "to": (0.0, 2500.0)}
    b.walker = w
    b._uc_control_at = 5.0
    p = {"pos": (0.0, 0.0, 300.0), "rot": 0.0}
    out = b._wall_core(p, {"hold": {"lup"}}, {"player": dict(p), "enemies": [], "room_map": rm}, 5.05)
    assert out["hold"] == {"lup"} and b.stats["room_map_route_legs"] == 1
    assert b.stats.get("room_map_steps_refused", 0) == 0 and b.doing != "unwall" and "_uc_unwall" not in b.__dict__


def test_the_room_map_is_the_stages_own_or_none():
    mine = re4_nav.load("r403")
    assert R.room_of_snap({"nav": mine}) == "r403"
    fake = re4_nav.Mesh([(0, 0, 0), (1000, 0, 0), (0, 0, 1000)], [(0, 1, 2)], room="r400")
    assert R.room_of_snap({"nav": fake}) is None, "a synthetic mesh named r400 is not Village's coordinates"
    assert R.room_of_snap({"game": {"stage": 1}}) is None, "a synthetic snapshot: no fallback"
    assert R.room_of_snap({"module_base": 1, "game": {"stage": 1}}) == "r402"
    assert R.room_of_snap({"module_base": 1, "stage": "Waterworld"}) == "r404"


def test_mercmode_stages_name_the_rooms():
    from gbox import re4_stage_greybox as G
    assert [R.room_for_stage(name) for name in D.STAGES] == ["r400", "r402", "r403", "r404"]
    assert [R.room_for_stage(i) for i in range(4)] == ["r400", "r402", "r403", "r404"], "Select Stage's index"
    assert all(G.STAGES[name][0] == room_id for name, room_id in R.STAGE_ROOM.items())
    assert R.room_for_stage("base") == "r403" and R.room_for_stage(0x0404) == "r404"


# --- the real tables ----------------------------------------------------------------------------------------------------
@pytest.fixture(scope="module")
def doc():
    return json.loads(DOC.read_text(encoding="utf-8"))["rooms"]


@pytest.mark.parametrize("room_id", sorted(R.ROOMS))
def test_each_table_carries_the_docs_walls_and_grid(doc, room_id):
    rm, d = R.load(room_id), doc[room_id]
    g = d["walk_grid"]
    assert (rm.ox, rm.oz, rm.cell, rm.cols, rm.rows) == (g["origin_mm"][0], g["origin_mm"][1], 250.0, g["cols"],
                                                          g["rows"])
    assert [w[:4] for w in rm.walls] == [tuple(s) for s in d["wall_segments_mm_x0_z0_x1_z1"]], "every segment, in order"
    assert all(w[5] - w[4] >= 999.0 for w in rm.walls), "taller than 1 m (#9342's rule), the span kept (whole mm)"
    cells = g["cells"]
    floor_cells = [i for i, ch in enumerate(cells) if ch == "."]
    assert all(rm.floor_at(rm.ox + (i % rm.cols + 0.5) * 250.0, rm.oz + (i // rm.cols + 0.5) * 250.0)
               for i in floor_cells[::97]), "every '.' of the doc is floor here"


# Live RAM positions of the bot (mm), 2026-11-10 on lilspark: gbox-data/mercs/re4-sight-blocks.jsonl (r402, r404) and
# the tactical map's Base round (r403); r400 the two #9342 cites from re4-switch-ram.md. Each one stands on a cell the
# doc's grid marks '#'  (r400's two on '.').
LIVE = {
    "r400": [(-3809.2, 41.6, 5961.0), (-3668.0, 41.0, 6021.0)],
    "r402": [(12911.0, 3073.0, -27392.0), (13722.0, 3073.0, -26413.0), (15662.0, 3073.0, -26736.0),
             (17252.0, 3073.0, -24571.0)],
    "r403": [(38943.0, 8662.0, 26978.0), (49626.0, 20536.0, 17310.0), (51553.0, 11411.0, -5655.0),
             (51426.0, 11411.0, -1012.0)],
    "r404": [(26711.0, 3000.0, -33046.0), (25756.0, 3000.0, -33656.0), (23472.0, 3000.0, -34555.0),
             (21764.0, 3000.0, -34983.0)],
}


def test_the_frame_live_positions_stand_on_the_floor_and_the_docs_hash_cells_are_not_walls(doc):
    for room_id, positions in LIVE.items():
        rm, mesh = R.load(room_id), re4_nav.load(room_id)
        g = doc[room_id]["walk_grid"]
        for x, y, z in positions:
            assert rm.floor_at(x, z) and not rm.blocked_cell(x, z, y), (room_id, x, z)
            fy = mesh.floor_y(x, z, y)
            assert fy is not None and abs(fy - y) < 50.0, "RAM y is the SAT floor's height: one frame"
            i = int((z - g["origin_mm"][1]) // 250) * g["cols"] + int((x - g["origin_mm"][0]) // 250)
            assert g["cells"][i] == ("." if room_id == "r400" else "#"), "the doc's grid there"


@pytest.mark.parametrize("room_id", sorted(R.ROOMS))
def test_no_shot_through_the_docs_walls(room_id):
    """The stage mesh's exact triangle test (the fight's line of sight) stops a level shot through the middle of nearly
    every #9342 wall (a wall plane with an opening in it lets some through); the room map's own test stops all."""
    rm, mesh = R.load(room_id), re4_nav.load(room_id)
    walls = [w for w in rm.walls if not w[6]]
    stopped = mine = 0
    for x0, z0, x1, z1, lo, hi, _b in walls:
        mx, mz, n = (x0 + x1) / 2, (z0 + z1) / 2, math.hypot(x1 - x0, z1 - z0) or 1.0
        nx, nz, y = -(z1 - z0) / n, (x1 - x0) / n, (lo + hi) / 2
        a = (mx + 1500 * nx, y - re4_nav.EYE_MM, mz + 1500 * nz)
        b = (mx - 1500 * nx, y - re4_nav.CHEST_MM, mz - 1500 * nz)
        stopped += mesh.blocking_wall(a, b) is not None
        mine += rm.sight_block(a, b) is not None
    assert mine == len(walls) and stopped >= 0.98 * len(walls)


def test_walks_the_shot_line_passes_through_walls_are_refused():
    """The gap ROOM_MAP closes: of 2-3 m walks from the Village floor that cross a #9342 wall within his body's height,
    some pass the stage mesh's shot-line test (nav.clear_segment, what the steps and escapes asked until now) - the
    room map refuses every one."""
    rm, mesh = R.load("r400"), re4_nav.load("r400")
    rng = random.Random(7)
    crossing = passed = 0
    for _ in range(1500):
        a = mesh.centre[rng.randrange(len(mesh.centre))]
        h, L = rng.uniform(-math.pi, math.pi), rng.choice((2000.0, 3000.0))
        b = (a[0] + L * math.sin(h), a[1], a[2] + L * math.cos(h))
        if rm.wall_crossed(a, b) is None:
            continue
        crossing += 1
        assert not rm.walk_clear(a, b)
        passed += mesh.clear_segment(a, b)
    assert crossing > 100 and passed >= 1
