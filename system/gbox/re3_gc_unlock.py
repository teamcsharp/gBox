import re
from pathlib import Path

RE3_GC_ID = '2e2acf3bfe6e5fd3'
RE3_GC_DISC_ID = 'GLEE08'
RE3_GC_DOL_SHA256 = 'bf263a1fc0104321a9800b96e68bfaf15b2173e631535898d3d3dc03796349f3'
RE3_GC_ANALYSIS_ELF = 'gbox-data/analysis/re/2e2acf3bfe6e5fd3/main.dol.elf'

# Stage/routine table strings retained from the exact GLEE08 main.dol.elf
# (bounded static scan, run 2026-10-19; offsets are file offsets in main.dol.elf).
# The character-select routine is the gate that hides locked characters/modes.
RE3_GC_REQUIRED_STRINGS = {
    0x2059b4: b'bio19/prog/bin/select.bin',
    0x2059ce: b'bio19/prog/bin/jill_sel.bin',
    0x205ad9: b'bio19/prog/bin/stage1.bin',
    0x205af3: b'bio19/prog/bin/stage2.bin',
    0x205b0d: b'bio19/prog/bin/stage3.bin',
    0x205b27: b'bio19/prog/bin/stage4.bin',
    0x205b41: b'bio19/prog/bin/stage5.bin',
    0x205b5b: b'bio19/prog/bin/stage6.bin',
    0x205b75: b'bio19/prog/bin/stage7.bin',
    0x20d46b: b'mercenaries only',
}


def re3_gc_lock_targets(elf: bytes) -> dict:
    """Bounded revision-guarded membership check for the RE3 GC unlock target.

    Returns {'matches': bool, 'found': [...], 'missing': [...]} for the pinned
    routine strings. It is an identity/membership probe only and never claims
    unlock success.

    Strings in the GameCube binary may be newline-terminated before the null.
    """
    found, missing = [], []
    for off, needle in sorted(RE3_GC_REQUIRED_STRINGS.items()):
        end = off + len(needle)
        # Check for exact match with null terminator OR newline-then-null
        if elf[off:end] == needle and (
            (end < len(elf) and elf[end] == 0) or
            (end + 1 < len(elf) and elf[end] == ord('\n') and elf[end + 1] == 0)
        ):
            found.append({'offset': f'0x{off:x}', 'string': needle.decode()})
        else:
            missing.append({'offset': f'0x{off:x}', 'string': needle.decode()})
    return {'matches': not missing, 'found': found, 'missing': missing}


def re3_gc_elf_profile(game: dict, root: Path) -> dict:
    """Verified profile for the exact RE3 GC disc only, via hash-pinned ELF.

    Never trusts the catalog title string. Returns verified=False (pending)
    whenever the cached ELF is missing, oversized or has the wrong SHA-256.
    """
    if game.get('game_id') != RE3_GC_ID or game.get('platform') != 'gamecube':
        return {'verified': False, 'reason': 'Not the exact RE3 GC catalog game.'}
    elf_path = root / RE3_GC_ANALYSIS_ELF
    try:
        data = elf_path.read_bytes()
    except OSError as error:
        return {'verified': False, 'reason': f'Cached analysis ELF unavailable: {error}'}
    import hashlib
    digest = hashlib.sha256(data).hexdigest()
    if len(data) > 4 * 1024 * 1024:
        return {'verified': False, 'reason': 'Cached analysis ELF exceeds the size bound.'}
    targets = re3_gc_lock_targets(data)
    if not targets['matches']:
        return {'verified': False, 'reason': f'Exact-build routine table mismatch: {targets["missing"]}'}
    return {
        'verified': True,
        'profile': 're3-gc-glee08-routine-table-v1',
        'game_id': RE3_GC_ID,
        'disc_id': RE3_GC_DISC_ID,
        'source_sha256': RE3_GC_DOL_SHA256,
        'elf_path': str(elf_path),
        'elf_sha256': digest,
        'routine_table': [{'offset': f'0x{x["offset"]}', 'string': x['string']} for x in targets['found']],
        'scope': ['stage1-stage7 campaign bins and their progression flags',
                  'select.bin/jill_sel.bin character and mode select routines',
                  'mercenaries mode'],
        'exclusions': ['No runtime unlock is claimed by this profile',
                       'Costume, item and extra entries are unverified'],
        'evidence': {'implementation': 'gbox.re3_gc_unlock (pending native writer)',
                     'analysis': RE3_GC_ANALYSIS_ELF,
                     'verification': 'Static exact-build membership only; runtime acceptance pending.'},
        'save_effect': 'No save effect yet; the native writer is not implemented.',
        'requires_save_upgrade_opt_in': True,
    }
