"""RE5 Switch wall governor (operator 21:0x: "the bot running with his face in the wall as if he doesn't actually
see"): the forward stick with no progress is a wall - the push stops at once, the spot remembered, a short step back
then the most open known way (his own trail), and no push there again on that heading."""
import math

import pytest

from gbox.mercs.titles import re5_switch as R


@pytest.fixture(autouse=True)
def _switch_fight(monkeypatch):
    monkeypatch.setattr(R, "PS3_BRAIN", False)
    monkeypatch.setattr(R, "HEAL_ENABLED", False)
    monkeypatch.setattr(R, "MINES", False)
    monkeypatch.setattr(R, "CALM", False)


def at(dist, deg, y=0.0):
    a = math.radians(deg)
    return (dist * math.sin(a), y, dist * math.cos(a))


def snap(pos=(0.0, 0.0, 0.0), rot=0.0, bonuses=None, enemies=()):
    s = {"player": {"ptr": 0x5D00001000, "pos": pos, "rot": rot, "hp": 1000, "hp_max": 1000, "motion": 4,
                    "aim_pitch": None},
         "enemies": [{"ptr": 10 + i, "pos": x, "hp": 800, "hp_max": 800} for i, x in enumerate(enemies)],
         "inventory": [], "kills": 0, "laser": {"from": (0, 0, 0), "at": (0, 0, 0), "up": False}}
    if bonuses is not None:
        s["bonuses"] = [{"ptr": 900 + i, "pos": b, "secs": 30} for i, b in enumerate(bonuses)]
    return s


def bot():
    clock = [0.0]
    b = R.Bot(stats={}, clock=lambda: clock[0])
    b._round_started = b._round_t0 = 0.0
    return b, clock


def test_running_into_a_wall_stops_forward_and_only_counts_an_observed_escape():
    b, clock = bot()
    b._trail = [(-10.0, (-600.0, 0.0, 0.0))]                       # a distant point alone cannot verify a straight corridor
    statue = at(1500, 0)
    act = b.tick(snap(bonuses=[statue]))
    assert "lup" in act["hold"]
    for k in range(1, 6):                                          # he does not move: a wall in front
        clock[0] = 0.08 * k
        act = b.tick(snap(bonuses=[statue]))
    assert b.stats["wall_hits"] == 1 and "lup" not in act["hold"] and "ldown" in act["hold"]   # the step back
    assert len(b._walls) == 1 and b.stats["wall_push_s"] <= R.WALL_WINDOW_S + .1
    clock[0] = 0.75
    act = b.tick(snap(bonuses=[statue]))
    assert "lup" not in act["hold"] and b.stats["wall_recoveries"] == 0
    clock[0] = .83
    b.tick(snap(pos=(0.0, 0.0, -25.0), bonuses=[statue]))
    assert b.stats["wall_recoveries"] == 1
    assert b._bonus is None and b._bonus_block[900] > clock[0], "the failed bonus cannot immediately request the same wall"


def test_no_trail_known_back_the_way_he_came():
    b, clock = bot()
    statue = at(1500, 0)
    b.tick(snap(bonuses=[statue]))
    for k in range(1, 6):
        clock[0] = 0.08 * k
        b.tick(snap(bonuses=[statue]))
    assert abs(abs(math.degrees(b._wall_rec["head"])) - 180) < 1


def test_a_remembered_wall_is_not_pushed_again_on_that_heading():
    b, clock = bot()
    b.wall_memory(0.0, 0.0, 0.0)
    act = b.tick(snap(bonuses=[at(1500, 0)]))
    assert b.stats["wall_preempts"] == 1 and "lup" not in act["hold"] and "ldown" in act["hold"]


def test_moving_freely_is_left_alone():
    b, clock = bot()
    statue = at(3000, 0)
    for k in range(10):
        clock[0] = 0.08 * k
        act = b.tick(snap(pos=(0.0, 0.0, 35.0 * k), bonuses=[statue]))
    assert b.stats["wall_hits"] == 0 and "lup" in act["hold"]


def test_aiming_is_not_movement():
    b, clock = bot()
    foe = at(600, 0)
    for k in range(10):
        clock[0] = 0.08 * k
        b.tick(snap(enemies=[foe]))
    assert b.stats["wall_hits"] == 0


def test_no_stick_in_the_boosted_shot_nor_just_after_it():
    """2026-10-28: fire_rate's x80 time scale is put back at the next snapshot; a run or turn begun in that gap teleported
    him. No stick in the shot motion and SHOT_TAIL_S after it."""
    b = R.Bot.__new__(R.Bot)
    b.stats, b.doing, b.quick = {}, "relocate", 0
    snap = {"player": {"motion": R.MOTION_SHOT}}
    out = b._shot_tail({"hold": ("lup", "rleft", "zr")}, snap, 10.0)
    assert out["hold"] == ("zr",)
    out = b._shot_tail({"hold": ("lup",)}, {"player": {"motion": 0}}, 10.0 + R.SHOT_TAIL_S / 2)
    assert out["hold"] == ()                                      # still in the tail
    out = b._shot_tail({"hold": ("lup",)}, {"player": {"motion": 0}}, 10.0 + R.SHOT_TAIL_S + 0.01)
    assert out["hold"] == ("lup",) and b.stats["shot_tail_drops"] == 2


def test_recovery_faces_its_observed_return_segment_before_any_forward_input(monkeypatch):
    b, clock = bot()
    monkeypatch.setattr(b, "_tick", lambda s, now: {"hold": ("lup",)})
    for k in range(5):
        clock[0] = k * .08
        b.tick(snap(pos=(-80. + k * 20., 0., 0.)))
    for k in range(5, 11):
        clock[0] = k * .08
        act = b.tick(snap())
    assert b.stats["wall_hits"] == 1
    assert "lup" not in act["hold"], "forward while still facing the wall repeats the collision"
    assert {"rleft", "rright"} & set(act["hold"])


def test_a_recovery_that_never_moves_is_not_counted_successful(monkeypatch):
    b, clock = bot()
    monkeypatch.setattr(b, "_tick", lambda s, now: {"hold": ("lup",)})
    for k in range(50):
        clock[0] = k * .08
        b.tick(snap())
    assert b.stats["wall_recoveries"] == 0


@pytest.mark.parametrize("doing,hold", [("prompt", ("y",)), ("held", ("a",)), ("heal", ()),
                                       ("quick_turn", ("ldown", "b")), ("fire", ("zl", "zr"))])
def test_recovery_cannot_add_movement_to_priority_actions(doing, hold):
    b, clock = bot()
    b._wall_start(snap()["player"], 0., preempt=False)
    b.doing = doing
    assert b._wall_gov({"hold": hold}, snap(), .1) == {"hold": hold}


def test_shot_tail_suppressed_forward_commands_cannot_teach_a_wall(monkeypatch):
    b, clock = bot()
    monkeypatch.setattr(b, "_tick", lambda s, now: {"hold": ("lup",)})
    for k in range(12):
        clock[0] = k * .08
        s = snap()
        s["player"]["motion"] = R.MOTION_SHOT
        assert "lup" not in b.tick(s)["hold"]
    assert b.stats["wall_hits"] == 0 and not b._walls


def test_recovery_uses_no_forward_guess_when_the_only_trail_is_on_another_floor(monkeypatch):
    b, clock = bot()
    monkeypatch.setattr(b, "_tick", lambda s, now: {"hold": ("lup",)})
    b._trail = [(0., (-600., 500., 0.))]
    for k in range(13):
        clock[0] = k * .08
        act = b.tick(snap())
        if b.stats["wall_hits"]:
            assert "lup" not in act["hold"]


def test_observed_heading_unlocks_only_the_recorded_short_return_segment(monkeypatch):
    b, clock = bot()
    monkeypatch.setattr(b, "_tick", lambda s, now: {"hold": ("lup",)})
    for k in range(5):
        clock[0] = k * .08
        b.tick(snap(pos=(-80. + k * 20., 0., 0.)))
    for k in range(5, 11):
        clock[0] = k * .08
        b.tick(snap())
    clock[0] += .08
    act = b.tick(snap(rot=-math.pi / 2))
    assert "lup" in act["hold"] and b._wall_rec["target"] == (-20., 0., 0.)
    clock[0] += .08
    act = b.tick(snap(pos=(-20., 0., 0.), rot=-math.pi / 2))
    assert "lup" not in act["hold"] and b.stats["wall_recoveries"] == 1


def test_combat_interruptions_do_not_consume_the_recovery_timer(monkeypatch):
    b, clock = bot()
    monkeypatch.setattr(b, "_tick", lambda s, now: {"hold": ("lup",)})
    for k in range(7):
        clock[0] = k * .08
        b.tick(snap())
    assert b._wall_rec is not None
    monkeypatch.setattr(b, "_tick", lambda s, now: {"hold": ("zl", "zr")})
    clock[0] += .08
    assert b.tick(snap())["hold"] == ("zl", "zr") and b._wall_rec is None
    clock[0] += 4.
    b.tick(snap())
    assert b.stats["wall_recoveries"] == 0 and b.stats.get("wall_recovery_failures", 0) == 0


def test_retry_turn_finishes_at_its_fixed_heading(monkeypatch):
    b, clock = bot()
    monkeypatch.setattr(R, "HEADING_GOV", False)
    monkeypatch.setattr(b, "_tick", lambda s, now: {"hold": ("lup",)})
    for k in range(32):
        clock[0] = k * .08
        b.tick(snap())
    assert b.stats.get("wall_recovery_failures") == 1
    # Another wall is known in the return direction; cooldown must stop at its
    # fixed recovery heading, not ask for a fresh 180-degree turn each tick.
    b.wall_memory(0., 0., math.pi)
    monkeypatch.setattr(b, "_tick", lambda s, now: {"hold": ("lup", "rright")})
    clock[0] += .08
    act = b.tick(snap(rot=math.pi))
    assert not {"lup", "rleft", "rright"} & set(act["hold"])


def test_return_follows_small_observed_corner_segments_without_a_diagonal_shortcut(monkeypatch):
    b, clock = bot()
    monkeypatch.setattr(b, "_tick", lambda s, now: {"hold": ("lup",)})
    points = [(-10., 0., -10.), (-5., 0., -10.), (0., 0., -10.), (0., 0., -5.), (0., 0., 0.)]
    for k, point in enumerate(points):
        clock[0] = k * .08
        b.tick(snap(pos=point))
    for k in range(5, 12):
        clock[0] = k * .08
        b.tick(snap())
    assert b._wall_rec["target"] == (0., 0., -5.)
    clock[0] += .08
    b.tick(snap(pos=(0., 0., -5.), rot=math.pi))
    assert b._wall_rec["target"] == (0., 0., -10.)


def test_recovery_consumes_overshot_breadcrumbs_without_turning_back(monkeypatch):
    b, clock = bot()
    monkeypatch.setattr(b, "_tick", lambda s, now: {"hold": ("lup",)})
    points = [(0., 0., -20.), (0., 0., -15.), (0., 0., -10.), (0., 0., -5.), (0., 0., 0.)]
    for k, point in enumerate(points):
        clock[0] = k * .08
        b.tick(snap(pos=point))
    for k in range(5, 12):
        clock[0] = k * .08
        b.tick(snap())
    clock[0] += .08
    act = b.tick(snap(pos=(0., 0., -8.), rot=math.pi))
    assert b._wall_rec["target"] == (0., 0., -10.)
    assert "lup" in act["hold"] and not {"rleft", "rright"} & set(act["hold"])
    clock[0] += .08
    act = b.tick(snap(pos=(0., 0., -16.), rot=math.pi))
    assert b._wall_rec["target"] == (0., 0., -20.)
    assert "lup" in act["hold"] and not {"rleft", "rright"} & set(act["hold"])
    clock[0] += .08
    act = b.tick(snap(pos=(0., 0., -24.), rot=math.pi))
    assert b._wall_rec is None and b.stats["wall_recoveries"] == 1
    assert "lup" not in act["hold"]


def test_passing_a_corner_preserves_the_next_turn_and_rejects_large_lateral_displacement(monkeypatch):
    from gbox.mercs.titles import re5_switch_wall as W
    b, clock = bot()
    W._state(b)["trail"] = [(-10., 0., -10.), (-5., 0., -10.), (0., 0., -10.), (0., 0., -5.), (0., 0., 0.)]
    b._wall_start(snap()["player"], 0., preempt=False)
    act = W._recover(b, {"hold": ("lup",)}, snap(pos=(0., 0., -12.), rot=math.pi)["player"], .1, R)
    assert b._wall_rec["target"] == (-5., 0., -10.)
    assert "lup" not in act["hold"] and {"rleft", "rright"} & set(act["hold"])
    target = b._wall_rec["target"]
    W._recover(b, {"hold": ("lup",)}, snap(pos=(-8., 0., -30.), rot=-math.pi / 2)["player"], .2, R)
    assert b._wall_rec["target"] == target, "crossing a target plane far outside its segment does not consume it"
