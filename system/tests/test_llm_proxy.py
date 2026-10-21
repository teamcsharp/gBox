"""gBox's proxy in front of the Spark's Ollama (Hermes's local route): message fixes (the EhmBird "no user query"
failure), context cap, tool calls intact both ways, streaming, concurrency 1, and the operator-plays gate."""
import asyncio
import json

import httpx
import pytest
from fastapi.testclient import TestClient

from gbox import llm_proxy as P
from gbox.config import HermesLocalConfig

S = HermesLocalConfig(proxy_url='http://127.0.0.1:8765/api/llm/local/v1', queue_wait_s=5, retry_after_s=90)
CALL = {'id': 'call_1', 'type': 'function', 'function': {'name': 'mcp_gbox_get_request',
                                                         'arguments': '{"request_id": "abcdef0123456789"}'}}


def qwen_template_accepts(messages):
    """Qwen3's chat template rule that made every EhmBird call fail with HTTP 500."""
    for m in reversed(messages):
        c = m.get('content')
        if m['role'] == 'user' and isinstance(c, str) and not (c.startswith('<tool_response>') and c.endswith('</tool_response>')):
            return True
    raise ValueError('No user query found in messages.')


def test_ehmbird_failure_case_gets_a_user_turn_without_breaking_the_tool_chain():
    # A compacted cron conversation: system prompt, an assistant tool call and its result, no user message at all.
    conversation = [{'role': 'system', 'content': 'You are Hermes.'},
                    {'role': 'assistant', 'content': None, 'tool_calls': [CALL]},
                    {'role': 'tool', 'tool_call_id': 'call_1', 'content': '{"status": "open"}'}]
    with pytest.raises(ValueError, match='No user query'):
        qwen_template_accepts(conversation)
    fixed, fixes = P.fix_messages(conversation)
    assert qwen_template_accepts(fixed) and 'added_user_turn' in fixes
    assert [m['role'] for m in fixed] == ['system', 'user', 'assistant', 'tool']   # call -> result stays adjacent
    assert fixed[1]['content'] == 'Continue.' and fixed[2]['tool_calls'] == [CALL] and fixed[2]['content'] == ''
    # Ending with a finished assistant reply (a compaction summary): the user turn goes last.
    fixed, _ = P.fix_messages([{'role': 'system', 'content': 's'}, {'role': 'assistant', 'content': 'Summary.'}])
    assert [m['role'] for m in fixed] == ['system', 'assistant', 'user']
    # A wrapped tool response or list content is not a query either.
    fixed, fixes = P.fix_messages([{'role': 'user', 'content': '<tool_response>x</tool_response>'}])
    assert qwen_template_accepts(fixed) and 'added_user_turn' in fixes


def test_roles_the_templates_reject_are_mapped():
    fixed, fixes = P.fix_messages([
        {'role': 'developer', 'content': 'dev rules'}, {'role': 'system', 'content': 'sys'},
        {'role': 'user', 'content': [{'type': 'text', 'text': 'look'}, {'type': 'image_url', 'image_url': {'url': 'data:'}}]},
        {'role': 'system', 'content': 'context was compacted'}, {'role': 'function', 'name': 'f', 'content': 'r'},
        {'role': 'critic', 'content': 'hmm'}])
    assert [m['role'] for m in fixed] == ['system', 'user', 'user', 'tool', 'user']
    assert fixed[0]['content'] == 'dev rules\n\nsys'
    assert fixed[1]['content'] == 'look\n[image omitted: the local model reads text only]'
    assert fixed[2]['content'] == '[system note] context was compacted'
    assert {'role_developer_to_system', 'merged_system', 'late_system_to_user', 'flattened_content',
            'role_function_to_tool', 'role_critic_to_user'} <= set(fixes)


def test_context_cap_drops_whole_old_turns_and_keeps_the_task():
    system = {'role': 'system', 'content': 'S' * 300}
    task = {'role': 'user', 'content': 'Assigned queue task: request #5'}
    old = [{'role': 'assistant', 'content': '', 'tool_calls': [dict(CALL, id=f'c{i}')]} if i % 2 == 0 else
           {'role': 'tool', 'tool_call_id': f'c{i - 1}', 'content': 'R' * 3000} for i in range(20)]
    last = {'role': 'assistant', 'content': 'nearly done'}
    out, info = P.cap_context([system, task, *old, last], None, budget=2500, cpt=3.0)
    assert out[1] == task and out[-1] == last and info['dropped'] > 0
    assert 'left out' in out[0]['content']
    for i, m in enumerate(out):                                 # no tool result without its call
        if m['role'] == 'tool':
            assert out[i - 1]['role'] in ('assistant', 'tool')
    assert P.estimate(out, None, 3.0) <= 2500
    huge = [system, task, {'role': 'assistant', 'content': '', 'tool_calls': [CALL]},
            {'role': 'tool', 'tool_call_id': 'call_1', 'content': 'X' * 60000}]
    out, info = P.cap_context(huge, None, budget=4000, cpt=3.0)
    assert info['cut'] >= 1 and 'characters cut by the gBox proxy' in out[-1]['content']
    assert P.estimate(out, None, 3.0) <= 4000


def test_tool_calls_pass_through_intact_both_ways():
    body = {'messages': [{'role': 'user', 'content': 'go'}, {'role': 'assistant', 'content': None, 'tool_calls': [CALL]},
                         {'role': 'tool', 'tool_call_id': 'call_1', 'content': 'ok'}],
            'tools': [{'type': 'function', 'function': {'name': 'mcp_gbox_get_request', 'parameters': {'type': 'object'}}}],
            'reasoning_effort': 'high', 'temperature': 0.2}
    payload = P.to_ollama(body, body['messages'], S, model='gpt-oss:20b', max_out=4096, ctx=65536)
    assert payload['messages'][1]['tool_calls'] == [{'function': {'name': 'mcp_gbox_get_request',
                                                                  'arguments': {'request_id': 'abcdef0123456789'}}}]
    assert payload['messages'][2]['tool_name'] == 'mcp_gbox_get_request'
    assert payload['tools'] == body['tools'] and payload['think'] == 'high'
    assert payload['options'] == {'num_ctx': 65536, 'num_predict': 4096, 'temperature': 0.2}
    assert 'think' not in P.to_ollama(body, body['messages'], S, model='gemma4:12b', max_out=1, ctx=1)
    answer = {'message': {'role': 'assistant', 'content': '', 'thinking': 'plan',
                          'tool_calls': [{'function': {'name': 'mcp_gbox_list_tasks', 'arguments': {'limit': 3}}}]},
              'done': True, 'done_reason': 'stop', 'prompt_eval_count': 1200, 'eval_count': 40}
    out = P.from_ollama(answer, 'gpt-oss:20b', 'chatcmpl-x', 1)
    choice = out['choices'][0]
    assert choice['finish_reason'] == 'tool_calls' and choice['message']['content'] is None
    call = choice['message']['tool_calls'][0]
    assert call['type'] == 'function' and call['id'].startswith('call_')
    assert call['function'] == {'name': 'mcp_gbox_list_tasks', 'arguments': '{"limit": 3}'}
    assert choice['message']['reasoning_content'] == 'plan'
    assert out['usage'] == {'prompt_tokens': 1200, 'completion_tokens': 40, 'total_tokens': 1240}


def test_stream_translation():
    lines = [json.dumps({'message': {'role': 'assistant', 'content': 'Hel'}}),
             json.dumps({'message': {'role': 'assistant', 'content': 'lo'}}),
             json.dumps({'message': {'role': 'assistant', 'content': '', 'tool_calls': [
                 {'function': {'name': 'f', 'arguments': {'a': 1}}}]}}),
             json.dumps({'done': True, 'done_reason': 'stop', 'prompt_eval_count': 10, 'eval_count': 3})]
    events = P.stream_chunks(lines, 'gpt-oss:20b', 'id', 1)
    assert events[-1] == 'data: [DONE]\n\n'
    data = [json.loads(e[6:]) for e in events[:-1]]
    deltas = [d['choices'][0]['delta'] for d in data if d['choices']]
    assert deltas[0] == {'role': 'assistant', 'content': ''}
    assert ''.join(d.get('content', '') for d in deltas) == 'Hello'
    calls = [d['tool_calls'] for d in deltas if 'tool_calls' in d][0]
    assert calls[0]['index'] == 0 and calls[0]['function'] == {'name': 'f', 'arguments': '{"a": 1}'}
    assert [d['choices'][0]['finish_reason'] for d in data if d['choices']][-1] == 'tool_calls'
    assert data[-1]['usage'] == {'prompt_tokens': 10, 'completion_tokens': 3, 'total_tokens': 13}


def ollama(seen, *, delay=0.0, active=None):
    """A fake Ollama /api/chat: records each payload, optionally tracks how many calls overlap."""
    async def handler(request: httpx.Request):
        body = json.loads(request.content or b'{}')
        seen.append((request.url.path, body))
        if request.url.path == '/api/generate':
            return httpx.Response(200, json={'done': True})
        if active is not None:
            active['now'] += 1
            active['max'] = max(active['max'], active['now'])
        await asyncio.sleep(delay)
        if active is not None:
            active['now'] -= 1
        if body.get('stream'):
            text = '\n'.join(json.dumps(x) for x in (
                {'message': {'role': 'assistant', 'content': 'ok'}},
                {'done': True, 'done_reason': 'stop', 'prompt_eval_count': 7, 'eval_count': 2})) + '\n'
            return httpx.Response(200, text=text)
        return httpx.Response(200, json={'message': {'role': 'assistant', 'content': 'ok'}, 'done': True,
                                         'done_reason': 'stop', 'prompt_eval_count': 7, 'eval_count': 2})
    return httpx.MockTransport(handler)


def test_concurrency_is_one_and_the_rest_queue(tmp_path):
    seen, active = [], {'now': 0, 'max': 0}
    proxy = P.LocalLLM(lambda: S, transport=ollama(seen, delay=0.05, active=active), log_path=tmp_path / 'log.jsonl')
    body = {'messages': [{'role': 'user', 'content': 'hi'}]}

    async def main():
        return await asyncio.gather(*(proxy.complete(dict(body)) for _ in range(4)))
    results = asyncio.run(main())
    assert all(r['choices'][0]['message']['content'] == 'ok' for r in results)
    assert active['max'] == 1 and len(seen) == 4
    records = [json.loads(x) for x in (tmp_path / 'log.jsonl').read_text().splitlines()]
    assert [r['status'] for r in records] == ['ok'] * 4
    assert sum(r['total_tokens'] for r in records) == 36 and any(r['queued_s'] > 0 for r in records)
    assert P.summarize(records)['tokens'] == 36


def test_full_queue_answers_503(tmp_path):
    seen = []
    tight = S.model_copy(update={'queue_limit': 1})
    proxy = P.LocalLLM(lambda: tight, transport=ollama(seen, delay=0.2))
    body = {'messages': [{'role': 'user', 'content': 'hi'}]}

    async def main():
        return await asyncio.gather(*(proxy.complete(dict(body)) for _ in range(3)), return_exceptions=True)
    results = asyncio.run(main())
    busy = [r for r in results if isinstance(r, P.Busy)]
    assert len(busy) == 1 and busy[0].status == 503 and busy[0].retry_after


def test_operator_playing_on_the_spark_gates_calls_and_frees_the_gpu(tmp_path):
    seen, playing = [], [None]
    proxy = P.LocalLLM(lambda: S, gate=lambda: playing[0], transport=ollama(seen), log_path=tmp_path / 'log.jsonl')
    body = {'messages': [{'role': 'user', 'content': 'hi'}]}
    asyncio.run(proxy.complete(dict(body)))
    playing[0] = 'the operator is playing Soulcalibur on the Spark'
    with pytest.raises(P.Busy) as e:
        asyncio.run(proxy.complete(dict(body)))
    assert e.value.status == 503 and e.value.retry_after == 90 and 'Soulcalibur' in e.value.message
    from gbox import hermes_quota                                # a wait for the operator never cools the route
    assert hermes_quota.provider_failure('HTTP 503: ' + e.value.message) is None
    assert seen[-1] == ('/api/generate', {'model': 'gpt-oss:20b', 'keep_alive': 0})   # model unloaded once
    with pytest.raises(P.Busy):
        asyncio.run(proxy.complete(dict(body)))
    assert sum(path == '/api/generate' for path, _ in seen) == 1
    assert proxy.status()['gated'].startswith('the operator')
    records = [json.loads(x) for x in (tmp_path / 'log.jsonl').read_text().splitlines()]
    assert [r['status'] for r in records] == ['ok', 'gated', 'gated']


def test_slow_operator_gate_does_not_freeze_the_event_loop():
    import threading
    entered, release = threading.Event(), threading.Event()
    def gate():
        entered.set()
        assert release.wait(3)
    proxy = P.LocalLLM(lambda: S, gate=gate, transport=ollama([]))
    async def main():
        call = asyncio.create_task(proxy.acquire(S))
        try:
            # The release is scheduled on the same loop: a synchronous gate would stall it.
            asyncio.get_running_loop().call_later(.05, release.set)
            lock, _ = await asyncio.wait_for(call, 1)
            assert entered.is_set()
            proxy.release(lock)
        finally:
            release.set()
    asyncio.run(main())


def test_cancelling_second_operator_gate_releases_model_slot():
    import threading
    entered, release = threading.Event(), threading.Event()
    calls = []
    def gate():
        calls.append(1)
        if len(calls) == 2:
            entered.set()
            assert release.wait(3)
    proxy = P.LocalLLM(lambda: S, gate=gate, transport=ollama([]))
    async def main():
        call = asyncio.create_task(proxy.acquire(S))
        try:
            while not entered.is_set():
                await asyncio.sleep(.005)
            call.cancel()
            with pytest.raises(asyncio.CancelledError): await call
            assert not proxy._lock().locked()
            assert proxy.active == 0
        finally: release.set()
    asyncio.run(main())


def test_endpoint_fixes_messages_streams_and_gates(cfg, monkeypatch, tmp_path):
    from gbox.server import create_app
    monkeypatch.setenv('GBOX_HERMES_DISPATCH_STATE', str(tmp_path / 'state'))
    app = create_app(cfg)
    seen = []
    app.state.local_llm.transport = ollama(seen)
    hermes = TestClient(app)                                    # loopback: no token, as Hermes on the Spark calls
    ehmbird = {'model': 'whatever', 'messages': [{'role': 'system', 'content': 's'},
                                                 {'role': 'assistant', 'content': None, 'tool_calls': [CALL]},
                                                 {'role': 'tool', 'tool_call_id': 'call_1', 'content': 'r'}]}
    r = hermes.post('/api/llm/local/v1/chat/completions', json=ehmbird)
    assert r.status_code == 200 and r.json()['choices'][0]['message']['content'] == 'ok'
    sent = seen[-1][1]
    assert seen[-1][0] == '/api/chat' and sent['model'] == 'gpt-oss:20b' and sent['options']['num_ctx'] == 65536
    assert any(m['role'] == 'user' for m in sent['messages'])
    r = hermes.post('/api/llm/local/v1/chat/completions', json=ehmbird | {'stream': True})
    assert r.status_code == 200 and r.headers['content-type'].startswith('text/event-stream')
    assert r.text.rstrip().endswith('data: [DONE]') and '"content": "ok"' in r.text
    assert hermes.get('/api/llm/local/v1/models').json()['data'][0]['context_length'] == 65536
    lan = TestClient(app, client=('10.89.1.50', 50000))         # another machine needs the gBox token
    assert lan.post('/api/llm/local/v1/chat/completions', json=ehmbird).status_code == 401
    assert lan.get('/api/llm/local/status', headers={'authorization': f'Bearer {cfg.token()}'}).status_code == 200
    # The operator starts a game on the Spark (a Linux worker); an agent's evidence session would not count.
    store = app.state.store
    store.put('worker', 'spark1', {'id': 'spark1', 'name': 'lilspark', 'os': 'linux', 'tools': [], 'last_seen': 9e12})
    store.put('session', 'spark1-s', {'session_id': 'spark1-s', 'state': 'running', 'title': 'Soulcalibur'})
    r = hermes.post('/api/llm/local/v1/chat/completions', json=ehmbird)
    assert r.status_code == 503 and r.headers['retry-after'] == '120' and 'Soulcalibur' in r.json()['error']['message']
    assert hermes.get('/api/llm/local/status').json()['gated'].startswith('the operator is playing')
    store.put('slabel', 'spark1-s', {'session_id': 'spark1-s', 'label': 'Evidence capture', 'owner': 'agent'})
    assert hermes.post('/api/llm/local/v1/chat/completions', json=ehmbird).status_code == 200


@pytest.mark.parametrize('stream', [False, True])
@pytest.mark.parametrize('hint,expected', [
    ('17', '17'), ('0', '0'), ('Wed, 21 Oct 2026 19:00:00 GMT', 'Wed, 21 Oct 2026 19:00:00 GMT'),
    ('-1', None), ('1.5', None), ('tomorrow', None), (None, None),
])
def test_upstream_retry_after_reaches_client_without_replaying(cfg, monkeypatch, tmp_path, stream, hint, expected):
    from gbox.server import create_app
    monkeypatch.setenv('GBOX_HERMES_DISPATCH_STATE', str(tmp_path / 'state'))
    app = create_app(cfg)
    calls = []
    def upstream(request):
        calls.append(request)
        return httpx.Response(429, json={'error': 'too many concurrent requests'},
                              headers={'Retry-After': hint} if hint is not None else {})
    app.state.local_llm.transport = httpx.MockTransport(upstream)
    response = TestClient(app).post('/api/llm/local/v1/chat/completions',
        json={'messages': [{'role': 'user', 'content': 'continue'}], 'stream': stream})
    assert response.status_code == 429
    assert response.headers.get('retry-after') == expected
    assert len(calls) == 1 and app.state.local_llm.active == 0


@pytest.mark.parametrize('stream', [False, True])
@pytest.mark.parametrize('status,expected_status', [(400, 400), (503, 502)])
def test_non_rate_limit_upstream_error_keeps_status_mapping(stream, status, expected_status):
    proxy = P.LocalLLM(lambda: S, transport=httpx.MockTransport(
        lambda request: httpx.Response(status, json={'error': 'unavailable'}, headers={'Retry-After': '23'})))
    with pytest.raises(P.Busy) as error:
        asyncio.run((proxy.stream if stream else proxy.complete)(
            {'messages': [{'role': 'user', 'content': 'continue'}]}))
    assert error.value.status == expected_status and error.value.retry_after == '23'
    assert proxy.active == 0


@pytest.mark.parametrize('stream', [False, True])
def test_context_recap_forwards_the_final_error_retry_after(stream):
    calls = []
    def upstream(request):
        calls.append(request)
        if len(calls) == 1:
            return httpx.Response(400, json={'error':
                'maximum context length is 32768 tokens; prompt contains at least 40000 input tokens'},
                headers={'Retry-After': '7'})
        return httpx.Response(429, json={'error': 'busy'}, headers={'Retry-After': '29'})
    proxy = P.LocalLLM(lambda: S, transport=httpx.MockTransport(upstream))
    with pytest.raises(P.Busy) as error:
        asyncio.run((proxy.stream if stream else proxy.complete)(
            {'messages': [{'role': 'user', 'content': 'continue'}]}))
    assert error.value.status == 429 and error.value.retry_after == '29'
    assert len(calls) == 2 and proxy.active == 0
