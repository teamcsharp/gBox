"""The raise / aim discipline (gbox.mercs.core.combat (g); live RE4 Switch 2026-11-10, Krauser on Base, the operator:
"What is the bot doing right now? It's like walking into the wall flickering" - 18 stand breaks and 5 flanks in 70 s,
fire -> turn -> fire, the bow half-raised against a grid wall). The shared rules, RE4 first: the fight meets the
never-stand rule while he fires at a target in range or turns toward it; with the gun up the next target is turned to
with the stick that moves the aim (learned live), the gun down only past AIM_KEEP_RAD; a step goes along open floor.

A synthetic RE4 player (Tank) answers the bot's keys the way the game does: tank controls, no walking with the gun up,
the aim stick turning him while it is up."""
import math

import pytest

from gbox.mercs.core import combat as C
from gbox.mercs.titles import re4_switch as D


class Wall:
    """The stage mesh's clear_segment: a grid wall along x = -50 cm on his left - no segment ends past it."""

    def __init__(self, x_cm=-50.0, ahead_cm=None):
        self.x, self.ahead = x_cm * D.MM_PER_CM, None if ahead_cm is None else ahead_cm * D.MM_PER_CM

    def clear_segment(self, a, b):
        return b[0] > self.x and (self.ahead is None or b[2] < self.ahead)

    def floor_segment(self, a, b):
        return self.clear_segment(a, b)


class Tank:
    """RE4's controls as the game answers them: gun down, the left stick turns him (TURN_RATE) and up walks him; gun
    up (ZL), he stands and `aim_stick`'s left / right turns him (AIM_RATE) - the other stick does nothing; a FIRE tap
    with the gun up costs the bot's target 200 health. The mesh stops a walk at its wall."""
    TURN_RATE, AIM_RATE, WALK_CM_S = 2.5, 1.5, 300.0

    def __init__(self, enemies, rot=0.0, aim_stick="right", mesh=None):
        self.pos, self.rot, self.aim_stick, self.mesh = [0.0, 0.0, 0.0], rot, aim_stick, mesh
        self.enemies = [dict(e) for e in enemies]
        self.walked_into_wall = 0
        self.blocked_ticks = []                                       # per tick: did he push into the wall
        self._quick = False

    def snap(self):
        return {"player": {"pos": tuple(self.pos), "rot": self.rot, "hp": 1000, "ptr": 1},
                "enemies": [dict(e) for e in self.enemies], "nav": self.mesh}

    def apply(self, bot, act, dt):
        hold, tap = set(act.get("hold") or ()), act.get("tap")
        keys = hold | ({tap} if tap else set())
        if D.AIM_BTN in hold:
            left, right = ("rleft", "rright") if self.aim_stick == "right" else ("lleft", "lright")
            rate = self.AIM_RATE * (dt if tap not in (left, right) else 0.3 * dt)
            self.rot += rate * ((left in keys) - (right in keys))
            if tap == D.FIRE_BTN:
                for e in self.enemies:
                    if e["ptr"] == bot.target and e["hp"] > 0:
                        e["hp"] = max(0, e["hp"] - 200)
            self.blocked_ticks.append(False)                          # (no walking with the gun up)
            return
        quick = set(D.QUICK_TURN) <= hold
        if quick and not self._quick:                                 # the 180 turn: one press, one half turn
            self.rot += math.pi
        self._quick = quick
        self.rot += self.TURN_RATE * dt * (("lleft" in hold) - ("lright" in hold))
        pushed = False
        if "lup" in hold:
            step = self.WALK_CM_S * dt * D.MM_PER_CM * (2.0 if D.RUN_BTN in hold else 1.0)
            end = (self.pos[0] + step * math.sin(self.rot), 0.0, self.pos[2] + step * math.cos(self.rot))
            if self.mesh is not None and not self.mesh.clear_segment(tuple(self.pos), end):
                self.walked_into_wall += 1
                pushed = True
            else:
                self.pos[0], self.pos[2] = end[0], end[2]
        self.blocked_ticks.append(pushed)


def ganado(ptr, heading, dist_cm, hp=400):
    return {"ptr": ptr, "hp": hp, "hp_max": 400, "class": 0xAE7050,
            "pos": (dist_cm * D.MM_PER_CM * math.sin(heading), 0.0, dist_cm * D.MM_PER_CM * math.cos(heading))}


def run(bot, game, seconds, dt=0.05, t0=0.0):
    trace = []
    for k in range(int(round(seconds / dt))):
        now = t0 + k * dt
        act = bot.tick(game.snap(), now=now)
        trace.append((now, act, bot.doing))
        game.apply(bot, act, dt)
    return trace


def gun_downs(trace):
    """How many times the gun went down (ZL held one tick, not the next) while a Ganado lived."""
    up = [D.AIM_BTN in set(a.get("hold") or ()) for _, a, _ in trace]
    return sum(1 for a, b in zip(up, up[1:]) if a and not b)


def the_live_moment():
    """Krauser at the grid wall (x = -50 cm): three Ganados in range on clear lines on its open side, each 0.5-0.6 rad
    from the last - past RAISE_TOL, inside AIM_KEEP_RAD."""
    return [ganado(100, 0.3, 800.0), ganado(101, 0.9, 900.0), ganado(102, 1.4, 1000.0)]


def test_the_live_moment_no_flicker_no_step_into_the_wall():
    game = Tank(the_live_moment(), mesh=Wall())
    b = D.Bot(stats={}, director=False)
    trace = run(b, game, 6.0)
    assert b.stats["shots"] >= 6 and all(e["hp"] == 0 for e in game.enemies), "all three shot down"
    end = next(i for i, (_, _, d) in enumerate(trace) if d in ("locate", "sweep"))   # the last kill
    assert b.stats["stand_breaks"] == 0 and not any(game.blocked_ticks[:end]), "no step, nothing into the wall"
    assert gun_downs(trace[:end]) == 0, "the gun stays up from the first raise to the last kill"


def test_the_rollback_flickers_as_live(monkeypatch):
    monkeypatch.setattr(D, "UNIVERSAL_CORE", False)
    game = Tank(the_live_moment(), mesh=Wall())
    b = D.Bot(stats={}, director=False)
    trace = run(b, game, 6.0)
    assert gun_downs(trace) >= 1, "the first version lowers the gun for each turn past RAISE_TOL"


def test_with_the_right_stick_dead_he_learns_the_left_one_and_keeps_the_gun_up():
    game = Tank([ganado(100, 0.6, 800.0)], aim_stick="left", mesh=Wall())
    b = D.Bot(stats={}, director=False)
    run(b, game, 4.0)
    assert b.stats["aim_stick"] == "left" and b.stats["aim_stick_switches"] == 1
    assert b.stats["shots"] >= 1 and game.enemies[0]["hp"] < 400


def test_turning_toward_a_target_in_range_is_not_standing():
    """A slow tank turn to one 1.5 rad off takes seconds: the facing moving is the fight, not a reason to step."""
    Slow = type("Slow", (Tank,), {"TURN_RATE": 0.25})
    game = Slow([ganado(100, 1.5, 700.0)])
    b = D.Bot(stats={}, director=False)
    run(b, game, 4.0)
    assert b.stats["stand_breaks"] == 0 and b.stats.get("stand_engaged", 0) > 0


def test_a_turn_that_moves_nothing_still_steps_and_a_frozen_scene_is_still_paged():
    s = {"player": {"pos": (0.0, 0.0, 0.0), "rot": 0.0, "hp": 1000, "ptr": 1},
         "enemies": [ganado(100, math.pi / 2, 500.0)]}
    b = D.Bot(stats={}, director=False)
    for k in range(int((D.STAND_MAX_S + 0.2) / 0.1)):
        b.tick(s, now=0.1 * k)
    assert b.stats["stand_breaks"] == 1, "no facing change: not the fight, a step"


def test_a_step_goes_along_open_floor_never_into_the_wall():
    wall = Wall(ahead_cm=40.0)                                        # walled ahead and on the -x side: +x is open
    s = {"player": {"pos": (0.0, 0.0, 0.0), "rot": 0.0, "hp": 1000, "ptr": 1}, "enemies": [], "nav": wall}
    b = D.Bot(stats={}, director=False)
    act, k = None, 0
    while b.stats["stand_breaks"] == 0 and k < 100:                   # nobody on the map: the sweep, standing
        act, k = b.tick(s, now=0.1 * k), k + 1
    goal = b._stand["goal"]
    assert b.doing == "step" and goal is not None and wall.clear_segment((0.0, 0.0, 0.0), goal) and goal[0] > 0
    off = abs(C.wrap(C.heading(goal[0], goal[2])))
    assert off > D.STEP_TURN_RAD and "lup" not in act["hold"], "a goal off his facing: turned to on the spot first"
    boxed = {"player": {"pos": (0.0, 0.0, 0.0), "rot": 0.0, "hp": 1000, "ptr": 1}, "enemies": [],
             "nav": type("Box", (), {"clear_segment": lambda self, a, b: False,
                                     "floor_segment": lambda self, a, b: False})()}
    w = D.Bot(stats={}, director=False)
    for k in range(60):
        w.tick(boxed, now=0.1 * k)
    assert w.stats["stand_breaks"] == 0 and w.stats["steps_walled_in"] >= 1, "walled in on every line: no step"


# --- pressed against a wall (the operator 2026-11-10: "the issue is more like this") ------------------------------------
class Panel:
    """A greybox wall 6 m wide across his way, 1 m in front of him (z = 100 cm, x from -300 to +300 cm): no segment
    crosses it - for his walk (the sim) and his sight (the bot's clear_segment) alike."""
    Z, HALF = 100.0 * D.MM_PER_CM, 300.0 * D.MM_PER_CM

    def clear_segment(self, a, b):
        if (a[2] - self.Z) * (b[2] - self.Z) > 0 or a[2] == b[2]:
            return True                                               # both on one side of it
        t = (self.Z - a[2]) / (b[2] - a[2])
        return abs(a[0] + t * (b[0] - a[0])) > self.HALF              # crossing its line beside it, not through it

    def floor_segment(self, a, b):
        return self.clear_segment(a, b)


def longest_run(flags):
    best = cur = 0
    for f in flags:
        cur = cur + 1 if f else 0
        best = max(best, cur)
    return best


def behind_the_panel():
    """The live shape: a Ganado behind the wall (no clear shot), so the fight walks at him - into the wall."""
    return [ganado(100, 0.0, 900.0)]


def test_pressed_against_a_wall_he_turns_away_and_never_drives_into_it_again():
    game = Tank(behind_the_panel(), mesh=Panel())
    b = D.Bot(stats={}, director=False)
    run(b, game, 10.0)
    press_ticks = int(D.WALL_PRESS_S / 0.05)
    assert b.stats["walls_pressed"] >= 1 and b.stats["unwalls"] >= 1
    assert longest_run(game.blocked_ticks) <= press_ticks + 3, "never longer against it than it takes to notice"
    assert sum(game.blocked_ticks) <= 3 * (press_ticks + 3), "and never back into the same wall over and over"


def test_the_rollback_keeps_walking_into_the_wall(monkeypatch):
    monkeypatch.setattr(D, "UNIVERSAL_CORE", False)
    game = Tank(behind_the_panel(), mesh=Panel())
    b = D.Bot(stats={}, director=False)
    run(b, game, 10.0)
    assert sum(game.blocked_ticks) >= 80, "as live: the stick held into the wall most of the time"


def test_wall_press_remembers_the_wall_and_sends_him_along_it():
    w = C.WallPress({}, press_s=0.5, press_cm=10.0)
    here = (0.0, 0.0, 0.0)
    assert not w.observe(0.0, here, 0.0, True) and not w.observe(0.4, here, 0.0, True)
    assert w.observe(0.6, here, 0.0, True) and w.stats["walls_pressed"] == 1
    assert w.blocked(1.0, (50.0, 0.0, 0.0), 0.2) and not w.blocked(1.0, (50.0, 0.0, 0.0), 1.5)
    assert not w.blocked(1.0, (500.0, 0.0, 0.0), 0.0), "far from that spot: a different place"
    back = w.away(1.0, here, 0.0, dist_cm=200.0)
    assert back == pytest.approx((0.0, 0.0, -200.0), abs=1e-6), "pressed: straight back first"
    along = w.away(1.0, here, 0.0, dist_cm=200.0, tries_deg=(0, 45, -45))
    assert along[2] > 0 and abs(along[0]) > 100.0, "refused straight on: the first open heading beside it"
    assert w.away(1.0, here, 0.0, clear=lambda a, b: False) is None
    frozen = C.WallPress({}, press_s=0.5, press_cm=10.0)
    assert not any(frozen.observe(0.1 * k, here, 0.0, True, in_control=False) for k in range(8))
    assert not frozen.walls, "a scene that takes no input teaches no wall"
    sparse = C.WallPress({}, press_s=0.5, press_cm=10.0)
    sparse.observe(0.0, here, 0.0, True)
    assert not sparse.observe(2.0, here, 0.0, True), "two looks 2 s apart are no press held"


# --- the shared pieces on their own ---------------------------------------------------------------------------------------
def test_stand_engaged_is_the_fight_in_range_firing_or_turning():
    assert C.stand_engaged(True, False, 0.5, False, 1.5) and C.stand_engaged(True, False, 9.0, True, 1.5)
    assert not C.stand_engaged(True, False, 9.0, False, 1.5), "in range, no shot, no turn: standing"
    assert not C.stand_engaged(True, True, 0.1, True, 1.5), "the shot blocked: a step (or the flank)"
    assert not C.stand_engaged(False, False, 0.1, True, 1.5), "nothing in range"


def test_open_step_takes_the_first_open_heading_from_his_facing():
    clear = lambda a, b: b[0] > -10.0                                   # a wall on his left
    end = C.open_step((0.0, 0.0, 0.0), 0.0, clear, 200.0)
    assert end == pytest.approx((0.0, 0.0, 200.0)), "ahead first"
    blocked_ahead = lambda a, b: b[0] > 50.0
    end = C.open_step((0.0, 0.0, 0.0), 0.0, blocked_ahead, 200.0)
    assert end[0] > 50.0 and end[2] > 0.0, "then the nearest open turn: 45 deg right"
    assert C.open_step((0.0, 0.0, 0.0), 0.0, lambda a, b: False, 200.0) is None
    near_foe = C.open_step((0.0, 0.0, 0.0), 0.0, None, 200.0, avoid=[(0.0, 0.0, 210.0)], avoid_r=100.0)
    assert near_foe is not None and near_foe[2] < 200.0, "not ending on a Ganado"


def test_the_aim_stick_is_learned_from_his_facing_only_while_he_is_in_control():
    s = C.AimStick({}, ("right", "left"), n=4)
    for k in range(10):
        s.observe(k * 0.05, 0.0, 1)                                     # never seen in control: proves nothing
    assert s.stick == "right"
    s.control(1.0)
    for k in range(6):
        s.observe(1.0 + k * 0.05, 0.0, 1)
    assert s.stick == "left" and s.stats["aim_stick_switches"] == 1
    for k in range(6):
        s.observe(2.0 + k * 0.05, 0.1 * k, 1)                           # the left stick moves it, with the press
    assert s.ok and s.stick == "left" and s.sign == 1
    flip, facing = C.AimStick({}, ("right",), n=4), 0.0
    for k in range(12):
        facing += 0.1 if flip.sign < 0 else -0.1                      # against the press until the sign flips
        flip.observe(k * 0.05, facing, 1)
    assert flip.sign == -1 and flip.stats["aim_stick_flips"] == 1, "flipped once, then it goes with the press"
    gone = C.AimStick({}, ("right",), n=2)
    gone.control(0.0)
    for k in range(4):
        gone.observe(k * 0.05, 0.0, 1)
    assert not gone.usable()
    gone.control(40.0)
    assert gone.usable(), "every stick ruled out: the first again after RETRY_S"
