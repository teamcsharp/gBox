"""The combo as a clock the RE5 Switch bot plays by (operator 2026-11-09, a 22 combo expiring in front of a Majini):
"it is important that they dispatch a foe every 3 seconds and never fail at it. The mode is a ballet and it's important to
never ever lose the combo. Have the bot understanding the combo and the amount of time left in it at all times and
manage it." And the maps of the same hour: "The bot needs to know that these enemies are on the map and that he needs to
go and dispatch them" - headed for a time bonus, six Majini alive behind a ladder / drop.

Live that round: combo_breaks 10 (9 with a Majini in reach), bonus_runs 36 for 1 statue, pursuits 0, longest idle 161 s."""
import math

import pytest

from gbox.mercs.core import doctrine
from gbox.mercs.titles import re5_nav
from gbox.mercs.titles import re5_switch as R


@pytest.fixture
def bot():
    b = object.__new__(R.Bot)
    b.stats = {k: 0 for k in R.COMBO_COUNTERS + R.BONUS_COUNTERS + R.PURSUIT_COUNTERS}
    b._combo_prev, b._combo_window, b._now, b._pur, b._pur_end_at = 0, None, None, None, -1e9
    b._bonus, b._bonus_block, b.aim_since, b._goal_dy = None, {}, None, None
    b._mesh, b._nav, b._mesh_link = None, None, False
    b.doing = b.why = ""
    b._turn = lambda err, tol=0.0: () if abs(err) <= tol else (("rleft",) if err > 0 else ("rright",))
    b._gun_down = lambda: None
    return b


def player(pos=(0.0, 0.0, 0.0), rot=0.0):
    return {"ptr": 1, "pos": pos, "rot": rot, "hp": 1000, "hp_max": 1000}


def test_the_pace_is_the_doctrines_three_seconds_and_the_push_starts_then():
    assert doctrine.KILL_PACE_S == 3.0 and R.KILL_PACE_S == 3.0
    assert R.COMBO_URGENT_S == R.COMBO_WINDOW_S - 3.0 == 7.0
    assert R.PURSUE_S >= R.COMBO_WINDOW_S                    # a combo with nobody in reach: off at once, not at 6 s
    assert doctrine.combo_left({"combo": 22, "combo_timer": 4.25}) == 4.25
    assert doctrine.combo_left({"combo": 0, "combo_timer": 4.25}) is None
    assert doctrine.combo_left({"combo": 3, "combo_timer": None}) is None
    assert doctrine.combo_left({}) is None


def test_he_reads_the_window_every_tick_and_pushes_from_three_seconds_after_a_kill(bot):
    bot._track_combo({"combo": 22, "combo_timer": 9.4})
    assert bot.stats["combo_left_s"] == 9.4 and bot.stats["combo_since_kill_s"] == 0.6
    assert not bot._combo_urgent({"combo": 22, "combo_timer": 9.4})          # he just killed
    assert not bot._combo_urgent({"combo": 22, "combo_timer": 7.1})
    assert bot._combo_urgent({"combo": 22, "combo_timer": 7.0})              # three seconds on: the next one is owed
    assert bot._combo_urgent({"combo": 22, "combo_timer": 0.4})
    assert not bot._combo_urgent({"combo": 0, "combo_timer": 0.0})
    bot._track_combo({"combo": 0, "combo_timer": 0.0})
    assert bot.stats["combo_left_s"] is None and bot.stats["combo_breaks"] == 1


STATUE_FAR = {"ptr": 0x51, "pos": (1500.0, 0.0, 0.0), "secs": 30}
STATUE_NEAR = {"ptr": 0x52, "pos": (0.0, 0.0, 250.0), "secs": 30}
STATUE_8M = {"ptr": 0x53, "pos": (0.0, 0.0, 790.0), "secs": 30}
MAJINI = {"ptr": 0x11, "pos": (-3000.0, 0.0, 4000.0), "hp": 800}


def bonus(bot, snap):
    flat = lambda e: math.hypot(e["pos"][0], e["pos"][2])
    return bot._go_bonus(player(), [], flat, snap, 50.0)


def test_a_statue_waits_while_a_majini_is_alive_anywhere(bot):
    """The operator's map: "Nearest: Time bonus 15 m" and him headed for it, 234 kills for a minute."""
    snap = {"bonuses": [STATUE_FAR], "enemies": [MAJINI], "timer": 780.0, "combo": 0}
    assert bonus(bot, snap) is None and bot.stats["bonus_deferred"] == 1 and bot._bonus is None
    assert bonus(bot, dict(snap, enemies=[])) is not None                     # nobody left alive: the statue
    bot._bonus = None
    assert bonus(bot, dict(snap, timer=R.BONUS_NEED_S)) is not None           # the clock needs it
    assert bot.stats["bonus_runs"] == 2


def test_a_statue_beside_him_is_taken_unless_the_combo_window_runs_down(bot):
    snap = {"bonuses": [STATUE_NEAR], "enemies": [MAJINI], "timer": 780.0, "combo": 0}
    assert bonus(bot, snap) is not None                                       # he is passing it: his floor, no combo
    bot._bonus = None
    assert bonus(bot, dict(snap, bonuses=[STATUE_8M])) is None                # 7.9 m off is a trip: the Majini first
    bot._bonus = None
    assert bonus(bot, dict(snap, combo=9, combo_timer=9.5)) is not None       # ... or right after a kill
    assert bonus(bot, dict(snap, combo=9, combo_timer=6.0)) is None           # the window running: the Majini first
    assert bot._bonus is None


# --- the mesh's ladders and drops ------------------------------------------------------------------------------------
class Mesh:
    """Two floors joined by one action link at x = 1000: the route is the link, then the goal."""
    sig = "two-floors"

    def __init__(self):
        self.asked = []

    def route(self, start, goal, avoid=()):
        self.asked.append(tuple(avoid))
        if avoid:
            return None                                      # the only link refused: no way
        link = re5_nav.Traversal((1100.0, -300.0, 0.0), (970.0, 0.0, 0.0), (1000.0, 0.0, 0.0))
        return [link, tuple(goal)]


def test_at_a_links_foot_he_pushes_on_through_it_and_gives_up_one_that_never_lets_him_through(bot):
    bot._mesh = mesh = Mesh()
    goal = (2000.0, -300.0, 0.0)
    wp = bot._mesh_waypoint(player(), goal, 10.0)
    assert wp == (970.0, 0.0) and not bot._mesh_link         # far from it: to its foot, on his own floor
    foot = player(pos=(950.0, 0.0, 0.0))
    wp = bot._mesh_waypoint(foot, goal, 10.2)
    assert bot._mesh_link and wp[0] == pytest.approx(1000.0 + R.MESH_LINK_PUSH_CM) and wp[1] == 0.0
    assert bot._goal_dy == -300.0 and bot.stats["mesh_links_tried"] == 1      # (the prompt rule presses its prompt)
    assert bot._mesh_waypoint(foot, goal, 10.2 + R.MESH_LINK_TRY_S - 0.1) is not None
    assert bot._mesh_waypoint(foot, goal, 10.3 + R.MESH_LINK_TRY_S) is None   # never through: the Majini's only
    assert bot.stats["mesh_links_refused"] == 1 and bot._mesh_avoid(mesh) == [(1000.0, 0.0, 0.0)]
    assert bot._mesh_waypoint(foot, goal, 20.0) is None and mesh.asked[-1] == ((1000.0, 0.0, 0.0),)
    assert bot.stats["mesh_no_route"] >= 1


def test_the_locate_run_takes_the_mesh_across_floors_and_keeps_its_majini(bot):
    bot._mesh = Mesh()
    bot._door_spots = lambda: []
    below = {"ptr": 0x21, "pos": (2000.0, -300.0, 0.0), "hp": 800}
    other = {"ptr": 0x22, "pos": (-2400.0, 0.0, 0.0), "hp": 800}
    act = bot._locate(player(), {"enemies": [below, other]}, 10.0)
    assert act["hold"][:2] == ("lup", "b") and "mesh" in bot.why
    first = bot._locate_key
    # the other one a little nearer now: he keeps the one he set off for (LOCATE_SWITCH)
    nearer = dict(below if first == 0x22 else other)
    nearer["pos"] = tuple(0.9 * v for v in nearer["pos"])
    rest = other if first == 0x22 else below
    bot._locate(player(), {"enemies": [rest, nearer]}, 10.1)
    assert bot._locate_key == first and bot.stats["locates"] == 1


class Wall:
    """A mesh whose floor ends right ahead of him along his facing; clear 45 degrees to his right."""

    def member(self, pos):
        return 1

    def floor_segment(self, a, b):
        return b[0] < a[0] - 50.0                            # only headings well to his right (x falling) are floor


def test_the_guard_follows_the_route_instead_of_turning_him_away_from_its_corner(bot):
    """Live 2026-11-09: the route turned him to its next corner, the guard (its probe clipping the wall beside that
    corner) turned him away, every tick - 'b,rright' held for 80 s, a target 30 m off, 245 steers in 8 s."""
    snap = {"nav": Wall(), "player": player()}
    walk = {"hold": ("lup", "b", "rleft")}
    bot._now, bot._mesh_wp = 5.0, None
    turned = bot._mesh_guard(dict(walk), snap)               # no route this tick: the guard's own heading, as before
    assert "rright" in turned["hold"] and bot.stats["mesh_steers"] == 1
    bot._mesh_wp = (20.0, 400.0, 5.0)                        # the route's point 3 degrees off his facing: walk on
    assert bot._mesh_guard(dict(walk), snap) == walk and bot.stats["mesh_follows"] == 1
    bot._mesh_wp = (400.0, 100.0, 5.0)                       # the route's point 76 degrees to his left: round to it first
    assert bot._mesh_guard(dict(walk), snap)["hold"] == ("lleft", "rleft")   # toward it while he turns: no B, no spot
    bot._mesh_wp = (20.0, 400.0, 4.9)                        # a route of an earlier tick is not this tick's
    assert "rright" in bot._mesh_guard(dict(walk), snap)["hold"]


def test_he_never_stands_a_step_along_open_floor_after_three_seconds_on_one_spot(bot):
    """Operator 2026-11-09: "There is never ever ever a reason to stand still. it makes no sense. Its inorganic." Live
    that hour: seven minutes on one spot, 'b,rleft' held (with B held he does not turn), 15 Majini alive."""
    snap = {"nav": Wall(), "player": player(), "mercenaries_phase": R.PHASE_PLAYING}
    spin = {"hold": ("b", "rleft")}
    bot.doing = "walk"
    assert bot._never_stand(dict(spin), snap, 10.0) == spin                      # the first look
    assert bot._never_stand(dict(spin), snap, 10.0 + R.STAND_MAX_S - 0.1) == spin
    act = bot._never_stand(dict(spin), snap, 10.0 + R.STAND_MAX_S)
    assert bot.stats["stand_breaks"] == 1 and "b" not in act["hold"]
    assert set(act["hold"]) & {"lup", "ldown", "lleft", "lright"}                # the left stick: he moves
    assert act["hold"] == ("lright", "lup")                                      # (this mesh: floor only to his right)
    assert bot._never_stand(dict(spin), snap, 10.5 + R.STAND_MAX_S) == act       # the step, to its end
    moved = dict(snap, player=player(pos=(-200.0, 0.0, 100.0)))
    assert bot._never_stand(dict(spin), moved, 20.0) == spin                     # he moved: nothing to break
    # an aimed shot, a plant, a heal are not standing
    for busy, doing in (({"hold": ("zl", "zr")}, "fire"), ({"hold": ()}, "mine"), ({"hold": ()}, "heal")):
        bot.doing = doing
        for dt in (0.0, 5.0, 10.0):
            assert bot._never_stand(dict(busy), moved, 30.0 + dt) == busy
    assert bot.stats["stand_breaks"] == 1


def test_the_left_stick_goes_toward_the_bearing_he_is_turning_to():
    import math as m
    assert R.Bot._stick_toward(0.0) == ("lup",)
    assert R.Bot._stick_toward(m.radians(80)) == ("lleft",)
    assert R.Bot._stick_toward(m.radians(-40)) == ("lright", "lup")
    assert R.Bot._stick_toward(m.radians(170)) == ("ldown",)
