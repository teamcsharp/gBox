import asyncio
import json

import httpx
import pytest

from mcp.client import Client
from gbox import mcp_server


@pytest.fixture(autouse=True)
def isolate_machine_preferences(monkeypatch):
    monkeypatch.delenv('GBOX_OPERATOR_WORKER', raising=False)
    monkeypatch.delenv('GBOX_TEST_WORKER', raising=False)


def test_mcp_returns_pending_job_and_deduplicates_a_retry(monkeypatch):
    jobs, posts = [], []
    def handler(req):
        if req.url.path == '/api/registry':
            return httpx.Response(200, json={'tools': []})
        if req.url.path == '/api/jobs' and req.method == 'GET':
            return httpx.Response(200, json=jobs)
        if req.url.path == '/api/workers':
            return httpx.Response(200, json=[{'id': 'remote', 'online': True, 'active_jobs': 0}])
        if req.url.path == '/api/jobs' and req.method == 'POST':
            body = json.loads(req.content); posts.append(body)
            job = body | {'id': 'one-job', 'state': 'running', 'worker_id': 'remote'}
            jobs.append(job)
            return httpx.Response(200, json=job)
        raise AssertionError(str(req.url))
    original = httpx.AsyncClient
    monkeypatch.setattr(httpx, 'AsyncClient', lambda *a, **kw: original(*a, **kw, transport=httpx.MockTransport(handler)))
    monkeypatch.setattr(mcp_server, 'JOB_WAIT_SECONDS', 0)
    async def check():
        async with Client(mcp_server.build('http://fixture', 'fixture')) as client:
            args = {'tool': 'characters', 'input': {'op': 'query_runtime'}, 'require_worker': 'remote'}
            first = await client.call_tool('start_job', args)
            second = await client.call_tool('start_job', args)
            assert not first.is_error and not second.is_error
            assert json.loads(second.content[0].text)['id'] == 'one-job'
            assert json.loads(second.content[0].text)['deduplicated']
    asyncio.run(check())
    assert len(posts) == 1


def test_generic_scan_recovers_routing_and_reuses_server_normalized_pending_job(monkeypatch):
    jobs, posts = [], []
    schema = {'type': 'object', 'properties': {
        'roots': {'default': None}, 'include_steam': {'default': None}}}

    def handler(req):
        if req.url.path == '/api/registry':
            return httpx.Response(200, json={'tools': [{'name': 'scan_library', 'description': 'fixture scan', 'input_schema': schema}]})
        if req.url.path == '/api/workers':
            return httpx.Response(200, json=[{'id': 'target', 'online': True, 'active_jobs': 1}])
        if req.url.path == '/api/jobs' and req.method == 'GET':
            return httpx.Response(200, json=jobs)
        if req.url.path == '/api/jobs' and req.method == 'POST':
            body = json.loads(req.content); posts.append(body)
            job = body | {'id': 'scan-on-target', 'state': 'running', 'worker_id': 'target',
                          'input': {'roots': None, 'include_steam': None} | body['input']}
            jobs.append(job)
            return httpx.Response(200, json=job)
        raise AssertionError(str(req.url))

    original = httpx.AsyncClient
    monkeypatch.setattr(httpx, 'AsyncClient', lambda *a, **kw: original(*a, **kw, transport=httpx.MockTransport(handler)))

    async def check():
        async with Client(mcp_server.build('http://fixture', 'fixture')) as client:
            first = await client.call_tool('start_job', {'tool': 'scan_library',
                'input': {'require_worker': 'target', 'parent_request_id': 'report'}})
            retry = await client.call_tool('start_job', {'tool': 'scan_library', 'input': {},
                'require_worker': 'target', 'parent_request_id': 'report'})
            assert not first.is_error and not retry.is_error
            assert json.loads(retry.content[0].text)['deduplicated'] is True
            different = await client.call_tool('start_job', {'tool': 'scan_library',
                'input': {'include_steam': False}, 'require_worker': 'target', 'parent_request_id': 'report'})
            assert not different.is_error
    asyncio.run(check())
    assert len(posts) == 2
    assert posts[0] == {'tool': 'scan_library', 'input': {}, 'require_worker': 'target',
                        'parent_request_id': 'report', 'agent_use': True}


def test_routing_recovery_preserves_declared_tool_fields_and_rejects_conflicting_envelopes():
    args = {'tool': 'collect_title_assets', 'input': {'parent_request_id': 'original', 'require_worker': 'target'}}
    body = mcp_server._generic_job_body(args, {'type': 'object', 'properties': {'parent_request_id': {}}})
    assert body['input'] == {'parent_request_id': 'original'} and body['require_worker'] == 'target'
    assert args['input']['require_worker'] == 'target'  # caller data stays intact
    with pytest.raises(ValueError, match='Conflicting require_worker'):
        mcp_server._generic_job_body({'tool': 'scan_library', 'input': {'require_worker': 'one'},
                                     'require_worker': 'two'}, {'type': 'object', 'properties': {}})
    # Unknown or union input contracts are never reinterpreted as transport metadata.
    assert mcp_server._generic_job_body(args, {'oneOf': []})['input'] == args['input']


def test_mcp_does_not_dispatch_to_an_offline_worker(monkeypatch):
    def handler(req):
        if req.url.path == '/api/registry': return httpx.Response(200, json={'tools': []})
        if req.url.path == '/api/jobs' and req.method == 'GET': return httpx.Response(200, json=[])
        if req.url.path == '/api/workers': return httpx.Response(200, json=[{'id': 'remote', 'online': False}])
        raise AssertionError('No job should be dispatched: ' + str(req.url))
    original = httpx.AsyncClient
    monkeypatch.setattr(httpx, 'AsyncClient', lambda *a, **kw: original(*a, **kw, transport=httpx.MockTransport(handler)))
    async def check():
        async with Client(mcp_server.build('http://fixture', 'fixture')) as client:
            result = await client.call_tool('start_job', {'tool': 'get_frame', 'input': {}, 'require_worker': 'remote'})
            assert result.is_error and 'worker is unavailable' in result.content[0].text
    asyncio.run(check())


def test_generic_tool_returns_durable_pending_id_without_error(monkeypatch):
    def handler(req):
        if req.url.path == '/api/registry':
            return httpx.Response(200, json={'tools': [{'name': 'characters', 'description': 'fixture', 'input_schema': {'type': 'object', 'properties': {'op': {'type': 'string'}}}}]})
        if req.url.path == '/api/jobs' and req.method == 'GET': return httpx.Response(200, json=[])
        if req.url.path == '/api/jobs' and req.method == 'POST':
            return httpx.Response(200, json={'id': 'durable', 'tool': 'characters', 'state': 'running'})
        raise AssertionError(str(req.url))
    original = httpx.AsyncClient
    monkeypatch.setattr(httpx, 'AsyncClient', lambda *a, **kw: original(*a, **kw, transport=httpx.MockTransport(handler)))
    monkeypatch.setattr(mcp_server, 'JOB_WAIT_SECONDS', 0)
    async def check():
        async with Client(mcp_server.build('http://fixture', 'fixture')) as client:
            result = await client.call_tool('job_characters', {'op': 'query_runtime'})
            body = json.loads(result.content[0].text)
            assert not result.is_error and body['id'] == 'durable'
            assert body['state'] == 'running' and 'get_job' in body['next_action']
    asyncio.run(check())


def test_idle_selection_never_uses_protected_pc_even_when_other_pc_is_offline(monkeypatch):
    monkeypatch.setenv('GBOX_OPERATOR_WORKER', 'My PC')
    def handler(req):
        if req.url.path == '/api/registry': return httpx.Response(200, json={'tools': []})
        if req.url.path == '/api/workers': return httpx.Response(200, json=[
            {'id': 'mine', 'name': 'My PC', 'os': 'windows', 'online': True, 'idle_seconds': 1000, 'tools': ['launch_game']},
            {'id': 'remote', 'name': 'Lab', 'os': 'windows', 'online': False, 'idle_seconds': 1000, 'tools': ['launch_game']}])
        raise AssertionError('Do not launch: ' + str(req.url))
    original = httpx.AsyncClient
    monkeypatch.setattr(httpx, 'AsyncClient', lambda *a, **kw: original(*a, **kw, transport=httpx.MockTransport(handler)))
    async def check():
        async with Client(mcp_server.build('http://fixture', 'fixture')) as client:
            result = await client.call_tool('launch_game', {'game_id': 'test', 'node': 'idle'})
            assert result.is_error and 'protected operator PC' in result.content[0].text
    asyncio.run(check())


def test_explicit_test_pc_choice_takes_precedence_over_recent_input_telemetry(monkeypatch):
    monkeypatch.setenv('GBOX_OPERATOR_WORKER', 'i9-NUC')
    monkeypatch.setenv('GBOX_TEST_WORKER', 'JAYBUILTFINALE')
    def handler(req):
        if req.url.path == '/api/registry': return httpx.Response(200, json={'tools': []})
        if req.url.path == '/api/workers': return httpx.Response(200, json=[
            {'id': 'operator', 'name': 'i9-NUC', 'os': 'windows', 'online': True, 'idle_seconds': 500, 'tools': ['get_frame']},
            {'id': 'test', 'name': 'JAYBUILTFINALE', 'os': 'windows', 'online': True, 'idle_seconds': 0, 'tools': ['get_frame']}])
        raise AssertionError(str(req.url))
    original = httpx.AsyncClient
    monkeypatch.setattr(httpx, 'AsyncClient', lambda *a, **kw: original(*a, **kw, transport=httpx.MockTransport(handler)))
    async def check():
        async with Client(mcp_server.build('http://fixture', 'fixture')) as client:
            result = await client.call_tool('select_idle_worker', {'tool': 'get_frame'})
            assert not result.is_error
            body = json.loads(result.content[0].text)
            assert body['id'] == 'test' and body['selection'] == 'configured test PC'
    asyncio.run(check())
