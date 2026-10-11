"""Native ACS termination while retaining the title's mode-2 initializer.

Owned DOA2 LE JP proof: 8c0dd278 and 8c0d42c2 test the first directive
byte for 0xff before consuming its argument. KTE_A03.ACS already contains
the canonical eight-byte empty directive used here, plus allocation padding.
Executable command substitution is deliberately not part of this helper.
"""
from __future__ import annotations

import hashlib
import struct

EMPTY_DIRECTIVE = b'\xff' + bytes(7)


def inspect_acs(data: bytes) -> dict:
    """Read the bounded eight-byte directory without inventing payload schemas."""
    if len(data) < 8:
        raise ValueError('ACS lacks a complete native directive/terminator')
    entries = []
    for offset in range(0, len(data) - 7, 8):
        word, argument = struct.unpack_from('<II', data, offset)
        mode = word & 0xff
        if mode == 0xff:
            return {'file_bytes': len(data), 'directive_count': len(entries),
                    'terminator_offset': offset, 'directives': entries}
        entries.append({'offset': offset, 'mode': mode,
                        'word': word, 'argument': argument})
    raise ValueError('ACS directory has no bounded native terminator')


def disable_acs(data: bytes) -> tuple[bytes, dict]:
    """Use a native empty directory; keep the executable initialization intact."""
    prior = inspect_acs(data)
    patched = EMPTY_DIRECTIVE + data[8:]
    return patched, {'supplement': 'ACS', 'file_bytes': len(data), 'before': prior,
                     'original_sha256': hashlib.sha256(data).hexdigest(),
                     'patched_sha256': hashlib.sha256(patched).hexdigest(),
                     'changed_bytes': sum(a != b for a, b in zip(data, patched)),
                     'policy': 'native empty ACS directory; mode-2 initialization retained',
                     'evidence': {'native_existing_file': 'DOA2/KTE_A03.ACS',
                                  'pointer_fixup_terminator': '0x8c0dd278',
                                  'descriptor_initializer': '0x8c0d42c2'}}
