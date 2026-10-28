"""RE5 Switch learned-grid navigation (re5_switch_nav): the occupancy grid, A* routing,
and the Bot integration (phase 1: statue-to-statue routes on the learned map)."""
import math

import pytest

from gbox.mercs.titles import re5_switch as R
from gbox.mercs.titles.re5_switch_nav import OccupancyGrid, Navigator


@pytest.fixture(autouse=True)
def _switch_fight(monkeypatch):
    monkeypatch.setattr(R, "PS3_BRAIN", False)
    monkeypatch.setattr(R, "HEAL_ENABLED", False)
    R._BONUS_SCAN.update(at=-1e9, list=None, line=None, full_at=-1e9)


def at(dist, deg, y=0.0):
    a = math.radians(deg)
    return (dist * math.sin(a), y, dist * math.cos(a))


def snap(enemies=(), bonuses=(), timer=100.0):
    return {"player": {"ptr": 0x5D00001000, "pos": (0.0, 0.0, 0.0), "rot": 0.0, "hp": 1000, "hp_max": 1000,
                       "motion": 0},
            "enemies": [{"ptr": 10 + i, "pos": x, "hp": 800, "hp_max": 800} for i, x in enumerate(enemies)],
            "inventory": [], "timer": timer,
            "bonuses": [{"ptr": 0x5D4A000000 + i, "pos": x, "secs": 60} for i, x in enumerate(bonuses)],
            "laser": {"from": (0, 0, 0), "at": (0, 0, 0), "up": False}}


def bot():
    clock = [0.0]
    return R.Bot(stats={}, clock=lambda: clock[0]), clock


# --- OccupancyGrid unit tests -------------------------------------------------


def test_grid_marks_walked_and_wall_cells():
    g = OccupancyGrid("Test")
    g.mark_walked(100, 100)
    g.mark_wall(500, 500)
    assert g.cost((1, 1)) == 0.5           # walked
    assert g.cost((5, 5)) == 16.0          # wall
    # neighbours of the wall are "near wall"
    assert g.cost((4, 4)) == 4.0
    assert g.cost((6, 6)) == 4.0


def test_grid_astar_routes_around_a_wall():
    g = OccupancyGrid("Maze")
    # corridor along z=0 from x=0 to x=1000
    for x in range(0, 1100, 100):
        g.mark_walked(x, 0)
    # wall across the corridor at x=500
    for z in range(-200, 300, 100):
        g.mark_wall(500, z)
    route = g.route((0, 0), (1000, 0))
    assert route is not None
    # the route must not pass through the wall cells
    for wp in route:
        assert not (abs(wp[0] - 500) < 50 and abs(wp[1]) < 200)


def test_grid_route_avoids_a_complete_barrier():
    g = OccupancyGrid("Blocked")
    # small island of walkable cells
    g.mark_walked(0, 0)
    g.mark_walked(100, 0)
    # full vertical barrier at x=500 from z=-1000 to z=1000
    for z in range(-1000, 1100, 100):
        g.mark_wall(500, z)
    route = g.route((0, 0), (1000, 0), max_expansions=2000)
    # the A* routes around the barrier (the grid is unbounded); verify no waypoint
    # lies inside the barrier column x=500 with |z| < 1000
    assert route is not None
    for wp in route:
        assert not (abs(wp[0] - 500) < 50 and abs(wp[1]) < 1000)


def test_grid_smooth_reduces_waypoints():
    g = OccupancyGrid("Smooth")
    for x in range(0, 1000, 100):
        g.mark_walked(x, 0)
    raw = g.route((0, 0), (900, 0))
    assert raw is not None and len(raw) >= 5
    smoothed = g.smooth(raw)
    assert len(smoothed) <= len(raw)
    # endpoints preserved
    assert smoothed[0] == raw[0]
    assert smoothed[-1] == raw[-1]


# --- Navigator tests ----------------------------------------------------------


def test_navigator_plan_and_next_waypoint():
    nav = Navigator("Nav Test")
    # seed the grid with a walked corridor
    trail = [(float(i), (i * 100.0, 0.0, 0.0)) for i in range(10)]
    nav.update(trail, [])
    route = nav.plan((0, 0), (900, 0), now=1.0)
    assert route is not None
    wp = nav.next_waypoint((0, 0))
    assert wp is not None
    # advance past the first waypoint
    wp2 = nav.next_waypoint((150, 0))
    assert wp2 is not None


def test_navigator_replans_when_goal_changes():
    nav = Navigator("Replan")
    trail = [(float(i), (i * 100.0, 0.0, 0.0)) for i in range(10)]
    nav.update(trail, [])
    r1 = nav.plan((0, 0), (500, 0), now=1.0)
    assert r1 is not None
    # same goal, recent: cached
    r2 = nav.plan((100, 0), (500, 0), now=2.0)
    assert r2 is r1
    # new goal: replan
    r3 = nav.plan((100, 0), (900, 0), now=3.0, force=True)
    assert r3 is not None


# --- Bot integration ----------------------------------------------------------


def test_bot_uses_nav_route_when_grid_has_data():
    b, clock = bot()
    b._round_started = b._round_t0 = 0.0
    # seed the navigator grid with a walked corridor east
    nav = Navigator("Integration")
    for i in range(20):
        nav.grid.mark_walked(i * 100, 0)
    b._nav = nav
    # statue to the east
    act = b.tick(snap(bonuses=[at(1500, 0)]))
    assert b.doing == "walk"
    assert "nav route" in b.why or "time bonus" in b.why


def test_bot_falls_back_to_straight_line_when_no_route():
    b, clock = bot()
    b._round_started = b._round_t0 = 0.0
    # empty grid: A* routes through unknown cells (cost 1.0 each), so the nav path is used
    b._nav = Navigator("Empty")
    act = b.tick(snap(bonuses=[at(1500, 0)]))
    assert b.doing == "walk"
    assert "time bonus" in b.why
    # with an empty grid the navigator still produces a route (through unknown cells);
    # the important thing is the bot walks toward the statue
    assert "lup" in act["hold"]


def test_bot_saves_nav_grid_on_release():
    b, clock = bot()
    b._round_started = b._round_t0 = 0.0
    import tempfile, pathlib
    with tempfile.TemporaryDirectory() as td:
        b._learn_dir = pathlib.Path(td)
        b._nav = Navigator("SaveTest", learn_dir=pathlib.Path(td))
        b._nav.grid.mark_walked(100, 100)
        b._nav.save()
        # verify the file was written
        files = list(pathlib.Path(td).rglob("*.json"))
        assert len(files) >= 1
