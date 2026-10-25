"""TimeSplitters: Future Perfect (GameCube, USA) unlock profile.

Gecko codes sourced from GameHacking.org for disc G3FE (USA):
  https://gamehacking.org/game/55216

Complete code file recovered from local evidence (G3FE69.txt):
  - "Game 100% Complete" [Codejunkies] — the primary unlock code.
    Sets the progress bitmask at 0x2503488 to 0x0011FFFF (all
    mission/character bits) and patches two code paths
    (0x08502D34, 0x08502F2C) so the flag is honoured on every reload.
    The 0x20150006/0x201B0006 lines are save-slot metadata
    writes (GameCube save block header fields) that mark the
    save as 100% complete so the game recognises the unlock
    on next load.
  - "Infinite Health" [Codejunkies] — patch at 0x040755D0.
  - "Infinite Ammo" [Codejunkies] — patches at 0x041A9BA0, 0x041A9BCC.
  - "Some Timers Frozen" [Codejunkies] — patch at 0x04127D1C.
  - "Player 1 1st/3rd Person Mode" [Jay007] — control-flow patch.

Save file context (GameCube):
  - TimeSplitters FP uses standard GameCube save blocks.
  - The game stores progress in a dedicated save block; the
    bitmask at 0x2503488 lives in game RAM (not the save file
    directly) — Gecko codes patch RAM at runtime.
  - To achieve a persistent save-based unlock, the game must
    be launched with the Gecko code active, allowed to write
    a save, then the save file can be reused.
  - Alternative: direct save-file editing at the offset
    corresponding to 0x2503488 minus the save block's base
    address (requires save file format analysis of the
    owned .gcz, job 08bd2cf516ff47de pending).

No runtime verification has been performed on this machine; the codes
are published community codes, not gBox-verified.  The profile is a
candidate profile that requires live acceptance on an authorized
agent session before it may be marked verified.
"""
from __future__ import annotations

GAME_ID = '1ccdf2aa4bfe4b32'
PLATFORM = 'gamecube'
GAME_CODE = 'G3FE'
DISC_ID = 'G3FE69'
SOURCE = 'https://gamehacking.org/game/55216'
AUTHOR = 'Codejunkies'
CODE_DESC = 'Game 100% Complete'

# ── "Game 100% Complete" unlock code ──────────────────────────────
CODE_LINES = [
    '02503488 0011FFFF',
    '08502D34 00000004',
    '20150006 00000000',
    '08502F2C 00000004',
    '201B0006 00000000',
]

# The primary unlock write: address 0x503488, value 0x0011FFFF.
UNLOCK_ADDRESS = 0x02503488
UNLOCK_VALUE = 0x0011FFFF

# ── Additional known codes (same source file, G3FE69.txt) ─────────
# Infinite Health [Codejunkies]
INFINITE_HEALTH_LINES = [
    '040755D0 C02301D8',
    '040755D4 D02301CC',
    '040755DC 4800000C',
]
# Infinite Ammo [Codejunkies]
INFINITE_AMMO_LINES = [
    '041A9BA0 60000000',
    '041A9BCC 60000000',
]
# Some Timers Frozen [Codejunkies]
TIMERS_FROZEN_LINES = [
    '04127D1C 60000000',
]
# Player 1 1st/3rd Person Mode [Jay007]
PERSON_MODE_LINES = [
    '284B114A 00000208',
    '48000000 80611D54',
    'DE000000 80008180',
    '1200021E 00004733',
    'E2000001 80008000',
    '48000000 80611D54',
    'DE000000 80008180',
    '1000021B 00000018',
    'E2000002 80008000',
    '284B114A 00000204',
    '48000000 80611D54',
    'DE000000 80008180',
    '1200021E 00004437',
    'E2000001 80008000',
    '48000000 80611D54',
    'DE000000 80008180',
    '1000021B 00000000',
    'E2000002 80008000',
]

# All codes in the G3FE69.txt file, grouped by feature.
ALL_CODES = {
    'Game 100% Complete': CODE_LINES,
    'Infinite Health': INFINITE_HEALTH_LINES,
    'Infinite Ammo': INFINITE_AMMO_LINES,
    'Some Timers Frozen': TIMERS_FROZEN_LINES,
    'Player 1 1st/3rd Person Mode': PERSON_MODE_LINES,
}

# Scope categories the code covers (per the "Game 100% Complete" description).
CATEGORIES = ('missions', 'characters', 'modes', 'items', 'stages')

# Save file analysis status: pending extraction from owned .gcz.
# Job 08bd2cf516ff47de (re_executable) is queued on lilspark,
# waiting for operator gameplay to end.
SAVE_FILE_STATUS = 'pending_extraction'
SAVE_FILE_JOB_ID = '08bd2cf516ff47de'


def profile() -> dict:
    """Candidate unlock profile for this exact catalog game."""
    return {
        'profile': 'tsfp-gc-gecko-100pct-v1',
        'game_id': GAME_ID,
        'platform': PLATFORM,
        'disc_id': DISC_ID,
        'verified': False,
        'complete_unlock_profile': False,
        'gameplay_verified': False,
        'source': SOURCE,
        'author': AUTHOR,
        'desc': CODE_DESC,
        'codes': CODE_LINES,
        'all_codes': {k: list(v) for k, v in ALL_CODES.items()},
        'scope': list(CATEGORIES),
        'unlock_ops': [
            {
                'address': UNLOCK_ADDRESS,
                'width': 4,
                'hex_bytes': format(UNLOCK_VALUE, '08x'),
                'gameplay_verified': False,
            }
        ],
        'save_file_status': SAVE_FILE_STATUS,
        'save_file_job_id': SAVE_FILE_JOB_ID,
        'reason': (
            'Published Gecko code from GameHacking.org (Codejunkies); '
            'not runtime-verified on gBox. Live acceptance required on '
            'an authorized agent session (i9-NUC or Spark) before '
            'this profile may be marked verified. Save file format '
            'analysis pending extraction of the owned .gcz '
            f'(job {SAVE_FILE_JOB_ID} queued on lilspark).'
        ),
    }


def profile_gate() -> dict:
    """Gate response for the Play path: research pending, no writer."""
    p = profile()
    return {
        'reason': p['reason'],
        'evidence': {
            'source': SOURCE,
            'author': AUTHOR,
            'desc': p['desc'],
            'codes': list(CODE_LINES),
            'all_codes': {k: list(v) for k, v in ALL_CODES.items()},
            'code_file': '/tmp/g3fe69.txt (G3FE69 — TimeSplitters Future Perfect)',
            'code_features': list(ALL_CODES.keys()),
        },
        'blockers': [
            'No runtime verification on gBox session',
            'Gecko code injection requires live GameCube session',
            'Disc identity (G3FE) must be confirmed from owned catalog',
            f'Save file format analysis pending (job {SAVE_FILE_JOB_ID})',
        ],
        'next': (
            'Run live acceptance on an authorized agent session: '
            'launch the game with the Gecko code held via '
            'game_unlocks.post_launch, confirm all missions/characters '
            'are unlocked in-game, then mark the profile verified. '
            f'Await completion of job {SAVE_FILE_JOB_ID} for save file '
            'format analysis to enable persistent save-based unlock.'
        ),
    }
