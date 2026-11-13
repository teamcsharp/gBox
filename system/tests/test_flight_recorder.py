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


def test_input_edges_survive_snapshot_throttling_and_never_assert_game_effects():
    f = FlightRecorder()
    f.observe(0, {'player': {'hp': 1}}, {}, {})
    f.input(.01, [{'key': 'zr', 'down': True}], {'sent': 1})
    f.input(.03, [{'key': 'zr', 'down': False}], None)
    f.input(.04, [{'key': 'lup', 'down': True}], {'sent': 0, 'held': True})
    f.observe(.05, {'player': {'hp': 1}}, {}, {})
    out = f.snapshot()
    assert len(out['tail']) == 1 and len(out['inputs']) == 3
    assert [r['transport'] for r in out['inputs']] == ['accepted', 'no_receipt', 'refused_or_partial']
    assert out['input_events'] == out['input_batches'] == 3
    assert 'no input evidence' in out['signal_quality']['warnings']  # held state still unavailable
    f.input(61, [{'key': 'lup', 'down': False}], True)
    assert len(f.snapshot()['inputs']) == 1


def test_quality_separates_empty_controls_from_unavailable_and_reports_sampling_gaps():
    f = FlightRecorder()
    for t in (1, 1.2, 5):
        f.observe(t, {'player': {'hp': 100, 'pos': [0, 0, 0]}}, {'controls': {'keys': []}}, {})
    q = f.snapshot()['signal_quality']
    assert q['tail_samples'] == q['tail_field_samples']['controls'] == 3
    assert q['tail_max_gap_s'] == 3.8 and q['tail_gaps_over_1s'] == 1
    assert 'no input evidence' not in q['warnings']
