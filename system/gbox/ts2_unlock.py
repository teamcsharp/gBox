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
DOL_SHA256 = None
REGION = 'USA'
PENDING_JOBS = ('00847528dcc4438f',)  # re_executable, queued (GPU admission)


def inventory() -> dict:
    """Eight-category inventory; every entry honest-unknown until evidenced."""
    return {c: {'status': 'unknown', 'evidence': None, 'items': []} for c in CATEGORIES}


def revision_guard(dol_sha256: str, region: str) -> bool:
    """True only for the pinned exact build. Rejects everything while unpinned."""
    return DOL_SHA256 is not None and dol_sha256 == DOL_SHA256 and region == REGION


def profile_gate() -> dict:
    return {
        'verified': False, 'status': 'pending_research', 'categories': list(CATEGORIES),
        'reason': 'TS2 (USA, GameCube) executable hash and save/progress gates not yet proven.',
        'evidence': {'executable': DOL_SHA256 or 'unpinned', 'pending_jobs': list(PENDING_JOBS)},
        'blockers': ['re_executable job queued: background GPU admission 70% budget exceeded',
                     'Ghidra function/xref analysis of save-load progress flags pending'],
        'next': 'Read re_executable output, pin DOL SHA-256, trace progress/unlock flags, '
                'then add an isolated-save overlay writer with rollback.',
    }
