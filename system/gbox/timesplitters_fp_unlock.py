"""TimeSplitters: Future Perfect (GameCube, USA) unlock profile.

Gecko codes sourced from GameHacking.org for disc G3FE (USA):
  https://gamehacking.org/game/55216

The "Game 100% Complete" code by Codejunkies sets the unlock flag at
0x503488 to 0x0011FFFF (a bitmask of all mission/character bits) and
patches two code paths so the flag is honoured on every reload.

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

# Gecko code lines, one unlock entry.
CODE_LINES = [
    '02503488 0011FFFF',
    '08502D34 00000004',
    '20150006 00000000',
    '08502F2C 00000004',
    '201B0006 00000000',
]

# The primary unlock write: address 0x503488, value 0x0011FFFF.
UNLOCK_ADDRESS = 0x503488
UNLOCK_VALUE = 0x0011FFFF

# Scope categories the code covers (per the "Game 100% Complete" description).
CATEGORIES = ('missions', 'characters', 'modes', 'items', 'stages')


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
        'scope': list(CATEGORIES),
        'unlock_ops': [
            {
                'address': UNLOCK_ADDRESS,
                'width': 4,
                'hex_bytes': format(UNLOCK_VALUE, '08x'),
                'gameplay_verified': False,
            }
        ],
        'reason': (
            'Published Gecko code from GameHacking.org (Codejunkies); '
            'not runtime-verified on gBox. Live acceptance required on '
            'an authorized agent session (i9-NUC or Spark) before '
            'this profile may be marked verified.'
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
        },
        'blockers': [
            'No runtime verification on gBox session',
            'Gecko code injection requires live GameCube session',
            'Disc identity (G3FE) must be confirmed from owned catalog',
        ],
        'next': (
            'Run live acceptance on an authorized agent session: '
            'launch the game with the Gecko code held via '
            'game_unlocks.post_launch, confirm all missions/characters '
            'are unlocked in-game, then mark the profile verified.'
        ),
    }
