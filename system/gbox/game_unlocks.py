"""Exact-game verified unlock profiles and explicit launch plans.

Planning does not change saves, settings, memory or running sessions. Existing
game tools perform an opted-in profile only after a caller accepts its scope.
An RE/decompiler tool being installed does not constitute an unlock profile.
"""
from __future__ import annotations
import hashlib
import json
from pathlib import Path

RE6_ID = '0871eee3b68cdea3'
MGSVR_ID = 'afd2fc507bb69843'
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
    if game.get('game_id') == MGSVR_ID:
        return {'state': 'needs_running_mission', 'applied': False, 'profile': profile['profile'],
                'scope': profile['scope'], 'exclusions': profile['exclusions'],
                'reason': profile['trigger']}
    return {'state': 'implementation_pending', 'applied': False}


def _mgsvr_profile() -> dict:
    from . import mgs_vr_unlock, mgsvr_inventory
    return {'status': 'verified_profile', 'profile': 'mgsvr-psx-clear-grid-v1', 'verified': True,
            'game_id': MGSVR_ID, 'serial': mgsvr_inventory.SERIAL,
            'exe_sha256': mgsvr_inventory.EXPECTED['exe_sha256'],
            'scope': [f'mission-select entries: {len(mgs_vr_unlock.MENU_BITS)} clear-grid bits '
                      '(training, weapon, advanced, special)'],
            'exclusions': [f'{mgs_vr_unlock.TOTAL_MISSIONS - len(mgs_vr_unlock.MENU_BITS)} of the 300 clear marks have no '
                           'menu table entry (photograph/variety extras) and are not forced'],
            'evidence': {'implementation': 'gbox.mgs_vr_unlock.unlock_all', 'tool': 'mgs_vr op=unlock_all',
                         'verification': 'Rides the game result screen clear-flag store; read-back of grid and patch.'},
            'trigger': 'Not automatic at boot: the grid lives in VRAM, so unlock_all runs only while a VR mission is running '
                       '(it completes that mission), then the menu reads the grid.',
            'auto_on_load': False,
            'save_effect': 'Clear marks reach the memory card only when the player saves from the menu; originals untouched.',
            'requires_save_upgrade_opt_in': True}


def profile_for(game: dict) -> dict:
    if game.get('game_id') == MGSVR_ID:
        return _mgsvr_profile()
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
        if game.get('game_id') == MGSVR_ID:
            unlock = common | {'tool': 'mgs_vr', 'input': {'op': 'unlock_all', 'session_id': session_id}}
            return {'status': 'planned', 'jobs': [unlock], 'executed': False, 'profile': profile,
                    'precondition': profile['trigger']}
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
