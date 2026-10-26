"""Human takeover revokes only that run, durably, and reset checks exact intent."""
import time
from types import SimpleNamespace

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from gbox import autoplay_resume as A, screensaver as S, server, tools
from gbox.config import Config
from gbox.store import Store
from tests.test_autoplay_resume import control
from tests.test_session_reset import enclosed


@pytest.fixture
def handoff(tmp_path):
    store = Store(tmp_path / 'store')
    app = FastAPI()
    S.install(app, store, None, lambda: 'autoplay', lambda *a, **k: None, lambda: [], None)
    S.TELEMETRY.clear()
    return store, TestClient(app)


def test_handoff_survives_telemetry_expiry_and_store_reopen(handoff):
    store, client = handoff
    control(store, continuous=True)
    assert client.post('/api/autoplay/telemetry/w-live', json={
        'running': False, 'autoplay_taken_over': True, 'source_autoplay_job_id': 'start'}).status_code == 200
    assert S.telemetry_get('w-live', now=time.time() + S.TELEMETRY_TTL + 1) == {}
    reopened = Store(store.dir)
    try:
        assert not A.continuous(reopened, 'w-live')
        assert A.snapshot(reopened, 'w-live', {}) is None
        assert A.snapshot(reopened, 'w-live', {'running': True, 'age_s': 0}) is None
    finally:
        reopened.db.close()


def test_later_start_is_not_revoked_by_stale_handoff(handoff):
    store, client = handoff
    control(store, continuous=True)
    assert A.note_handoff(store, 'w-live', 'start')
    control(store, continuous=True, at=20, ident='second')
    client.post('/api/autoplay/telemetry/w-live', json={
        'running': False, 'autoplay_taken_over': True, 'source_autoplay_job_id': 'start'})
    assert A.continuous(store, 'w-live')
    assert A.snapshot(store, 'w-live', {})['job_id'] == 'second'
    assert not A.note_handoff(store, 'w-other', 'second')
    assert not A.note_handoff(store, 'w-live', '')


def test_handoff_before_start_job_finishes_still_revokes_it(handoff):
    store, _ = handoff
    control(store, state='running', continuous=True)
    assert A.note_handoff(store, 'w-live', 'start')
    control(store, continuous=True)
    assert not A.continuous(store, 'w-live')


def test_worker_final_telemetry_carries_exact_source_and_takeover(monkeypatch):
    threads, packets = [], []
    class Thread:
        def __init__(self, target, **kwargs):
            self.target = target
            threads.append(self)
        def start(self):
            pass
    monkeypatch.setattr(tools.threading, 'Thread', Thread)
    monkeypatch.setattr(tools.time, 'sleep', lambda _: None)
    monkeypatch.setattr(tools, '_ap_headers', lambda ctx: {})
    monkeypatch.setattr(tools.httpx, 'post', lambda *a, **kw: packets.append(kw['json']))
    tools._telemetry({'sid': 'w-live', 'took_over': True}, SimpleNamespace(server='http://test', job_id='start'))
    threads[0].target()
    assert packets == [{'running': False, 'mode': '', 'mission': '', 'title': '', 'stats': {}, 'demo': False,
                        'autoplay_taken_over': True, 'source_autoplay_job_id': 'start'}]


@pytest.fixture
def real_reset(tmp_path, monkeypatch):
    app = server.create_app(Config(data_dir=tmp_path / 'data', cache_dir=tmp_path / 'cache'))
    store = app.state.store
    store.put('worker', 'w', {'id': 'w', 'name': 'fixture', 'os': 'windows', 'last_seen': time.time()})
    store.put('session', 'w-live', {'session_id': 'w-live', 'game_id': 'ts', 'state': 'running', 'adapter': 'dolphin'})
    route = next(r for r in app.routes if getattr(r, 'path', '') == '/api/sessions/{sid}/reset')
    reset = enclosed(route.endpoint, 'reset_job').cell_contents
    # Keep the production permission checks; never execute an emulator/reset task.
    monkeypatch.setattr(server.threading, 'Thread', lambda **kw: SimpleNamespace(start=lambda: None))
    return store, reset


@pytest.mark.parametrize('case', ['allowed', 'ordinary', 'pending', 'stop', 'wrong-session', 'handoff', 'new-start'])
def test_real_reset_job_checks_exact_continuous_permission(real_reset, case):
    store, reset = real_reset
    control(store, continuous=case != 'ordinary', state='running' if case == 'pending' else 'succeeded',
            sid='w-other' if case == 'wrong-session' else 'w-live')
    if case == 'stop':
        control(store, op='stop', state='queued', at=20, ident='stop')
    if case in ('handoff', 'new-start'):
        assert A.note_handoff(store, 'w-live', 'start')
    if case == 'new-start':
        control(store, continuous=True, at=20, ident='second')
    if case in ('allowed', 'new-start'):
        job = reset('w-live', 'restart', 'autoplay')
        assert job.tool == 'session_reset' and job.input['session_id'] == 'w-live'
    else:
        with pytest.raises(HTTPException) as denied:
            reset('w-live', 'restart', 'autoplay')
        assert denied.value.status_code == 409 and 'continuous recovery' in denied.value.detail
        assert not any(j.get('tool') == 'session_reset' for j in store.all('job'))
