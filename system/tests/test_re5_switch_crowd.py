"""RE5 Switch crowd fire (operator 19:25: "They should have pulled out their shotgun and did crowd control"; 19:5x:
"give the bot rapid fire shotguns for crowd control ... this bot is swarmed and is barely shooting"): three within 5 m
or one within 2 m - the shotgun up, the trigger with the aim on them, the aim turned to the nearest in front between
shots only, never an unaim with anyone within 5 m."""
import math
import copy
import json
from pathlib import Path

import pytest

from gbox.mercs.titles import re5_switch as R

MUZZLE = (0.0, 140.0, 30.0)
M92F = {"slot": 0, "id": 0x102, "type": 1, "item": 0x02, "rounds": 15, "cap": 15, "grid": 3, "hand": True}
SHOTGUN = {"slot": 1, "id": 0x104, "type": 1, "item": 0x04, "rounds": 6, "cap": 6, "grid": 5, "hand": False}


@pytest.fixture(autouse=True)
def _switch_fight(monkeypatch):
    monkeypatch.setattr(R, "PS3_BRAIN", False)
    monkeypatch.setattr(R, "HEAL_ENABLED", False)
    monkeypatch.setattr(R, "MINES", False)
    monkeypatch.setattr(R, "CALM", False)                         # (the calm budget's coasting is tested on its own)


def at(dist, deg, y=0.0):
    a = math.radians(deg)
    return (dist * math.sin(a), y, dist * math.cos(a))


def chest(foot):
    return (foot[0], foot[1] + R.CHEST_H, foot[2])


def snap(enemies, dot=None, motion=0, inv=None, aim_pitch=None, kills=0):
    return {"player": {"ptr": 0x5D00001000, "pos": (0.0, 0.0, 0.0), "rot": 0.0, "hp": 1000, "hp_max": 1000,
                       "motion": motion, "aim_pitch": aim_pitch},
            "enemies": [{"ptr": 10 + i, "pos": x, "hp": 800, "hp_max": 800} for i, x in enumerate(enemies)],
            "inventory": inv if inv is not None else [], "kills": kills,
            "laser": {"from": MUZZLE, "at": dot, "up": True} if dot else {"from": (0, 0, 0), "at": (0, 0, 0), "up": False}}


def bot():
    clock = [0.0]
    return R.Bot(stats={}, clock=lambda: clock[0]), clock


CROWD = [at(250, 5), at(350, 60), at(300, -100)]


@pytest.mark.parametrize("weapon", [0x04, 0x0B, 0x1A, 0x1B])
@pytest.mark.parametrize("obstruction", ["off_target", "wall", "floor", "missing_ray"])
def test_idle_incident_corrects_aim_then_keeps_firing_at_reachable_target(weapon, obstruction):
    """#1576: firing attempts are no substitute for a reachable body in the crowd.

    Replay the recorded enemy layout with explicit synthetic aim observations;
    this verifies control decisions, not native damage or live survival.
    """
    path = Path(__file__).parent / "fixtures" / "mercs_incidents" / "re5_switch_idle_among_foes.json"
    fixture = json.loads(path.read_text(encoding="utf-8"))
    scene = copy.deepcopy(fixture["snapshot"])
    scene["player"]["motion"] = 26
    scene["inventory"] = [dict(SHOTGUN, id=0x100 | weapon, item=weapon, hand=True)]
    b, clock = bot()
    b.tick(scene)
    target = next(e for e in scene["enemies"] if e["ptr"] == b.target)
    body = chest(target["pos"])
    delta = tuple(body[i] - MUZZLE[i] for i in range(3))
    if obstruction == "off_target":
        angle = math.radians(-30)
        dot = (MUZZLE[0] + delta[0] * math.cos(angle) + delta[2] * math.sin(angle),
               body[1], MUZZLE[2] - delta[0] * math.sin(angle) + delta[2] * math.cos(angle))
    elif obstruction == "wall":
        dot = tuple(MUZZLE[i] + delta[i] * 0.25 for i in range(3))
    else:
        dot = (0.0, -100.0, 70.0)
    if obstruction != "missing_ray":
        scene["laser"] = {"from": MUZZLE, "at": dot, "up": True}
    clock[0] = 0.3
    missed = b.tick(scene)
    assert "zl" in missed["hold"] and "zr" not in missed["hold"]
    if obstruction == "off_target":
        assert {"rleft", "rright"}.intersection(missed["hold"])
    idle = b.stats["idle_in_5m_s"]
    scene["laser"] = {"from": MUZZLE, "at": body, "up": True}
    for when in (0.6, 0.9, 1.2):
        clock[0] = when
        firing = b.tick(scene)
        assert {"zl", "zr"} <= set(firing["hold"])
        assert not set(R.QUICK.values()).intersection(firing["hold"])
    assert b.stats["idle_in_5m_s"] == idle
    assert b.stats["unaims_in_5m"] == 0


def test_three_within_5_m_put_the_shotgun_up_first():
    b, clock = bot()
    act = b.tick(snap(CROWD, inv=[M92F, SHOTGUN]))
    assert act["hold"] == ("dright",) and b.stats["shotgun_swaps"] == 1 and b.stats["rampage_weapon"] == "shotgun"


def test_crowd_fires_the_held_shotgun_instead_of_cycling_to_an_earlier_shotgun():
    b, clock = bot()
    held = dict(SHOTGUN, slot=2, id=0x117, item=0x17, grid=4, hand=True)
    inv = [SHOTGUN, held]
    act = b.tick(snap(CROWD, inv=inv))
    assert "zl" in act["hold"] and not set(act["hold"]) & set(R.QUICK.values())
    clock[0] = 0.2
    act = b.tick(snap(CROWD, dot=chest(CROWD[0]), motion=26, inv=inv))
    assert {"zl", "zr"} <= set(act["hold"])
    assert b.stats["shotgun_swaps"] == b.stats["rampage_swaps"] == 0


def test_with_the_aim_on_the_nearest_in_front_the_trigger_holds_and_no_stick():
    b, clock = bot()
    held = [dict(M92F, hand=False), dict(SHOTGUN, hand=True)]
    b.tick(snap(CROWD, inv=held))
    clock[0] = 0.2
    act = b.tick(snap(CROWD, dot=chest(CROWD[0]), motion=26, inv=held))
    assert {"zl", "zr"} <= set(act["hold"]) and not {"rleft", "rright"} & set(act["hold"])
    assert b.target == 10 and b.stats["crowd_fire_s"] > 0


def test_the_aim_off_them_lets_the_trigger_go_and_turns_between_shots_only(monkeypatch):
    monkeypatch.setattr(R, "SHOT_TAIL_S", 0.0)                          # (the post-shot pause: its own test)
    b, clock = bot()
    held = [dict(M92F, hand=False), dict(SHOTGUN, hand=True)]
    b.tick(snap(CROWD, inv=held))
    off = (-1500.0, 140.0, 2500.0)                                 # the dot 31 deg right of the one in front
    clock[0] = 0.2
    act = b.tick(snap(CROWD, dot=off, motion=29, inv=held))        # the shot still playing: no stick
    assert "zr" not in act["hold"] and not {"rleft", "rright"} & set(act["hold"]) and "zl" in act["hold"]
    clock[0] = 0.25
    act = b.tick(snap(CROWD, dot=off, motion=26, inv=held))
    assert "rleft" in act["hold"] and "zr" not in act["hold"] and b.doing == "aim"


def test_one_within_2_m_alone_is_crowd_fire():
    b, clock = bot()
    b.tick(snap([at(150, 10)]))
    assert b.stats["crowd_fire_s"] >= 0 and b._ramp is not None and b.aim_since is not None


def test_two_at_3_m_are_not_crowd_fire_but_the_gun_never_goes_down():
    b, clock = bot()
    pair = [at(300, 0), at(350, 30)]
    b.tick(snap(pair))
    assert b._ramp is None
    clock[0] = 0.3
    act = b.tick(snap(pair, dot=(2000.0, 140.0, -500.0), motion=26))   # the aim far off them
    assert "zl" in act["hold"] and b.stats["unaims_in_5m"] == 0 and b.stats["unaims"] == 0


def test_once_on_it_stays_while_anyone_is_within_5_m_then_the_main_gun_comes_back():
    b, clock = bot()
    held = [dict(M92F, hand=False), dict(SHOTGUN, hand=True)]
    b.tick(snap(CROWD, inv=[M92F, SHOTGUN]))
    clock[0] = 0.2
    b.tick(snap(CROWD, inv=held))
    clock[0] = 0.4
    b.tick(snap([at(450, 0)], dot=chest(at(450, 0)), motion=26, inv=held))
    assert b._ramp is not None and b.doing == "fire"               # one left inside: still on
    clock[0] = 0.6
    b.tick(snap([at(900, 0)], inv=held))
    assert b._ramp is None


def test_a_confirmed_body_shot_does_not_steer_away_for_a_conflicting_pitch_read():
    b, clock = bot()
    held = [dict(M92F, hand=False), dict(SHOTGUN, hand=True)]
    b.tick(snap(CROWD, inv=held))
    clock[0] = 0.3
    act = b.tick(snap(CROWD, dot=chest(CROWD[0]), motion=26, inv=held, aim_pitch=-0.4))
    assert "zr" in act["hold"] and not {"rdown", "rup"}.intersection(act["hold"])


def test_with_one_near_a_far_one_is_never_the_target_nor_shot():
    b, clock = bot()
    near, far = at(400, 50), at(1200, 0)                           # the far one straight ahead, the near one aside
    b.tick(snap([near, far]))
    assert b.target == 10
    clock[0] = 0.3
    act = b.tick(snap([near, far], dot=chest(far), motion=26))    # the dot lands on the far one
    assert "zr" not in act["hold"] and b.target == 10 and b.stats["far_picks_while_crowded"] == 0
    assert b.stats["confirmed_shots"] == 0


def test_the_crowds_gun_prefers_a_magnum_then_shotgun_then_automatic():
    b, _ = bot()
    gatling = {"slot": 2, "id": 0x115, "type": 1, "item": 0x15, "rounds": 100, "cap": 100, "grid": 7, "hand": False}
    magnum = {"slot": 3, "id": 0x10B, "type": 1, "item": 0x0B, "rounds": 6, "cap": 6, "grid": 1, "hand": False}
    assert b._rampage_gun([magnum, gatling])[1] == "magnum"
    assert b._rampage_gun([magnum, gatling, SHOTGUN])[1] == "magnum"
    assert b._rampage_gun([magnum])[1] == "magnum"
    assert b._rampage_gun([gatling, SHOTGUN])[1] == "shotgun"


@pytest.mark.parametrize("weapon", [0x0B, 0x1A, 0x1B])
def test_the_held_magnum_fires_on_the_body_without_swapping_to_a_shotgun(weapon):
    b, clock = bot()
    held = dict(SHOTGUN, slot=2, id=0x100 | weapon, item=weapon, grid=3, hand=True)
    inv = [SHOTGUN, dict(held, slot=3, grid=1, hand=False), held]
    act = b.tick(snap(CROWD, inv=inv))
    assert "zl" in act["hold"] and not set(act["hold"]) & set(R.QUICK.values())
    clock[0] = 0.2
    act = b.tick(snap(CROWD, dot=chest(CROWD[0]), motion=26, inv=inv))
    assert {"zl", "zr"} <= set(act["hold"])
    assert b.stats["rampage_weapon"] == "magnum" and b.stats["rampage_swaps"] == 0


@pytest.mark.parametrize("dot,pitch,key", [
    ((0.0, 0.0, 100.0), 0.8, "rup"),       # ground before the crowd
    ((0.0, 1000.0, 100.0), -0.8, "rdown"), # sky over the crowd
    ((0.0, 140.0, 100.0), 0.0, None),       # wall directly before a target
])
def test_crowd_yaw_alignment_does_not_fire_into_ground_sky_or_wall(dot, pitch, key):
    b, clock = bot()
    ring = [at(400, 0), at(350, 70), at(300, -100)]
    held = [dict(SHOTGUN, hand=True)]
    b.tick(snap(ring, inv=held))
    clock[0] = 0.3
    act = b.tick(snap(ring, dot=dot, motion=26, inv=held, aim_pitch=pitch))
    assert "zl" in act["hold"] and "zr" not in act["hold"]
    if key:
        assert key in act["hold"]
    clock[0] = 0.6
    act = b.tick(snap(ring, dot=chest(ring[0]), motion=26, inv=held, aim_pitch=0.0))
    assert {"zl", "zr"} <= set(act["hold"])
    assert b.stats["unaims_in_5m"] == 0


def test_crowd_corrects_pitch_instead_of_firing_during_and_after_a_boosted_shot():
    b, clock = bot()
    held = [dict(SHOTGUN, hand=True)]
    b.tick(snap(CROWD, inv=held))
    clock[0] = 0.3
    b.tick(snap(CROWD, dot=chest(CROWD[0]), motion=26, inv=held))
    bad = (0.0, 0.0, 100.0)
    clock[0] = 0.4
    act = b.tick(snap(CROWD, dot=bad, motion=29, inv=held, aim_pitch=0.8))
    assert "zr" not in act["hold"] and not R.SHOT_TAIL_KEYS.intersection(act["hold"])
    clock[0] = 0.45
    act = b.tick(snap(CROWD, dot=bad, motion=26, inv=held, aim_pitch=0.8))
    assert "zr" not in act["hold"] and not R.SHOT_TAIL_KEYS.intersection(act["hold"])
    clock[0] = 0.4 + R.SHOT_TAIL_S + 0.1
    act = b.tick(snap(CROWD, dot=bad, motion=26, inv=held, aim_pitch=0.8))
    assert "rup" in act["hold"] and "zr" not in act["hold"]


def test_point_blank_does_not_override_a_laser_pointing_at_the_floor():
    b, clock = bot()
    ring = [at(120, 0)]
    b.tick(snap(ring))
    clock[0] = 0.3
    act = b.tick(snap(ring, dot=(0.0, -100.0, 70.0), motion=26, aim_pitch=1.0))
    assert "zr" not in act["hold"] and "rup" in act["hold"]


@pytest.mark.parametrize("dot", [(0.0, 100.0, 50.0), (40.0, 140.0, 40.0)])
def test_point_blank_never_overrides_a_short_miss_with_stale_level_pitch(dot):
    b, clock = bot()
    ring = [at(120, 0)]
    b.tick(snap(ring))
    clock[0] = 0.3
    ap = math.atan2(R.MUZZLE_H - R.CHEST_H, 120.0)
    act = b.tick(snap(ring, dot=dot, motion=26, aim_pitch=ap))
    assert "zr" not in act["hold"]


def test_a_close_body_hit_still_fires_without_the_point_blank_exception():
    b, clock = bot()
    ring = [at(100, 5)]
    b.tick(snap(ring))
    clock[0] = 0.3
    act = b.tick(snap(ring, dot=chest(ring[0]), motion=26))
    assert {"zl", "zr"} <= set(act["hold"])


def test_a_target_that_moves_behind_does_not_hide_a_front_threat(monkeypatch):
    monkeypatch.setattr(R, "QUICK_TURN", False)
    b, clock = bot()
    b.tick(snap([at(250, 0), at(350, 80), at(300, -100)]))
    assert b.target == 10
    clock[0] = R.RAMPAGE_RETARGET_S + 0.1
    ring = [at(250, 160), at(350, 0), at(300, -100)]
    act = b.tick(snap(ring, dot=chest(ring[1]), motion=26))
    assert b.target == 11 and {"zl", "zr"} <= set(act["hold"])
    assert not {"rleft", "rright"}.intersection(act["hold"])


@pytest.mark.parametrize("weapon,fire", [(SHOTGUN, True), (M92F, False)])
def test_only_the_held_shotgun_gets_a_three_dimensional_spread_cone(weapon, fire):
    b, clock = bot()
    ring = [at(400, 8), at(350, 70), at(300, -100)]
    inv = [dict(weapon, hand=True)]
    b.tick(snap(ring, inv=inv))
    clock[0] = 0.3
    act = b.tick(snap(ring, dot=(0.0, 110.0, 450.0), motion=26, inv=inv))
    assert ("zr" in act["hold"]) is fire


def test_crowd_laser_dropout_requires_a_recent_confirmed_ray():
    b, clock = bot()
    ring = [at(300, 0), at(350, 70), at(300, -100)]
    b.tick(snap(ring))
    clock[0] = 0.3
    assert "zr" not in b.tick(snap(ring, motion=26))["hold"]
    clock[0] = 0.4
    assert "zr" in b.tick(snap(ring, dot=chest(ring[0]), motion=26))["hold"]
    clock[0] = 0.5
    assert "zr" in b.tick(snap(ring, motion=29))["hold"]
    clock[0] = 0.4 + R.FLICKER_S + 0.1
    assert "zr" not in b.tick(snap(ring, motion=26))["hold"]


@pytest.mark.parametrize("position,heading,muzzle", [
    ((100.0, 0.0, 0.0), 0.0, None),
    ((0.0, 0.0, 0.0), 0.5, None),
    ((0.0, 0.0, 0.0), 0.0, (100.0, 140.0, 30.0)),
])
def test_crowd_laser_dropout_does_not_reuse_a_ray_after_the_player_moves(position, heading, muzzle, monkeypatch):
    monkeypatch.setattr(R, "QUICK_TURN", False)
    b, clock = bot()
    ring = [at(300, 0), at(350, 70), at(300, -100)]
    b.tick(snap(ring))
    clock[0] = 0.3
    assert "zr" in b.tick(snap(ring, dot=chest(ring[0]), motion=26))["hold"]
    clock[0] = 0.4
    sample = snap(ring, motion=26)
    sample["player"].update(pos=position, rot=heading)
    if muzzle is not None:
        sample["laser"]["from"] = muzzle
    assert "zr" not in b.tick(sample)["hold"]


def test_a_short_wall_ray_releases_a_blocked_target_for_another_crowd_threat(monkeypatch):
    monkeypatch.setattr(R, "QUICK_TURN", False)
    b, clock = bot()
    ring = [at(400, 0), at(450, 40), at(300, -100)]
    b.tick(snap(ring))
    for now in (0.3, 0.3 + R.WALL_DROP_S + 0.05, 0.3 + R.WALL_DROP_S + 0.15):
        clock[0] = now
        act = b.tick(snap(ring, dot=(0.0, 130.0, 150.0), motion=26))
    assert b.target == 11 and "zr" not in act["hold"] and "rleft" in act["hold"]
    clock[0] += 0.3
    act = b.tick(snap(ring, dot=chest(ring[1]), motion=26))
    assert {"zl", "zr"} <= set(act["hold"])
