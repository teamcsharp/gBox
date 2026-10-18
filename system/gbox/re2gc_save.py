"""Read-only GHAE08 GCI integrity and saved-mode inspection.

Award records are not playable mode saves. This module does not create, edit,
import or activate a save, and a matching checksum is not gameplay acceptance.
"""
from __future__ import annotations

import argparse
import json
import re
import struct
from pathlib import Path

from .re2gc_state import Build, DOL_SIZE, REL_SIZES, _read_bounded, _source_bytes, sha
from .re2gc_native import DISC_ID

GCI_HEADER = 0x40
CARD_FILE_SIZE = 0x2000
GCI_SIZE = GCI_HEADER + CARD_FILE_SIZE
CHECKSUM_OFFSET = 0x1ffc
PAYLOAD_OFFSET = 0x1600
PAYLOAD_SIZE = 0x798
WORKING_OFFSET = 0x1800
CLEAR_FLAGS_OFFSET = 0x1b88
AWARDS = {'hunk': 0x13, 'tofu': 0x14, 'extreme_battle': 0x15}
CHECKSUM_CODE = {
    'leon': 0x17ded0,
    'claire': 0x17dca8,
}
CHECKSUM_CODE_SHA256 = 'f217caf774e2a594e5f1b2ef7336130e943cdf41e4e0cda6bface7f56399610d'


def _inspect_gci(data):
    data = _source_bytes(data, {GCI_SIZE}, 'one-block GCI')
    if data[:6] != DISC_ID.encode('ascii'):
        raise ValueError('GCI game/maker identity is not GHAE08')
    if struct.unpack_from('>H', data, 0x38)[0] != 1:
        raise ValueError('GHAE08 save requires exactly one card block')
    filename = data[8:40].split(b'\0', 1)[0]
    match = re.fullmatch(rb'RESIDENTEVIL2([ A])-(\d{2})', filename)
    if not match or int(match[2]) > 14:
        raise ValueError('unrecognized native RE2 save filename or slot')
    body = data[GCI_HEADER:]
    stored = struct.unpack_from('>I', body, CHECKSUM_OFFSET)[0]
    calculated = sum(body[:CHECKSUM_OFFSET])
    if stored != calculated:
        raise ValueError(f'native save checksum mismatch: stored {stored:08x}, calculated {calculated:08x}')
    character = body[WORKING_OFFSET + 0x0a]
    flags = struct.unpack_from('>I', body, WORKING_OFFSET + 0x14)[0]
    clear = struct.unpack_from('>2I', body, CLEAR_FLAGS_OFFSET)
    # Native loader tests HUNK/Tofu before Extreme Battle. Keep this priority;
    # this describes its dispatch path, not full save-state validity.
    if character in (0x0c, 0x0d):
        route = 'hunk' if character == 0x0c else 'tofu'
    elif flags & 0x4000:
        route = 'extreme_battle'
    else:
        route = 'ordinary'
    return {
        'disc_id': DISC_ID,
        'gci_sha256': sha(data), 'card_file_sha256': sha(body),
        'filename': filename.decode('ascii'), 'slot': int(match[2]),
        'card_file_bytes': CARD_FILE_SIZE,
        'native_checksum': {'valid': True, 'stored': stored, 'calculated': calculated,
                            'algorithm': 'unsigned byte sum', 'offset_in_card_file': CHECKSUM_OFFSET},
        'payload': {'offset_in_card_file': PAYLOAD_OFFSET, 'bytes': PAYLOAD_SIZE,
                    'sha256': sha(body[PAYLOAD_OFFSET:PAYLOAD_OFFSET + PAYLOAD_SIZE])},
        'saved_character': character, 'saved_system_flags': f'{flags:08x}',
        'native_load_route': route,
        'award_records': {name: bool(clear[index // 32] & (0x80000000 >> (index % 32)))
                          for name, index in AWARDS.items()},
        'clear_flag_words': [f'{value:08x}' for value in clear],
        'progression_counter': body[0x1cde],
        'gameplay_verified': False, 'complete_unlocks_verified': False,
        'save_writer_available': False,
        'limits': [
            'A checksum verifies native file integrity, not authenticity or a coherent playable state.',
            'Award records can suppress new reward-save prompts; they do not create playable mode saves.',
            'The load route does not prove that native loading, saving or second launch succeeds.',
        ],
    }


def inspect_gci(build: Build, data):
    """Inspect immutable bytes only after the owned executable revision matches."""
    if not isinstance(build, Build):
        raise ValueError('exact owned GHAE08 Build is required')
    # Revalidate public Build buffers: do not rely on a caller-mutated identity.
    verified = Build(build.dol, build.rel)
    at = CHECKSUM_CODE[verified.scenario]
    if sha(verified.rel[at:at + 80]) != CHECKSUM_CODE_SHA256:
        raise ValueError('owned save checksum routine differs')
    report = _inspect_gci(data)
    report['layout_source'] = verified.identity()
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dol', type=Path, required=True)
    parser.add_argument('--rel', type=Path, required=True)
    parser.add_argument('gci', type=Path, nargs='+', help='explicit copied GCI files; no card-directory scanning')
    args = parser.parse_args(argv)
    try:
        build = Build(_read_bounded(args.dol, {DOL_SIZE}, 'DOL'),
                      _read_bounded(args.rel, set(REL_SIZES.values()), 'REL'))
        reports = [inspect_gci(build, _read_bounded(path, {GCI_SIZE}, 'GCI')) for path in args.gci]
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    print(json.dumps({'saves': reports, 'read_only': True, 'gameplay_verified': False,
                      'complete_unlocks_verified': False}, indent=2))


if __name__ == '__main__':
    main()
