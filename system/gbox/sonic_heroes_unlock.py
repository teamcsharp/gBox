"""Bounded unlock research evidence for Sonic Heroes (USA) on GameCube.

Read-only static analysis of the owned executable. This module never launches
the game, never edits a save and never claims a lock check was proved: the
inventory records what this owned revision actually contains and marks every
category that still needs a lock-check proof as unknown.

Evidence: Ghidra bridge open of the owned ELF (job b1879e1439af406e, receipt
bbe94a42906f4a5c, worker 7b23bff397df4e2e) and a local sha256 of the same file.
"""
from __future__ import annotations

import hashlib
import re
import struct

GAME_ID = 'f2c5f36ae6845713'
PLATFORM = 'gamecube'
TITLE = 'Sonic Heroes (USA)'

# Pinned revision identity of the owned executable.
EXECUTABLE_SHA256 = '7073fbc47d28579aecf510b7b7ae94a514b37b61a3ad7cccedd2b97a19fa5846'
EXECUTABLE_MD5 = 'adda79815b67ff0a03f6fb86fa4a8257'
EXECUTABLE_RELATIVE = 'gbox-data/analysis/re/f2c5f36ae6845713/main.dol.elf'
IMAGE_BASE = 0x80003100
LANGUAGE = 'PowerPC:BE:32:default'
GHIDRA_FUNCTIONS = 5580
GHIDRA_JOB_ID = 'b1879e1439af406e'
GHIDRA_RECEIPT_ID = 'bbe94a42906f4a5c'
GHIDRA_WORKER_ID = '7b23bff397df4e2e'

# Strings trace of the pinned revision (job 7fdb3e1b2701445c, receipt
# b891463a8d154249, worker 7b23bff397df4e2e): character-select, team-manager
# and save-namespace references. These prove the *locations* the character/mode
# eligibility checks live, not the lock decision itself, so every derived
# unlock target stays unproven until the branch is read and the save flag
# layout is mapped.
STRINGS_JOB_ID = '7fdb3e1b2701445c'
STRINGS_RECEIPT_ID = 'b891463a8d154249'
CHARACTER_STRINGS = {
    # value: (address, referencing_function, referencing_function_address)
    'Tsonic.str': (0x80240a80, 'FUN_80015df4', 0x80015df4),
    'TSonic HEAP         %10d': (0x80255678, 'FUN_800cd6a0', 0x800cd6a0),
}
MODE_STRINGS = {
    'SONIC HEROES : %02d': (0x80289e58, ('FUN_801250e8', 'FUN_80124938')),
}
SAVE_NAMESPACE_STRINGS = {
    'SONICHEROES': (0x80289eb8, 'FUN_80126008', 0x80126178),
    'SONICHEROES_': (0x80289ec4, 'FUN_80126008', 0x80126184),
}

CATEGORIES = ('characters', 'hidden_characters', 'modes', 'levels', 'stages',
              'costumes', 'items', 'extras')

STAGE_NAME_RE = re.compile(
    r'^(?:ACTIONSTAGE|BOSSSTAGE|BOUNUSSTAGE|SPECIALSTAGE|TUTORIALSTAGE)[A-Z0-9_]*$')
PREFIXES = ('ACTIONSTAGE_', 'BOSSSTAGE_', 'BOUNUSSTAGE_', 'SPECIALSTAGE_', 'TUTORIALSTAGE_')


def _load(data=None, path=None):
    if data is not None:
        return data
    if path is None:
        raise ValueError('owned executable data or path is required')
    with open(path, 'rb') as handle:
        return handle.read()


def segments(data):
    """Loadable segments of the owned ELF (32-bit big-endian)."""
    data = _load(data)
    if data[:4] != b'\x7fELF' or data[4] != 1 or data[5] != 2:
        raise ValueError('owned executable is not a 32-bit big-endian ELF')
    phoff = struct.unpack('>I', data[28:32])[0]
    phentsize = struct.unpack('>H', data[42:44])[0]
    phnum = struct.unpack('>H', data[44:46])[0]
    out = []
    for index in range(phnum):
        base = phoff + index * phentsize
        p_type, p_offset, p_vaddr, _p_paddr, p_filesz, p_memsz = struct.unpack('>IIIIII', data[base:base + 24])
        if p_type == 1:
            out.append({'offset': p_offset, 'vaddr': p_vaddr, 'filesz': p_filesz, 'memsz': p_memsz})
    return out


def _vaddr(segs, offset):
    for seg in segs:
        if seg['offset'] <= offset < seg['offset'] + seg['filesz']:
            return seg['vaddr'] + (offset - seg['offset'])
    return None


def stage_names(data=None, path=None):
    """Stage identifier table of the owned revision, keyed by virtual address."""
    data = _load(data, path)
    segs = segments(data)
    names = {}
    for match in re.finditer(rb'[\x20-\x7e]{4,}\x00', data):
        raw = match.group()[:-1]
        try:
            name = raw.decode('ascii')
        except UnicodeDecodeError:
            continue
        if not STAGE_NAME_RE.match(name):
            continue
        vaddr = _vaddr(segs, match.start())
        if vaddr is None:
            continue
        names[vaddr] = name
    return dict(sorted(names.items()))


def reference_evidence():
    """Proven *location* evidence for the character/mode/save references.

    Returned as a structured, verifiable mapping. It proves where the
    character-select, team-manager and save-namespace references live in this
    exact revision; it does NOT prove a lock decision or a save flag layout,
    so it feeds the 'next' acceptance step, not an unlock write.
    """
    return {
        'strings_job': STRINGS_JOB_ID,
        'strings_receipt': STRINGS_RECEIPT_ID,
        'worker': GHIDRA_WORKER_ID,
        'character_select': {
            'strings': {k: {'address': hex(v[0]), 'function': v[1],
                            'function_address': hex(v[2])}
                        for k, v in CHARACTER_STRINGS.items()},
            'note': 'TSonic character string and its heap-allocation format; the '
                    'select/team-manager routines reference the character roster.',
        },
        'mode': {
            'strings': {k: {'address': hex(v[0]), 'functions': v[1]}
                        for k, v in MODE_STRINGS.items()},
            'note': 'Mode/round format string referenced by two routines; the '
                    'mode-eligibility check branches on these.',
        },
        'save_namespace': {
            'strings': {k: {'address': hex(v[0]), 'function': v[1],
                            'function_address': hex(v[2])}
                        for k, v in SAVE_NAMESPACE_STRINGS.items()},
            'note': 'SONICHEROES save namespace built by FUN_80126008; the save '
                    'flag layout to map before any write.',
        },
        'status': 'locations_proved_locks_unproven',
    }


def stage_roster(data=None, path=None):
    """Grouped stage identifiers of the owned revision."""
    names = sorted(set(stage_names(data, path).values()))
    grouped = {prefix: [n for n in names if n.startswith(prefix)] for prefix in PREFIXES}
    return {prefix: sorted(values) for prefix, values in grouped.items() if values}


def content_inventory(data=None, path=None):
    """Honest per-category inventory for this exact owned revision."""
    data = _load(data, path)
    digest = hashlib.sha256(data).hexdigest()
    roster = stage_roster(data)
    stages = sorted(n for values in roster.values() for n in values)
    unknown = 'no lock check, roster table or save flag for this category was identified yet'
    return {
        'kind': 'sonic_heroes_unlock_inventory',
        'game_id': GAME_ID,
        'title': TITLE,
        'platform': PLATFORM,
        'executable_sha256': digest,
        'revision_matches_pin': digest == EXECUTABLE_SHA256,
        'image_base': hex(IMAGE_BASE),
        'language': LANGUAGE,
        'categories': {
            'stages': {'status': 'present_in_binary', 'count': len(stages),
                       'names': stages, 'groups': {k: len(v) for k, v in roster.items()}},
            **{name: {'status': 'unknown', 'count': 0, 'names': [], 'reason': unknown}
               for name in CATEGORIES if name != 'stages'},
        },
        'unlock_targets': [],
        'unlock_targets_note': 'Empty on purpose: no lock check or save flag is proved for this revision yet.',
        'reference_evidence': reference_evidence(),
        'runtime_hooks': 'none (evidence only; see gbox.game_unlocks.profile_for)',
    }


def profile_gate():
    """Fields merged into gbox.game_unlocks.profile_for for this exact game."""
    return {
        'reason': ('Sonic Heroes (USA) revision is pinned; its stage identifier table is '
                   'inventoried and the character-select, team-manager and save-namespace '
                   'reference locations are proven, but no character, mode, costume or '
                   'save-flag lock check is proved for this owned build, so no unlock '
                   'write is published yet.'),
        'scope': list(CATEGORIES),
        'executable_sha256': EXECUTABLE_SHA256,
        'evidence': {
            'executable': EXECUTABLE_RELATIVE,
            'executable_sha256': EXECUTABLE_SHA256,
            'executable_md5': EXECUTABLE_MD5,
            'ghidra': {'job_id': GHIDRA_JOB_ID, 'receipt_id': GHIDRA_RECEIPT_ID,
                       'worker_id': GHIDRA_WORKER_ID, 'language': LANGUAGE,
                       'functions': GHIDRA_FUNCTIONS, 'image_base': hex(IMAGE_BASE)},
            'stage_table': '46 stage identifiers at 0x802545d0-0x80254aec in the owned revision',
            'reference_evidence': reference_evidence(),
        },
        'next': ('Read the character-select / team-manager branch (FUN_80015df4, '
                 'FUN_800cd6a0) and the mode-eligibility branch to prove the lock '
                 'decision, then map the SONICHEROES save flag layout (FUN_80126008) '
                 'before any unlock write.'),
    }


def profile():
    """Full research profile; verified stays False until a lock check is proved."""
    return {'status': 'pending_research', 'profile': None, 'verified': False, **profile_gate()}
