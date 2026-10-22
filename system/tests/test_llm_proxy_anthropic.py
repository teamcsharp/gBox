"""The Claude pool node (api_format = 'anthropic'): OpenAI chat completions in, the Messages API out and back, with
prompt caching, thinking blocks replayed on the next tool step, Sonnet 5.5's 400 traps avoided, and the health check.
No real API calls: every upstream is an httpx.MockTransport."""
import asyncio
import json

import httpx
import pytest

from gbox import hermes_pool as HP
from gbox import llm_proxy as P
from gbox.config import HermesLocalConfig

KEY_ENV = 'GBOX_TEST_ANTHROPIC_KEY'
S = HermesLocalConfig(provider='gbox-claude', model='claude-sonnet-5-5', upstream='https://api.anthropic.com/v1',
                      api_format='anthropic', upstream_key_env=KEY_ENV, shared_with_games=False, max_parallel_jobs=4,
                      context_tokens=200000, max_output_tokens=32000, enable_thinking=True,
                      proxy_url='http://127.0.0.1:8765/api/llm/local/nodes/claude/v1')
TOOLS = [{'type': 'function', 'function': {'name': 'terminal', 'description': 'Run a command',
                                           'parameters': {'type': 'object', 'properties': {'cmd': {'type': 'string'}}}}},
         {'type': 'function', 'function': {'name': 'list_tasks', 'parameters': {}}}]
CALL = {'id': 'functions.terminal:0', 'type': 'function', 'function': {'name': 'terminal', 'arguments': '{"cmd": "ls"}'}}


def blocks_of(payload, i):
    return payload['messages'][i]['content']


def test_request_translation_caching_and_the_400_traps():
    messages = [{'role': 'system', 'content': 'You are Hermes.'}, {'role': 'user', 'content': 'go'},
                {'role': 'assistant', 'content': 'Looking.', 'tool_calls': [CALL]},
                {'role': 'tool', 'tool_call_id': 'functions.terminal:0', 'content': 'a.txt'},
                {'role': 'user', 'content': 'Only 4 tool calls remain.'}]
    body = {'messages': messages, 'tools': TOOLS, 'tool_choice': 'required', 'temperature': 0.2, 'top_p': 0.9,
            'reasoning_effort': 'xhigh', 'stop': ['\n\nUser:', ''], 'parallel_tool_calls': False}
    p = P.to_anthropic(body, messages, S, model=S.model, max_out=32000, tail=1)
    assert p['model'] == 'claude-sonnet-5-5' and p['max_tokens'] == 32000
    assert p['system'] == [{'type': 'text', 'text': 'You are Hermes.', 'cache_control': {'type': 'ephemeral'}}]
    assert [m['role'] for m in p['messages']] == ['user', 'assistant', 'user']
    assert blocks_of(p, 1) == [{'type': 'text', 'text': 'Looking.'},
                               {'type': 'tool_use', 'id': 'functions_terminal_0', 'name': 'terminal', 'input': {'cmd': 'ls'}}]
    # The result and the proxy's reminder share one user turn, result first; the cache breakpoint sits on the result
    # (the last message Hermes sent), so the next step's prefix matches this one's.
    result, reminder = blocks_of(p, 2)
    assert result == {'type': 'tool_result', 'tool_use_id': 'functions_terminal_0', 'content': 'a.txt',
                      'cache_control': {'type': 'ephemeral'}}
    assert reminder == {'type': 'text', 'text': 'Only 4 tool calls remain.'}
    assert p['tools'][0] == {'name': 'terminal', 'description': 'Run a command',
                             'input_schema': {'type': 'object', 'properties': {'cmd': {'type': 'string'}}}}
    assert p['tools'][1]['input_schema'] == {'type': 'object', 'properties': {}} and 'cache_control' not in p['tools'][1]
    # Forced tool choice is a 400 on Sonnet 5.5: "required" falls back to auto (here with one call at a time).
    assert p['tool_choice'] == {'type': 'auto', 'disable_parallel_tool_use': True}
    assert p['stop_sequences'] == ['\n\nUser:'] and p['output_config'] == {'effort': 'xhigh'}
    for absent in ('thinking', 'temperature', 'top_p', 'chat_template_kwargs', 'options', 'num_ctx', 'think',
                   'keep_alive', 'stream_options'):
        assert absent not in p
    # Thinking off on the node: between_tools (never "disabled"), effort clamped to high; at the tool budget: none.
    off = S.model_copy(update={'enable_thinking': False})
    p = P.to_anthropic({'messages': messages, 'tools': TOOLS, 'reasoning_effort': 'max'}, messages, off,
                       model=S.model, max_out=1000, final=True)
    assert p['thinking'] == {'type': 'between_tools'} and p['output_config'] == {'effort': 'high'}
    assert p['tool_choice'] == {'type': 'none'}
    assert blocks_of(p, 2)[-1]['cache_control'] == {'type': 'ephemeral'}       # no tail: the last message itself


def test_compacted_histories_still_pair_every_call_with_a_result():
    # An orphan result (its call compacted away), a call whose result is missing, no user turn first, and an
    # assistant turn last (prefill is a 400): all repaired. Without a system prompt the tools carry the breakpoint.
    messages = [{'role': 'assistant', 'content': 'Summary of earlier work.'},
                {'role': 'tool', 'tool_call_id': 'call_gone', 'content': 'old output'},
                {'role': 'assistant', 'content': '', 'tool_calls': [CALL]},
                {'role': 'assistant', 'content': 'Done.'}]
    p = P.to_anthropic({'messages': messages, 'tools': TOOLS}, messages, S, model=S.model, max_out=100)
    roles = [m['role'] for m in p['messages']]
    assert roles == ['user', 'assistant', 'user', 'assistant', 'user', 'assistant', 'user']
    assert blocks_of(p, 0) == [{'type': 'text', 'text': 'Continue.'}]
    assert blocks_of(p, 2) == [{'type': 'text', 'text': '[tool result call_gone] old output'}]
    assert blocks_of(p, 4) == [{'type': 'tool_result', 'tool_use_id': 'functions_terminal_0', 'is_error': True,
                                'content': 'No result was recorded for this call.'}]
    assert blocks_of(p, 6) == [{'type': 'text', 'text': 'Continue.'}]
    assert p['tools'][-1]['cache_control'] == {'type': 'ephemeral'} and 'system' not in p


def test_response_translation_with_cache_usage():
    resp = {'content': [{'type': 'thinking', 'thinking': 'plan it', 'signature': 'sig'},
                        {'type': 'text', 'text': 'Checking.'},
                        {'type': 'tool_use', 'id': 'toolu_1', 'name': 'terminal', 'input': {'cmd': 'ls'}}],
            'stop_reason': 'tool_use',
            'usage': {'input_tokens': 300, 'cache_read_input_tokens': 54000, 'cache_creation_input_tokens': 700,
                      'output_tokens': 90}}
    out = P.from_anthropic(resp, 'claude-sonnet-5-5', 'chatcmpl-x', 1)
    msg = out['choices'][0]['message']
    assert out['choices'][0]['finish_reason'] == 'tool_calls'
    assert msg['content'] == 'Checking.' and msg['reasoning_content'] == 'plan it'
    assert msg['tool_calls'] == [{'id': 'toolu_1', 'type': 'function',
                                  'function': {'name': 'terminal', 'arguments': '{"cmd": "ls"}'}}]
    assert out['usage']['prompt_tokens'] == 55000 and out['usage']['completion_tokens'] == 90
    assert out['usage']['prompt_tokens_details'] == {'cached_tokens': 54000}
    assert out['usage']['cache_creation_input_tokens'] == 700
    for reason, finish in (('end_turn', 'stop'), ('max_tokens', 'length'), ('refusal', 'content_filter')):
        assert P.from_anthropic({'content': [], 'stop_reason': reason}, 'm', 'c', 1)['choices'][0]['finish_reason'] == finish


def sse(*events):
    """Anthropic's stream: an `event:` line and a `data:` line per event."""
    out = []
    for ev in events:
        out += [f'event: {ev["type"]}', 'data: ' + json.dumps(ev), '']
    return out


STREAM = sse(
    {'type': 'message_start', 'message': {'usage': {'input_tokens': 20, 'cache_read_input_tokens': 5000,
                                                    'cache_creation_input_tokens': 0, 'output_tokens': 1}}},
    {'type': 'content_block_start', 'index': 0, 'content_block': {'type': 'thinking', 'thinking': '', 'signature': ''}},
    {'type': 'content_block_delta', 'index': 0, 'delta': {'type': 'thinking_delta', 'thinking': 'look first'}},
    {'type': 'content_block_delta', 'index': 0, 'delta': {'type': 'signature_delta', 'signature': 'SIG'}},
    {'type': 'content_block_stop', 'index': 0},
    {'type': 'ping'},
    {'type': 'content_block_start', 'index': 1, 'content_block': {'type': 'text', 'text': ''}},
    {'type': 'content_block_delta', 'index': 1, 'delta': {'type': 'text_delta', 'text': 'Hel'}},
    {'type': 'content_block_delta', 'index': 1, 'delta': {'type': 'text_delta', 'text': 'lo'}},
    {'type': 'content_block_stop', 'index': 1},
    {'type': 'content_block_start', 'index': 2,
     'content_block': {'type': 'tool_use', 'id': 'toolu_A', 'name': 'terminal', 'input': {}}},
    {'type': 'content_block_delta', 'index': 2, 'delta': {'type': 'input_json_delta', 'partial_json': '{"cmd": '}},
    {'type': 'content_block_delta', 'index': 2, 'delta': {'type': 'input_json_delta', 'partial_json': '"ls"}'}},
    {'type': 'content_block_stop', 'index': 2},
    {'type': 'content_block_start', 'index': 3,
     'content_block': {'type': 'tool_use', 'id': 'toolu_B', 'name': 'list_tasks', 'input': {}}},
    {'type': 'content_block_stop', 'index': 3},
    {'type': 'message_delta', 'delta': {'stop_reason': 'tool_use'}, 'usage': {'output_tokens': 42}},
    {'type': 'message_stop'})


def test_stream_translation_keeps_tool_calls_and_the_signed_thinking():
    t = P.AnthropicStream('claude-sonnet-5-5', 'id', 1)
    events = P.stream_chunks(STREAM, 'claude-sonnet-5-5', 'id', 1, translator=lambda *a: t)
    assert events[-1] == 'data: [DONE]\n\n'
    data = [json.loads(e[6:]) for e in events[:-1]]
    deltas = [d['choices'][0]['delta'] for d in data if d['choices']]
    assert deltas[0] == {'role': 'assistant', 'content': ''}
    assert ''.join(d.get('content', '') for d in deltas) == 'Hello'
    assert ''.join(d.get('reasoning_content', '') for d in deltas) == 'look first'
    calls = [c for d in deltas for c in d.get('tool_calls', [])]
    assert calls[0] == {'index': 0, 'id': 'toolu_A', 'type': 'function', 'function': {'name': 'terminal', 'arguments': ''}}
    assert ''.join(c['function']['arguments'] for c in calls if c['index'] == 0) == '{"cmd": "ls"}'
    assert ''.join(c['function']['arguments'] for c in calls if c['index'] == 1) == '{}'
    assert [d['choices'][0]['finish_reason'] for d in data if d['choices']][-1] == 'tool_calls'
    assert data[-1]['usage']['prompt_tokens'] == 5020 and data[-1]['usage']['completion_tokens'] == 42
    assert t.result['content'][0] == {'type': 'thinking', 'thinking': 'look first', 'signature': 'SIG'}
    assert t.result['content'][2] == {'type': 'tool_use', 'id': 'toolu_A', 'name': 'terminal', 'input': {'cmd': 'ls'}}
    # A stream that breaks off, or reports an error, never claims usage.
    cut = P.stream_chunks(STREAM[:12], 'm', 'id', 1, translator=P.AnthropicStream)
    assert 'usage' not in cut[-2]
    err = P.AnthropicStream('m', 'id', 1)
    P.stream_chunks(sse({'type': 'error', 'error': {'type': 'overloaded_error', 'message': 'Overloaded'}}), 'm', 'id', 1,
                    translator=lambda *a: err)
    assert err.result['error'] == 'Overloaded' and err.result['usage'] is None


def claude(seen, answers):
    """A fake api.anthropic.com: records (path, headers, body) and plays the scripted answers in order."""
    async def handler(request: httpx.Request):
        seen.append((request.url.path, dict(request.headers), json.loads(request.content or b'{}')))
        status, payload = answers.pop(0)
        if isinstance(payload, list):
            return httpx.Response(status, text='\n'.join(payload) + '\n', headers={'content-type': 'text/event-stream'})
        return httpx.Response(status, json=payload)
    return httpx.MockTransport(handler)


async def stream_all(proxy, body):
    return [e async for e in await proxy.stream(body)]


def test_two_tool_steps_replay_thinking_with_its_signature(monkeypatch, tmp_path):
    monkeypatch.setenv(KEY_ENV, 'sk-ant-test')
    seen = []
    done = {'content': [{'type': 'text', 'text': 'All done.'}], 'stop_reason': 'end_turn',
            'usage': {'input_tokens': 10, 'cache_read_input_tokens': 5000, 'output_tokens': 3}}
    proxy = P.LocalLLM(lambda: S, transport=claude(seen, [(200, STREAM), (200, done)]), log_path=tmp_path / 'log.jsonl')
    history = [{'role': 'system', 'content': 'You are Hermes.'}, {'role': 'user', 'content': 'go'}]
    body = {'messages': history, 'tools': TOOLS, 'stream': True, 'temperature': 0.7}
    asyncio.run(stream_all(proxy, body))
    path, headers, first = seen[0]
    assert path == '/v1/messages' and first['stream'] is True and 'stream_options' not in first
    assert headers['x-api-key'] == 'sk-ant-test' and headers['anthropic-version'] == '2023-06-01'
    assert 'authorization' not in headers and 'temperature' not in first
    # Hermes sends the turn back in OpenAI form (no signature anywhere); the proxy restores the model's own blocks.
    history += [{'role': 'assistant', 'content': 'Hello', 'reasoning_content': 'look first',
                 'tool_calls': [{'id': 'toolu_A', 'type': 'function', 'function': {'name': 'terminal', 'arguments': '{"cmd": "ls"}'}},
                                {'id': 'toolu_B', 'type': 'function', 'function': {'name': 'list_tasks', 'arguments': '{}'}}]},
                {'role': 'tool', 'tool_call_id': 'toolu_A', 'content': 'a.txt'},
                {'role': 'tool', 'tool_call_id': 'toolu_B', 'content': '[]'}]
    out = asyncio.run(proxy.complete({'messages': history, 'tools': TOOLS}))
    assert out['choices'][0]['message']['content'] == 'All done.'
    second = seen[1][2]
    assert second['stream'] is False
    assert blocks_of(second, 1)[0] == {'type': 'thinking', 'thinking': 'look first', 'signature': 'SIG'}
    assert [b['type'] for b in blocks_of(second, 1)] == ['thinking', 'text', 'tool_use', 'tool_use']
    assert [b['tool_use_id'] for b in blocks_of(second, 2)] == ['toolu_A', 'toolu_B']
    records = [json.loads(x) for x in (tmp_path / 'log.jsonl').read_text().splitlines()]
    assert [r['status'] for r in records] == ['ok', 'ok'] and records[0]['tool_calls'] == 2
    assert records[1]['replayed_thinking'] == 1 and records[1]['cache_read_input_tokens'] == 5000
    assert records[0]['api_format'] == 'anthropic' and records[0]['provider'] == 'gbox-claude'


@pytest.mark.parametrize('stream', [False, True])
def test_refused_thinking_blocks_are_dropped_and_sent_once_more(monkeypatch, stream):
    monkeypatch.setenv(KEY_ENV, 'sk-ant-test')
    seen = []
    refused = {'type': 'error', 'error': {'type': 'invalid_request_error', 'message':
               'messages.1.content.0: Invalid `signature` in `thinking` block. The block is bound to a different conversation.'}}
    ok = {'content': [{'type': 'text', 'text': 'ok'}], 'stop_reason': 'end_turn', 'usage': {}}
    answer = sse({'type': 'message_start', 'message': {'usage': {}}}, {'type': 'message_stop'}) if stream else ok
    proxy = P.LocalLLM(lambda: S, transport=claude(seen, [(400, refused), (200, answer)]))
    proxy.remember([{'type': 'thinking', 'thinking': '', 'signature': 'OLD'},
                    {'type': 'tool_use', 'id': 'toolu_A', 'name': 'terminal', 'input': {'cmd': 'ls'}}])
    history = [{'role': 'user', 'content': 'go'},
               {'role': 'assistant', 'content': None, 'tool_calls': [{'id': 'toolu_A', 'type': 'function',
                                                                      'function': {'name': 'terminal', 'arguments': '{"cmd": "ls"}'}}]},
               {'role': 'tool', 'tool_call_id': 'toolu_A', 'content': 'a.txt'}]
    body = {'messages': history, 'tools': TOOLS, 'stream': stream}
    asyncio.run(stream_all(proxy, body) if stream else proxy.complete(body))
    assert len(seen) == 2
    assert [b['type'] for b in blocks_of(seen[0][2], 1)] == ['thinking', 'tool_use']
    assert [b['type'] for b in blocks_of(seen[1][2], 1)] == ['tool_use']
    # Any other 400 is the caller's answer, not retried.
    seen.clear()
    proxy = P.LocalLLM(lambda: S, transport=claude(seen, [(400, {'type': 'error', 'error': {'message': 'bad tools'}})]))
    with pytest.raises(P.Busy) as e:
        asyncio.run(proxy.complete({'messages': history}))
    assert e.value.status == 400 and len(seen) == 1


def test_health_lists_claude_models_with_the_api_key(monkeypatch):
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, json={'data': [{'id': 'claude-opus-5-5'}, {'id': 'claude-sonnet-5-5'}]})
    real = httpx.Client
    monkeypatch.setattr(HP.httpx, 'Client', lambda **kw: real(transport=httpx.MockTransport(handler), **kw))
    monkeypatch.setattr(HP, '_HEALTH', {})
    monkeypatch.delenv(KEY_ENV, raising=False)
    value = HP.health('claude', S, refresh=True)
    assert not value['capable'] and value['reason'] == f'{KEY_ENV} is not set for gBox' and not seen
    monkeypatch.setenv(KEY_ENV, 'sk-ant-test')
    value = HP.health('claude', S, refresh=True)
    assert value['online'] and value['capable'] and value['reason'] == 'Ready'
    assert len(seen) == 1 and str(seen[0].url) == 'https://api.anthropic.com/v1/models?limit=1000'   # no /metrics
    assert seen[0].headers['x-api-key'] == 'sk-ant-test' and seen[0].headers['anthropic-version'] == '2023-06-01'
    value = HP.health('claude', S.model_copy(update={'model': 'claude-sonnet-9'}), refresh=True)
    assert value['online'] and not value['capable'] and value['reason'] == 'Configured model is not served'
