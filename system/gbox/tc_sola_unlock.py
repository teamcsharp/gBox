"""Revision-guarded unlock research for True Crime: Streets of LA (USA) (GameCube).

This module is the on-load unlock registration point for catalog game
b5f07832ba61272a (disc id GTLE52). Everything here is grounded in the owned
revision only:

  * main.dol sha256 55461d07b48b88f0509f2eeab85e3279cd8150672f33137a9d43553d0343a978
    (4,624,192 bytes); the game code at 0x00 is GTLE52.
  * Shell/mc.dat, 5,120 bytes (ten 512-byte memory-card blocks), sha256
    5c08bde8d2cb01f1f8ea37de08305ab964fa63f4104c9e21ea8077a7a2cd1180, is the
    game's own save template. main.dol references that path at 0x80309a44
    (lis 0x8024bc58 + addi 0x8024bc60), next to the "Save data" banner string
    at 0x803099a4.
  * The template holds a 404-byte progress table at 0x0C16..0x0DAA whose last
    bytes are 0xFF; 0xFF is the maximum value the table ever uses, so it is the
    only value that can mean "everything done" in this table.

Nothing here writes a save, a ROM or a progress byte. The byte -> content
mapping is NOT yet proven, so the writer stays unreachable: pre_launch reports
research_pending and apply_ops refuses to write until a proven content map and
a runtime boot exist. Original ROMs and operator saves are never touched.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

GAME_ID = 'b5f07832ba61272a'
PLATFORM = 'gamecube'
DISC_ID = 'GTLE52'
GAME_TITLE = 'True Crime - Streets of LA (USA)'

DOL_SHA256 = '55461d07b48b88f0509f2eeab85e3279cd8150672f33137a9d43553d0343a978'
DOL_SIZE = 4624192
DOL_ENTRY = '0x80003100'
DOL_BSS_ADDR = '0x8046a9c0'
DOL_BSS_SIZE = 640088

MC_DISC_PATH = 'Shell/mc.dat'
MC_SHA256 = '5c08bde8d2cb01f1f8ea37de08305ab964fa63f4104c9e21ea8077a7a2cd1180'
MC_SIZE = 5120
MC_BLOCK_SIZE = 512
MC_BLOCK_COUNT = MC_SIZE // MC_BLOCK_SIZE
MC_FLAG_REGION = (0x0C16, 0x0DAA)
MC_FLAG_REGION_SHA256 = 'c4492df79e380054ecab53c04ad1a9a1a03a89a8b01236b547431a302c4943f0'
MC_COMPLETE_VALUE = 0xFF

MC_PATH_XREF = {'string_vaddr': '0x80309a44', 'lis': '0x8024bc58', 'addi': '0x8024bc60'}
SAVE_BANNER_STRING = {'vaddr': '0x803099a4', 'text': 'Save data'}

CATEGORIES = ('characters', 'hidden_characters', 'modes', 'levels', 'stages',
              'costumes', 'items', 'extras')
PROFILE_REL = 'profiles/gamedata/b5f07832ba61272a-unlock.json'


class UnlockNotProven(RuntimeError):
    """Raised when a write is attempted without a proven byte -> content map."""


def profile_path() -> Path:
    return Path(__file__).resolve().parent.parent / PROFILE_REL


def load_profile() -> dict:
    return json.loads(profile_path().read_text(encoding='utf-8'))


def verify_dol(dol: bytes) -> tuple[bool, str]:
    """True only for the exact owned main.dol revision."""
    if len(dol) != DOL_SIZE:
        return False, f'main.dol size {len(dol)} != {DOL_SIZE}'
    digest = hashlib.sha256(dol).hexdigest()
    if digest != DOL_SHA256:
        return False, f'main.dol sha256 {digest} != {DOL_SHA256}'
    return True, digest


def verify_mc(mc: bytes) -> tuple[bool, str]:
    """True only for the owned save template bytes."""
    if len(mc) != MC_SIZE:
        return False, f'mc.dat size {len(mc)} != {MC_SIZE}'
    digest = hashlib.sha256(mc).hexdigest()
    if digest != MC_SHA256:
        return False, f'mc.dat sha256 {digest} != {MC_SHA256}'
    return True, digest


def progress_table(mc: bytes) -> bytes:
    """The progress-table bytes of a save template or save."""
    if len(mc) != MC_SIZE:
        raise ValueError(f'mc.dat size {len(mc)} != {MC_SIZE}')
    return bytes(mc[MC_FLAG_REGION[0]:MC_FLAG_REGION[1]])


def unlock_ops(mc: bytes, *, complete_value: int = MC_COMPLETE_VALUE) -> list[dict]:
    """Candidate progress-table edits that are not already complete.

    Every op carries content=None: no byte of this table has been proven to
    gate a specific piece of content in this revision, so an op is only ever
    executable once a content map proves it.
    """
    table = progress_table(mc)
    base = MC_FLAG_REGION[0]
    ops = []
    for index, value in enumerate(table):
        if value == complete_value:
            continue
        ops.append({'offset': base + index, 'current': value,
                    'target': complete_value, 'content': None})
    return ops


def apply_ops(mc: bytes, ops: list[dict], content_map: dict | None = None,
              *, backup: bool = True) -> dict:
    """Apply proven unlock ops to a copy of the save template.

    Refuses to write unless every op names content that the caller has proven,
    keeps every write inside the progress-table region, and only ever moves a
    byte forward. The original bytes are returned as a backup for rollback.
    """
    if not ops:
        raise ValueError('no unlock operations to apply')
    content_map = content_map or {}
    unmapped = [op for op in ops
                if not op.get('content') or op['content'] not in content_map]
    if unmapped:
        raise UnlockNotProven(
            f'{len(unmapped)} of {len(ops)} progress bytes have no proven content mapping; '
            'a runtime-verified content map is required before any write')
    out = bytearray(mc)
    lo, hi = MC_FLAG_REGION
    for op in ops:
        offset = int(op['offset'])
        if not lo <= offset < hi:
            raise ValueError(f'offset 0x{offset:04x} is outside the progress table 0x{lo:04x}-0x{hi:04x}')
        if int(op['target']) < out[offset]:
            raise ValueError(f'offset 0x{offset:04x} would move backwards')
        out[offset] = int(op['target'])
    return {'data': bytes(out), 'backup': bytes(mc) if backup else None,
            'applied': len(ops)}


def check_profile_consistency() -> list[str]:
    """Differences between the shipped evidence artifact and this module."""
    problems = []
    try:
        prof = load_profile()
    except (OSError, ValueError) as error:
        return [f'profile artifact unavailable: {error}']
    rev = prof.get('revision', {})
    save = prof.get('save', {})
    if rev.get('dol_sha256') != DOL_SHA256:
        problems.append('profile dol_sha256 differs from module constant')
    if prof.get('disc_id') != DISC_ID:
        problems.append('profile disc_id differs from module constant')
    if save.get('sha256') != MC_SHA256:
        problems.append('profile mc.dat sha256 differs from module constant')
    if list(save.get('flag_region', [])) != list(MC_FLAG_REGION):
        problems.append('profile flag region differs from module constant')
    if save.get('mc_flag_region_sha256') != MC_FLAG_REGION_SHA256:
        problems.append('profile flag-region digest differs from module constant')
    if list(prof.get('categories', [])) != list(CATEGORIES):
        problems.append('profile categories differ from module constant')
    return problems


def profile() -> dict:
    """The registered research state for this exact catalog game and build."""
    problems = check_profile_consistency()
    prof = load_profile()
    return {
        'game_id': GAME_ID,
        'platform': PLATFORM,
        'disc_id': DISC_ID,
        'verified': False,
        'scope': list(CATEGORIES),
        'evidence': {
            'disc_id': DISC_ID,
            'dol_sha256': DOL_SHA256,
            'dol_size': DOL_SIZE,
            'mc_dat_sha256': MC_SHA256,
            'mc_dat_size': MC_SIZE,
            'mc_dat_path': MC_DISC_PATH,
            'progress_table': ['0x%04x' % MC_FLAG_REGION[0], '0x%04x' % MC_FLAG_REGION[1]],
            'progress_table_sha256': MC_FLAG_REGION_SHA256,
            'save_template_xref': MC_PATH_XREF,
            'artifact': PROFILE_REL,
        },
        'inventory': prof.get('inventory', {}),
        'proof_gaps': prof.get('proof_gaps', []),
        'consistency_problems': problems,
    }


def profile_gate() -> dict:
    """The honest gate used by gbox.game_unlocks for this game."""
    state = profile()
    reason = ('True Crime: Streets of LA (USA) is mapped to the owned GTLE52 revision '
              '(main.dol and the Shell/mc.dat save template are hashed), but no progress '
              'byte is yet proven to gate a specific piece of content and no runtime boot '
              'has been performed, so no unlock writer is reachable.')
    return {
        'reason': reason,
        'evidence': state['evidence'],
        'blockers': list(state['proof_gaps']) + list(state['consistency_problems']),
        'next': prof_next(),
    }


def prof_next() -> str:
    return ('Decompile the save routine at main.dol 0x8024bc58 (xref to Shell/mc.dat '
            '0x80309a44) to map each progress-table byte to the content it gates, then '
            'boot the owned build on an idle authorized worker with an isolated save, '
            'select each discovered mode/level/extra, relaunch to prove the unlock '
            'survives a load, and roll back to the original save.')
