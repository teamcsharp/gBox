"""Pinned Switch RE5 / RE6 editions and explicit readiness for the requested No Mercy mode."""
from __future__ import annotations

import hashlib
import re

from . import re6_switch_unlock as RE6U

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

RE6_TITLE_ID = RE6U.TITLE_ID                    # 01002A000CD48000, played with its v131072 update (1.0.2)
RE6_GAME_ID = hashlib.sha1(b'quickswap-switch:Resident Evil 6/Resident Evil 6 [01002A000CD48000].nsp').hexdigest()[:16]
RE6_UPDATE_GAME_ID = hashlib.sha1(
    b'quickswap-switch:Resident Evil 6/Resident Evil 6 [01002A000CD48800][v131072].nsp').hexdigest()[:16]
RE6_DRIVER = 'gbox.mercs.titles.re6_switch'
RE6_REASON = ('Switch RE6 No Mercy runs on Citron NEO with the re6_switch driver: the native menus from boot to a No Mercy '
              'round and back after each round, the round (sGameMan timer / kills / combo / score), the player, the '
              'enemies and the laser sight from RAM (docs/research/re6-switch-ram.md).')
RE6_UNLOCK_REASON = ('A fresh RE6 Switch save forces the Prologue and never opens the main menu, so The Mercenaries and '
                     'No Mercy (both always enabled in EXTRA CONTENT) are unreachable. gBox sets the save\'s own '
                     '"Prologue cleared" bit (cSystemInfo mUnlockFlag bit 0) in RAM at the title screen, read back, and '
                     'the title opens the main menu.')


EDITIONS = {'re5': {'platform': 'switch', 'mode': 'no_mercy', 'title_id': RE5_TITLE_ID},
            're6': {'platform': 'switch', 'mode': 'no_mercy', 'title_id': RE6_TITLE_ID}}


def normalize_preferences(value):
    """{title: edition}: only the reviewed Switch No Mercy editions of RE5 and RE6, each exactly as EDITIONS says."""
    if not isinstance(value, dict) or set(value) - set(EDITIONS):
        raise ValueError('MercMode edition preferences support only RE5 and RE6 (Switch, No Mercy) currently')
    out = {}
    for title, selected in value.items():
        if selected != EDITIONS[title]:
            raise ValueError(f"{title.upper()} edition preference must select Switch {EDITIONS[title]['title_id']} "
                             "No Mercy")
        out[title] = dict(EDITIONS[title])
    return out


def preferred_spec(title, native_spec, settings):
    """The selected edition stays visible and never falls back silently to the native (PS3 / Xbox 360) one."""
    selected = (settings.get('preferred_editions') or {}).get(title)
    if not selected:
        return native_spec
    normalize_preferences({title: selected})
    if title == 're6':
        return {'name': 'Resident Evil 6 (Switch, No Mercy)', 'platform': 'switch',
                'map_id': RE6_TITLE_ID, 'game_ids': (RE6_GAME_ID,), 'playable': True,
                'modes': ['no_mercy'], 'preferred_mode': 'no_mercy', 'stages': 10, 'characters': 4,
                'driver': RE6_DRIVER, 'notes': RE6_REASON}
    return {'name': 'Resident Evil 5 (Switch, No Mercy)', 'platform': 'switch',
            'map_id': RE5_TITLE_ID, 'game_ids': (RE5_GAME_ID,), 'playable': True,
            'modes': ['no_mercy'], 'preferred_mode': 'no_mercy', 'stages': 8, 'characters': 10,
            'driver': DRIVER, 'notes': REASON}


def _serial(game) -> str:
    return str(game.get('serial') or (game.get('launch') or {}).get('title_id') or '').removeprefix('0x').upper()


def _edition(game) -> str | None:
    """'re5' / 're6' for the pinned Switch base games (by title id, else by title when no id is known), else None.
    RE6's update NSP (its own title id and catalog entry) is content for the base game, never an edition."""
    if str(game.get('platform') or '').casefold() != 'switch':
        return None
    serial = _serial(game)
    if serial == RE5_TITLE_ID:
        return 're5'
    if serial == RE6_TITLE_ID:
        return 're6'
    title = re.split(r'[\[(]', str(game.get('title') or ''), maxsplit=1)[0].strip().casefold()
    if re.fullmatch(r'(?:resident\s+evil|biohazard)\s*5', title):
        return 're5'
    if (re.fullmatch(r'(?:resident\s+evil|biohazard)\s*6', title) and not serial
            and game.get('game_id') != RE6_UPDATE_GAME_ID):
        return 're6'
    return None


def capabilities(game):
    edition = _edition(game)
    if edition is None:
        return None
    serial = _serial(game)
    if edition == 're6':
        return {'edition': 're6', 'platform': 'switch', 'backend': 'yuzu', 'serial': serial or None,
                'backends': {'windows': 'yuzu', 'linux': 'citron', 'linux_fallback': 'eden'},
                'requested_mode': 'no_mercy', 'modes_in_release': ['mercenaries', 'no_mercy'],
                'no_mercy_in_release': True, 'full_playback_verified': False,
                'autoplay': {'available': True, 'driver': RE6_DRIVER, 'backend': 'linux', 'reason': RE6_REASON},
                'unlock_on_load': {'available': True, 'needed': True, 'profile': RE6U.PROFILE,
                                   'apply': 'post_launch_ram', 'backend': 'linux', 'reason': RE6_UNLOCK_REASON},
                'evidence': {'title_id': RE6_TITLE_ID,
                             'update': {'title_id': RE6U.UPDATE_TITLE_ID, 'version': RE6U.UPDATE_VERSION,
                                        'game_id': RE6_UPDATE_GAME_ID},
                             'main_build_id': RE6U.MAIN_BUILD_ID, 'main_nso_sha256': RE6U.MAIN_NSO_SHA256,
                             'ram_map': 'profiles/gamedata/01002A000CD48000-ram.json',
                             'research': 'docs/research/re6-switch-ram.md',
                             'unlock_live_acceptance': 'private Citron NEO session on the Spark, 2026-10-26',
                             'runtime_verified_in_gbox': False, 'checked_date': '2026-10-26'}}
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
    if info['edition'] == 're6':
        record = RE6U.profile()
        return {'status': 'verified_profile', 'profile': record['profile'], 'verified': True,
                'game_id': game.get('game_id'), 'platform': 'switch', 'scope': record['scope'],
                'exclusions': record['exclusions'], 'reason': RE6_UNLOCK_REASON, 'capabilities': info,
                'evidence': record['evidence'], 'apply': record['apply'], 'save_effect': record['save_effect'],
                'blockers': ['Applied by Eden sessions on the Linux node (guest memory through /proc/<pid>/mem); '
                             'Yuzu on Windows has no memory access, so it stays manual there.',
                             'Live acceptance ran the same module against Citron NEO, not yet a gBox Eden session.']}
    return {'status': 'not_needed', 'profile': None, 'verified': False,
            'game_id': game.get('game_id'), 'platform': 'switch',
            'scope': ['The Mercenaries: No Mercy', 'Mercenaries characters, costumes and stages'],
            'exclusions': [], 'reason': UNLOCK_REASON, 'capabilities': info, 'evidence': info['evidence'],
            'blockers': ['Characters and costumes beyond the starting four still unlock by play (not measured).'],
            'save_effect': 'No save or game-memory writes are applied by this profile.'}
