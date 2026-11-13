"""Replay the Base b96ab135 ladder refusals without stepping through a gap.

Positions/headings are from navigation incidents 0001/0002 at 1794580884.361
and 1794580912.322. Geometry is the game's exported r403 SAT/AEV data.
The movement model below only exercises admission, not game traversal success.
"""
import math

import pytest

from gbox.mercs.titles import re4_nav as N, re4_room_map as R
from gbox.mercs.titles import re4_walk as W, re4_movement_safety as S, re4_traversal as T


CASES = [((41900., 20536.1, 15012.1), -2.20474267, (50900., 17468.1, 14900.)),
         ((51545.9, 20536.1, 26070.7), .584307015, (46100., 13548.7, 12300.))]


def observe(w, pos, yaw, now):
    w.observe({'player': {'pos': pos, 'rot': yaw, 'ptr': 101, 'id': 7, 'hp': 1000},
               'nav': N.load('r403'), 'room_map': R.load('r403'), 'game': {'in_control': True}}, now)


def reach_prompt(case):
    pos, yaw, goal = case
    w = W.Walker({'round_evidence_id': 'b96ab135'})
    commands = []
    for tick in range(60):
        observe(w, pos, yaw, tick*.1)
        wanted = w.approach(goal, run=True)
        act = S.guard(w, {'hold': set(wanted)})
        keys = act['hold']
        commands.append(keys)
        if 'y' in keys:
            assert keys == {'y'}
            assert w.portal_command['state'].startswith('stationary interaction')
            assert not w.stats.get('mesh_links_taken')  # a request is not a completed traversal
            return w, goal, commands
        if 'lleft' in keys:
            yaw = W.wrap(yaw+.1)
        if 'lright' in keys:
            yaw = W.wrap(yaw-.1)
        if 'lup' in keys:
            assert keys == {'lup'}
            end = (pos[0]+70*math.sin(yaw), pos[1], pos[2]+70*math.cos(yaw))
            assert w.mesh.floor_segment(pos, end)
            assert R.load('r403').walk_block(pos, end, end_r=0.) is None
            pos = end
        assert not keys & {'b', 'ldown'}
    pytest.fail('the recorded approach did not reach a stationary interaction within six seconds')


@pytest.mark.parametrize('case', CASES)
def test_recorded_ladder_approach_reaches_stationary_y_on_safe_floor(case):
    w, _, commands = reach_prompt(case)
    assert any('lup' in c for c in commands)
    assert w._pos()[1] == case[0][1]
    anchor = w.portal_command['anchor']
    assert w.mesh.floor_segment(w._pos(), anchor)
    assert R.load('r403').walk_block(anchor, anchor, end_r=w.clearance) is None
    assert math.dist(anchor, w._portal_plan['portal']) > 350.


def test_waiting_for_prompt_is_stationary_and_bounded_without_native_completion(tmp_path, monkeypatch):
    monkeypatch.setattr(W, 'CROSSING_LOG', tmp_path/'crossings.jsonl')
    w, goal, _ = reach_prompt(CASES[0])
    pos, yaw, start = w._pos(), w.p['rot'], w.now
    for i in range(1, 50):
        observe(w, pos, yaw, start+i*.1)
        act = S.guard(w, {'hold': set(w.approach(goal))})
        assert not act['hold'] & {'lup', 'ldown', 'b'}
        if w.stats.get('mesh_links_refused'):
            break
    assert w.stats['mesh_links_refused'] == 1
    assert not w.stats.get('mesh_links_taken')


def test_prompt_turn_and_release_are_not_overwritten_by_old_wall_recovery():
    w, goal, _ = reach_prompt(CASES[0])
    pos, yaw = w._pos(), w.p['rot']
    for now, turn in [(w.now+.1, .8), (w.now+.5, 0.)]:
        observe(w, pos, yaw+turn, now)
        keys = w.approach(goal)
        w._final_walk['recovery'] = {'heading': yaw, 'until': now+3., 'from': pos}
        out = S.guard(w, {'hold': set(keys)})
        assert out['hold'] == set(keys)
        assert not out['hold'] & {'lup', 'ldown', 'b'}
        assert w._final_walk['recovery'] is None


def test_portal_admission_cannot_remove_floor_or_wall_checks(monkeypatch):
    pos, _, goal = CASES[0]
    w = W.Walker({'round_evidence_id': 'b96ab135'})
    observe(w, pos, -2.8, 0.)
    keys = w.approach(goal)
    assert keys == ('lup',)
    monkeypatch.setattr(S, 'clear', lambda *args: False)
    out = S.guard(w, {'hold': set(keys)})
    assert not out['hold'] & {'lup', 'ldown', 'b'}
    assert w.stats['walk_final_guard'] == 'interaction approach blocked; no translation'


@pytest.mark.parametrize('change', ['time', 'actor', 'round', 'keys'])
def test_old_or_changed_portal_command_cannot_override_final_admission(change, monkeypatch):
    pos, _, goal = CASES[0]
    w = W.Walker({'round_evidence_id': 'b96ab135'})
    observe(w, pos, -2.8, 0.)
    w.approach(goal)
    act = {'hold': {'lup'}}
    if change == 'time':
        w.now += .1
    elif change == 'actor':
        w.p['id'] += 1
    elif change == 'round':
        w.stats['round_evidence_id'] = 'next'
    else:
        act['hold'].add('b')
    monkeypatch.setattr(S, 'clear', lambda *args: False)
    assert not S.guard(w, act)['hold'] & {'lup', 'ldown', 'b'}


def test_confirmed_native_traversal_does_not_retry_a_stationary_prompt_mid_air():
    w, goal, _ = reach_prompt(CASES[0])
    pos = (w._pos()[0], w._pos()[1]-900., w._pos()[2])
    observe(w, pos, w.p['rot'], w.now+.1)
    w.stats['traversal_observation'] = {'state': 'native', 'owner': T.identity(w.snap, w.stats),
        'at': w.now, 'routine': [0, 16, 0, 0], 'kind': 'ladder', 'handler': T.HANDLERS[16], 'pos': pos}
    assert w.approach(goal) == ()
    assert w.how == 'native traversal in progress'
    assert not w.no_exit()
    assert not w.stats.get('mesh_links_refused')
