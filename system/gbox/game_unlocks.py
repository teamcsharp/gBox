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
DOAPP_ID = '59c55e95af61abbe'  # Dead Or Alive ++ (Korea), platform=arcade
PUYOTETRIS_ID = 'd306523a3f20c360'  # Puyo Puyo Tetris (USA), Switch
NDS_WCW_GAME_ID = 'd9467f457f53f2c7'  # Call of Duty: World at War (USA), NDS


def pre_launch(game: dict, ctx, mod: str = '') -> dict:
    """Fast reviewed launch hooks; background research supplies additional games.

    Never run REA/Ghidra here or infer a write from a title string. Existing RE6
    opt-out settings remain authoritative and its writer retains the save backup.
    """
    profile = profile_for(game)
    if not profile['verified']:
        if game.get('game_id') == DOAPP_ID and game.get('platform') == 'arcade':
            # Registration point for the DOA++ (Korea) arcade unlock work. The
            # fast Play path must never guess a write: report the live static
            # evidence state and hand off to the background research task.
            from . import doapp_unlock
            record = doapp_unlock.profile()
            return {'state': 'research_pending', 'applied': False,
                    'reason': record['reason'],
                    'proven_revisions': record['proven_revisions'],
                    'unknown_counts': record['unknown_counts']}
        if game.get('game_id') == PUYOTETRIS_ID and game.get('platform') == 'switch':
            from . import puyotetris_unlock
            record = puyotetris_unlock.profile()
            return {'state': 'research_pending', 'applied': False, 'reason': record['reason'],
                    'proven_revisions': record['proven_revisions'],
                    'unknown_counts': record['unknown_counts']}
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
    if game.get('game_id') == NDS_WCW_GAME_ID and game.get('platform') == 'nds':
        from . import nds_wcw_unlock
        # Candidate (not gameplay-verified) profile: report the pinned database ops and
        # the live-acceptance plan; never claim verified unlocks here.
        return {'state': 'candidate_pending_verification', 'applied': False,
                'profile': 'nds-wcw-database-candidate-v1',
                'scope': nds_wcw_unlock.profile()['scope'],
                'ops': nds_wcw_unlock.unlock_ops(),
                'next': 'Run live_acceptance_plan on an authorized agent session (i9-NUC/Spark, 2% audio).'}
    return {'state': 'implementation_pending', 'applied': False}


def profile_for(game: dict) -> dict:
    from . import doax2_unlock
    if game.get('game_id') == doax2_unlock.GAME_ID and game.get('platform') == doax2_unlock.PLATFORM:
        # Honest gate for DOAX2: research pending, no verified write targets exist.
        # pre_launch below short-circuits on verified=False, so no writer is reachable.
        return {'status': 'pending_research', 'profile': None, 'verified': False,
                'scope': list(doax2_unlock.CATEGORIES), **doax2_unlock.profile_gate()}
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


# ---- unlock-on-load from held cheat codes (#1986: Soul Calibur II keeps its unlock flags in RAM, loaded from the save)

def code_profile(game: dict) -> dict | None:
    """profiles/gamedata/<game_id>-codes.json: published cheat codes verified in gBox for this exact catalog game
    (platform must match; `verified` must be true). None when the game has no such profile."""
    gid = str(game.get('game_id') or '')
    if not gid or not gid.isalnum():
        return None
    path = Path(__file__).resolve().parent.parent / 'profiles/gamedata' / f'{gid}-codes.json'
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None
    if data.get('platform') != game.get('platform') or data.get('verified') is not True or not data.get('codes'):
        return None
    return data


def post_launch(sid: str, game: dict, hold) -> dict | None:
    """Unlock-on-load for a game with a code profile: once the session runs, each code is held in it (hold(sid,
    lines, desc), what cheats op=add does), so the flags stay set however the game reloads them. The save is never
    edited; the game autosaves what it unlocks. None when the game has no profile."""
    prof = code_profile(game)
    if not prof:
        return None
    held, failed = [], []
    for entry in prof['codes']:
        try:
            hold(sid, list(entry['lines']), str(entry.get('desc') or 'unlock code'))
            held.append(entry.get('desc') or 'unlock code')
        except Exception as exc:                       # noqa: BLE001 - one bad code never fails the launch
            failed.append(f"{entry.get('desc') or 'unlock code'}: {str(exc)[:160]}")
    return {'state': 'applied' if held and not failed else ('partial' if held else 'failed'), 'applied': bool(held),
            'profile': prof.get('profile'), 'held': held, 'failed': failed, 'scope': prof.get('scope') or [],
            'evidence': prof.get('evidence') or {}}
