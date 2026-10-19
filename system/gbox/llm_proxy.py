"""OpenAI-compatible proxy in front of the Spark's Ollama: Hermes's local route (docs/hermes-local-fallback.md).

POST /api/llm/local/v1/chat/completions   chat completions (stream or not), tool calls passed through intact
GET  /api/llm/local/v1/models             the configured model and its context limit
GET  /api/llm/local/status                gate, queue and token counters (also read by the Hermes queue tick)

Hermes's custom provider ``spark-local`` points here (loopback callers need no gBox token, so no secret is written
into Hermes's config; anyone else needs the token). Each call:

1. is refused with 503 + Retry-After while the operator plays a game on the Spark (the GPU and memory are theirs);
2. waits for the single model slot (concurrency 1; a bounded queue, 503 when it is full or the wait runs out);
3. gets its messages fixed for the model's chat template: ``developer`` -> ``system``, ``function`` -> ``tool``, only
   one leading system message (later ones become user notes), list content flattened to text, and a minimal user
   turn ("Continue.") when the conversation has none. The last one is the EhmBird failure: Qwen templates raise
   "No user query found in messages" (HTTP 500) when Hermes sends a cron conversation that, after compaction, holds
   only system/assistant/tool messages;
4. is capped to the model's context: whole old turns are dropped (an assistant tool call and its results go together,
   the system prompt and the task's first user message stay), then the longest contents are cut in the middle;
5. is sent to Ollama's native /api/chat (the OpenAI-compatible endpoint cannot set num_ctx, so Ollama would silently
   cut a long Hermes prompt to its default context) and translated back to the OpenAI shape, streaming included;
6. is logged (tokens in/out, wait, duration, fixes) to <hermes dispatch state>/local-llm-calls.jsonl for the
   Providers view.
"""
from __future__ import annotations

import asyncio
import contextlib
import ipaddress
import json
import os
from pathlib import Path
import re
import threading
import time
import uuid

import httpx
from fastapi import Depends, Request

# the queue header names the run's lane; an inbox-lane run may have a larger tool budget (#2399, hermes_local.lane_budget)
LANE = re.compile(r'Assigned queue task: request #\d+ \([0-9a-f]{16}\) \[lane (inbox|favorite)\]')
from fastapi.responses import JSONResponse, StreamingResponse

LOG_NAME = 'local-llm-calls.jsonl'
LOG_MAX_BYTES = 4 << 20
NOTE = '[gBox proxy: {n} earlier message(s) were left out to fit the local model\'s {ctx}-token context.]'
ROLE_MAP = {'developer': 'system', 'function': 'tool'}
ROLES = ('system', 'user', 'assistant', 'tool')
CONTINUE = 'Continue.'
MARGIN_TOKENS = 512


# ------------------------------------------------------------------------------------------------ message fixes

def text_of(content) -> str:
    """OpenAI content (a string or a list of parts) as plain text; images are named, not sent (text-only model)."""
    if content is None:
        return ''
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        out = []
        for part in content:
            if isinstance(part, str):
                out.append(part)
            elif isinstance(part, dict):
                kind = part.get('type')
                if kind in ('text', 'input_text', 'output_text') or 'text' in part:
                    out.append(str(part.get('text') or ''))
                elif kind in ('image_url', 'input_image', 'image'):
                    out.append('[image omitted: the local model reads text only]')
        return '\n'.join(x for x in out if x)
    return json.dumps(content)


def _is_query(message) -> bool:
    """A user turn a chat template accepts as the query (Qwen skips wrapped tool responses and non-string content)."""
    content = message.get('content')
    if message.get('role') != 'user' or not isinstance(content, str) or not content.strip():
        return False
    stripped = content.strip()
    return not (stripped.startswith('<tool_response>') and stripped.endswith('</tool_response>'))


def fix_messages(messages) -> tuple[list[dict], list[str]]:
    """Messages every local chat template accepts, and the list of fixes made (for the call log)."""
    fixes: list[str] = []
    out: list[dict] = []
    for raw in messages or []:
        if not isinstance(raw, dict):
            fixes.append('dropped_non_object')
            continue
        m = dict(raw)
        role = str(m.get('role') or 'user')
        if role in ROLE_MAP:
            fixes.append(f'role_{role}_to_{ROLE_MAP[role]}')
            role = ROLE_MAP[role]
        elif role not in ROLES:
            fixes.append(f'role_{role}_to_user')
            role = 'user'
        m['role'] = role
        if role == 'tool' and not m.get('tool_call_id') and raw.get('name'):
            m['name'] = raw['name']
        if not isinstance(m.get('content'), str):
            if m.get('content') is not None:
                fixes.append('flattened_content')
            m['content'] = text_of(m.get('content'))
        out.append(m)
    # One system message, first: later system turns (Hermes notes after compaction) become user notes.
    head: list[dict] = []
    while out and out[0]['role'] == 'system':
        head.append(out.pop(0))
    if len(head) > 1:
        fixes.append('merged_system')
        head = [{'role': 'system', 'content': '\n\n'.join(m['content'] for m in head if m['content'])}]
    for m in out:
        if m['role'] == 'system':
            fixes.append('late_system_to_user')
            m['role'] = 'user'
            m['content'] = '[system note] ' + m['content']
    out = head + out
    if not any(_is_query(m) for m in out):
        fixes.append('added_user_turn')
        turn = {'role': 'user', 'content': CONTINUE}
        last = out[-1] if out else None
        if last is not None and last['role'] == 'assistant' and not last.get('tool_calls'):
            out.append(turn)                       # a finished reply: the model answers the new turn
        else:
            out.insert(len(head), turn)            # mid tool chain: keep call -> results -> next step adjacent
    return out, fixes


# ------------------------------------------------------------------------------------------------ context cap

def estimate(messages, tools=None, cpt: float = 3.0) -> int:
    size = sum(len(json.dumps(m, ensure_ascii=False)) for m in messages)
    if tools:
        size += len(json.dumps(tools, ensure_ascii=False))
    return int(size / max(cpt, 1.0)) + 4 * len(messages)


def _groups(messages):
    """Units that are dropped together: an assistant tool call with its tool results; anything else alone."""
    groups, i = [], 0
    while i < len(messages):
        g = [messages[i]]
        if messages[i]['role'] == 'assistant' and messages[i].get('tool_calls'):
            while i + 1 < len(messages) and messages[i + 1]['role'] == 'tool':
                i += 1
                g.append(messages[i])
        groups.append(g)
        i += 1
    return groups


def _cut(text: str, keep: int) -> str:
    if len(text) <= keep:
        return text
    keep = max(keep, 200)
    half = keep // 2
    return text[:half] + f'\n...[{len(text) - keep} characters cut by the gBox proxy]...\n' + text[-half:]


def cap_context(messages, tools, budget: int, cpt: float = 3.0) -> tuple[list[dict], dict]:
    """Fit messages (with tool schemas) into `budget` tokens. Returns (messages, {dropped, cut, tokens})."""
    info = {'dropped': 0, 'cut': 0, 'tokens': estimate(messages, tools, cpt)}
    if info['tokens'] <= budget:
        return messages, info
    # Pinned: the system prompt and the task's first user message (cron runs put the assignment there).
    first_user = next((i for i, m in enumerate(messages) if m['role'] == 'user'), None)
    pin = (first_user + 1) if first_user is not None else next(
        (i for i, m in enumerate(messages) if m['role'] != 'system'), len(messages))
    head, groups = [dict(m) for m in messages[:pin]], _groups(messages[pin:])
    dropped = 0
    while len(groups) > 1 and estimate(head + [m for g in groups for m in g], tools, cpt) > budget:
        dropped += len(groups.pop(0))
    rest = [dict(m) for g in groups for m in g]
    if dropped:
        note = NOTE.format(n=dropped, ctx=budget)
        if head and head[0]['role'] == 'system':
            head[0]['content'] = (head[0]['content'] + '\n\n' + note).strip()
        else:
            head.insert(0, {'role': 'system', 'content': note})
    out = head + rest
    cut = 0
    # Still too long (one huge tool result or prompt): cut the longest contents, tool results first.
    for _ in range(64):
        over = estimate(out, tools, cpt) - budget
        if over <= 0:
            break
        order = sorted(range(len(out)), key=lambda i: (out[i]['role'] != 'tool', -len(out[i].get('content') or '')))
        i = order[0]
        text = out[i].get('content') or ''
        if len(text) < 400:
            break
        keep = max(200, len(text) - int(over * cpt) - 200)
        out[i]['content'] = _cut(text, keep)
        cut += 1
    info.update(dropped=dropped, cut=cut, tokens=estimate(out, tools, cpt))
    return out, info


# ------------------------------------------------------------------------------------------------ OpenAI <-> Ollama

def _think(model: str, effort):
    """Ollama's think value for a model, or None to omit it (models without thinking refuse the field)."""
    name = model.lower()
    if name.startswith('gpt-oss'):
        level = str(effort or 'medium').lower()
        return level if level in ('low', 'medium', 'high') else 'medium'
    if name.startswith(('qwen3', 'deepseek-r1', 'qwq')):
        return str(effort or '').lower() not in ('none', 'off', 'minimal', 'false')
    return None


def _arguments(value):
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value) if value.strip() else {}
            return parsed if isinstance(parsed, dict) else {'value': parsed}
        except ValueError:
            return {'raw': value}
    return {} if value is None else {'value': value}


def to_ollama(body: dict, messages: list[dict], s, *, model: str, max_out: int, ctx: int) -> dict:
    names = {}
    msgs = []
    for m in messages:
        out = {'role': m['role'], 'content': m.get('content') or ''}
        if m['role'] == 'assistant':
            calls = []
            for c in m.get('tool_calls') or []:
                fn = (c or {}).get('function') or {}
                names[c.get('id')] = fn.get('name')
                calls.append({'function': {'name': fn.get('name'), 'arguments': _arguments(fn.get('arguments'))}})
            if calls:
                out['tool_calls'] = calls
            thinking = m.get('reasoning_content') or m.get('reasoning')
            if isinstance(thinking, str) and thinking:
                out['thinking'] = thinking
        elif m['role'] == 'tool':
            name = names.get(m.get('tool_call_id')) or m.get('name')
            if name:
                out['tool_name'] = name
        msgs.append(out)
    options = {'num_ctx': ctx, 'num_predict': max_out}
    for key, target in (('temperature', 'temperature'), ('top_p', 'top_p'), ('seed', 'seed'),
                        ('presence_penalty', 'presence_penalty'), ('frequency_penalty', 'frequency_penalty')):
        if body.get(key) is not None:
            options[target] = body[key]
    if body.get('stop'):
        options['stop'] = body['stop'] if isinstance(body['stop'], list) else [body['stop']]
    payload = {'model': model, 'messages': msgs, 'stream': bool(body.get('stream')), 'options': options,
               'keep_alive': s.keep_alive}
    if body.get('tools'):
        payload['tools'] = body['tools']
    reasoning = body.get('reasoning')
    effort = body.get('reasoning_effort') or (reasoning.get('effort') if isinstance(reasoning, dict) else None)
    think = _think(model, effort or s.reasoning_effort)
    if think is not None:
        payload['think'] = think
    fmt = body.get('response_format') or {}
    if isinstance(fmt, dict) and fmt.get('type') == 'json_object':
        payload['format'] = 'json'
    elif isinstance(fmt, dict) and fmt.get('type') == 'json_schema' and isinstance(fmt.get('json_schema'), dict):
        payload['format'] = fmt['json_schema'].get('schema') or 'json'
    return payload


def _openai_calls(calls, start: int = 0) -> list[dict]:
    out = []
    for i, c in enumerate(calls or []):
        fn = (c or {}).get('function') or {}
        args = fn.get('arguments')
        out.append({'index': start + i, 'id': 'call_' + uuid.uuid4().hex[:24], 'type': 'function',
                    'function': {'name': fn.get('name'),
                                 'arguments': args if isinstance(args, str) else json.dumps(args or {})}})
    return out


def usage_of(resp: dict) -> dict:
    p, c = int(resp.get('prompt_eval_count') or 0), int(resp.get('eval_count') or 0)
    return {'prompt_tokens': p, 'completion_tokens': c, 'total_tokens': p + c}


def _finish(resp: dict, has_calls: bool) -> str:
    if has_calls:
        return 'tool_calls'
    return 'length' if resp.get('done_reason') == 'length' else 'stop'


def from_ollama(resp: dict, model: str, cid: str, created: int) -> dict:
    msg = resp.get('message') or {}
    calls = _openai_calls(msg.get('tool_calls'))
    for c in calls:
        c.pop('index', None)
    message = {'role': 'assistant', 'content': msg.get('content') or (None if calls else '')}
    if calls:
        message['tool_calls'] = calls
    if msg.get('thinking'):
        message['reasoning_content'] = msg['thinking']
    return {'id': cid, 'object': 'chat.completion', 'created': created, 'model': model,
            'choices': [{'index': 0, 'message': message, 'finish_reason': _finish(resp, bool(calls))}],
            'usage': usage_of(resp)}


def _chunk(cid, created, model, delta, finish=None) -> str:
    data = {'id': cid, 'object': 'chat.completion.chunk', 'created': created, 'model': model,
            'choices': [{'index': 0, 'delta': delta, 'finish_reason': finish}]}
    return 'data: ' + json.dumps(data) + '\n\n'


class StreamTranslator:
    """Ollama NDJSON lines -> OpenAI SSE events, fed one line at a time as they arrive from the network."""

    def __init__(self, model: str, cid: str, created: int, include_usage: bool = True):
        self.model, self.cid, self.created, self.include_usage = model, cid, created, include_usage
        self.started = self.done = False
        self.calls_sent = 0
        self.final: dict = {}

    def _start(self) -> list[str]:
        if self.started:
            return []
        self.started = True
        return [_chunk(self.cid, self.created, self.model, {'role': 'assistant', 'content': ''})]

    def feed(self, line) -> list[str]:
        out = self._start()
        if self.done or not line or not str(line).strip():
            return out
        try:
            part = json.loads(line)
        except ValueError:
            return out
        if not isinstance(part, dict):
            return out
        if part.get('error'):
            self.final, self.done = {'error': str(part['error'])[:300]}, True
            out.append(_chunk(self.cid, self.created, self.model, {}, 'stop'))
            return out
        msg = part.get('message') or {}
        if msg.get('thinking'):
            out.append(_chunk(self.cid, self.created, self.model, {'reasoning_content': msg['thinking']}))
        if msg.get('content'):
            out.append(_chunk(self.cid, self.created, self.model, {'content': msg['content']}))
        if msg.get('tool_calls'):
            calls = _openai_calls(msg['tool_calls'], self.calls_sent)
            self.calls_sent += len(calls)
            out.append(_chunk(self.cid, self.created, self.model, {'tool_calls': calls}))
        if part.get('done'):
            self.final, self.done = part, True
            out.append(_chunk(self.cid, self.created, self.model, {}, _finish(part, self.calls_sent > 0)))
        return out

    def finish(self) -> list[str]:
        out = self._start()
        if not self.done:
            self.done = True
            self.final = self.final or {'error': 'the model stream ended before it finished'}
            out.append(_chunk(self.cid, self.created, self.model, {}, 'stop'))
        if self.include_usage and not self.final.get('error'):
            out.append('data: ' + json.dumps({'id': self.cid, 'object': 'chat.completion.chunk', 'created': self.created,
                                              'model': self.model, 'choices': [],
                                              'usage': usage_of(self.final)}) + '\n\n')
        out.append('data: [DONE]\n\n')
        return out

    @property
    def result(self) -> dict:
        error = self.final.get('error')
        return {'usage': None if error or not self.final else usage_of(self.final), 'error': error,
                'tool_calls': self.calls_sent}


def stream_chunks(lines, model: str, cid: str, created: int, *, include_usage: bool = True) -> list[str]:
    """Every SSE event for a complete list of Ollama lines (tests and simple callers)."""
    t = StreamTranslator(model, cid, created, include_usage)
    out = []
    for line in lines:
        out += t.feed(line)
    return out + t.finish()


# ------------------------------------------------------------------------------------------------ the proxy

class Busy(Exception):
    def __init__(self, status: int, message: str, retry_after: int | None = None):
        super().__init__(message)
        self.status, self.message, self.retry_after = status, message, retry_after


class ResizableSlots:
    """Loop-local permits: lowering capacity drains work without cancelling it."""

    def __init__(self, capacity):
        self.capacity, self.used = capacity, 0
        self.waiters = set()

    def locked(self):
        return self.used >= self.capacity

    def resize(self, capacity):
        self.capacity = capacity
        self._wake()

    def _wake(self):
        for waiter in self.waiters:
            if not waiter.done():
                waiter.set_result(None)

    async def acquire(self):
        while self.locked():
            waiter = asyncio.get_running_loop().create_future()
            self.waiters.add(waiter)
            try:
                await waiter
            finally:
                self.waiters.discard(waiter)
        self.used += 1
        return True

    def release(self):
        self.used -= 1
        self._wake()


class LocalLLM:
    """The single-slot proxy. `settings` returns HermesLocalConfig; `gate` returns why calls must wait (the operator
    plays on the Spark) or None; `transport` is an httpx transport for tests."""

    def __init__(self, settings, gate=None, log_path: Path | None = None, transport=None, clock=time.time):
        self.settings, self.gate, self.transport, self.clock = settings, gate or (lambda: None), transport, clock
        self.log_path = log_path
        self._slot = None
        self._mu = threading.Lock()
        self.waiting = 0
        self.active = 0
        self.last_call_at = 0.0
        self.unloaded_at = 0.0
        self.totals = {'calls': 0, 'ok': 0, 'failed': 0, 'gated': 0, 'busy': 0, 'prompt_tokens': 0,
                       'completion_tokens': 0, 'fixed': 0, 'trimmed': 0}

    def _lock(self) -> ResizableSlots:
        """Inference capacity, bound to the serving event loop (uvicorn runs one)."""
        loop = asyncio.get_running_loop()
        with self._mu:
            if self._slot is None or self._slot[0] is not loop:
                self._slot = (loop, ResizableSlots(self.settings().max_parallel_jobs))
            self._slot[1].resize(self.settings().max_parallel_jobs)
            return self._slot[1]

    def _client(self, s) -> httpx.AsyncClient:
        timeout = httpx.Timeout(s.request_timeout_s, connect=10.0)
        key = os.environ.get(s.upstream_key_env, '') if s.upstream_key_env else ''
        headers = {'Authorization': 'Bearer ' + key} if key else {}
        return httpx.AsyncClient(base_url=s.upstream.rstrip('/') + '/', timeout=timeout,
                                 transport=self.transport, headers=headers)

    # -- logging
    def log(self, record: dict) -> None:
        status = record.get('status')
        with self._mu:
            self.totals['calls'] += status in ('ok', 'error')
            self.totals['ok'] += status == 'ok'
            self.totals['failed'] += status == 'error'
            self.totals['gated'] += status == 'gated'
            self.totals['busy'] += status == 'busy'
            self.totals['prompt_tokens'] += int(record.get('prompt_tokens') or 0)
            self.totals['completion_tokens'] += int(record.get('completion_tokens') or 0)
            self.totals['fixed'] += bool(record.get('fixes'))
            self.totals['trimmed'] += bool(record.get('dropped') or record.get('cut'))
        if not self.log_path:
            return
        try:
            self.log_path.parent.mkdir(parents=True, exist_ok=True)
            if self.log_path.exists() and self.log_path.stat().st_size > LOG_MAX_BYTES:
                self.log_path.replace(self.log_path.with_suffix('.jsonl.1'))
            with self.log_path.open('a', encoding='utf-8') as f:
                f.write(json.dumps(record) + '\n')
        except OSError:
            pass

    # -- gate
    def gate_reason(self):
        if not self.settings().shared_with_games:
            return None
        try:
            return self.gate()
        except Exception:                          # noqa: BLE001 - an unknown state never blocks Hermes forever
            return None

    async def _maybe_unload(self, s):
        """The operator started playing: free the GPU memory the model holds (Ollama keep_alive 0), once."""
        if s.api_format != 'ollama' or not self.last_call_at or self.unloaded_at >= self.last_call_at:
            return
        self.unloaded_at = self.clock()
        with contextlib.suppress(Exception):
            async with self._client(s) as client:
                await client.post('/api/generate', json={'model': s.model, 'keep_alive': 0}, timeout=20)

    def status(self) -> dict:
        s = self.settings()
        with self._mu:
            totals = dict(self.totals)
        return {'enabled': s.enabled, 'model': s.model, 'provider': s.provider, 'upstream': s.upstream,
                'host_name': s.host_name, 'api_format': s.api_format, 'capacity': s.max_parallel_jobs,
                'context_tokens': _ctx(s), 'active': self.active, 'waiting': self.waiting,
                'queue_limit': s.queue_limit, 'gated': self.gate_reason(), 'last_call_at': self.last_call_at or None,
                'totals_since_start': totals}

    # -- one call
    async def prepare(self, body: dict):
        s = self.settings()
        if not s.enabled:
            raise Busy(503, 'The local route is switched off ([hermes.local] enabled = false)', s.retry_after_s)
        messages = body.get('messages')
        if not isinstance(messages, list) or not messages:
            raise Busy(400, 'messages must be a non-empty list')
        model = s.model  # the route has one model; a different name in the call is answered by it
        ctx = _ctx(s, model)
        asked = body.get('max_completion_tokens') or body.get('max_tokens')
        max_out = min(int(asked), s.max_output_tokens) if isinstance(asked, int) and asked > 0 else s.max_output_tokens
        fixed, fixes = fix_messages(messages)
        # Queue runs must yield a result instead of consuming a slot indefinitely.
        # Count before context trimming so the proxy cannot erase its own budget.
        queued = any('Assigned queue task: request #' in str(m.get('content', '')) for m in messages if isinstance(m, dict))
        from . import hermes_local, hermes_run_budget
        usage = await asyncio.to_thread(hermes_run_budget.measure, messages, s.proxy_url) if queued else None
        used = usage['attempts'] if usage else 0
        lane = next((m.group(1) for m in (LANE.search(str(msg.get('content', ''))) for msg in messages
                                          if isinstance(msg, dict)) if m), None) if queued else None
        budget = hermes_local.lane_budget(s, lane)
        final = queued and used >= budget
        instruction = None
        if queued and used >= budget - 6:
            instruction = ('This run has reached its tool budget. Return a factual final checkpoint now: verified '
                           'results, artifact/job IDs, tests, blockers and the exact next step. Do not claim incomplete '
                           'acceptance criteria are resolved. The scheduler retains this report for the next run.'
                           if final else f'Only {budget-used} tool calls remain. Stop exploration and use them to save '
                           'a checkpoint on the assigned request, record tests and blockers, then return your result.')
        # Reserve the reminder's space, then append it AFTER trimming. Otherwise
        # it becomes the sole retained tail group and erases the last tool result
        # precisely when a factual final checkpoint is required.
        reminder = [{'role': 'user', 'content': instruction}] if instruction else []
        reserve = estimate(reminder, None, s.chars_per_token) if reminder else 0
        capped, info = cap_context(fixed, body.get('tools'), ctx - max_out - MARGIN_TOKENS - reserve, s.chars_per_token)
        capped += reminder
        info['tokens'] = estimate(capped, body.get('tools'), s.chars_per_token)
        if s.api_format == 'openai':
            payload = {k: body[k] for k in ('tools', 'tool_choice', 'parallel_tool_calls', 'temperature',
                       'top_p', 'stop', 'response_format', 'presence_penalty', 'frequency_penalty') if k in body}
            payload.update(model=model, messages=capped, max_tokens=max_out)
            if s.enable_thinking is not None:
                payload['chat_template_kwargs'] = {'enable_thinking': s.enable_thinking}
            if final:
                payload['tool_choice'] = 'none'
        else:
            payload = to_ollama(body, capped, s, model=model, max_out=max_out, ctx=ctx)
            if final:
                payload.pop('tools', None)
        meta = {'model': model, 'provider': s.provider, 'host_name': s.host_name,
                'upstream': s.upstream, 'api_format': s.api_format,
                'fixes': sorted(set(fixes)), 'dropped': info['dropped'], 'cut': info['cut'],
                'est_prompt_tokens': info['tokens'], 'stream': bool(body.get('stream')),
                'tools': len(body.get('tools') or []), 'queue_tool_calls': used if queued else None,
                'budget_final': final, 'queue_budget': usage}
        return s, payload, meta

    async def acquire(self, s, gone=None):
        reason = await asyncio.to_thread(self.gate_reason)
        if reason:
            await self._maybe_unload(s)
            raise Busy(503, f'Local model paused: {reason}', s.retry_after_s)
        if self.waiting >= s.queue_limit:
            raise Busy(503, f'Local model busy: {self.waiting} calls already waiting', 30)
        lock = self._lock()
        self.waiting += 1
        start = self.clock()
        try:
            await asyncio.wait_for(lock.acquire(), timeout=s.queue_wait_s)
        except asyncio.TimeoutError:
            raise Busy(503, f'Local model busy for {int(s.queue_wait_s)} s', 60) from None
        finally:
            self.waiting -= 1
        try:
            # Worker/session snapshots may wait on SQLite. Keep the serving loop responsive.
            reason = await asyncio.to_thread(self.gate_reason)
        except BaseException:
            lock.release()
            raise
        if reason:
            lock.release()
            raise Busy(503, f'Local model paused: {reason}', s.retry_after_s)
        self.active += 1
        if gone is not None and await gone():          # the caller timed out while it waited: skip the GPU work
            self.release(lock)
            raise Busy(499, 'The caller went away while it waited for the local model')
        return lock, self.clock() - start

    def release(self, lock):
        self.active -= 1
        self.last_call_at = self.clock()
        with contextlib.suppress(RuntimeError):
            lock.release()

    async def complete(self, body: dict, gone=None) -> dict:
        """A non-streaming call: the OpenAI chat.completion dict (raises Busy for an HTTP error answer)."""
        t0 = self.clock()
        s, payload, meta = await self.prepare(body)
        try:
            lock, waited = await self.acquire(s, gone)
        except Busy as e:
            self.log(meta | {'ts': t0, 'status': 'gated' if 'paused' in e.message else 'busy', 'error': e.message})
            raise
        try:
            async with self._client(s) as client:
                r = await client.post('chat/completions' if s.api_format == 'openai' else '/api/chat',
                                      json=payload | {'stream': False})
            if r.status_code >= 400:
                raise Busy(502 if r.status_code >= 500 else r.status_code, 'Local inference: ' + _error_text(r))
            data = r.json()
            out = data if s.api_format == 'openai' else from_ollama(
                data, meta['model'], 'chatcmpl-' + uuid.uuid4().hex[:24], int(t0))
            if not isinstance(out, dict) or not out.get('choices') or 'message' not in out['choices'][0]:
                raise Busy(502, 'Local inference returned an invalid completion')
            self.log(meta | {'ts': t0, 'status': 'ok', 'queued_s': round(waited, 2),
                             'duration_s': round(self.clock() - t0, 2), **(out.get('usage') or {}),
                             'tool_calls': len(out['choices'][0]['message'].get('tool_calls') or [])})
            return out
        except Busy as e:
            self.log(meta | {'ts': t0, 'status': 'error', 'error': e.message[:300]})
            raise
        except (httpx.HTTPError, ValueError) as e:
            self.log(meta | {'ts': t0, 'status': 'error', 'error': type(e).__name__})
            raise Busy(502, f'Local inference unreachable or invalid answer ({type(e).__name__})') from None
        finally:
            self.release(lock)

    async def stream(self, body: dict, gone=None):
        """A streaming call: (async iterator of SSE text). Gate/queue errors raise Busy before the first byte."""
        t0 = self.clock()
        s, payload, meta = await self.prepare(body)
        try:
            lock, waited = await self.acquire(s, gone)
        except Busy as e:
            self.log(meta | {'ts': t0, 'status': 'gated' if 'paused' in e.message else 'busy', 'error': e.message})
            raise
        include_usage = True
        client = self._client(s)
        try:
            if s.api_format == 'openai':
                payload['stream_options'] = {'include_usage': True}
            request = client.build_request('POST', 'chat/completions' if s.api_format == 'openai' else '/api/chat',
                                            json=payload | {'stream': True})
            response = await client.send(request, stream=True)
        except httpx.HTTPError as e:
            await client.aclose()
            self.release(lock)
            self.log(meta | {'ts': t0, 'status': 'error', 'error': type(e).__name__})
            raise Busy(502, f'Local inference unreachable ({type(e).__name__})') from None
        if response.status_code >= 400:
            await response.aread()
            text = _error_text(response)
            await response.aclose()
            await client.aclose()
            self.release(lock)
            self.log(meta | {'ts': t0, 'status': 'error', 'error': text[:300]})
            raise Busy(502 if response.status_code >= 500 else response.status_code, 'Local inference: ' + text)
        if s.api_format == 'openai':
            async def openai_events():
                usage, calls, done, error = {}, set(), False, None
                try:
                    async for line in response.aiter_lines():
                        if line.startswith('data: '):
                            value = line[6:]
                            if value == '[DONE]':
                                done = True
                            else:
                                part = json.loads(value)
                                if part.get('error'):
                                    error = 'Upstream inference returned a stream error'
                                usage = part.get('usage') or usage
                                for choice in part.get('choices') or []:
                                    for call in (choice.get('delta') or {}).get('tool_calls') or []:
                                        calls.add((choice.get('index', 0), call.get('index', 0)))
                        yield line + '\n'
                finally:
                    await response.aclose()
                    await client.aclose()
                    self.release(lock)
                    error = error or (None if done else 'Local inference stream interrupted before completion')
                    self.log(meta | {'ts': t0, 'status': 'error' if error else 'ok',
                                     'queued_s': round(waited, 2), 'duration_s': round(self.clock() - t0, 2),
                                     'tool_calls': len(calls), **usage, **({'error': error} if error else {})})
            return openai_events()
        cid, created = 'chatcmpl-' + uuid.uuid4().hex[:24], int(t0)
        translator = StreamTranslator(meta['model'], cid, created, include_usage)

        async def events():
            try:
                async for line in response.aiter_lines():
                    for event in translator.feed(line):
                        yield event
                    if translator.done:
                        break
                for event in translator.finish():
                    yield event
            finally:
                await response.aclose()
                await client.aclose()
                self.release(lock)
                result = translator.result
                self.log(meta | {'ts': t0, 'status': 'error' if result['error'] else 'ok',
                                 'queued_s': round(waited, 2), 'duration_s': round(self.clock() - t0, 2),
                                 'tool_calls': result['tool_calls'], **(result['usage'] or {}),
                                 **({'error': result['error']} if result['error'] else {})})

        return events()


def _ctx(s, model: str | None = None) -> int:
    return int(s.contexts.get(model or s.model) or s.context_tokens)


def _error_text(response) -> str:
    try:
        data = response.json()
        if isinstance(data, dict) and data.get('error'):
            return str(data['error'])[:500]
    except ValueError:
        pass
    return f'HTTP {response.status_code}'


# ------------------------------------------------------------------------------------------------ routes

def _loopback(request) -> bool:
    host = (request.client.host if request.client else '') or ''
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return host in ('localhost', 'testclient')


def log_path() -> Path:
    from . import hermes_delivery
    return hermes_delivery.state_dir() / LOG_NAME


def read_log(since: float, path: Path | None = None, limit_bytes: int = 8 << 20) -> list[dict]:
    """Call records at or after `since` (the current file and its one rotation)."""
    path = path or log_path()
    out = []
    for p in (path.with_suffix('.jsonl.1'), path):
        try:
            with p.open('rb') as f:
                size = p.stat().st_size
                if size > limit_bytes:
                    f.seek(size - limit_bytes)
                    f.readline()
                for raw in f:
                    try:
                        rec = json.loads(raw)
                    except ValueError:
                        continue
                    if isinstance(rec, dict) and (rec.get('ts') or 0) >= since:
                        out.append(rec)
        except OSError:
            continue
    return out


def summarize(records: list[dict]) -> dict:
    ok = [r for r in records if r.get('status') == 'ok']
    return {'calls': sum(r.get('status') in ('ok', 'error') for r in records), 'calls_ok': len(ok),
            'calls_failed': sum(r.get('status') == 'error' for r in records),
            'refused_while_playing': sum(r.get('status') == 'gated' for r in records),
            'refused_busy': sum(r.get('status') == 'busy' for r in records),
            'prompt_tokens': sum(int(r.get('prompt_tokens') or 0) for r in ok),
            'completion_tokens': sum(int(r.get('completion_tokens') or 0) for r in ok),
            'tokens': sum(int(r.get('total_tokens') or 0) for r in ok),
            'fixed_calls': sum(bool(r.get('fixes')) for r in records),
            'trimmed_calls': sum(bool(r.get('dropped') or r.get('cut')) for r in records),
            'wall_s': round(sum(float(r.get('duration_s') or 0) for r in ok), 1),
            'last_call_at': max((r.get('ts') or 0 for r in records), default=None) or None}


def routes(app, config, auth, gate=None, transport=None) -> LocalLLM:
    def settings():
        s = config.hermes.local
        if not s.proxy_url:
            s = s.model_copy(update={'proxy_url': f'http://127.0.0.1:{config.api_port}/api/llm/local/v1'})
        return s

    proxy = LocalLLM(settings, gate, log_path=None if os.environ.get('GBOX_LOCAL_LLM_NOLOG') else log_path(),
                     transport=transport)
    app.state.local_llm = proxy

    def local_auth(request: Request) -> str:
        """Hermes on the Spark calls from loopback without the gBox token; any other caller needs it."""
        if _loopback(request):
            return 'hermes-local'
        return auth(request)

    def error(status, message, retry_after=None):
        headers = {'Retry-After': str(int(retry_after))} if retry_after else {}
        # Not "rate_limit": Hermes's failure classifier would cool the local route for a wait that is the operator's game.
        kind = 'service_unavailable' if status == 503 else 'api_error'
        return JSONResponse({'error': {'message': message, 'type': kind, 'code': status}}, status_code=status,
                            headers=headers)

    @app.post('/api/llm/local/v1/chat/completions')
    async def local_chat(request: Request, actor=Depends(local_auth)):
        if config.hermes.local.nodes:
            return await app.state.local_pool_chat(config.hermes.local.host_name, request, actor)
        try:
            body = await request.json()
        except ValueError:
            return error(400, 'invalid JSON body')
        if not isinstance(body, dict):
            return error(400, 'the body must be a JSON object')
        try:
            if body.get('stream'):
                events = await proxy.stream(body, request.is_disconnected)
                return StreamingResponse(events, media_type='text/event-stream',
                                         headers={'Cache-Control': 'no-store', 'X-Accel-Buffering': 'no'})
            return await proxy.complete(body, request.is_disconnected)
        except Busy as e:
            return error(e.status, e.message, e.retry_after)

    @app.get('/api/llm/local/v1/models')
    def local_models(actor=Depends(local_auth)):
        s = settings()
        return {'object': 'list', 'data': [{'id': s.model, 'object': 'model', 'owned_by': 'gbox-spark',
                                            'context_length': _ctx(s), 'max_model_len': _ctx(s)}]}

    @app.get('/api/llm/local/status')
    def local_status(actor=Depends(local_auth)):
        return proxy.status()

    from . import hermes_pool
    hermes_pool.routes(app, config, auth, gate)
    return proxy
