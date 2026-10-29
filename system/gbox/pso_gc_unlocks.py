"""Phantasy Star Online Episode I & II Plus (GameCube, USA) unlock-on-load support.

Holds the revision-guarded evidence profile for the owned build and a guarded
save-overlay writer. The profile is deliberately *unverified* until a live
acceptance run proves every category, so ``gbox.game_unlocks.pre_launch``
short-circuits and no writer is reachable from the fast Play path.

Proven so far (static analysis, 2026-10-20):
  * the owned executable is resolved and hashed: GPOE8P (USA) revision 2, main
    executable ``PsoV3.dol`` sha256 ``1f80fb82...`` (read from the owned disc
    image 436e0bb84d5337d1, not from a copy);
  * the unlock-relevant data files the build reads are named;
  * the guarded writer's backup / expected-bytes / monotonic / rollback
    behaviour is covered by focused tests.

Not proven yet, and therefore recorded as ``unknown``:
  * which save bytes hold the progress flags, and so which characters, modes,
    levels, stages, costumes, items and extras this revision actually gates.
    No category is claimed unlocked and no absent content is invented.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

GAME_ID = '436e0bb84d5337d1'
PLATFORM = 'gamecube'
TITLE = 'Phantasy Star Online Episode I & II Plus (USA)'

# The owned build: GPOE8P (USA) revision 2. The main executable is PsoV3.dol;
# main.dol is only the AppSwitcher bootstrap.
DOL_NAME = 'PsoV3.dol'
DOL_SHA256 = '1f80fb82b41c05b26b6d0545b1ba9c0aa60b52e6589cf32fbb2ffe644692a61a'
# The runtime revision stamp the game checks at 0x80000000.
REVISION_STAMP = b'GPOE8P\x00\x02'

CATEGORIES = ('characters', 'hidden_characters', 'modes', 'levels', 'stages',
              'costumes', 'items', 'extras')

# Read-only data files the build reads for the unlock-relevant tables, named the
# way the executable spells them. They ship with the disc; the progress flags
# live in the save the game writes, whose layout is not resolved yet.
DATA_FILES = ('PsoCardDataTbl_Base.prs', 'PlyLevelTbl.cpt', 'QtOffTitleList_e.rel',
              'ItemPMT.prs', 'ItemRTT.prs', 'ItemMagEdit.prs', 'BattleParamEntry.dat',
              'screen.bin', 'iplist.txt')

BACKUP_SUFFIX = '.gbox-unlock-backup'

_UNRESOLVED = 'the save layout that holds this category flag is not resolved yet'


def profile() -> dict:
    """Honest, unverified profile for this exact catalog game/build."""
    return {
        'status': 'pending_research',
        'profile': 'psogc-plus-unlock-overlay-v0',
        'verified': False,
        'game_id': GAME_ID,
        'platform': PLATFORM,
        'title': TITLE,
        'reason': ('The owned build and its executable are hashed, but no save '
                   'flag has been runtime-proven, so no unlock is applied yet.'),
        'scope': list(CATEGORIES),
        'exclusions': ['No account entitlement or DLC change',
                       'No online competitive advantage patch',
                       'No content that is absent from this revision'],
        'categories': {name: {'state': 'unknown', 'entries': [], 'evidence': _UNRESOLVED}
                       for name in CATEGORIES},
        'evidence': {
            'executable': {'name': DOL_NAME, 'sha256': DOL_SHA256,
                           'source': 'owned disc image 436e0bb84d5337d1 (GPOE8P rev 2)'},
            'revision_stamp': REVISION_STAMP.hex(),
            'data_files': list(DATA_FILES),
            'runtime': 'not yet observed: no live acceptance run for this build',
        },
    }


def plan() -> dict:
    """The guarded writer's plan. Empty until the save layout is proven."""
    return {'state': 'layout_unresolved', 'edits': [], 'reason': _UNRESOLVED,
            'target': 'isolated save overlay only (never the operator card)'}


def pre_launch(game: dict) -> dict:
    """Play-path entry point. Inert until the plan carries proven edits."""
    prof = profile()
    return {'state': 'research_pending', 'applied': False,
            'profile': prof['profile'], 'scope': prof['scope'],
            'reason': prof['reason'], 'writer': plan()}


def revision_guard(stamp: bytes) -> bool:
    """True only for the exact owned revision stamp."""
    return stamp == REVISION_STAMP


def _int_be(data: bytes) -> int:
    return int.from_bytes(data, 'big')


def apply_overlay(save_path, edits, *, dry_run: bool = False) -> dict:
    """Apply guarded, monotonic progress edits to an isolated save overlay.

    Each edit is ``{'offset': int, 'expected': bytes, 'value': bytes,
    'kind': 'progress'|'flag'}``. The file is only written when every edit's
    expected bytes are present; a 'progress' edit may only move a counter
    forward. The original is kept next to the save as
    ``<name>.gbox-unlock-backup`` so :func:`rollback` can restore it.
    """
    data = Path(save_path).read_bytes()
    out = bytearray(data)
    failed = []
    for edit in edits:
        offset = int(edit['offset'])
        expected = bytes(edit['expected'])
        value = bytes(edit['value'])
        if offset < 0 or offset + len(expected) > len(data):
            failed.append({'offset': offset, 'reason': 'out of range'})
            continue
        if data[offset:offset + len(expected)] != expected:
            failed.append({'offset': offset, 'reason': 'expected bytes not present'})
            continue
        if edit.get('kind') == 'progress' and len(expected) == len(value):
            if _int_be(value) < _int_be(expected):
                failed.append({'offset': offset, 'reason': 'progress counter would move backwards'})
                continue
        out[offset:offset + len(value)] = value
    if failed:
        return {'applied': False, 'failed': failed, 'edits': 0,
                'sha256_before': hashlib.sha256(data).hexdigest(),
                'sha256_after': hashlib.sha256(data).hexdigest()}
    report = {'applied': True, 'failed': [], 'edits': len(edits),
              'sha256_before': hashlib.sha256(data).hexdigest(),
              'sha256_after': hashlib.sha256(bytes(out)).hexdigest()}
    if dry_run:
        return report
    save = Path(save_path)
    backup = save.with_name(save.name + BACKUP_SUFFIX)
    backup.write_bytes(data)
    save.write_bytes(bytes(out))
    report['backup'] = str(backup)
    return report


def rollback(save_path, backup_path) -> dict:
    """Restore the byte-exact original from a backup written by apply_overlay."""
    original = Path(backup_path).read_bytes()
    Path(save_path).write_bytes(original)
    return {'rolled_back': True, 'sha256': hashlib.sha256(original).hexdigest()}
