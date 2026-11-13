"""A bad registry refresh must not erase dispatch schemas or stall live controls."""
import asyncio
import copy
import json
from types import SimpleNamespace

import httpx
import pytest

pytest.importorskip('mcp')
from mcp.client import Client
from gbox import mcp_server as M


ENTRY = {'name': 'fixture', 'description': 'Fixture tool',
         'input_schema': {'type': 'object', 'properties': {'payload': {'type': 'string'}}},
         'workers': ['worker']}


def harness(monkeypatch, handler):
    callbacks, clients, options = {}, [], []
    original_client, original_server = httpx.AsyncClient, M.Server

    def client(*args, **kwargs):
        options.append(kwargs.copy())
        out = original_client(*args, **kwargs, transport=httpx.MockTransport(handler))
        clients.append(out)
        return out

    def server(*args, **kwargs):
        callbacks.update(kwargs)
        return original_server(*args, **kwargs)

    clock = [100.0]
    monkeypatch.setattr(M, 'time', SimpleNamespace(monotonic=lambda: clock[0]))
    monkeypatch.setattr(httpx, 'AsyncClient', client)
    monkeypatch.setattr(M, 'Server', server)
    return M.build('http://fixture', 'fixture'), callbacks, clients, options, clock


def names(result):
    return {t.name for t in result.tools}


@pytest.mark.parametrize('failure', [
    'timeout', 'http_error', 'bad_json', {}, {'tools': None},
    {'tools': [ENTRY, {'description': 'missing name'}]},
    {'tools': [ENTRY, ENTRY]},
    {'tools': [{**ENTRY, 'workers': 'worker'}]},
    {'tools': [{**ENTRY, 'workers': ['worker', None]}]},
    {'tools': [{**ENTRY, 'input_schema': []}]},
    {'tools': [{**ENTRY, 'input_schema': {'properties': []}}]},
])
def test_invalid_refresh_preserves_complete_schema_then_recovers(monkeypatch, caplog, failure):
    calls = []
    response = [{'tools': [copy.deepcopy(ENTRY)]}]

    def handler(request):
        calls.append(request.url.path)
        value = response[0]
        if value == 'timeout':
            raise httpx.ReadTimeout('sensitive response details', request=request)
        if value == 'http_error':
            return httpx.Response(503, text='sensitive response details')
        if value == 'bad_json':
            return httpx.Response(200, text='sensitive response details')
        return httpx.Response(200, json=value)

    server, callbacks, clients, _, clock = harness(monkeypatch, handler)

    async def check():
        async with server.lifespan(server):
            first = await callbacks['on_list_tools'](None, None)
            old = next(t for t in first.tools if t.name == 'job_fixture')
            response[0] = failure
            clock[0] += M.REGISTRY_CACHE_SECONDS + 1
            failed = await callbacks['on_list_tools'](None, None)
            assert next(t for t in failed.tools if t.name == 'job_fixture') == old
            assert names(failed) == names(first)
            # Same failed refresh is coalesced; no repeated retries per viewer.
            await callbacks['on_list_tools'](None, None)
            assert len(calls) == 2
            response[0] = {'tools': [{**ENTRY, 'name': 'recovered'}]}
            clock[0] += M.REGISTRY_RETRY_SECONDS + .1
            recovered = await callbacks['on_list_tools'](None, None)
            assert 'job_recovered' in names(recovered)
            assert 'job_fixture' not in names(recovered)
            assert len(calls) == 3
        assert all(c.is_closed for c in clients)

    asyncio.run(check())
    assert 'retaining 1 tools' in caplog.text
    assert 'sensitive response details' not in caplog.text


def test_valid_empty_registry_removes_retired_tools(monkeypatch):
    response = [{'tools': [ENTRY]}]
    server, callbacks, _, _, clock = harness(
        monkeypatch, lambda request: httpx.Response(200, json=response[0]))

    async def check():
        async with server.lifespan(server):
            assert 'job_fixture' in names(await callbacks['on_list_tools'](None, None))
            response[0] = {'tools': []}
            clock[0] += M.REGISTRY_CACHE_SECONDS + 1
            assert names(await callbacks['on_list_tools'](None, None)) == set(M.CONVENIENCE)

    asyncio.run(check())


def test_registry_routing_preserves_strict_schema_and_deduplicates_workers(monkeypatch):
    schema = {'oneOf': [{'type': 'object', 'properties': {'code': {'type': 'string'}},
                          'additionalProperties': False}]}
    entry = {**ENTRY, 'name': 'rea_fixture', 'workers': ['worker', 'worker'], 'input_schema': schema}
    original = copy.deepcopy(entry)
    server, callbacks, _, _, _ = harness(
        monkeypatch, lambda request: httpx.Response(200, json={'tools': [entry]}))

    async def check():
        async with server.lifespan(server):
            result = await callbacks['on_list_tools'](None, None)
            tool = next(t for t in result.tools if t.name == 'job_rea_fixture')
            assert tool.input_schema['properties']['input'] == schema
            assert 'require_worker' in tool.input_schema['properties']
            assert 'workers: worker;' in tool.description
            assert entry == original

    asyncio.run(check())


def test_simultaneous_schema_reads_share_one_refresh(monkeypatch):
    calls = []

    async def check():
        started, release = asyncio.Event(), asyncio.Event()

        async def handler(request):
            calls.append(request.url.path)
            started.set()
            await release.wait()
            return httpx.Response(200, json={'tools': [ENTRY]})

        server, callbacks, _, _, _ = harness(monkeypatch, handler)
        async with server.lifespan(server):
            tasks = [asyncio.create_task(callbacks['on_list_tools'](None, None)) for _ in range(8)]
            await started.wait()
            assert len(calls) == 1
            release.set()
            results = await asyncio.gather(*tasks)
            assert len(calls) == 1
            assert all('job_fixture' in names(result) for result in results)

    asyncio.run(check())


def test_registry_deadline_cancels_request_and_returns_only_known_tools(monkeypatch):
    monkeypatch.setattr(M, 'REGISTRY_TIMEOUT_SECONDS', .02)

    async def check():
        cancelled = asyncio.Event()

        async def handler(request):
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()

        server, callbacks, _, _, _ = harness(monkeypatch, handler)
        async with server.lifespan(server):
            result = await asyncio.wait_for(callbacks['on_list_tools'](None, None), .5)
            assert names(result) == set(M.CONVENIENCE)
            assert cancelled.is_set()

    asyncio.run(check())


def test_live_get_and_click_use_separate_pool_during_registry_stall(monkeypatch):
    calls = []

    async def check():
        started, release = asyncio.Event(), asyncio.Event()
        session = {'session_id': 'pc-round', 'state': 'running', 'game_id': '115f9cdbba115432',
                   'adapter': 'eden', 'title': 'RE6'}
        rotation = {'hosts': [{'id': 'pc', 'online': True, 'current_run': {
            'session_id': 'pc-round', 'game_id': session['game_id'], 'phase': 'playing'}}]}

        async def handler(request):
            calls.append((request.url.path, request.method, request.headers['x-gbox-actor']))
            assert request.headers['authorization'] == 'Bearer fixture'
            if request.url.path == '/api/registry':
                started.set()
                await release.wait()
                return httpx.Response(200, json={'tools': []})
            if request.url.path == '/api/sessions':
                assert request.url.params['include_ended'] == 'false'
                return httpx.Response(200, json=[session])
            if request.url.path == '/api/mercmode':
                return httpx.Response(200, json=rotation)
            if request.url.path == '/api/sessions/pc-round/interventions':
                if request.method == 'POST':
                    body = json.loads(request.content)
                    return httpx.Response(200, json={'request': {**body, 'state': 'queued'}})
                return httpx.Response(200, json={'available': True, 'capabilities': ['flash_now']})
            raise AssertionError(str(request.url))

        server, callbacks, clients, options, _ = harness(monkeypatch, handler)
        async with server.lifespan(server):
            pending = asyncio.create_task(callbacks['on_list_tools'](None, None))
            await started.wait()
            out = await asyncio.wait_for(callbacks['on_call_tool'](None, SimpleNamespace(
                name='game_live_controls', arguments={'session_id': 'pc-round', 'op': 'flash_now',
                    'request_id': '00000000-0000-4000-8000-000000000001'})), .5)
            assert not out.is_error
            assert json.loads(out.content[0].text)['action']['state'] == 'queued'
            assert not pending.done()
            assert all(actor == ('mcp' if path == '/api/registry' else 'pine-live-controls')
                       for path, _, actor in calls)
            assert clients[0] is not clients[1]
            assert options[1]['timeout'].pool == 2 and options[1]['trust_env'] is False
            release.set()
            await pending
        assert all(c.is_closed for c in clients)

    asyncio.run(check())


def test_real_mcp_lifespan_closes_pools_and_can_restart(monkeypatch):
    server, _, clients, _, _ = harness(
        monkeypatch, lambda request: httpx.Response(200, json={'tools': [ENTRY]}))

    async def check():
        assert clients == []  # building an unused server allocates no HTTP pools
        for _ in range(2):
            async with Client(server) as client:
                assert 'job_fixture' in names(await client.list_tools())
                assert not clients[-1].is_closed
            assert all(c.is_closed for c in clients)
        assert len(clients) == 4

    asyncio.run(check())


def test_overlapping_lifespans_keep_shared_pools_until_last_exit(monkeypatch):
    server, callbacks, clients, _, _ = harness(
        monkeypatch, lambda request: httpx.Response(200, json={'tools': []}))

    async def check():
        async with server.lifespan(server):
            async with server.lifespan(server):
                assert len(clients) == 2
            assert not any(c.is_closed for c in clients)
            await callbacks['on_list_tools'](None, None)
        assert all(c.is_closed for c in clients)

    asyncio.run(check())
