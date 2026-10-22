"""Tetris 4D (Japan, Dreamcast) unlock gate: honest research-pending state.

Static disc evidence only. No writer exists and nothing is runtime-verified.
"""
from __future__ import annotations

GAME_ID = '864538c6473a986e'
PLATFORM = 'dc'
CHD_SHA256 = '531a6ce7fb56c8bdb367d9c98eb724b13404d548f0e817e9958a6f55fb456058'
FIRST_READ_SHA256 = '5579d8c6f9e21e570eecb880d4ac52d688c3ba17428ce2cd7be81c9b66a86055'
CATEGORIES = ('modes', 'levels', 'stages', 'options', 'extras')


def profile_gate() -> dict:
    return {
        'verified': False,
        'reason': ('Tetris 4D (Japan) Dreamcast: disc inventory and executable digests are '
                   'pinned, but no unlock flag, cheat code or save layout is mapped and '
                   'nothing has been runtime-verified.'),
        'categories': list(CATEGORIES),
        'evidence': {
            'chd_sha256': CHD_SHA256,
            '1ST_READ.BIN_sha256': FIRST_READ_SHA256,
            'inventory': 'gbox-cache/dc/864538c6473a986e/tetris4d_inventory.json',
            'menu_strings': 'Mode Select, Player Select, Level Select, Sound Select, '
                            'Option Select; MENUMODEL BATTLE/CLASSIC/CONFIG/MAIN/OPTION/SELECT/SOUND/TEST',
        },
        'blockers': [
            'No libretro/cheat-database codes found (search timed out; none verified).',
            'No SH-4 static analysis of 1ST_READ.BIN for the Level/Mode Select gating flags.',
            'No runtime acceptance on an authorized idle worker (i9-NUC/Spark, 2% audio).',
        ],
        'next': 'Open 1ST_READ.BIN (SuperH:LE:32:SH-4) in Ghidra on lilspark/Spark, xref the '
                '"Level Select"/"Mode Select" strings to the gating flags, then verify live.',
    }
