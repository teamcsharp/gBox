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
RE6_TEMPLATE_SHA256 = '194cb5b71858f65feeb2b1703642ddc4ffde09b9a087119189b29b0ad7b83f11'

DOA2_ID = '3dd7e33362597f85'
DOA2_FIRST_READ_SHA256 = '105056d9ffef86bf5e470fa28dc5907443156f9ab1c6bc009f73661d9c047a85'
DOA2_PRODUCT = 'T3601N'
DOA2_VERSION = 'V1.100'


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
    if game.get('game_id') == DOA2_ID and game.get('platform') == 'dreamcast':
        return {
            'status': 'research_pending',
            'profile': 'doa2-us-research-stub-v1',
            'verified': False,
            'game_id': DOA2_ID,
            'product': DOA2_PRODUCT,
            'version': DOA2_VERSION,
            'first_read_sha256': DOA2_FIRST_READ_SHA256,
            'scope': [
                '17 characters: 13 regular + Tengu + Ein (KAS AYA LEI TIN BAS JAN GEN BAY '
                'RYU ZAC HIK TNG KTE) plus LOR MAM WBA YTI story variants',
                'no SAM/Leon, no PDG variant (Limited Edition only)',
            ],
            'exclusions': [
                'No SAM/Leon family',
                'No PDG variant',
                'No runtime verification performed',
            ],
            'reason': (
                'Research pending: owned DOA2 US .7z disc set (first-read SHA256 '
                '105056d9ffef86bf5e470fa28dc5907443156f9ab1c6bc009f73661d9c047a85) not '
                'extracted on this node; Ghidra/REA lock/progress xref analysis not yet '
                'performed on the resolved T3601N V1.100 1ST_READ.BIN executable. '
                'Hash-only result from job 2fdd3f0e1c21459d is preserved but insufficient.'
            ),
            'evidence': {
                'hash_job': '2fdd3f0e1c21459d',
                'hash_job_output': {
                    'crc32': '684f5179',
                    'sha1': '4349ed13d350d1297011729306879a7f5befc396',
                    'size': 252886868,
                },
                'inventory': 'gbox.doa2usa_inventory (build_matches=True on owned disc)',
                'expected_roster': ['KAS', 'AYA', 'LEI', 'TIN', 'BAS', 'JAN', 'GEN', 'BAY',
                                     'RYU', 'ZAC', 'HIK', 'TNG', 'KTE', 'LOR', 'MAM', 'WBA', 'YTI'],
            },
            'blocker': (
                'Owned DOA2 US .7z not extracted on this node; no runtime launch test '
                'performed. A bounded Ghidra/REA inspection on i9-NUC (worker '
                'eb99ab24ec5e420c) is needed to resolve lock/progress xrefs before '
                'the profile can be marked verified.'
            ),
            'source_verification': (
                'Registered Dreamcast catalog ID 3dd7e33362597f85; pinned first-read '
                'SHA256 105056d9ffef86bf5e470fa28dc5907443156f9ab1c6bc009f73661d9c047a85; '
                'product T3601N V1.100. No verified unlock profile yet.'
            ),
            'requires_save_upgrade_opt_in': False,
        }
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
