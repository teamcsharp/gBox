import asyncio
import json

import httpx
import pytest

from gbox import hermes_local, hermes_providers as H, llm_proxy as P
from gbox.config import HermesLocalConfig


S = HermesLocalConfig(provider='sparkDeux-inbox', host_name='sparkDeux',
    api_format='openai', upstream='http://10.89.1.225:8101/v1',
    proxy_url='http://127.0.0.1:8765/api/llm/local/v1', model='owned-model',
    shared_with_games=False, max_parallel_jobs=2, allow_large_tasks=True, enable_thinking=False)
CALL = {'id': 'native-call', 'type': 'function',
        'function': {'name': 'read_request', 'arguments': '{"id":"request"}'}}
BODY = {'messages': [{'role': 'user', 'content': 'Read the request'}],
        'tools': [{'type': 'function', 'function': {'name': 'read_request', 'parameters': {'type': 'object'}}}]}


def test_vllm_preserves_tools_and_records_actual_host(tmp_path):
    seen = []
    def handle(req):
        seen.append(json.loads(req.content))
        assert str(req.url) == 'http://10.89.1.225:8101/v1/chat/completions'
        return httpx.Response(200, json={'model': S.model,
            'choices': [{'message': {'role': 'assistant', 'content': None, 'tool_calls': [CALL]},
                         'finish_reason': 'tool_calls'}],
            'usage': {'prompt_tokens': 30, 'completion_tokens': 10, 'total_tokens': 40}})
    proxy = P.LocalLLM(lambda: S, gate=lambda: 'lilspark game', log_path=tmp_path/'calls.jsonl',
                       transport=httpx.MockTransport(handle))
    result = asyncio.run(proxy.complete(BODY))
    assert result['choices'][0]['message']['tool_calls'] == [CALL]
    assert seen[0]['tools'] == BODY['tools'] and 'options' not in seen[0]
    assert seen[0]['chat_template_kwargs'] == {'enable_thinking': False}
    record = json.loads((tmp_path/'calls.jsonl').read_text())
    assert record['host_name'] == 'sparkDeux' and record['provider'] == S.provider
    assert record['total_tokens'] == 40 and proxy.status()['capacity'] == 2


def test_vllm_stream_tool_fragments_usage_and_disconnect(tmp_path):
    chunks = [
        {'choices': [{'index': 0, 'delta': {'tool_calls': [{'index': 0, **CALL}]}}]},
        {'choices': [{'index': 0, 'delta': {'tool_calls': [{'index': 0,
            'function': {'arguments': 'remaining'}}]}, 'finish_reason': 'tool_calls'}]},
        {'choices': [], 'usage': {'prompt_tokens': 22, 'completion_tokens': 8, 'total_tokens': 30}}]
    wire = ''.join('data: '+json.dumps(c)+'\n\n' for c in chunks)+'data: [DONE]\n\n'
    async def check(complete):
        def handle(req):
            assert json.loads(req.content)['stream_options']['include_usage']
            return httpx.Response(200, text=wire if complete else wire.replace('data: [DONE]\n\n',''))
        proxy = P.LocalLLM(lambda: S, log_path=tmp_path/('ok' if complete else 'cut'),
                           transport=httpx.MockTransport(handle))
        events = await proxy.stream(BODY)
        result = ''.join([part async for part in events])
        assert result == (wire if complete else wire.replace('data: [DONE]\n\n',''))
        assert proxy.active == 0
        record = json.loads(proxy.log_path.read_text())
        assert record['status'] == ('ok' if complete else 'error') and record['tool_calls'] == 1
        assert record['total_tokens'] == 30
    asyncio.run(check(True));asyncio.run(check(False))


def test_remote_capacity_and_error_release():
    active, maximum = 0, 0
    async def handle(req):
        nonlocal active, maximum
        active += 1;maximum = max(maximum, active)
        await asyncio.sleep(.01)
        active -= 1
        return httpx.Response(503, json={'error': {'message': 'busy'}})
    proxy = P.LocalLLM(lambda: S, transport=httpx.MockTransport(handle))
    async def run():
        results = await asyncio.gather(*(proxy.complete(BODY) for _ in range(4)), return_exceptions=True)
        assert all(isinstance(r, P.Busy) for r in results)
    asyncio.run(run())
    assert maximum == 2 and proxy.active == proxy.waiting == 0


def test_provider_attribution_requires_observed_endpoint_and_model(monkeypatch, tmp_path):
    monkeypatch.setattr(H, '_local_settings', lambda: S)
    scan = H.Scanner(tmp_path/'agent.log', tmp_path/'audit.jsonl')
    for line in (
        '2026-10-17 05:00:00 INFO [cron_a_20261017_050000] OpenAI client created (chat_completion_stream_request) provider=custom model=owned-model base_url=http://127.0.0.1:8765/api/llm/local/v1',
        '2026-10-17 05:00:01 INFO [cron_a_20261017_050000] API call #1: model=owned-model provider=custom in=20 out=5',
        '2026-10-17 05:00:02 INFO [cron_b_20261017_050000] OpenAI client created (chat_completion_stream_request) provider=custom model=owned-model base_url=http://another-host/v1'):
        scan._line(line, None)
    assert H.served_by(scan.sessions['cron_a_20261017_050000'])['provider'] == S.provider
    assert H.served_by(scan.sessions['cron_b_20261017_050000'])['provider'] == 'custom'
    assert scan.events[1]['provider'] == S.provider


def test_second_spark_metrics_do_not_inherit_lilspark_calls(monkeypatch):
    monkeypatch.setattr(P, 'read_log', lambda since: [
        {'model': 'gpt-oss:20b', 'status': 'ok', 'total_tokens': 100000},
        {'provider': S.provider, 'model': S.model, 'host_name': S.host_name,
         'status': 'ok', 'total_tokens': 30}])
    result = H.local_summary(S, {}, [], 0)
    assert result['calls_ok'] == 1 and result['tokens'] == 30 and result['host_name'] == 'sparkDeux'
    assert 'at most one source file' not in hermes_local.local_prompt('Assigned task', S)
