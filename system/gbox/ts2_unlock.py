"""TimeSplitters 2 (USA, GameCube) unlock research gate.

Read-only. No writer exists until the owned DOL hash/region/revision and the
save/progress gate functions are proven by REA/Ghidra evidence. pre_launch
reports this state and never writes a save or touches memory.
"""
from __future__ import annotations

GAME_ID = 'a794bc41fdeadf21'
PLATFORM = 'gamecube'
PARENT_REQUEST = '600ead0e94d14d28'
CATEGORIES = ('characters', 'hidden_characters', 'modes', 'levels', 'stages',
              'costumes', 'items', 'extras')
# Pinned only after the re_executable job output is read; None = not yet proven.
DOL_SHA256 = '5c4e544220b7f9576e7f0f78189778b8974caa8c3554a970fea213a8de28e69f'  # main.dol
ELF_SHA256 = 'afbae0df60e189624cec220c2980445bfe2fb0e887fc519596b9c75c91315913'  # converted ELF
DISC_ID = 'GTSE4F'
REGION = 'USA'
ENTRY = 0x80003140
RE_JOB = '00847528dcc4438f'  # re_executable, succeeded
PENDING_JOBS = ()


def inventory() -> dict:
    """Eight-category inventory; every entry honest-unknown until evidenced."""
    return {c: {'status': 'unknown', 'evidence': None, 'items': []} for c in CATEGORIES}


def revision_guard(dol_sha256: str, region: str) -> bool:
    """True only for the pinned exact build. Rejects everything while unpinned."""
    return DOL_SHA256 is not None and dol_sha256 == DOL_SHA256 and region == REGION


def profile_gate() -> dict:
    return {
        'verified': False, 'status': 'pending_research', 'categories': list(CATEGORIES),
        'reason': 'TS2 (USA, GameCube, GTSE4F) DOL pinned; save/progress unlock gates not yet traced.',
        'evidence': {'executable': DOL_SHA256, 'elf_sha256': ELF_SHA256, 'disc_id': DISC_ID,
                     're_job': RE_JOB, 'entry': hex(ENTRY), 'pending_jobs': list(PENDING_JOBS)},
        'blockers': ['Ghidra function/xref analysis of save-load progress flags pending'],
        'next': 'Trace progress/unlock flags in main.dol.elf, '
                'then add an isolated-save overlay writer with rollback.',
    }
