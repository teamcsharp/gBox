"""BLAS-kernel rounding in the reviewed Sonic skeleton tables (RE5 Chris normal: v12, v14, v15).

``mtf_retarget.reposition_bind_pose`` writes each bone's length, local matrix and inverse-bind matrix through
BLAS/LAPACK (``@``, ``numpy.linalg.inv``, ``numpy.linalg.norm``). Its float64 results agree between BLAS kernels to
about 1e-12, and a float32 keeps that wherever the value is small: a slot whose exact value is zero stores the
kernel's residue (1e-13, or 0.0 from another kernel), and a sub-micron offset such as bone 120's local z
-4.3981745e-07 can land on the neighbouring float32. The reviewed MODs were authored on a PC whose NumPy runs
OpenBLAS's SkylakeX (AVX-512) kernels and the stage guards pin whole-file SHA-256s, so any other kernel stopped in
``re5_sonic_hands.author`` at "requires the exact reviewed v12 MOD".

Measured 2026-11-09 on that PC, one commit, ``OPENBLAS_CORETYPE`` forced (NumPy 2.5.4, OpenBLAS 0.3.34):

    kernel                  stage-1 MOD   v12 -> hands   v14 -> grip
    SkylakeX (reviewed)     b87ecc87      426ac8ad       45f13063
    Haswell                 44296edc      dbfcdb9e       22a010eb
    Nehalem                 26c7a135      b80d92a4       8e6d2dcb

In every cell the bytes that differ from the reviewed MOD are float32 slots of the bone headers and the two matrix
tables, each within 1e-12 of the reviewed value. No vertex, weight, envelope or bound byte differs. Zen selects the
Haswell kernels; Sandybridge and Katmai gave Nehalem's stage-1 bytes. The aarch64 game host was reported to stop at
the same two guards (``cec895d2``, ``e9c2bf23``); its bytes have not been diffed.

``settle`` accepts that difference and nothing else. In each float32 slot ``reposition_bind_pose`` stores, a
computed value within ``TOLERANCE`` of the reviewed one takes the reviewed bits. The result is returned only when
its SHA-256 is the reviewed one, so every other byte, and every slot beyond the tolerance, was computed identically
here; otherwise the input comes back untouched and the stage guards refuse it as before. A table lists the reviewed
slots that are nonzero and below ``LISTED``: rounding residue and offsets under ten micrometres, no usable geometry.
``record`` derives a table from a MOD, so each one can be checked against its reviewed artifact.
"""
from __future__ import annotations

import base64
import hashlib
import struct
import zlib

# The kernels measured differ by less than 1e-12 in these slots; a thousand times that is ten femtometres in the
# centimetre tables.
TOLERANCE = 1e-9
# A table lists the nonzero reviewed values below this: residue up to 3e-12, and 106 bind offsets of 4e-7 to 2e-4 cm
# whose float32 spacing (3e-14 at 4e-7) is within reach of that rounding. One of them moved under Haswell.
LISTED = 1e-3
_BONE_HEADER, _BONE_RECORD = 24, 152    # header, then a 64-byte local and a 64-byte inverse-bind matrix per bone

# reviewed MOD SHA-256 -> base64(zlib(u16 bone count, then rows of u16 offset in the bone block + u32 float32 bits))
_TABLES = {
    # v12: 501 residue slots peaking at 1.7e-12, 106 offsets from 4.2e-07 to 1.9e-04
    'b87ecc87d3fb414f4692dd1d237f949d7b7db6bd969c028e43669ea5d199d3fb': (
        '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'),
    # v14: 1045 residue slots peaking at 3.0e-12, 106 offsets from 4.2e-07 to 1.9e-04
    '426ac8adbad137b8ad42e1b3748d1fb56e5b1f87664ac0acc6626ad6ad241d56': (
        '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'),
    # v15: 1056 residue slots peaking at 3.0e-12, 106 offsets from 4.2e-07 to 1.9e-04
    '45f130636f32c7a403d8fb68687f19994ebf9093a55ca2d988b308f30c3c7fb9': (
        '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'),
}


def _slots(mod: bytes) -> tuple[int, int, list[int]]:
    """(bone block offset, bone count, offsets of the float32 slots a bind rewrite stores); no slots if not a MOD."""
    if len(mod) < 0x30 or mod[:4] != b'MOD\0':
        return 0, 0, []
    count, start = struct.unpack_from('<H', mod, 6)[0], struct.unpack_from('<Q', mod, 0x28)[0]
    if not count or start + count * _BONE_RECORD > len(mod):
        return 0, 0, []
    # +8 in a bone header is the length and position reposition_bind_pose stores; the matrices follow the headers.
    lengths = [start + bone * _BONE_HEADER + 8 + 4 * i for bone in range(count) for i in range(4)]
    return start, count, lengths + list(range(start + count * _BONE_HEADER, start + count * _BONE_RECORD, 4))


def _value(bits: int) -> float:
    return struct.unpack('<f', struct.pack('<I', bits))[0]


def _rows(table: str) -> tuple[int, dict[int, int]]:
    raw = zlib.decompress(base64.b64decode(table))
    rows = dict(struct.iter_unpack('<HI', raw[2:]))
    if any(not abs(_value(bits)) < LISTED for bits in rows.values()):
        raise ValueError('a residue table may hold only values below the listed limit')
    return struct.unpack_from('<H', raw)[0], rows


def record(mod: bytes) -> str:
    """The table of one MOD: every bind slot whose bits are not +0.0 and whose value is below LISTED."""
    start, count, slots = _slots(mod)
    if not slots:
        raise ValueError('a residue table needs a complete Switch MOD skeleton')
    rows = bytearray(struct.pack('<H', count))
    for offset in slots:
        bits = struct.unpack_from('<I', mod, offset)[0]
        if bits and abs(_value(bits)) < LISTED:
            rows += struct.pack('<HI', offset - start, bits)
    return base64.b64encode(zlib.compress(bytes(rows), 9)).decode()


def _replay(mod: bytes, table: str) -> bytes | None:
    start, count, slots = _slots(mod)
    expected, rows = _rows(table)
    if not slots or count != expected:
        return None
    out = bytearray(mod)
    for offset in slots:
        bits = rows.get(offset - start, 0)      # an unlisted slot is +0.0 or too large to settle
        if abs(struct.unpack_from('<f', mod, offset)[0] - _value(bits)) <= TOLERANCE:
            struct.pack_into('<I', out, offset, bits)
    return bytes(out)


def settle(mod: bytes) -> bytes:
    """The reviewed MOD that ``mod`` equals up to kernel rounding in its bind tables, otherwise ``mod`` unchanged."""
    if hashlib.sha256(mod).hexdigest() in _TABLES:
        return mod
    for reviewed, table in _TABLES.items():
        candidate = _replay(mod, table)
        if candidate is not None and hashlib.sha256(candidate).hexdigest() == reviewed:
            return candidate
    return mod
