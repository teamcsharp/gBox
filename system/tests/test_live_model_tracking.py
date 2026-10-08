from fastapi.testclient import TestClient

from gbox.server import create_app


def test_successive_live_models_preserve_the_boot_rom_and_require_a_live_session(cfg):
    app = create_app(cfg)
    client = TestClient(app, headers={'Authorization': f'Bearer {cfg.token()}'})
    app.state.store.put('session', 'test-game', {'session_id': 'test-game', 'state': 'running', 'mod': 'original'})
    for mod in ['big_head', 'edited_head']:
        r = client.post('/api/sessions/test-game/live-model', json={'mod': mod})
        assert r.status_code == 200
        session = next(s for s in client.get('/api/sessions').json() if s['session_id'] == 'test-game')
        assert session['mod'] == 'original'
        assert session['live_mod'] == mod
    assert client.post('/api/sessions/test-game/live-model', json={'mod': '../other'}).status_code == 422
    assert client.post('/api/sessions/missing/live-model', json={'mod': 'head'}).status_code == 404
    app.state.store.put('session', 'test-game', {'session_id': 'test-game', 'state': 'ended'})
    assert client.post('/api/sessions/test-game/live-model', json={'mod': 'head'}).status_code == 409
