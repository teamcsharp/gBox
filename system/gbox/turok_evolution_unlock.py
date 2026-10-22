"""Turok - Evolution (USA) on Nintendo GameCube: exact-revision identity and unlock inventory.

Owned build: Acclaim Cheltenham, "Turok - Evolution" (USA), disc id GTKE51.
This module is READ-ONLY. It records what this exact revision contains and gates the
unlock routine behind verified runtime evidence. Nothing here edits a save, a ROM or a
memory card: the writer path only becomes reachable once the save layout is mapped and
the revision guard below is satisfied.

Identity measured on the owned .gcz in this task workspace (2026-10-21):
  ISO 1459978240 B sha256 07039b4bfe33d49e67b50ad0f222f6b500f4b0941e0d2216fb829e879e71603c
  main.dol 2918144 B sha256 95114308df486b2f0ef08552c12dd681bffac7667a55a267f7c54b1c217cc426
  (text base 0x80003100, 4658 ASCII strings recovered)
  supertree0.tre 846329672 B at ISO offset 613648544 (the content container)
  Game.txt -> DataPath "." , Level "data/levels/u_jcowlishaw/screens/begin/begin.atr"
"""
from __future__ import annotations

import copy
import hashlib
from pathlib import Path

GAME_ID = '103baa3f4d8cea89'
PLATFORM = 'gamecube'
SERIAL = 'GTKE51'
TITLE = 'Turok - Evolution (USA)'

ISO_SHA256 = '07039b4bfe33d49e67b50ad0f222f6b500f4b0941e0d2216fb829e879e71603c'
ISO_SIZE = 1459978240
DOL_SHA256 = '95114308df486b2f0ef08552c12dd681bffac7667a55a267f7c54b1c217cc426'
DOL_SIZE = 2918144
DOL_TEXT_ADDR = 0x80003100
TRE_NAME = 'supertree0.tre'
TRE_SIZE = 846329672
TRE_OFFSET = 613648544
GAME_TXT = 'data/levels/u_jcowlishaw/screens/begin/begin.atr'
BOOT_LEVEL = 'data/levels/u_jcowlishaw/screens/begin/begin.atr'

CATEGORIES = ('characters', 'hidden_characters', 'modes', 'levels', 'stages',
              'costumes', 'items', 'extras')
STATES = ('unlocked', 'not_present', 'unknown')

# Level namespaces referenced by this revision's main.dol string table.
POD_LEVELS = ('Pod-01-Through-The-Jungle',)


def _e(name, state, evidence):
    return {'name': name, 'state': state, 'evidence': evidence}


def build_inventory(pod_levels=None):
    """Category inventory for the exact owned revision, with per-entry evidence.

    State values: 'unlocked' (runtime-verified reachable), 'not_present' (proven
    absent from this revision) or 'unknown' (asset present, lock state not proven).
    No entry may claim 'unlocked' before runtime acceptance on a test worker.
    """
    pods = tuple(pod_levels if pod_levels is not None else POD_LEVELS)
    level_entries = []
    for pod in pods:
        level_entries.append(_e(
            pod, 'unknown',
            "main.dol string data/Levels/%s/<stage>/<stage>.atr - campaign level "
            "namespace present in this revision's string table; menu eligibility "
            "not yet traced" % pod))
    level_entries.append(_e(
        'U_JCowlishaw', 'unknown',
        'main.dol string $/Data/Levels/U_JCowlishaw/Screens/Begin/Begin.atr and '
        'Game.txt Level="data/levels/u_jcowlishaw/screens/begin/begin.atr" - the '
        'front-end screen set of the boot level'))
    level_entries.append(_e(
        'DM_Ruins', 'unknown',
        'main.dol string $\\Data\\Levels\\Multiplayer\\DM_Ruins\\DM_Ruins.atr - '
        'multiplayer level asset present in the disc data'))
    stage_entries = []
    for pod in pods:
        stage_entries.append(_e(
            pod.replace('-', '') + '_stage_id', 'unknown',
            'main.dol string data/Levels/%s/<stage>/<stage>.atr - stage identifier '
            'inside the level namespace of %s' % (pod, pod)))
    return {
        'characters': {
            'entries': [
                _e('U_JCowlishaw', 'unknown',
                   'campaign/boot level namespace of the playable protagonist '
                   '($/Data/Levels/U_JCowlishaw/Screens/...); no separate '
                   'character-select roster was found in the 4658 recovered strings'),
                _e('CompyPlayer', 'unknown',
                   'main.dol string $\\Data\\Actors\\Multiplayer\\Players\\CompyPlayer\\CompyPlayer.atr - '
                   'multiplayer player asset present in the disc data'),
                _e('TalsetPlayer', 'unknown',
                   'main.dol string $\\Data\\Actors\\Multiplayer\\Players\\TalsetPlayer\\TalsetPlayer.atr - '
                   'multiplayer player asset present in the disc data'),
                _e('TalSetPlayer', 'unknown',
                   'main.dol string /Data/Actors/Multiplayer/Players/TalSetPlayer/TalSetPlayer.atr - '
                   'second spelling of the same multiplayer player namespace'),
            ],
            'note': 'No character-select menu was located statically, so the playable '
                    'roster and any hidden selectable character stay unknown.',
        },
        'hidden_characters': {
            'entries': [],
            'note': 'No hidden-character evidence located in this revision (roster, '
                    'select, hidden and secret markers were searched in the recovered '
                    'main.dol string table). Absence of evidence is not proof of absence.',
        },
        'modes': {
            'entries': [
                _e('CheatFly', 'unknown',
                   "main.dol strings 'CheatFly' and 'Cheat-fly mode' - an in-build "
                   'cheat/fly mode exists in this revision; its activation path is '
                   'not yet traced'),
                _e('Multiplayer', 'unknown',
                   'multiplayer actors (CompyPlayer/TalSetPlayer) and the DM_Ruins '
                   'level ship in the disc data, but whether the GameCube build '
                   'exposes the mode in menus is not established by static evidence'),
            ],
            'note': 'Campaign mode is the boot level named in Game.txt.',
        },
        'levels': {'entries': level_entries, 'note': ''},
        'stages': {
            'entries': stage_entries,
            'note': 'Stages are addressed inside the level namespace; the stage/level '
                    'split of this revision is not yet proven from the menu code.',
        },
        'costumes': {
            'entries': [],
            'note': 'No costume/skin system was found in the recovered main.dol string '
                    'table; not proven absent from the build.',
        },
        'items': {
            'entries': [
                _e('ARROW', 'unknown',
                   'main.dol string Y:\\Data\\Actors\\Weapons\\Object\\Arrow\\ARROW\\ARROW.atr - '
                   'weapon object asset present in the disc data'),
                _e('ARROW_EXPLO', 'unknown',
                   'main.dol string Y:\\Data\\Actors\\Weapons\\Object\\Arrow\\ARROW\\ARROW_EXPLO.atr - '
                   'explosive arrow variant asset present in the disc data'),
                _e('ARROW_TEK_POISON', 'unknown',
                   'main.dol string Y:\\Data\\Actors\\Weapons\\Object\\Arrow\\ARROW\\ARROW_TEK_POISON.atr - '
                   'poison arrow variant asset present in the disc data'),
            ],
            'note': 'Weapon assets are present; per-item unlock conditions are unknown.',
        },
        'extras': {
            'entries': [
                _e('Cheats.txm', 'unknown',
                   'main.dol string $\\Data\\Text\\Cheats.txm - cheat list text resource'),
                _e('Cheats.hst', 'unknown',
                   'main.dol string $\\Data\\History\\Cheats.hst - cheat history file'),
                _e('history.txt', 'unknown',
                   'main.dol string $\\Data\\History\\history.txt - history file'),
                _e('ingamesave.atr', 'unknown',
                   'main.dol string ingamesave.atr - in-game save resource; this is the '
                   'candidate carrier of progress/unlock flags'),
                _e('Game.txt', 'unknown',
                   'ISO file Game.txt (78 B): DataPath "." , Level "data/levels/'
                   'u_jcowlishaw/screens/begin/begin.atr"'),
                _e('attract-mode videos', 'unknown',
                   'ISO files data/video/attract.thp, data/video/intro.thp, '
                   'data/video/scity.thp, data/video/english/{end,gamestar,tarkeen,'
                   'tyrannus}.thp and opening.bnr - attract and cutscene media'),
            ],
            'note': 'The save/progress carrier (ingamesave.atr) is identified but its '
                    'layout is not mapped, so no flag offset is claimed.',
        },
    }


INVENTORY = build_inventory()


def disc_identity():
    """The measured identity of the exact owned build this profile is guarded to."""
    return {
        'game_id': GAME_ID, 'platform': PLATFORM, 'serial': SERIAL, 'title': TITLE,
        'iso_sha256': ISO_SHA256, 'iso_size': ISO_SIZE,
        'dol_sha256': DOL_SHA256, 'dol_size': DOL_SIZE, 'dol_text_addr': DOL_TEXT_ADDR,
        'content_archive': TRE_NAME, 'content_archive_size': TRE_SIZE,
        'content_archive_offset': TRE_OFFSET,
        'boot_level': BOOT_LEVEL,
    }


def inventory():
    return copy.deepcopy(INVENTORY)


def category_states():
    return {name: sorted({e['state'] for e in data['entries']})
            for name, data in INVENTORY.items()}


def verify_build(iso_sha256=None, dol_sha256=None):
    """Revision guard: the routine only runs against the exact measured build."""
    if iso_sha256 is not None and iso_sha256 != ISO_SHA256:
        return False
    if dol_sha256 is not None and dol_sha256 != DOL_SHA256:
        return False
    return True


def unlock_ops():
    """Planned, revision-guarded unlock operations for this build.

    These are the operations a writer will perform once the save/progress layout is
    mapped and runtime-verified. They are declarations, not executed writes.
    """
    return [
        {'op': 'map_save_layout',
         'target': 'ingamesave.atr',
         'state': 'not_mapped',
         'why': 'The progress carrier is identified in the main.dol string table but '
                'its byte layout and flag offsets are not yet proven.'},
        {'op': 'unlock_progress',
         'applies_to': ['characters', 'modes', 'levels', 'stages', 'items', 'extras'],
         'state': 'blocked',
         'blocked_on': 'map_save_layout',
         'revision_guard': {'iso_sha256': ISO_SHA256, 'dol_sha256': DOL_SHA256},
         'requires': ['save backup', 'monotonic progress edits', 'rollback path']},
    ]


def apply_unlock(save_path=None, *, iso_sha256=None, dol_sha256=None):
    """Entry point for the on-load routine. Refuses to write until it is proven safe.

    Returns a state dict; 'applied' is only ever True with a verified save layout and
    a matching revision guard, so a mis-dispatched call cannot touch an operator save.
    """
    if not verify_build(iso_sha256, dol_sha256):
        return {'state': 'revision_mismatch', 'applied': False,
                'reason': 'The supplied build digests do not match the measured '
                          'GTKE51 build; no save was touched.'}
    save_state = 'not_supplied'
    if save_path is not None:
        save_state = 'present' if Path(save_path).exists() else 'absent'
    return {'state': 'research_pending', 'applied': False,
            'save_state': save_state,
            'reason': 'The save/progress layout for this revision is not mapped and no '
                      'runtime acceptance has been performed, so no write is allowed.',
            'ops': unlock_ops()}


def profile_gate():
    """Honest gate for the unlock profile: what is proven, what blocks, what is next."""
    ident = disc_identity()
    return {
        'status': 'pending_research',
        'verified': False,
        'reason': 'Identity and category inventory for the exact owned GTKE51 build are '
                  'measured from the disc, but no lock flag, save layout or runtime '
                  'selection has been verified on this revision, so nothing is claimed '
                  'unlocked and no writer is reachable.',
        'scope': list(CATEGORIES),
        'evidence': {
            'identity': ident,
            'inventory': category_states(),
            'sources': [
                'owned .gcz streamed block-by-block and hashed',
                'main.dol string table (4658 ASCII strings) for asset and namespace paths',
                'ISO file table (gcdisc) for sizes, offsets and video extras',
            ],
        },
        'blockers': [
            'save/progress carrier layout (ingamesave.atr) is not mapped',
            'menu eligibility / lock checks are not traced (Ghidra bridge was down this run)',
            'no runtime acceptance on an idle authorized worker yet',
        ],
        'next': 'Map ingamesave.atr on an x64 worker with the Ghidra bridge, trace the '
                'menu eligibility check, then runtime-verify a fresh boot plus a second '
                'launch and rollback on an idle authorized worker (i9-NUC or Spark, 2% audio).',
    }
