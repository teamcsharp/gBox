"""Actual swap route with synthetic transport; never starts a game or provider."""
import time

from fastapi import HTTPException
from fastapi.testclient import TestClient
import pytest

from gbox import server
from gbox.config import Config


def enclosed(fn, name):
    return dict(zip(fn.__code__.co_freevars, fn.__closure__))[name]


@pytest.fixture
def swap_route(tmp_path, monkeypatch):
    cfg = Config(data_dir=tmp_path / 'data', cache_dir=tmp_path / 'cache')
    app = server.create_app(cfg)
    store = app.state.store
    store.upsert_catalog([{'game_id': 'g', 'title': 'Game', 'platform': 'dreamcast',
                           'source_paths': [], 'format': 'gdi'}])
    store.put('worker', 'w', {'id': 'w', 'name': 'Test PC', 'os': 'windows', 'last_seen': time.time()})
    store.put('session', 'w-live', {'session_id': 'w-live', 'game_id': 'g', 'state': 'running',
                                   'mod': 'old', 'launch_mod': 'old~preserved'})
    checkpoint = store.put_artifact(b'preserved-operator-checkpoint', 'Original.state31',
                                    'application/octet-stream', {'source': 'synthetic test'}).sha256
    route = next(r for r in app.routes if getattr(r, 'path', '') == '/api/sessions/{sid}/swap')
    swap = enclosed(enclosed(route.endpoint, 'swap_job').cell_contents, 'session_swap').cell_contents
    # Synchronous HTTP execution avoids creating a real dispatch thread; it
    # still exercises the actual body validation/authentication and swap logic.
    enclosed(route.endpoint, 'swap_job').cell_contents = lambda sid, mod, to, actor, keep, **_: swap(sid, mod, to, actor, keep)
    monkeypatch.setattr(server.time, 'sleep', lambda _: None)
    return cfg, app, store, swap, checkpoint


def transport(swap_route, import_output, *, fail_import=False):
    _, _, store, swap, checkpoint = swap_route
    calls = []
    launches = []
    def run(tool, inp, *args, **kwargs):
        calls.append((tool, dict(inp)))
        if tool == 'prepare_mod':
            return {'ready': True, 'mod': 'amy'}
        if tool == 'get_frame':
            return {'mean_luma': 20}
        if tool == 'state_transfer':
            if inp['op'] == 'export':
                return {'result': {'artifact': checkpoint}}
            if fail_import and inp['session_id'] == 'w-new':
                raise HTTPException(409, 'native import transport failed')
            return import_output
        if tool == 'launch_game':
            sid = 'w-new' if not launches else 'w-recovered'
            launches.append(inp['mod'])
            store.put('session', sid, {'session_id': sid, 'game_id': 'g', 'state': 'running', 'mod': inp['mod']})
            return {'session_id': sid}
        if tool == 'session_op':
            return {'ok': True}
        pytest.fail('Unexpected tool: ' + tool)
    enclosed(swap, '_run_job').cell_contents = run
    return calls, launches


def invoke(swap_route, **body):
    cfg, app, _, _, _ = swap_route
    with TestClient(app, headers={'Authorization': 'Bearer ' + cfg.token()}) as client:
        return client.post('/api/sessions/w-live/swap', json={'mod': 'amy', **body})


@pytest.mark.parametrize('details, requested, verified, loaded', [
    ({}, None, None, False),
    ({'load_requested': True}, True, None, False),
    ({'load_requested': True, 'loaded': True}, True, None, False),
    ({'load_requested': True, 'load_verified': False, 'loaded': True}, True, False, False),
    ({'load_requested': True, 'load_verified': True}, True, True, False),
    ({'load_requested': True, 'load_verified': True, 'loaded': False}, True, True, False),
    ({'load_requested': True, 'load_verified': True, 'loaded': True}, True, True, True),
    ({'load_requested': 1, 'load_verified': 1, 'loaded': 1}, None, None, False),
    ({'load_requested': False, 'load_verified': False}, False, False, False),
])
def test_swap_requires_explicit_native_flags_not_transport_success(swap_route, details, requested, verified, loaded):
    _, _, store, _, checkpoint = swap_route
    original = store.artifact_path(checkpoint).read_bytes()
    calls, launches = transport(swap_route, {'result': details})
    response = invoke(swap_route)
    assert response.status_code == 200, response.text
    result = response.json()
    assert result['state_loaded'] is loaded
    assert result['load_requested'] is requested
    assert result['load_verified'] is verified
    assert result['session_id'] == 'w-new' and launches == ['amy']
    assert store.artifact_path(checkpoint).read_bytes() == original
    assert [i['op'] for t, i in calls if t == 'state_transfer'] == ['export', 'import']
    # Unknown/false verification must not start recovery or reset the game.
    assert [(i['session_id'], i['op']) for t, i in calls if t == 'session_op'] == [('w-live', 'stop_game')]
    assert sum(t == 'get_frame' for t, _ in calls) == (3 if loaded else 1)
    assert (not result['notes']) if loaded else any('not confirmed loaded' in n for n in result['notes'])
    audit = next(r['data'] for r in store.audit_log() if r['action'] == 'session.swap')
    assert audit['state_loaded'] is loaded and audit['load_requested'] is requested and audit['load_verified'] is verified


@pytest.mark.parametrize('output', [{}, {'result': None}, {'result': 'unstructured legacy output'}, None])
def test_missing_or_malformed_result_is_unknown_without_recovery(swap_route, output):
    calls, launches = transport(swap_route, output)
    response = invoke(swap_route)
    assert response.status_code == 200
    result = response.json()
    assert result['state_loaded'] is False and result['load_requested'] is None and result['load_verified'] is None
    assert launches == ['amy']
    assert not any(t == 'session_op' and i['session_id'] == 'w-new' for t, i in calls)


def test_no_checkpoint_request_does_not_claim_restore(swap_route):
    calls, launches = transport(swap_route, {'result': {'loaded': True, 'load_verified': True}})
    response = invoke(swap_route, keep_state=False, intent='reset_model')
    assert response.status_code == 200
    result = response.json()
    assert result['state_loaded'] is False and result['load_requested'] is False and result['load_verified'] is None
    assert result['notes'] == [] and launches == ['amy']
    assert not any(t in ('state_transfer', 'get_frame') for t, _ in calls)


def test_transport_failure_keeps_existing_checkpoint_recovery(swap_route):
    _, _, store, _, checkpoint = swap_route
    original = store.artifact_path(checkpoint).read_bytes()
    calls, launches = transport(swap_route, {'result': {'load_requested': True,
                                'load_verified': True, 'loaded': True}}, fail_import=True)
    response = invoke(swap_route)
    assert response.status_code == 409
    assert checkpoint in response.json()['detail']
    assert launches == ['amy', 'old~preserved']
    assert [(i['session_id'], i['artifact']) for t, i in calls if t == 'state_transfer' and i['op'] == 'import'] == [
        ('w-new', checkpoint), ('w-recovered', checkpoint)]
    assert ('session_op', {'session_id': 'w-new', 'op': 'stop_game', 'args': {}}) in calls
    assert store.get('session', 'w-live')['replaced_by'] == 'w-recovered'
    assert store.artifact_path(checkpoint).read_bytes() == original
    assert not any(r['action'] == 'session.swap' for r in store.audit_log())


def test_session_ending_during_prepare_skips_state_save_and_starts_fresh(swap_route):
    """#1755: the session can end while prepare_mod fetches a large mod; the swap must
    start the replacement fresh instead of 409ing about a moment it can no longer save."""
    _, _, store, swap, _ = swap_route
    calls, launches = [], []
    def run(tool, inp, *args, **kwargs):
        calls.append((tool, dict(inp)))
        if tool == 'prepare_mod':
            store.put('session', 'w-live', store.get('session', 'w-live') | {'state': 'ended'})
            return {'ready': True, 'mod': 'amy'}
        if tool == 'launch_game':
            launches.append(inp['mod'])
            store.put('session', 'w-new', {'session_id': 'w-new', 'game_id': 'g', 'state': 'running', 'mod': inp['mod']})
            return {'session_id': 'w-new'}
        pytest.fail('Unexpected tool: ' + tool)
    enclosed(swap, '_run_job').cell_contents = run
    response = invoke(swap_route)
    assert response.status_code == 200, response.text
    result = response.json()
    assert result['session_id'] == 'w-new' and launches == ['amy']
    assert not any(t in ('state_transfer', 'get_frame') for t, _ in calls)
    assert any('already ended' in n for n in result['notes'])


def test_state_save_failing_after_session_ended_starts_fresh_not_409(swap_route):
    """#1755: even if the session ends in the small window between the liveness re-check
    and the export job, the swap degrades to a fresh launch rather than a 409."""
    _, _, store, swap, _ = swap_route
    calls, launches = [], []
    def run(tool, inp, *args, **kwargs):
        calls.append((tool, dict(inp)))
        if tool == 'prepare_mod':
            return {'ready': True, 'mod': 'amy'}
        if tool == 'get_frame':
            return {'mean_luma': 20}
        if tool == 'state_transfer' and inp['op'] == 'export':
            store.put('session', 'w-live', store.get('session', 'w-live') | {'state': 'ended'})
            raise HTTPException(409, 'state_transfer failed: game session ended before the job could run')
        if tool == 'launch_game':
            launches.append(inp['mod'])
            store.put('session', 'w-new', {'session_id': 'w-new', 'game_id': 'g', 'state': 'running', 'mod': inp['mod']})
            return {'session_id': 'w-new'}
        pytest.fail('Unexpected tool: ' + tool)
    enclosed(swap, '_run_job').cell_contents = run
    response = invoke(swap_route)
    assert response.status_code == 200, response.text
    result = response.json()
    assert result['session_id'] == 'w-new' and launches == ['amy']
    assert any('ended before' in n for n in result['notes'])


def linux_rpcs3_swap(swap_route, *, stop_confirmed=True, import_fails=False, launch_fails=False):
    _, _, store, swap, checkpoint = swap_route
    store.put('worker', 'w', store.get('worker', 'w') | {'os': 'linux'})
    store.put('session', 'w-live', store.get('session', 'w-live') | {'adapter': 'rpcs3'})
    calls, launches = [], []

    def run(tool, inp, *args, **kwargs):
        calls.append((tool, dict(inp)))
        if tool == 'prepare_mod':
            return {'ready': True, 'mod': 'amy'}
        if tool == 'get_frame':
            return {'mean_luma': 20}
        if tool == 'state_transfer':
            if inp['op'] in ('export', 'snapshot'):
                return {'result': {'artifact': checkpoint}}
            if import_fails:
                raise HTTPException(409, 'native import failed')
            return {'result': {'loaded': True, 'load_verified': True, 'load_requested': True}}
        if tool == 'session_op':
            assert inp['op'] == 'stop_game'
            confirmed = stop_confirmed if inp['session_id'] == 'w-live' else False
            return {'session_id': inp['session_id'], 'ended': confirmed}
        if tool == 'launch_game':
            assert store.get('session', 'w-live')['state'] == 'ended'
            assert 'keep_session' not in inp
            launches.append(inp['mod'])
            if launch_fails:
                raise HTTPException(409, 'launch_game failed: running')
            store.put('session', 'w-new', {'session_id': 'w-new', 'game_id': 'g', 'state': 'running', 'adapter': 'rpcs3'})
            return {'session_id': 'w-new'}
        pytest.fail('Unexpected tool: ' + tool)
    enclosed(swap, '_run_job').cell_contents = run
    return calls, launches


@pytest.mark.parametrize('keep_state', [False, True])
def test_linux_rpcs3_swap_confirms_stop_after_snapshot_before_launch(swap_route, keep_state):
    calls, launches = linux_rpcs3_swap(swap_route)
    response = invoke(swap_route, keep_state=keep_state, intent='reset_model')
    assert response.status_code == 200, response.text
    operations = [(tool, inp.get('op')) for tool, inp in calls]
    saved = operations.index(('state_transfer', 'export' if keep_state else 'snapshot'))
    stopped = operations.index(('session_op', 'stop_game'))
    launched = operations.index(('launch_game', None))
    assert saved < stopped < launched
    assert operations.count(('session_op', 'stop_game')) == 1
    assert launches == ['amy']
    assert swap_route[2].get('session', 'w-live')['replaced_by'] == 'w-new'


def test_linux_rpcs3_swap_keep_old_cannot_request_overlapping_profile(swap_route):
    calls, launches = linux_rpcs3_swap(swap_route)
    result = swap_route[3]('w-live', 'amy', '', 'operator', False, keep_old=True)
    assert result['session_id'] == 'w-new' and launches == ['amy']
    assert 'keep_session' not in next(inp for tool, inp in calls if tool == 'launch_game')


def test_linux_rpcs3_swap_unconfirmed_old_stop_aborts_without_launch(swap_route):
    calls, launches = linux_rpcs3_swap(swap_route, stop_confirmed=False)
    response = invoke(swap_route, keep_state=False, intent='reset_model')
    assert response.status_code == 409 and 'stop of session w-live was not confirmed' in response.json()['detail']
    assert launches == []
    assert [(inp['session_id'], inp['op']) for tool, inp in calls if tool == 'session_op'] == [('w-live', 'stop_game')]


def test_replaced_linux_rpcs3_sid_cannot_redirect_swap(swap_route):
    calls, launches = linux_rpcs3_swap(swap_route)
    store = swap_route[2]
    store.put('session', 'w-live', store.get('session', 'w-live') | {'state': 'ended', 'replaced_by': 'w-new'})
    store.put('session', 'w-new', {'session_id': 'w-new', 'game_id': 'g', 'state': 'running', 'adapter': 'rpcs3'})
    response = invoke(swap_route, keep_state=False, intent='reset_model')
    assert response.status_code == 409 and 'session was replaced' in response.json()['detail']
    assert calls == [] and launches == [] and store.get('session', 'w-new')['state'] == 'running'


def test_linux_rpcs3_swap_launch_timeout_never_races_recovery(swap_route):
    calls, launches = linux_rpcs3_swap(swap_route, launch_fails=True)
    response = invoke(swap_route, keep_state=False, intent='reset_model')
    assert response.status_code == 409 and 'previous session was stopped' in response.json()['detail']
    assert launches == ['amy']
    assert sum(tool == 'session_op' for tool, _ in calls) == 1


def test_linux_rpcs3_failed_restore_cannot_recover_until_new_stop_confirmed(swap_route):
    calls, launches = linux_rpcs3_swap(swap_route, import_fails=True)
    response = invoke(swap_route)
    assert response.status_code == 409 and 'checkpoint is retained' in response.json()['detail']
    assert launches == ['amy'], 'an unconfirmed replacement stop cannot be followed by another launch'
    assert [(inp['session_id'], inp['op']) for tool, inp in calls if tool == 'session_op'] == [
        ('w-live', 'stop_game'), ('w-new', 'stop_game')]


def test_linux_rpcs3_cross_worker_swap_keeps_source_until_replacement_runs(swap_route):
    _, _, store, swap, _ = swap_route
    store.put('worker', 'w', store.get('worker', 'w') | {'os': 'linux'})
    store.put('worker', 'v', {'id': 'v', 'name': 'Other PC', 'os': 'linux', 'last_seen': time.time()})
    store.put('session', 'w-live', store.get('session', 'w-live') | {'adapter': 'rpcs3'})
    calls, launches = transport(swap_route, {})
    result = swap('w-live', 'amy', 'v', 'operator', False, keep_old=True)
    assert result['session_id'] == 'w-new' and launches == ['amy']
    operations = [(tool, inp.get('op')) for tool, inp in calls]
    assert operations.index(('launch_game', None)) < operations.index(('session_op', 'stop_game'))
    assert not any(tool == 'state_transfer' for tool, _ in calls)
