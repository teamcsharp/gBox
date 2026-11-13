import json
from gbox.mercs.flight_recorder import FlightRecorder


def test_re5_camera_weapon_motion_and_aim_feedback_are_preserved():
    f = FlightRecorder()
    snap = {'player': {'motion': 26, 'pos': [0, 0, 0]}, 'mercenaries_phase': 1,
            'inventory': [{'hand': False, 'item': 2}, {'hand': True, 'item': 11}],
            'aim_cam': {'pitch': .3, 'heading': -.2}, 'laser': {'up': False}}
    stats = {'target_feedback_yaw_deg': 22., 'target_feedback_write_failures': 3,
             'target_feedback_gate': 'no current laser'}
    f.observe(1, snap, {}, stats)
    out = f.snapshot(); row = out['tail'][0]
    assert row['weapon'] == 11 and row['native_action'] == 26 and row['game_phase'] == 1
    assert row['camera'] == snap['aim_cam'] and row['diagnostics'] == stats
    assert out['signal_quality']['tail_field_samples']['camera'] == 1


def test_native_defensive_requests_are_bounded_and_detached_from_later_receipts():
    f = FlightRecorder()
    event = {'id': 3, 'kind': 'hit', 'at': 10.0, 'owner': ['round', 10, 20], 'damage': 100}
    stats = {'rapid_fire_configured_x': 20.0, 'rapid_fire_active': False, 'automine_enabled': True,
             'native_mine_pending': True, 'native_mine_request_id': 'request-1', 'native_mines_placed': 2,
             'automine_request_reason': 'hit', 'reactive_ring_requests': 3, 'reactive_ring_event': event,
             'reactive_escape_requests': 2, 'automine_request_count': 5,
             'native_mine_deployed_hazards': 5, 'native_mine_escape_required': True,
             'native_mine_escape_clearance_cm': 420., 'native_mine_escape_replans': 1,
             'native_mine_escape_blocked': {'required_cm': 1500., 'center': [100, 0, 200]}}
    f.observe(10, {'player': {'hp': 900, 'pos': [100, 0, 200]}},
              {'controls': {'keys': ['b', 'lup']}}, stats)
    event['damage'] = 999
    event['owner'][0] = 'next round'
    stats.update(native_mine_pending=False, native_mines_placed=3)
    row = f.snapshot()['tail'][0]
    assert row['diagnostics']['reactive_ring_event']['damage'] == 100
    assert row['diagnostics']['reactive_ring_event']['owner'][0] == 'round'
    assert row['diagnostics']['native_mine_pending'] is True
    assert row['diagnostics']['native_mines_placed'] == 2
    assert row['diagnostics']['native_mine_escape_required'] is True
    assert row['diagnostics']['native_mine_escape_blocked']['required_cm'] == 1500.
    assert row['diagnostics']['rapid_fire_configured_x'] == 20 and row['controls']['keys'] == ['b', 'lup']
    json.dumps(row, allow_nan=False)


def test_ground_mine_evidence_is_bounded_scaled_detached_and_preserves_trigger_not_in_hazard_list():
    f = FlightRecorder(.1)
    rows = [{'ptr': k, 'generation': 42, 'native_owner': 7, 'pos': [100, 200, 300],
             'active': True, 'trigger_observed': k == 0, 'primary_enabled': False,
             'proximity_enabled': True, 'unbounded_extra': 'x'*10000} for k in range(50)]
    f.observe(1, {'ground_mines': [], 'ground_mine_observations': rows}, {}, {})
    rows[0]['pos'][0] = 9999
    rows[0]['primary_enabled'] = True
    out = f.snapshot()
    for key in ('tail', 'timeline'):
        recorded = out[key][0]['ground_mines']
        assert len(recorded) == 40 and recorded[0]['pos'] == [10., 20., 30.]
        assert recorded[0]['trigger_observed'] is True and recorded[0]['primary_enabled'] is False
        assert 'unbounded_extra' not in recorded[0]
    json.dumps(out, allow_nan=False)


def test_missing_ground_mine_observation_is_distinct_from_confirmed_empty():
    f = FlightRecorder()
    f.observe(1, {}, {}, {})
    f.observe(2, {'ground_mines': []}, {}, {})
    rows = f.snapshot()['tail']
    assert rows[0]['ground_mines'] is None and rows[1]['ground_mines'] == []


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


def test_missing_intent_cannot_confirm_failure_and_missing_goal_stays_unknown():
    for plan in ({'phase': 'walk'}, {'phase': 'walk', 'controls': {'keys': ['lup']}}):
        f = FlightRecorder()
        for k in range(30):
            f.observe(k*.2, {'player': {'pos': [0, 0, 0]}}, plan, {})
        if 'controls' not in plan:
            assert f.findings == []
        else:
            assert f.findings[0]['goal_progress_cm'] is None
            assert 'unknown' in f.findings[0]['cause']


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
