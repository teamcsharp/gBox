import asyncio
import json

import httpx

from mcp.client import Client
from gbox import mcp_server


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
