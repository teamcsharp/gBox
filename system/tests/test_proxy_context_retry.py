"""The local proxy re-caps a prompt the model says exceeds its context, from the model's own count, and retries once."""
import asyncio
import json

import httpx

from gbox import llm_proxy as P
from gbox.config import HermesLocalConfig

S = HermesLocalConfig(proxy_url='http://127.0.0.1:8765/api/llm/local/v1', queue_wait_s=5, retry_after_s=90,
                      context_tokens=4000, max_output_tokens=500)
OVERRUN = ("This model's maximum context length is 4000 tokens. However, your prompt contains at least 4620 input "
           "tokens, which exceeds this limit even without the completion.")


def test_tighter_cpt_comes_from_the_models_count():
    assert P.tighter_cpt(OVERRUN, estimated=3000, cpt=3.0) == round(min(3.0 * (3000 / 4620) * 0.9, 2.85), 3)
    assert P.tighter_cpt("Local inference: HTTP 500", 3000, 3.0) is None
    assert P.tighter_cpt(OVERRUN, 0, 3.0) is None
    assert P.tighter_cpt(OVERRUN, 9000, 3.0) == 2.7, "an estimate above the count still tightens by a tenth"


def _transport(seen, fail_first=True):
    state = {'calls': 0}

    async def handler(request: httpx.Request):
        body = json.loads(request.content or b'{}')
        seen.append(body)
        state['calls'] += 1
        if fail_first and state['calls'] == 1:
            return httpx.Response(400, json={'error': {'message': OVERRUN, 'type': 'BadRequestError'}})
        if body.get('stream'):
            text = '\n'.join(json.dumps(x) for x in (
                {'message': {'role': 'assistant', 'content': 'ok'}},
                {'done': True, 'done_reason': 'stop', 'prompt_eval_count': 7, 'eval_count': 2})) + '\n'
            return httpx.Response(200, text=text)
        return httpx.Response(200, json={'message': {'role': 'assistant', 'content': 'ok'}, 'done': True,
                                         'done_reason': 'stop', 'prompt_eval_count': 7, 'eval_count': 2})
    return httpx.MockTransport(handler)


def _body():
    old = [{'role': 'user', 'content': 'q%d ' % i + 'x' * 1500} if i % 2 == 0 else
           {'role': 'assistant', 'content': 'a%d ' % i + 'y' * 1500} for i in range(8)]
    return {'model': 'm', 'messages': [{'role': 'system', 'content': 'Assigned queue task.'}, *old,
                                        {'role': 'user', 'content': 'the last question'}]}


def test_an_overrun_is_recapped_tighter_and_answered(tmp_path):
    seen = []
    proxy = P.LocalLLM(lambda: S, transport=_transport(seen), log_path=tmp_path / 'log.jsonl')
    out = asyncio.run(proxy.complete(_body()))
    assert out['choices'][0]['message']['content'] == 'ok'
    assert len(seen) == 2, 'one retry'
    first, second = (sum(len(m.get('content') or '') for m in b['messages']) for b in seen)
    assert second < first, 'the retry sends a shorter prompt'
    assert seen[1]['messages'][-1]['content'] == 'the last question', 'the task and the last turn survive the tighter cap'
    log = [json.loads(l) for l in (tmp_path / 'log.jsonl').read_text().splitlines()]
    assert log[-1]['status'] == 'ok' and log[-1].get('recapped')


def test_a_second_overrun_is_an_error_not_a_loop(tmp_path):
    seen = []

    async def always_overrun(request: httpx.Request):
        seen.append(json.loads(request.content or b'{}'))
        return httpx.Response(400, json={'error': {'message': OVERRUN}})
    proxy = P.LocalLLM(lambda: S, transport=httpx.MockTransport(always_overrun), log_path=tmp_path / 'log.jsonl')
    try:
        asyncio.run(proxy.complete(_body()))
        raise AssertionError('expected Busy')
    except P.Busy as e:
        assert 'maximum context length' in e.message
    assert len(seen) == 2, 'exactly one retry'


def test_streaming_overrun_is_recapped_too(tmp_path):
    seen = []
    proxy = P.LocalLLM(lambda: S, transport=_transport(seen), log_path=tmp_path / 'log.jsonl')

    async def run():
        chunks = []
        async for piece in await proxy.stream(_body() | {'stream': True}):
            chunks.append(piece)
        return ''.join(chunks)
    text = asyncio.run(run())
    assert '"content": "ok"' in text and len(seen) == 2
