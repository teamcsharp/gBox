import json
from gbox.mercs.flight_recorder import FlightRecorder


def record(phase='walk', step=0, turns=False, scale=1):
    f = FlightRecorder(scale)
    for k in range(30):
        keys = ['lup'] + (['lleft' if k % 2 else 'lright'] if turns else [])
        s = {'player': {'pos': [k*step, k*step, 0], 'hp': 1000}, 'game': {'phase': 'playing'}}
        plan = {'phase': phase, 'controls': {'keys': keys},
                'operator_goal': {'id': 'stairs', 'pos': [1000, 1000, 0]}}
        f.observe(k*.2, s, plan, {})
    return f


def test_stationary_navigation_has_timestamped_evidence():
    findings = record(turns=True).snapshot()['findings']
    assert {v['kind'] for v in findings} == {
        'navigation_no_progress', 'alternating_turn_commands_without_progress'}
    assert all(v['to_t'] > v['from_t'] and v['travel_cm'] == 0 for v in findings)


def test_combat_and_stair_progress_are_not_navigation_failures():
    assert record('fire', turns=True).findings == []
    assert record(step=20, turns=True).findings == []


def test_evidence_is_detached_and_never_guesses_wall_hits():
    f = FlightRecorder(.1)
    pos = [100, 200, 300]
    plan = {'controls': {'keys': ['zl']}, 'target': {'id': 4, 'pos': pos},
            'operator_goal': {'pos': pos}, 'route': [pos]}
    f.observe(1, {'player': {'pos': pos}, 'aim': {'bad': float('nan')}}, plan, {'shots': 100})
    pos[0] = 99999
    plan['controls']['keys'].append('lup')
    out = f.snapshot()
    row = out['tail'][0]
    assert row['pos'] == row['target']['pos'] == row['goal']['pos'] == row['route'][0] == [10, 20, 30]
    assert row['controls']['keys'] == ['zl'] and row['aim']['bad'] is None
    assert out['findings'] == []
    json.dumps(out, allow_nan=False)


def test_missing_intent_or_goal_never_confirms_a_navigation_failure():
    for plan in ({'phase': 'walk'}, {'phase': 'walk', 'controls': {'keys': ['lup']}}):
        f = FlightRecorder()
        for k in range(30):
            f.observe(k*.2, {'player': {'pos': [0, 0, 0]}}, plan, {})
        assert f.findings == []
