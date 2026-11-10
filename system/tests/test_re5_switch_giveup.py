"""RE5 Switch: the target he can neither shoot nor reach is given up, the reachable ones come first, and with every
Majini on another floor he goes there by the stage's mesh (live 2026-11-10 01:29-01:37 UTC, Prison, No Mercy: kills
389 of 400 for over three minutes, doctrine_since_kill_s 186 - his own choice kept a Majini on the upper walkway,
+317 cm and 13 m off, "target 7.2 m behind geometry at 1.7 m" over and over, while one on his own floor 44 m off was
never pursued). And the crows (hp_max 1, the tactical frame's rule) are no candidates while a Majini lives (01:42 UTC:
the frame listed no enemy while the plan aimed at one "7.9 m behind geometry")."""
import math

import pytest

from gbox.mercs.titles import re5_switch as R

MUZZLE = (0.0, 140.0, 30.0)
W, F = 10, 11                                                    # the walkway one (first row), the floor one (second)


@pytest.fixture(autouse=True)
def _switch_fight(monkeypatch):
    monkeypatch.setattr(R, "PS3_BRAIN", False)
    monkeypatch.setattr(R, "CROWD_FIRE", False)
    monkeypatch.setattr(R, "HEAL_ENABLED", False)


def at(dist, deg, y=0.0):
    a = math.radians(deg)
    return (dist * math.sin(a), y, dist * math.cos(a))


def chest(foot):
    return (foot[0], foot[1] + R.CHEST_H, foot[2])


def along(target, short):
    """A point on the line muzzle -> target, `short` cm before it: the dot on geometry in front of him."""
    d = math.dist(MUZZLE, target)
    return tuple(MUZZLE[k] + (target[k] - MUZZLE[k]) * (d - short) / d for k in range(3))


def row(i, pos, hp=800, hp_max=800, **more):
    return {"ptr": 10 + i, "pos": pos, "hp": hp, "hp_max": hp_max, **more}


def snap(enemies, dot=None, motion=0, nav=None):
    rows = [e if isinstance(e, dict) else row(i, e) for i, e in enumerate(enemies)]
    s = {"player": {"ptr": 0x5D00001000, "pos": (0.0, 0.0, 0.0), "rot": 0.0, "hp": 1000, "hp_max": 1000,
                    "motion": motion},
         "enemies": rows, "inventory": [],
         "laser": {"from": MUZZLE, "at": dot, "up": True} if dot else {"from": (0, 0, 0), "at": (0, 0, 0), "up": False}}
    if nav is not None:
        s["nav"] = nav
    return s


class Mesh:
    """The stage's mesh, as far as these rules ask it: a route (by the stairs at STAIRS) to the goals in `reach`."""
    sig = "test-stairs"
    STAIRS = (600.0, 0.0, 0.0)

    def __init__(self, reach=()):
        self.reach, self.calls = list(reach), 0

    def route(self, start, goal, avoid=(), **_kw):
        self.calls += 1
        if any(math.dist(goal, g) < 1.0 for g in self.reach):
            return [self.STAIRS, tuple(goal)]
        return None


def bot(mesh=None):
    clock = [0.0]
    b = R.Bot(stats={}, clock=lambda: clock[0])
    b._mesh = mesh
    return b, clock


def wall_dots(foot):
    """A dot short of him on geometry 5 m out, a centimetre off each tick (a live ray: never the frozen dot)."""
    k = 0
    while True:
        x, y, z = along(chest(foot), math.dist(MUZZLE, chest(foot)) - 500.0)
        yield (x + 0.5 * (k % 7), y, z)
        k += 1


def moving(hold) -> bool:
    return bool(set(hold) & {"lup", "ldown", "lleft", "lright"})


# --- the give-up after the timeout -----------------------------------------------------------------------------------
def test_a_majini_he_cannot_shoot_and_does_not_close_on_is_given_up_and_the_choice_moves_on():
    behind, floor = at(900, 0), at(1600, 50)                     # both on his floor; the near one behind a wall
    b, clock = bot()
    b.tick(snap([behind, floor], motion=22))
    assert b.target == W                                          # the cheaper one: the one behind the wall
    dots, gave_at = wall_dots(behind), None
    for k in range(3, 81):                                        # 0.3 .. 8 s, the dot on the wall in front of him
        clock[0] = 0.1 * k
        b.tick(snap([behind, floor], dot=next(dots), motion=26))
        if b.stats["target_giveups"]:
            gave_at = clock[0]
            break
    assert gave_at is not None, "never given up: the gun stayed on the wall in front of him"
    assert R.TARGET_GIVEUP_AFTER_S <= gave_at <= 6.0
    assert b.stats["wall_blocks"] >= 1 and W in b._giveup and F not in b._giveup
    assert "geometry" in b.stats["target_giveup_reason"] and "left for 12 s" in b.stats["target_giveup_reason"]
    assert "gave up 10" in b.stats["ex_target_giveup"]
    # the choice is on the other one now, and stays there while the first is given up
    for k in range(1, 30):
        clock[0] = gave_at + 0.1 * k
        b.tick(snap([behind, floor], motion=0))
        assert b.target != W, "the given-up one came back inside its give-up"
    assert b.target == F
    # given up for TARGET_GIVEUP_S, then his again; a second give-up of the same one lasts twice as long
    assert b._giveup[W]["until"] == pytest.approx(gave_at + R.TARGET_GIVEUP_S)
    clock[0] = gave_at + R.TARGET_GIVEUP_S + 0.1
    assert W in [e["ptr"] for e in b._giveup_pool(snap([])["player"], [row(0, behind), row(1, floor)], clock[0])]
    b._noshot_note(snap([])["player"], row(0, behind), clock[0], "test")
    clock[0] += R.TARGET_GIVEUP_AFTER_S + 0.1
    b._giveup_pool(snap([])["player"], [row(0, behind), row(1, floor)], clock[0])
    assert b._giveup[W]["until"] == pytest.approx(clock[0] + 2 * R.TARGET_GIVEUP_S)


def test_the_only_one_left_unshootable_he_goes_to_him_and_never_stands_with_the_gun_on_the_wall():
    behind = at(900, 0)                                           # nobody else: the old wall block changed nothing
    b, clock = bot()
    b.tick(snap([behind], motion=22))
    dots = wall_dots(behind)
    for k in range(3, 61):
        clock[0] = 0.1 * k
        act = b.tick(snap([behind], dot=next(dots), motion=26))
        if b.stats["target_giveups"]:
            break
    assert b.stats["target_giveups"] == 1
    clock[0] += 0.1
    act = b.tick(snap([behind], motion=0))
    assert "zl" not in act["hold"] and moving(act["hold"]), act      # off the wall, on the move: the locate run
    assert b.doing == "walk" and "locating" in b.why


def test_closing_on_him_renews_the_clock():
    b, _clock = bot()
    p0 = {"pos": (0.0, 0.0, 0.0), "rot": 0.0}
    e = row(0, at(1500, 0))
    b._noshot_note(p0, e, 0.0, "his shots end on geometry")
    for k in range(1, 8):                                         # he walks at him 2 m a second, the evidence kept warm
        t = 0.5 * k
        b._noshot[10]["last"] = t
        b._giveup_pool({"pos": (0.0, 0.0, 200.0 * t), "rot": 0.0}, [e], t)
    assert b.stats["target_giveups"] == 0 and 10 not in b._giveup
    last_closer, gave_at = b._noshot[10]["best_at"], None
    for k in range(1, 12):                                        # then he stands: given up within the timeout
        t = 3.5 + 0.5 * k
        b._noshot[10]["last"] = t
        b._giveup_pool({"pos": (0.0, 0.0, 700.0), "rot": 0.0}, [e], t)
        if 10 in b._giveup:
            gave_at = t
            break
    assert b.stats["target_giveups"] == 1 and gave_at is not None
    assert gave_at - 0.5 < last_closer + R.TARGET_GIVEUP_AFTER_S <= gave_at   # once he had not closed for the timeout


# --- the reachable first -----------------------------------------------------------------------------------------------
WALKWAY, FLOOR = at(800, 0, y=280.0), at(3000, 40)                # 2.8 m up 8 m ahead; 30 m off on his floor


def test_the_reachable_one_comes_before_one_up_on_a_walkway_with_no_way_up():
    b, clock = bot(Mesh(reach=[]))                                # the mesh has no route to the walkway
    act = b.tick(snap([WALKWAY, FLOOR], motion=0, nav=b._mesh))
    assert b.target == F and b.stats["unreachable_skip_ticks"] == 1
    assert b.doing == "walk" and "zl" not in act["hold"] and moving(act["hold"])   # (30 m: he runs to him)
    # without the rule the walkway one is the cheaper choice (the live lock)
    b2, _ = bot(Mesh(reach=[]))
    assert b2._choose(snap([])["player"], [row(0, WALKWAY), row(1, FLOOR)], 0.0)["ptr"] == W


def test_one_on_another_floor_the_mesh_reaches_stays_a_choice():
    b, clock = bot(Mesh(reach=[WALKWAY]))
    b.tick(snap([WALKWAY, FLOOR], motion=0, nav=b._mesh))
    assert b.target == W and b.stats["unreachable_skip_ticks"] == 0
    assert b._reach_c[W][1] is True and b._reach_c[W][2] == pytest.approx(600.0 + math.dist(Mesh.STAIRS, WALKWAY))


def test_no_mesh_read_his_floor_first_and_the_off_floor_one_when_he_is_the_only_one():
    b, clock = bot(None)
    b.tick(snap([WALKWAY, FLOOR], motion=0))
    assert b.target == F
    b2, _ = bot(None)
    b2.tick(snap([WALKWAY], motion=0))
    assert b2.target == W                                         # nobody reachable: he is still the target


def test_a_bot_built_before_a_hot_reload_runs_the_new_rules():
    # gbox.hot_reload rebinds the live bot to the new class without this version's __init__
    b, clock = bot()
    for k in ("_noshot", "_giveup", "_giveup_n", "_reach_c", "_reach_budget", "_off_run"):
        del b.__dict__[k]
    for k in R.GIVEUP_COUNTERS:
        b.stats.pop(k)
    b.tick(snap([WALKWAY, FLOOR], motion=0))
    assert b.target == F and b.stats["unreachable_skip_ticks"] == 1


def test_the_mesh_is_asked_once_per_majini_per_check_and_a_few_a_tick():
    mesh = Mesh(reach=[])
    b, _ = bot(mesh)
    p = snap([])["player"]
    rows = [row(i, at(800 + 100 * i, 10 * i, y=280.0)) for i in range(5)]
    for e in rows:
        b._reach(p, e, 0.0)
    assert mesh.calls == R.REACH_ROUTES_PER_TICK                  # this tick's budget
    for e in rows:
        b._reach(p, e, 0.0)
    assert mesh.calls == R.REACH_ROUTES_PER_TICK
    for i, t in enumerate((0.03, 0.06, 0.09)):
        for e in rows:
            b._reach(p, e, t)
    assert mesh.calls == 5                                        # every one asked once, none again inside REACH_CHECK_S


# --- every one on another floor: by the mesh, not shooting into the walkway ------------------------------------------
def test_with_every_majini_up_on_the_walkway_he_runs_there_by_the_mesh_instead_of_shooting_its_floor():
    up = at(800, 0, y=280.0)
    mesh = Mesh(reach=[up])
    b, clock = bot(mesh)
    b.tick(snap([up], motion=22, nav=mesh))
    dots, ran = wall_dots(up), None
    for k in range(3, 20):
        clock[0] = 0.1 * k
        act = b.tick(snap([up], dot=next(dots), motion=26, nav=mesh))
        if b.stats["off_floor_runs"]:
            ran = act
            break
    assert ran is not None, "he kept the gun on the walkway's underside"
    assert b.stats["wall_blocks"] >= 1 and b.stats["off_floor_runs"] == 1
    assert "zl" not in ran["hold"] and {"lup", "b"} <= set(ran["hold"])
    assert b.doing == "walk" and "to his floor by the stage's mesh" in b.why
    assert b._mesh_wp[:2] == (Mesh.STAIRS[0], Mesh.STAIRS[2])     # toward the stairs, not at the wall under him
    # on to the stairs; he never stands and never raises the gun at the walkway again while the run lasts
    t0 = clock[0]
    for k in range(1, 50):
        clock[0] = t0 + 0.1 * k
        act = b.tick(snap([up], motion=0, nav=mesh))
        assert "zl" not in act["hold"] and moving(act["hold"]), (clock[0], b.doing, b.why, act)
    # (the synthetic snapshot never moves him: the run stalls, the give-up's clock ends it, the locate run goes on)
    assert b.stats["target_giveups"] == 1 and b.stats["off_floor_run_ticks"] >= 10


def test_one_up_there_he_can_shoot_is_shot_not_run_from():
    up = at(800, 0, y=280.0)
    mesh = Mesh(reach=[up])
    b, clock = bot(mesh)
    b.tick(snap([up], motion=22, nav=mesh))
    fired = False
    for k in range(3, 30):
        clock[0] = 0.1 * k
        foot = chest(up)
        act = b.tick(snap([up], dot=(foot[0] + 0.5 * (k % 3), foot[1], foot[2]), motion=26, nav=mesh))
        fired = fired or "zr" in act["hold"]
    assert fired and b.stats["off_floor_runs"] == 0 and b.stats["target_giveups"] == 0


# --- a visible, reachable target is never given up -------------------------------------------------------------------
def test_the_dot_on_him_ends_the_evidence_and_he_is_never_given_up():
    foe = at(900, 0)
    b, clock = bot()
    b.tick(snap([foe], motion=22))
    dots = wall_dots(foe)
    for k in range(3, 9):                                         # a moment on the wall: one wall block, the evidence
        clock[0] = 0.1 * k
        b.tick(snap([foe], dot=next(dots), motion=26))
    assert b.stats["wall_blocks"] == 1 and W in b._noshot
    for k in range(9, 90):                                        # then the dot on him for 8 s
        clock[0] = 0.1 * k
        c = chest(foe)
        b.tick(snap([foe], dot=(c[0] + 0.5 * (k % 3), c[1], c[2]), motion=26))
    assert W not in b._noshot and W not in b._giveup and b.stats["target_giveups"] == 0
    assert b.target == W


def test_one_the_target_feedback_shows_in_front_of_the_gun_is_never_given_up():
    b, _ = bot()
    p = snap([])["player"]
    e = row(0, at(900, 0))
    b._feedback_visible = W
    b._noshot_note(p, e, 0.0, "his shots end on geometry")
    assert W not in b._noshot                                     # no evidence taken while it shows
    b._feedback_visible = None
    b._noshot_note(p, e, 0.0, "his shots end on geometry")
    b._feedback_visible = W                                       # it shows again: the evidence is dropped
    for t in (1.0, 2.0, 3.0, 4.0):
        b._noshot.get(W, {})["last"] = t
        assert W in [x["ptr"] for x in b._giveup_pool(p, [e], t)]
    assert b.stats["target_giveups"] == 0 and W not in b._noshot


def test_one_close_on_his_floor_is_never_given_up_and_one_given_up_comes_back_when_near():
    b, _ = bot()
    p = snap([])["player"]
    near = row(0, at(R.TARGET_GIVEUP_MIN_R - 50.0, 0))
    b._noshot_note(p, near, 0.0, "his shots end on geometry")
    for t in (1.0, 2.0, 3.0, 4.0, 5.0):
        b._noshot[W]["last"] = t
        b._giveup_pool(p, [near], t)
    assert b.stats["target_giveups"] == 0
    b._giveup[W] = {"until": 100.0, "off_floor": False}            # given up farther off: he comes within reach
    assert [x["ptr"] for x in b._giveup_pool(p, [near], 6.0)] == [W] and b.stats["target_giveup_lifts"] == 1
    b._giveup[W] = {"until": 100.0, "off_floor": True}             # given up up there: now on his floor
    farther = row(0, at(1500, 0))
    assert [x["ptr"] for x in b._giveup_pool(p, [farther], 7.0)] == [W] and b.stats["target_giveup_lifts"] == 2


def test_the_operators_mark_is_never_given_up():
    b, clock = bot()
    marked = row(0, at(900, 0))
    b._giveup[W] = {"until": 100.0, "off_floor": False}
    p = snap([])["player"]
    flat = lambda e: math.hypot(e["pos"][0], e["pos"][2])
    b._goal_decide(p, [marked], flat, marked, flat(marked), snap([at(900, 0)]), 1.0)
    assert b.target == W and not b._goal_fighting                  # the mark's fight is on him as it is
    act = b._decide(p, [marked], flat, marked, flat(marked), snap([at(900, 0)]), 1.1)
    assert b.doing == "walk" and "locating" in b.why and "zl" not in act["hold"]   # (his own play: no fight on him)


# --- crows --------------------------------------------------------------------------------------------------------------
CROW = row(40, at(600, 0, y=250.0), hp=1, hp_max=1, **{"class": "uEm62"})   # perched up ahead, behind the rail
MAJINI = row(1, at(1200, 30), **{"class": "uEm10"})


def test_a_crow_behind_a_wall_is_never_the_target_ahead_of_a_majini_on_the_floor():
    b, clock = bot()
    assert b._choose(snap([])["player"], [CROW, MAJINI], 0.0)["ptr"] == CROW["ptr"]   # (the old choice: the crow)
    b, clock = bot()
    b.tick(snap([CROW, MAJINI], motion=22))
    dots = wall_dots(CROW["pos"])
    for k in range(3, 40):
        clock[0] = 0.1 * k
        b.tick(snap([CROW, MAJINI], dot=next(dots), motion=26))
        assert b.target != CROW["ptr"]
    assert b.target == MAJINI["ptr"]
    assert b.stats["census_count"] == 1 and b.stats["crows_alive"] == 1


def test_crows_are_left_out_only_while_a_majini_lives_and_the_doctrine_sees_the_same():
    s = snap([CROW, MAJINI])
    out = R.without_crows(s)
    assert [e["ptr"] for e in out["enemies"]] == [MAJINI["ptr"]] and len(s["enemies"]) == 2   # (the snapshot as read)
    dead = dict(MAJINI, hp=0)
    only = snap([CROW, dead])
    assert R.without_crows(only) is only                           # no Majini alive: the crows stay (the last resort)
    assert R.without_crows(snap([MAJINI])) is not None and not R.is_crow({"ptr": 1, "pos": (0, 0, 0), "hp": 5})
    v = R.RE5Switch().doctrine_view(s)
    assert v["alive"] == 1 and len(v["foes"]) == 1                 # (the crow 6 m off is neither alive nor a foe)
