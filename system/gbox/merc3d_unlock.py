"""Resident Evil: The Mercenaries 3D (3DS) unlock research profile - candidate stage.

Facts that gate every write for this title:

  * progress lives in the 3DS save and the game can erase its own save, so a
    writer must copy the save aside first and must never delete or truncate it;
  * the citra_libretro core exposes no memory map to gBox, so unlocks cannot be
    applied in RAM the way the RE4/RE5/RE6 tools do.

No save byte offset of this build is verified against a real save yet, so this
module performs no write: it reports the research state, the evidence collected
so far and the next verification step.  ``apply_unlock`` refuses until a layout
is verified, and ``unlock_ops`` stays empty so no caller can be handed a
guessed offset.
"""
from __future__ import annotations

import hashlib
import shutil
from pathlib import Path

CATALOG_GAME_ID = '0ed22ae742e1b56b'   # Resident Evil: The Mercenaries 3D (3DS)
PLATFORM = '3ds'
TITLE = 'Resident Evil: The Mercenaries 3D'
CODE_BASE = 0x100000
CODE_SHA256 = '85a34c86eb62597d89f1dc48b2e75dc7f4b25fdfeed7def086f93e875e5821be'
BACKUP_SUFFIX = '.gbox-backup'

SCOPE: list[str] = []
EXCLUSIONS = [
    'No verified unlock target yet: no save offset of this build is confirmed.',
    'The operator save is never deleted, truncated or replaced by this module.',
    'No RAM write path exists for this title (citra_libretro exposes no memory map).',
]


def _sha256(path) -> str:
    h = hashlib.sha256()
    with open(path, 'rb') as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def profile() -> dict:
    """Research state for this exact build.

    ``verified`` stays False until a save layout is confirmed against a real
    save of this title; callers must not treat this profile as an unlock.
    """
    return {
        'status': 'research_pending',
        'verified': False,
        'title': TITLE,
        'game_id': CATALOG_GAME_ID,
        'platform': PLATFORM,
        'scope': list(SCOPE),
        'exclusions': list(EXCLUSIONS),
        'reason': ('Resident Evil: The Mercenaries 3D keeps its unlocks in the 3DS save and the '
                   'citra_libretro core exposes no memory map, so no save offset of this build is '
                   'verified yet; this profile performs no write.'),
        'evidence': {
            'code_sha256': CODE_SHA256,
            'code_base': CODE_BASE,
            'binary_tools': ['gbox.merc3d_exe', 'gbox.merc3d_inventory', 'gbox.ctr_romfs'],
            'member_names_present': ['mSaveData', 'mUnlock', 'mGameFlags', 'mIDTrofy',
                                     'mRecord', 'mSkill', 'mAchievement'],
            'verified_facts': [
                'member-name strings exist in the decompressed .code of this build',
                'no pointer table binding those names was found in the scanned image',
            ],
        },
        'next': ('Locate the Citra save for this title, map the unlock bitfield against a real '
                 'save, verify the write by re-reading the saved file, and only then publish a '
                 'writer with pinned offsets.'),
    }


def unlock_ops() -> list:
    """Pinned write operations. Empty while the layout is unverified."""
    return []


def find_save_files(root) -> list[dict]:
    """Candidate save files for this title under ``root`` (Citra save trees)."""
    root = Path(root)
    out: list[dict] = []
    if not root.exists():
        return out
    for path in sorted(root.rglob('*')):
        if not path.is_file():
            continue
        if not any('mercenar' in part.lower() for part in path.parts):
            continue
        try:
            size = path.stat().st_size
        except OSError:
            continue
        out.append({'path': str(path), 'size': size, 'sha256': _sha256(path)})
    return out


def backup_save(path) -> str:
    """Copy the save aside before any future write; returns the backup path.

    The original is never deleted, truncated or moved.
    """
    src = Path(path)
    dst = src.with_name(src.name + BACKUP_SUFFIX)
    shutil.copy2(src, dst)
    return str(dst)


def apply_unlock(path, ops=None) -> dict:
    """Refuse to write: the save layout of this title is not verified."""
    return {'state': 'refused', 'applied': False,
            'reason': 'No verified save layout for this title; unlock_ops() is empty and no byte is written.',
            'path': str(path), 'ops': list(ops or unlock_ops())}
