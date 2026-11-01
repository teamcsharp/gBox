"""Aimed fire requires the measured laser segment; camera writes are not hit evidence."""
import math
import pytest

from gbox.mercs.titles import re6_switch as R
from test_re6_switch import _fresh_caches, brain, lock_brain, round_guest, run


@pytest.mark.parametrize("height", [0.0, 600.0])
def test_a_laser_stopped_before_the_body_never_confirms_a_hit(height):
    bot = R.Bot(stats={})
    bot._ppos = (0.0, 0.0, 0.0)
    enemy = {"ptr": 123, "pos": (0.0, height, 900.0), "hp": 700}
    origin = (0.0, height + R.CHEST_H, 0.0)
    # The old same-floor slack extends 50 cm, and the off-floor line has no endpoint limit.
    dot = (0.0, height + R.CHEST_H, 850.0)
    assert bot._on_line(origin, dot, "laser", [enemy], 1.0) is None
    assert not bot.laser_seen


def test_an_off_floor_dot_at_the_feet_is_not_a_body_hit():
    bot = R.Bot(stats={})
    bot._ppos = (0.0, 0.0, 0.0)
    enemy = {"ptr": 123, "pos": (0.0, 600.0, 300.0), "hp": 700}
    assert bot._on_line((0.0, 145.0, 30.0), enemy["pos"], "laser", [enemy], 1.0) is None
    assert not bot.laser_seen


@pytest.mark.parametrize("height", [0.0, 600.0])
@pytest.mark.parametrize("end_z", [880.0, 900.0, 1100.0])
def test_measured_body_hits_and_segments_through_the_body_still_fire(height, end_z):
    bot = R.Bot(stats={})
    bot._ppos = (0.0, 0.0, 0.0)
    enemy = {"ptr": 123, "pos": (0.0, height, 900.0), "hp": 700}
    origin, dot = (0.0, height + R.CHEST_H, 0.0), (0.0, height + R.CHEST_H, end_z)
    assert bot._on_line(origin, dot, "laser", [enemy], 1.0) is enemy
    assert bot.laser_seen[123] == 1.0


@pytest.mark.parametrize("pos", [(0.0, 0.0, 700.0), (0.0, 0.0, 1500.0), (0.0, 600.0, 300.0)])
def test_camera_alignment_and_old_hit_evidence_cannot_authorize_aimed_fire(pos):
    bot = R.Bot(stats={})
    bot._ppos = (0.0, 0.0, 0.0)
    enemy = {"ptr": 123, "pos": pos, "hp": 700}
    bot.seen[123] = bot.laser_seen[123] = 1.0
    assert bot._on_line((0.0, 145.0, 0.0), R.aim_point(enemy, bot._ppos), "camera", [enemy], 1.0) is None


@pytest.mark.parametrize("dot, correction", [((0.0, -300.0, 900.0), "rup"), ((500.0, 115.0, 900.0), "rright")])
def test_a_successful_ram_write_with_a_misaligned_laser_yields_to_stick_correction(dot, correction):
    wrong = (dot, (20.0, 145.0, 30.0), 0.86)
    bot, clock, snap, writes = lock_brain(((0.0, 0.0, 900.0, 700),), laser=wrong)
    acts = run(bot, snap, clock, 16)
    assert bot.stats["lock_write_ok"] > 0
    assert bot.stats["lock_fallbacks"] == 1
    assert bot.lock_off_until > clock[0]
    assert any(correction in act.get("hold", ()) for act in acts)
    assert all("zr" not in act.get("hold", ()) for act in acts)
    count = len(writes)
    run(bot, snap, clock, 5)
    assert len(writes) == count


def test_lock_reacquisition_gets_a_new_grace_then_fires_when_the_laser_converges():
    wrong = ((0.0, -300.0, 900.0), (20.0, 145.0, 30.0), 0.86)
    bot, clock, snap, writes = lock_brain(((0.0, 0.0, 900.0, 700),), laser=wrong)
    run(bot, snap, clock, 16)
    assert bot.lock_off_until > clock[0]
    count = len(writes)
    clock[0] = bot.lock_off_until + 0.01
    run(bot, snap, clock, 2)
    assert len(writes) > count
    assert bot.stats["lock_fallbacks"] == 1
    snap["laser"]["at"] = (0.0, R.CHEST_H, 900.0)
    acts = run(bot, snap, clock, 10)
    assert any("zr" in act.get("hold", ()) for act in acts)
    assert bot.stats["lock_fallbacks"] == 1


def test_lost_laser_holds_aimed_fire_and_reappearing_laser_resumes_it():
    on = ((0.0, R.CHEST_H, 900.0), (20.0, 145.0, 30.0), 0.86)
    bot, clock, snap, writes = lock_brain(((0.0, 0.0, 900.0, 700),), laser=on)
    assert any("zr" in a.get("hold", ()) for a in run(bot, snap, clock, 8))
    laser, snap["laser"] = snap["laser"], None
    assert all("zr" not in a.get("hold", ()) for a in run(bot, snap, clock, 16))
    snap["laser"] = laser
    assert any("zr" in a.get("hold", ()) for a in run(bot, snap, clock, 8))
    assert bot.stats["lock_fallbacks"] == 0


def test_point_blank_emergency_quick_shots_survive_without_a_laser():
    bot, clock, snap = brain(round_guest(enemies=((0.0, 0.0, 150.0, 700),), cam_yaw=0.0))
    bot.held = lambda p, now: False
    acts = run(bot, snap, clock, int(2 * R.CC_QSHOT_GAP_S / 0.05))
    # Close range does not establish a clear projectile path. Acquire the gun's
    # measured line before requesting emergency quick shots.
    assert bot.stats["cc_quick_shots"] == 0
    assert any('zl' in a.get('hold', ()) for a in acts)
    assert all('zr' not in a.get('hold', ()) and a.get('tap') != 'zr' for a in acts)


def test_a_material_camera_redirect_cannot_fire_using_the_pre_write_ray():
    on = ((0.0, R.CHEST_H, 900.0), (20.0, 145.0, 30.0), 0.86)
    bot, clock, snap, writes = lock_brain(((0.0, 0.0, 900.0, 700), (700.0, 0.0, 900.0, 700)), laser=on)
    bot._ppos = snap["player"]["pos"]
    old, target = snap["enemies"]
    origin, dot = snap["laser"]["from"], snap["laser"]["at"]
    assert bot._on_line(origin, dot, "laser", [old], 1.0) is old
    assert bot._lock(snap["player"], target, snap, 1.0)
    assert writes
    assert bot._on_line(origin, dot, "laser", [old], 1.0) is None
    # A new frame with a ray on the redirected target can authorize fire again.
    dot = R.aim_point(target, bot._ppos)
    assert bot._on_line(origin, dot, "laser", [target], 1.05) is target


def test_an_off_floor_threat_stays_targetable_during_stick_correction(monkeypatch):
    monkeypatch.setattr(R, "CEILING_R", 400.0)  # exercise the supported vertical-target policy (disabled by default)
    wrong = ((0.0, 100.0, 900.0), (20.0, 145.0, 30.0), 0.86)
    bot, clock, snap, writes = lock_brain(((0.0, 600.0, 300.0, 700),), laser=wrong)
    acts = run(bot, snap, clock, 24)  # bounded climb to the ceiling, then the actual-ray settling window
    assert bot.stats["lock_fallbacks"] == 1
    assert snap["enemies"][0] in bot._off_floor(snap["player"], snap, clock[0])
    assert any("rup" in act.get("hold", ()) for act in acts)
    assert all("zr" not in act.get("hold", ()) for act in acts)


def test_retargeting_behind_turns_with_a_bounded_step_even_after_a_long_pause():
    bot, clock, snap, writes = lock_brain(((100.0, 0.0, -900.0, 700),))
    p, target = snap['player'], snap['enemies'][0]
    assert bot._lock(p, target, snap, 1.0)
    assert abs(writes[-1][2]) <= math.radians(R.LOCK_YAW_DEG_S * R.TICK_S) + 1e-8
    first = writes[-1][2]
    assert bot._lock(p, target, snap, 20.0)
    assert abs(R.wrap(writes[-1][2] - first)) <= math.radians(R.LOCK_YAW_DEG_S * R.LOCK_STEP_MAX_S) + 1e-8
    # A second decision in the same snapshot cannot spend another angular step.
    second = writes[-1][2]
    assert bot._lock(p, target, snap, 20.0)
    assert writes[-1][2] == pytest.approx(second)


def test_pitch_correction_is_bounded_and_yaw_uses_the_short_path_across_pi():
    bot, clock, snap, writes = lock_brain(((-100.0, 600.0, -900.0, 700),))
    snap['aim_cam'].update(pitch=-1.0, yaw=math.pi - 0.03)
    bot._lock(snap['player'], snap['enemies'][0], snap, 1.0)
    _, pitch, yaw = writes[-1]
    assert 0 < R.wrap(yaw - (math.pi - 0.03)) <= math.radians(R.LOCK_YAW_DEG_S * R.TICK_S) + 1e-8
    assert 0 < (pitch + 1.0) * R.PITCH_DEG_PER_UNIT <= R.LOCK_PITCH_DEG_S * R.TICK_S + 1e-8


def test_camera_movement_during_melee_does_not_poison_the_next_aim_lock():
    bot, clock, snap, writes = lock_brain(((0.0, 0.0, 900.0, 700),))
    target = snap['enemies'][0]
    bot._lock(snap['player'], target, snap, 1.0)
    bot.lock_fails = [0.8, 0.9]
    bot._gun_down()
    snap['aim_cam'].update(yaw=2.0, pitch=0.8)  # a completed kick / turn moved the camera
    bot._lock(snap['player'], target, snap, 1.1)
    assert bot.stats['lock_overwritten'] == 0
    assert bot.stats['lock_fallbacks'] == 0
    assert bot.lock_fails == []


def test_retreating_body_cannot_quick_turn_the_camera_away_from_a_visible_threat():
    bot, clock, snap = brain(round_guest(enemies=((0.0, 0.0, 150.0, 700),), cam_yaw=0.0,
        laser=((0.0, R.CHEST_H, 150.0), (0.0, R.CHEST_H, 0.0), 0.86)))
    bot.held = lambda p, now: False
    snap['player']['rot'] = math.pi  # running away, but still looking at the enemy
    acts = run(bot, snap, clock, 6)
    assert bot.stats['quick_turns'] == 0
    assert bot.stats['cc_kicks'] + bot.stats['cc_quick_shots'] > 0
    assert any('zr' in act.get('hold', ()) or act.get('tap') == 'zr' for act in acts)


@pytest.mark.parametrize('state', ['deferred', 'disabled', 'unconfirmed'])
def test_native_grenade_refusal_keeps_the_gun_up_and_returns_to_combat(state):
    class Refused:
        def select(self, player, index):
            return {'state': state, 'reason': 'native_action_busy'}

    bot = R.Bot(stats={}, equip=Refused())
    bot.aim_since = 0.5
    bot.nade = {'kind': 'flash', 'index': 11, 'phase': 'equip', 'at': 0.0,
                'steps': 0, 'to': (0, 300), 'since': 0.0, 'seen': [0], 'gun': 0}
    player = {'ptr': 123, 'pos': (0, 0, 0), 'equipped': 0, 'guns': {0x107: 0}}
    assert bot._nade(player, [], [], lambda e: 0, 0, {}, 1.0) is None
    assert bot.nade is None and bot.nade_last == 1.0
    assert bot.aim_since == 0.5
    assert bot.stats['nade_aborts'] == 1


@pytest.mark.parametrize('native_pitch, measured_degrees', [(-.268, -12.9), (-.310, -15.3), (-.187, -8.6)])
def test_raised_gun_pitch_matches_the_measured_live_scale(native_pitch, measured_degrees):
    # Independent live measurements in cPlAction_pl_act_weapon_ready_loop. The old
    # lowered-camera conversion asked for ~2x the needed deflection at these angles.
    bot, clock, snap, writes = lock_brain(((0.0, 0.0, 900.0, 700),))
    snap['aim_cam']['pitch'] = native_pitch
    c = snap['camera']['pos']
    point = (c[0], c[1] + 900.0 * math.tan(math.radians(measured_degrees)), c[2] + 900.0)
    bot._lock(snap['player'], snap['enemies'][0], snap, 1.0, point=point)
    assert writes[-1][1] == pytest.approx(native_pitch, abs=.015)


def test_locked_primary_does_not_start_an_automatic_grenade_selection():
    bot = R.Bot(stats={})
    bot._operator_primary = {'item': 7, 'locked': True}
    bot.aim_since = .5
    p = {'ptr': 123, 'pos': (0, 0, 0), 'equipped': 0, 'nades': {0x115: (11, 20)}}
    enemies = [{'pos': (0, 0, 300), 'hp': 700} for _ in range(5)]
    assert bot._nade(p, enemies, enemies, lambda e: 300, 0, {}, 1.0) is None
    assert bot.nade is None and bot.aim_since == .5
