import json
import sqlite3
import threading
import time

import pytest
from fastapi.testclient import TestClient

from gbox.config import Config
from gbox.job_routing import main, repair_analysis_os
from gbox.models import Job
from gbox.server import create_app
from gbox.store import Store


@pytest.fixture
def queued(tmp_path):
    store = Store(tmp_path)
    worker = {'id': 'linux-id', 'name': 'Spark', 'os': 'linux', 'last_seen': time.time(),
              'tools': ['analyze_binary'], 'unavailable': {}}
    job = Job(id='queued-id', tool='analyze_binary', input={'binary_path': '/owned/game.elf', 'processor': None},
              require_worker=worker['id'], require_os='windows', parent_request_id='original-request',
              agent_use=True).model_dump()
    store.put('worker', worker['id'], worker)
    store.put('job', job['id'], job)
    store.audit('mcp', 'job.submit', job['id'], {'tool': job['tool']})
    return store, job, worker


def repair(store, **kw):
    return repair_analysis_os(store.db, 'queued-id', expected_worker='linux-id', expected_os='windows', **kw)


def test_dry_run_preserves_job_and_audit(queued):
    store, job, _ = queued
    result = repair(store)
    assert result['applied'] is False and result['audit_seq'] is None
    assert result['after'] == job | {'require_os': 'linux'}
    assert store.get('job', job['id']) == job
    assert store.audit_log_last_seq() == 1


def test_apply_preserves_every_other_field_and_atomic_audit(queued):
    store, job, _ = queued
    result = repair(store, apply=True, target_os='linux')
    assert result['applied'] is True and result['audit_seq'] == 2
    assert store.get('job', job['id']) == job | {'require_os': 'linux'}
    event = store.audit_for(job['id'])[-1]
    assert event['action'] == 'job.analysis_os_corrected'
    assert event['data']['before'] == job and event['data']['after'] == result['after']
    assert store.verify_audit() == (True, 2, None)
    with pytest.raises(ValueError, match='no longer matches'):
        repair(store, apply=True, target_os='linux')
    assert store.audit_log_last_seq() == 2


@pytest.mark.parametrize('change', [
    {'state': 'running'}, {'state': 'failed'}, {'worker_id': 'linux-id'}, {'started': 0},
    {'finished': 0}, {'receipt_id': 'receipt'}, {'output': {}}, {'cancel': True},
    {'tool': 'launch_game'}, {'tool': 'ghidra_script'}, {'tool': 'characters'},
    {'origin': {'inspection_run': 'reserved'}}, {'require_worker': 'different'}, {'require_os': 'linux'},
])
def test_refuses_changed_claimed_finished_or_nonanalysis_job(queued, change):
    store, job, _ = queued
    store.put('job', job['id'], job | change)
    with pytest.raises(ValueError):
        repair(store, apply=True, target_os='linux')
    assert store.get('job', job['id']) == job | change
    assert store.audit_log_last_seq() == 1


@pytest.mark.parametrize('change', [
    {'id': 'different'}, {'os': 'unknown'}, {'os': 'windows'}, {'last_seen': 0},
    {'last_seen': float('nan')}, {'last_seen': True}, {'last_seen': time.time() + 9999}, {'tools': []},
])
def test_refuses_stale_unknown_incapable_or_compatible_worker(queued, change):
    store, job, worker = queued
    store.put('worker', worker['id'], worker | change)
    with pytest.raises(ValueError):
        repair(store, apply=True, target_os='linux')
    assert store.get('job', job['id']) == job
    assert store.audit_log_last_seq() == 1


def test_requires_explicit_correct_target_os(queued):
    store, job, _ = queued
    for target in (None, 'windows'):
        with pytest.raises(ValueError):
            repair(store, apply=True, target_os=target)
    assert store.get('job', job['id']) == job


def test_audit_failure_rolls_back_correction(queued):
    store, job, _ = queued
    store.db.execute("CREATE TRIGGER fixture_audit_failure BEFORE INSERT ON audit BEGIN SELECT RAISE(ABORT, 'fixture'); END")
    store.db.commit()
    with pytest.raises(sqlite3.IntegrityError, match='fixture'):
        repair(store, apply=True, target_os='linux')
    assert store.get('job', job['id']) == job
    assert store.audit_log_last_seq() == 1


def test_worker_claim_wins_before_correction_transaction(queued):
    store, job, _ = queued
    path = store.dir / 'gbox.sqlite3'
    claimed = threading.Event()
    release = threading.Event()

    def claim():
        with sqlite3.connect(path) as db:
            db.execute('BEGIN IMMEDIATE')
            db.execute("UPDATE docs SET body=? WHERE kind='job' AND id=?",
                       (json.dumps(job | {'state': 'running', 'worker_id': 'linux-id', 'started': time.time()}), job['id']))
            claimed.set()
            release.wait(3)

    thread = threading.Thread(target=claim)
    thread.start()
    assert claimed.wait(3)
    release.set()
    with pytest.raises(ValueError, match='unclaimed'):
        repair(store, apply=True, target_os='linux')
    thread.join()
    assert store.get('job', job['id'])['state'] == 'running'
    assert store.audit_log_last_seq() == 1


def test_cli_default_is_readonly_and_does_not_create_missing_db(queued, tmp_path, capsys):
    store, job, _ = queued
    args = ['--database', str(store.dir / 'gbox.sqlite3'), '--job-id', job['id'],
            '--expected-worker', 'linux-id', '--expected-os', 'windows']
    main(args)
    assert json.loads(capsys.readouterr().out)['applied'] is False
    assert store.get('job', job['id']) == job and store.audit_log_last_seq() == 1
    missing = tmp_path / 'missing.db'
    args[1] = str(missing)
    with pytest.raises(sqlite3.OperationalError):
        main(args)
    assert not missing.exists()


def test_separate_store_connections_serialize_audit_predecessors(queued):
    import concurrent.futures
    store, _, _ = queued
    other = Store(store.dir)
    barrier = threading.Barrier(2)

    def append(s):
        barrier.wait(timeout=3)
        for i in range(20):
            s.audit('fixture', 'test.concurrent', str(i), {'connection': id(s)})

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(append, s) for s in (store, other)]
        for future in futures:
            future.result(timeout=10)
    assert store.verify_audit() == (True, 41, None)


@pytest.mark.parametrize('worker_ref', ['linux-id', 'Spark', 'old-id'])
def test_api_rejects_contradictory_constraints_before_queueing(tmp_path, worker_ref):
    cfg = Config(data_dir=tmp_path)
    app = create_app(cfg)
    store = app.state.store
    store.put('worker', 'linux-id', {'id': 'linux-id', 'name': 'Spark', 'os': 'linux',
                                   'tools': ['analyze_binary'], 'last_seen': time.time()})
    store.put('worker_alias', 'old-id', {'to': 'linux-id', 'name': 'Spark'})
    client = TestClient(app, headers={'Authorization': f'Bearer {cfg.token()}'})
    body = {'tool': 'analyze_binary', 'input': {'binary_path': '/owned/game.elf'},
            'require_worker': worker_ref, 'require_os': 'windows'}
    response = client.post('/api/jobs', json=body)
    assert response.status_code == 422 and 'runs linux' in response.text
    assert store.all('job') == []
    response = client.post('/api/jobs', json=body | {'require_os': 'linux'})
    assert response.status_code == 200, response.text
    assert response.json()['require_os'] == 'linux' and response.json()['require_worker'] == 'linux-id'


def test_api_keeps_unpinned_os_constraint_and_rejects_unknown_os(tmp_path):
    cfg = Config(data_dir=tmp_path)
    app = create_app(cfg)
    client = TestClient(app, headers={'Authorization': f'Bearer {cfg.token()}'})
    body = {'tool': 'analyze_binary', 'input': {'binary_path': 'C:/owned/game.elf'}, 'require_os': 'windows'}
    response = client.post('/api/jobs', json=body)
    assert response.status_code == 200 and response.json()['require_os'] == 'windows'
    assert response.json()['require_worker'] is None
    assert client.post('/api/jobs', json=body | {'require_os': 'unrecognized'}).status_code == 422


@pytest.mark.parametrize('tool_name', ['start_job', 'job_analyze_binary'])
def test_mcp_rejects_conflicting_worker_os_even_with_existing_impossible_job(monkeypatch, tool_name):
    import asyncio
    import httpx
    from mcp.client import Client
    from gbox import mcp_server

    def handler(req):
        if req.url.path == '/api/registry':
            return httpx.Response(200, json={'tools': [{'name': 'analyze_binary', 'description': 'test',
                'input_schema': {'type': 'object', 'properties': {'binary_path': {'type': 'string'}}}}]})
        if req.url.path == '/api/workers':
            return httpx.Response(200, json=[{'id': 'linux-id', 'name': 'Spark', 'os': 'linux', 'online': True}])
        raise AssertionError('Reject before dispatch or reuse: ' + str(req.url))

    original = httpx.AsyncClient
    monkeypatch.setattr(httpx, 'AsyncClient', lambda *a, **kw: original(*a, **kw, transport=httpx.MockTransport(handler)))
    async def check():
        async with Client(mcp_server.build('http://fixture', 'fixture')) as client:
            args = {'require_worker': 'linux-id', 'require_os': 'windows'}
            args |= {'tool': 'analyze_binary', 'input': {'binary_path': '/owned/game.elf'}} if tool_name == 'start_job' else {'binary_path': '/owned/game.elf'}
            result = await client.call_tool(tool_name, args)
            assert result.is_error and 'runs linux' in result.content[0].text
    asyncio.run(check())


def test_mcp_retry_identity_keeps_explicit_os_constraint(monkeypatch):
    import asyncio
    import httpx
    from mcp.client import Client
    from gbox import mcp_server

    posts = []
    def handler(req):
        if req.url.path == '/api/registry':
            return httpx.Response(200, json={'tools': []})
        if req.url.path == '/api/jobs' and req.method == 'GET':
            return httpx.Response(200, json=[{'id': 'windows-job', 'tool': 'analyze_binary', 'state': 'queued',
                'input': {'binary_path': 'shared.elf'}, 'require_os': 'windows'}])
        if req.url.path == '/api/jobs' and req.method == 'POST':
            posts.append(json.loads(req.content))
            return httpx.Response(200, json=posts[-1] | {'id': 'linux-job', 'state': 'queued'})
        raise AssertionError(str(req.url))

    original = httpx.AsyncClient
    monkeypatch.setattr(httpx, 'AsyncClient', lambda *a, **kw: original(*a, **kw, transport=httpx.MockTransport(handler)))
    async def check():
        async with Client(mcp_server.build('http://fixture', 'fixture')) as client:
            result = await client.call_tool('start_job', {'tool': 'analyze_binary', 'input': {'binary_path': 'shared.elf'}, 'require_os': 'linux'})
            assert not result.is_error
            assert json.loads(result.content[0].text)['id'] == 'linux-job'
    asyncio.run(check())
    assert len(posts) == 1 and posts[0]['require_os'] == 'linux'


def test_requester_worker_pins_the_pc_a_play_came_from():
    from gbox.job_routing import requester_worker
    nuc = {'id': 'nuc', 'name': 'i9-NUC', 'os': 'windows', 'online': True, 'tools': ['launch_game'], 'address': '10.89.1.43'}
    jay = {'id': 'jay', 'name': 'JAYBUILTFINALE', 'os': 'windows', 'online': True, 'tools': ['launch_game'], 'address': '10.89.1.13'}
    spark = {'id': 'spark', 'name': 'lilspark', 'os': 'linux', 'online': True, 'tools': ['launch_game'], 'address': '127.0.0.1'}
    workers = [jay, nuc, spark]
    assert requester_worker(workers, '10.89.1.43') is nuc
    assert requester_worker(workers, '10.89.1.43', 'windows') is nuc
    assert requester_worker(workers, '10.89.1.43', 'linux') is None          # the PS2 rule wants Windows: no pin elsewhere
    assert requester_worker(workers, '127.0.0.1') is spark
    assert requester_worker(workers, '10.89.1.99') is None                   # a phone browser: the old placement applies
    assert requester_worker(workers, None) is None
    assert requester_worker([dict(nuc, online=False)], '10.89.1.43') is None
    assert requester_worker([dict(nuc, tools=['get_frame'])], '10.89.1.43') is None
