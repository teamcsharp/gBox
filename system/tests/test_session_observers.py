from concurrent.futures import Future
import io
from types import SimpleNamespace

from fastapi.testclient import TestClient
from PIL import Image
import pytest

from gbox.config import Config
from gbox.server import create_app
from gbox.session_observers import SessionObservers, analyze
from gbox.store import Store


def png(color='red'):
    out = io.BytesIO()
    Image.new('RGB', (40, 40), color).save(out, 'PNG')
    return out.getvalue()


@pytest.fixture
def observer(tmp_path):
    store = Store(tmp_path)
    session = {'session_id': 'worker-launch', 'game_id': 'testgame', 'title': 'Test game',
               'state': 'running', 'last_frame_age': 1}
    store.put('session', session['session_id'], session)
    calls = []
    def api(path, body=None, *, binary=False):
        calls.append((path, body))
        if path == '/api/sessions?include_ended=false':
            return store.all('session')
        if path == '/api/workers':
            return [{'id': 'worker', 'online': True}]
        if binary:
            return png()
        if path == '/api/requests':
            req = body | {'id': 'request' + str(len(store.all('request'))), 'number': 1, 'status': 'open'}
            store.put('request', req['id'], req)
            return req
        if path == '/api/jobs':
            job = body | {'id': 'job' + str(len(store.all('job'))), 'state': 'queued'}
            store.put('job', job['id'], job)
            return job
        if path.startswith('/api/requests/') and path.endswith('/status'):
            rid = path.split('/')[3]
            req = store.get('request', rid) | body
            store.put('request', rid, req)
            return req
        raise AssertionError(path)
    o = SessionObservers(store, Config(data_dir=tmp_path), api, clock=lambda: 1000,
                         observe=lambda *_: {'summary': 'Player walking', 'actors': ['player']})
    o.calls, o.session = calls, session
    yield o
    o.close()


def test_unknown_game_attaches_two_roles_and_creates_one_repair(observer):
    o = observer
    for _ in range(2):
        o.tick()
        for f in list(o.pending.values()):
            f.result()
    row = o.store.get('session_observer', 'worker-launch')
    assert row['state'] == 'attached'
    assert row['samples'] == 1
    assert row['models']['state'] == 'unsupported'
    assert row['models']['request_id'] == 'request0'
    req = o.store.all('request')[0]
    assert req['context']['passive_only']
    assert len(o.store.all('request')) == 1
    assert not o.store.all('job')
    assert o.store.read_artifact(row['latest']['frame'])


def test_same_game_multiple_sessions_share_model_repair(observer):
    o = observer
    o._models(o.session)
    o._models(o.session | {'session_id': 'worker-second'})
    assert len(o.store.all('request')) == 1
    assert o.store.get('session_observer', 'worker-second')['models']['request_id'] == 'request0'


def test_concurrent_failures_share_one_repair_and_reopen_premature_completion(observer):
    from concurrent.futures import ThreadPoolExecutor
    o = observer
    with ThreadPoolExecutor(max_workers=4) as pool:
        ids = list(pool.map(lambda _: o._gap(o.session, 'observation', 'broken'), range(8)))
    assert set(ids) == {'request0'}
    old = o.store.get('request', 'request0')
    o.store.put('request', 'request0', old | {'status': 'done'})
    o._gap(o.session, 'observation', 'still broken')
    assert o.store.get('request', 'request0')['status'] == 'open'
    assert len(o.store.all('request')) == 1


def test_unchanged_frames_skip_inference_and_survive_restart(observer):
    o = observer
    o.sample(o.session)
    o.observe = lambda *_: pytest.fail('unchanged frame called model')
    o.sample(o.session)
    assert len(o.store.all('session_observation')) == 1
    assert o.store.get('session_observer', 'worker-launch')['gameplay_state'] == 'unchanged'


def test_end_during_inference_discards_live_result(observer):
    o = observer
    def end(*_):
        o.store.put('session', 'worker-launch', o.session | {'state': 'ended'})
        return {'summary': 'late'}
    o.observe = end
    o.sample(o.session)
    o.tick()
    assert not o.store.all('session_observation')
    assert o.store.get('session_observer', 'worker-launch')['state'] == 'ended'


def test_pause_during_inference_discards_live_result(observer):
    o = observer
    def pause(*_):
        o._put('worker-launch', enabled=False)
        return {'summary': 'late'}
    o.observe = pause
    o.sample(o.session)
    assert not o.store.all('session_observation')


def test_frame_fallback_never_duplicates_pending_job_or_sends_controls(observer):
    o = observer
    o.session['last_frame_age'] = None
    o.sample(o.session); o.sample(o.session)
    assert len(o.store.all('job')) == 1
    job = o.store.all('job')[0]
    assert job['tool'] == 'get_frame' and job['input'] == {'session_id': 'worker-launch'}
    ref = o.store.put_artifact(png(), 'frame.png', 'image/png', {})
    o.store.put('job', job['id'], job | {'state': 'succeeded', 'finished': 999, 'output': {'sha256': ref.sha256}})
    o.sample(o.session)
    assert o.store.get('session_observer', 'worker-launch')['samples'] == 1
    assert len(o.store.all('job')) == 1


def test_failed_capture_backs_off_and_becomes_one_actionable_request(observer):
    o = observer
    o.observe = lambda *_: (_ for _ in ()).throw(RuntimeError('vision unavailable'))
    for _ in range(4):
        o.sample(o.session)
    row = o.store.get('session_observer', 'worker-launch')
    assert row['gameplay_state'] == 'blocked' and row['next_sample'] > 1000
    assert row['observation_request_id'] == 'request0'
    assert len(o.store.all('request')) == 1 and not o.store.all('session_observation')


def test_agent_sessions_excluded_until_operator_claims_them(observer):
    o = observer
    o.store.put('job', 'launch', {'id': 'launch', 'agent_use': True})
    o.tick()
    assert not o.store.all('session_observer')
    o.store.put('slabel', 'worker-launch', {'owner': 'you'})
    o.tick()
    assert o.store.get('session_observer', 'worker-launch')['state'] == 'attached'


def test_offline_sessions_do_not_queue_capture_or_models(observer):
    o = observer
    original = o.api
    o.api = lambda path, *args, **kwargs: [] if path == '/api/workers' else original(path, *args, **kwargs)
    o.tick()
    assert o.store.get('session_observer', 'worker-launch')['state'] == 'offline'
    assert not o.pending and not o.store.all('request') and not o.store.all('job')


def test_stalled_stream_waits_instead_of_starting_another_capture(observer):
    # docs/stream-stability.md: a stale stream means the machine is struggling; one more ffmpeg grab job makes it worse.
    o = observer
    o.session['last_frame_age'] = 42
    o.sample(o.session)
    row = o.store.get('session_observer', 'worker-launch')
    assert row['gameplay_state'] == 'waiting_for_frame' and 'stalled' in row['error']
    assert not o.store.all('job') and not o.store.all('request')


def test_stale_model_gap_closes_once_a_registered_reader_collects(observer):
    """#1623: the gap filed before the Twin Snakes reader shipped closes with evidence when collection succeeds,
    and a later failure reopens the same request."""
    o = observer
    o._models(o.session)
    assert o.store.get('request', 'request0')['status'] == 'open'
    o.store.put('job', 'collect1', {'id': 'collect1', 'state': 'succeeded', 'output': {
        'result': {'characters': 17, 'collected': 17, 'status': 'complete', 'entries': []}}})
    o.store.put('character_collection', 'testgame', {'state': 'queued', 'job_id': 'collect1', 'updated': 1})
    o._models(o.session | {'session_id': 'worker-later'})
    req = o.store.get('request', 'request0')
    assert req['status'] == 'done' and 'collected 17 of 17' in req['note'] and 'collect1' in req['note']
    assert o.store.get('session_observer', 'worker-later')['models']['request_id'] == 'request0'
    assert len(o.store.all('request')) == 1
    n = len(o.calls)
    o._models(o.session | {'session_id': 'worker-later'})       # already done: no repeated status writes
    assert not [c for c in o.calls[n:] if c[0].endswith('/status')]
    o.store.put('job', 'collect1', o.store.get('job', 'collect1') | {'state': 'failed', 'error': 'disc missing'})
    o._models(o.session)
    assert o.store.get('request', 'request0')['status'] == 'open'


def test_succeeded_collection_without_a_gap_files_nothing(observer):
    o = observer
    o.store.put('job', 'c', {'id': 'c', 'state': 'succeeded', 'output': {'result': {'characters': 2, 'collected': 2}}})
    o.store.put('character_collection', 'testgame', {'state': 'queued', 'job_id': 'c', 'updated': 1})
    o._models(o.session)
    assert not o.store.all('request')
    assert 'request_id' not in o.store.get('session_observer', 'worker-launch')['models']


def test_ended_session_view_shows_current_collection_not_frozen_snapshot(tmp_path):
    cfg = Config(data_dir=tmp_path)
    app = create_app(cfg)
    st = app.state.store
    st.put('session', 's', {'state': 'ended', 'game_id': 'g'})
    st.put('session_observer', 's', {'session_id': 's', 'game_id': 'g', 'state': 'ended', 'models': {
        'state': 'unsupported', 'updated': 5, 'message': 'No native model reader registered for this game.',
        'request_id': 'r1'}})
    st.put('job', 'j', {'id': 'j', 'state': 'succeeded', 'output': {'result': {'characters': 3, 'collected': 3}}})
    st.put('character_collection', 'g', {'state': 'queued', 'job_id': 'j', 'updated': 9})
    with TestClient(app) as client:
        client.headers['Authorization'] = 'Bearer ' + cfg.token()
        data = client.get('/api/sessions/s/observers').json()
    m = data['models']
    assert m['state'] == 'succeeded' and m['result']['collected'] == 3 and m['request_id'] == 'r1'
    assert m['snapshot']['state'] == 'unsupported'
    models_agent = next(a for a in data['goals']['agents'] if a['agent'] == 'models')
    assert 'No native model reader' not in models_agent['blocked_by']


def test_collection_waits_while_the_operator_plays_on_the_linux_node(observer):
    o = observer
    original = o.api
    o.api = lambda path, *args, **kwargs: ([{'id': 'worker', 'online': True, 'os': 'linux'}] if path == '/api/workers'
                                           else original(path, *args, **kwargs))
    o.tick()
    for f in list(o.pending.values()):
        f.result()
    row = o.store.get('session_observer', 'worker-launch')
    assert row['models']['state'] == 'not_started'           # reported, not scheduled
    assert not o.store.get('character_collection', 'testgame')


def test_bounded_admission_attaches_all_sessions(observer):
    o = observer
    o.pool.shutdown()
    class Pool:
        def submit(self, *_):
            return Future()
        def shutdown(self, **_):
            pass
    o.pool = Pool()
    for i in range(5):
        sid = 'worker-s' + str(i)
        o.store.put('session', sid, o.session | {'session_id': sid})
    o.tick()
    assert len(o.store.all('session_observer')) == 6
    assert len(o.pending) == 2


def test_observer_api_requires_auth_and_preserves_history(tmp_path):
    cfg = Config(data_dir=tmp_path)
    app = create_app(cfg)
    app.state.store.put('session', 's', {'state': 'running'})
    app.state.store.put('session_observer', 's', {'session_id': 's', 'history': [{'summary': 'test'}]})
    with TestClient(app) as client:
        assert client.get('/api/sessions/s/observers').status_code == 401
        client.headers['Authorization'] = 'Bearer ' + cfg.token()
        assert client.get('/api/sessions/missing/observers').status_code == 404
        data = client.post('/api/sessions/s/observers', json={'enabled': False}).json()
        assert data['enabled'] is False and data['state'] == 'paused'
        assert data['history'] == [{'summary': 'test'}]
        assert data['service_online'] is False
        assert client.post('/api/sessions/s/observers', json={'enabled': 'yes'}).status_code == 422


def test_vision_has_no_tools_and_validates_output(monkeypatch):
    from gbox import session_observers as module
    calls = []
    class Client:
        def __init__(self, **_): pass
        def __enter__(self): return self
        def __exit__(self, *_): pass
        def post(self, url, **kwargs):
            calls.append(kwargs['json'])
            return SimpleNamespace(raise_for_status=lambda: None,
                json=lambda: {'choices': [{'message': {'content': '{"summary":"A vehicle", "actors":["yellow taxi"]}'}}]})
    monkeypatch.setattr(module.httpx, 'Client', Client)
    result = analyze(Config(), png(), None)
    assert result['actors'] == ['yellow taxi']
    assert 'tools' not in calls[0] and calls[0]['max_tokens'] == 1000


def test_session_repair_is_admitted_with_passive_prompt():
    from gbox import hermes_work_queue as q
    data = {'items': {}}
    request = {'id': 'a'*16, 'number': 1, 'title': 'Session models', 'source': 'gap', 'automated': True,
               'status': 'open', 'context': {'session_observer': True, 'game_id': 'b'*16}}
    q.sync(data, {'count': 0, 'items': []}, [request], now=1)
    item = data['items']['inbox:' + request['id']]
    assert item['session_observer']
    assert 'Never send input' in q._prompt(item)


def failed_frame(o, error):
    """Queue the observer's get_frame job, then fail it the way the worker reports it."""
    o.session['last_frame_age'] = None
    o.sample(o.session)
    job = next(j for j in o.store.all('job') if j['state'] == 'queued')
    o.store.put('job', job['id'], job | {'state': 'failed', 'finished': 999, 'error': error})
    o.sample(o.session)


def test_closed_game_window_after_frames_is_not_a_capture_repair(observer):
    # #1371: Dolphin kept running without a window and the operator's own load_state failed too.
    o = observer
    o.sample(o.session)  # a real frame proves the capture route for this session
    for _ in range(4):
        failed_frame(o, "RuntimeError: the game window isn't open")
    row = o.store.get('session_observer', 'worker-launch')
    assert row['gameplay_state'] == 'no_window' and row['failures'] == 0
    assert row['window_failures'] == 4 and row['window_missing_since'] == 1000
    assert row['next_sample'] == 1000 + 120 and "window isn't open" in row['error']
    assert not o.store.all('request') and all(c[0] != '/api/requests' for c in o.calls)
    assert all(j['tool'] == 'get_frame' for j in o.store.all('job'))  # still passive: no session_op


def test_window_never_captured_still_files_one_capture_repair(observer):
    # Without one frame the window lookup itself may be broken (e.g. a launcher PID): keep it repairable.
    o = observer
    for _ in range(3):
        failed_frame(o, "RuntimeError: the game window isn't open")
    row = o.store.get('session_observer', 'worker-launch')
    assert row['gameplay_state'] == 'blocked' and row['failures'] == 3
    assert row['observation_request_id'] == 'request0' and len(o.store.all('request')) == 1


def test_covered_window_waits_and_the_next_frame_clears_the_miss(observer):
    o = observer
    o.sample(o.session)
    failed_frame(o, 'RuntimeError: the game window is covered by another app; bring gBox or the emulator '
                    'forward before capturing')
    row = o.store.get('session_observer', 'worker-launch')
    assert row['gameplay_state'] == 'covered' and row['window_failures'] == 1 and not o.store.all('request')
    o.session['last_frame_age'] = 1
    o.sample(o.session)  # the same picture comes back: unchanged, and the window is visible again
    row = o.store.get('session_observer', 'worker-launch')
    assert row['gameplay_state'] == 'unchanged' and row['window_failures'] == 0
    assert row['window_missing_since'] is None and row['failures'] == 0


def test_capture_for_an_ended_session_is_stopped_not_a_repair(observer):
    o = observer
    for _ in range(3):
        failed_frame(o, 'game session ended before the job could run')
    row = o.store.get('session_observer', 'worker-launch')
    assert row['gameplay_state'] == 'stopped' and row.get('failures', 0) == 0 and not o.store.all('request')


def test_worker_without_the_session_is_stopped_not_a_repair(observer):
    # #1371 live check: after stop_game, get_frame jobs c4e81d36dcd849d5, b4e56aadc55246f8 and bf333fafb5c64d78
    # reached the worker, which no longer had the session and failed with KeyError('<session id>').
    o = observer
    o.sample(o.session)
    for _ in range(4):
        failed_frame(o, "KeyError: 'worker-launch'")
    row = o.store.get('session_observer', 'worker-launch')
    assert row['gameplay_state'] == 'stopped' and row.get('failures', 0) == 0
    assert not o.store.all('request') and all(c[0] != '/api/requests' for c in o.calls)


def test_other_key_errors_still_count_toward_one_capture_repair(observer):
    o = observer
    for _ in range(3):
        failed_frame(o, "KeyError: 'sha256'")
    row = o.store.get('session_observer', 'worker-launch')
    assert row['gameplay_state'] == 'blocked' and row['failures'] == 3 and len(o.store.all('request')) == 1


def test_any_capture_failure_after_the_session_ended_is_stopped(observer):
    o = observer
    o.sample(o.session)
    o.store.put('session', 'worker-launch', o.session | {'state': 'ended'})
    for _ in range(3):
        failed_frame(o, 'RuntimeError: ffmpeg exited with status 1')
    row = o.store.get('session_observer', 'worker-launch')
    assert row['gameplay_state'] == 'stopped' and row.get('failures', 0) == 0 and not o.store.all('request')


def test_worker_session_gone_is_stopped_not_a_repair(observer):
    # Workers since #840 raise tools.SessionGone instead of a bare KeyError for a session they no longer hold.
    o = observer
    o.sample(o.session)
    for _ in range(4):
        failed_frame(o, 'SessionGone: This game session (worker-launch) is no longer running on this PC: the worker '
                        'restarted or another game replaced it. Relaunch the game to continue.')
    row = o.store.get('session_observer', 'worker-launch')
    assert row['gameplay_state'] == 'stopped' and row.get('failures', 0) == 0 and not o.store.all('request')


def test_vision_timeouts_back_off_and_file_one_repair_only_after_a_window(observer):
    # #1455: the Spark was saturated (load 27, GPU 94 percent) and the vision model timed out on Ocarina of
    # Time; three timeouts filed a repair for a route that was fine. Timeouts now back off instead.
    import httpx
    from gbox import session_observers as module
    o = observer
    now = [1000.0]
    o.clock = lambda: now[0]
    o.observe = lambda *_: (_ for _ in ()).throw(httpx.ReadTimeout('timed out'))
    delays = []
    for _ in range(module.TIMEOUT_GAP_COUNT - 1):
        o.sample(o.session)
        row = o.store.get('session_observer', 'worker-launch')
        delays.append(row['next_sample'] - now[0])
        now[0] = row['next_sample']
    assert delays == [60, 120, 240, 480]
    assert row['gameplay_state'] == 'backing_off' and row['timeouts'] == 4 and row['timeout_since'] == 1000
    assert row.get('failures', 0) == 0 and 'timed out' in row['error']
    assert not o.store.all('request') and all(c[0] != '/api/requests' for c in o.calls)

    # one answer ends the streak; the next slow spell starts counting from zero
    o.observe = lambda *_: {'summary': 'Link in Kokiri Forest'}
    o.sample(o.session)
    row = o.store.get('session_observer', 'worker-launch')
    assert row['gameplay_state'] == 'watching' and row['timeouts'] == 0 and row['timeout_since'] is None

    # a capture job the worker failed with a bare TimeoutError (the #1455 reason text) is the same load symptom
    start = now[0] = 5000.0
    o.session['last_frame_age'] = None
    while now[0] - start < module.TIMEOUT_GAP_WINDOW:
        failed_frame(o, 'TimeoutError: ')
        row = o.store.get('session_observer', 'worker-launch')
        assert row['gameplay_state'] == 'backing_off' and row.get('failures', 0) == 0
        assert not o.store.all('request')  # timeouts inside the window never file a repair
        assert row['next_sample'] - now[0] <= module.TIMEOUT_BACKOFF[1]
        now[0] = row['next_sample']
    failed_frame(o, 'TimeoutError: ')  # still timing out after the whole window: now it is a repair
    row = o.store.get('session_observer', 'worker-launch')
    assert row['timeouts'] >= module.TIMEOUT_GAP_COUNT and row['timeout_since'] == start
    assert row['observation_request_id'] == 'request0' and len(o.store.all('request')) == 1
    assert 'timeouts over' in o.store.get('request', 'request0')['body']
    failed_frame(o, 'TimeoutError: ')
    assert len(o.store.all('request')) == 1


def test_timeout_detection():
    import httpx
    from gbox.session_observers import is_timeout
    assert is_timeout(TimeoutError()) and is_timeout(httpx.ConnectTimeout('x'))
    assert is_timeout(RuntimeError('TimeoutError: ')) and is_timeout(RuntimeError('ReadTimeout: timed out'))
    assert not is_timeout(RuntimeError('vision unavailable')) and not is_timeout(KeyError('sha256'))



# ---------------------------------------------------------------- #1602: malformed vision JSON, schema-constrained replies
import json as _json
from types import SimpleNamespace as _NS

import httpx as _httpx
import pytest as _pytest

from gbox import session_observers as _so

# The shape of the DOA2 LE failure on session 2882962538984a44-18835ca8a18e4a03: on-screen text quoted without
# escaping, which json rejects with "Expecting ',' delimiter".
DOA2_REPLY = """{
  "summary": "Two fighters face off in a dojo; the banner "ROUND 2" is shown.",
  "actors": ["Character in purple outfit (player 1)", "Character in red and white outfit with pink hair (player 2)"],
  "changes": ["The banner "ROUND 2" appeared"],
  "hud": ["Damage/Revision: 40/100%", "Total/Max DMG: 40/45", "Combo/Max Combo: 0/2"],
  "mechanics_hypotheses": ["Rounds are announced between bouts"],
  "uncertainties": ["Which fighter the operator controls"]
}"""


def test_1602_doa2_unescaped_quotes_are_repaired_not_a_failure():
    with _pytest.raises(_json.JSONDecodeError, match="Expecting ',' delimiter"):
        _json.loads(DOA2_REPLY)
    result = _so.parse_observation(DOA2_REPLY)
    assert result['repaired_json'] is True
    assert result['summary'] == 'Two fighters face off in a dojo; the banner "ROUND 2" is shown.'
    assert result['changes'] == ['The banner "ROUND 2" appeared']
    assert result['hud'] == ['Damage/Revision: 40/100%', 'Total/Max DMG: 40/45', 'Combo/Max Combo: 0/2']
    assert len(result['actors']) == 2 and result['uncertainties'] == ['Which fighter the operator controls']


def test_1602_missing_and_trailing_commas_inside_fences():
    raw = '```json\n{"summary": "Character select screen"\n "actors": ["Kasumi" "Ayane",],\n "hud": ["TIME 99",],}\n```'
    result = _so.parse_observation(raw)
    assert result['summary'] == 'Character select screen'
    assert result['actors'] == ['Kasumi', 'Ayane'] and result['hud'] == ['TIME 99']
    assert result['repaired_json'] is True


def test_1602_inner_quote_pair_and_raw_newline():
    raw = '{"summary": "HUD label "P1""\n, "hud": ["line one\nline two", "say "hi", then go"]}'
    result = _so.parse_observation(raw)
    assert result['summary'] == 'HUD label "P1"'
    assert result['hud'] == ['line one line two', 'say "hi", then go']


def test_1602_truncated_reply_keeps_what_arrived():
    raw = '{"summary": "Kasumi and Ayane fight in the snow", "actors": ["Kasumi (player 1)", "Ayane (play'
    result = _so.parse_observation(raw)
    assert result['summary'] == 'Kasumi and Ayane fight in the snow'
    assert result['actors'] == ['Kasumi (player 1)', 'Ayane (play']
    assert result['hud'] == [] and result['repaired_json'] is True
    assert _so.parse_observation('{"summary": "Title screen", "hud"')['hud'] == []
    assert _so.parse_observation('{"summary": "Title screen", "hud":')['hud'] == []
    assert _so.parse_observation('{"summary": "Title screen",')['summary'] == 'Title screen'


def test_1602_valid_replies_are_untouched_and_garbage_still_fails():
    clean = _json.dumps({'summary': 'Versus screen', 'actors': ['Kasumi'], 'changes': [], 'hud': [],
                         'mechanics_hypotheses': [], 'uncertainties': []})
    assert 'repaired_json' not in _so.parse_observation(clean)
    assert 'repaired_json' not in _so.parse_observation('Here you go:\n' + clean + '\nHope this helps')
    assert _so.repair_json(clean) == clean
    with _pytest.raises(ValueError, match='malformed JSON'):
        _so.parse_observation('{"summary": }')
    with _pytest.raises(ValueError, match='no JSON observation'):
        _so.parse_observation('I cannot see the game.')


class _VisionEndpoint:
    """httpx.Client stand-in: records each request body and answers from a script of (status, content)."""

    def __init__(self, script):
        self.script, self.sent = list(script), []

    def __call__(self, *args, **kwargs):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def post(self, url, json):
        self.sent.append(json)
        status, content = self.script.pop(0)
        body = {'choices': [{'message': {'content': content}}]} if status == 200 else {'error': content}
        return _httpx.Response(status, json=body, request=_httpx.Request('POST', url))


_CFG = _NS(agent={'llm_url': 'http://vision.test/v1/', 'vision_model': 'qwen2.5vl:7b'})
_GOOD = _json.dumps({'summary': 'Kasumi blocks', 'actors': ['Kasumi'], 'changes': [], 'hud': ['TIME 42'],
                     'mechanics_hypotheses': [], 'uncertainties': []})


def test_1602_analyze_requests_schema_constrained_json(monkeypatch):
    endpoint = _VisionEndpoint([(200, _GOOD)])
    monkeypatch.setattr(_so, '_UNSTRUCTURED_URLS', set())
    monkeypatch.setattr(_so.httpx, 'Client', endpoint)
    result = _so.analyze(_CFG, b'png', None)
    assert result['summary'] == 'Kasumi blocks' and result['model'] == 'qwen2.5vl:7b'
    (sent,) = endpoint.sent
    assert sent['response_format']['type'] == 'json_schema'
    schema = sent['response_format']['json_schema']['schema']
    assert set(schema['required']) == {'summary', *_so.OBSERVATION_LISTS}
    assert all(schema['properties'][k]['items'] == {'type': 'string'} for k in _so.OBSERVATION_LISTS)


def test_1602_endpoint_without_response_format_falls_back_once(monkeypatch):
    endpoint = _VisionEndpoint([(400, 'unknown field response_format'), (200, _GOOD), (200, _GOOD)])
    monkeypatch.setattr(_so, '_UNSTRUCTURED_URLS', set())
    monkeypatch.setattr(_so.httpx, 'Client', endpoint)
    assert _so.analyze(_CFG, b'png', None)['summary'] == 'Kasumi blocks'
    assert _so.analyze(_CFG, b'png', None)['summary'] == 'Kasumi blocks'
    assert ['response_format' in body for body in endpoint.sent] == [True, False, False]


def test_1602_a_failing_plain_retry_keeps_the_schema(monkeypatch):
    endpoint = _VisionEndpoint([(400, 'image too large'), (400, 'image too large')])
    monkeypatch.setattr(_so, '_UNSTRUCTURED_URLS', set())
    monkeypatch.setattr(_so.httpx, 'Client', endpoint)
    with _pytest.raises(_httpx.HTTPStatusError):
        _so.analyze(_CFG, b'png', None)
    assert _so._UNSTRUCTURED_URLS == set()



# ---------------------------------------------------------------- #1602: stale running code is detected
def _watch_files(tmp_path, clock):
    a, b = tmp_path / 'session_observers.py', tmp_path / 'store.py'
    a.write_text('X = 1\n'); b.write_text('Y = 2\n')
    import os
    for path in (a, b):
        os.utime(path, (clock[0] - 100, clock[0] - 100))
    return a, b


def test_1602_unchanged_code_is_not_stale(tmp_path):
    clock = [1_000_000.0]
    a, b = _watch_files(tmp_path, clock)
    watch = _so.CodeWatch([a, b], clock=lambda: clock[0])
    row = watch.status()
    assert row['code_stale'] is False and row['code'] == row['code_on_disk'] and len(row['code']) == 16
    assert watch.should_restart() is False


def test_1602_changed_code_restarts_only_after_it_settles_and_nothing_is_pending(tmp_path):
    import os
    clock = [1_000_000.0]
    a, b = _watch_files(tmp_path, clock)
    watch = _so.CodeWatch([a, b], clock=lambda: clock[0])
    a.write_text('X = 3\n'); os.utime(a, (clock[0] - 5, clock[0] - 5))   # a sync just wrote it
    assert watch.status()['code_stale'] is True and watch.status()['code_error'] is None
    assert watch.should_restart() is False            # still settling
    clock[0] += 60
    assert watch.should_restart(pending=1) is False   # a frame is being analysed
    assert watch.should_restart(pending=0) is True


def test_1602_changed_code_that_does_not_compile_keeps_the_running_observer(tmp_path):
    clock = [1_000_000.0]
    a, b = _watch_files(tmp_path, clock)
    watch = _so.CodeWatch([a, b], clock=lambda: clock[0])
    b.write_text('def broken(:\n')
    clock[0] += 600
    row = watch.status()
    assert row['code_stale'] is True and row['code_error'].startswith('store.py')
    assert watch.should_restart() is False


def test_1602_watch_covers_the_observer_modules_and_restart_code_is_nonzero():
    names = {p.name for p in _so.code_paths()}
    assert {'session_observers.py', 'background_testing.py', 'store.py'} <= names
    assert all(p.exists() for p in _so.code_paths())
    assert _so.RESTART_EXIT_CODE != 0



def test_1602_main_reports_running_code_and_exits_nonzero_for_restart(tmp_path, monkeypatch):
    import contextlib, sys
    import gbox.config, gbox.hermes_delivery
    store = Store(tmp_path)
    monkeypatch.setattr(sys, 'argv', ['session_observers', '--config', 'x.toml'])
    monkeypatch.setattr(gbox.config, 'load', lambda path: _NS(data_dir=tmp_path, api_port=1, token=lambda: 't'))
    monkeypatch.setattr(gbox.hermes_delivery, 'locked', lambda name: contextlib.nullcontext())
    monkeypatch.setattr(_so, 'Store', lambda path: store)
    monkeypatch.setattr(_so.httpx, 'Client', lambda **kw: contextlib.nullcontext(object()))
    ticks = []

    class FakeObservers:
        def __init__(self, store_, config, api):
            self.pending, self.closed = {}, False
        def tick(self):
            ticks.append(1)
            store.put('setting', 'session_observers_runtime', {'heartbeat': 1.0, 'active': 0})
        def close(self):
            self.closed = True

    class FakeWatch:
        def __init__(self, paths):
            pass
        def status(self):
            return {'code': 'a' * 16, 'code_on_disk': 'b' * 16, 'code_stale': True, 'code_error': None}
        def should_restart(self, pending=0):
            return len(ticks) >= 2

    monkeypatch.setattr(_so, 'SessionObservers', FakeObservers)
    monkeypatch.setattr(_so, 'CodeWatch', FakeWatch)
    monkeypatch.setattr(_so.threading.Event, 'wait', lambda self, timeout=None: False)
    with _pytest.raises(SystemExit) as exit_info:
        _so.main()
    assert exit_info.value.code == _so.RESTART_EXIT_CODE and len(ticks) == 2
    runtime = store.get('setting', 'session_observers_runtime')
    assert runtime['active'] == 0 and runtime['code_stale'] is True and 'restarting' in runtime
