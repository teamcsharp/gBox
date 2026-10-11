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
    enclosed(route.endpoint, 'swap_job').cell_contents = lambda sid, mod, to, actor, keep: swap(sid, mod, to, actor, keep)
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
    response = invoke(swap_route, keep_state=False)
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
