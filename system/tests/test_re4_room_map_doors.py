"""The RE4 Switch bot through openings, on the fight's line, and its controls on the map (live 2026-11-10, Castle r402,
the operator: "why does the bot meander and move at walls so weird?" and "i want you able to analyze and see the path
and controls"): a 60 s trace had him 22.6 s flanking, the route's detour north past the west doorway, the doorway's
waypoints refused while Ganados filled it (no route left: the straight line into the jamb), the walls he pressed by
it refusing the way through for a minute, and a grudge turning him off the pack he was shooting.

Synthetic rooms (mm, y up, heading atan2(dx, dz)) and the real r402 tables (gbox/data/re4_switch_room_map,
re4_switch_nav) at the trace's positions."""
import json
import math

import pytest

from gbox.mercs import tactical as T
from gbox.mercs.core import room_map as C
from gbox.mercs.titles import re4_nav
from gbox.mercs.titles import re4_room_map as R
from gbox.mercs.titles import re4_switch as D
from gbox.mercs.titles import re4_walk as W

Y = 3073.0                                       # the Castle floor by the west doorway (RAM y)
TGT = (14929.0, Y, -26359.0)                     # a Ganado in the corridor west of the doorway (the trace, 35.3 s)


@pytest.fixture(scope="module")
def r402():
    return re4_nav.load("r402"), R.load("r402")


def door(gap):
    """A wall across z = 1000 with a door `gap` wide round x = 0, over a 10 m floor."""
    h = gap / 2
    walls = [(-3000.0, 1000.0, -h, 1000.0, 0.0, 3000.0, 0), (h, 1000.0, 3000.0, 1000.0, 0.0, 3000.0, 0)]
    return R.RoomMap.from_mask("r400", (-5000.0, -5000.0), 250.0, [[1] * 40 for _ in range(40)], walls)


# --- the room map's margins in a gap ------------------------------------------------------------------------------------
def test_a_door_narrower_than_the_margins_is_passed_through_its_middle(monkeypatch):
    rm = door(550.0)                                             # 275 mm a side: short of BRUSH_R_MM (300)
    assert rm.walk_clear((0.0, 0.0, 0.0), (0.0, 0.0, 2000.0)), "through its middle"
    why = rm.walk_block((80.0, 0.0, 0.0), (80.0, 0.0, 2000.0))
    assert why and "brushes" in why and "margin 220" in why, "80 mm off its middle: 195 mm from a jamb"
    assert rm.walk_clear((0.0, 0.0, 0.0), (0.0, 0.0, 1000.0)), "ending in its middle: 275 mm a side"
    assert not rm.walk_clear((100.0, 0.0, 0.0), (100.0, 0.0, 1000.0)), "ending 175 mm from a jamb"
    monkeypatch.setattr(C, "GAP_MARGIN_X", 1e9)                  # the rollback: the full margins, shut
    assert "brushes" in rm.walk_block((0.0, 0.0, 0.0), (0.0, 0.0, 2000.0))


def test_a_wide_door_keeps_the_full_margins():
    rm = door(1400.0)
    assert rm.walk_clear((0.0, 0.0, 0.0), (0.0, 0.0, 2000.0))
    assert "margin 300" in rm.walk_block((500.0, 0.0, 0.0), (500.0, 0.0, 2000.0)), "200 mm from a jamb"


def test_the_west_doorway_of_the_castle(r402):
    """r402's west doorway: the arena wall x ~ 16090 open between z -27186 and -25809 (1.38 m), the corridor beyond
    1.4 m wide. Through its middle he passes; along the corridor's south wall (195 mm off) he does not; a way past
    the south jamb and on to 209 mm of the corridor's north wall is no gap (the two lie 1 m apart along it): refused at
    the full margin."""
    _mesh, rm = r402
    assert rm.walk_clear((16800.0, Y, -26500.0), (15300.0, Y, -26500.0))
    assert "brushes" in rm.walk_block((16800.0, Y, -27000.0), (15300.0, Y, -27000.0))
    why = rm.walk_block((16507.0, Y, -27244.0), (15400.0, Y, -26000.0), end_r=0.0)
    assert why == "brushes a wall 16061,-28649-16103,-27186 (263 mm, margin 300)"


# --- the mesh's own route legs (ROOM_LEGS) ------------------------------------------------------------------------------
def _at_door(mesh, rm, rot=-0.7):
    """The bot 1 m east of the doorway (the trace, 34.7 s), facing along the walker's route to the corridor."""
    b = D.Bot(stats={}, director=False)
    w = b.walker = W.Walker(b.stats)
    p = {"pos": (16507.0, Y, -27244.0), "rot": rot, "hp": 1000, "hp_max": 1000, "ptr": 1}
    snap = {"player": p, "enemies": [], "nav": mesh, "room_map": rm}
    w.observe(snap, 5.0)
    keys = w.approach(TGT)
    return b, w, p, snap, keys


def test_a_route_leg_through_the_doorway_passes_the_wall_he_pressed_beside_it(r402, monkeypatch):
    mesh, rm = r402
    b, w, p, snap, keys = _at_door(mesh, rm)
    assert w.how == "the stage mesh" and w.leg and w.leg["open"] and "lup" in keys
    b._wall_core(p, {"hold": set(keys)}, snap, 5.0)              # (the press memory made)
    b._uc_walls.remember(5.0, b._profile().pos_cm(p["pos"]), p["rot"])   # pressed here before, facing this way
    out = b._wall_core(p, {"hold": set(keys)}, snap, 5.0)
    assert "lup" in out["hold"] and b.stats["room_map_route_legs"] >= 1 and b.stats["walls_refused"] == 0
    w.leg = None                                                 # a free step the same way: still refused
    out = b._wall_core(p, {"hold": {"lup"}}, snap, 5.0)
    assert b.doing == "unwall" and b.stats["walls_refused"] == 1
    monkeypatch.setattr(D, "ROOM_LEGS", False)                   # the rollback: the route leg refused there too
    r, rw, rp, rsnap, rkeys = _at_door(mesh, rm)
    r._wall_core(rp, {"hold": set(rkeys)}, rsnap, 5.0)
    r._uc_walls.remember(5.0, r._profile().pos_cm(rp["pos"]), rp["rot"])
    r._wall_core(rp, {"hold": set(rkeys)}, rsnap, 5.0)
    assert r.doing == "unwall" and r.stats["walls_refused"] == 1


def test_a_leg_he_still_swings_round_to_is_not_the_routes(r402):
    mesh, rm = r402
    b, w, p, snap, keys = _at_door(mesh, rm, rot=0.4)            # 1.1 rad off the leg: turning onto it
    assert not b._route_leg({"hold": set(keys)}, p)


# --- the walker -----------------------------------------------------------------------------------------------------------
def _walker(mesh, pos, now=1.0, enemies=()):
    w = W.Walker({})
    w.observe({"player": {"pos": pos, "rot": 0.0}, "enemies": list(enemies), "nav": mesh}, now)
    return w


def test_the_routes_detour_north_is_cut_to_the_doorway(r402, monkeypatch):
    """From the arena's south side (the trace, 4.9 s) the mesh's route runs 9 m - north to z -23800 and back - to the
    doorway 3.6 m away in a straight line on open floor: the walker heads for the doorway."""
    mesh, rm = r402
    pos = (18900.0, 3064.0, -28750.0)
    w = _walker(mesh, pos)
    w.approach(TGT)
    assert (round(w.wp[0]), round(w.wp[1])) == (16235, -26348) and w.stats["mesh_shortcuts"] == 1
    assert rm.walk_clear(pos, (16235.0, 3064.0, -26348.0), end_r=0.0) and mesh.floor_segment(pos, (16235.0, Y, -26348.0))
    monkeypatch.setattr(W, "ROUTE_SHORTCUT", False)
    r = _walker(mesh, pos)
    r.approach(TGT)
    assert (round(r.wp[0]), round(r.wp[1])) == (18000, -23800), "the rollback: waypoint by waypoint, north first"


def test_a_shortcut_never_passes_a_refused_crossing_nor_brushes_a_jamb(r402):
    mesh, rm = r402
    pos = (18900.0, 3064.0, -28750.0)
    pts = mesh.route(pos, TGT, clearance=W.CLEARANCE_MM)
    w = _walker(mesh, pos)
    doorway = next(i for i, q in enumerate(pts) if (round(q[0]), round(q[2])) == (16235, -26348))
    assert w._shortcut(pos, list(pts)) == doorway
    w._avoid["pts"] = [(17567.0, 3064.0, -27549.0, 1e9, False)]   # a refused crossing on the straight way
    assert w._shortcut(pos, list(pts)) < doorway
    door = (16507.0, Y, -27244.0)                                # the corridor's far point brushes the south jamb
    near = _walker(mesh, door)
    route = mesh.route(door, TGT, clearance=W.CLEARANCE_MM)
    cut = near._shortcut(door, list(route))
    q = route[cut]
    assert rm.walk_clear(door, (q[0], Y, q[2]), end_r=0.0) and (round(q[0]), round(q[2])) != (15400, -26000)


def test_floor_refusals_that_shut_every_way_are_forgiven(r402, monkeypatch):
    """The live state: the doorway's floor waypoints refused after stalls (the Ganados in it) - every route to the
    corridor goes through it, so none is left and the walker took the straight line into the jamb."""
    mesh, _rm = r402
    pos = (16507.0, Y, -27244.0)
    w = _walker(mesh, pos)
    for q in ((16200.0, Y, -26650.0), (16235.0, Y, -26348.0), (15730.0, Y, -26325.0)):
        w.refuse(q, "a crossing the game does not let him walk", floor=True)
    w.refuse((30000.0, Y, -20000.0), "a crossing that never let him through")      # a real crossing refusal
    w.approach(TGT)
    assert w.how == "the stage mesh" and w.stats["mesh_avoid_forgiven"] == 1 and w.stats["nav_status"] == "route"
    assert [q[:3] for q in w._avoid["pts"]] == [(30000.0, Y, -20000.0)], "the crossing that never let him by stays"
    monkeypatch.setattr(W, "FORGIVE_FLOOR", False)
    r = _walker(mesh, pos)
    for q in ((16200.0, Y, -26650.0), (16235.0, Y, -26348.0), (15730.0, Y, -26325.0)):
        r.refuse(q, "a crossing the game does not let him walk", floor=True)
    r.approach(TGT)
    assert r.how == "no proved path to the goal" and r.stats["mesh_no_route"] == 1
    assert r.no_exit(), "even without floor-refusal forgiveness, no route must not become a line into the jamb"


def test_a_stall_with_ganados_in_the_doorway_refuses_no_waypoint(r402):
    mesh, _rm = r402
    pos = (16507.0, Y, -27244.0)
    crowd = [{"pos": (16150.0, Y, -26500.0), "hp": 400}, {"pos": (15900.0, Y, -26400.0), "hp": 400}]
    for enemies, refused in ((crowd, False), ((), True)):
        w = W.Walker({})
        for k in range(40):                                      # 20 s pushing and never moving
            w.observe({"player": {"pos": pos, "rot": -0.7}, "enemies": list(enemies), "nav": mesh}, 0.5 * k)
            w.approach(TGT)
        assert bool(w.stats.get("mesh_crossings_refused")) is refused
        assert bool(w.stats.get("mesh_stall_foe_skips")) is not refused


# --- the flank: to where the shot opens (FLANK_LOS) ----------------------------------------------------------------------
def test_the_flank_goes_to_where_the_shot_opens_and_ends_when_it_is_open(r402, monkeypatch):
    mesh, rm = r402
    b = D.Bot(stats={}, director=False)
    p = {"pos": (16600.0, Y, -28500.0), "rot": -0.7}
    e = {"ptr": 100, "pos": TGT, "hp": 400, "hp_max": 400}
    snap = {"player": p, "enemies": [e], "nav": mesh, "room_map": rm}
    assert not D.Bot._line_of_sight_ok(p, e, snap), "the arena's west wall between them"
    goal = b._flank_goal(p, e, snap, 1.0)
    assert goal != TGT and D.Bot._line_of_sight_ok({"pos": goal}, e, snap)
    assert math.hypot(goal[0] - p["pos"][0], goal[2] - p["pos"][2]) < 3000.0, "a few steps on, not the whole route"
    there = {"pos": goal, "rot": -0.7}
    assert b._flank_step(there, e, 0.0, dict(snap, player=there), 2.0) is None and b.stats["flank_los_opens"] == 1
    monkeypatch.setattr(D, "FLANK_LOS", False)
    assert D.Bot(stats={}, director=False)._flank_step(p, e, 0.0, snap, 1.0) is not None


# --- the pack he is winning against (PACK_KEEP) --------------------------------------------------------------------------
def _pack(hp=1000):
    b = D.Bot(stats={}, director=False)
    p = {"pos": (0.0, 0.0, 0.0), "rot": 0.0, "hp": hp, "hp_max": 1000, "ptr": 1}
    front = [{"ptr": 100 + i, "pos": (x, 0.0, 4000.0), "hp": 400, "hp_max": 400, "class": 0xAE7050}
             for i, x in enumerate((-300.0, 0.0, 300.0))]
    behind = {"ptr": 200, "pos": (0.0, 0.0, -4500.0), "hp": 400, "hp_max": 400, "class": 0xAE7050}
    live = b._live(p, front + [behind])
    return b, p, live


def test_a_grudge_behind_him_waits_while_he_is_shooting_the_pack_in_front(monkeypatch):
    b, p, live = _pack()
    cur = next(t for t in live if t[2]["ptr"] == 101)
    grudge = next(t for t in live if t[2]["ptr"] == 200)
    b.target, b._last_fire = 101, 9.5
    assert b._keep_pack(p, live, live, grudge, 10.0, "the grudge") is cur and b.stats["pack_keeps"] == 1
    assert "the grudge waits" in b.why and "(3 there)" in b.why
    side = next(t for t in live if t[2]["ptr"] == 102)          # within the gun's swing: taken
    assert b._keep_pack(p, live, live, side, 10.0, "the grudge") is side
    b._last_fire = 7.0                                           # not firing at it now: the grudge
    assert b._keep_pack(p, live, live, grudge, 10.0, "the grudge") is grudge
    monkeypatch.setattr(D, "PACK_KEEP", False)
    b._last_fire = 9.5
    assert b._keep_pack(p, live, live, grudge, 10.0, "the grudge") is grudge


def test_hurt_or_swarmed_he_turns_to_the_grudge():
    b, p, live = _pack()
    grudge = next(t for t in live if t[2]["ptr"] == 200)
    b.target, b._last_fire = 101, 9.5
    b._keep_pack(p, live, live, grudge, 9.0, "the grudge")
    p = dict(p, hp=900)                                          # hit: his life fell
    assert b._keep_pack(p, live, live, grudge, 10.0, "the grudge") is grudge
    s, sp, slive = _pack()
    close = [{"ptr": 300 + i, "pos": (x, 0.0, 800.0), "hp": 400, "hp_max": 400, "class": 0xAE7050}
             for i, x in enumerate((-400.0, 0.0, 400.0))]
    slive = s._live(sp, [t[2] for t in slive] + close)
    s.target, s._last_fire = 101, 9.5
    g = next(t for t in slive if t[2]["ptr"] == 200)
    assert s._keep_pack(sp, slive, slive, g, 10.0, "the grudge") is g, "three at arm's length: swarmed"


# --- the controls on the tactical frame ----------------------------------------------------------------------------------
def test_controls_name_the_keys_the_sticks_and_the_gun():
    c = T.controls({"hold": {"lup", "lleft", "b"}})
    assert c["keys"] == ["b", "lleft", "lup"] and c["tap"] is None
    assert c["stick"]["left"] == {"deg": 45.0, "mag": 1.0} and c["stick"]["right"]["mag"] == 0.0
    assert c["stick"]["aim"] is False
    c = T.controls({"hold": {"zl", "rright"}, "tap": "zr"}, aim_stick="right")
    assert c["tap"] == "zr" and c["stick"]["aim"] is True and c["stick"]["right"]["deg"] == -90.0
    assert c["stick"]["aim_stick"] == "right"
    assert T.controls({"hold": {"ldown", "b"}})["stick"]["left"]["deg"] == 180.0, "the quick turn: back"
    assert T.controls(None) == {"keys": [], "tap": None, "stick": {"left": {"deg": 0.0, "mag": 0.0},
                                                                    "right": {"deg": 0.0, "mag": 0.0}, "aim": False}}


def test_the_frame_carries_what_he_pressed():
    out = T._clean_plan({"phase": "fire", "controls": T.controls({"hold": {"zl"}, "tap": "zr"})}, {}, {})
    assert out["keys"] == ["zl"] and out["tap"] == "zr" and out["stick"]["aim"] is True
    assert out["stick"]["left"] == {"deg": 0.0, "mag": 0.0}
    assert "keys" not in T._clean_plan({"phase": "walk"}, {}, {})
    json.dumps(out)


def test_the_bots_plan_has_this_ticks_controls(r402):
    mesh, rm = r402
    bot = D.Bot(clock=lambda: 100.0)
    snap = {"player": {"pos": (16507.0, Y, -27244.0), "rot": -0.7, "hp": 1000, "hp_max": 1000}, "enemies": [],
            "nav": mesh, "room_map": rm, "timer": 90.0, "kills": 0, "combo": 0, "combo_timer": 0.0}
    act = bot.tick(snap)
    plan = T.take_plan(bot)
    assert plan["controls"]["keys"] == sorted(act.get("hold") or ()) and plan["controls"]["tap"] == act.get("tap")
    frame = T._clean_plan(plan, {}, {})
    assert frame["keys"] == sorted(act.get("hold") or ())
