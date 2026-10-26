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
   a pool node with api_format 'anthropic' goes to Claude's Messages API instead (prompt caching on, thinking blocks
   replayed on the next tool step) and is translated back the same way;
6. is logged (tokens in/out, wait, duration, fixes) to <hermes dispatch state>/local-llm-calls.jsonl for the
   Providers view.
"""
from __future__ import annotations

import asyncio
from collections import OrderedDict
import contextlib
from datetime import timezone
from email.utils import format_datetime, parsedate_to_datetime
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
CONTEXT_OVERRUN = re.compile(r"maximum context length is (\d+) tokens.*?prompt contains at least (\d+) input tokens", re.I | re.S)


def tighter_cpt(error_text: str, estimated: int, cpt: float) -> float | None:
    """The chars-per-token to re-cap with when the model reports the prompt overran its context, from the count the
    model measured against the proxy's estimate (a tenth tighter for safety); None when the error is something else."""
    m = CONTEXT_OVERRUN.search(error_text or '')
    if not m or estimated <= 0:
        return None
    actual = int(m.group(2))
    ratio = min(1.0, estimated / max(actual, 1))
    return round(min(cpt * ratio * 0.9, cpt * 0.95), 3)


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


def stream_chunks(lines, model: str, cid: str, created: int, *, include_usage: bool = True,
                  translator=None) -> list[str]:
    """Every SSE event for a complete list of Ollama (or, with AnthropicStream, Anthropic) lines."""
    t = (translator or StreamTranslator)(model, cid, created, include_usage)
    out = []
    for line in lines:
        out += t.feed(line)
    return out + t.finish()


# ------------------------------------------------------------------------------------------------ OpenAI <-> Anthropic
# A pool node with api_format = 'anthropic' (Claude through the Messages API, docs/hermes-local-fallback.md). Hermes
# still speaks OpenAI chat completions to the proxy; Ollama/vLLM extras (num_ctx, chat_template_kwargs) never go out.

ANTHROPIC_VERSION = '2023-06-01'
CACHE = {'type': 'ephemeral'}
EFFORTS = ('low', 'medium', 'high', 'xhigh', 'max')
THINKING = ('thinking', 'redacted_thinking')
RATE_LIMIT_COOL_S = 60.0   # an upstream 429 holds every call of that node at least this long (Retry-After when longer):
                           # 2026-10-26 Kimi answered 429 page after page while 16 runs kept retrying it
THINKING_SWITCH_HOSTS = ('api.deepseek.com', 'api.kimi.com', 'api.z.ai')   # OpenAI-format upstreams with a thinking:{type} switch
STOP_REASONS = {'tool_use': 'tool_calls', 'max_tokens': 'length', 'model_context_window_exceeded': 'length',
                'refusal': 'content_filter'}
REPLAY_LIMIT = 4096


def _tool_id(value) -> str:
    """Anthropic tool ids allow [A-Za-z0-9_-] only; ids another model wrote ('functions.x:0') are mapped the same way
    for the call and its result."""
    return re.sub(r'[^A-Za-z0-9_-]', '_', str(value or ''))[:64]


def _anthropic_tool(tool) -> dict | None:
    fn = (tool or {}).get('function') if (tool or {}).get('type', 'function') == 'function' else None
    if not isinstance(fn, dict) or not fn.get('name'):
        return None
    schema = fn.get('parameters') if isinstance(fn.get('parameters'), dict) else {}
    out = {'name': fn['name'], 'input_schema': {'type': 'object', **schema} if schema else
           {'type': 'object', 'properties': {}}}
    if fn.get('description'):
        out['description'] = fn['description']
    return out


def _effort(body: dict, s) -> str | None:
    reasoning = body.get('reasoning')
    value = str(body.get('reasoning_effort') or (reasoning.get('effort') if isinstance(reasoning, dict) else None)
                or s.reasoning_effort or '').lower()
    value = 'low' if value in ('minimal', 'none', 'off') else value
    if value not in EFFORTS:
        return None
    # between_tools (thinking off) is accepted at effort high or below only
    return 'high' if s.enable_thinking is False and value in ('xhigh', 'max') else value


def to_anthropic(body: dict, messages: list[dict], s, *, model: str, max_out: int, replay=None, final=False,
                 tail: int = 0) -> dict:
    """The Messages API request for fixed OpenAI messages. `replay` maps a tool-call id to the assistant turn the
    model wrote (its thinking blocks carry signatures OpenAI messages cannot hold); `tail` messages at the end are the
    proxy's own reminder, kept after the cache breakpoint so the cached prefix matches the next call's."""
    system = '\n\n'.join(m['content'] for m in messages if m['role'] == 'system' and m.get('content'))
    turns: list[list] = []           # [role, blocks]; consecutive turns of one role are merged
    pending: list[str] = []          # tool_use ids of the last assistant turn still waiting for a result
    anchor = None                    # the last block of the last caller message: the conversation's cache breakpoint

    def add(role, blocks):
        if turns and turns[-1][0] == role:
            turns[-1][1].extend(blocks)
        else:
            turns.append([role, list(blocks)])

    def close():                     # every tool_use needs its result in the next user turn
        if pending:
            add('user', [{'type': 'tool_result', 'tool_use_id': i, 'is_error': True,
                          'content': 'No result was recorded for this call.'} for i in pending])
            pending.clear()

    rest = [m for m in messages if m['role'] != 'system']
    for n, m in enumerate(rest):
        role, text = m['role'], m.get('content') or ''
        if role == 'assistant':
            close()
            calls = [c for c in m.get('tool_calls') or [] if isinstance(c, dict)]
            ids = [_tool_id(c.get('id')) or f'call_{n}_{j}' for j, c in enumerate(calls)]
            cached = (replay or {}).get(ids[0]) if ids else None
            if cached and [b.get('id') for b in cached if b.get('type') == 'tool_use'] == ids:
                blocks = [dict(b) for b in cached]
            else:
                blocks = [{'type': 'text', 'text': text}] if text.strip() else []
                for i, c in zip(ids, calls):
                    fn = c.get('function') or {}
                    blocks.append({'type': 'tool_use', 'id': i, 'name': fn.get('name') or 'unknown',
                                   'input': _arguments(fn.get('arguments'))})
            if not blocks:
                continue
            add('assistant', blocks)
            pending = ids
        elif role == 'tool':
            tid = _tool_id(m.get('tool_call_id')) or (pending[0] if pending else '')
            if tid in pending:
                pending.remove(tid)
                blocks = [{'type': 'tool_result', 'tool_use_id': tid, 'content': text or '(no output)'}]
            else:                    # its call was compacted away: keep the result as plain text
                blocks = [{'type': 'text', 'text': f'[tool result {tid or "?"}] {text or "(no output)"}'}]
            add('user', blocks)
        else:
            close()
            blocks = [{'type': 'text', 'text': text if text.strip() else CONTINUE}]
            add('user', blocks)
        if n == len(rest) - 1 - tail:
            anchor = blocks[-1]
    close()
    if not turns or turns[0][0] != 'user':
        turns.insert(0, ['user', [{'type': 'text', 'text': CONTINUE}]])
    if turns[-1][0] != 'user':       # no assistant prefill on current Claude models
        turns.append(['user', [{'type': 'text', 'text': CONTINUE}]])
    for role, blocks in turns:       # tool results first in a user turn, any text after them
        if role == 'user':
            blocks.sort(key=lambda b: b['type'] != 'tool_result')
    # Prompt caching: one breakpoint after tools + system (they render first), one on the conversation so far.
    # Hermes resends the whole growing transcript every step; the next call reads this one's prefix from the cache.
    if anchor is not None and anchor.get('type') not in THINKING:
        anchor['cache_control'] = CACHE
    payload = {'model': model, 'max_tokens': max_out, 'messages': [{'role': r, 'content': b} for r, b in turns]}
    tools = [t for t in map(_anthropic_tool, body.get('tools') or []) if t]
    if system:
        payload['system'] = [{'type': 'text', 'text': system, 'cache_control': CACHE}]
    elif tools:
        tools[-1]['cache_control'] = CACHE
    if tools:
        payload['tools'] = tools
        # Forced tool choice (any/tool) is a 400 on current models: "required" or a named function becomes auto.
        if final or body.get('tool_choice') == 'none':
            payload['tool_choice'] = {'type': 'none'}
        elif body.get('parallel_tool_calls') is False:
            payload['tool_choice'] = {'type': 'auto', 'disable_parallel_tool_use': True}
    stop = body.get('stop')
    stop = [x for x in (stop if isinstance(stop, list) else [stop]) if isinstance(x, str) and x.strip()]
    if stop:
        payload['stop_sequences'] = stop
    # No temperature/top_p (non-default values are a 400) and no "disabled" thinking (a 400 on Sonnet 5.5): thinking
    # stays adaptive unless the node turns it off, which is between_tools.
    if s.enable_thinking is False:
        payload['thinking'] = {'type': 'between_tools'}
    if effort := _effort(body, s):
        payload['output_config'] = {'effort': effort}
    return payload


def strip_thinking(payload: dict) -> dict:
    """The request without replayed thinking blocks (Anthropic refused them: an edited history, another account)."""
    messages = [m | {'content': [b for b in m['content'] if b.get('type') not in THINKING]}
                for m in payload['messages']]
    return payload | {'messages': messages}


def anthropic_usage(u: dict) -> dict:
    """OpenAI usage from Anthropic's; prompt_tokens counts cached and cache-written input too."""
    read, write = int(u.get('cache_read_input_tokens') or 0), int(u.get('cache_creation_input_tokens') or 0)
    p, c = int(u.get('input_tokens') or 0) + read + write, int(u.get('output_tokens') or 0)
    return {'prompt_tokens': p, 'completion_tokens': c, 'total_tokens': p + c,
            'prompt_tokens_details': {'cached_tokens': read},
            'cache_read_input_tokens': read, 'cache_creation_input_tokens': write}


def _anthropic_finish(stop_reason, has_calls: bool) -> str:
    finish = STOP_REASONS.get(stop_reason, 'stop')
    return 'tool_calls' if has_calls and finish == 'stop' else finish


def from_anthropic(resp: dict, model: str, cid: str, created: int) -> dict:
    text, reasoning, calls = [], [], []
    for b in resp.get('content') or []:
        kind = (b or {}).get('type')
        if kind == 'text':
            text.append(b.get('text') or '')
        elif kind == 'thinking' and b.get('thinking'):
            reasoning.append(b['thinking'])
        elif kind == 'tool_use':
            calls.append({'id': b.get('id'), 'type': 'function',
                          'function': {'name': b.get('name'), 'arguments': json.dumps(b.get('input') or {})}})
    message = {'role': 'assistant', 'content': ''.join(text) or (None if calls else '')}
    if calls:
        message['tool_calls'] = calls
    if reasoning:
        message['reasoning_content'] = '\n\n'.join(reasoning)
    return {'id': cid, 'object': 'chat.completion', 'created': created, 'model': model,
            'choices': [{'index': 0, 'message': message,
                         'finish_reason': _anthropic_finish(resp.get('stop_reason'), bool(calls))}],
            'usage': anthropic_usage(resp.get('usage') or {})}


class AnthropicStream:
    """Anthropic Messages SSE lines -> OpenAI SSE events, fed one line at a time (each `data:` line names its event).
    Keeps the finished content blocks, so a tool-calling turn can be replayed with its thinking blocks."""

    def __init__(self, model: str, cid: str, created: int, include_usage: bool = True):
        self.model, self.cid, self.created, self.include_usage = model, cid, created, include_usage
        self.started = self.done = False
        self.blocks: dict = {}       # index -> block being streamed
        self.calls: dict = {}        # block index -> OpenAI tool-call index
        self.content: list = []      # finished blocks, in order
        self.usage: dict = {}
        self.stop = self.error = None

    def _event(self, delta, finish=None):
        return _chunk(self.cid, self.created, self.model, delta, finish)

    def _start(self) -> list[str]:
        if self.started:
            return []
        self.started = True
        return [self._event({'role': 'assistant', 'content': ''})]

    def feed(self, line) -> list[str]:
        out = self._start()
        line = str(line or '')
        if self.done or not line.startswith('data:'):
            return out
        try:
            ev = json.loads(line[5:].strip())
        except ValueError:
            return out
        if not isinstance(ev, dict):
            return out
        kind = ev.get('type')
        if kind == 'message_start':
            self.usage.update({k: v for k, v in ((ev.get('message') or {}).get('usage') or {}).items() if v is not None})
        elif kind == 'content_block_start':
            b = {k: v for k, v in (ev.get('content_block') or {}).items() if v is not None}
            self.blocks[ev.get('index')] = b
            if b.get('type') == 'tool_use':
                k = self.calls[ev.get('index')] = len(self.calls)
                b['input'] = ''
                out.append(self._event({'tool_calls': [{'index': k, 'id': b.get('id'), 'type': 'function',
                                                        'function': {'name': b.get('name'), 'arguments': ''}}]}))
            elif b.get('type') == 'text' and b.get('text'):
                out.append(self._event({'content': b['text']}))
            elif b.get('type') == 'thinking' and b.get('thinking'):
                out.append(self._event({'reasoning_content': b['thinking']}))
        elif kind == 'content_block_delta':
            b, d = self.blocks.get(ev.get('index')), ev.get('delta') or {}
            if b is None:
                return out
            dt = d.get('type')
            if dt == 'text_delta' and d.get('text'):
                b['text'] = b.get('text', '') + d['text']
                out.append(self._event({'content': d['text']}))
            elif dt == 'input_json_delta' and d.get('partial_json'):
                b['input'] += d['partial_json']
                out.append(self._event({'tool_calls': [{'index': self.calls[ev.get('index')],
                                                        'function': {'arguments': d['partial_json']}}]}))
            elif dt == 'thinking_delta' and d.get('thinking'):
                b['thinking'] = b.get('thinking', '') + d['thinking']
                out.append(self._event({'reasoning_content': d['thinking']}))
            elif dt == 'signature_delta':
                b['signature'] = b.get('signature', '') + (d.get('signature') or '')
        elif kind == 'content_block_stop':
            b = self.blocks.pop(ev.get('index'), None)
            if b is not None and b.get('type') == 'tool_use':
                if not b['input'].strip():   # a call without arguments still sends valid JSON
                    out.append(self._event({'tool_calls': [{'index': self.calls[ev.get('index')],
                                                            'function': {'arguments': '{}'}}]}))
                b['input'] = _arguments(b['input'])
            if b is not None:
                self.content.append(b)
        elif kind == 'message_delta':
            self.stop = (ev.get('delta') or {}).get('stop_reason') or self.stop
            self.usage.update({k: v for k, v in (ev.get('usage') or {}).items() if v is not None})
        elif kind == 'message_stop':
            self.done = True
            out.append(self._event({}, _anthropic_finish(self.stop, bool(self.calls))))
        elif kind == 'error':
            self.error = str((ev.get('error') or {}).get('message') or 'Anthropic stream error')[:300]
            self.done = True
            out.append(self._event({}, 'stop'))
        return out

    def finish(self) -> list[str]:
        out = self._start()
        if not self.done:
            self.done = True
            self.error = self.error or 'the model stream ended before it finished'
            out.append(self._event({}, 'stop'))
        if self.include_usage and not self.error:
            out.append('data: ' + json.dumps({'id': self.cid, 'object': 'chat.completion.chunk', 'created': self.created,
                                              'model': self.model, 'choices': [],
                                              'usage': anthropic_usage(self.usage)}) + '\n\n')
        out.append('data: [DONE]\n\n')
        return out

    @property
    def result(self) -> dict:
        return {'usage': None if self.error else anthropic_usage(self.usage), 'error': self.error,
                'tool_calls': len(self.calls), 'content': self.content}


# ------------------------------------------------------------------------------------------------ the proxy

def retry_after_headers(value) -> dict[str, str]:
    """Forward valid delay-seconds or HTTP dates; malformed hints are omitted."""
    text = str(value).strip() if value is not None else ''
    if not text or len(text) > 128 or '\r' in text or '\n' in text:
        return {}
    if re.fullmatch(r'[0-9]+', text):
        text = str(int(text))
    else:
        try:
            date = parsedate_to_datetime(text)
            if date.tzinfo is None:
                return {}
            text = format_datetime(date.astimezone(timezone.utc), usegmt=True)
        except (ValueError, TypeError, OverflowError):
            return {}
    return {'Retry-After': text}


class Busy(Exception):
    def __init__(self, status: int, message: str, retry_after: int | str | None = None):
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
        self.cool_until = 0.0         # the upstream answered 429: no call goes out before this (Busy 429 locally)
        self.last_call_at = 0.0
        self.unloaded_at = 0.0
        self.totals = {'calls': 0, 'ok': 0, 'failed': 0, 'gated': 0, 'busy': 0, 'prompt_tokens': 0,
                       'completion_tokens': 0, 'fixed': 0, 'trimmed': 0}
        self.replay = OrderedDict()   # anthropic: first tool-call id -> the turn's blocks, thinking signatures included

    def remember(self, content) -> None:
        """Keep a tool-calling Claude turn that has thinking blocks, to send it back verbatim on the next step."""
        blocks = [b for b in content or [] if isinstance(b, dict) and (b.get('type') != 'text' or b.get('text'))]
        first = next((b.get('id') for b in blocks if b.get('type') == 'tool_use'), None)
        if not first or not any(b.get('type') in THINKING for b in blocks):
            return
        with self._mu:
            self.replay[first] = blocks
            while len(self.replay) > REPLAY_LIMIT:
                self.replay.popitem(last=False)

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
        if s.api_format == 'anthropic':
            headers = {'anthropic-version': ANTHROPIC_VERSION, **({'x-api-key': key} if key else {})}
        else:
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
    async def prepare(self, body: dict, cpt: float | None = None):
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
                           'results, artifact/job IDs, tests, blockers and the exact next step. Include actual test '
                           'results and returned commit/PR receipts. Publication without a returned receipt remains pending. Do not claim incomplete '
                           'acceptance criteria are resolved. The scheduler retains this report for the next run.'
                           if final else f'Only {budget-used} tool calls remain. Stop exploration and use them to save '
                           'a checkpoint on the assigned request: run the focused verification, use publish_task_changes '
                           'for passing source changes and keep its commit/PR receipt, then record actual results, '
                           'pending job IDs and the next acceptance step. Reuse existing work and do not start duplicate '
                           'jobs. Close only a fully verified request; keep partial work in_progress. Then return your result.')
        # Reserve the reminder's space, then append it AFTER trimming. Otherwise
        # it becomes the sole retained tail group and erases the last tool result
        # precisely when a factual final checkpoint is required.
        reminder = [{'role': 'user', 'content': instruction}] if instruction else []
        cpt = cpt or s.chars_per_token
        reserve = estimate(reminder, None, cpt) if reminder else 0
        capped, info = cap_context(fixed, body.get('tools'), ctx - max_out - MARGIN_TOKENS - reserve, cpt)
        capped += reminder
        info['tokens'] = estimate(capped, body.get('tools'), cpt)
        info['cpt'] = cpt
        if s.api_format == 'openai':
            payload = {k: body[k] for k in ('tools', 'tool_choice', 'parallel_tool_calls', 'temperature',
                       'top_p', 'stop', 'response_format', 'presence_penalty', 'frequency_penalty') if k in body}
            payload.update(model=model, messages=capped, max_tokens=max_out)
            if s.enable_thinking is not None:
                if any(host in (s.upstream or '') for host in THINKING_SWITCH_HOSTS):
                    # DeepSeek's / Kimi's own switch; their models think by default, and a thinking turn must have its
                    # reasoning_content replayed, which Hermes does not send (2026-10-24: every multi-turn run failed)
                    payload['thinking'] = {'type': 'enabled' if s.enable_thinking else 'disabled'}
                else:
                    payload['chat_template_kwargs'] = {'enable_thinking': s.enable_thinking}
            if final:
                payload['tool_choice'] = 'none'
        elif s.api_format == 'anthropic':
            # A trimmed history no longer matches what the thinking blocks were signed against: send none then.
            payload = to_anthropic(body, capped, s, model=model, max_out=max_out, final=final, tail=len(reminder),
                                   replay=None if info['dropped'] or info['cut'] else self.replay)
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
        if s.api_format == 'anthropic':
            meta['replayed_thinking'] = sum(b.get('type') in THINKING for m in payload['messages'] for b in m['content'])
        return s, payload, meta

    async def retry(self, body: dict, s, payload: dict, meta: dict, text: str):
        """(s, payload, meta) for one more try after an error the proxy can fix, else None: the model counted more
        tokens than the proxy estimated (re-cap from its count), or Anthropic refused replayed thinking blocks."""
        if cpt := tighter_cpt(text, meta['est_prompt_tokens'], meta.get('cpt') or s.chars_per_token):
            s, payload, meta = await self.prepare(body, cpt=cpt)
            return s, payload, meta | {'recapped': cpt}
        if s.api_format == 'anthropic' and meta.get('replayed_thinking') and re.search(r'thinking|signature', text, re.I):
            return s, strip_thinking(payload), meta | {'replayed_thinking': 0, 'thinking_stripped': True}
        return None

    def cooling(self) -> None:
        """Refuse locally while the upstream is rate limiting: no request reaches it (or counts against it)."""
        left = self.cool_until - self.clock()
        if left > 0:
            with self._mu:
                self.totals['busy'] += 1
            raise Busy(429, f'Upstream rate limited: holding calls for {left:.0f} s', int(left) + 1)

    def rate_limited(self, status: int, retry_after) -> None:
        if status != 429:
            return
        try:
            wait = float(retry_after)
        except (TypeError, ValueError):
            wait = 0.0
        self.cool_until = max(self.cool_until, self.clock() + max(wait, RATE_LIMIT_COOL_S))

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
            self.cooling()
            lock, waited = await self.acquire(s, gone)
        except Busy as e:
            self.log(meta | {'ts': t0, 'status': 'gated' if 'paused' in e.message else 'busy', 'error': e.message})
            raise
        try:
            async with self._client(s) as client:
                r = await client.post(_path(s), json=payload | {'stream': False})
                if r.status_code >= 400 and (again := await self.retry(body, s, payload, meta, _error_text(r))):
                    s, payload, meta = again
                    r = await client.post(_path(s), json=payload | {'stream': False})
            if r.status_code >= 400:
                self.rate_limited(r.status_code, r.headers.get('Retry-After'))
                raise Busy(502 if r.status_code >= 500 else r.status_code, 'Local inference: ' + _error_text(r),
                           retry_after_headers(r.headers.get('Retry-After')).get('Retry-After'))
            data = r.json()
            cid = 'chatcmpl-' + uuid.uuid4().hex[:24]
            if s.api_format == 'anthropic':
                out = from_anthropic(data, meta['model'], cid, int(t0))
                self.remember(data.get('content'))
            else:
                out = data if s.api_format == 'openai' else from_ollama(data, meta['model'], cid, int(t0))
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
            self.cooling()
            lock, waited = await self.acquire(s, gone)
        except Busy as e:
            self.log(meta | {'ts': t0, 'status': 'gated' if 'paused' in e.message else 'busy', 'error': e.message})
            raise
        include_usage = True
        client = self._client(s)
        try:
            request = client.build_request('POST', _path(s), json=_streaming(s, payload))
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
            again = await self.retry(body, s, payload, meta, text)
            if again:                                        # a fixable refusal: send once more
                s, payload, meta = again
                try:
                    request = client.build_request('POST', _path(s), json=_streaming(s, payload))
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
            if response.status_code >= 400:
                self.rate_limited(response.status_code, response.headers.get('Retry-After'))
                await client.aclose()
                self.release(lock)
                self.log(meta | {'ts': t0, 'status': 'error', 'error': text[:300]})
                raise Busy(502 if response.status_code >= 500 else response.status_code, 'Local inference: ' + text,
                           retry_after_headers(response.headers.get('Retry-After')).get('Retry-After'))
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
        translator = (AnthropicStream if s.api_format == 'anthropic' else StreamTranslator)(
            meta['model'], cid, created, include_usage)

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
                if result.get('content') and not result['error']:
                    self.remember(result['content'])
                self.log(meta | {'ts': t0, 'status': 'error' if result['error'] else 'ok',
                                 'queued_s': round(waited, 2), 'duration_s': round(self.clock() - t0, 2),
                                 'tool_calls': result['tool_calls'], **(result['usage'] or {}),
                                 **({'error': result['error']} if result['error'] else {})})

        return events()


def _streaming(s, payload: dict) -> dict:
    extra = {'stream_options': {'include_usage': True}} if s.api_format == 'openai' else {}
    return payload | {'stream': True} | extra


def _path(s) -> str:
    """The upstream endpoint, relative to `upstream`."""
    return {'openai': 'chat/completions', 'anthropic': 'messages'}.get(s.api_format, '/api/chat')


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
        headers = retry_after_headers(retry_after)
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
