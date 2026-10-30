"""Target feedback: noisy close rays, firing evidence, elapsed time and owner guards."""
import math
from types import SimpleNamespace

import pytest

from gbox.mercs.titles import re5_switch as R, re5_target_feedback as F


def scene(pitch=0, heading=0, distance=300, ray_pitch=None):
    origin = (0., 140., 0.)
    rp = pitch if ray_pitch is None else ray_pitch
    dot = (5000*math.sin(heading)*math.cos(rp), 140+5000*math.sin(rp), 5000*math.cos(heading)*math.cos(rp))
    return {'player': {'ptr': 1, 'generation': 1, 'pos': (0, 0, 0), 'rot': heading, 'hp': 1000, 'motion': 26},
            'aim_cam': {'player': 1, 'generation': 1, 'pitch': pitch, 'heading': heading},
            'inventory': [{'hand': True, 'item': 0x1b}],
            'enemies': [{'ptr': 2, 'pos': (0, 0, distance), 'hp': 800}],
            'laser': {'up': True, 'from': origin, 'at': dot}}


def controller(ok=True):
    writes = []
    def write(st, pitch, heading):
        writes.append((pitch, heading))
        return ok
    bot = SimpleNamespace(target=2, doing='aim', stats={}, aim_since=0, _feedback_at=0,
                          _writer=lambda: write, _aim_h=lambda *args: R.CHEST_H,
                          _crowd_hit=R.Bot._crowd_hit, _trigger=lambda on, now: {'zr'} if on else set())
    return bot, writes


@pytest.mark.parametrize('pitch', [-1., 1.])
def test_sky_and_ground_correct_towards_chest_without_firing(pitch):
    bot, writes = controller()
    act = F.apply(bot, scene(pitch), {'hold': ('zl', 'zr', 'rup')}, .05)
    assert set(act['hold']) == {'zl'}
    assert abs(writes[-1][0]) < abs(pitch)
    assert abs(writes[-1][0]-pitch) <= F.PITCH_RATE*.05 + 1e-8


def test_close_collision_ray_cannot_reverse_camera_correction():
    bot, writes = controller()
    s = scene(pitch=.5, ray_pitch=-.7, distance=100)
    F.apply(bot, s, {'hold': ('zl',)}, .05)
    assert writes[-1][0] < .5  # toward the chest, not upward following the bad ray


def test_close_target_uses_actual_low_offset_muzzle_not_nominal_camera_height():
    bot, writes = controller(); s = scene(distance=150)
    s['laser'] = {'up': True, 'from': (30, 80, 50), 'at': (30, 80, 5000)}
    act = F.apply(bot, s, {'hold': ('zl', 'zr')}, .05)
    assert writes[-1][0] > 0 and writes[-1][1] < 0
    assert 'zr' not in act['hold']


@pytest.mark.parametrize('dt', [0., -.1, .001, .01, .05, 1.])
def test_no_minimum_step_or_stall_catchup(dt):
    bot, writes = controller()
    F.apply(bot, scene(heading=.8), {'hold': ('zl', 'rleft')}, dt)
    assert abs(writes[-1][1]-.8) == pytest.approx(F.YAW_RATE*max(0, min(dt, F.MAX_DT)))


def test_ram_write_is_not_proof_a_shot_is_aligned():
    bot, writes = controller()
    s = scene(heading=.1)
    s['laser']['at'] = (0, 0, 50)  # obstruction, despite a successful correction
    act = F.apply(bot, s, {'hold': ('zl', 'zr')}, .05)
    assert writes and 'zr' not in act['hold']


def test_live_body_and_camera_agreement_resume_firing():
    bot, _ = controller()
    s = scene()
    s['laser']['at'] = (0, R.CHEST_H, 300)
    act = F.apply(bot, s, {'hold': ('zl',)}, .3)
    assert set(act['hold']) == {'zl', 'zr'}


def test_reachable_front_enemy_wins_over_prior_rear_target():
    bot, _ = controller(); s = scene()
    s['enemies'].append({'ptr': 3, 'pos': (0, 0, -100), 'hp': 800})
    s['laser']['at'] = (0, R.CHEST_H, 300); bot.target = 3
    assert F.visible_target(s)['ptr'] == 2
    act = F.apply(bot, s, {'hold': ('zl',)}, .3)
    assert 'zr' in act['hold'] and bot.target == 2 and bot._aimctx['target'] == 2


def test_old_life_cannot_write_or_fire():
    bot, writes = controller()
    s = scene(); s['aim_cam']['generation'] = 0
    act = F.apply(bot, s, {'hold': ('zl', 'zr', 'rdown')}, .05)
    assert not writes and set(act['hold']) == {'zl'}


def test_throwing_and_no_laser_weapons_keep_their_controller():
    for item in (0x06, 0x08, 0x0a, 0x0f, 0x0d):
        bot, writes = controller(); s = scene(); s['inventory'][0]['item'] = item
        act = {'hold': ('zl', 'zr')}
        assert F.apply(bot, s, act, .05) == act and not writes


def test_failed_owner_or_write_check_releases_aim_and_fire_until_fresh_snapshot():
    bot, _ = controller(False)
    act = F.apply(bot, scene(pitch=1), {'hold': ('zl', 'zr', 'rdown')}, .05)
    assert set(act['hold']) == {'zl'}


def test_operator_control_never_moves_camera_ram():
    bot, writes = controller(); bot.stats['operator_control'] = True
    act = {'hold': ('zl',)}
    assert F.apply(bot, scene(pitch=1), act, .05) == act and not writes


@pytest.mark.parametrize('aim_speed', [1, 7])
def test_closed_loop_converges_with_extra_frames_and_aim_speed(aim_speed):
    bot, writes = controller()
    pitch, heading = .9, -.7
    for frame in range(1, 121):
        bot.doing = 'aim'
        act = F.apply(bot, scene(pitch, heading), {'hold': ('zl', 'rup', 'rleft')}, frame/120)
        # Real input scales can only affect held stick axes. A RAM correction
        # must release them and remain bounded at 120 Hz as well as at 20 Hz.
        pitch, heading = writes[-1]
        pitch += aim_speed*.01*(('rup' in act['hold'])-('rdown' in act['hold']))
        heading += aim_speed*.01*(('rleft' in act['hold'])-('rright' in act['hold']))
    assert abs(heading) < .001
    assert pitch == pytest.approx(math.atan2(R.CHEST_H-140,300), abs=.001)
