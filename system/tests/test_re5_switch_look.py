"""RE5 Switch "look at the bot" (gbox.mercs.titles.re5_switch, gbox.mercs.bot_look): every trigger pull in stats look
with its target, aim and outcome, the decisions and why, and the aim's per-round counters (the time spent on each
decision, misses with the dot on, rays through a Majini that took nothing, targets left mid-burst, the first pull after
the raise, turning with a Majini in front)."""
import math

import pytest

from gbox.mercs.titles import re5_switch as R

MUZZLE = (0.0, 140.0, 30.0)
GUN = {"slot": 3, "id": 0x102, "type": 1, "item": 0x02, "rounds": 50, "cap": 50, "grid": 3, "hand": True}



@pytest.fixture(autouse=True)
def _switch_fight(monkeypatch):
    """These tests drive the Switch's own fight (re5_switch.Bot._decide), kept behind PS3_BRAIN = False until the RE5
    PS3 combat core (tests/test_re5_switch_brain.py) has proven itself live."""
    monkeypatch.setattr(R, "PS3_BRAIN", False)

@pytest.fixture(autouse=True)
def _no_heal(monkeypatch):
    monkeypatch.setattr(R, "HEAL_ENABLED", False)


def at(dist, deg):
    a = math.radians(deg)
    return (dist * math.sin(a), 0.0, dist * math.cos(a))


def along(frm, to, cm):
    """The point cm along the line frm -> to."""
    d = math.dist(frm, to)
    return tuple(frm[k] + (to[k] - frm[k]) * cm / d for k in range(3))


def snap(enemies, dot=None, hp=None):
    """Chris at the origin facing +z; enemies: [(pos, hp)]; the laser up on dot (None: the gun down)."""
    return {"player": {"ptr": 0x5D00001000, "pos": (0.0, 0.0, 0.0), "rot": 0.0, "hp": hp or 1000, "hp_max": 1000,
                       "motion": 0},
            "enemies": [{"ptr": 10 + i, "pos": pos, "hp": h, "hp_max": 800} for i, (pos, h) in enumerate(enemies)],
            "inventory": [dict(GUN)],
            "laser": {"from": MUZZLE, "at": dot, "up": True} if dot else {"from": (0, 0, 0), "at": (0, 0, 0), "up": False}}


def bot():
    clock = [0.0]
    return R.Bot(stats={}, clock=lambda: clock[0]), clock


def chest(foot):
    return (foot[0], foot[1] + R.CHEST_H, foot[2])


def test_a_pull_that_takes_health_is_a_hit_with_its_target_aim_and_the_first_pull_time():
    b, clock = bot()
    foe = at(500, 0)
    b.tick(snap([(foe, 800)]))                                         # the gun goes up
    assert b.doing == "raise"
    clock[0] = 0.2
    act = b.tick(snap([(foe, 800)], dot=chest(foe)))                  # the dot on his body: the trigger
    assert "zr" in act["hold"] and b.doing == "fire"
    assert b.stats["first_pull_n"] == 1 and b.stats["first_pull_s"] == pytest.approx(0.2)
    clock[0] = 0.25
    b.tick(snap([(foe, 700)], dot=chest(foe)))                        # his health falls
    clock[0] = 0.3
    off = (chest(foe)[0] + 100.0, chest(foe)[1], chest(foe)[2])
    b.tick(snap([(foe, 700)], dot=off))                               # the aim slides off him: the pull ends
    assert b.doing == "aim" and b.stats["pulls_slipped"] == 1
    clock[0] = 0.8
    b.tick(snap([(foe, 700)], dot=(off[0] - 1.0, off[1], off[2])))   # past the hit window: resolved
    assert b.stats["pulls_hit"] == 1 and b.stats["pulls_dot_miss"] == 0
    shot = b.stats["look"]["shots"][-1]
    assert shot["outcome"] == "hit:majini" and shot["hp_delta"] == -100 and shot["dot_on"] == "target"
    assert shot["target"] == {"id": "10", "kind": "majini", "dist_m": 5.0, "bearing_deg": 0.0}
    assert shot["gate"] == "dot on body" and shot["weapon"] == "0x102" and abs(shot["aim_err_deg"]) < 1.0
    # the time between ticks is charged to the decision that ran in it: raise 0.2, fire 0.05 + 0.05, aim 0.25 (capped)
    assert b.stats["t_raise"] == pytest.approx(0.2) and b.stats["t_fire"] == pytest.approx(0.1)
    assert b.stats["t_aim"] == pytest.approx(R.LOOK_STEP_MAX_S)


def test_the_dot_on_him_without_his_health_falling_is_a_miss_with_the_dot_on():
    b, clock = bot()
    foe = at(500, 0)
    b.tick(snap([(foe, 800)]))
    for k, t in enumerate((0.2, 0.25, 0.3)):
        clock[0] = t
        b.tick(snap([(foe, 800)], dot=(0.0, 110.0 + k, 500.0)))      # on his body, a live ray, no damage
    clock[0] = 0.35
    b.tick(snap([(foe, 800)], dot=(200.0, 110.0, 500.0)))            # off him: the pull ends
    clock[0] = 1.0
    b.tick(snap([(foe, 800)], dot=(199.0, 110.0, 500.0)))
    assert b.stats["pulls_dot_miss"] == 1 and b.stats["pulls_hit"] == 0
    assert b.stats["look"]["shots"][-1]["outcome"] == "miss:no_damage"


def test_a_ray_through_him_that_takes_nothing_names_what_the_dot_met_behind_him():
    b, clock = bot()
    foe = at(500, 0)
    behind = along(MUZZLE, chest(foe), 1000.0)                        # the line through his chest, the dot past him
    assert R.dot_on(behind, foe) is None and R.through(MUZZLE, behind, foe)
    b.tick(snap([(foe, 800)]))
    clock[0] = 0.2
    b.tick(snap([(foe, 800)], dot=behind))
    assert b.doing == "fire"
    clock[0] = 0.25
    b.tick(snap([(foe, 800)], dot=(behind[0] + 300.0, behind[1], behind[2])))   # off him
    clock[0] = 0.9
    b.tick(snap([(foe, 800)], dot=(behind[0] + 301.0, behind[1], behind[2])))
    shot = b.stats["look"]["shots"][-1]
    assert b.stats["pulls_ray_miss"] == 1 and shot["outcome"] == "miss:off_target"
    assert shot["gate"] == "ray through him (the dot on the wall behind him)"


def test_turning_the_body_to_a_side_target_while_another_stands_in_front_is_counted():
    b, clock = bot()
    ahead, side = at(1500, 0), at(100, 100)                           # one about to grab him beside: turned to first
    for k in range(5):
        clock[0] = 0.05 * k
        b.tick(snap([(ahead, 800), (side, 800)]))
        assert b.doing == "turn" and b.target == 11
    assert b.stats["t_turn"] == pytest.approx(0.2) and b.stats["t_turn_foe_front"] == pytest.approx(0.2)


def test_a_living_target_left_with_the_trigger_held_is_a_drop_and_a_new_pull():
    b, clock = bot()
    a = at(500, 0)
    b.tick(snap([(a, 800)]))
    clock[0] = 0.2
    b.tick(snap([(a, 800)], dot=chest(a)))
    assert b.fire_down and b.stats["shots"] == 1
    clock[0] = 1.3                                                    # past COMMIT_S: one comes within THREAT_R
    near = at(200, 3)                                                 # in the line too, in front of the dot
    b.tick(snap([(a, 800), (near, 800)], dot=chest(near)))
    assert b.target == 11 and b.fire_down and b.stats["drops_mid_burst"] == 1 and b.stats["shots"] == 2
    clock[0] = 1.35
    b.tick(snap([(a, 800), (near, 800)], dot=(chest(near)[0], chest(near)[1] + 1, chest(near)[2])))
    assert b.stats["drops_mid_burst"] == 1                            # the same one: no new drop
    clock[0] = 2.0                                                    # he dies: the next one is no drop
    b.tick(snap([(a, 800), (near, 0)], dot=(chest(a)[0], chest(a)[1] + 2, chest(a)[2])))
    assert b.stats["drops_mid_burst"] == 1


def test_the_look_has_the_shared_shape_and_the_round_counters_reach_the_notebook():
    b, clock = bot()
    foe = at(500, 0)
    b.tick(snap([(foe, 800)]))
    clock[0] = 0.3
    b.tick(snap([(foe, 800)], dot=chest(foe)))
    look = b.stats["look"]
    assert set(look) == {"shots", "decisions", "idle_among_foes_s", "walls_shot"}
    assert [(d["phase"], d["decision"]) for d in look["decisions"]] == [("fight", "raise"), ("fight", "fire")]
    assert look["decisions"][-1]["reason"] == "body at 5.0 m"
    for key in R.AIM_COUNTERS + ("t_fire", "t_aim", "t_raise", "t_turn", "reraise", "backoffs"):
        assert key in R.RE5Switch.round_counters and isinstance(b.stats[key], (int, float))


def test_aiming_without_shooting_with_a_majini_close_is_idle_among_foes():
    b, clock = bot()
    foe = at(300, 0)
    b.tick(snap([(foe, 800)]))
    for k in range(1, 12):                                            # the dot stays beside him: steering, no pull
        clock[0] = 0.1 * k
        b.tick(snap([(foe, 800)], dot=(150.0 + k * 0.1, 110.0, 300.0)))
    assert b.doing == "aim" and b.stats["shots"] == 0
    assert b.stats["look_idle_among_foes_s"] == pytest.approx(1.1, abs=0.05)   # raising and steering, 1.1 s
