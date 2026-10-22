"""Exact-game verified unlock profiles and explicit launch plans.

Planning does not change saves, settings, memory or running sessions. Existing
game tools perform an opted-in profile only after a caller accepts its scope.
An RE/decompiler tool being installed does not constitute an unlock profile.
"""
from __future__ import annotations
import hashlib
import json
from pathlib import Path

AUF_ID = '65b7187589166b26'
AUF_TEMPLATE_SHA256 = 'a8dcade5456c132494d0bfda9f2ee1aa26776ba93e2ccb3bd7652bccedbc808c'
# Agent test sessions for 007 run on the authorised Spark / i9-NUC workers only;
# the operator's play PC is never used for them.
AUF_TEST_WORKERS = ('spark', 'i9-nuc', 'i9_nuc')


def _auf_profile(game: dict) -> dict:
    """AUF unlock profile: analysis done, on-load unlock not yet runtime-verified.

    The profile is deliberately not 'verified': without a runtime acceptance
    run it must never authorise a save write, so pre_launch stays
    'research_pending'.
    """
    if game.get('platform') != 'gamecube':
        return {'status': 'unsupported', 'profile': None, 'verified': False, 'scope': [],
                'reason': 'The AUF unlock profile covers the GameCube build only.'}
    path = Path(__file__).resolve().parent.parent / 'profiles/gamedata' / f'{AUF_ID}-unlock.json'
    try:
        try:
            template = json.loads(path.read_text(encoding='utf-8'))
        except OSError:
            from .auf_unlock_template import TEMPLATE as template  # embedded mirror
        digest = hashlib.sha256(json.dumps(template, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    except (OSError, ValueError, ImportError) as error:
        return {'status': 'unavailable', 'profile': None, 'verified': False, 'scope': [],
                'reason': f'AUF unlock template unavailable: {error}'}
    if digest != AUF_TEMPLATE_SHA256:
        return {'status': 'unverified', 'profile': None, 'verified': False, 'scope': [],
                'reason': 'AUF template changed; this profile requires new verification.'}
    progression = template.get('progression', {})
    return {'status': 'research_pending', 'profile': 'auf-gc-medal-progression-v1', 'verified': False,
            'game_id': AUF_ID, 'template_sha256': digest,
            'scope': ['campaign mission medal progression (13-mission medal-flag table)',
                      'multiplayer selectable bodies: 15',
                      'campaign levels: 38 (24 mission levels, 16 multiplayer maps)',
                      'items via the runtime give_item path'],
            'exclusions': ['no extras/trophy system in this revision',
                           'no separate alternate campaign agent in this revision'],
            'evidence': {'analysis': 'gbox.auf_unlock_report / gbox.auf_xref / gbox.auf_disasm',
                         'artifact': 'docs/auf-unlock-analysis.json',
                         'template': 'profiles/gamedata/65b7187589166b26-unlock.json',
                         'medal_flags_table': progression.get('medal_flags_table', {}).get('address'),
                         'medal_levels_table': progression.get('medal_levels_table', {}).get('address')},
            'source_verification': 'Addresses are read off the owned disc executable Bond.elf symbol table, '
                                   'not inferred from titles.',
            'save_effect': 'None yet: the on-load unlock has not been runtime-verified, so no save is written.',
            'requires_save_upgrade_opt_in': True,
            'reason': 'Static analysis of the owned executable is complete; the on-load unlock still needs a '
                      'runtime acceptance run before it may be applied.'}


def _auf_launch_plan(game: dict, worker: dict, *, mod: str = '', enable_unlock: bool = False,
                     session_id: str = '', parent_request_id=None) -> dict:
    """AUF agent-test plans: authorised test workers only, never the play PC."""
    name = (worker.get('name') or '').casefold()
    if 'jaybuild' in name:
        raise ValueError('007 agent test sessions must not run on the operator play PC.')
    if not worker.get('id'):
        raise ValueError('A launch plan needs a known test worker.')
    profile = _auf_profile(game)
    if enable_unlock and not profile['verified']:
        return {'status': 'unsupported_unlock', 'profile': profile, 'jobs': [], 'executed': False,
                'reason': profile['reason']}
    common = {'require_worker': worker['id'], 'agent_use': True,
              **({'parent_request_id': parent_request_id} if parent_request_id else {})}
    if session_id:
        if not session_id.startswith(worker['id'] + '-'):
            raise ValueError('The session identifier must belong to the test worker.')
        unlock = common | {'tool': 'auf_live', 'input': {'op': 'give_item', 'on': True, 'session_id': session_id}}
        return {'status': 'planned', 'jobs': [unlock], 'executed': False, 'profile': profile}
    launch = common | {'tool': 'launch_game', 'input': {'game': game, 'mod': mod}}
    return {'status': 'planned', 'jobs': [launch], 'executed': False, 'profile': profile,
            'unlock_after_launch': bool(enable_unlock),
            'audio_policy': 'agent_use on the test worker enforces 2% volume'}
RE6_ID = '0871eee3b68cdea3'
RE6_TEMPLATE_SHA256 = '194cb5b71858f65feeb2b1703642ddc4ffde09b9a087119189b29b0ad7b83f11'


def pre_launch(game: dict, ctx, mod: str = '') -> dict:
    """Fast reviewed launch hooks; background research supplies additional games.

    Never run REA/Ghidra here or infer a write from a title string. Existing RE6
    opt-out settings remain authoritative and its writer retains the save backup.
    """
    profile = profile_for(game)
    if not profile['verified']:
        return {'state': 'research_pending', 'applied': False, 'reason': profile['reason']}
    if game.get('game_id') == RE6_ID and game.get('platform') == 'xbox360':
        from . import re6_tool
        try:
            result = re6_tool.pre_launch(ctx, mod)
        except Exception as exc:
            return {'state': 'failed', 'applied': False, 'reason': str(exc)[:500]}
        unlock = result.get('unlock') or {}
        state = ('disabled' if not result.get('everything_unlocked') else
                 'pending_save' if unlock.get('error') else 'applied')
        return {'state': state, 'applied': state == 'applied', 'profile': profile['profile'],
                'scope': profile['scope'], 'exclusions': profile['exclusions'], 'detail': result}
    return {'state': 'implementation_pending', 'applied': False}


def profile_for(game: dict) -> dict:
    if game.get('game_id') == AUF_ID:
        return _auf_profile(game)
    if game.get('game_id') != RE6_ID or game.get('platform') != 'xbox360':
        return {'status': 'unsupported', 'profile': None, 'verified': False,
                'scope': [], 'reason': 'No verified unlock profile for this exact catalog game/build.'}
    path = Path(__file__).resolve().parent.parent / 'profiles/gamedata' / f'{RE6_ID}-unlock.json'
    try:
        template = json.loads(path.read_text(encoding='utf-8'))
        digest = hashlib.sha256(json.dumps(template, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    except (OSError, ValueError) as error:
        return {'status': 'unavailable', 'profile': None, 'verified': False, 'scope': [],
                'reason': f'Verified RE6 template unavailable: {error}'}
    if digest != RE6_TEMPLATE_SHA256:
        return {'status': 'unverified', 'profile': None, 'verified': False, 'scope': [],
                'reason': 'RE6 template changed; this profile requires new verification.'}
    return {'status': 'verified_profile', 'profile': 're6-x360-native-save-template-v1', 'verified': True,
            'game_id': RE6_ID, 'template_sha256': digest,
            'scope': ['campaign chapters/difficulties present on this Xbox 360 disc', 'skills',
                      'Mercenaries: 9 characters with EX costumes and 3 stages on this disc',
                      'figures/emblems/titles/special features'],
            'exclusions': ['No Hope difficulty', 'Mercenaries No Mercy', 'DLC stages and retro costumes absent from this build'],
            'evidence': {'implementation': 'gbox.re6_tool.unlock_all', 'native_routine': '0x824d8800',
                         'template': 'profiles/gamedata/0871eee3b68cdea3-unlock.json',
                         'verification': 'Native routine invoked in the game and its resulting save recorded.'},
            'source_verification': 'Registered Xbox 360 catalog ID and pinned template; the existing live tool guards the native build before editing memory.',
            'save_effect': 'Existing RE6 tool monotonically upgrades the save and keeps its original backup.',
            'requires_save_upgrade_opt_in': True}


def launch_plan(game: dict, worker: dict, *, mod: str = '', enable_unlock: bool = False,
                allow_save_upgrade: bool = False, session_id: str = '', parent_request_id=None) -> dict:
    """Concrete job plans; no jobs dispatched or operator settings changed."""
    if game.get('game_id') == AUF_ID:
        return _auf_launch_plan(game, worker, mod=mod, enable_unlock=enable_unlock,
                                 session_id=session_id, parent_request_id=parent_request_id)
    if not worker.get('id') or worker.get('name', '').casefold() != 'jaybuiltfinale':
        raise ValueError('Background launch plans must target the designated JAYBUILTFINALE testing worker.')
    if session_id and not session_id.startswith(worker['id'] + '-'):
        raise ValueError('The session identifier must belong to the designated testing worker.')
    profile = profile_for(game)
    if enable_unlock and not profile['verified']:
        return {'status': 'unsupported_unlock', 'profile': profile, 'jobs': [],
                'reason': profile['reason'], 'executed': False}
    if enable_unlock and not allow_save_upgrade:
        return {'status': 'save_upgrade_opt_in_required', 'profile': profile, 'jobs': [], 'executed': False,
                'reason': 'This verified profile changes RE6 save progress; explicit allow_save_upgrade is required.'}
    common = {'require_worker': worker['id'], 'agent_use': True,
              **({'parent_request_id': parent_request_id} if parent_request_id else {})}
    if session_id:
        if not enable_unlock:
            return {'status': 'disabled', 'jobs': [], 'executed': False, 'profile': profile}
        unlock = common | {'tool': 're6', 'input': {'op': 'unlock_all', 'on': True, 'session_id': session_id}}
        return {'status': 'planned', 'jobs': [unlock], 'executed': False, 'profile': profile}
    launch = common | {'tool': 'launch_game', 'input': {'game': game, 'mod': mod}}
    # A real session identifier must be returned before planning the live unlock.
    # No string placeholders are sent into validated tool inputs.
    return {'status': 'planned', 'jobs': [launch], 'executed': False, 'profile': profile,
            'unlock_after_launch': bool(enable_unlock),
            'next': 'Call launch_plan with the returned session_id to produce the opted-in unlock job.' if enable_unlock else None,
            'audio_policy': 'agent_use on the designated worker enforces 2% volume',
            'existing_re6_boot_policy': 'Existing RE6 boot settings are unchanged by this planner.'}
