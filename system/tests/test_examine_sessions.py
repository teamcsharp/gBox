from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from gbox import scene_capture as scene
from gbox.config import Config
from gbox.registry import Unsupported
from gbox.server import create_app


class Adapter:
    def __init__(self, paused=False, exited=False):
        self.proc = SimpleNamespace(poll=lambda: 0 if exited else None, pid=123)
        self.paused = paused
        self.resumes = 0
        self.addr = ('localhost', 123)
        self.cmd = lambda *args, **kwargs: None

    def query_runtime(self):
        return {'state': 'PAUSED' if self.paused else 'PLAYING'}

    def pause(self):
        self.paused = True

    def resume(self):
        self.paused = False
        self.resumes += 1


@pytest.mark.parametrize('paused', [False, True])
def test_failed_capture_restores_original_pause_state(monkeypatch, tmp_path, paused):
    ad = Adapter(paused)
    monkeypatch.setattr(scene, 'hooked', lambda proc: True)
    def failed(*args, **kwargs):
        assert ad.paused
        raise RuntimeError('GPU capture failed')
    monkeypatch.setattr(scene, 'capture_rdc', failed)
    with pytest.raises(RuntimeError, match='GPU capture failed'):
        scene.capture_session(ad, tmp_path)
    assert ad.paused == paused
    assert ad.resumes == (0 if paused else 1)


@pytest.mark.parametrize('paused', [False, True])
def test_successful_capture_records_pause_ownership(monkeypatch, tmp_path, paused):
    ad = Adapter(paused)
    def captured(*args, **kwargs):
        ad.pause()
        return {'draws_exported': 2}
    monkeypatch.setattr(scene, '_capture_session', captured)
    assert scene.capture_session(ad, tmp_path)['resume_on_leave'] == (not paused)
    assert ad.paused


def test_stopped_process_cannot_be_captured(tmp_path):
    with pytest.raises(Unsupported, match='emulator has stopped'):
        scene.capture_session(Adapter(exited=True), tmp_path)


def test_missing_worker_session_has_actionable_error(tmp_path):
    with pytest.raises(Unsupported, match='no longer available'):
        scene.scene_capture(scene.SceneIn(session_id='missing-test-session'), SimpleNamespace())


def test_scene_publication_failure_resumes_game(monkeypatch, tmp_path):
    from gbox.tools import SESSIONS
    ad = Adapter(paused=True)
    monkeypatch.setitem(SESSIONS, 'worker-live', (ad, {'game_id': 'mario'}))
    monkeypatch.setattr(scene, 'capture_session', lambda *args: {
        'draws_exported': 1, 'textures': 1, 'resume_on_leave': True})
    def failed(*args):
        raise RuntimeError('publication failed')
    ctx = SimpleNamespace(config=SimpleNamespace(runtime=tmp_path), progress=failed)
    with pytest.raises(RuntimeError, match='publication failed'):
        scene.scene_capture(scene.SceneIn(session_id='worker-live'), ctx)
    assert not ad.paused


@pytest.mark.parametrize('state', [None, 'ended'])
def test_server_rejects_expired_capture_without_queueing(tmp_path, state):
    cfg = Config(data_dir=tmp_path)
    app = create_app(cfg)
    if state:
        app.state.store.put('session', 'worker-expired', {'session_id': 'worker-expired', 'state': state})
    with TestClient(app, headers={'Authorization': 'Bearer ' + cfg.token()}) as client:
        response = client.post('/api/jobs', json={'tool': 'scene_capture', 'input': {'session_id': 'worker-expired'}})
        assert response.status_code == 409
        assert 'Open the running game' in response.json()['detail']
    assert not app.state.store.all('job')
