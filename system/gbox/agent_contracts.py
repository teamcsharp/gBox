"""Small caller contracts and required-operation evidence checks."""
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


def _operation_key(name: str, args: dict) -> str:
    """A successful change at another target cannot erase a failed operation."""
    if name == 'cheats':
        op = args.get('op') or 'list'
        # The precise correction for enable-with-codes is add-with-those-codes.
        # Descriptions and list filters do not identify the cheat being applied.
        identity = {'session_id': args.get('session_id'),
                    'op': 'enable' if op in {'enable', 'add'} else op}
        if args.get('codes'):
            identity['codes'] = args['codes']
        else:
            identity['index'] = args.get('index')
    else:
        identity = args
    return name + ':' + json.dumps(identity, sort_keys=True, default=str)


def _creates_game_files(name: str, args: dict) -> bool:
    """File builds need completion evidence but must not trigger live bookmarks."""
    return ((name == 'rom_export' and args.get('op', 'export') == 'export') or
            (name == 'file_mod' and args.get('op') == 'build'))


def _file_deliverable(layers: list[dict], name: str, args: dict) -> bool:
    """Recognize the producers' returned deliverable, not a job's terminal state.

    This checks the tool's output contract, not whether the built game satisfies
    all requested gameplay changes. Keep native gameplay verification separate.
    """
    def text(value):
        return isinstance(value, str) and bool(value.strip())

    def paths(value):
        return isinstance(value, list) and bool(value) and all(text(v) for v in value)

    if name == 'rom_export':
        # Export summaries intentionally omit the full file manifest. Both a
        # built image/folder and an explicit cheat-file export are supported;
        # a plan, README or generic succeeded wrapper is not a deliverable.
        return any(text(layer.get('rel_dir')) and
                   (not args.get('game_id') or layer['rel_dir'].split('/')[:2] == ['exports', args['game_id']]) and
                   (text(layer.get('image')) or paths(layer.get('cheat_files')))
                   for layer in layers)
    return any(text(layer.get('dir')) and text(layer.get('mod')) and
               layer['mod'] == args.get('name') and paths(layer.get('files'))
               for layer in layers)


def _operation_result_state(text: str, name: str, args: dict) -> str:
    """Read explicit tool/job failures without treating null error metadata as failure."""
    try:
        payload = json.loads(text or '')
    except (TypeError, ValueError):
        return 'unresolved'
    if not isinstance(payload, dict) or not payload:
        return 'unresolved'
    layers = [payload]
    for layer in layers:
        # Only known result wrappers, not arbitrary game data containing 'error'.
        for field in ('result', 'output'):
            nested = layer.get(field)
            if isinstance(nested, dict) and len(layers) < 8:
                layers.append(nested)
    pending = repeat = False
    for layer in layers:
        state = str(layer.get('state') or '').lower()
        status = str(layer.get('status') or '').lower()
        if _creates_game_files(name, args) and (layer.get('ready') is False or
                {state, status} & {'unsupported', 'partial', 'needs_selection', 'needs_writer'} or
                (args.get('game_id') and layer.get('game_id') and layer['game_id'] != args['game_id'])):
            return 'failed'
        if (layer.get('error') or layer.get('overlay_error') or
                state in {'failed', 'blocked', 'invalid', 'cancelled', 'canceled', 'timeout', 'timed_out'} or
                status in {'failed', 'blocked', 'missing', 'unsupported'} or
                layer.get('success') is False or layer.get('ok') is False or layer.get('verified') is False):
            return 'failed'
        if name == 'cheats' and isinstance(layer.get('enabled'), bool):
            expected = args.get('op') in {'enable', 'add'}
            if args.get('op') in {'enable', 'add', 'disable'} and layer['enabled'] != expected:
                return 'failed'
        pending |= state in {'queued', 'running'} or status in {'queued', 'running'}
        repeat |= layer.get('repeat') is True
    if pending:
        return 'unresolved'
    if repeat:
        return 'repeat'
    if _creates_game_files(name, args) and not _file_deliverable(layers, name, args):
        return 'unresolved'
    return 'complete'


def required_operation_outcome(events: list[dict], modifies_game) -> dict:
    """Keep failed game changes/builds pending; successful reads cannot resolve them.

    Uses the caller's live change/read classifier plus explicit file-creation
    contracts, without classifying file builds as live mutations. Recovery is deliberately
    limited to the same tool and exact arguments/target, or the documented cheat
    enable-with-codes -> add-with-the-same-codes correction. This does not infer
    success from the assistant's prose or prove gameplay beyond the tool result.
    """
    outstanding = {}
    calls = {}
    completed = set()
    for event in events:
        name = event.get('name')
        if event.get('type') == 'tool_call':
            args = event.get('args') or {}
            if not isinstance(args, dict):
                args = {}
            operation_name, operation_args = name, args
            if name == 'run_tool' and isinstance(args.get('input'), dict):
                operation_name, operation_args = args.get('name'), args['input']
            required = (modifies_game(operation_name, operation_args) or
                        _creates_game_files(operation_name, operation_args))
            call = None
            if required:
                key = _operation_key(operation_name, operation_args)
                label = operation_name + (' op=' + str(operation_args['op']) if operation_args.get('op') else '')
                outstanding[key] = label
                call = (key, operation_name, operation_args)
            calls.setdefault(name, []).append(call)
        elif event.get('type') == 'tool_result' and calls.get(name):
            call = calls[name].pop(0)
            if call is not None:
                key, operation_name, operation_args = call
                state = _operation_result_state(event.get('text'), operation_name, operation_args)
                if state == 'complete' or (state == 'repeat' and key in completed):
                    outstanding.pop(key, None)
                    completed.add(key)
                elif state != 'repeat':
                    completed.discard(key)
    labels = list(dict.fromkeys(outstanding.values()))
    return {'unresolved': bool(outstanding), 'operations': labels,
            'reason': ('Required game operation(s) did not complete: ' + ', '.join(labels[:5]) +
                       '. Keep the request pending until those changes succeed; successful reads do not resolve them.')
                      if outstanding else ''}
