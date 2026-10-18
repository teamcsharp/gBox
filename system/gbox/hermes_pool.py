"""Local inference pool: per-machine switches, admission, health and durable task routing.

The prime Spark owns the queue, workspaces and evidence. A model server only performs
inference, so a checkpoint remains usable when the next run moves to another machine.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import json
import os
import re
import subprocess
import threading
import time

import httpx
from fastapi import Depends, HTTPException, Request
from pydantic import BaseModel, Field

from . import hermes_delivery as D, hermes_local as L
from .config import HermesLocalConfig

_HEALTH = {}
_LOCK = threading.Lock()
_PROXIES = {}
_GATE = lambda: None
CONCURRENCY_CHOICES = (4, 8, 12, 16, 24, 32)


class PoolSwitch(BaseModel):
    enabled: bool


class PoolCapacity(BaseModel):
    capacity: int = Field(ge=4, le=32, strict=True)


def pool_limit():
    return int(_state().get('pool_max_parallel_jobs', L.settings().pool_max_parallel_jobs))


def _sync_cron_capacity(capacity):
    from . import hermes_task_mode as M
    from . import hermes_build_supervisor
    from . import hermes_result_review
    capacity += int(bool(hermes_build_supervisor.status().get('enabled')))
    capacity += int(bool(hermes_result_review.config().get('enabled')))
    if (M._config().get('cron') or {}).get('max_parallel_jobs') == capacity:
        return
    try:
        result = subprocess.run([str(M._cli()), 'config', 'set', 'cron.max_parallel_jobs', str(capacity)],
                                capture_output=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        raise RuntimeError('Could not update Hermes task capacity') from None
    if result.returncode:
        raise RuntimeError('Could not update Hermes task capacity')


def set_capacity(name, capacity):
    nodes = node_settings()
    if name not in nodes:
        raise KeyError(name)
    if nodes[name].shared_with_games:
        raise ValueError('The prime Spark keeps its reserved task capacity')
    if type(capacity) is not int or capacity not in CONCURRENCY_CHOICES:
        raise ValueError('Choose 4, 8, 12, 16, 24 or 32 tasks')
    with D.locked('local-nodes'):
        nodes = node_settings()
        limit = min(64, sum(capacity if n == name else s.max_parallel_jobs for n, s in nodes.items()))
        # Update the scheduler before exposing the new admission limit. Existing
        # runs keep their slots when the limit is reduced; nothing is cancelled.
        _sync_cron_capacity(limit)
        data = _state()
        row = data.setdefault('nodes', {}).setdefault(name, {})
        row.update(max_parallel_jobs=capacity, changed_at=time.time())
        data['pool_max_parallel_jobs'] = limit
        path = D.state_dir() / 'local-nodes.json'
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_suffix('.tmp');temp.write_text(json.dumps(data, indent=2));temp.replace(path)
    return {'name': name, 'capacity': capacity, 'pool_capacity': limit}


def configured():
    return bool(L.settings().nodes)


def _state():
    path = D.state_dir() / 'local-nodes.json'
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return {'nodes': {}}


def node_settings(base=None):
    base = base or L.settings()
    state = _state().get('nodes', {})
    out = {}
    for name, values in base.nodes.items():
        if not re.fullmatch(r'[a-zA-Z0-9_-]{1,40}', name):
            continue
        row = base.model_dump(exclude={'nodes'}) | values
        row.update(nodes={}, host_name=name,
                   proxy_url=base.proxy_url.rstrip('/').removesuffix('/v1') + f'/nodes/{name}/v1')
        # Endpoint/model configuration cannot be changed by an enable-switch request.
        overrides = state.get(name, {})
        row.update({k: overrides[k] for k in ('enabled', 'model', 'upstream', 'max_parallel_jobs') if k in overrides})
        if overrides.get('maintenance'):
            row['enabled'] = False
        out[name] = HermesLocalConfig.model_validate(row)
    return out


def set_node(name, enabled):
    if name not in node_settings():
        raise KeyError(name)
    with D.locked('local-nodes'):
        data = _state()
        row = data.setdefault('nodes', {}).setdefault(name, {})
        row.update(enabled=bool(enabled), changed_at=time.time())
        path = D.state_dir() / 'local-nodes.json'
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_suffix('.tmp');temp.write_text(json.dumps(data, indent=2));temp.replace(path)
    with _LOCK:
        _HEALTH.pop(name, None)
    return {'name': name, **row}


def maintenance(name, active):
    with D.locked('local-nodes'):
        data = _state()
        data.setdefault('nodes', {}).setdefault(name, {})['maintenance'] = bool(active)
        path = D.state_dir() / 'local-nodes.json'
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_suffix('.tmp');temp.write_text(json.dumps(data, indent=2));temp.replace(path)
    with _LOCK:
        _HEALTH.pop(name, None)


def _metric(text, name):
    values = re.findall(r'^vllm:' + re.escape(name) + r'(?:\{[^\n]*\})?\s+([0-9.eE+-]+)', text, re.M)
    return sum(float(v) for v in values) if values else None


def health(name, s, *, refresh=False):
    now = time.time()
    key = (s.upstream, s.model, s.enabled)
    with _LOCK:
        cached = _HEALTH.get(name)
        if cached and cached['key'] == key and not refresh and now - cached['at'] < 10:
            return dict(cached['value'])
    value = {'online': False, 'capable': False, 'reason': 'Disabled', 'checked_at': now}
    if s.enabled:
        try:
            if s.shared_with_games and (reason := _GATE()):
                value['reason'] = reason
            else:
                if s.shared_with_games:
                    import psutil
                    free = psutil.virtual_memory().available
                    value['memory_available_bytes'] = free
                    if free < 12 * 1024**3:
                        raise RuntimeError('Less than 12 GiB memory headroom on the prime Spark')
                token = os.environ.get(s.upstream_key_env, '') if s.upstream_key_env else ''
                with httpx.Client(timeout=3, headers={'Authorization': 'Bearer '+token} if token else {}) as client:
                    url = s.upstream.rstrip('/') + ('/models' if s.api_format == 'openai' else '/api/tags')
                    response = client.get(url);response.raise_for_status();data = response.json()
                    models = [m.get('id') for m in data.get('data', [])] if s.api_format == 'openai' else [
                        m.get('name') for m in data.get('models', [])]
                    value.update(online=True, capable=s.model in models,
                                 reason='Ready' if s.model in models else 'Configured model is not served')
                    if s.api_format == 'openai':
                        try:
                            metrics = client.get(s.upstream.rstrip('/').removesuffix('/v1') + '/metrics')
                            if metrics.status_code == 200:
                                value.update(running_requests=_metric(metrics.text, 'num_requests_running'),
                                    waiting_requests=_metric(metrics.text, 'num_requests_waiting'),
                                    kv_cache_fraction=_metric(metrics.text, 'kv_cache_usage_perc'))
                                if (value.get('kv_cache_fraction') or 0) >= .9:
                                    value.update(capable=False, reason='KV cache at 90%; waiting for headroom')
                        except httpx.HTTPError:
                            pass  # models API is sufficient for readiness; metrics are optional
        except (httpx.HTTPError, ValueError, RuntimeError) as exc:
            value['reason'] = str(exc)[:160] if isinstance(exc, RuntimeError) else type(exc).__name__
    with _LOCK:
        _HEALTH[name] = {'key': key, 'at': now, 'value': value}
    return value


def snapshot():
    settings = node_settings()
    with ThreadPoolExecutor(max_workers=max(1, min(4, len(settings)))) as pool:
        checks = dict(zip(settings, pool.map(lambda pair: health(*pair), settings.items())))
    from . import llm_proxy
    records = llm_proxy.read_log(time.time() - 86400)
    nodes = []
    for name, s in settings.items():
        proxy = _PROXIES.get(name)
        row = {'name': name, 'provider': s.provider, 'model': s.model, 'upstream': s.upstream,
               'api_format': s.api_format, 'enabled': s.enabled, 'capacity': s.max_parallel_jobs,
               'primary': s.shared_with_games, 'allow_large_tasks': s.allow_large_tasks, **checks[name]}
        if not s.shared_with_games:
            row['concurrency_choices'] = CONCURRENCY_CHOICES
        row.update(llm_proxy.summarize([r for r in records if r.get('host_name') == name]))
        if proxy:
            row.update(active=proxy.active, waiting=proxy.waiting)
        nodes.append(row)
    from . import hermes_models
    return {'enabled': L.settings().enabled, 'nodes': nodes, 'model_management': hermes_models.status(), 'capacity': min(pool_limit(),
            sum(n['capacity'] for n in nodes if n['enabled'] and n['capable'])),
            'policy': 'Prime Spark when free; dedicated Spark handles the larger concurrent backlog',
            'checkpoint_owner': 'lilspark'}


def assignments(nodes, items, reserved):
    """Free per-node agent slots, bounded by the global run limit. Unknown legacy claims still consume capacity."""
    active = [i for i in items.values() if i.get('job_id') in reserved]
    slots = []
    for node in sorted(nodes, key=lambda n: not n.get('primary')):
        if not node.get('enabled') or not node.get('capable'):
            continue
        used = sum(i.get('inference_node') == node['name'] for i in active)
        slots.extend([node] * max(0, node['capacity'] - used))
    limit = min(pool_limit(),
                sum(n['capacity'] for n in nodes if n.get('enabled') and n.get('capable')))
    return slots[:max(0, limit - len(reserved))], limit


def register_providers():
    from . import hermes_task_mode as M
    for s in node_settings().values():
        L.register_provider(M._home() / 'config.yaml', s)


def routes(app, config, auth, gate):
    global _GATE
    _GATE = gate or (lambda: None)
    from .llm_proxy import LocalLLM, Busy, _loopback
    from fastapi.responses import JSONResponse, StreamingResponse

    def access(request: Request):
        return 'hermes-local' if _loopback(request) else auth(request)

    def proxy(name):
        if name not in node_settings():
            raise HTTPException(404, 'Unknown inference machine')
        if name not in _PROXIES:
            from .llm_proxy import log_path
            _PROXIES[name] = LocalLLM(lambda: node_settings()[name], gate=_GATE, log_path=log_path())
        return _PROXIES[name]

    @app.get('/api/hermes/local/nodes')
    def nodes(actor=Depends(auth)):
        return snapshot()

    @app.post('/api/hermes/local/nodes/{name}')
    def switch(name: str, body: PoolSwitch, actor=Depends(auth)):
        try:
            return set_node(name, body.enabled)
        except KeyError:
            raise HTTPException(404, 'Unknown inference machine') from None

    @app.post('/api/hermes/local/nodes/{name}/capacity')
    async def capacity(name: str, body: PoolCapacity, actor=Depends(auth)):
        import asyncio
        try:
            result = await asyncio.to_thread(set_capacity, name, body.capacity)
        except KeyError:
            raise HTTPException(404, 'Unknown inference machine') from None
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from None
        except RuntimeError as exc:
            raise HTTPException(503, str(exc)) from None
        # Resize the existing limiter on its serving event loop, including
        # queued calls; do not replace it while requests hold permits.
        if name in _PROXIES:
            _PROXIES[name]._lock()
        return result

    @app.get('/api/llm/local/nodes/{name}/v1/models')
    def models(name: str, actor=Depends(access)):
        s = node_settings().get(name)
        if not s:
            raise HTTPException(404, 'Unknown inference machine')
        return {'object': 'list', 'data': [{'id': s.model, 'object': 'model', 'context_length': s.context_tokens}]}

    @app.post('/api/llm/local/nodes/{name}/v1/chat/completions')
    async def chat(name: str, request: Request, actor=Depends(access)):
        settings = node_settings()
        if name not in settings:
            raise HTTPException(404, 'Unknown inference machine')
        try:
            body = await request.json()
        except ValueError:
            raise HTTPException(400, 'Invalid JSON') from None
        if not isinstance(body, dict):
            raise HTTPException(400, 'Expected a JSON object')
        # Fail over before inference begins. Never replay a partially emitted tool-call stream.
        candidates = [name] + [n for n in settings if n != name]
        if not L.settings().enabled:
            raise HTTPException(503, 'Local task pool is disabled')
        for target in candidates:
            s = settings[target]
            if not s.enabled:
                continue
            import asyncio
            ready = await asyncio.to_thread(health, target, s)
            if not ready['capable']:
                continue
            try:
                p = proxy(target)
                if body.get('stream'):
                    events = await p.stream(body, request.is_disconnected)
                    return StreamingResponse(events, media_type='text/event-stream',
                        headers={'X-gBox-Inference-Host': target, 'Cache-Control': 'no-store'})
                return JSONResponse(await p.complete(body, request.is_disconnected),
                                    headers={'X-gBox-Inference-Host': target})
            except Busy as exc:
                if exc.status < 500:
                    return JSONResponse({'error': {'message': exc.message}}, status_code=exc.status)
                continue
        return JSONResponse({'error': {'message': 'Enabled local inference machines are unavailable; task retained'}},
                            status_code=503, headers={'Retry-After': '30'})

    from . import hermes_models
    hermes_models.routes(app, auth)
    app.state.local_pool_chat = chat
