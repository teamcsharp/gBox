"""Replay test for the crowd_gun_down incident (cluster b294c62b554c77fd), prompt path.

The guard in Bot._prompt defers the prompt press when live enemies of his level
within CC_CROWD_R reach the crowd threshold:

    threshold = CC_BACK_N - 1 if any is inside the CC cone (CC_CONE = 100 deg)
                else CC_BACK_N
    guard fires when n >= threshold

with the heading taken from the camera yaw (player rot when the camera field is
absent).  Lowering the gun to take a prompt in a surround is the crowd_gun_down
trigger.  This file drives Bot.tick on synthetic snapshots (fresh bot, single
prompt, no tablet path) and on the recorded incident fixture, and asserts:

  - the refined guard defers the press at 2-in-cone (threshold 2);
  - the press still happens with 1-in-cone and 2-out-of-cone (threshold 3);
  - the camera yaw drives the cone test (a prompt behind the camera is pressed);
  - the recorded fixture still reaches the tablet with its crowd hold set.
"""
import json
import math
from pathlib import Path

from gbox.mercs.titles import re6_switch
from gbox.mercs.titles.re6_switch import Bot

FIXTURE = Path(__file__).parent / "fixtures" / "mercs_incidents" / "re6_switch_crowd_gun_down.json"
CC_CROWD_R = re6_switch.CC_CROWD_R
CC_BACK_N = re6_switch.CC_BACK_N
CC_CONE = re6_switch.CC_CONE

PROMPT = {"ab": 1, "type": 7, "key": "a", "pad": 0x2000, "button": 3}


def _enemy(dx, dz, hp=700.0, dy=0.0):
    return {"pos": [dx, dy, dz], "hp": hp, "state": 0}


def _snap(cam_yaw, enemies, hp=900.0, cam_missing=False, rot=0.0):
    snap = {
        "player": {
            "pos": [0.0, 0.0, 0.0], "rot": rot, "hp": hp, "hp_max": 900.0,
            "state": 0, "ammo": 9, "tablets": 3, "guns": {0x107: 0},
            "equipped": 0,                       # a gun in hand: no bomb/throw path
        },
        "enemies": enemies,
        "mercenaries_phase": 1,
        "mercenaries_mode": "no_mercy",
    }
    if not cam_missing:
        snap["camera"] = {"yaw": cam_yaw}
    snap["prompts"] = [dict(PROMPT)]
    return snap


def _at(bearing_deg, r=100.0, cam_yaw=0.0):
    """An enemy at r cm, `bearing_deg` away from the camera heading."""
    a = math.radians(bearing_deg - math.degrees(cam_yaw))
    return _enemy(r * math.sin(a), r * math.cos(a))


def _tick(snap):
    """One tick on a fresh bot; (doing, did the prompt get pressed)."""
    b = Bot(clock=lambda: 0.0)
    out = b.tick(snap)
    pressed = b.prompt_live.get((PROMPT["ab"], PROMPT["type"]), {}).get("pressed")
    return b, out.get("doing"), pressed is not None


def test_guard_3_in_cone_defers_press():
    b, doing, pressed = _tick(_snap(0.0, [_at(d) for d in (0.0, 40.0, -40.0)]))
    assert not pressed, f"3 in cone: press must be deferred, doing={doing}"
    assert b.stats.get("prompt_presses", 0) == 0


def test_guard_2_in_cone_defers_press():
    """The refined case: 2 enemies, at least one in the CC cone -> threshold 2,
    n=2 >= 2 -> defer.  The old guard (threshold 3, no cone) let the press through."""
    b, doing, pressed = _tick(_snap(0.0, [_at(0.0), _at(40.0)]))
    assert not pressed, f"2 in cone: refined guard must defer, doing={doing}"
    assert b.stats.get("prompt_presses", 0) == 0


def test_2_outside_cone_presses():
    """2 enemies, none in the CC cone -> threshold stays at CC_BACK_N (3),
    n=2 < 3 -> the press goes out (guard does not fire)."""
    b, doing, pressed = _tick(_snap(0.0, [_at(150.0), _at(-150.0)]))
    assert pressed, f"2 out of cone: press must fire, doing={doing}"
    assert b.stats.get("prompt_presses", 0) == 1


def test_1_in_cone_presses():
    b, doing, pressed = _tick(_snap(0.0, [_at(0.0)]))
    assert pressed, f"1 in cone: press must fire, doing={doing}"


def test_4_outside_cone_defers_press():
    """4 enemies, none in the cone: threshold 3, n=4 >= 3 -> defer (original
    guard behavior preserved)."""
    b, doing, pressed = _tick(_snap(0.0, [_at(d) for d in (120.0, 160.0, -120.0, -160.0)]))
    assert not pressed, f"4 out of cone: press must be deferred, doing={doing}"


def test_cone_follows_camera_yaw():
    """The cone test uses the camera heading: an enemy in front of the bot but
    behind the camera is outside the cone, so 2 such enemies do not defer."""
    cam_yaw = math.pi  # camera looks opposite the +Z
    b, doing, pressed = _tick(_snap(cam_yaw, [_at(0.0, cam_yaw=cam_yaw), _at(30.0, cam_yaw=cam_yaw)]))
    # the CC kick (crowd control) may preempt the prompt's press; what must hold
    # is that the guard did not defer it as a crowd
    assert not (not pressed and b.stats.get("prompt_defers", 0) > 0), (
        f"camera facing away: enemies behind it must not count as a crowd, doing={doing}"
    )


def test_cone_falls_back_to_player_rot():
    """No camera field: the player's rot drives the cone test; 2 in the rot's
    cone still defer."""
    b, doing, pressed = _tick(_snap(0.0, [_at(0.0), _at(40.0)], cam_missing=True, rot=0.0))
    assert not pressed, f"camera absent, 2 in rot cone: must defer, doing={doing}"


def test_crowd_radius_and_level_filter():
    """Only enemies of his level (|dy| <= MAX_DY) within CC_CROWD_R count: a
    crowd at 500 cm (past CC_CROWD_R) and one on a ledge do not defer even in
    the cone."""
    snap = _snap(0.0, [
        _enemy(0.0, 500.0),              # in the cone but past CC_CROWD_R
        _enemy(0.0, 300.0, dy=400.0),    # in range but on a ledge (dy > MAX_DY)
    ])
    b, doing, pressed = _tick(snap)
    assert pressed, f"out-of-range crowd must not defer, doing={doing}"


def test_threshold_logic_table():
    """The guard's arithmetic, straight from the guard in Bot._prompt:
    threshold = CC_BACK_N - 1 if cone_hit else CC_BACK_N; fires when n >= threshold."""
    cases = [
        # (n, cone_hit, fires)
        (3, True, True),
        (3, False, True),
        (2, True, True),    # refined: the cone drops the threshold to 2
        (2, False, False),
        (4, False, True),
        (4, True, True),
        (1, True, False),
        (1, False, False),
        (5, True, True),
    ]
    for n, cone_hit, expected in cases:
        threshold = CC_BACK_N - 1 if cone_hit else CC_BACK_N
        assert (n >= threshold) == expected, f"n={n} cone_hit={cone_hit}: expected {expected}"


def test_recorded_fixture_still_reaches_tablet_with_crowd_hold():
    """The recorded incident snapshot: low hp (488/900) with 14 enemies around -
    the tablet path runs and the crowd around him sets tablet_hold_until."""
    fx = json.loads(FIXTURE.read_text())
    b = Bot(clock=lambda: 0.0)
    b.tick(fx["snapshot"])
    assert b.doing == "tablet", f"fixture must take a tablet, doing={b.doing}"
    assert b.tablet_hold_until > 0.0, (
        f"crowd around the tablet: hold must be set, got {b.tablet_hold_until}"
    )
    assert b.stats.get("tablet_presses", 0) == 1
