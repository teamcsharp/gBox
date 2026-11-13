"""Village 5cbf663d: a blocked escape must not spend 45 seconds disarmed."""
import math
import struct
from types import SimpleNamespace

import pytest

from gbox.mercs.titles import re5_native_mine_escape as E, re5_switch as R
from gbox.mercs.titles import re5_switch_aim as A, re5_movement_safety as S
from test_re5_native_mine_escape import scene, mesh_grid
from test_re5_target_feedback import controller, scene as aim_scene


def trapped():
    b, s = scene()
    b._sm = SimpleNamespace(walk_block=lambda *a, **kw: 'wall')
    b.aim_since = .25
    b._gun_down = lambda: pytest.fail('a blocked escape must not lower the gun')
    return b, s


@pytest.mark.parametrize('lock', ['none', 'shot', 'tail', 'native_aim_write'])
def test_blocked_escape_keeps_gated_gun_and_strips_travel_even_during_shot(lock):
    b, s = trapped()
    b.doing = 'fire'
    if lock == 'shot': s['player']['motion'] = R.MOTION_SHOT
    if lock == 'tail': b._shot_until = 3.
    if lock == 'native_aim_write': b.stats['target_feedback_ram'] = True
    out = E.guard(b, {'hold': ('zl', 'zr', 'lup', 'b', 'rright')}, s, 1.)
    assert out == {'hold': ('zl', 'zr')}
    assert b.aim_since == .25 and b.doing == 'fire'
    assert b.stats['native_mine_defending'] is True
    assert b.mines._native_escape is not None  # not reported as successful departure
    row = b.stats['native_mine_escape_final']
    assert row['safe_end'] is None and sum(row['candidate_vetoes'].values()) == 8
    assert row['candidate_vetoes']['room'] > 0


def test_final_wall_rewrite_cannot_erase_this_ticks_verified_combat():
    b, s = trapped()
    b.doing = 'walk'
    out = E.guard(b, {'hold': ('lup', 'b')}, s, 1., combat_action={'hold': ('zl', 'zr')})
    assert out == {'hold': ('zl', 'zr')} and b.doing == 'fire'
    # A withheld shot is never invented by the mine guard.
    out = E.guard(b, {'hold': ('lup', 'b', 'zr')}, s, 1.1, combat_action={'hold': ('zl',)})
    assert out == {'hold': ('zl',)} and b.doing == 'aim'


def test_next_snapshot_with_clear_lane_immediately_resumes_escape():
    b, s = trapped()
    assert E.guard(b, {'hold': ('zl',)}, s, 1.)['hold'] == ('zl',)
    # Same room object, before the .75 second route-cache deadline: candidate
    # validation must still observe the newly open corridor on this tick.
    b._sm.walk_block = lambda *a, **kw: None
    lowered = []
    b._gun_down = lambda: lowered.append(True)
    out = E.guard(b, {'hold': ('zl', 'zr')}, s, 1.01, before_aim=True)
    assert lowered and not set(out['hold']) & {'zl', 'zr'}
    assert S._travel_heading(s['player'], out['hold']) is not None
    assert b.stats['native_mine_defending'] is False


@pytest.mark.parametrize('reason', ['floor', 'room', 'mine', 'stage'])
def test_veto_counts_name_real_first_exclusion_and_remain_bounded(monkeypatch, reason):
    b, s = scene()
    monkeypatch.setattr(E, 'route', lambda *a: None)
    monkeypatch.setattr(S, '_mine_clear', lambda *a: reason != 'mine')
    monkeypatch.setattr(E.hazards, 'blocked_segment', lambda *a, **kw: 'fire' if reason == 'stage' else None)
    s['nav'] = SimpleNamespace(floor_segment=lambda *a: reason != 'floor')
    if reason == 'room': b._sm = SimpleNamespace(walk_block=lambda *a, **kw: 'door')
    E.guard(b, {'hold': ('zl',)}, s, 1.)
    assert b.stats['native_mine_escape_vetoes'] == {
        key: 8 if key == reason else 0 for key in ('floor', 'room', 'mine', 'stage')}


@pytest.mark.parametrize('doing', ['held', 'heal', 'flashbang', 'native_equip'])
def test_blocked_combat_never_overwrites_mandatory_actions(doing):
    b, s = trapped()
    b.doing = doing
    act = {'tap': 'a'}
    assert E.guard(b, act, s, 1., combat_action={'hold': ('zl', 'zr')}) is act


@pytest.mark.parametrize('fault', [None, 'stale', 'life', 'round', 'action', 'vtable', 'owner', 'read', 'unknown'])
def test_only_fresh_current_native_traversal_is_preserved(fault):
    from gbox.mercs.titles import re5_traversal as T
    b, s = scene()
    b.stats['round_evidence_id'] = 'this-round'
    action, vt = 0x5000000, 0x7000000
    p = s['player']
    obs = {'state': 'native', 'active': True, 'at': .9, 'owner': ['this-round', p['ptr'], p['generation']],
           'name': 'cOmWindowEvent_dive', 'action': action, 'action_vtable': vt}
    b.stats['traversal_observation'] = obs
    values = {p['ptr']+T.ACTION: action, action: vt, action+T.ACTOR_OWNER: p['ptr'],
              p['ptr']+0x1A00: p['generation']}
    if fault == 'stale': obs['at'] = .49
    elif fault == 'life': p['generation'] += 1
    elif fault == 'round': b.stats['round_evidence_id'] = 'new-round'
    elif fault == 'action': values[p['ptr']+T.ACTION] += 0x80
    elif fault == 'vtable': values[action] += 0x80
    elif fault == 'owner': values[action+T.ACTOR_OWNER] += 1
    elif fault == 'read': values.clear()
    elif fault == 'unknown': obs['name'] = 'unverified_window'
    b._m = SimpleNamespace(rd=lambda a, n: struct.pack('<Q', values[a]))
    act = {'hold': ('lup', 'b'), 'tap': 'a'}
    out = E.guard(b, act, s, 1.)
    if fault is None:
        assert out is act and b.stats['native_mine_escape_pause'] == 'verified active native traversal'
    else:
        assert out is not act and b.stats['native_mine_escape_pause'] is None


def test_blocked_combat_still_uses_actual_ray_gate_not_the_aim_write():
    b, _ = controller()
    _, s = scene(pos=(0., 0., 0.), mines={1: (0., 0., -300.)})
    mine_bot, _ = trapped()
    b.mines, b._sm, b._gun_down = mine_bot.mines, mine_bot._sm, mine_bot._gun_down
    s.update(aim_scene(heading=math.radians(30)))
    b._choose = lambda p, live, now: live[0]
    b._set_target = lambda key, now: setattr(b, 'target', key)
    b.aim_since = 0.
    act = E.defend(b, s, s['enemies'], 1.)
    assert act == {'hold': ('zl',)}
    act = E.guard(b, act, s, 1., before_aim=True)
    act = A.apply(b, s, act, 1.)
    assert b.stats['target_feedback_ram'] and not b.stats['target_feedback_on']
    assert E.guard(b, {'hold': ('ldown',)}, s, 1., combat_action=act)['hold'] == ('zl',)
    # A later observed aligned ray authorizes the trigger via apply(), not guard().
    s.update(aim_scene())
    act = E.defend(b, s, s['enemies'], 1.1)
    act = A.apply(b, s, act, 1.1)
    assert b.stats['target_feedback_on']
    assert set(E.guard(b, {'hold': ('lup',)}, s, 1.1, combat_action=act)['hold']) == {'zl', 'zr'}


def test_mine_action_yields_blocked_retreat_but_keeps_hazard_state():
    b, s = trapped()
    b.mines.automatic = lambda *a: {'hold': ('lup', 'b')}
    assert R.Bot._mine_action(b, s['player'], s, [], 1.) is None
    assert b.mines._native_escape is not None


def test_real_bot_keeps_aiming_and_firing_instead_of_restarting_raise(monkeypatch):
    monkeypatch.setattr(R, 'PS3_BRAIN', False)
    monkeypatch.setattr(R, 'HEAL_ENABLED', False)
    clock = [1.]
    b = R.Bot(stats={}, clock=lambda: clock[0])
    b._round_started = 0.
    b._new_round(0.)
    b._start_facing_done = True
    source, s = scene(pos=(0., 0., 0.), mines={1: (0., 0., -300.)})
    s.update(aim_scene())
    s['inventory'][0].update(id=0x11b, slot=0, type=1, rounds=50, cap=50, grid=0)
    s['timer'] = 180.
    b.mines = source.mines
    b.mines.stats = b.stats
    b.mines.observe_native = lambda *a: None
    room = SimpleNamespace(walk_block=lambda *a, **kw: 'closed exit')
    monkeypatch.setattr(b, '_room_map', lambda *a: room)
    monkeypatch.setattr(b, '_writer', lambda: (lambda *a: True))
    # The late wall governor really can replace a gun plan. The final guard
    # must recover only the aim feedback's accepted keys, not this rewrite.
    monkeypatch.setattr(b, '_wall_gov', lambda *a: {'hold': ('lup', 'b')})
    outputs = []
    for tick in range(15):
        clock[0] = 1. + tick * .15
        outputs.append(b.tick(s))
    assert all('zl' in a.get('hold', ()) for a in outputs)
    assert any('zr' in a.get('hold', ()) for a in outputs[4:])
    assert all(not (set(a.get('hold', ())) & S.MOVEMENT) for a in outputs)
    assert b.stats['raises'] == 1 and b.stats['shots'] > 0
