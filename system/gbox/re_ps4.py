"""Edition-specific Resident Evil PS4 capabilities; no guessed game writes.

The PS3 RE5 save layout and Xbox 360 RE6 executable/ARC layout are not PS4
profiles. Product content and upstream emulator reports are evidence about
those releases, not evidence that gBox can unlock or autoplay a particular dump.
"""
from __future__ import annotations

import re


_EDITIONS = {
    're5': {
        'name': 'Resident Evil 5', 'report_serial': 'CUSA04437',
        'modes': ['mercenaries_united', 'no_mercy'],
        'content_source': 'https://store.playstation.com/en-us/product/UP0102-CUSA04437_00-RE5HDPS400000000',
        'compatibility_report': 'https://github.com/shadps4-compatibility/shadps4-game-compatibility/issues/178',
        'compatibility_observation': 'https://github.com/shadps4-compatibility/shadps4-game-compatibility/issues/178#issuecomment-5648040893',
        'reported_issues': 'On Windows with shadPS4 0.18.0, reached the first enemy then crashed; cutscene audio desynchronization reported.',
    },
    're6': {
        'name': 'Resident Evil 6', 'report_serial': 'CUSA03856',
        'modes': ['mercenaries', 'no_mercy'],
        'content_source': 'https://news.capcomusa.com/lets/browse/resident-evil-6-is-now-available-on-playstation-4-xbox-one',
        'compatibility_report': 'https://github.com/shadps4-compatibility/shadps4-game-compatibility/issues/179',
        'compatibility_observation': 'https://github.com/shadps4-compatibility/shadps4-game-compatibility/issues/179#issuecomment-5646681563',
        'reported_issues': 'On Windows with shadPS4 0.18.0, still crashes when breaking two boxes at once; graphics and performance issues remain reported.',
    },
}


def capabilities(game: dict) -> dict | None:
    """Describe a PS4 edition without importing a live tool or touching a save.

    Title matching is only for this read-only pending report. A future writer
    must bind a catalog entry, title ID, app version and executable digest.
    """
    if str(game.get('platform') or '').casefold() != 'ps4':
        return None
    launch = game.get('launch') or {}
    serial = str(game.get('serial') or launch.get('title_id') or '').upper()
    edition = next((key for key, data in _EDITIONS.items() if serial == data['report_serial']), None)
    if edition is None:
        # Catalog titles can include a region suffix; do not match unrelated
        # titles such as Resident Evil 50 or a collection containing RE5.
        title = re.split(r'[\[(]', str(game.get('title') or ''), maxsplit=1)[0].strip().casefold()
        match = re.fullmatch(r'(?:resident\s+evil|biohazard)\s*([56])', title)
        if match:
            edition = 're' + match.group(1)
    if edition is None:
        return None
    data = _EDITIONS[edition]
    return {
        'edition': edition, 'platform': 'ps4', 'backend': 'shadps4',
        'serial': serial or None, 'app_ver': launch.get('app_ver'),
        'modes_in_release': list(data['modes']), 'no_mercy_in_release': True,
        'unlock_on_load': {'available': False, 'reason': 'No verified PS4 save or memory unlock profile for this build.'},
        'autoplay': {'available': False, 'reason': 'No verified PS4 menu navigation, combat driver or round-result reader.'},
        'character_replacement': {'available': False, 'reason': 'Existing RE5 PS3 and RE6 Xbox 360 model writers do not support PS4 assets.'},
        'full_playback_verified': False,
        'evidence': {
            'content_source': data['content_source'],
            'compatibility_report': data['compatibility_report'],
            'compatibility_observation': data['compatibility_observation'],
            'report_serial': data['report_serial'], 'report_host_os': 'windows',
            'reported_emulator_version': '0.18.0', 'reported_date': '2026-09-12',
            'checked_date': '2026-10-25', 'reported_status': 'ingame',
            'reported_issues': data['reported_issues'],
            'runtime_verified_in_gbox': False,
        },
    }


def unlock_profile(game: dict) -> dict | None:
    info = capabilities(game)
    if info is None:
        return None
    name = _EDITIONS[info['edition']]['name']
    return {
        'status': 'research_pending', 'profile': None, 'verified': False,
        'game_id': game.get('game_id'), 'platform': 'ps4',
        'scope': ['The Mercenaries: No Mercy', 'Mercenaries characters, costumes and stages'],
        'exclusions': [],
        'reason': f'{name} on PS4 includes No Mercy, but gBox has no verified PS4 unlock-on-load or autoplay profile for this build.',
        'capabilities': info, 'evidence': info['evidence'],
        'blockers': [
            'Bind the extracted PS4 title ID, app version and executable hash.',
            'Verify No Mercy selection and a complete round in the installed shadPS4 build.',
            'Implement and validate the PS4 save/unlock checks and menu/round driver.',
            'Validate fresh boot, second launch and rollback before enabling automatic save changes.',
        ],
        'save_effect': 'None; PS3 and Xbox 360 patches are not applied to PS4.',
    }
