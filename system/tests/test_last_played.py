"""Last played (gbox/last_played.py + /api/last_played*): after the operator's game ends, offer to reload it, and to
reload it with the moment saved just before the end. Synthetic store and transport: no game is started or stopped."""
import time
from types import SimpleNamespace

from fastapi import HTTPException
from fastapi.testclient import TestClient
import pytest

from gbox import last_played as LP, server, tools
from gbox.config import Config


def enclosed(fn, name):
    return dict(zip(fn.__code__.co_freevars, fn.__closure__))[name]


@pytest.fixture
def app(tmp_path, monkeypatch):
    cfg = Config(data_dir=tmp_path / 'data', cache_dir=tmp_path / 'cache')
    a = server.create_app(cfg)
    store = a.state.store
    store.upsert_catalog([{'game_id': 'ts', 'title': 'MGS: The Twin Snakes', 'platform': 'gamecube', 'source_paths': [],
                           'format': 'iso'}, {'game_id': 'pso', 'title': 'PSO', 'platform': 'dreamcast', 'source_paths': [],
                                              'format': 'gdi'}])
    store.put('worker', 'w', {'id': 'w', 'name': 'JAYBUILTFINALE', 'os': 'windows', 'last_seen': time.time()})
    monkeypatch.setattr(server.time, 'sleep', lambda _: None)
    client = TestClient(a, headers={'Authorization': 'Bearer ' + cfg.token()})
    return SimpleNamespace(app=a, store=store, client=client)


def session(store, sid, **kw):
    doc = {'session_id': sid, 'game_id': 'ts', 'title': 'MGS: The Twin Snakes', 'state': 'ended', 'started': 100, 'ended': 200,
           'mod': 'tts_sonic_full_cast', 'collection_mod': 'tts_sonic_full_cast', 'adapter': 'dolphin',
           'detail': {'worker_name': 'JAYBUILTFINALE'}} | kw
    store.put('session', sid, doc)
    return doc


def get(app):
    r = app.client.get('/api/last_played')
    assert r.status_code == 200, r.text
    return r.json()['entry']


def test_a_stopped_game_offers_reload_and_its_last_moment(app):
    st = app.store
    art = st.put_artifact(b'DOLPHIN-STATE', 'GGSEA4.s01', 'application/octet-stream', {'session': 'w-a'}).sha256
    pic = st.put_artifact(b'\x89PNG fake', 'moment.png', 'image/png', {'session': 'w-a'}).sha256
    session(st, 'w-a', exit={'returncode': 1, 'timings': {'kill_s': 0.4}, 'moment': {'artifact': art, 'frame': pic}},
            checkpoint=art, moment_frame=pic, moment_ts=199)
    e = get(app)
    assert (e['session_id'], e['title'], e['mod'], e['node'], e['node_online']) == ('w-a', 'MGS: The Twin Snakes', 'tts_sonic_full_cast', 'JAYBUILTFINALE', True)
    assert e['reason'] == {'kind': 'stopped', 'crash': False, 'text': 'You stopped it.'}
    assert e['moment']['artifact'] == art and e['moment']['frame_url'] == f'/api/artifacts/{pic}' and e['moment']['ts'] == 199


@pytest.mark.parametrize('extra,kind,crash', [
    ({'exit': {'returncode': 3221225477}}, 'crash', True),
    ({'exit': {'returncode': 0}}, 'closed', False),
    ({'exit': 'worker restarted'}, 'worker_restarted', False),
    ({'exit': {'via': 'relaunch_failed', 'error': 'launch_game failed: Dolphin exited 1'}}, 'relaunch_failed', True),
    ({'exit': {'via': 'single_game', 'to': 'w-other'}}, 'single_game', False),
])
def test_every_way_a_game_ends_is_named(app, extra, kind, crash):
    session(app.store, 'w-a', **extra)
    e = get(app)
    assert e['reason']['kind'] == kind and e['reason']['crash'] is crash
    if kind == 'relaunch_failed':
        assert 'Dolphin exited 1' in e['reason']['text']


def test_a_running_game_is_never_interrupted_and_a_continued_one_is_not_offered(app):
    st = app.store
    session(st, 'w-a', state='running', ended=None)
    assert get(app) is None
    session(st, 'w-a', replaced_by='w-b', exit={'via': 'relaunch', 'to': 'w-b'})
    session(st, 'w-b', state='running', started=300, ended=None)
    assert get(app) is None                                     # reset / swap went on in a new copy


def test_a_game_whose_pc_went_away_counts_as_ended(app):
    st = app.store
    st.put('worker', 'w', {'id': 'w', 'name': 'JAYBUILTFINALE', 'os': 'windows', 'last_seen': time.time() - 3600})
    session(st, 'w-a', state='running', ended=None)
    e = get(app)
    assert e['reason']['kind'] == 'offline' and e['node_online'] is False


def test_agent_test_sessions_do_not_count(app):
    st = app.store
    session(st, 'w-op', exit={'timings': {}})
    session(st, 'w-agent', started=500, game_id='pso', title='PSO', exit={'timings': {}})
    st.put('slabel', 'w-agent', {'session_id': 'w-agent', 'owner': 'agent', 'label': 'test'})
    assert get(app)['session_id'] == 'w-op'
    session(st, 'w-cap', started=600, state='running', detail={'capture_session': {'capture_for': 'w-op'}})
    assert get(app)['session_id'] == 'w-op'                     # an Examine 3D capture session is not the operator's game


def test_the_moment_falls_back_to_the_newest_state_uploaded_for_the_session(app):
    st = app.store
    st.put_artifact(b'old', 'GGSEA4.s01', 'application/octet-stream', {'session': 'w-a', 'note': 'state transfer'})
    new = st.put_artifact(b'newer', 'GGSEA4.s01', 'application/octet-stream', {'session': 'w-a', 'note': 'state transfer'}).sha256
    session(st, 'w-a', exit={'returncode': 0})
    assert get(app)['moment']['artifact'] == new
    session(st, 'w-a', exit={'returncode': 0}, session_id='w-a')
    st.put('session', 'w-z', {'session_id': 'w-z', 'game_id': 'pso', 'title': 'PSO', 'state': 'ended', 'started': 900})
    assert get(app)['moment'] is None                           # the newest game has no saved moment: Reload only


def test_dismiss_and_dont_ask_again_for_this_game(app):
    st = app.store
    session(st, 'w-a')
    assert app.client.post('/api/last_played/dismiss', json={'session_id': 'w-a'}).status_code == 200
    assert get(app) is None
    session(st, 'w-b', started=300)
    assert get(app)['session_id'] == 'w-b'                      # a new end asks again
    app.client.post('/api/last_played/dismiss', json={'session_id': 'w-b', 'never_for_game': True})
    session(st, 'w-c', started=400)
    assert get(app) is None and st.get(LP.MUTE_KIND, 'ts')


def reload_fn(app):
    route = next(r for r in app.app.routes if getattr(r, 'path', '') == '/api/last_played/reload')
    return enclosed(route.endpoint, 'session_reload').cell_contents


def transport(app, fn, import_result=None):
    calls = []

    def run(tool, inp, *a, **k):
        calls.append((tool, dict(inp), k.get('worker')))
        if tool == 'launch_game':
            app.store.put('session', 'w-new', {'session_id': 'w-new', 'game_id': 'ts', 'state': 'running', 'started': 999})
            return {'session_id': 'w-new'}
        if tool == 'state_transfer':
            return {'result': import_result or {'loaded': True, 'load_verified': True}}
        pytest.fail(tool)
    enclosed(fn, '_run_job').cell_contents = run
    return calls


def test_reload_with_the_last_moment_launches_the_same_build_on_the_same_pc_then_loads_it(app):
    st = app.store
    art = st.put_artifact(b'DOLPHIN-STATE', 'GGSEA4.s01', 'application/octet-stream', {'session': 'w-a'}).sha256
    session(st, 'w-a', checkpoint=art, mod='tts_sonic_full_cast~9a1b')
    fn = reload_fn(app)
    calls = transport(app, fn)
    out = fn('w-a', 'operator', True)
    assert [c[0] for c in calls] == ['launch_game', 'state_transfer']
    assert calls[0][1]['mod'] == 'tts_sonic_full_cast' and calls[0][2] == 'w'
    assert calls[1][1] == {'session_id': 'w-new', 'op': 'import', 'artifact': art}
    assert out['session_id'] == 'w-new' and out['moment_loaded'] is True
    assert st.get(LP.DISMISS_KIND, 'w-a')['reloaded'] == 'w-new'
    calls.clear()
    st.put('session', 'w-new', st.get('session', 'w-new') | {'state': 'ended'})
    fn('w-a', 'operator', False)                               # plain Reload: from boot, no state
    assert [c[0] for c in calls] == ['launch_game']


def test_reload_never_stops_a_game_running_on_that_pc(app):
    st = app.store
    session(st, 'w-a')
    session(st, 'w-other', game_id='pso', title='PSO', state='running', started=300, ended=None)
    fn = reload_fn(app)
    calls = transport(app, fn)
    with pytest.raises(HTTPException) as e:
        fn('w-a', 'operator', False)
    assert e.value.status_code == 409 and 'PSO is running on JAYBUILTFINALE; it was not stopped' in e.value.detail
    assert calls == []
    st.put('worker', 'w', {'id': 'w', 'name': 'JAYBUILTFINALE', 'os': 'windows', 'last_seen': time.time() - 3600})
    with pytest.raises(HTTPException, match='offline'):
        fn('w-a', 'operator', False)


def test_reload_endpoint_runs_as_an_in_server_job(app):
    from gbox.job_maintenance import SERVER_TOOLS
    assert 'session_reload' in SERVER_TOOLS
    session(app.store, 'w-a')
    transport(app, reload_fn(app))
    j = app.client.post('/api/last_played/reload', json={'session_id': 'w-a'}).json()
    for _ in range(100):
        j = app.client.get(f"/api/jobs/{j['id']}").json()
        if j['state'] not in ('queued', 'running'):
            break
        time.sleep(0.02)
    assert j['state'] == 'succeeded' and j['output']['session_id'] == 'w-new'


def test_stop_with_moment_uploads_it_and_the_session_keeps_it(monkeypatch):
    stopped = []
    ad = SimpleNamespace(name='dolphin', proc=None, get_frame=lambda: b'\x89PNGframe', stop_game=lambda: stopped.append(1) or {'returncode': 1})
    monkeypatch.setitem(tools.SESSIONS, 'w-stop', (ad, {'game_id': 'ts'}))
    monkeypatch.setattr(tools, 'state_transfer', lambda inp, ctx: {'result': {'artifact': 'a' * 64}})
    monkeypatch.setattr(tools, 'track_emulator', lambda *a, **k: None)
    arts = []
    ctx = SimpleNamespace(config=None, artifact=lambda *a, **k: arts.append((a, k)))
    out = tools._stop_session('w-stop', {'moment': True}, ctx)
    moment = out['result']['moment']
    assert moment['artifact'] == 'a' * 64 and moment['frame'] and stopped == [1]
    assert arts[0][0][0] == 'moment.png' and arts[0][1]['session'] == 'w-stop'
    store = {'w-stop': {'session_id': 'w-stop', 'state': 'running'}}
    fake = SimpleNamespace(get=lambda k, sid: store.get(sid), put=lambda k, sid, doc: store.__setitem__(sid, doc))
    tools._session_accept(fake, tools.SessionOut(**out), 'operator')
    assert store['w-stop']['state'] == 'ended' and store['w-stop']['checkpoint'] == 'a' * 64
    assert store['w-stop']['moment_frame'] == moment['frame']


def test_a_slow_moment_never_holds_the_stop(monkeypatch):
    ad = SimpleNamespace(name='dolphin', proc=None, get_frame=lambda: b'', stop_game=lambda: {'returncode': 0})
    monkeypatch.setitem(tools.SESSIONS, 'w-slow', (ad, {'game_id': 'ts'}))
    monkeypatch.setattr(tools, 'state_transfer', lambda inp, ctx: time.sleep(5))
    monkeypatch.setattr(tools, 'track_emulator', lambda *a, **k: None)
    t0 = time.monotonic()
    out = tools._stop_session('w-slow', {'moment': True, 'moment_cap_s': 0.2}, SimpleNamespace(config=None, artifact=lambda *a, **k: None))
    assert time.monotonic() - t0 < 2 and out['result']['moment']['skipped'] is True and out['ended'] is True


def test_the_app_quit_moment_endpoint_keeps_a_checkpoint(app):
    session(app.store, 'w-a', state='running', ended=None)
    route = next(r for r in app.app.routes if getattr(r, 'path', '') == '/api/sessions/{sid}/moment')
    enclosed(route.endpoint, '_run_job').cell_contents = lambda tool, inp, *a, **k: {'result': {'artifact': 'b' * 64}}
    r = app.client.post('/api/sessions/w-a/moment?wait=3').json()
    assert r == {'saved': True, 'artifact': 'b' * 64} and app.store.get('session', 'w-a')['checkpoint'] == 'b' * 64
