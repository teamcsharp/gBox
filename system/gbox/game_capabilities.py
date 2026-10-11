"""Evidence-based capability scope; registered roster completion is not full RE."""
from __future__ import annotations
import re
import json
from pathlib import Path
from . import game_unlocks

OPERATIONS = ('source_inventory', 'characters', 'costumes', 'stages',
              'blender_edit', 'native_reimport', 'mod_launch', 'unlocks')
_DIGEST = re.compile(r'^[0-9a-f]{64}$')


def bundled_evidence(game):
    """Audited owned-build source evidence shipped separately from collection state."""
    path = Path(__file__).resolve().parent.parent / 'profiles/gamedata/game-capabilities.json'
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
        return data.get('games', {}).get(game.get('game_id'), {})
    except (OSError, ValueError):
        return {}


def verified_evidence(proof, operation):
    """Require bounded scope, source identity and artifacts before a verified label."""
    if not isinstance(proof, dict) or proof.get('result') != 'passed':
        return False
    if not _DIGEST.fullmatch(str(proof.get('source_sha256', ''))):
        return False
    artifacts = proof.get('artifact_sha256')
    if not isinstance(artifacts, list) or not artifacts or not all(_DIGEST.fullmatch(str(v)) for v in artifacts):
        return False
    if not isinstance(proof.get('scope'), str) or not proof['scope'].strip():
        return False
    if operation in ('native_reimport', 'mod_launch', 'unlocks') and proof.get('runtime_verified') is not True:
        return False
    if proof.get('scope') == 'full_source':
        expected, verified = proof.get('expected'), proof.get('verified')
        if proof.get('inventory_authoritative') is not True or not isinstance(expected, int) or isinstance(expected, bool) or expected <= 0:
            return False
        if not isinstance(verified, int) or isinstance(verified, bool) or verified != expected:
            return False
    return True


def describe(game, entries=(), *, extractor=None, roster=(), writer=None, evidence=None):
    gid = game['game_id']
    own = [m for m in entries if (m.get('source') or {}).get('game_id') == gid]
    characters = [m for m in own if m.get('kind', 'character') == 'character' and not m.get('variant_of')]
    slugs = {m['slug'] for m in characters}
    missing = [r['slug'] for r in roster if r.get('slug') not in slugs]
    mapped = [m['slug'] for m in characters if (m.get('rig') or {}).get('roles')]
    native = bool(writer and writer.get('routed'))
    editable = [m['slug'] for m in own if str(m.get('model', '')).lower().endswith(('.glb', '.gltf', '.blend'))]
    unlock = game_unlocks.profile_for(game)
    capabilities = {
        'source_inventory': {'status': 'unknown', 'supported': False, 'scope': 'full_source',
                             'reason': 'No authoritative all-character/costume/stage inventory verified.'},
        'characters': {'status': 'partial' if characters else 'available' if extractor else 'unsupported',
                       'supported': bool(extractor), 'scope': 'registered_roster_subset', 'extractor': extractor,
                       'registered_roster': len(roster), 'in_collection': sorted(slugs), 'mapped': sorted(mapped),
                       'missing_registered': missing, 'full_source_verified': False},
        'costumes': {'status': 'available' if extractor == 'doa2' else 'partial' if any(m.get('variant_of') for m in own) else 'unknown',
                     'supported': extractor == 'doa2', 'scope': 'native_bound_costumes' if extractor == 'doa2' else 'unverified',
                     'tool': {'tool': 'doa2_assets', 'input': {'op': 'decompose', 'game_id': gid,
                              'fighter': 'all', 'costume': 'all', 'complete_source': True}} if extractor == 'doa2' else None,
                     'full_source_verified': False},
        'stages': {'status': 'partial' if any(m.get('kind') == 'environment' for m in own) else 'unknown',
                   'supported': False, 'scope': 'unverified', 'full_source_verified': False,
                   'reason': 'Frame captures and character extractors do not establish native stage extraction/reimport.'},
        'blender_edit': {'status': 'available' if editable else 'blocked', 'supported': bool(editable),
                         'scope': 'collected_editable_assets', 'assets': editable},
        'native_reimport': {'status': 'implemented_unverified' if native else 'unsupported',
                           'supported': native, 'scope': (writer or {}).get('replaces') or 'unavailable',
                           'writer': (writer or {}).get('writer'), 'slots': (writer or {}).get('slots', []),
                           'reason': 'Runtime acceptance is per donor, target slot, and game build.'},
        'mod_launch': {'status': 'implemented_unverified' if native else 'blocked', 'supported': native,
                       'scope': 'mods produced by the routed native writer', 'runtime_verified': False},
        'unlocks': unlock,
    }
    proofs = bundled_evidence(game) | (evidence or {})
    source_exports = proofs.get('native_fighter_costumes')
    if (extractor == 'doa2' and verified_evidence(source_exports, 'characters')
        and source_exports.get('inventory_authoritative') is True
        and isinstance(source_exports.get('expected'), int) and not isinstance(source_exports.get('expected'), bool)
        and isinstance(source_exports.get('verified'), int) and not isinstance(source_exports.get('verified'), bool)
        and source_exports['expected'] > 0 and source_exports.get('verified') == source_exports['expected']):
        capabilities['characters']['source_exports'] = source_exports
        capabilities['costumes'].update(status='verified', evidence=source_exports,
                                        verified_scope=source_exports['scope'], domain_verified=True)
        capabilities['source_inventory']['verified_fighter_costume_inventory'] = source_exports
    else:
        source_exports = None
    for operation, proof in proofs.items():
        if operation in capabilities and verified_evidence(proof, operation):
            capabilities[operation].update(status='verified', evidence=proof, verified_scope=proof['scope'])
            if proof.get('runtime_verified') is True:
                capabilities[operation]['runtime_verified'] = True
            if proof['scope'] == 'full_source':
                capabilities[operation]['full_source_verified'] = True
    complete = all(capabilities[key].get('full_source_verified') for key in ('source_inventory', 'characters', 'costumes', 'stages'))
    return {'game_id': gid, 'title': game.get('title'), 'platform': game.get('platform'), 'library': game.get('library'),
            'favorite': bool(game.get('favorite')), 'operations': capabilities, 'complete_source_verified': complete,
            'verified_fighter_costume_source': source_exports,
            'any_character_to_any_slot_verified': False}


def backlog(row):
    labels = {'source_inventory': 'Enumerate the owned source and every character/costume/stage',
              'characters': 'Finish native character extraction and rig mapping',
              'costumes': 'Extract every native costume and its complete components',
              'stages': 'Build native stage extraction and reimport',
              'blender_edit': 'Prepare portable editable assets and verify Blender roundtrip',
              'native_reimport': 'Implement or verify native replacement per target slot',
              'mod_launch': 'Verify the rebuilt mod in gameplay with screenshots and saved moments',
              'unlocks': 'Establish an exact-build unlock profile and verify its scope'}
    tasks = []
    for key in OPERATIONS:
        cap = row['operations'][key]
        full_source = key in ('source_inventory', 'characters', 'costumes', 'stages')
        partial_runtime = key in ('native_reimport', 'mod_launch') and cap.get('verified_scope') != 'full_source'
        if (full_source and cap.get('full_source_verified') or key == 'costumes' and cap.get('domain_verified')
            or not full_source and not partial_runtime and cap['status'] == 'verified'
            or key == 'unlocks' and cap.get('verified')):
            continue
        tasks.append({'id': f'{row["game_id"]}:{key}', 'game_id': row['game_id'], 'operation': key,
                      'title': labels[key], 'state': 'needed', 'capability_status': cap['status'],
                      'scope': cap.get('scope'), 'depends_on': [] if key == 'source_inventory' else [f'{row["game_id"]}:source_inventory'],
                      'verified_scope': cap.get('verified_scope'),
                      'acceptance': 'Owned-source identity, bounded inventory coverage, artifacts, and explicit native runtime evidence where applicable.'})
    return tasks
