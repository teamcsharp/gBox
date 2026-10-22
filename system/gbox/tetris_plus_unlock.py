"""Tetris Plus (USA) (PSX, SLUS_003.38) - unlock-on-load research anchor.

Milestone scope: the owned revision and its memory-card save layout are pinned
from the disc image itself.  The progress-flag layout, the per-category
inventory and every runtime check are still open, so ``profile_gate()`` reports
an honest pending state and the Play path never reaches a save write here.

Verified on the owned disc (Tetris Plus (USA), serial SLUS_003.38):

* ``SYSTEM.CNF`` -> ``BOOT = cdrom:\\SLUS_003.38;1``.
* Four executables carry the standard PlayStation memory-card block table
  ``bu00:baslus-00338`` (block 0, primary save) and ``bu10:baslus-00338``
  (block 1, backup) plus the enumeration wildcards ``bu00:*`` / ``bu10:*``:
  ``SELECT.EXE`` (option/mode select), ``SW_ON.EXE`` (sound test), ``PAZLE.EXE``
  (puzzle mode) and ``EDIT.EXE`` (puzzle editor).
* The remaining executables (``TITLE``, ``NOMAL``, ``RANKING``, ``VSPUZ``,
  ``TIT_DEMO``, ``HOW_N``, ``HOW_P``, ``HOW_VS``, ``JLOGO``) contain no
  ``bu*:baslus-00338`` literal at all: only those four persist state.

The block *names* are revision-agnostic (they encode the disc serial), but the
payload layout belongs to this executable revision, so any writer must be
guarded on the digests pinned below.
"""
from __future__ import annotations

import re

GAME_ID = 'ecdc312d440ccf98'
PLATFORM = 'psx'
DISC_SERIAL = 'SLUS_003.38'
DISC_TITLE = 'Tetris Plus (USA)'
CATEGORIES = ('characters', 'hidden_characters', 'modes', 'levels', 'stages',
              'costumes', 'items', 'extras')

# Verbatim memory-card block table observed in the four owning executables.
SAVE_BLOCK_TABLE = {
    'SELECT.EXE': {'primary': 'bu00:baslus-00338', 'backup': 'bu10:baslus-00338',
                   'wildcards': ('bu00:*', 'bu10:*'),
                   'addresses': ('0x8002dcb4', '0x8002ddb3', '0x8002deb4', '0x8002df34'),
                   'inferred_role': 'option / mode select'},
    'SW_ON.EXE': {'primary': 'bu00:baslus-00338', 'backup': 'bu10:baslus-00338',
                  'wildcards': ('bu00:*', 'bu10:*'),
                  'addresses': ('0x8002ada8', '0x8002aea7', '0x8002afa8', '0x8002b028'),
                  'inferred_role': 'sound test'},
    'PAZLE.EXE': {'primary': 'bu00:baslus-00338', 'backup': 'bu10:baslus-00338',
                  'wildcards': ('bu00:*', 'bu10:*'),
                  'addresses': ('0x80051244', '0x80051343', '0x80051444', '0x800514c4'),
                  'inferred_role': 'puzzle mode'},
    'EDIT.EXE': {'primary': 'bu00:baslus-00338', 'backup': 'bu10:baslus-00338',
                 'wildcards': ('bu00:*', 'bu10:*'),
                 'addresses': ('0x800450c8', '0x800451c7', '0x800452c8', '0x80045348'),
                 'inferred_role': 'puzzle editor'},
}

# Negative control: these executables hold no memory-card literal.
NO_SAVE_EXECUTABLES = ('TITLE.EXE', 'NOMAL.EXE', 'RANKING.EXE', 'VSPUZ.EXE',
                        'TIT_DEMO.EXE', 'HOW_N.EXE', 'HOW_P.EXE', 'HOW_VS.EXE',
                        'JLOGO.EXE')

EXECUTABLE_SHA256 = {
    "EDIT.EXE": "dd3e4f2ed3c0ba78f39d591b2dbce2ae8c2e60096cf38fa7afce286d2b9c7c2b",
    "PAZLE.EXE": "9118a819b8bc0c3a27066c7c089e6a907ab06fd2d0be84129d135f0833a456d0",
    "SELECT.EXE": "7a2c613433e3b1c68a66e73c0d09b66dee4d0d00177b5c10411331eb1880b2e6",
    "SW_ON.EXE": "ae426700ee36cc2e3c86ea50284bbc05f5ed9a4b288cf7a3adcfd2922fb6993c"
}
DISC_IMAGE = {"error": "no *tetris*.chd under the Sony collection (bounded find, 35s)"}

_HEX64 = re.compile(r'^[0-9a-f]{64}$')


def profile() -> dict:
    """Static evidence for the exact owned revision (no writes, no claims)."""
    return {
        'game_id': GAME_ID,
        'platform': PLATFORM,
        'disc': {'serial': DISC_SERIAL, 'title': DISC_TITLE, 'image': DISC_IMAGE},
        'save_blocks': {name: dict(spec) for name, spec in SAVE_BLOCK_TABLE.items()},
        'executables_without_save_table': list(NO_SAVE_EXECUTABLES),
        'executable_sha256': dict(EXECUTABLE_SHA256),
        'categories': {name: 'unknown' for name in CATEGORIES},
    }


def profile_gate() -> dict:
    """Honest pending state: static evidence only, no writer, no runtime proof."""
    return {
        'status': 'pending_research',
        'verified': False,
        'reason': ('Tetris Plus (USA) SLUS_003.38 is pinned to the owned disc and its '
                   'PSX memory-card block table is mapped, but the progress-flag '
                   'layout, the per-category inventory and every runtime check are '
                   'still open.'),
        'scope': list(CATEGORIES),
        'evidence': {
            'disc_serial': DISC_SERIAL,
            'executable_sha256': dict(EXECUTABLE_SHA256),
            'save_block_table': 'bu00:baslus-00338 / bu10:baslus-00338 (+ bu00:*, bu10:*)',
            'save_block_owners': sorted(SAVE_BLOCK_TABLE),
            'no_save_table': list(NO_SAVE_EXECUTABLES),
            'disc_image': DISC_IMAGE,
            'xref_status': 'unresolved: the block-table literals sit in the text '
                           'segment; the code that opens the card is not yet located',
            'runtime_status': 'no game session exercised; nothing runtime-verified',
        },
        'blockers': [
            'No PSX memory-card image (.mcr/.mcd) and no in-game save sample is '
            'available yet, so the block payload layout is still unmapped.',
            'The read/write routine for the memory-card blocks is not located yet, '
            'so no progress flag offset is known.',
            'The category inventory (characters, hidden_characters, modes, levels, '
            'stages, costumes, items, extras) is not derived from this revision.',
            'No runtime acceptance has been performed, so no unlock is claimed.',
        ],
        'next': [
            'Open SELECT.EXE / PAZLE.EXE in Ghidra on an x64 worker (i9-NUC) via the '
            'gbox ghidra_bridge or REA binary_session and resolve the xrefs to the '
            'pinned table addresses to find the memory-card open/read/write code.',
            'Capture a real save (a short play session on an authorized idle worker: '
            'i9-NUC or Spark, 2% audio) and map the block payload bytes to the flags.',
            'Derive the per-category inventory from the menu code and the flag bits, '
            'then implement the writer guarded on the pinned executable digests, '
            'with a backup and rollback, and runtime-verify every entry.',
        ],
    }
