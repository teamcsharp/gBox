import json
import math
from types import SimpleNamespace

from gbox.mercs.navigation_incidents import Monitor, ReportWriter, guard_started, guard_finished
from gbox.mercs.run_capture import RunCapture


def row(t, pos=(0, 0, 0), *, phase='walk', route=((1000, 0, 0),)):
    return {'t': t, 'pos': list(pos), 'phase': phase, 'player': 1, 'game_phase': 'playing',
            'controls': {'keys': ['lup']}, 'route': list(route), 'goal': {}}


def feed(m, start=0, count=17, pos=lambda k: (0, 0, 0), **kw):
    for k in range(count):
        m.observe(row(start+k*.2, pos(k), **kw))


def test_stall_opens_once_then_records_progress_and_a_new_incident_without_global_throttle():
    m = Monitor(); feed(m)
    assert m.sequence == 1 and m.active['collision_confirmed'] is None
    feed(m, start=3.4, count=6, pos=lambda k: (150, 0, 0))
    assert m.active is None and m.changes[-1]['outcome'] == 'progress_restored'
    feed(m, start=4.6)
    assert m.sequence == 2 and m.active['detected_at'] < 10


def test_circling_next_to_a_wall_reports_motion_without_claiming_collision():
    m = Monitor()
    feed(m, pos=lambda k: (0, 0, 50*math.sin(k*math.pi/4)))
    assert m.active['kinds'] == ['navigation_motion_without_progress']
    assert m.active['collision_confirmed'] is None


def test_travelling_along_a_wall_with_no_waypoint_progress_gets_a_report():
    m = Monitor()
    feed(m, count=33, pos=lambda k: (0, 0, k*10))
    assert m.active['kinds'] == ['navigation_path_progress_stalled']


def test_valid_corridor_detour_progresses_toward_waypoint_even_away_from_final_goal():
    m = Monitor()
    for k in range(40):
        r = row(k*.2, (0, 0, k*20), route=((0, 0, 1000),))
        r['goal'] = {'pos': (1000, 0, 0)}
        m.observe(r)
    assert not m.changes


def test_combat_and_telemetry_gaps_are_not_wall_evidence():
    m = Monitor(); feed(m, phase='aim')
    assert not m.changes
    feed(m, start=10)
    m.observe(row(20))
    assert m.changes[-1]['outcome'] == 'telemetry_gap' and m.active is None


def escape_row(t):
    r = row(t, (-2970.98, 500.11, 3914.22), phase='bomb', route=())
    r.update(native_action='cPlAction_pl_act_walk',
             controls={'keys': ['ldown', 'lleft'], 'source': 'transport_tracked_held_state'},
             diagnostics={'mine_escape_required': True, 'mine_clearance_cm': 721.1,
                          'bomb_escape_output': {'at': t-.1, 'act': 'bomb_escape',
                                                 'final_hold': ['ldown', 'lleft']}})
    return r


def test_remote_bomb_escape_stall_is_reported_and_native_catch_ends_navigation():
    m = Monitor()
    for k in range(17):
        m.observe(escape_row(k*.2))
    assert m.sequence == 1 and m.active['kinds'] == ['navigation_no_progress']
    assert m.active['collision_confirmed'] is None
    assert m.active['before'][-1]['diagnostics']['mine_clearance_cm'] == 721.1
    caught = escape_row(3.4)
    caught['native_action'] = 'cEm1000ActAtkFlyCatchHit_PL'
    m.observe(caught)
    assert m.active is None and m.changes[-1]['outcome'] == 'navigation_interrupted'


def test_blocked_walk_to_wait_is_still_a_commanded_escape_attempt():
    m = Monitor()
    for k in range(17):
        r = escape_row(k*.2)
        r['native_action'] = 'cPlAction_pl_act_walk_to_wait'
        m.observe(r)
    assert m.sequence == 1 and m.active['collision_confirmed'] is None


def test_bomb_placement_grabs_stale_plans_and_uncommanded_waits_are_not_escape_stalls():
    for invalid in ('placement', 'grab', 'dying', 'stale', 'future', 'no_pending', 'no_movement'):
        m = Monitor()
        for k in range(17):
            r = escape_row(k*.2)
            if invalid == 'placement': r['diagnostics']['bomb_escape_output']['act'] = 'bomb_place'
            elif invalid == 'grab': r['native_action'] = 'cEm5000ActNeckHangCS_PL'
            elif invalid == 'dying': r['native_action'] = 'cPlAction_pl_act_dying_loop'
            elif invalid == 'stale': r['diagnostics']['bomb_escape_output']['at'] = r['t']-1.
            elif invalid == 'future': r['diagnostics']['bomb_escape_output']['at'] = r['t']+.1
            elif invalid == 'no_pending': r['diagnostics']['mine_escape_required'] = False
            else: r['controls']['keys'] = []
            m.observe(r)
        assert m.sequence == 0 and not m.changes, invalid


def oscillating_escape_row(k):
    r = escape_row(k*.2)
    r.update(player_generation=3, pos=[20*math.sin(k*math.pi/4), 0, 0],
             throwables=[{'unit': 7, 'generation': 12, 'kind': 'remote'}])
    # Final floor vetoes alternate with actual movement; neither is a collision receipt.
    r['controls']['keys'] = ['lup'] if k % 2 else []
    r['diagnostics'].update(mine_deadline_at=-10., mine_deadline_pending=1,
                            mine_timing_source='native_placed_armed', mine_clearance_cm=800.)
    r['diagnostics']['bomb_escape_output']['requested_hold'] = ['lup']
    return r


def test_remote_escape_oscillation_and_floor_vetoes_report_actual_and_requested_inputs():
    m = Monitor()
    for k in range(32):
        m.observe(oscillating_escape_row(k))
    report = m.active
    assert report['kinds'] == ['remote_bomb_escape_without_progress']
    assert report['distance_metric'] == 'nearest_pending_bomb_clearance'
    assert report['goal_progress_cm'] == 0
    assert .4 < report['movement_command_coverage'] < .6
    assert report['movement_intent_coverage'] == 1.
    assert report['collision_confirmed'] is None and report['learning_applied'] is False
    for k in range(32, 39):
        r = oscillating_escape_row(k)
        r['diagnostics']['mine_clearance_cm'] = 910.
        m.observe(r)
    assert m.active is None and m.changes[-1]['outcome'] == 'clearance_progress_restored'


def test_escape_oscillation_requires_stable_bombs_player_intent_and_no_detour_progress():
    for mode in ('new_bomb', 'new_player', 'unknown_generation', 'no_intent',
                 'no_clearance', 'progress', 'detour', 'stairs', 'non_native_timing'):
        m = Monitor()
        for k in range(32):
            r = oscillating_escape_row(k)
            if mode == 'new_bomb': r['throwables'][0]['generation'] = k
            elif mode == 'new_player': r['player_generation'] = k
            elif mode == 'unknown_generation': r['throwables'][0].pop('generation')
            elif mode == 'no_intent': r['diagnostics']['bomb_escape_output']['requested_hold'] = []
            elif mode == 'no_clearance': r['diagnostics']['mine_clearance_cm'] = None
            elif mode == 'progress': r['diagnostics']['mine_clearance_cm'] += k*5
            elif mode == 'detour': r['pos'][0] = k*10
            elif mode == 'stairs': r['pos'][1] = k*5
            else: r['diagnostics']['mine_timing_source'] = 'request'
            m.observe(r)
        assert not m.changes, mode


def test_escape_report_does_not_join_a_replacement_bomb_to_the_old_episode():
    m = Monitor()
    for k in range(32):
        m.observe(oscillating_escape_row(k))
    r = oscillating_escape_row(32)
    r['throwables'][0]['generation'] = 13
    m.observe(r)
    assert m.active is None and m.changes[-1]['outcome'] == 'escape_hazards_changed'


def churn_row(k, pos=(0, 0, 0)):
    r = row(k*.2, pos, route=([(500, 0, 100)] if k % 2 else [(500, 0, -100)]))
    r.update(goal={'id': 'time-bonus'}, route_endpoint=[1000, 0, 0])
    return r


def test_changing_waypoints_cannot_hide_a_repeated_navigation_failure():
    m = Monitor()
    for k in range(17):
        m.observe(churn_row(k))
    assert m.active['kinds'] == ['navigation_waypoint_churn_without_progress']
    assert m.active['distance_metric'] == 'stable_final_goal_distance'
    assert m.active['collision_confirmed'] is None and m.sequence == 1
    for k in range(17, 22):
        m.observe(churn_row(k))
    assert m.sequence == 1  # waypoint changes do not close/reopen the same episode
    for k in range(22, 28):
        m.observe(churn_row(k, (150, 0, 0)))
    assert m.active is None and m.changes[-1]['outcome'] == 'progress_restored'


def test_waypoint_changes_alone_do_not_prove_a_navigation_failure():
    for mode in ('stairs', 'forward', 'new_goal', 'new_player', 'arrived', 'no_endpoint', 'uncommanded'):
        m = Monitor()
        for k in range(17):
            r = churn_row(k)
            if mode == 'stairs': r['pos'][1] = k*5
            elif mode == 'forward': r['pos'][0] = k*10
            elif mode == 'new_goal': r['goal']['id'] = str(k)
            elif mode == 'new_player': r['player_generation'] = k
            elif mode == 'arrived': r['pos'] = list(r['route'][0])
            elif mode == 'no_endpoint': r.pop('route_endpoint')
            else: r['controls'] = {'keys': []}
            m.observe(r)
        assert not m.changes, mode


def test_full_route_endpoint_survives_the_recorders_bounded_route_prefix():
    from gbox.mercs.flight_recorder import FlightRecorder
    cap = FlightRecorder(scale=.1)
    path = [(i*1000, 0, 0) for i in range(20)]
    cap.observe(1, {'player': {'pos': (0, 0, 0)}}, {'route': path}, {})
    r = cap.tail[-1]
    assert len(r['route']) == 12 and r['route_endpoint'] == [1900, 0, 0]


def test_missing_goal_is_preserved_as_unknown_but_commanded_immobility_is_reported():
    m = Monitor(); feed(m, route=())
    assert m.active['distance_metric'] == 'unavailable'
    assert m.active['waypoint'] is None and m.active['goal_progress_cm'] is None


def test_frozen_game_timer_is_explicitly_distinguished_from_proven_wall_contact():
    m = Monitor()
    for k in range(17):
        r = row(k*.2); r['timer'] = 120.
        m.observe(r)
    assert m.active['game_timer_span_s'] == 0
    assert 'stalled simulation' in m.active['evidence_warnings'][0]
    assert m.active['collision_confirmed'] is None


def test_report_is_written_before_round_end_with_input_and_geometry_context(tmp_path):
    cap = RunCapture(tmp_path/'round_maps', 'RE4', 'round1', threaded=False,
                     position_scale_to_cm=.1, provenance={'source_session_id': 'session1'})
    bot = SimpleNamespace(doing='walk', why='time bonus', plan=lambda: {
        'phase': 'walk', 'route': [(10000, 0, 0)], 'route_requires_prompt': True})
    mesh = SimpleNamespace(member=lambda pos: 0, points=[(0, 0, 0), (1000, 0, 0), (0, 0, 1000)],
                           tris=[(0, 1, 2)], links={0: []}, geometry_source='room_collision')
    stats = {'stage': 'Village'}
    for k in range(17):
        cap.input(k*.2, [{'key': 'lup', 'down': True}], {'sent': 1})
        cap.observe(k*.2, 'playing', {'player': {'ptr': 1, 'pos': (0, 0, 0), 'hp': 1000},
                                    'game': {'phase': 'playing', 'in_control': True}, 'nav': mesh},
                    bot, stats, controls={'keys': ['lup']})
    assert cap._finished is None and stats['navigation_incidents'] == 1
    files = list((tmp_path/'round_maps').rglob('round1-0001.json'))
    report = json.loads(files[0].read_text())
    assert report['state'] == 'open' and report['session_id'] == 'session1'
    assert report['waypoint'] == [1000, 0, 0] and report['input_events']
    assert report['geometry']['local_triangles'][0][1] == [100, 0, 0]
    assert report['before'][-1]['route_requires_prompt'] is True
    assert (tmp_path/'lessons'/'RE4.jsonl').exists()
    cap.finish(3.5, 'stopped')
    report = json.loads(files[0].read_text())
    assert report['outcome'] == 'round_ended' and report['state'] == 'closed'
    assert len((tmp_path/'lessons'/'RE4.jsonl').read_text().splitlines()) == 1


def test_storage_failure_is_visible_and_retry_keeps_the_report(tmp_path, monkeypatch):
    from gbox.mercs import run_capture
    m = Monitor(); feed(m)
    status = {}
    writer = ReportWriter(tmp_path, {'title': 'RE5', 'round_id': 'r'}, status, threaded=False)
    original = run_capture._atomic
    monkeypatch.setattr(run_capture, '_atomic', lambda *a: (_ for _ in ()).throw(OSError('disk unavailable')))
    writer.submit(m.changes[0], 'stage', [])
    assert writer.pending and 'disk unavailable' in status['navigation_report_error']
    monkeypatch.setattr(run_capture, '_atomic', original)
    writer.submit(m.changes[0], 'stage', [])
    assert not writer.pending and status['navigation_reports_written'] == 1


def test_short_measured_guard_stall_survives_recovery_and_phase_changes(tmp_path):
    cap = RunCapture(tmp_path/'round_maps', '010018100CD46000', 'short', threaded=False)
    stats = {'stage': 'Prison', 'round_evidence_id': 'short'}
    bot = SimpleNamespace(stats=stats, doing='walk', why='time bonus')
    player = {'ptr': 1, 'generation': 2, 'pos': [0, 0, 0], 'hp': 1000}
    goal = {'id': 'bonus', 'kind': 'bonus', 'pos': [1000, 0, 0]}
    route = [[500, 0, 0], [1000, 0, 0]]
    cap.observe(0, 'playing', {'player': player}, bot, stats, controls={'keys': ['lup']})
    guard_started(bot, 're5_wall_guard', player, .4, anchor=[0, 0, 0], effort_s=.4,
                  threshold_s=.35, progress_limit_cm=15, commands=['lup'], goal=goal, route=route)
    route.clear(); goal['pos'][0] = 9999  # the live route is discarded by the recovery
    cap.input(.41, [{'key': 'ldown', 'down': True}], {'sent': 1})
    bot.doing = 'aim'  # combat can preempt before the next capture sample
    guard_finished(bot, player, .48, 'recovery_interrupted')
    cap.observe(.6, 'playing', {'player': player}, bot, stats, controls={'keys': ['zl']})
    report = json.loads(next((tmp_path/'round_maps').rglob('short-0001.json')).read_text())
    assert report['outcome'] == 'recovery_interrupted' and report['collision_confirmed'] is None
    assert report['goal']['pos'] == [1000, 0, 0] and report['waypoint'] == [500, 0, 0]
    assert report['driver_witness']['commands'] == ['lup'] and report['input_events']
    cap.observe(.8, 'playing', {'player': player}, bot, stats, controls={'keys': ['zl']})
    assert cap.flight.navigation.sequence == 1
    assert len((tmp_path/'lessons'/'010018100CD46000.jsonl').read_text().splitlines()) == 1


def test_driver_witness_needs_measured_effort_identity_and_final_movement_commands():
    from copy import deepcopy
    bot = SimpleNamespace(stats={}, doing='walk', why='bonus')
    player = {'ptr': 1, 'pos': [0, 0, 0]}
    guard_started(bot, 're6_wall_guard', player, .4, anchor=[0, 0, 0], effort_s=.4,
                  threshold_s=.4, progress_limit_cm=15, commands=['lup'])
    for change in ({'commands': ['zl']}, {'effort_s': .2}, {'position_cm': [50, 0, 0]},
                   {'player': 2}, {'source': 'remembered_wall'}, {'detected_at': -10}):
        witness = deepcopy(bot.stats['navigation_obstruction_context']); witness.update(change)
        r = row(.6, phase='aim'); r['navigation_obstruction'] = witness
        m = Monitor(); m.observe(r)
        assert not m.changes, change


def test_guard_recovery_records_displacement_without_claiming_a_route_arrival():
    bot = SimpleNamespace(stats={}, doing='walk', why='bonus')
    player = {'ptr': 1, 'pos': [0, 0, 0]}
    guard_started(bot, 're5_wall_guard', player, .4, anchor=[0, 0, 0], effort_s=.4,
                  threshold_s=.35, progress_limit_cm=15, commands=['lup'])
    m = Monitor(); r = row(.4); r['navigation_obstruction'] = bot.stats['navigation_obstruction_context']
    m.observe(r)
    player['pos'] = [0, 0, -25]
    guard_finished(bot, player, .7, 'movement_restored')
    r = row(.8, pos=player['pos']); r['navigation_obstruction'] = bot.stats['navigation_obstruction_context']
    m.observe(r)
    assert m.sequence == 1 and m.active is None
    assert m.changes[-1]['outcome'] == 'movement_restored'
    assert m.changes[-1]['driver_witness']['recovery_position_cm'] == [0, 0, -25]
