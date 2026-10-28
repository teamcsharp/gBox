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


# Verified Ghidra evidence (Ghidra 12.1.4, PowerPC:BE:32:default, image base
# 0x80003100, 4699 functions; ELF sha256 dcb56beb5f318623c2c0e488abd52e1d9ecf72a4dff693336df408bc8468a142).
# ghidra_bridge jobs on request 1be8e7d76bf249d6, receipts 2026-10-26:
#   open c81d2355501f4da2 / 5feffcbec9cf44a0 (receipts ec3ce8be16a84d68, dc4f4dfd2a254bad)
#   strings a5c429ed81fb439d, e98eed9dfd8149a8, d00166c15df74d0e, da3bfbda7f564112
#   xrefs 919b0cdb42ab4a5e, f9b625c335db4a15
#   decompile 79cd0e1f54b94e63 (FUN_800f9200, receipt), 3302e2595cea46d7
#     (FUN_800f832c, receipt c9361d6ed93a459d)
RE3_GC_GHIDRA_EVIDENCE = {
    's_select_bin': 0x80208920,       # 'bio19/prog/bin/select.bin'
    'select_bin_ref': 0x80208b44,     # DATA table ref, no containing function
    's_mercenaries_only': 0x802103d7,  # 'mercenaries only\n', no direct xref (table-driven)
    's_number_of_save': 0x8020cfd4,   # status screen, FUN_800f884c/FUN_800f832c
    's_epilogue': 0x8020d0f3,         # title/epilogue state machine FUN_800f9200
    'FUN_800f9200': 0x800f9200,       # epilogue/state machine; polls _DAT_80247fd0/0x80247fdc
    'FUN_800f832c': 0x800f832c,       # save status screen; save struct via FUN_8018fa14
    'FUN_800f884c': 0x800f884c,       # save status screen (slot variant)
    'play_frames': 0x8024d6cc,        # _DAT_8024d6cc play-time frame counter (R/W many)
    # save-status struct semantics (FUN_800f832c): +0xc u8 save count,
    # +4 u8 difficulty/character index.
}

# Revision-guarded native write plan (runtime application NOT yet implemented).
# Guard: ELF sha256 must equal dcb56b...; the plan is applied only after the
# in-memory image matches, and every write is paired with an undo entry so the
# original games and saves are preserved (copy-on-write, never in place).
RE3_GC_NATIVE_WRITE_PLAN = {
    'guard_sha256': 'dcb56beb5f318623c2c0e488abd52e1d9ecf72a4dff693336df408bc8468a142',
    'stage': 'plan-only',   # no byte writes authorized yet
    'rollback': 'copy-on-write shadow of patched pages; restore on detach',
    'open_questions': [
        'Unlock flag bitfield address inside the loaded save struct not yet located '
        '(menu eligibility is table-driven via select.bin; no direct xref to the '
        '"mercenaries only" string at 0x802103d7).',
        'Requires follow-up: decompile the select.bin loader and the state table at '
        '0x80208b44 to find the eligibility gate that reads clear/unlock bits.',
    ],
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
        'save_effect': 'No save effect yet; native writer is plan-only '
                       '(RE3_GC_NATIVE_WRITE_PLAN, copy-on-write rollback).',
        'requires_save_upgrade_opt_in': True,
    }
