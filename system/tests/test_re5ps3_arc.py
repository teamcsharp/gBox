import os
import struct
import zlib
from pathlib import Path

import pytest

from gbox.re5ps3_arc import Arc, sha


def fixture():
    body = b'UNCHANGED-MODEL' * 20
    z = zlib.compressobj(wbits=14)
    encoded = z.compress(body) + z.flush()
    first = b'\0CRA' + struct.pack('>HH', 8, 2)
    def entry(name, typ, size, raw, offset):
        return name.ljust(64, b'\0') + struct.pack('>4I', typ, size, (raw << 3) | 2, offset)
    first += entry(b'actor\\body', 0x58a15856, len(encoded), len(body), 168)
    first += entry(b'actor\\body', 0x241f5deb, 8, 8, 168 + len(encoded))
    return first + encoded + b'RAW-TEX!'


def test_big_endian_shifted_size_and_stored_members():
    data = fixture(); arc = Arc(data)
    assert len(arc.entries) == 2
    assert arc.read(arc.entries[0]) == b'UNCHANGED-MODEL' * 20
    assert arc.read(arc.entries[1]) == b'RAW-TEX!'
    assert arc.build() == data
    assert arc.replace('actor\\body', 0x58a15856, arc.read(arc.entries[0]), expected_sha256=sha(data)) == data


def test_changed_member_preserves_unrelated_payload_and_metadata():
    data = fixture(); arc = Arc(data); e, other = arc.entries
    replacement = b'NEW-GEOMETRY' * 30
    changed = arc.replace(e.name, e.type_hash, replacement, expected_sha256=sha(data))
    back = Arc(changed)
    assert back.read(back.entries[0]) == replacement
    assert back.read(back.entries[1]) == arc.read(other)
    assert changed[other.table_offset:other.table_offset + 80] == data[other.table_offset:other.table_offset + 80]
    assert changed[other.offset:other.offset + other.compressed_size] == data[other.offset:other.offset + other.compressed_size]
    assert back.entries[0].size_word & 7 == e.size_word & 7


def test_growing_stored_member_appends_and_keeps_original_bytes():
    data = fixture(); arc = Arc(data); e = arc.entries[1]
    changed = arc.replace(e.name, e.type_hash, bytes(range(256)) * 3, expected_sha256=sha(data))
    back = Arc(changed)
    assert back.entries[1].offset == len(data)
    assert changed[e.offset:len(data)] == data[e.offset:]
    assert back.read(back.entries[0]) == arc.read(arc.entries[0])


def test_rejects_hash_mismatch_and_foreign_entry():
    data = fixture(); a, b = Arc(data), Arc(data)
    with pytest.raises(ValueError, match='source hash'):
        a.replace(a.entries[0].name, a.entries[0].type_hash, b'x', expected_sha256='f' * 64)
    with pytest.raises(ValueError, match='belong'):
        a.read(b.entries[0])


@pytest.mark.parametrize('where,value', [(4, 7), (6, 0xffff)])
def test_rejects_wrong_version_or_truncated_table(where, value):
    bad = bytearray(fixture()); struct.pack_into('>H', bad, where, value)
    with pytest.raises(ValueError):
        Arc(bad)


@pytest.mark.parametrize('where,value', [(8 + 76, 0xffffffff), (8 + 68, 0xffffffff),
                                        (8 + 72, 0xffffffff), (88 + 76, 168)])
def test_rejects_extents_size_bombs_and_overlaps(where, value):
    bad = bytearray(fixture()); struct.pack_into('>I', bad, where, value)
    with pytest.raises(ValueError):
        Arc(bad)


def test_rejects_zlib_expansion_beyond_declared_size_and_trailing_data():
    bad = bytearray(fixture()); struct.pack_into('>I', bad, 8 + 72, (8 << 3) | 2)
    arc = Arc(bad)
    with pytest.raises(ValueError, match='declared extent'):
        arc.read(arc.entries[0])
    bad = bytearray(fixture()); arc = Arc(bad); e = arc.entries[0]
    # Shorten its declared compressed extent while preserving valid archive bounds.
    struct.pack_into('>I', bad, 8 + 68, e.compressed_size - 2)
    arc = Arc(bad)
    with pytest.raises(ValueError):
        arc.read(arc.entries[0])


def test_rejects_duplicate_identity_and_unterminated_names():
    bad = bytearray(fixture()); struct.pack_into('>I', bad, 88 + 64, 0x58a15856)
    with pytest.raises(ValueError, match='duplicate'):
        Arc(bad)
    bad = bytearray(fixture()); bad[8:72] = b'x' * 64
    with pytest.raises(ValueError, match='unterminated'):
        Arc(bad)


def test_owned_chris_and_sheva_every_member_and_writer():
    root = os.environ.get('GBOX_RE5PS3_ARCS')
    if not root:
        pytest.skip('set GBOX_RE5PS3_ARCS to extracted owned character archive folder')
    expected = {'uPl00ChrisNormal.arc': (79, '51df8884b6a114101356e19fcc608b69c196e7c0cd56c626a3f7660aeb99d867'),
                'uPl01ShebaNormal.arc': (72, '27ce670e29438738d024e5ec5a7b729ea5da19eab98a668ada42da9630d92d6f')}
    for name, (count, digest) in expected.items():
        data = (Path(root) / name).read_bytes(); arc = Arc(data)
        assert sha(data) == digest and len(arc.entries) == count
        report = arc.inventory()
        assert len(report['members']) == count and report['noop_identical']
        model = next(e for e in arc.entries if e.type_hash == 0x58a15856)
        decoded = arc.read(model)
        assert decoded[:4] == b'\0DOM'
        assert arc.replace(model.name, model.type_hash, decoded, expected_sha256=digest) == data
        # Archive-level test only; an altered model is not a publishable mod.
        replacement = decoded[:-1] + bytes([decoded[-1] ^ 1])
        changed = arc.replace(model.name, model.type_hash, replacement, expected_sha256=digest)
        back = Arc(changed)
        for old, new in zip(arc.entries, back.entries):
            assert old.key == new.key
            assert back.read(new) == (replacement if old.key == model.key else arc.read(old))
        assert (Path(root) / name).read_bytes() == data
