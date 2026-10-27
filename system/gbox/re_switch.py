"""Pinned Switch RE5 edition and explicit readiness for the requested No Mercy mode."""
from __future__ import annotations

import hashlib
import re

RE5_TITLE_ID = '010018100CD46000'
RE5_GAME_ID = hashlib.sha1(b'quickswap-switch:Resident Evil 5/Resident Evil 5.nsp').hexdigest()[:16]
RE5_PROGRAM_SHA256 = '15af72f22608689dc8a668105f01bf6161a79e8528dd991dcdedbee05e2d1174'
RE5_MAIN_BUILD_ID = 'EBFFDB223149A725A93CD9B60979F6AA'
CONTENT_SOURCE = 'https://www.nintendo.com/en-gb/Games/Nintendo-Switch-download-software/Resident-Evil-5-1575781.html?nsuid=70010000015874'
DRIVER = 'gbox.mercs.titles.re5_switch'
REASON = ('Switch RE5 No Mercy runs on Eden (single-core) with the re5_switch driver: RAM map measured live '
          '2026-10-26 (player, enemies, cGameSys timer / kills / combo / score, native menus to No Mercy); '
          'the brain is a first cut (face, aim, fire, break free) without time bonuses or the laser-sight aim.')
UNLOCK_REASON = 'No Mercy is selectable from a fresh save (Extra Content > The Mercenaries United); no unlock is needed.'


def normalize_preferences(value):
    if not isinstance(value, dict) or set(value) - {'re5'}:
        raise ValueError('MercMode edition preferences support only RE5 currently')
    if not value:
        return {}
    expected = {'platform': 'switch', 'mode': 'no_mercy', 'title_id': RE5_TITLE_ID}
    if value.get('re5') != expected:
        raise ValueError('RE5 edition preference must select Switch 010018100CD46000 No Mercy')
    return {'re5': dict(expected)}


def preferred_spec(title, native_spec, settings):
    """The selected edition stays visible and never falls back silently to the native (PS3) one."""
    selected = (settings.get('preferred_editions') or {}).get(title)
    if not selected:
        return native_spec
    normalize_preferences({title: selected})
    return {'name': 'Resident Evil 5 (Switch, No Mercy)', 'platform': 'switch',
            'map_id': RE5_TITLE_ID, 'game_ids': (RE5_GAME_ID,), 'playable': True,
            'modes': ['no_mercy'], 'preferred_mode': 'no_mercy', 'stages': 8, 'characters': 10,
            'driver': DRIVER, 'notes': REASON}


def capabilities(game):
    if str(game.get('platform') or '').casefold() != 'switch':
        return None
    serial = str(game.get('serial') or (game.get('launch') or {}).get('title_id') or '').removeprefix('0x').upper()
    title = re.split(r'[\[(]', str(game.get('title') or ''), maxsplit=1)[0].strip().casefold()
    if serial != RE5_TITLE_ID and not re.fullmatch(r'(?:resident\s+evil|biohazard)\s*5', title):
        return None
    return {'edition': 're5', 'platform': 'switch', 'backend': 'yuzu', 'serial': serial or None,
            'backends': {'windows': 'yuzu', 'linux': 'citron', 'linux_fallback': 'eden'},   # gbox.adapters.YuzuAdapter /
            # CitronLinuxAdapter (multi-core, canonical since 2026-10-26) / SwitchLinuxAdapter (Eden, single-core)
            'requested_mode': 'no_mercy', 'modes_in_release': ['mercenaries_united', 'no_mercy'],
            'no_mercy_in_release': True, 'full_playback_verified': False,
            'autoplay': {'available': True, 'driver': DRIVER, 'backend': 'linux', 'reason': REASON},
            'unlock_on_load': {'available': False, 'needed': False, 'reason': UNLOCK_REASON},
            'evidence': {'content_source': CONTENT_SOURCE, 'title_id': RE5_TITLE_ID,
                         'base_version': 0, 'program_nca_sha256_from_cnmt': RE5_PROGRAM_SHA256,
                         'main_build_id': RE5_MAIN_BUILD_ID, 'ram_map': 'profiles/gamedata/010018100CD46000-ram.json',
                         'runtime_verified_in_gbox': True, 'checked_date': '2026-10-26'}}


def unlock_profile(game):
    info = capabilities(game)
    if info is None:
        return None
    return {'status': 'not_needed', 'profile': None, 'verified': False,
            'game_id': game.get('game_id'), 'platform': 'switch',
            'scope': ['The Mercenaries: No Mercy', 'Mercenaries characters, costumes and stages'],
            'exclusions': [], 'reason': UNLOCK_REASON, 'capabilities': info, 'evidence': info['evidence'],
            'blockers': ['Characters and costumes beyond the starting four still unlock by play (not measured).'],
            'save_effect': 'No save or game-memory writes are applied by this profile.'}
