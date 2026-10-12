from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from gbox import tools
from gbox.config import Config
from gbox.server import create_app


@pytest.mark.parametrize('alive', [True, False])
def test_native_stop_must_confirm_process_exit(monkeypatch, tmp_path, alive):
    adapter = SimpleNamespace(stop_game=lambda: {}, proc=SimpleNamespace(poll=lambda: None if alive else 0))
    monkeypatch.setitem(tools.SESSIONS, 'worker-game', (adapter, {}))
    monkeypatch.setattr(tools, 'track_emulator', lambda *args, **kwargs: None)
    ctx = SimpleNamespace(config=Config(data_dir=tmp_path))
    inp = tools.SessionIn(session_id='worker-game', op='stop_game')
    if alive:
        with pytest.raises(RuntimeError, match='still running'):
            tools.session_op(inp, ctx)
        assert 'worker-game' in tools.SESSIONS
    else:
        assert tools.session_op(inp, ctx)['ended'] is True
        assert 'worker-game' not in tools.SESSIONS


def test_premature_ended_event_does_not_retire_cleanup_job(tmp_path):
    cfg = Config(data_dir=tmp_path)
    app = create_app(cfg)
    app.state.store.put('session', 'w-s', {'session_id': 'w-s', 'state': 'ended'})
    with TestClient(app, headers={'Authorization': 'Bearer ' + cfg.token()}) as client:
        job = client.post('/api/jobs', json={'tool':'session_op', 'input':{'session_id':'w-s','op':'stop_game'}}).json()
        client.get('/api/jobs')
        result = client.get('/api/jobs/' + job['id']).json()
        assert result['state'] == 'queued'
