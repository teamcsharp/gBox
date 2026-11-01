"""Automatic flashes need a live firing follow-through, not a census alone."""
from types import SimpleNamespace

import pytest

from gbox.mercs.titles import re5_switch as R
from gbox.mercs import interventions


@pytest.mark.parametrize('doing', ['aim', 'raise', 'mine', 'heal', 'walk', 'escape', 'held'])
def test_crowd_during_noncombat_actions_does_not_spawn_flashes(monkeypatch, doing):
    monkeypatch.setattr(R, 'GRENADES', True)
    b = R.Bot(stats={}, clock=lambda: 1.)
    b._m = SimpleNamespace(adapter=object())
    b.doing, b.fire_down = doing, True
    b.stats['target_feedback_on'] = True
    monkeypatch.setattr(R.threading, 'Thread', lambda **kw: pytest.fail('unplanned native flash'))
    b._grenade_crowd(crowd(), 1.)


def crowd():
    return {'mercenaries_phase': R.PHASE_PLAYING, 'player': {'hp': 1000, 'pos': (0., 0., 0.)},
            'enemies': [{'ptr': i+10, 'hp': 800, 'pos': (i*20., 0., 200.), 'motion': 80, 'act': 0}
                        for i in range(R.GRENADE_CROWD_N)]}


def test_verified_crowd_fire_can_flash_once_and_respects_cadence(monkeypatch):
    monkeypatch.setattr(R, 'GRENADES', True)
    calls = []
    monkeypatch.setattr(interventions, 'native_controller', lambda ad: SimpleNamespace(
        flash=lambda: calls.append(ad) or {'state': 'confirmed'}))
    monkeypatch.setattr(R.threading, 'Thread', lambda **kw: SimpleNamespace(start=kw['target']))
    b = R.Bot(stats={}, clock=lambda: 1.)
    b._m = SimpleNamespace(adapter=object())
    b.doing, b.fire_down = 'fire', True
    b.stats['target_feedback_on'] = False
    b._grenade_crowd(crowd(), 1.)
    assert not calls
    b.stats['target_feedback_on'] = True
    b._grenade_crowd(crowd(), 1.)
    b._grenade_crowd(crowd(), 1.1)
    assert len(calls) == 1 and b.stats['bot_grenades'] == 1
    assert b.stats['bot_grenade_state'] == 'confirmed' and 'attack windup' in b.stats['bot_grenade_reason']


@pytest.mark.parametrize('invalid', ['owner', 'camera', 'target', 'writer'])
def test_old_firing_feedback_cannot_flash_after_validation_fails(monkeypatch, invalid):
    from tests.test_re5_target_feedback import scene
    from gbox.mercs.titles import re5_switch_aim as F
    monkeypatch.setattr(R, 'GRENADES', True)
    monkeypatch.setattr(R.threading, 'Thread', lambda **kw: pytest.fail('stale contact authorized a flash'))
    b = R.Bot(stats={}, clock=lambda: .3)
    b._m = SimpleNamespace(adapter=object())
    b._writer = lambda: lambda *args: True
    b._aim_h = lambda *args: R.CHEST_H
    b.target, b.aim_since, b.doing = 2, 0., 'fire'
    s = scene()
    s['laser']['at'] = (0., R.CHEST_H, 300.)
    assert 'zr' in F.apply(b, s, {'hold': ('zl',)}, .3)['hold']
    assert b.fire_down and b.stats['target_feedback_on']
    if invalid == 'owner': s['aim_cam']['generation'] += 1
    elif invalid == 'camera': s['aim_cam'] = None
    elif invalid == 'target': s['enemies'] = []
    elif invalid == 'writer': b._writer = lambda: lambda *args: False
    act = F.apply(b, s, {'hold': ('zl', 'zr')}, .33)
    assert 'zr' not in act['hold'] and not b.fire_down and not b.stats['target_feedback_on']
    b._grenade_crowd(crowd(), .33)


@pytest.mark.parametrize('change', ['standing', 'unknown', 'far', 'other_floor', 'dead'])
def test_census_without_verified_close_live_attack_does_not_flash(monkeypatch, change):
    b = R.Bot(stats={}, clock=lambda: 1.)
    b._m = SimpleNamespace(adapter=object())
    b.doing, b.fire_down = 'fire', True
    b.stats['target_feedback_on'] = True
    s = crowd()
    for e in s['enemies']:
        if change == 'standing': e.update(motion=4, act=0)
        elif change == 'unknown': e.update(motion=85, act=None)  # no invented stun/attack interpretation
        elif change == 'far': e['pos'] = (e['pos'][0], 0., R.WINDUP_R+20)
        elif change == 'other_floor': e['pos'] = (e['pos'][0], R.LEVEL_DY+1, 200.)
        elif change == 'dead': e['hp'] = 0
    monkeypatch.setattr(R.threading, 'Thread', lambda **kw: pytest.fail('census authorized a flash'))
    b._grenade_crowd(s, 1.)
    assert b.stats['bot_grenade_state'] == 'idle'


def test_attack_flag_is_useful_evidence_and_success_clears_prior_failure(monkeypatch):
    b = R.Bot(stats={}, clock=lambda: 1.)
    b._m = SimpleNamespace(adapter=object())
    b.doing, b.fire_down = 'fire', True
    b.stats.update(target_feedback_on=True, bot_grenade_reason='Unavailable: old death',
                   bot_grenade_error='Unavailable: old death')
    s = crowd()
    for e in s['enemies']: e.update(motion=4, act=0)
    s['enemies'][0]['act'] = R.E_ATTACKING
    monkeypatch.setattr(interventions, 'native_controller', lambda ad: SimpleNamespace(flash=lambda: {'state':'confirmed'}))
    monkeypatch.setattr(R.threading, 'Thread', lambda **kw: SimpleNamespace(start=kw['target']))
    b._grenade_crowd(s, 1.)
    assert b.stats['bot_grenade_threats'] == 1 and b.stats['bot_grenade_threat'] == 10
    assert b.stats['bot_grenade_error'] == '' and 'old death' not in b.stats['bot_grenade_reason']
    assert b.stats['bot_grenade_requested_at'] == 1.


def test_native_nonconfirmation_never_counts_as_success(monkeypatch):
    b = R.Bot(stats={}, clock=lambda: 1.)
    b._m = SimpleNamespace(adapter=object())
    b.doing, b.fire_down = 'fire', True
    b.stats['target_feedback_on'] = True
    monkeypatch.setattr(interventions, 'native_controller', lambda ad: SimpleNamespace(
        flash=lambda: {'state':'refused', 'reason':'player changed'}))
    monkeypatch.setattr(R.threading, 'Thread', lambda **kw: SimpleNamespace(start=kw['target']))
    b._grenade_crowd(crowd(), 1.)
    assert not b.stats.get('bot_grenades') and not b._grenade_inflight
    assert b.stats['bot_grenade_state'] == 'unconfirmed' and b.stats['bot_grenade_reason'] == 'player changed'
