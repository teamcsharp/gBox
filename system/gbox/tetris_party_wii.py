"""Tetris Party Deluxe (USA) (Wii): revision-pinned unlock research for the game's own save.

Everything here is grounded in the owned Wii image in the operator's HyperSpin
library (``collections/Nintendo Wii/roms/Tetris Party Deluxe (USA).wbfs``) and in
the disc that was extracted from it read-only on the Spark.  No save, ROM or
progress flag is written by this module: it names the exact revision, the exact
executable, the exact save file the game uses and the evidence that is still
missing before any writer may run.

How the image was obtained (reproducible, read-only):

    flatpak run --filesystem=host --command=dolphin-tool org.DolphinEmu.dolphin-emu \\
        extract -i "<copy of the .wbfs>" -o <out>

``dolphin-tool convert`` cannot read a WBFS container and a hand-written WBFS
reconstruction did not reproduce the disc, so the extraction route above is the
supported one.  The owned ``.wbfs`` itself is never modified.

Layout facts (verified against the extracted disc):

  * disc game code ``STEE`` (DATA/disc/header.bin), Wii title id
    ``4fb00410ea31f649`` (DATA/ticket.bin).
  * the executable is ``DATA/sys/main.dol``; its ELFDOL header maps nine loaded
    sections (two text, seven data) plus BSS, entry point ``0x80006310``.
  * the game keeps its progress in its own Wii persistent save file, named
    ``TTPARTY.bin`` next to ``banner.bin`` (the name string lives in
    ``main.dol`` at ``0x803F32B4``); the strings ``Failed to save persistent
    data.``, ``The system file for Tetris Party Deluxe`` and
    ``Tetris Party Deluxe disc.`` sit next to the save handling.
  * the shipped template for that save file is ``DATA/files/system/save.tpl``
    (43,264 bytes).  Its first 0x100 bytes are a header; the record area that
    follows holds 4-byte records whose high byte carries a set bit and whose
    paired byte cycles through 0x74/0x95/0xb6/0xd7 in the region that was
    inspected.  The meaning of each field is NOT established yet, so no unlock
    claim is made from it.

Because the payload semantics are not mapped and no writer exists, the honest
gate below reports ``verified: False``.  The Play path therefore reports
``research_pending`` for this exact catalog game and never touches a save.
"""
from __future__ import annotations

import hashlib
import struct

GAME_ID = '6ad5e998536407a3'          # Tetris Party Deluxe (USA), platform=wii, core=dolphin
PLATFORM = 'wii'
GAME_TITLE = 'Tetris Party Deluxe (USA)'
CORE = 'dolphin'

# ---- the owned image -------------------------------------------------------
LIBRARY = 'hyperspin'
REL_PATH = 'collections/Nintendo Wii/roms/Tetris Party Deluxe (USA).wbfs'
WBFS_SHA256 = 'faea5839da2889b57a7991f934e7578eaae93cd033148ac25b436441cf70f6f5'
WBFS_SIZE = 60817408
DISC_GAMECODE = 'STEE'
TITLE_ID = '4fb00410ea31f649'

# ---- the executable --------------------------------------------------------
MAIN_DOL_SHA256 = 'e2f588ab0e985f83cc7fe5eedd782e15251b4ea21df267ad3886efe1d84609f1'
MAIN_DOL_SIZE = 5010592
DOL_ENTRY = 0x80006310
DOL_BSS_ADDR = 0x804C6000
DOL_BSS_SIZE = 0xF42CC

# (kind, index, file_offset, vaddr, size) of every loaded section of this main.dol.
DOL_SEGMENTS = (
    ('text', 0, 0x00000100, 0x80004000, 0x0026E0),
    ('text', 1, 0x000027E0, 0x80027AC0, 0x003C2EA0),
    ('data', 0, 0x003C5680, 0x800066E0, 0x00018760),
    ('data', 1, 0x003DDDE0, 0x8001EE40, 0x00008C80),
    ('data', 2, 0x003E6A60, 0x803EA960, 0x000000E0),
    ('data', 3, 0x003E6B40, 0x803EAA40, 0x00000020),
    ('data', 4, 0x003E6B60, 0x803EAA80, 0x0005B080),
    ('data', 5, 0x00441BE0, 0x80445B00, 0x00080500),
    ('data', 6, 0x004C20E0, 0x805B3D40, 0x00002000),
    ('data', 7, 0x004C40E0, 0x805B6EE0, 0x000033C0),
)

# ---- the save --------------------------------------------------------------
SAVE_FILE_NAME = 'TTPARTY.bin'
SAVE_BANNER_NAME = 'banner.bin'
SAVE_NAME_VADDR = 0x803F32B4          # the "TTPARTY.bin" string inside main.dol
SAVE_TEMPLATE_PATH = 'system/save.tpl'
SAVE_TEMPLATE_SIZE = 43264
SAVE_TEMPLATE_HEADER_SIZE = 0x100
SAVE_RECORD_SIZE = 4
SAVE_RECORD_AREA = 0x100               # the region whose records were inspected

# The unlock categories this research must inventory before any writer exists.
CATEGORIES = ('characters', 'hidden_characters', 'modes', 'levels', 'stages',
              'costumes', 'items', 'extras')

# Strings in main.dol that pin the save handling (file offsets are stable for
# this revision; the virtual addresses follow from the DOL segment map).
SAVE_HANDLING_STRINGS = {
    'TTPARTY.bin': 0x3EF394,
    'banner.bin': 0x3EF3A4,
}


def parse_dol_header(data: bytes) -> dict:
    """Decode an ELFDOL header: loaded segments, BSS and the entry point.

    Layout: 7 text file offsets, 11 data file offsets, 7 text addresses,
    11 data addresses, 7 text sizes, 11 data sizes, BSS address/size, entry.
    """
    if len(data) < 0xE4:
        raise ValueError('DOL header shorter than 0xE4 bytes')
    text_off = [struct.unpack_from('>I', data, 0x00 + 4 * i)[0] for i in range(7)]
    data_off = [struct.unpack_from('>I', data, 0x1C + 4 * i)[0] for i in range(11)]
    text_addr = [struct.unpack_from('>I', data, 0x48 + 4 * i)[0] for i in range(7)]
    data_addr = [struct.unpack_from('>I', data, 0x64 + 4 * i)[0] for i in range(11)]
    text_size = [struct.unpack_from('>I', data, 0x90 + 4 * i)[0] for i in range(7)]
    data_size = [struct.unpack_from('>I', data, 0xAC + 4 * i)[0] for i in range(11)]
    segments = []
    for i in range(7):
        if text_size[i]:
            segments.append({'kind': 'text', 'index': i, 'file_offset': text_off[i],
                             'vaddr': text_addr[i], 'size': text_size[i]})
    for i in range(11):
        if data_size[i]:
            segments.append({'kind': 'data', 'index': i, 'file_offset': data_off[i],
                             'vaddr': data_addr[i], 'size': data_size[i]})
    return {'segments': segments,
            'bss_addr': struct.unpack_from('>I', data, 0xD8)[0],
            'bss_size': struct.unpack_from('>I', data, 0xDC)[0],
            'entry': struct.unpack_from('>I', data, 0xE0)[0]}


def vaddr_to_file(vaddr: int, segments=DOL_SEGMENTS) -> int | None:
    """File offset of a loaded virtual address, or None when it is not loaded."""
    for kind, index, file_offset, addr, size in segments:
        if addr <= vaddr < addr + size:
            return file_offset + (vaddr - addr)
    return None


def file_to_vaddr(offset: int, segments=DOL_SEGMENTS) -> int | None:
    """Virtual address of a file offset inside a loaded section, or None."""
    for kind, index, file_offset, addr, size in segments:
        if file_offset <= offset < file_offset + size:
            return addr + (offset - file_offset)
    return None


def find_ascii(data: bytes, needle: bytes, segments=DOL_SEGMENTS) -> list[dict]:
    """Every offset of ``needle`` in the file, with the virtual address it loads at."""
    out = []
    start = 0
    while True:
        at = data.find(needle, start)
        if at < 0:
            return out
        out.append({'offset': at, 'vaddr': file_to_vaddr(at, segments)})
        start = at + 1


def save_tpl_records(data: bytes) -> list[dict]:
    """Split the save template into its 4-byte records.

    Each record is reported byte by byte.  The high bit of the first byte marks
    a populated record and the paired byte counts up in the region that was
    inspected; the *meaning* of the fields is still unknown, so nothing here is
    presented as an unlock flag.
    """
    if len(data) < SAVE_TEMPLATE_HEADER_SIZE:
        raise ValueError('save template shorter than its 0x100 header')
    out = []
    for off in range(SAVE_TEMPLATE_HEADER_SIZE, len(data) - SAVE_RECORD_SIZE + 1,
                     SAVE_RECORD_SIZE):
        b0, b1, b2, b3 = data[off:off + SAVE_RECORD_SIZE]
        out.append({'offset': off, 'b0': b0, 'b1': b1, 'b2': b2, 'b3': b3,
                    'high_bit_set': bool(b0 & 0x80),
                    'paired_high_bit_set': bool(b2 & 0x80)})
    return out


def record_summary(records: list[dict]) -> dict:
    """Counts over the decoded records: how many, how many populated, which values."""
    return {'records': len(records),
            'populated': sum(1 for r in records if r['high_bit_set']),
            'paired_populated': sum(1 for r in records if r['paired_high_bit_set']),
            'distinct_first_bytes': sorted({r['b0'] for r in records}),
            'distinct_second_bytes': sorted({r['b1'] for r in records})}


def save_file_plan() -> dict:
    """Where the game keeps its progress, and what a writer would have to touch."""
    return {'save_file': SAVE_FILE_NAME,
            'banner_file': SAVE_BANNER_NAME,
            'save_name_vaddr': f'{SAVE_NAME_VADDR:#x}',
            'template': SAVE_TEMPLATE_PATH,
            'template_size': SAVE_TEMPLATE_SIZE,
            'header_size': SAVE_TEMPLATE_HEADER_SIZE,
            'record_size': SAVE_RECORD_SIZE,
            'storage': "the game's own Wii persistent save file (per-title save directory); "
                       "Dolphin serves it from its NAND, so the live path must locate and "
                       "back up the save the game actually writes before any change",
            'policy': 'read-only research: no writer exists, no save is touched'}


def profile_gate() -> dict:
    """Honest, unverified gate for the Tetris Party Deluxe unlock scope."""
    return {
        'verified': False,
        'reason': ('Tetris Party Deluxe (USA) STEE: the owned image, the executable and the '
                    'game\'s own save file are pinned, but the save payload fields are not '
                    'mapped and no unlock writer exists, so nothing is unlocked yet.'),
        'categories': list(CATEGORIES),
        'evidence': {
            'image': REL_PATH + ' (library ' + LIBRARY + ')',
            'image_sha256': WBFS_SHA256,
            'image_size': WBFS_SIZE,
            'disc_gamecode': DISC_GAMECODE,
            'title_id': TITLE_ID,
            'executable': 'DATA/sys/main.dol sha256 ' + MAIN_DOL_SHA256,
            'executable_size': MAIN_DOL_SIZE,
            'dol_entry': f'{DOL_ENTRY:#x}',
            'dol_sections': len(DOL_SEGMENTS),
            'save_file': SAVE_FILE_NAME,
            'save_template': SAVE_TEMPLATE_PATH + ' (' + str(SAVE_TEMPLATE_SIZE) + ' bytes)',
            'save_handling_strings': ['Failed to save persistent data.',
                                       'The system file for Tetris Party Deluxe',
                                       'Tetris Party Deluxe disc.'],
            'extraction': 'dolphin-tool extract on a copy of the owned .wbfs (read-only)',
        },
        'blockers': [
            'The 4-byte save records in system/save.tpl are decoded byte by byte, but the '
            'meaning of each field (counters, per-mode records, unlock flags) is not mapped, '
            'so no field can be written with a proven effect.',
            'No category inventory (characters, modes, stages, costumes, items, extras) has '
            'been read out of the game\'s own data yet.',
            'The save the running game writes has never been located on a worker NAND and '
            'never backed up, so no live write could be reverted.',
            'No runtime acceptance has been performed: no boot, no menu check, no '
            'second-launch check, no rollback check.',
        ],
        'next': ('Open DATA/sys/main.dol (sha256 ' + MAIN_DOL_SHA256[:16] + '...) in Ghidra/REA, '
                 'xref the "TTPARTY.bin" string at ' + f'{SAVE_NAME_VADDR:#x}' + ' to the routine '
                 'that reads and writes the save, map the record fields against the menu data '
                 'in DATA/files/mess/009_config.bin and 007_records.bin, then write a '
                 'revision-guarded writer and a live acceptance plan (i9-NUC or the Spark, '
                 'idle, 2% audio; never on the operator\'s play PC).'),
    }


def digest_of(path) -> str:
    """sha256 of a file on disk, used to confirm the owned image before analysis."""
    h = hashlib.sha256()
    with open(path, 'rb') as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()
