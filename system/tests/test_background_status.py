import time

import pytest
from fastapi.testclient import TestClient

from gbox.server import create_app
from test_background_resources import worker, measured


@pytest.fixture(autouse=True)
def isolated_coordinator(monkeypatch):
    monkeypatch.setattr('gbox.hermes_tasks.list_runs', lambda **kw: [])


def setup(cfg):
    app = create_app(cfg)
    store = app.state.store
    store.put('worker', 'nuc', worker() | {'last_seen': time.time(), 'tools': ['scan_library']})
    client = TestClient(app, headers={'Authorization': f'Bearer {cfg.token()}'})
    return client, store


def test_controller_owned_game_blocks_compute_despite_long_keyboard_idle(cfg):
    c, s = setup(cfg)
    sid = 'nuc-human'
    s.put('session', sid, {'session_id': sid, 'title': 'Human game', 'state': 'running'})
    # Explicit ownership takes precedence over a formerly automated launch.
    s.put('job', 'human', {'agent_use': True})
    s.put('slabel', sid, {'owner': 'you'})
    job = c.post('/api/jobs', json={'tool': 'scan_library', 'input': {}, 'agent_use': True}).json()
    assert c.post('/api/workers/nuc/claim', json={'idle_seconds': 900}).status_code == 204
    status = c.get('/api/background/workers/i9-NUC/status').json()
    assert status['mode'] == 'operator' and not status['admission']['allowed']
    assert 'Human gameplay' in status['admission']['reason']
    assert s.get('job', job['id'])['state'] == 'queued'
    assert not c.get('/api/workers').json()[0]['admission']['allowed']
    s.put('session', sid, s.get('session', sid) | {'state': 'ended'})
    assert c.post('/api/workers/nuc/claim', json={'idle_seconds': 900}).json()['id'] == job['id']


def test_status_is_read_only_bounded_and_keeps_tool_success_distinct_from_goal(cfg):
    c, s = setup(cfg)
    for n in range(230):
        s.put('session', str(n), {'session_id': str(n), 'state': 'ended', 'detail': {'bulk': 'x'*1000}})
        s.put('job', str(n), {'id': str(n), 'tool': 'scan_library', 'state': 'succeeded',
                            'worker_id': 'nuc', 'output': {'bulk': 'x'*1000}, 'receipt_id': 'receipt-'+str(n)})
    s.put('session', 'nuc-agent', {'session_id': 'nuc-agent', 'state': 'running', 'title': 'Test game',
                                 'detail': {'local_window': True}})
    s.put('slabel', 'nuc-agent', {'owner': 'agent'})
    before = s.digest('job'), s.digest('session')
    response = c.get('/api/background/workers/nuc/status')
    assert response.status_code == 200
    status = response.json()
    assert status['mode'] == 'testing' and status['admission']['allowed']
    assert status['sessions'] == [{'session_id': 'nuc-agent', 'state': 'running', 'title': 'Test game',
                                   'mod': None, 'local_window': True, 'agent_owned': True,
                                   'presentation': None, 'gameplay_state': None}]
    assert len(status['recent_results']) == 10
    assert status['recent_results'][0]['id'] == '229'
    assert 'output' not in status['recent_results'][0] and 'goal_verified' not in status
    assert before == (s.digest('job'), s.digest('session'))
    plan = s.db.execute("EXPLAIN QUERY PLAN SELECT body FROM docs INDEXED BY docs_session_state "
                        "WHERE kind='session' AND json_extract(body,'$.state')='running'").fetchall()
    assert any('SEARCH' in str(row) and 'docs_session_state' in str(row) for row in plan)


def test_native_session_health_reports_exit_offline_and_observer_independently(cfg):
    c, s = setup(cfg)
    sid = 'nuc-agent'
    s.put('session', sid, {'session_id': sid, 'state': 'running', 'detail': {'local_window': True}})
    s.put('session_observer', sid, {'gameplay_state': 'covered'})
    health = c.get(f'/api/sessions/{sid}/stream/health').json()
    assert health['state'] == 'running' and health['age_s'] is None
    assert health['local_window'] and health['worker_online'] and health['gameplay_state'] == 'covered'
    s.put('worker', 'nuc', worker(measured()) | {'last_seen': 0, 'tools': []})
    health = c.get(f'/api/sessions/{sid}/stream/health').json()
    assert not health['worker_online'] and health['state'] == 'running'
    s.put('session', sid, s.get('session', sid) | {'state': 'ended', 'exit': {'returncode': 1}})
    health = c.get(f'/api/sessions/{sid}/stream/health').json()
    assert health['state'] == 'ended' and health['exit'] == {'returncode': 1}


def test_resource_budget_is_available_to_evidence_node_selection(cfg):
    from gbox.evidence_capture import pick_node, EvidenceError
    import pytest
    c, s = setup(cfg)
    s.put('worker', 'nuc', worker(measured(cpu=85)) | {'last_seen': time.time(), 'tools': ['scan_library']})
    with pytest.raises(EvidenceError, match='CPU is at 85%'):
        pick_node('i9-NUC', c.get('/api/workers').json(), [], needs={'scan_library'})


def test_coordinator_is_cached_separately_from_worker_jobs_and_contains_no_transcript(cfg, monkeypatch):
    calls = []
    def runs(**kw):
        calls.append(kw)
        return [{'id': 'run', 'name': 'Game analysis', 'state': 'running', 'progress': 'Inspecting native data',
                 'output': 'private transcript excluded', 'session_id': 'conversation'}]
    monkeypatch.setattr('gbox.hermes_tasks.list_runs', runs)
    c, s = setup(cfg)
    for _ in range(2):
        data = c.get('/api/background/workers/nuc/status').json()
        assert data['active'] == [] and data['coordinator']['host'] == 'control plane'
        assert data['coordinator']['runs'][0]['id'] == 'run'
        assert 'output' not in data['coordinator']['runs'][0]
    assert calls == [{'limit': 3}]
    assert not s.all('job')
