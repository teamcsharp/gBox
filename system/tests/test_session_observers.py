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
