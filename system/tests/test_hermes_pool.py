import asyncio
import json

from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient
import pytest

from gbox import hermes_local as L, hermes_pool as P, hermes_models as M
from gbox.config import HermesLocalConfig


@pytest.fixture
def pool(monkeypatch, tmp_path):
    monkeypatch.setenv('GBOX_HERMES_DISPATCH_STATE', str(tmp_path))
    s = HermesLocalConfig(proxy_url='http://localhost:8765/api/llm/local/v1', pool_max_parallel_jobs=5,
        nodes={'lilspark': {'provider': 'prime', 'model': 'small', 'max_parallel_jobs': 1},
               'sparkDeux': {'provider': 'second', 'model': 'large', 'api_format': 'openai',
                            'upstream': 'http://second/v1', 'max_parallel_jobs': 4, 'shared_with_games': False,
                            'allow_large_tasks': True}})
    monkeypatch.setattr(L, 'settings', lambda: s)
    monkeypatch.setattr(P, '_HEALTH', {})
    monkeypatch.setattr(P, '_PROXIES', {})
    return s


def test_admission_prefers_prime_and_loads_second_without_oversubscription(pool):
    nodes = [{'name': 'sparkDeux', 'primary': False, 'enabled': True, 'capable': True, 'capacity': 4},
             {'name': 'lilspark', 'primary': True, 'enabled': True, 'capable': True, 'capacity': 1}]
    slots, cap = P.assignments(nodes, {}, set())
    assert [n['name'] for n in slots] == ['lilspark'] + ['sparkDeux']*4 and cap == 5
    items = {'a': {'job_id': '1', 'inference_node': 'lilspark'},
             'b': {'job_id': '2', 'inference_node': 'sparkDeux'}}
    assert len(P.assignments(nodes, items, {'1', '2', 'legacy'})[0]) == 2
    nodes[0]['capable'] = False
    assert P.assignments(nodes, items, {'1', '2'})[0] == []


def test_switch_and_maintenance_persist_without_overwriting_operator(pool):
    assert P.node_settings()['sparkDeux'].proxy_url.endswith('/nodes/sparkDeux/v1')
    P.maintenance('sparkDeux', True)
    P.set_node('sparkDeux', False)
    P.maintenance('sparkDeux', False)
    assert not P.node_settings()['sparkDeux'].enabled
    P.set_node('sparkDeux', True)
    assert P.node_settings()['sparkDeux'].enabled
    assert L.is_local({'provider': 'prime'})


def test_cron_default_keeps_canonical_node_endpoint_and_active_model(pool):
    base = pool.model_copy(update={'provider': 'second', 'model': 'old-model'})
    node = P.node_settings(base)['sparkDeux']
    entry = L.provider_entry(base)
    assert entry['base_url'] == node.proxy_url
    assert entry['model'] == node.model
    assert L.merged_providers([entry], base) is None


def _app(monkeypatch):
    app = FastAPI()
    def auth(request: Request):
        if request.headers.get('authorization') != 'Bearer test':
            raise HTTPException(401)
        return 'operator'
    P.routes(app, None, auth, lambda: None)
    return TestClient(app), {'Authorization': 'Bearer test'}


def test_authenticated_switch_and_failover_preserve_tools(pool, monkeypatch):
    client, headers = _app(monkeypatch)
    assert client.post('/api/hermes/local/nodes/sparkDeux', json={'enabled': False}).status_code == 401
    assert client.post('/api/hermes/local/nodes/sparkDeux', headers=headers, json={'enabled': False}).status_code == 200
    monkeypatch.setattr(P, 'health', lambda *a, **kw: {'capable': True})
    seen = []
    class Proxy:
        async def complete(self, body, *args):
            seen.append(body)
            return {'choices': [{'message': {'tool_calls': body['tools']}}]}
    P._PROXIES['lilspark'] = Proxy()
    body = {'messages': [{'role': 'user', 'content': 'continue checkpoint'}], 'tools': [{'function': {'name': 'read'}}]}
    r = client.post('/api/llm/local/nodes/sparkDeux/v1/chat/completions', headers=headers, json=body)
    assert r.status_code == 200 and r.headers['X-gBox-Inference-Host'] == 'lilspark'
    assert seen == [body]
    P.set_node('lilspark', False)
    assert client.post('/api/llm/local/nodes/sparkDeux/v1/chat/completions', headers=headers, json=body).status_code == 503


@pytest.mark.parametrize('cooldown_delta', [60, 0, -60])
def test_pre_stream_failover_does_not_retry_a_known_credit_exhausted_node(pool, monkeypatch, cooldown_delta):
    from gbox.llm_proxy import Busy
    settings = pool.model_copy(update={'nodes': {
        'sparkDeux': {'provider': 'gbox-sparkDeux', 'model': 'qwen', 'max_parallel_jobs': 4,
                      'shared_with_games': False},
        'claude': {'provider': 'gbox-claude', 'model': 'claude-sonnet-5-5', 'max_parallel_jobs': 4,
                   'shared_with_games': False},
    }})
    monkeypatch.setattr(L, 'settings', lambda: settings)
    monkeypatch.setattr(P.time, 'time', lambda: 1000.0)
    # /models still reports both nodes ready even though paid inference is denied.
    monkeypatch.setattr(P, 'health', lambda *a, **k: {'capable': True})
    path = P.D.state_dir() / 'feedback.json'
    path.write_text(json.dumps({'cooldowns': {'gbox-claude/claude-sonnet-5-5': 1000 + cooldown_delta}}))
    before = path.read_bytes()
    seen = []

    class Spark:
        async def complete(self, body, *args):
            seen.append('sparkDeux')
            raise Busy(503, 'upstream temporarily unavailable')

    class Claude:
        async def complete(self, body, *args):
            seen.append('claude')
            return {'ok': True}

    P._PROXIES.update(sparkDeux=Spark(), claude=Claude())
    client, headers = _app(monkeypatch)
    response = client.post('/api/llm/local/nodes/sparkDeux/v1/chat/completions',
                           headers=headers, json={'messages': [{'role': 'user', 'content': 'resume'}]})
    assert response.status_code == (503 if cooldown_delta > 0 else 200)
    assert seen == (['sparkDeux'] if cooldown_delta > 0 else ['sparkDeux', 'claude'])
    assert path.read_bytes() == before and P.node_settings()['claude'].enabled


def test_capacity_slider_persists_and_drains_without_disabling(pool, monkeypatch):
    cron = []
    monkeypatch.setattr(P, '_sync_cron_capacity', cron.append)
    client, headers = _app(monkeypatch)
    path = '/api/hermes/local/nodes/sparkDeux/capacity'
    assert client.post(path, json={'capacity': 24}).status_code == 401
    for invalid in (0, 5, 20, 33, '24', True):
        assert client.post(path, headers=headers, json={'capacity': invalid}).status_code in (400, 422)
    for capacity in (4, 8, 12, 16, 24, 32, 4):
        response = client.post(path, headers=headers, json={'capacity': capacity})
        assert response.status_code == 200
        assert cron[-1] == capacity + 1
        nodes = P.node_settings()
        assert nodes['sparkDeux'].max_parallel_jobs == capacity and nodes['sparkDeux'].enabled
        assert nodes['lilspark'].max_parallel_jobs == 1
        active = {str(n): {'job_id': str(n), 'inference_node': 'sparkDeux'} for n in range(24)}
        state = [{'name': n, 'primary': s.shared_with_games, 'enabled': True, 'capable': True,
                  'capacity': s.max_parallel_jobs} for n, s in nodes.items()]
        slots, limit = P.assignments(state, active, set(active))
        assert limit == capacity + 1
        assert len(slots) == max(0, capacity + 1 - 24)
    assert client.post('/api/hermes/local/nodes/lilspark/capacity', headers=headers,
                       json={'capacity': 24}).status_code == 400
    assert client.post('/api/hermes/local/nodes/missing/capacity', headers=headers,
                       json={'capacity': 24}).status_code == 404
    def failed(_):
        raise RuntimeError('Scheduler unavailable')
    monkeypatch.setattr(P, '_sync_cron_capacity', failed)
    assert client.post(path, headers=headers, json={'capacity': 24}).status_code == 503
    assert P.node_settings()['sparkDeux'].max_parallel_jobs == 4


def test_partial_tool_stream_is_never_replayed(pool, monkeypatch):
    client, headers = _app(monkeypatch)
    monkeypatch.setattr(P, 'health', lambda *a, **kw: {'capable': True})
    class Proxy:
        async def stream(self, *args):
            async def events():
                yield 'data: {"tool_call":"partial"}\n\n'
                raise RuntimeError('connection lost')
            return events()
    class Prime:
        async def stream(self, *args):
            raise AssertionError('Must not replay a partially emitted tool call')
    P._PROXIES.update(sparkDeux=Proxy(), lilspark=Prime())
    with pytest.raises(RuntimeError, match='connection lost'):
        client.post('/api/llm/local/nodes/sparkDeux/v1/chat/completions', headers=headers,
                    json={'stream': True, 'messages': []})


@pytest.mark.parametrize('stream', [False, True])
@pytest.mark.parametrize('unavailable', ['disabled', 'cooldown', 'health', 'upstream'])
def test_strict_node_never_fails_over(pool, monkeypatch, stream, unavailable):
    from gbox.llm_proxy import Busy
    client, headers = _app(monkeypatch)
    monkeypatch.setattr(P, 'health', lambda name, *a, **k: {
        'capable': not (name == 'sparkDeux' and unavailable == 'health')})
    calls = []
    class Spark:
        async def complete(self, *args):
            calls.append('sparkDeux')
            raise Busy(502, 'bounded upstream failure', 17)
        stream = complete
    class Prime:
        async def complete(self, *args):
            raise AssertionError('Strict Spark2 work must never use the prime GPU')
        stream = complete
    P._PROXIES.update(sparkDeux=Spark(), lilspark=Prime())
    if unavailable == 'disabled':
        P.set_node('sparkDeux', False)
    if unavailable == 'cooldown':
        (P.D.state_dir() / 'feedback.json').write_text(json.dumps({
            'cooldowns': {'second/large': P.time.time() + 60}}))
    response = client.post('/api/llm/local/strict-nodes/sparkDeux/v1/chat/completions',
                           headers=headers, json={'stream': stream, 'messages': []})
    assert response.status_code == 503
    assert response.headers['retry-after'] == ('17' if unavailable == 'upstream' else '30')
    assert calls == (['sparkDeux'] if unavailable == 'upstream' else [])


def test_strict_node_models_and_chat_require_access_and_known_target(pool, monkeypatch):
    mounted, headers = _app(monkeypatch)
    client = TestClient(mounted.app, client=('192.0.2.1', 1234))
    root = '/api/llm/local/strict-nodes/'
    assert client.get(root + 'sparkDeux/v1/models').status_code == 401
    assert client.post(root + 'sparkDeux/v1/chat/completions', json={}).status_code == 401
    response = client.get(root + 'sparkDeux/v1/models', headers=headers)
    assert response.status_code == 200 and response.json()['data'][0]['id'] == 'large'
    assert client.get(root + 'unknown/v1/models', headers=headers).status_code == 404
    assert client.post(root + 'unknown/v1/chat/completions', headers=headers, json={}).status_code == 404
    monkeypatch.setattr(L, 'settings', lambda: pool.model_copy(update={'enabled': False}))
    assert client.post(root + 'sparkDeux/v1/chat/completions', headers=headers, json={}).status_code == 503


def test_strict_and_normal_calls_share_the_real_node_admission_limiter(pool, monkeypatch):
    import httpx
    from gbox import llm_proxy
    # All ten admissions can enter the queue before its acquisition tasks run.
    # Exercise permit sharing without deliberately overflowing that queue.
    monkeypatch.setattr(L, 'settings', lambda: pool.model_copy(update={'queue_limit': 16}))
    actual = llm_proxy.LocalLLM
    created, seen = [], []
    active, maximum = 0, 0
    async def upstream(request):
        nonlocal active, maximum
        active += 1
        maximum = max(maximum, active)
        seen.append(json.loads(request.content))
        await asyncio.sleep(.02)
        active -= 1
        return httpx.Response(200, json={'model': 'large', 'choices': [
            {'message': {'role': 'assistant', 'content': 'bounded review'}, 'finish_reason': 'stop'}]})
    def make_proxy(settings, **kw):
        proxy = actual(settings, transport=httpx.MockTransport(upstream), **kw)
        created.append(proxy)
        return proxy
    monkeypatch.setattr(llm_proxy, 'LocalLLM', make_proxy)
    monkeypatch.setattr(P, 'health', lambda *a, **kw: {'capable': True})
    client, headers = _app(monkeypatch)
    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=client.app),
                                     base_url='http://testserver', headers=headers) as http:
            responses = await asyncio.gather(*(http.post(
                '/api/llm/local/' + ('strict-nodes' if i % 2 else 'nodes') +
                '/sparkDeux/v1/chat/completions',
                json={'messages': [{'role': 'user', 'content': 'Analyze one round'}]}) for i in range(10)))
            bad = [(r.status_code, r.headers.get('x-gbox-inference-host'), r.text) for r in responses
                   if r.status_code != 200 or r.headers.get('x-gbox-inference-host') != 'sparkDeux']
            assert not bad, bad
    asyncio.run(run())
    assert len(created) == 1 and P._PROXIES['sparkDeux'] is created[0]
    assert maximum == 4 and len(seen) == 10
    assert created[0].active == created[0].waiting == 0


@pytest.mark.parametrize('stream', [False, True])
@pytest.mark.parametrize('hint,expected', [
    (19, '19'), ('0', '0'), ('Wed, 21 Oct 2026 19:00:00 GMT', 'Wed, 21 Oct 2026 19:00:00 GMT'),
    ('invalid', None), ('-4', None), ('20\r\nInjected: true', None), (None, None),
])
def test_pool_forwards_rate_limit_retry_after_without_failover(pool, monkeypatch, stream, hint, expected):
    from gbox.llm_proxy import Busy
    client, headers = _app(monkeypatch)
    monkeypatch.setattr(P, 'health', lambda *a, **kw: {'capable': True})
    calls = []
    class Limited:
        async def complete(self, *args):
            calls.append('sparkDeux')
            raise Busy(429, 'Local inference: busy', hint)
        stream = complete
    class Prime:
        async def complete(self, *args):
            raise AssertionError('429 must retain its existing no-failover behavior')
        stream = complete
    P._PROXIES.update(sparkDeux=Limited(), lilspark=Prime())
    response = client.post('/api/llm/local/nodes/sparkDeux/v1/chat/completions', headers=headers,
                           json={'stream': stream, 'messages': [{'role': 'user', 'content': 'continue'}]})
    assert response.status_code == 429 and response.headers.get('retry-after') == expected
    assert calls == ['sparkDeux'] and P.node_settings()['sparkDeux'].max_parallel_jobs == 4


@pytest.mark.parametrize('hint,expected', [(None, '30'), ('invalid', '30'), (45, '45'),
    ('Wed, 21 Oct 2026 19:00:00 GMT', 'Wed, 21 Oct 2026 19:00:00 GMT')])
def test_exhausted_failover_retains_valid_retry_hint(pool, monkeypatch, hint, expected):
    from gbox.llm_proxy import Busy
    client, headers = _app(monkeypatch)
    monkeypatch.setattr(P, 'health', lambda *a, **kw: {'capable': True})
    calls = []
    class Unavailable:
        def __init__(self, name): self.name = name
        async def complete(self, *args):
            calls.append(self.name)
            raise Busy(502, 'Local inference: unavailable', hint if self.name == 'sparkDeux' else None)
    P._PROXIES.update(sparkDeux=Unavailable('sparkDeux'), lilspark=Unavailable('lilspark'))
    response = client.post('/api/llm/local/nodes/sparkDeux/v1/chat/completions', headers=headers,
                           json={'messages': [{'role': 'user', 'content': 'continue'}]})
    assert response.status_code == 503 and response.headers['retry-after'] == expected
    assert calls == ['sparkDeux', 'lilspark']


def test_model_actions_are_allowlisted_and_require_download(pool, monkeypatch):
    monkeypatch.setattr(M, 'access', lambda: {'ready': True})
    with pytest.raises(ValueError, match='Unknown'):
        M.submit('start', 'arbitrary/model; shell')
    with pytest.raises(ValueError, match='Pull'):
        M.submit('start', M.MODEL)


def test_remote_failed_model_start_restores_original(monkeypatch):
    from gbox import hermes_model_remote as R
    calls = []
    old = {'State': {'Running': True}, 'Image': 'sha256:pinned', 'Config': {'Env': []},
           'Mounts': [{'Destination': '/root/.cache/huggingface', 'Type': 'bind', 'Source': '/cache'}]}
    def run(args, **kw):
        calls.append(args)
        if args[:2] == ['docker', 'inspect']:
            return json.dumps([old])
        if args[:2] == ['docker', 'run']:
            assert args[args.index('--gpu-memory-utilization')+1] == '0.9'
            raise RuntimeError('Model launch failed')
        return ''
    class Metrics:
        def read(self):
            return b'vllm:num_requests_running 0\nvllm:num_requests_waiting 0\n'
    monkeypatch.setattr(R, 'run', run)
    monkeypatch.setattr(R.urllib.request, 'urlopen', lambda *a, **k: Metrics())
    monkeypatch.setattr(R.subprocess, 'run', lambda args, **kw: calls.append(args))
    with pytest.raises(RuntimeError, match='launch failed'):
        R.main({'action': 'start', 'model': M.MODEL, 'container': 'original', 'id': '123'})
    assert calls[-1] == ['docker', 'start', 'original']


def test_queue_report_handoff_retries_and_deduplicates_without_closing_task(pool, monkeypatch):
    from gbox import hermes_work_queue as Q
    item = {'local': True, 'request_id': 'a'*16}
    run = {'id': 'b'*32}
    monkeypatch.setattr(Q, '_final_report', lambda r: 'Partial inventory. Artifact abc. Next: verify build hash.')
    messages, attempts = [], []
    def api(path, body=None):
        if body is None:
            return {'messages': messages, 'status': 'open'}
        assert path.endswith('/messages') and 'status' not in body
        attempts.append(body)
        messages.append(body)
        if len(attempts) == 1:
            raise TimeoutError('acknowledgment lost after the server stored the report')
    monkeypatch.setattr(Q, '_api', api)
    Q._preserve_report(item, run)
    assert item['final_report'].startswith('Partial inventory') and item['report_error'] == 'TimeoutError'
    Q._preserve_report(item, run)
    assert item['report_posted_run'] == run['id'] and len(attempts) == 1


def test_the_global_cap_is_shared_between_non_primary_nodes(pool, monkeypatch):
    monkeypatch.setattr(P, 'pool_limit', lambda: 64)
    # 2026-10-24: 13 free under the cap went to spark2's 15 free slots; DeepSeek ran 3 of its 16
    nodes = [{'name': 'sparkDeux', 'primary': False, 'enabled': True, 'capable': True, 'capacity': 32},
             {'name': 'deepseek', 'primary': False, 'enabled': True, 'capable': True, 'capacity': 16}]
    items = {str(n): {'job_id': str(n), 'inference_node': 'sparkDeux'} for n in range(17)}
    items |= {f'd{n}': {'job_id': f'd{n}', 'inference_node': 'deepseek'} for n in range(3)}
    reserved = set(i['job_id'] for i in items.values()) | {f'legacy{n}' for n in range(15)}
    slots, limit = P.assignments(nodes, items, reserved)
    names = [n['name'] for n in slots]
    assert limit == 48 and len(names) == 13
    assert names.count('deepseek') >= 6 and names.count('sparkDeux') >= 6
