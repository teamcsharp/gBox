import base64
import hashlib
import struct
import zlib

import numpy as np
import pytest

from gbox import re5_sonic_grip as grip, re5_sonic_hands as hands, re5_sonic_residue as residue
from gbox import re5_sonic_writer as writer

START, BONES = 0xa4, 3
LOCAL, INVERSE = BONES*24, BONES*88
FOOT_Z = LOCAL + 64 + 56                # bone 1's local z translation: a real offset below a micron
ZERO = LOCAL + 4                        # an off-axis rotation element: exactly zero, so it stores residue


def skeleton(values=(), count=BONES):
    """A Switch MOD shell through its bone block: real lengths, axis-aligned bind matrices, chosen small slots."""
    raw = bytearray(START + count*152 + 256)
    raw[:4] = b'MOD\0'
    struct.pack_into('<H', raw, 6, count)
    struct.pack_into('<Q', raw, 0x28, START)
    for bone in range(count):
        raw[START + bone*24:START + bone*24 + 2] = bytes((bone, 255 if not bone else bone-1))
        struct.pack_into('<4f', raw, START + bone*24 + 8, 5., 3., 0., 4.)
        struct.pack_into('<16f', raw, START + count*24 + bone*64, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, bone, 2, 3, 1)
        struct.pack_into('<16f', raw, START + count*88 + bone*64, 118, 0, 0, 0, 0, 118, 0, 0, 0, 0, 118, 0,
                         -bone, -2, -3, 1)
    for offset, value in values:
        struct.pack_into('<f', raw, START + offset, value)
    return bytes(raw)


def reviewed(monkeypatch, mod):
    digest = hashlib.sha256(mod).hexdigest()
    monkeypatch.setattr(residue, '_TABLES', {digest: residue.record(mod)})
    return digest


ACCEPTED = ((ZERO, 3e-13), (INVERSE + 64 + 16, -7e-14), (24 + 16, 2e-17), (LOCAL + 8, -0.), (FOOT_Z, -4.3981745e-07))


def test_tables_belong_to_the_three_pinned_stage_models_and_hold_no_usable_geometry():
    assert set(residue._TABLES) == {hands.BASE_MOD_SHA256, grip.V14_MOD_SHA256, writer.GRIP_PAYLOADS[0][2]}
    for table in residue._TABLES.values():
        count, rows = residue._rows(table)
        values = [abs(residue._value(bits)) for bits in rows.values()]
        # rounding residue, then nothing for five decades, then the bind offsets smaller than two micrometres
        assert count == 130 and 500 <= sum(v < 1e-11 for v in values) <= 1100
        assert sum(1e-11 <= v < 1e-7 for v in values) == 0
        assert sum(v >= 1e-7 for v in values) == 106 and max(values) < 2e-4 < residue.LISTED
        # every row is a float slot of a bone header (+8..+24) or of the two matrix tables
        assert all(offset % 4 == 0 and (offset >= count*24 or offset % 24 >= 8) and offset < count*152
                   for offset in rows)


def test_another_kernels_rounding_settles_to_the_reviewed_bytes(monkeypatch):
    accepted = skeleton(ACCEPTED)
    digest = reviewed(monkeypatch, accepted)
    assert residue.settle(accepted) is accepted
    # another kernel: other residue in a reviewed slot, 0.0 where the review has residue, residue where the review
    # has +0.0, and the sub-micron offset on the neighbouring float32
    neighbour = float(np.nextafter(np.float32(-4.3981745e-07), np.float32(0)))
    other = skeleton(((ZERO, -1e-13), (LOCAL + 36, 5e-16), (INVERSE + 12, -2e-19), (FOOT_Z, neighbour)))
    assert neighbour != struct.unpack('<f', struct.pack('<f', -4.3981745e-07))[0]
    assert hashlib.sha256(other).hexdigest() != digest
    assert residue.settle(other) == accepted


@pytest.mark.parametrize('offset,value', [
    (LOCAL, 1.0000001),                 # a rotation element one float32 away
    (INVERSE + 48, 1e-6),               # a translation the review has at exactly zero
    (8, 5.0000005),                     # a bone length
    (ZERO, 2e-9),                       # more than rounding where the review has residue
    (FOOT_Z, -4.5e-07),                 # the listed offset moved by a tenth of a nanometre
    (INVERSE, float('nan'))])
def test_a_difference_beyond_kernel_rounding_is_never_settled(monkeypatch, offset, value):
    reviewed(monkeypatch, skeleton(ACCEPTED))
    drifted = skeleton(ACCEPTED + ((ZERO, 1e-13), (offset, value)))
    assert residue.settle(drifted) is drifted


@pytest.mark.parametrize('position', [2, START + 2, START + 24 + 4, START + BONES*152 + 9])
def test_bytes_outside_the_bind_slots_are_never_settled(monkeypatch, position):
    reviewed(monkeypatch, skeleton(ACCEPTED))
    changed = bytearray(skeleton(ACCEPTED + ((ZERO, 1e-13),)))       # header, bone ids, animation map
    changed[position] ^= 1
    assert residue.settle(bytes(changed)) == bytes(changed)


@pytest.mark.parametrize('data', [b'', b'MOD authored', b'MOD\0' + bytes(60), skeleton(count=2)],
                         ids=['empty', 'fixture', 'truncated', 'other skeleton'])
def test_other_models_and_fragments_pass_through(monkeypatch, data):
    reviewed(monkeypatch, skeleton(ACCEPTED))
    assert residue.settle(data) is data


def test_a_table_cannot_carry_geometry(monkeypatch):
    table = residue.record(skeleton(ACCEPTED))
    assert set(residue._rows(table)[1]) == {offset for offset, _ in ACCEPTED}
    forged = base64.b64encode(zlib.compress(zlib.decompress(base64.b64decode(table))
                                            + struct.pack('<Hf', LOCAL, 1.))).decode()
    monkeypatch.setattr(residue, '_TABLES', {'0'*64: forged})
    with pytest.raises(ValueError, match='listed limit'):
        residue.settle(skeleton(((ZERO, 1e-13),)))
    with pytest.raises(ValueError, match='complete Switch MOD'):
        residue.record(b'MOD authored')
