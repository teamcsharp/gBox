"""RE5 Switch: every walk goes by the stage's own nav mesh (operator 2026-11-09, with a screenshot of the tactical map:
him in a dead-end room, six Majini two corridors away, the plan line straight through the wall between - "I need the
bot to know and understand where the enemies are on the map and to go and to pursue and to locate them")."""
import math

from gbox.mercs.titles import re5_switch as R
from gbox.mercs.titles.re5_nav import NavMesh


def corridor():
    """An L: a 2 m wide corridor 20 m up +z, then 20 m along +x. The straight line between its two ends is a wall."""
    points = [(0.0, 0.0, 0.0), (200.0, 0.0, 0.0), (200.0, 0.0, 2000.0), (0.0, 0.0, 2000.0),
              (0.0, 0.0, 2200.0), (2000.0, 0.0, 2200.0), (2000.0, 0.0, 2000.0)]
    tris = [(0, 1, 2), (0, 2, 3), (3, 2, 4), (2, 5, 4), (2, 6, 5)]
    links = [[] for _ in tris]
    for u, a in enumerate(tris):
        for edge in range(3):
            pair = {a[edge], a[(edge + 1) % 3]}
            for v, b in enumerate(tris):
                if v != u and pair <= set(b):
                    links[u].append((v, edge, 0))
    return NavMesh(points, tris, links)


def player(pos=(100.0, 0.0, 100.0), rot=0.0):
    return {"ptr": 1, "pos": pos, "rot": rot, "hp": 1000, "hp_max": 1000, "motion": 0}


def bot(mesh):
    b = R.Bot(stats={}, clock=lambda: 1000.0)
    b._mesh = mesh
    return b


GOAL = (1900.0, 0.0, 2100.0)                                 # the far end of the L


def test_the_route_to_an_enemy_round_the_corner_goes_up_the_corridor_not_at_the_wall():
    b = bot(corridor())
    p = player()
    straight = math.degrees(R.heading(GOAL[0] - 100.0, GOAL[2] - 100.0))
    assert 35 < straight < 50                                 # the line to him: through the wall
    wp = b._mesh_waypoint(p, GOAL, 1000.0)
    assert wp is not None and b.stats["mesh_routes"] == 1
    along = math.degrees(R.heading(wp[0] - 100.0, wp[1] - 100.0))
    assert abs(along) < 12 and wp[1] >= 1500.0                # up the corridor to its corner
    assert b._approach(p, GOAL, 1000.0) == b._turn(R.wrap(math.radians(along)), R.TURN_TOL)
    assert b.stats["mesh_route_ticks"] >= 2 and not b.stats.get("nav_direct_ticks")


def test_waypoints_are_dropped_as_he_reaches_them_and_the_plan_is_not_redone_every_tick():
    b = bot(corridor())
    first = b._mesh_waypoint(player(), GOAL, 1000.0)
    at_corner = player(pos=(first[0], 0.0, first[1] - 50.0))
    nxt = b._mesh_waypoint(at_corner, GOAL, 1000.2)           # within MESH_WP_CM of it: on to the next one
    assert nxt != first and nxt[0] > first[0]
    for i in range(20):                                       # a Majini drifting inside his square: the same plan
        b._mesh_waypoint(at_corner, (GOAL[0] + i, 0.0, GOAL[2]), 1000.2 + i * 0.01)
    assert b.stats["mesh_routes"] == 1


def test_no_mesh_or_an_end_off_the_mesh_falls_back_and_says_so():
    b = bot(None)
    assert b._mesh_waypoint(player(), GOAL, 1000.0) is None
    b = bot(corridor())
    off = (1500.0, 0.0, 500.0)                                # in the wall: no floor under it
    assert b._mesh_waypoint(player(), off, 1000.0) is None and b.stats["mesh_no_route"] == 1
    assert isinstance(b._approach(player(), off, 1000.0), tuple)   # (the learned map or the line still answer)


def test_the_run_out_from_a_bomb_follows_the_mesh_not_the_widest_gap():
    from gbox.mercs.titles import re5_switch_mines as MN
    b = bot(corridor())
    b.mines = MN.Mines(b.stats)
    b.mines.state, b.mines.site = "retreat", (100.0, 0.0, 1900.0)       # a bomb at the top of the corridor
    p = player(pos=(100.0, 0.0, 1700.0), rot=math.pi / 2)              # 2 m below it, facing the wall (+x)
    act = b._mine_route(p, {"hold": ("b", "lup", "rleft")}, 1000.0)
    assert {"lup", "b"} <= set(act["hold"]) and b.stats["mine_mesh_retreats"] == 1
    # the only floor away from the bomb is back down the corridor (-z): he turns that way, not on into the wall
    assert "rright" in act["hold"] or "rleft" in act["hold"]
    assert b._mine_route(p, {"hold": ()}, 1000.0) == {"hold": ()}        # the controller's pauses are left alone
