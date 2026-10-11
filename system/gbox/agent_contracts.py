"""Small caller contracts and native character-swap evidence checks."""
from __future__ import annotations

import json


def require_character(op: str, character: str) -> None:
    if op in {'use', 'live_use', 'overlay', 'place'} and not str(character or '').strip():
        raise ValueError(f'characters op={op} requires character=<the exact collection slug or name>; '
                         'copy the character supplied in the request, or use op=list to find it')


def validate_cheat_call(op: str, index, codes) -> None:
    if op in {'enable', 'disable'}:
        if index is None:
            raise ValueError(f'cheats op={op} requires index from op=list. '
                             'To apply new code lines, use op=add with codes=["ADDR VALUE"]; '
                             'add enables the new code immediately')
        if isinstance(index, bool) or not isinstance(index, int) or index < 0:
            raise ValueError('cheats index must be a nonnegative integer returned by op=list')
        if codes:
            raise ValueError('cheats enable/disable uses an existing index, not codes; '
                             'use op=add to apply new code lines')
    if op == 'add' and (not isinstance(codes, list) or not codes or
                        any(not isinstance(line, str) or not line.strip() for line in codes)):
        raise ValueError('cheats op=add requires nonempty codes=["ADDR VALUE", ...]')


def resolve_read_session(session_id: str, game_id: str, sessions: list[dict], context_session_id: str = '') -> str:
    """Correct a unique truncated prefix only for a read-only, game-bound call.

    Never select another session merely because it shares a worker or title.
    Exact identifiers remain subject to the caller's ordinary live check.
    """
    live = [s for s in sessions if s.get('state') == 'running' and not s.get('ended')]
    exact = next((s for s in live if s.get('session_id') == session_id), None)
    if exact:
        if game_id and exact.get('game_id') != game_id:
            raise ValueError('The supplied live session belongs to a different game; copy the requested game session ID')
        return session_id
    if not session_id or not game_id or '-' not in session_id:
        return session_id
    matches = [s['session_id'] for s in live if s.get('game_id') == game_id
               and s.get('session_id', '').startswith(session_id)]
    if len(matches) == 1:
        return matches[0]
    bound = next((s for s in live if s.get('session_id') == context_session_id
                  and s.get('game_id') == game_id), None)
    if (bound and len(session_id) < len(context_session_id)
            and session_id.split('-', 1)[0] == context_session_id.split('-', 1)[0]):
        return context_session_id
    return session_id


def native_swap_result(result: dict) -> dict:
    """A returned/finished tool or successful overlay does not verify the ROM."""
    layers = [result]
    if isinstance(result.get('result'), dict):
        layers.append(result['result'])
    for layer in layers:
        status = str(layer.get('status') or layer.get('state') or '').lower()
        if (layer.get('error') or layer.get('overlay_error') or status in
                {'overlay', 'missing', 'blocked', 'failed', 'queued', 'running'} or
                layer.get('fallback') == 'overlay' or layer.get('in_engine') is False or
                layer.get('native_swap_verified') is False):
            return {'verified': False, 'reason': 'Native character replacement was not verified; '
                    'the tool reported an error, pending result, or overlay fallback. Keep the request pending.'}
    result = layers[-1]
    if result.get('verified') is True or result.get('landed') is True:
        return {'verified': True, 'reason': ''}
    return {'verified': False, 'reason': 'The character mod may be built or launched, but no verified '
            'native result was returned. Verify the replacement in the game before marking done.'}


def native_swap_outcome(events: list[dict]) -> dict:
    """Track the final native-use attempt, without crediting overlay/read calls."""
    outcome = {'required': False, 'verified': False, 'reason': ''}
    native_call = False
    for event in events:
        if event.get('type') == 'tool_call' and event.get('name') == 'characters':
            native_call = (event.get('args') or {}).get('op') in {'use', 'live_use'}
            if native_call:
                outcome = {'required': True, 'verified': False,
                           'reason': 'The native character replacement attempt has no verified result.'}
        elif native_call and event.get('type') == 'tool_result' and event.get('name') == 'characters':
            try:
                result = json.loads(event.get('text') or '')
            except (TypeError, ValueError):
                result = {}
            outcome.update(native_swap_result(result if isinstance(result, dict) else {}))
            native_call = False
    return outcome
