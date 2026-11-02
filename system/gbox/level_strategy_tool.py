"""Runnable level research tool; research never directly issues game inputs."""
from __future__ import annotations
import hashlib
import json
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field
from .models import Permission as P
from .registry import tool, Unsupported
from .level_strategy import Store, scope


class StrategyIn(BaseModel):
    model_config = ConfigDict(extra='forbid')
    session_id: str
    op: Literal['research', 'status', 'enable', 'disable'] = 'research'
    goal: str = Field(default='Complete the current level and verify its result and unlocks.', max_length=1000)


class StrategyOut(BaseModel):
    result: dict


def current(ad, game):
    from .mercs.titles.merc3d_strategy import GAME_ID, native_context
    if game.get('game_id') == GAME_ID or 'mercenaries 3d' in str(game.get('title') or '').lower():
        return native_context(ad, game)
    from .tools import _semantic_state
    snapshot = _semantic_state(ad, game)
    profile = snapshot.get('profile')
    native = snapshot.get('globals') or {}
    level = next((native[k] for k in ('level', 'stage', 'area', 'level_id', 'stage_id', 'area_id')
                  if native.get(k) is not None), None)
    # Research works for any observed level; executing it needs a registered adapter.
    if not profile or snapshot.get('verified') is not True or level is None or isinstance(level, (dict, list)):
        raise Unsupported('This game needs a verified current-level reader before live strategy research')
    encoded = json.dumps(game.get('_profile') or {}, sort_keys=True, default=str)
    return {'game_id': game['game_id'], 'title': game.get('title', game['game_id']),
            'platform': game.get('platform'), 'build': 'semantic-profile:' + hashlib.sha256(encoded.encode()).hexdigest(),
            'mod': str(game.get('mod') or ''), 'level': str(level), 'actions': [], 'targets': {},
            'limitations': ['Research-only: this title has no registered semantic strategy executor.']}, snapshot


@tool('level_strategy', '1.0', StrategyIn, StrategyOut, capabilities=['runtime'],
      permissions=[P.READ, P.STAGE, P.NETWORK], timeout_s=180, retries=0,
      side_effects=['Fetches public game guides; stores cited level plans and optional bounded automatic re-research settings'])
def run(inp, ctx):
    """Research the observed game level online, store a cited semantic plan, or enable/status/disable its agent.

    Research does not send inputs. Merc3D consumes grounded combat objectives;
    games without an executor retain an advisory plan with explicit blockers.
    """
    from .tools import SESSIONS
    from .level_strategy_service import transport
    if inp.session_id not in SESSIONS:
        raise Unsupported('The exact session must be running on this worker')
    ad, game = SESSIONS[inp.session_id]
    if ad.query_runtime().get('running') is not True:
        raise Unsupported('The selected game is no longer running')
    context, snap = current(ad, game)
    context['goal'] = inp.goal
    store = Store(ctx.config.data_dir / 'level-strategy')
    # The existing brain reads these exact scope/path properties, without new input ownership.
    ad._level_strategy_root = store.root
    ad._level_strategy_identity = {k: context[k] for k in ('game_id', 'build', 'mod')}
    if inp.op in ('enable', 'disable'):
        settings = store.configure(context['game_id'], inp.op == 'enable', ctx.config.agent)
        return {'result': {'scope': scope(context), 'settings': {'enabled': settings['enabled']},
                           'instructions': 'Merc3D refreshes online plans on missing plans or observed stalls; other games require an executor.'}}
    if inp.op == 'status':
        return {'result': {'scope': scope(context), 'plan': store.plan(context),
                           'enabled': store.settings(context['game_id']).get('enabled', False),
                           'limitations': context.get('limitations'), 'inputs_sent': False}}
    ctx.progress(10, 'Researching the observed level and its mission objectives')
    if not ctx.server:
        raise Unsupported('Level research needs the existing authenticated control-plane connection')
    research = transport(ctx.server, ctx.headers, inp.session_id,
                         lambda: P.NETWORK in ctx.config.granted_permissions)
    plan = research(context, {}, {'progress': {}, 'plan': store.plan(context)})
    if SESSIONS.get(inp.session_id) != (ad, game):
        raise Unsupported('Session changed during research; plan was not activated')
    after, _ = current(ad, game)
    if scope(after) != scope(context) or ad.query_runtime().get('running') is not True:
        raise Unsupported('Game or mission changed during research; plan was not activated')
    store.save(context, plan)
    store.configure(context['game_id'], True, ctx.config.agent)
    ctx.artifact('level-strategy.json', json.dumps(plan, indent=2).encode(), 'application/json',
                 game=context['game_id'], level=context['level'], session=inp.session_id)
    ctx.progress(100, 'Cited strategy saved; only grounded adapter actions may execute')
    return {'result': {'session_id': inp.session_id, 'plan': plan, 'enabled': True,
                       'inputs_sent': False, 'completion_verified': False}}
