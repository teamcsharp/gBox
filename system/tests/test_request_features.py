from fastapi.testclient import TestClient

from gbox.server import create_app


def test_delivery_history_includes_subtasks_mods_legacy_and_reopen(cfg):
    client = TestClient(create_app(cfg), headers={"Authorization": "Bearer " + cfg.token()})
    root = client.post('/api/requests', json={"title": "PSO performance"}).json()
    child = client.post('/api/requests', json={"title": "FPS control", "automated": True,
        "parent_request_id": root['id']}).json()
    delivery = {"added": ["FPS display"], "accomplished": ["Exposed emulator output rate"],
                "test_steps": ["Enable Show emulator FPS, save and restart"],
                "where": ["Sessions > Graphics & performance settings"],
                "mods": [], "verification": "Config generation tested; live FPS unverified"}
    response = client.post('/api/requests/' + child['id'] + '/status',
        json={"status": "done", "note": "FPS option added", "delivery": delivery})
    assert response.status_code == 200, response.text
    assert client.get('/api/requests/' + child['id']).json()['delivery'] == delivery
    client.post('/api/requests/' + root['id'] + '/status', json={"status": "done", "note": "Legacy note"})
    mod = client.post('/api/mods', json={"title": "PSO test mod", "game_id": "pso", "calls": [],
                                       "requests": [child['number']], "verified": False}).json()
    history = client.get('/api/requests/features').json()
    assert history['total'] == 2
    rows = {r['id']: r for r in history['items']}
    assert rows[child['id']]['linked_mods'][0]['id'] == mod['id']
    assert rows[child['id']]['automated'] and rows[child['id']]['documented']
    assert rows[root['id']]['completion_note'] == 'Legacy note'
    assert not rows[root['id']]['documented']
    assert client.get('/api/requests/features?q=emulator%20output').json()['matched'] == 1
    assert len(client.get('/api/requests/features?limit=1').json()['items']) == 1
    assert client.get('/api/requests/features?offset=2').json()['items'] == []
    client.post('/api/requests/' + child['id'] + '/status', json={"status": "in_progress"})
    assert client.get('/api/requests/features').json()['total'] == 1
    # Historical tasks can be documented without manufacturing another completion.
    updated = client.put('/api/requests/' + root['id'] + '/delivery', json=delivery)
    assert updated.status_code == 200
    assert client.get('/api/requests/features').json()['items'][0]['documented']
    assert client.get('/api/requests/features', headers={'Authorization': 'Bearer wrong'}).status_code == 401


def test_invalid_delivery_is_rejected(cfg):
    client = TestClient(create_app(cfg), headers={"Authorization": "Bearer " + cfg.token()})
    task = client.post('/api/requests', json={"title": "Task"}).json()
    result = client.post('/api/requests/' + task['id'] + '/status',
                         json={"status": "done", "delivery": {"test_steps": "not a list"}})
    assert result.status_code == 422
    assert client.get('/api/requests/' + task['id']).json()['status'] == 'open'
