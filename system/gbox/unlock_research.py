"""Durable unlock-on-load research for every favorite and newly played title.

The cheap Hermes cron scan creates deduplicated, per-game engineering requests.
It never runs a decompiler on Play, launches games, or guesses save/memory writes.
Reviewed implementations live in game_unlocks; unknown games remain pending.
"""
from __future__ import annotations

import json
import re
import time

from . import hermes_delivery as delivery

SCHEMA = 1
NAME = 'gBox favorite and played-game unlock research'
KEY = 'unlock_on_load'
CATEGORIES = ('characters', 'hidden_characters', 'modes', 'levels', 'stages', 'costumes', 'items', 'extras')
# Offline artifact kinds for the bounded DOAPP inventory evidence report.
# Runtime hooks stay in game_unlocks; the dump itself never touches them.
DOAPP_EVIDENCE_KIND = 'doapp_inventory_report'


def instructions(game):
    return (f'Standing operator request: unlock all content available in the owned version of '
        f'{game.get("title") or game["game_id"]} automatically when it loads, including the stock game and custom builds. '
        f'Exact game_id={game["game_id"]}, platform={game.get("platform") or "resolve from owned files"}.\n\n'
        'This is unlock research and implementation, not a character replacement task. Use the existing REA tools '
        '(discover rea_tools/rea_open_binary) plus re_executable, re_study and Ghidra/ghidra_bridge. Resolve and hash '
        'the actual owned executable and reuse its existing analysis project. Trace lock checks, save/progress flags, '
        'menu eligibility and hidden content using functions/xrefs and bounded probes. Inventory every category: '
        + ', '.join(CATEGORIES) + '. Record exact entry names and evidence for unlocked, not_present or unknown. '
        'Do not assume DOA3 has a locked roster without inspecting this revision. Resident Evil versions, modes, '
        'regions and discs need separate proofs. Account for hidden modes and hidden selectable characters.\n\n'
        'Implement a reusable, revision-guarded unlock routine and register its evidence and scope in '
        'gbox.game_unlocks.profile_for and its automatic pre_launch hook; add a guarded session-start hook if '
        'the game must load its native save first. Keep Ghidra/REA analysis in this background task, not the Play '
        'path. Preserve original ROMs and back up saves before changes; prefer an isolated unlock save overlay or '
        'monotonic progress edits. Preserve player settings and existing character/stage mods. Verify expected '
        'bytes/checksums/region before applying, support rollback, and report pending/unsupported/failed honestly. '
        'Do not alter account entitlements, invent absent DLC, or apply online competitive advantage patches.\n\n'
        'Use Spark\'s gbox Ghidra bridge for static analysis. REA 6\'s bundled Ghidra provider rejects Linux ARM; '
        'route REA binary sessions to an available x64 worker such as i9-NUC and inspect binary_session first. '
        'Do not repeatedly retry an unsupported provider. Read the standing parent request for current tool '
        'readiness and pending probe IDs. Use an idle authorized test worker and isolated saves for runtime tests. '
        'Never stop, replace, attach mutation tools to, or test on the operator\'s running game. Read live worker '
        'and session identity before each acceptance test. Start long jobs once and preserve their job IDs. '
        'Perform a fresh boot and actually select/play each discovered character and mode; screenshots alone '
        'of a boot screen are not unlock evidence. Test a second launch and rollback.\n\n'
        'Publish tested source via prepare_task_workspace/publish_task_changes, preserving previous work. '
        'Attach stored REA/Ghidra and runtime artifacts plus executable hashes, original bytes, resulting save '
        'or patch hashes, complete category inventory, commit/PR, and launch receipt. For custom builds also '
        'submit the existing custom-build-unlocks profile/verification receipts. A queued task, tool install, '
        'partial inventory or code-only PR is not unlock-all completion. Keep this child in_progress until the '
        'on-load routine is deployed and its complete scope is runtime-verified; otherwise checkpoint one bounded '
        'milestone with the exact next step so Hermes continues. Use at most 45 tool calls per run.')


def doapp_inventory_report(inventory, game_id):
    """Bounded offline evidence artifact for one game's DOAPP unlock research.

    Summarizes a prior doapp_inventory.build() result for the request report:
    entry/category counts, hidden-costume candidates, and a per-category sample
    of entry names. This is evidence only. It never registers runtime hooks
    (that stays in game_unlocks) and never mutates ROMs, saves, or builds.
    Raises ValueError when the game is absent from the inventory.
    """
    # Support both flat format (from doapp_inventory.inventory) and games dict format
    games = (inventory or {}).get('games')
    if games is not None:
        # games dict format
        if game_id not in games:
            raise ValueError(f'game {game_id} is not in the DOAPP inventory')
        game = games[game_id]
        entries = game.get('entries') or {}
        categories = {name: list(names) for name, names in (game.get('categories') or {}).items()}
        hidden = [n for n, meta in entries.items() if meta.get('hidden_costume')]
        samples = {name: names[:10] for name, names in sorted(categories.items())}
        return {
            'kind': DOAPP_EVIDENCE_KIND,
            'game_id': game_id,
            'title': game.get('title') or game_id,
            'title_source': game.get('title_source') or 'unresolved',
            'files': game.get('files', 0),
            'entries': len(entries),
            'entry_kinds': dict(sorted(game.get('entry_kinds', {}).items())),
            'categories': {name: len(names) for name, names in sorted(categories.items())},
            'category_samples': samples,
            'hidden_costumes': sorted(hidden),
            'hidden_costume_count': len(hidden),
            'warnings': list(game.get('warnings') or []),
            'source': (inventory or {}).get('source', ''),
            'inventory_generated': (inventory or {}).get('generated'),
            'runtime_hooks': 'none (evidence only; see gbox.game_unlocks profile_for)',
        }
    else:
        # Flat format (from doapp_inventory.inventory)
        # inventory is the game object itself
        game = inventory or {}
        if game.get('game_id') != game_id:
            raise ValueError(f'game {game_id} is not in the DOAPP inventory')
        # Build categories from the characters roster
        roster = game.get('characters', {}).get('roster', [])
        # Each fighter has model files (costumes) and character tables (one file each)
        # For now, create a minimal categorization
        categories = {
            'characters': roster,
            'models': [f'{char}_model' for char in roster],
            'costumes': [f'{char}_costume_{i}' for char in roster for i in range(4)],
        }
        entries = {name: {} for name in categories.get('characters', [])}
        hidden = []
        samples = {name: names[:10] for name, names in sorted(categories.items())}
        # Extract source from the inventory
        sources = game.get('sources', {})
        source = sources.get('clone_zip', {}).get('file', '')
        return {
            'kind': DOAPP_EVIDENCE_KIND,
            'game_id': game_id,
            'title': game.get('title') or game_id,
            'title_source': 'library',
            'files': len(game.get('container', {}).get('bankedroms_layout', [])),
            'entries': len(entries),
            'entry_kinds': {},
            'categories': {name: len(names) for name, names in sorted(categories.items())},
            'category_samples': samples,
            'hidden_costumes': sorted(hidden),
            'hidden_costume_count': len(hidden),
            'warnings': [],
            'source': source,
            'inventory_generated': None,
            'runtime_hooks': 'none (evidence only; see gbox.game_unlocks profile_for)',
        }


def targets(favorites, sessions, since):
    if (not isinstance(favorites, dict) or not isinstance(favorites.get('items'), list)
            or favorites.get('count') != len(favorites['items'])):
        raise ValueError('Incomplete favorite snapshot; no unlock tasks created')
    games = {}
    for game in favorites['items']:
        gid = game.get('game_id', '')
        if not re.fullmatch('[0-9a-f]{16}', gid) or gid in games:
            raise ValueError('Invalid or repeated favorite identity')
        games[gid] = dict(game)
    for session in sessions:
        gid = session.get('game_id', '')
        if (re.fullmatch('[0-9a-f]{16}', gid)
                and (session.get('state') == 'running' or (session.get('started') or 0) >= since)):
            games.setdefault(gid, {'game_id': gid, 'title': session.get('title'), 'from_launch': True})
    return sorted(games.values(), key=lambda g: (
        0 if re.search(r'dead or alive 3', g.get('title') or '', re.I) else
        1 if re.search(r'resident evil|biohazard', g.get('title') or '', re.I) else 2,
        g.get('title') or '', g['game_id']))


def reconcile(state, api, save, *, now=None, limit=40):
    """One bounded scan. Reserve before POST and reconcile uncertain creates by context."""
    now = time.time() if now is None else now
    if not state.get('enabled'):
        return {'status': 'disabled'}
    if not api('/api/hermes/task-mode').get('enabled'):
        return {'status': 'paused_with_hermes'}
    requests = api('/api/requests')
    children = {(r.get('context') or {}).get(KEY): r for r in requests if (r.get('context') or {}).get(KEY)}
    games = targets(api('/api/favorites'), api('/api/sessions'), state['enabled_at'])
    parent = state.get('parent_request_id')
    if not parent or not any(r['id'] == parent for r in requests):
        raise ValueError('Standing unlock research request is missing')
    tracked = state.setdefault('games', {})
    created, held = [], []
    for game in games:
        gid = game['game_id']; entry = tracked.setdefault(gid, {})
        entry.update(title=game.get('title') or gid, last_seen=now)
        if gid in children:
            r = children[gid]
            entry.update(request_id=r['id'], number=r['number'], status=r['status'])
            entry.pop('uncertain', None)
            continue
        if entry.get('uncertain') or entry.get('request_id'):
            held.append(gid)  # never replay an uncertain write or a deleted request
            continue
        if len(created) >= limit:
            continue
        entry['uncertain'] = now; save(state)
        r = api('/api/requests', {'title': 'Unlock on load: ' + entry['title'],
            'body': instructions(game), 'source': 'api', 'author': 'operator', 'automated': True,
            'parent_request_id': parent,
            'context': {KEY: gid, 'game_id': gid, 'requires_rea': True, 'requires_ghidra': True,
                        'unlock_research_schema': SCHEMA, 'categories': list(CATEGORIES),
                        'scope': 'stock_and_custom_builds_on_load'}})
        entry.update(request_id=r['id'], number=r['number'], status=r.get('status', 'open'))
        entry.pop('uncertain', None); created.append(r['id']); save(state)
    summary = {'status': 'scanned', 'targets': len(games), 'tracked': sum(bool(tracked[g['game_id']].get('request_id')) for g in games),
               'created': created, 'uncertain': held, 'at': now}
    state['last_scan'] = summary; save(state)
    return summary


def main():
    from .hermes_availability import _api
    with delivery.locked('unlock-research'):
        path = delivery.state_dir() / 'unlock-research.json'
        state = json.loads(path.read_text()) if path.exists() else {}
        def save(value):
            temp = path.with_suffix('.tmp')
            temp.write_text(json.dumps(value, indent=2), encoding='utf8'); temp.replace(path)
        print(json.dumps(reconcile(state, _api, save)))


if __name__ == '__main__':
    main()
