import json
import math
from types import SimpleNamespace

from gbox.mercs.navigation_incidents import Monitor, ReportWriter
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


def test_missing_goal_is_preserved_as_unknown_but_commanded_immobility_is_reported():
    m = Monitor(); feed(m, route=())
    assert m.active['distance_metric'] == 'unavailable'
    assert m.active['waypoint'] is None and m.active['goal_progress_cm'] is None


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
