"""Albedo edits must target the material's named command without rewriting its native shader."""
import struct
import zlib

import pytest

from gbox import mt_model, mtf_mrl
from tests.test_mtf_author import make_target


def fixture():
    mod = bytearray(make_target(1))
    offset = mt_model.parse_mod(bytes(mod)).header()['offsets']['materials']
    name = b'measured_material'
    mod[offset:offset + len(name)] = name
    paths = [r'pawn\body_NM', r'pawn\body_BM', r'pawn\atlas_BM']
    material_offset = 40 + len(paths) * 88
    command_offset = (material_offset + 72 + 15) & ~15
    raw = bytearray(command_offset + 48)
    struct.pack_into('<4sIIIQQQ', raw, 0, b'MRL\0', 34, 1, len(paths), mtf_mrl.RE5_SHADER_VERSION, 40, material_offset)
    for i, path in enumerate(paths):
        start = 40 + i * 88 + 24
        raw[start:start + len(path)] = path.encode('ascii')
    struct.pack_into('<QII', raw, material_offset, mtf_mrl.MATERIAL_STD, zlib.crc32(name) ^ 0xFFFFFFFF, 48)
    struct.pack_into('<I', raw, material_offset + 28, 2)
    struct.pack_into('<Q', raw, material_offset + 56, command_offset)
    for i, (value, shader) in enumerate([(1, 0x22660), (2, mtf_mrl.ALBEDO_HASH)]):
        struct.pack_into('<IIQQ', raw, command_offset + i * 24, 3, 0xCDCDCDCD, value, shader << 12 | 0x375)
    return bytes(raw), bytes(mod), command_offset


def test_binding_changes_only_albedo_index_preserving_normal_map_and_shader():
    source, model, commands = fixture()
    result, report = mtf_mrl.bind_albedo(source, model, [0], r'pawn\atlas_BM')
    expected = bytearray(source)
    struct.pack_into('<Q', expected, commands + 24 + 8, 3)
    assert result == bytes(expected)
    assert report['native_shader_preserved'] and report['secondary_maps_preserved']
    assert report['live_verified'] is False
    bindings = mtf_mrl.inspect_bindings(result, model)[0]['bindings']
    assert [b['path'] for b in bindings] == [r'pawn\body_NM', r'pawn\atlas_BM']
    assert mtf_mrl.bind_albedo(source, model, [0], r'pawn\body_BM')[0] == source


def test_mismatched_mod_material_name_is_refused():
    source, model, _ = fixture()
    model = bytearray(model)
    offset = mt_model.parse_mod(bytes(model)).header()['offsets']['materials']
    model[offset] = ord('x')
    with pytest.raises(mtf_mrl.MaterialBindingError, match='no matching'):
        mtf_mrl.bind_albedo(source, bytes(model), [0], r'pawn\atlas_BM')


@pytest.mark.parametrize('indices', [[], [0, 0], [-1], [1], [True]])
def test_invalid_or_duplicate_material_selection_is_refused(indices):
    source, model, _ = fixture()
    with pytest.raises(mtf_mrl.MaterialBindingError):
        mtf_mrl.bind_albedo(source, model, indices, r'pawn\atlas_BM')


@pytest.mark.parametrize('path', [r'pawn\body_NM', r'pawn\missing_BM'])
def test_non_albedo_or_missing_texture_slot_is_refused(path):
    source, model, _ = fixture()
    with pytest.raises(mtf_mrl.MaterialBindingError, match='existing native BM'):
        mtf_mrl.bind_albedo(source, model, [0], path)


@pytest.mark.parametrize('change', ['revision', 'texture_index', 'command_extent', 'duplicate_albedo'])
def test_unverified_layouts_and_ambiguous_commands_are_refused(change):
    source, model, commands = fixture()
    raw = bytearray(source)
    if change == 'revision':
        raw[16] ^= 1
    elif change == 'texture_index':
        struct.pack_into('<Q', raw, commands + 8, 99)
    elif change == 'command_extent':
        struct.pack_into('<Q', raw, 40 + 3 * 88 + 56, len(raw))
    else:
        struct.pack_into('<Q', raw, commands + 16, mtf_mrl.ALBEDO_HASH << 12 | 0x375)
    with pytest.raises(mtf_mrl.MaterialBindingError):
        mtf_mrl.bind_albedo(bytes(raw), model, [0], r'pawn\atlas_BM')
