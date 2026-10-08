from fastapi.testclient import TestClient
from gbox.server import create_app
from gbox.inbox import organize


def test_automatic_gap_preserves_origin_and_unrelated_tasks_stay_unlinked(cfg):
    app = create_app(cfg)
    client = TestClient(app, headers={"Authorization": f"Bearer {cfg.token()}"})
    def create(**body):
        r = client.post('/api/requests', json=body)
        assert r.status_code == 200, r.text
        return r.json()
    root = create(title='Play as Sonic', body='Play as Sonic', source='gbox-chat')
    child = create(title='Missing swap', source='characters', parent_request_id=root['id'])
    gap = create(title='GAP', source='gap', body='## What the operator asked\nPlay as Sonic\n\n## Context\ngame: test')
    orphan = create(title='Unrelated extraction', source='characters')
    rows = {r['id']: r for r in client.get('/api/requests').json()}
    assert not rows[root['id']]['automated']
    assert rows[child['id']]['parent_request_id'] == root['id']
    assert rows[gap['id']]['parent_request_id'] == root['id']
    assert rows[orphan['id']]['automated'] and rows[orphan['id']]['parent_request_id'] is None
    assert client.post(f"/api/requests/{root['id']}/parent", json={'parent_request_id': child['id']}).status_code == 409
    assert client.post('/api/requests', json={'title': 'Bad parent', 'parent_request_id': 'missing'}).status_code == 404
    assert client.post(f"/api/requests/{orphan['id']}/parent", json={'parent_request_id': root['id']}).status_code == 200


def test_imported_system_reports_are_not_operator_prompts_and_cycles_are_safe():
    rows = organize([
        {'id': 'user', 'body': 'Actual prompt', 'created': 1},
        {'id': 'report', 'body': '<agent-message from="agent">Report', 'created': 2},
        {'id': 'a', 'parent_request_id': 'b'},
        {'id': 'b', 'parent_request_id': 'a'},
    ])
    assert not rows[0]['automated'] and rows[1]['automated']
    assert rows[1]['parent_request_id'] is None
    assert not (rows[2]['parent_request_id'] == 'b' and rows[3]['parent_request_id'] == 'a')


def test_ledger_system_handoff_keeps_the_original_operator_request(monkeypatch):
    from scripts import agent_ledger as ledger
    state, submitted = {}, []
    monkeypatch.setattr(ledger, 'load_state', lambda: state)
    monkeypatch.setattr(ledger, 'save_state', lambda st: None)
    def api(path, body=None):
        if path == '/api/requests':
            submitted.append(body)
            return {'id': str(len(submitted))}
        return []
    monkeypatch.setattr(ledger, 'api', api)
    ledger.hook_prompt({'session_id': 'session', 'prompt': 'Fix the character selector'})
    ledger.hook_prompt({'session_id': 'session', 'prompt': '<agent-message from="worker">Report'})
    assert not submitted[0]['automated']
    assert submitted[1]['automated'] and submitted[1]['parent_request_id'] == '1'
    assert state['session']['operator_request'] == '1'
