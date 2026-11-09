"""Whole native resource swaps retain entry identity, payload length and compression framing."""
import struct
import zlib

import pytest

from gbox import model_swap, mt_arc


def entry(name, raw, *, window=15, flags=0x40):
    stream = zlib.compressobj(6, wbits=window)
    data = stream.compress(raw) + stream.flush()
    return mt_arc.Entry(name, 0x241F5DEB, flags << 24 | len(raw), len(data), 0, data)


def archive(*entries):
    return mt_arc.build(mt_arc.Arc(7, list(entries)))


def mrl(texture):
    data = bytearray(64 + 88)
    struct.pack_into('<4sIII', data, 0, b'MRL\0', 34, 1, 1)
    struct.pack_into('<I', data, 0x18, 40)
    path = texture.encode('ascii')
    data[64:64 + len(path)] = path
    return bytes(data)


@pytest.mark.parametrize('window', [15, -15])
def test_discovery_accepts_both_stream_framings_and_ignores_unrelated_payload(window):
    texture = r'pawn\donor\body_BM'
    source = archive(entry('same', mrl(texture), window=window),
                     entry('same', b'MOD\0geometry', window=window),
                     entry('other', b'TEX\0texture', window=window),
                     mt_arc.Entry('bad', 0, 0, 3, 0, b'bad'))
    parsed = mt_arc.parse(source)
    assert model_swap.model_indices(parsed) == [0, 1]
    assert model_swap.model_indices(parsed, b'MOD\0') == [1]
    assert model_swap.model_paths(source) == [texture]


@pytest.mark.parametrize('window', [15, -15])
def test_swap_copies_exact_donor_stream_and_size_tag_for_shared_names(window):
    target = archive(entry('shared', mrl('old'), flags=0x60), entry('shared', b'MOD\0old', flags=0x40))
    donor = archive(entry('other', b'MOD\0longer donor geometry', window=window, flags=0x80),
                    entry('other', mrl('new'), window=window, flags=0x80))
    result = model_swap.swap_models(target, donor, geometry=True, textures=False)
    rebuilt, original, incoming = map(mt_arc.parse, [result['data'], target, donor])
    assert [e.name for e in rebuilt.entries] == ['shared', 'shared']
    for i, donor_i in [(0, 1), (1, 0)]:
        assert rebuilt.entries[i].data == incoming.entries[donor_i].data
        assert rebuilt.entries[i].tag == (original.entries[i].tag & 0xFF000000) | (incoming.entries[donor_i].tag & 0xFFFFFF)
        assert rebuilt.entries[i].tag & 0xFFFFFF == len(zlib.decompress(rebuilt.entries[i].data, window))


def test_default_material_swap_leaves_geometry_intact_and_copies_referenced_texture():
    texture = r'pawn\donor\body_BM'
    target = archive(entry('shared', mrl('old')), entry('shared', b'MOD\0target geometry'))
    donor = archive(entry('other', mrl(texture), window=-15), entry('other', b'MOD\0donor geometry'),
                    entry(texture, b'TEX\0native texture'))
    result = model_swap.swap_models(target, donor)
    rebuilt = mt_arc.parse(result['data'])
    original = mt_arc.parse(target).entries[1]
    assert (rebuilt.entries[1].name, rebuilt.entries[1].hash, rebuilt.entries[1].tag, rebuilt.entries[1].data) == (
        original.name, original.hash, original.tag, original.data)
    assert result['textures'] == [texture]
    assert rebuilt.entries[2].data == mt_arc.parse(donor).entries[2].data
    assert rebuilt.entries[2].tag == mt_arc.parse(donor).entries[2].tag
