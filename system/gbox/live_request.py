"""Exact-session contracts for requests that change a running game.

These helpers never dispatch work or infer success from assistant text. Console
analysis, a successful job, and a successful memory read are not goal evidence.
"""
from __future__ import annotations

import json
import re


_READ_OPS = {'list', 'get', 'status', 'verify', 'inspect', 'info', 'preview', 'roster',
             'coverage', 'scan', 'plan', 'search', 'describe', 'query', 'state', 'items',
             'games', 'stages', 'readiness', 'capabilities', 'catalog', 'addresses',
             'bosses', 'groups', 'player', 'pools', 'vehicles'}
_NATIVE = {'re_inventory', 're6', 're4r', 'ac_mods', 'gta_mods', 'zelda', 're_mods',
           'pso_mods', 'zelda_oot', 'pso_drops', 'pso_inventory', 'stage_warp',
           'mario_kart', 'mgs_vr', 're5', 'gta_live', 'sonic_adventure_2', 'auf_live',
           'game_live_controls', 'pso_face', 'gta3_items', 'twin_snakes_live'}
_LOW_LEVEL = {'poke', 'write_memory', 'freeze_memory', 'script_patch', 'cheats', 'mod'}
_BAD_STATES = {'failed', 'blocked', 'invalid', 'cancelled', 'canceled', 'timeout',
               'timed_out', 'missing', 'unsupported', 'unavailable', 'overlay',
               'queued', 'running', 'pending', 'research_pending', 'unverified'}


def _plain(text):
    return re.sub(r'\s+', ' ', str(text or '').split('\n[context:', 1)[0]).strip()


def is_live_change_request(text: str, context: dict) -> bool:
    """Recognize an instruction to change the selected game, not an explanation.

    ``live_edit`` only identifies the client's surface. It does not make an
    analysis request, reply, greeting or navigation action a mutation goal.
    """
    if not context.get('session_id'):
        return False
    q = _plain(text).lower()
    if not q or re.fullmatch(r'(hi|hello|hey|thanks|thank you|good morning|good evening)[!.? ]*', q):
        return False
    if re.match(r'^(?:who|what|when|where|why|how)\b', q):
        return False
    if re.match(r'^(?:please\s+)?(?:open|launch|load|play|close|show|search|find|browse|go to)\b', q):
        # "Go to the next checkpoint" is an in-game instruction.
        if not re.search(r'\b(?:checkpoint|boss|end of (?:the )?level)\b', q):
            return False
    if re.search(r'\b(?:search|filter|sort|library|home page|list view|info view|chat history)\b', q):
        return False
    if re.match(r'^(?:please\s+)?go to\b', q) and re.search(r'\b(?:checkpoint|boss|end of (?:the )?level)\b', q):
        return True
    if re.match(r'^(?:infinite|unlimited|invincib\w*|noclip|never miss|walk through (?:any )?(?:walls?|doors?|obstacles?|laser))\b', q):
        return True
    action = r'(?:unlock|give|grant|spawn|teleport|warp|skip|replace|swap|change|modify|alter|set|make|add|remove|increase|decrease|double|triple|scale|paint|freeze|enable|disable|turn|map|remap|blend|bypass|equip|upgrade|max)'
    if re.match(rf'^(?:(?:please|can you|could you|would you|i want you to|i need you to|let me)\s+)*{action}\b', q):
        return True
    return bool(re.match(r'^(?:i want|i need|i would like|allow me)\b', q) and re.search(
        rf'\b{action}\b|\b(?:infinite|unlimited|invincible|never miss|every attack|all characters|all stages|all weapons|all items|everything unlocked)\b', q))


def bind_target(context: dict, sessions: list[dict]) -> dict:
    """Pin the exact currently live session. Never follow another game on its PC."""
    sid = context.get('session_id')
    if not isinstance(sid, str) or not sid:
        raise ValueError('Select the running game before requesting a live change')
    matches = [s for s in sessions if isinstance(s, dict) and s.get('session_id') == sid]
    if len(matches) != 1 or matches[0].get('state') != 'running' or matches[0].get('ended'):
        raise ValueError('The selected game session has ended or changed; select the running game again')
    session = matches[0]
    gid = session.get('game_id')
    if not isinstance(gid, str) or not gid:
        raise ValueError('The running session has no catalog game identity')
    worker = session.get('worker_id') or sid.split('-', 1)[0]
    if not isinstance(worker, str) or not sid.startswith(worker + '-'):
        raise ValueError('The selected session has an inconsistent worker identity')
    mod = session.get('mod') or ''
    if not isinstance(mod, str):
        raise ValueError('The running session has an invalid mod identity')
    for key, expected in (('game_id', gid), ('mod', mod), ('worker_id', worker)):
        if key in context and context[key] is not None and context[key] != expected:
            raise ValueError(f'The selected game {key} changed; select the running game again')
    prior = context.get('live_target')
    if isinstance(prior, dict):
        for key, expected in (('session_id', sid), ('game_id', gid), ('mod', mod), ('worker_id', worker)):
            if key in prior and prior[key] != expected:
                raise ValueError(f'The pinned live target {key} changed; a different game will not be modified')
    return {'session_id': sid, 'game_id': gid, 'title': session.get('title') or '',
            'game_title': session.get('title') or '', 'mod': mod, 'worker_id': worker,
            'adapter': session.get('adapter') or '', 'platform': session.get('platform') or context.get('platform') or ''}


def _operation(name, args):
    args = args if isinstance(args, dict) else {}
    if name == 'run_tool':
        return args.get('name'), args.get('input') if isinstance(args.get('input'), dict) else {}
    return name, args


def is_mutation(name: str, args: dict) -> bool:
    """Recognize guest mutations; analysis metadata edits never count."""
    name, args = _operation(name, args)
    op = str(args.get('op') or '').lower()
    if name == 'characters':
        return op in {'use', 'live_use'}
    if name == 'game_live_controls':
        return op == 'apply'
    if name == 'mod':
        return op == 'apply'
    if name == 'cheats':
        return op in {'enable', 'disable', 'add'}
    if name == 'gta_live':
        return (op in {'teleport', 'spawn'} or op == 'weather' and args.get('value') not in (None, '')
                or op == 'time' and any(args.get(k) is not None for k in ('hours', 'minutes'))
                or op == 'wanted' and args.get('level') is not None)
    return name in (_NATIVE | _LOW_LEVEL) and op not in _READ_OPS


def phase_for_tool(name: str, args: dict) -> str | None:
    name, args = _operation(name, args)
    if is_mutation(name, args):
        return 'apply'
    if name == 'session_info':
        return 'attach'
    if name in {'look_at_screen', 'get_frame', 'verify_live_goal'} or (name == 'game_live_controls' and args.get('op') == 'inspect'):
        return 'verify'
    if (str(name).startswith(('rea_', 're_', 'ghidra')) or name in
            {'analyze_binary', 'assimilate', 'memory_search', 'memory_snapshot', 'memory_filter', 'read_memory', 'debugger', 'cheats', 'game_controls_research'}):
        return 'research'
    return None


def _layers(payload):
    """Only descend typed result envelopes, never arbitrary game-data fields."""
    layers = [payload]
    for layer in layers:
        if len(layers) > 16:
            break
        for field in ('result', 'output', 'verification'):
            if isinstance(layer.get(field), dict):
                layers.append(layer[field])
    return layers


def _failed(layers):
    return len(layers) > 16 or any(layer.get('error') or layer.get('overlay_error') or
               str(layer.get('state') or '').lower() in _BAD_STATES or
               str(layer.get('status') or '').lower() in _BAD_STATES or
               any(layer.get(k) is False for k in ('success', 'ok', 'verified', 'goal_verified')) or
               any(k in layer and layer[k] is not None and not isinstance(layer[k], dict)
                   for k in ('result', 'output', 'verification')) or
               layer.get('fallback') == 'overlay' or layer.get('in_engine') is False
               for layer in layers)


def _same_target(args, layers, target):
    if args.get('session_id') != target.get('session_id'):
        return False
    for value in [args, *layers]:
        for key in ('session_id', 'game_id', 'mod', 'worker_id'):
            if key in value and key in target and value[key] != target[key]:
                return False
    return True


def _command_key(name, args):
    # A new short deadline/nonce is a retry of the same action, not another goal.
    return str(name) + ':' + json.dumps({k: v for k, v in args.items()
        if k not in {'command_id', 'expires'}}, sort_keys=True, default=str)


def _unlock_scope(text):
    """Conservative categories for quantified unlock goals; None is not one.

    "Everything" requires the same complete inventory as custom-build unlocks.
    A merely named single fighter/flag has no inferred all-content scope.
    """
    from .custom_build_unlocks import CATEGORIES
    q = _plain(text).lower()
    if not re.search(r'\bunlock(?:ed|ing|s)?\b', q) or not re.search(r'\b(?:all|every|everything|everyone|entire|whole)\b', q):
        return None
    if re.search(r'\b(?:except|excluding|without|only|not)\b', q):
        # An all-content inventory does not prove the requested exclusions were
        # preserved. Do not infer this scope from a generic "verified" field.
        return {'the exact requested exclusions'}
    if (re.search(r'\b(?:everything|everyone|content|secrets|extras|etc)\b', q)
            or re.search(r'\b(?:all|every)\s*(?:[.!?]|$)', q)):
        return set(CATEGORIES)
    categories = set()
    for category, words in (
            ('characters', r'characters?|fighters?|roster'), ('levels', r'levels?|missions?|chapters?'),
            ('stages', r'stages?|arenas?'), ('costumes', r'costumes?|outfits?|skins?'),
            ('modes', r'modes?|difficulties'), ('items', r'items?|weapons?|equipment|gadgets?')):
        if re.search(rf'\b(?:{words})\b', q):
            categories.add(category)
    if 'characters' in categories:
        categories.add('hidden_characters')
    return categories or set(CATEGORIES)


def _artifact_ids(value):
    return (isinstance(value, list) and 1 <= len(value) <= 100
            and all(isinstance(item, str) and re.fullmatch('[a-f0-9]{64}', item) for item in value))


def _needs_exact_goal(text, unlock_scope):
    """A single successful action cannot prove a quantified or compound goal."""
    q = _plain(text).lower()
    if unlock_scope:
        # Multiple unlock categories have their explicit inventory contract.
        # An additional independent effect still needs whole-goal verification.
        return bool(re.search(r'\b(?:and|also|plus|then)\b.{0,80}\b(?:give|grant|spawn|teleport|warp|skip|replace|swap|change|set|make|add|remove|increase|decrease|freeze|enable|disable|turn|map|remap|blend|bypass|equip|upgrade|max)\b', q)
                    or re.search(r'\b(?:infinite|unlimited|invincib\w*|never miss|noclip)\b', q))
    return bool(re.search(r'\b(?:all|every|everything|everyone|entire|whole)\b', q)
                or re.search(r'\b(?:and|also|plus|then)\b|;', q)
                or re.search(r'\bwith\b.{0,40}\b(?:infinite|unlimited|invincib\w*|never miss)\b', q)
                or re.search(r'\b(?:[2-9]|[1-9]\d+|two|three|four|five|six|seven|eight|nine|ten)\b.{0,40}\b(?:items?|weapons?|characters?|fighters?|npcs?|pedestrians?|enemies|models?)\b', q))


def _exact_goal_evidence(layers, text, target):
    # This field is produced by a tool, not assistant prose or client arguments.
    wanted = _plain(text).casefold()
    return any(layer.get('goal_verified') is True
        and layer.get('session_id') == target['session_id']
        and isinstance(layer.get('goal'), str) and _plain(layer['goal']).casefold() == wanted
        and _artifact_ids(layer.get('evidence')) for layer in layers)


def _unlock_evidence(layers, target):
    """Read explicit exact-build runtime coverage, not a function/action label.

    The producer supplies ``unlock_coverage`` with session/game/mod identity,
    inventory_complete=true, runtime_artifacts (stored SHA256 IDs), and a
    categories map using the custom-build inventory's status/entries/evidence
    rows. A partial/unknown category contributes no coverage.
    """
    from .custom_build_unlocks import CATEGORIES
    covered = set()
    for layer in layers:
        coverage = layer.get('unlock_coverage')
        if not isinstance(coverage, dict) or coverage.get('inventory_complete') is not True:
            continue
        if any(coverage.get(k) != target.get(k, '') for k in ('session_id', 'game_id', 'mod')):
            continue
        if not _artifact_ids(coverage.get('runtime_artifacts')):
            continue
        categories = coverage.get('categories')
        if not isinstance(categories, dict) or len(categories) > len(CATEGORIES):
            continue
        for category, row in categories.items():
            if category not in CATEGORIES or not isinstance(row, dict):
                continue
            entries, evidence = row.get('entries'), row.get('evidence')
            if (row.get('status') not in {'unlocked', 'not_present'} or not isinstance(entries, list)
                    or len(entries) > 10000 or any(not isinstance(v, str) or not v.strip() for v in entries)
                    or (row['status'] == 'unlocked') != bool(entries)
                    or not (isinstance(evidence, str) and bool(evidence.strip()) or _artifact_ids(evidence))
                    or row.get('verified') is False or row.get('complete') is False or row.get('error')):
                continue
            covered.add(category)
    return covered


def request_outcome(text: str, context: dict, events: list[dict]) -> dict:
    """Require a successful exact-target change with explicit goal evidence.

    Native operations may return their own ``verified``/``landed`` proof. A later
    semantic verifier must explicitly return ``goal_verified``, the exact
    ``session_id`` and nonempty ``evidence``. Ordinary reads or screenshots never
    prove that the requested change happened, even if their readback succeeded.
    """
    required = is_live_change_request(text, context)
    if not required:
        return {'required': False, 'verified': False, 'reason': ''}
    target = dict(context.get('live_target') if isinstance(context.get('live_target'), dict) else context)
    if not target.get('session_id') or not target.get('game_id'):
        return {'required': True, 'verified': False, 'reason': 'The live change has no pinned game/session identity; keep the request in progress.'}
    target.setdefault('worker_id', target['session_id'].split('-', 1)[0])
    unlock_scope = _unlock_scope(text)
    needs_exact_goal = _needs_exact_goal(text, unlock_scope)
    calls, changes = {}, {}
    coverage_by_change = {}
    semantic_coverage = set()
    semantic_verification = False
    semantic_failed = False
    exact_goal_verified = False
    for event in events:
        if not isinstance(event, dict):
            continue
        name = event.get('name')
        if event.get('type') == 'tool_call':
            op_name, args = _operation(name, event.get('args'))
            calls.setdefault(name, []).append((op_name, args))
            if is_mutation(op_name, args):
                changes[_command_key(op_name, args)] = False
                # A later mutation may invalidate earlier unlock flags. Only
                # coverage observed after the latest change can complete scope.
                coverage_by_change = {_command_key(op_name, args): set()}
                semantic_verification = False
                exact_goal_verified = False
                semantic_coverage = set()
                semantic_failed = False
        elif event.get('type') == 'tool_result' and calls.get(name):
            op_name, args = calls[name].pop(0)
            mutation = is_mutation(op_name, args)
            key = _command_key(op_name, args)
            if mutation:
                changes[key] = False
                coverage_by_change[key] = set()
                semantic_verification = False  # A newer change needs fresh evidence.
                exact_goal_verified = False
            try:
                payload = json.loads(event.get('text') or '')
            except (TypeError, ValueError):
                continue
            if not isinstance(payload, dict) or not payload:
                continue
            layers = _layers(payload)
            if not _same_target(args, layers, target):
                continue
            if _failed(layers):
                if op_name == 'verify_live_goal' or any(layer.get('goal_verified') is False for layer in layers):
                    semantic_failed = True
                continue
            if mutation:
                # Raw byte writes/cheat enablement only prove that bytes changed.
                native = op_name in _NATIVE or op_name == 'characters'
                changes[key] = 'verified' if native and any(
                    layer.get('verified') is True or layer.get('landed') is True for layer in layers) else 'changed'
                if changes[key] == 'verified':
                    coverage_by_change[key] = _unlock_evidence(layers, target)
            if changes and all(changes.values()) and any(
                    layer.get('goal_verified') is True and layer.get('session_id') == target['session_id']
                    and bool(layer.get('evidence')) for layer in layers):
                semantic_verification = True
                semantic_coverage = _unlock_evidence(layers, target)
                exact_goal_verified = _exact_goal_evidence(layers, text, target)
                semantic_failed = False
    verified = bool(changes) and all(changes.values()) and not semantic_failed and (
        all(value == 'verified' for value in changes.values()) or semantic_verification)
    if verified and unlock_scope:
        covered = set().union(*coverage_by_change.values(), semantic_coverage)
        verified = unlock_scope <= covered
        if not verified:
            return {'required': True, 'verified': False, 'reason':
                'Unlock-all is still unverified for: ' + ', '.join(sorted(unlock_scope - covered)) +
                '. A verified flag or single-character change does not prove complete unlock coverage; keep the request in progress.'}
    if verified and needs_exact_goal and not exact_goal_verified:
        return {'required': True, 'verified': False, 'reason':
            'The complete requested goal has not been verified on the selected session. A single successful action does not prove every requested item, character or independent effect; keep the request in progress.'}
    return {'required': True, 'verified': bool(verified), 'reason': '' if verified else
            'The requested live game change has not been verified on the selected session. Research, attachment, successful reads and queued work do not complete it; keep the request in progress.'}
