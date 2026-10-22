"""Resident Evil 4 on GameCube -- "P.N. 03 (USA)" (disc GPNE08): unlock research profile.

Owned-disc identity (read-only, verified):
  disc header game code  GPNE08, header title "P.N.03"
  catalog               game_id 0369bdbf9347869a, platform gamecube
  main.dol              1593280 bytes, sha256 0f8e93089581128fe57dace4a6f3339021d9266616a3e922110678be52b8bcb6
  Ghidra ELF (gbox.gcdisc.dol_to_elf) sha256 10017d633444fc5f0829e238aa2a231dc9fe6bda31b6fb3fe452b3a677de10fd
  Ghidra: image base 0x80003100, language PowerPC:BE:32:default, 5357 functions

This disc is NOT the other owned RE4 GameCube disc ("Resident Evil 4 (USA) (Disc 1)",
disc G4BE08, catalog 78ab9efa2e310db4): that disc has its own readers in gbox/re4gc_*.py
and none of their evidence applies here.

This module is a REVISION GUARD plus the evidence table for the writer that is still to
come.  It performs NO save or ROM write.  The unlock flags for this revision are not
yet proven, so profile()["verified"] is False and game_unlocks.pre_launch() must not
write anything; the research report records what is still missing.
"""
from __future__ import annotations

import copy
import hashlib

GAME_ID = '0369bdbf9347869a'
PLATFORM = 'gamecube'
TITLE = 'P.N. 03 (USA)'
DISC_ID = 'GPNE08'
DISC_HEADER_TITLE = 'P.N.03'
MAIN_DOL_SHA256 = '0f8e93089581128fe57dace4a6f3339021d9266616a3e922110678be52b8bcb6'
MAIN_DOL_SIZE = 1593280
MAIN_ELF_SHA256 = '10017d633444fc5f0829e238aa2a231dc9fe6bda31b6fb3fe452b3a677de10fd'
GHIDRA_IMAGE_BASE = '0x80003100'
GHIDRA_LANGUAGE = 'PowerPC:BE:32:default'
GHIDRA_FUNCTIONS = 5357
FST_ENTRIES = 700

CATEGORIES = ('characters', 'hidden_characters', 'modes', 'levels', 'stages',
              'costumes', 'items', 'extras')

# The save/progress tables the game loads from the disc (etc/*.dat) and, where the
# loader was located in main.elf, the Ghidra function that reads it.
SAVE_TABLES = (
    {'file': 'etc/card.dat', 'kind': 'card', 'loader': 'FUN_8001c5ac',
     'load_call': 'FUN_8007b744(0xffff, s_etc_card_dat_80163f38, 0, 0, 0, 0x104, 0x10, param_1 + 0x24)',
     'container': 'TPL@0x14 IDD@0x18 TPL@0x1C MDT@0x24', 'size': 1014912},
    {'file': 'etc/continue.dat', 'kind': 'continue', 'loader': 'FUN_8007a290',
     'load_call': 'FUN_8007b744(0xffff, s_etc_continue_dat_80168f44, 0x80480000, 0, 0, 0x104, 0, 0)',
     'container': 'TPL@0x0C IDD@0x10', 'size': 468096},
    {'file': 'etc/title.dat', 'kind': 'title', 'loader': None, 'load_call': None,
     'container': 'TPL@0x0C IDD@0x10', 'size': 1062048},
    {'file': 'etc/allResult.dat', 'kind': 'all_result', 'loader': None, 'load_call': None,
     'container': 'IDD@0x1C TPL@0x20 IDD@0x24 TPL@0x28 TPL@0x2C TPL@0x30', 'size': 608192},
    {'file': 'etc/result00.dat', 'kind': 'result', 'loader': None, 'load_call': None,
     'container': 'u32 table at 0x00 (39 entries)', 'size': 535648},
)

STAGE_PACKS = ('st0', 'st1', 'st2', 'st3', 'st4', 'st5', 'st6', 'st7', 'st8', 'st9',
               'sta', 'stb')

INVENTORY = {
    'characters': {
        'status': 'unknown', 'entries': [],
        'evidence': ('FST lists em/pl00.dat and em/pl000.tpl..em/pl00a.tpl as the only '
                     'player packs; no roster table and no selection code are proven, so '
                     'no character name is claimed.')},
    'hidden_characters': {
        'status': 'unknown', 'entries': [],
        'evidence': ('No hidden-character table exists on the disc; a hidden character '
                     'could still be gated by a progress flag, which is untraced.')},
    'modes': {
        'status': 'present_on_disc_unverified',
        'entries': ['etc/mission01.tpl..etc/mission11.tpl (11 mission tables)',
                    'etc/trial01.tpl..etc/trial11.tpl (11 trial tables)',
                    'etc/omake01_f.tpl..etc/omake03_s.tpl (3 bonus tables x 5 languages)',
                    'etc/allResult.dat', 'etc/result00.dat'],
        'evidence': ('DOL string table at 0x001662E8-0x001663F4 names etc/mission01.tpl '
                     '.. etc/mission11.tpl and etc/trial01.tpl; the 0x104 table id is used '
                     'by the card/continue loaders.')},
    'levels': {
        'status': 'unknown', 'entries': [],
        'evidence': ('etc/rank_a.tpl..etc/rank_e.tpl are rank tables, not level tables; '
                     'no per-level unlock record is proven.')},
    'stages': {
        'status': 'present_on_disc_unverified',
        'entries': ['%s/ (12 stage packs, .adr + .lze each)' % ', '.join(STAGE_PACKS)],
        'evidence': 'FST stage directories; no hidden stage table is proven.'},
    'costumes': {
        'status': 'unknown', 'entries': [],
        'evidence': 'No costume table is present on the disc for this revision.'},
    'items': {
        'status': 'present_on_disc_unverified',
        'entries': ['etc/rank_a.tpl..etc/rank_e.tpl', 'id/eng/equip_ck_e.dat',
                    'id/eng/combo.tpl'],
        'evidence': ('DOL string table names etc/rank_a.tpl..etc/rank_e.tpl; '
                     'id/eng/equip_ck_e.dat is the equipment check table (738560 bytes).')},
    'extras': {
        'status': 'present_on_disc_unverified',
        'entries': ['etc/title.dat', 'etc/icon.dat', 'etc/allResult.dat',
                    'etc/result00.dat', 'etc/omake01..03 (per language)',
                    'movie/joe.thp', 'movie/dance.thp', 'movie/demo.thp'],
        'evidence': ('DOL string table names /etc/title.dat and movie/{joe,dance,demo}.thp; '
                     'title.dat and result00.dat hold the record/result structures.')},
}


def revision_ok(main_dol: bytes) -> bool:
    """True only for the exact owned main.dol this profile was researched against."""
    return (len(main_dol) == MAIN_DOL_SIZE
            and hashlib.sha256(main_dol).hexdigest() == MAIN_DOL_SHA256)


def save_tables() -> list:
    return [dict(t) for t in SAVE_TABLES]


def inventory() -> dict:
    return copy.deepcopy(INVENTORY)


def disc_evidence() -> dict:
    return {'game_id': GAME_ID, 'platform': PLATFORM, 'title': TITLE,
            'disc_id': DISC_ID, 'disc_header_title': DISC_HEADER_TITLE,
            'main_dol_sha256': MAIN_DOL_SHA256, 'main_dol_size': MAIN_DOL_SIZE,
            'main_elf_sha256': MAIN_ELF_SHA256, 'ghidra_image_base': GHIDRA_IMAGE_BASE,
            'ghidra_language': GHIDRA_LANGUAGE, 'ghidra_functions': GHIDRA_FUNCTIONS,
            'fst_entries': FST_ENTRIES}


def profile() -> dict:
    """Revision-guarded research profile.  verified=False until a write target is proven."""
    return {
        'status': 'research_pending',
        'profile': 'pn03-gc-revision-guard-v1',
        'verified': False,
        'game_id': GAME_ID,
        'platform': PLATFORM,
        'disc_id': DISC_ID,
        'scope': [
            'revision guard for P.N. 03 (USA) / disc GPNE08 only',
            'save/progress table map: ' + ', '.join(t['file'] for t in SAVE_TABLES),
            'category inventory with per-category evidence (modes, stages, items, extras '
            'present on disc; characters, hidden_characters, levels, costumes unknown)',
        ],
        'exclusions': [
            'no unlock write is performed: no flag offset is proven for this revision',
            'the other owned RE4 GameCube disc (G4BE08 / 78ab9efa2e310db4) is a different '
            'revision with different readers and is not covered',
            'no account entitlement, DLC or online advantage change',
        ],
        'items': [],
        'inventory': inventory(),
        'evidence': {
            'disc_identity': disc_evidence(),
            'save_tables': save_tables(),
            'dol_string_table': ['etc/card.dat @0x00160F38', 'etc/continue.dat @0x00165F44',
                                 'etc/result00.dat @0x0016628C', 'etc/allresult.dat @0x00166608',
                                 'id/eng/lobby_e.dat @0x00168968', 'id/eng/equip_ck_e.dat @0x0016B118',
                                 'id/eng/trialrank_e.dat @0x0016BCB8', '/etc/title.dat @0x0016B95C'],
            'ghidra': 'main.elf opened with PowerPC:BE:32:default, base 0x80003100, 5357 functions',
            'loaders': {'etc/card.dat': 'FUN_8001c5ac', 'etc/continue.dat': 'FUN_8007a290'},
            'container_magic': 'TPL / IDD / MDT headers in the etc/*.dat tables',
        },
        'save_effect': ('None. No save, ROM or memory write is attempted by this profile; '
                        'the original ROM and the operator saves are untouched.'),
        'requires_save_upgrade_opt_in': False,
        'reason': ('P.N. 03 (USA) (GPNE08) is mapped, but no unlock flag offset is proven '
                   'for this revision yet, so no write is attempted.'),
    }


def unlock_ops() -> list:
    """Unlock operations.  Empty: no write target is proven for this revision."""
    return []


def next_step() -> list:
    return [
        'Decompile FUN_8001c5ac (card.dat loader) and FUN_8007a290 (continue.dat loader) '
        'to the flag reads that gate the mission/trial/rank/omake tables.',
        'Map etc/card.dat and etc/continue.dat record layouts (TPL/IDD/MDT headers) and '
        'identify the progress/clear-flag words.',
        'Re-derive the category inventory from the menu eligibility code, not from file names.',
        'Only then add a writer with a digest-guarded overlay and runtime acceptance on an '
        'idle authorized worker (i9-NUC or the Spark, 2% audio).',
    ]
