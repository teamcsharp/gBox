from fastapi.testclient import TestClient

from gbox.server import create_app


def test_inbox_mutations_return_utf8_safe_history(cfg):
    app = create_app(cfg)
    client = TestClient(app, headers={"Authorization": f"Bearer {cfg.token()}"})
    created = client.post('/api/requests', json={"title": "Clipboard", "body": "Original"})
    assert created.status_code == 200
    rid = created.json()['id']
    stored = app.state.store.get('request', rid)
    stored['body'] = 'Old imported text\udc9d'
    app.state.store.put('request', rid, stored)
    for endpoint, payload in [
        ('status', {'status': 'done', 'note': 'Verified'}),
        ('messages', {'author': 'agent', 'text': 'Evidence'}),
        ('metrics', {'turns': 1}),
    ]:
        response = client.post(f'/api/requests/{rid}/{endpoint}', json=payload)
        assert response.status_code == 200
        assert response.json()['body'] == 'Old imported text?'
    assert client.get(f'/api/requests/{rid}').json()['status'] == 'done'
    # Sanitizing a response must preserve the imported source record.
    assert app.state.store.get('request', rid)['body'] == 'Old imported text\udc9d'
