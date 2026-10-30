import math
import struct
import pytest
from gbox.mercs.titles import re5_switch_mods as M
from test_re5_switch_mods import Adapter, weapon_guest
from test_re6_switch import brain, round_guest, run
from test_tactical_map import T, two_levels, snap


@pytest.mark.parametrize('speed', [1, 3, 7, 10])
def test_switch_turn_rate_preserves_normalized_input_even_after_old_boost(speed):
    memory = weapon_guest()
    adapter = Adapter(memory)
    game = M.RE5Switch(adapter)
    parameter = memory.alloc(0x400)
    memory.q(game.base + M.S_PARAM_PTR, parameter)
    for offset, (_, base) in M.TURN.items():
        memory.put(parameter + offset, struct.pack('<f', base * 7))
    out = M.turn_speed(game, speed)
    assert out['verified']
    assert out['values']['stick_min'] == pytest.approx(.2)
    assert out['values']['stick_max'] == pytest.approx(1.2)
    assert out['values']['aim_yaw_deg_s'] == pytest.approx(57.9 * speed)
    assert out['values']['aim_pitch_deg_s'] == pytest.approx(57.9 * speed)


def test_re6_first_miss_recovery_quick_attack_does_not_stop_the_round():
    bot, clock, snapshot = brain(round_guest(enemies=((0., 0., 250., 700),)))
    bot.held = lambda p, now: False
    bot.qa_burst = 3
    assert bot.qa_at is None
    actions = run(bot, snapshot, clock, 60)
    assert any(a.get('tap') == 'zr' for a in actions)
    assert bot.stats['miss_quick_attacks'] > 0


def test_missing_mesh_never_reuses_the_previous_rooms_floor():
    tracker = T.Tracker('BLUS30491')
    first = tracker.frame(snap(nav=two_levels()), now=1)
    assert first['stage']
    second = tracker.frame(snap(nav=None), now=2)
    assert second['stage'] == '' and second['player']
    assert tracker.frame(snap(nav=two_levels()), now=3)['stage'] == first['stage']


def test_equal_vertices_with_different_triangles_are_different_maps():
    a, b = two_levels(), two_levels()
    b.tris = list(reversed(b.tris))
    assert T.stage_key('BLUS30491', a) != T.stage_key('BLUS30491', b)
