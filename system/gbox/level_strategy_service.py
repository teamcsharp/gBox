"""Authenticated text-only strategy service on the paired control plane."""
from __future__ import annotations
import json
import threading
import time
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field

from .level_strategy import ACTIONS, scope


class Target(BaseModel):
    model_config = ConfigDict(extra='forbid')
    enemy_class: str = Field(max_length=120)


class Context(BaseModel):
    model_config = ConfigDict(extra='forbid')
    game_id: str = Field(min_length=1, max_length=100)
    build: str = Field(min_length=1, max_length=200)
    mod: str = Field(default='', max_length=200)
    level: str = Field(min_length=1, max_length=100)
    title: str = Field(min_length=1, max_length=200)
    platform: str = Field(default='', max_length=100)
    objective: str = Field(default='', max_length=1000)
    required_action: str | None = Field(default=None, max_length=40)
    goal: str = Field(default='', max_length=1000)
    actions: list[str] = Field(default_factory=list, max_length=12)
    targets: dict[str, Target] = Field(default_factory=dict, max_length=64)
    source_urls: list[str] = Field(default_factory=list, max_length=4)
    limitations: list[str] = Field(default_factory=list, max_length=12)


class Progress(BaseModel):
    model_config = ConfigDict(extra='forbid')
    stalled: bool = False
    stalls: int = Field(default=0, ge=0, le=1000000)
    no_progress_seconds: float = Field(default=0, ge=0, le=1e8, allow_inf_nan=False)
    progress_evidence: str | None = Field(default=None, max_length=80)
    objective_ended: bool = False
    failed: bool = False
    mission_cleared: bool = False
    unlock_verified: bool = False


class Request(BaseModel):
    model_config = ConfigDict(extra='forbid')
    session_id: str = Field(min_length=1, max_length=150, pattern=r'^[A-Za-z0-9_-]+$')
    context: Context
    progress: Progress = Field(default_factory=Progress)


def payload(session_id, context, previous=None):
    fields = Context.model_fields
    data = {k: context[k] for k in fields if k in context}
    data['platform'] = str(data.get('platform') or '')
    progress = (previous or {}).get('progress') or {}
    body = Request(session_id=session_id, context=data,
                   progress={k: progress[k] for k in Progress.model_fields if k in progress}).model_dump()
    if len(json.dumps(body)) > 20000:
        raise ValueError('Strategy context exceeds 20 KiB')
    if any(len(k) > 120 for k in body['context']['targets']) or \
            any(len(s) > 500 for s in body['context']['source_urls'] + body['context']['limitations']):
        raise ValueError('Strategy labels exceed their bounded size')
    if set(body['context']['actions']) - ACTIONS:
        raise ValueError('Unknown semantic action capability')
    return body


def transport(server, headers, session_id, network_allowed):
    """Credentials remain in the existing session context, never saved in plans."""
    def remote(context, _config, previous=None):
        import httpx
        if not network_allowed():
            raise PermissionError('Network permission is required for strategy research')
        body = payload(session_id, context, previous)
        response = httpx.post(server.rstrip('/') + '/api/level-strategy/research', json=body,
                              headers=headers, timeout=160)
        response.raise_for_status()
        plan = response.json()['plan']
        if not network_allowed() or plan.get('scope') != scope(context):
            raise ValueError('Strategy response no longer matches its permitted context')
        return plan
    return remote


def install(app, config, auth):
    from fastapi import Depends, HTTPException
    from .level_strategy_web import research
    from .desktop_bridge import origin
    slots = threading.BoundedSemaphore(2)

    @app.post('/api/level-strategy/research')
    def research_level(request: Request, actor=Depends(auth)):
        allowed = lambda: 'network' in config.granted_permissions
        if not allowed():
            raise HTTPException(403, 'Network permission is required for level research')
        try:
            body = payload(request.session_id, request.context.model_dump(), {'progress': request.progress.model_dump()})
        except ValueError as error:
            raise HTTPException(422, str(error))
        store = app.state.store
        def identity():
            session = store.get('session', request.session_id) or {}
            if session.get('state') != 'running' or session.get('game_id') != request.context.game_id \
                    or str(session.get('mod') or '') != request.context.mod:
                raise HTTPException(409, 'Strategy session is no longer the same running game/mod')
            return session.get('worker_id'), session.get('started')
        before = identity()
        if not slots.acquire(blocking=False):
            raise HTTPException(429, 'Two level research requests are already active')
        try:
            # A desktop authority already has a paired channel. Forward this
            # text-only research to that exact origin; never rewrite ports or
            # export the paired credential to the worker/model.
            bridge = getattr(app.state, 'desktop_bridge', None)
            if bridge is not None:
                import httpx
                with bridge.lock:
                    if not bridge.remote or not bridge.token or not bridge.state.get('connected'):
                        raise HTTPException(503, 'The paired research authority is disconnected')
                    remote, token = origin(bridge.remote), bridge.token
                response = httpx.post(remote + '/api/level-strategy/research', json=body, timeout=150,
                    headers={'Authorization': 'Bearer ' + token, 'X-GBox-Actor': 'level-strategy'})
                response.raise_for_status()
                plan = response.json()['plan']
            else:
                plan = research(body['context'], config.agent, {'progress': body['progress']}, network_allowed=allowed)
            if not allowed() or identity() != before or plan.get('scope') != scope(body['context']):
                raise HTTPException(409, 'Session changed while its strategy was researched')
            return {'plan': plan, 'inputs_sent': False, 'completion_verified': False}
        except HTTPException:
            raise
        except Exception as error:
            raise HTTPException(502, 'Level research failed: ' + str(error)[:300])
        finally:
            slots.release()
