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
    result = asyncio.run(proxy.complete(dict(BODY, reasoning_effort='max', reasoning={'effort': 'max'})))
    assert result['choices'][0]['message']['tool_calls'] == [CALL]
    assert seen[0]['tools'] == BODY['tools'] and 'options' not in seen[0]
    assert seen[0]['chat_template_kwargs'] == {'enable_thinking': False}
    assert 'reasoning_effort' not in seen[0] and 'reasoning' not in seen[0]
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


def test_live_capacity_increases_and_lowering_drains_existing_requests():
    async def run():
        cfg = S.model_copy(update={'max_parallel_jobs': 4, 'queue_limit': 40})
        proxy = P.LocalLLM(lambda: cfg)
        held = [await proxy.acquire(cfg) for _ in range(4)]
        waiting = [asyncio.create_task(proxy.acquire(cfg)) for _ in range(20)]
        await asyncio.sleep(.02)
        assert proxy.active == 4 and not any(t.done() for t in waiting)
        cfg.max_parallel_jobs = 24
        original = held[0][0]
        assert proxy._lock() is original
        held += await asyncio.wait_for(asyncio.gather(*waiting), 1)
        assert proxy.active == 24
        cfg.max_parallel_jobs = 4
        assert proxy._lock() is original
        next_call = asyncio.create_task(proxy.acquire(cfg))
        for lock, _ in held[:20]:
            proxy.release(lock)
        await asyncio.sleep(.02)
        assert proxy.active == 4 and not next_call.done()
        proxy.release(held[20][0])
        acquired, _ = await asyncio.wait_for(next_call, 1)
        assert proxy.active == 4
        for lock, _ in held[21:]:
            proxy.release(lock)
        proxy.release(acquired)
        assert proxy.active == proxy.waiting == original.used == 0
    asyncio.run(run())


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


@pytest.mark.parametrize('api_format', ['openai', 'ollama'])
def test_queue_budget_warns_then_forces_final_checkpoint(api_format):
    s = S.model_copy(update={'api_format': api_format, 'tool_budget': 8})
    proxy = P.LocalLLM(lambda: s)
    messages = [{'role': 'user', 'content': 'Assigned queue task: request #7. Read the inventory.'}]
    for n in range(8):
        call = dict(CALL, id='call-'+str(n))
        messages += [{'role': 'assistant', 'content': None, 'tool_calls': [call]},
                     {'role': 'tool', 'tool_call_id': call['id'], 'content': 'bounded result'}]
    _, warning, meta = asyncio.run(proxy.prepare(dict(BODY, messages=messages[:-2])))
    assert 'save a checkpoint' in str(warning['messages']) and not meta['budget_final']
    assert 'publish_task_changes' in str(warning['messages'])
    assert 'commit/PR receipt' in str(warning['messages']) and 'keep partial work in_progress' in str(warning['messages'])
    assert warning.get('tool_choice') != 'none' and warning.get('tools'), 'handoff calls remain available'
    _, final, meta = asyncio.run(proxy.prepare(dict(BODY, messages=messages)))
    assert meta['budget_final'] and meta['queue_tool_calls'] == 8
    assert 'factual final checkpoint' in str(final['messages'])
    assert 'Publication without a returned receipt remains pending' in str(final['messages'])
    if api_format == 'openai':
        assert final['tool_choice'] == 'none'
    else:
        assert 'tools' not in final
    messages[0]['content'] = 'Unrelated interactive conversation'
    _, payload, meta = asyncio.run(proxy.prepare(dict(BODY, messages=messages)))
    assert not meta['budget_final'] and payload.get('tools')


def test_the_proxy_budget_follows_the_lane_in_the_queue_header():
    """#2399: the proxy enforces tool_budget_inbox for an inbox-lane run and tool_budget for a favorite, read from
    the queue header the dispatcher writes, so the prompt and the proxy agree."""
    s = S.model_copy(update={'tool_budget': 8, 'tool_budget_inbox': 12})
    proxy = P.LocalLLM(lambda: s)

    def meta_for(lane):
        messages = [{'role': 'user', 'content': f'Assigned queue task: request #7 ({"ab" * 8}) [lane {lane}]. Read the inventory.'}]
        for n in range(8):
            call = dict(CALL, id='call-' + str(n))
            messages += [{'role': 'assistant', 'content': None, 'tool_calls': [call]},
                         {'role': 'tool', 'tool_call_id': call['id'], 'content': 'bounded result'}]
        return asyncio.run(proxy.prepare(dict(BODY, messages=messages)))[2]
    assert meta_for('favorite')['budget_final'], 'a favorite run at 8 of 8 calls ends'
    assert not meta_for('inbox')['budget_final'], 'an inbox run at 8 of 12 calls continues'


@pytest.mark.parametrize('upstream', ['https://api.deepseek.com/v1', 'https://api.kimi.com/coding/v1', 'https://api.z.ai/api/coding/paas/v4'])
def test_deepseek_upstream_gets_its_own_thinking_switch(tmp_path, upstream):
    """DeepSeek ignores vLLM's chat_template_kwargs; V4 models then think and demand replayed reasoning_content."""
    seen = []
    D = S.model_copy(update={'upstream': upstream, 'model': 'deepseek-v4-pro', 'host_name': 'deepseek'})

    def handle(req):
        seen.append(json.loads(req.content))
        return httpx.Response(200, json={'model': D.model,
            'choices': [{'message': {'role': 'assistant', 'content': 'ok'}, 'finish_reason': 'stop'}],
            'usage': {'prompt_tokens': 3, 'completion_tokens': 1, 'total_tokens': 4}})
    proxy = P.LocalLLM(lambda: D, gate=lambda: None, log_path=tmp_path/'calls.jsonl', transport=httpx.MockTransport(handle))
    asyncio.run(proxy.complete(dict(BODY)))
    assert seen[0]['thinking'] == {'type': 'disabled'} and 'chat_template_kwargs' not in seen[0]
