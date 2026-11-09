"""Bounded albedo binding edits for measured RE5 Switch MRL v34 resources.

The 64-bit layout follows Albam's MRL schema and was checked against every material
in owned uEm10/em1000: 70 name hashes, 72-byte descriptors and 24-byte commands.
Reference: https://github.com/Brachi/albam/blob/master/albam/engines/mtfw/structs/mrl.py
Unknown shader layouts fail. Existing shader programs, buffers and texture slots stay intact.
"""
from __future__ import annotations

import struct
import zlib

from . import mt_model

RE5_SHADER_VERSION = 0x7BE0E51F
MATERIAL_STD = 0xCDCDCDCD5FB0EBE4
ALBEDO_HASH = 0xCD06F
MAX_BYTES = 16 * 1024 * 1024


class MaterialBindingError(ValueError):
    """The source material binding is not a measured, unambiguous RE5 layout."""


def _span(data, offset, size, label):
    if offset < 0 or size < 0 or offset + size > len(data):
        raise MaterialBindingError(f'{label} runs outside the MRL')


def parse(data: bytes) -> dict:
    """Read only bounded native texture slots and material commands; return all binding offsets."""
    data = bytes(data)
    if not 40 <= len(data) <= MAX_BYTES:
        raise MaterialBindingError('MRL byte length is outside limits')
    magic, version, count, texture_count, shader, texture_offset, material_offset = struct.unpack_from('<4sIIIQQQ', data)
    if (magic, version, shader, texture_offset) != (b'MRL\0', 34, RE5_SHADER_VERSION, 40):
        raise MaterialBindingError('expected the measured RE5 Switch 64-bit MRL shader revision')
    if not 1 <= count <= 4096 or not 1 <= texture_count <= 4096:
        raise MaterialBindingError('MRL material/texture counts are outside limits')
    texture_end = texture_offset + texture_count * 88
    if material_offset != texture_end:
        raise MaterialBindingError('MRL texture and material table extents do not agree')
    _span(data, texture_offset, texture_count * 88, 'texture table')
    _span(data, material_offset, count * 72, 'material table')
    table_end = material_offset + count * 72
    textures = []
    for index in range(texture_count):
        raw = data[texture_offset + index * 88 + 24:texture_offset + index * 88 + 88]
        if b'\0' not in raw:
            raise MaterialBindingError('texture path is not terminated inside its slot')
        raw = raw.split(b'\0', 1)[0]
        if not raw or any(v < 32 or v > 126 for v in raw):
            raise MaterialBindingError('texture path is not printable ASCII')
        textures.append(raw.decode('ascii'))
    records, occupied, hashes = [], [], set()
    for index in range(count):
        offset = material_offset + index * 72
        kind, name_hash, buffer_size = struct.unpack_from('<QII', data, offset)
        resources = struct.unpack_from('<I', data, offset + 28)[0] & 0xFFF
        command_offset, animation_offset = struct.unpack_from('<QQ', data, offset + 56)
        if kind != MATERIAL_STD or name_hash in hashes:
            raise MaterialBindingError('unknown material type or duplicate material name hash')
        hashes.add(name_hash)
        if not resources or resources * 24 > buffer_size or command_offset < table_end:
            raise MaterialBindingError('material commands exceed their declared buffer')
        _span(data, command_offset, buffer_size, 'material command buffer')
        animation_size = struct.unpack_from('<I', data, offset + 52)[0]
        if animation_size:
            if animation_offset < table_end:
                raise MaterialBindingError('material animation data overlaps its table')
            _span(data, animation_offset, animation_size, 'material animation data')
        occupied.append((command_offset, command_offset + buffer_size))
        bindings = []
        for resource in range(resources):
            at = command_offset + resource * 24
            command, filler, value, shader_id = struct.unpack_from('<IIQQ', data, at)
            command_type = command & 15
            if command_type not in (0, 1, 2, 3, 4) or filler != 0xCDCDCDCD or shader_id >> 32:
                raise MaterialBindingError('unknown material command layout')
            if command_type == 3:
                if not 1 <= value <= texture_count:
                    raise MaterialBindingError('material texture index runs outside its one-based table')
                bindings.append({'shader_hash': shader_id >> 12, 'texture_index': value - 1,
                                 'path': textures[value - 1], 'value_offset': at + 8})
        records.append({'index': index, 'name_hash': name_hash, 'bindings': bindings})
    occupied.sort()
    if any(a[1] > b[0] for a, b in zip(occupied, occupied[1:])):
        raise MaterialBindingError('material command buffers overlap')
    return {'textures': textures, 'materials': records, 'shader_version': shader}


def inspect_bindings(mrl: bytes, model: bytes | mt_model.ModFile) -> list[dict]:
    """Match MOD material indices to MRL records by the native name hash, never table order alone."""
    model = mt_model.parse_mod(model) if isinstance(model, bytes) else model
    header = model.header()
    if (header['version'], header['revision']) != (211, 0):
        raise MaterialBindingError('expected the measured RE5 Switch MOD revision')
    count, offsets = header['material_count'], header['offsets']
    if offsets['materials'] + count * 128 != offsets['meshes']:
        raise MaterialBindingError('MOD material name table does not match its count')
    table = parse(mrl)
    by_hash = {record['name_hash']: record for record in table['materials']}
    found = []
    for index in range(count):
        raw = model.raw[offsets['materials'] + index * 128:offsets['materials'] + (index + 1) * 128]
        name = raw.split(b'\0', 1)[0]
        if b'\0' not in raw or not name or any(v < 32 or v > 126 for v in name):
            raise MaterialBindingError('MOD material name is not bounded printable ASCII')
        record = by_hash.get(zlib.crc32(name) ^ 0xFFFFFFFF)
        if record is None:
            raise MaterialBindingError('MOD material name has no matching MRL descriptor')
        found.append(record | {'mod_index': index, 'name': name.decode('ascii')})
    return found


def _is_albedo_name(path: str) -> bool:
    """A native albedo slot: `..._BM`, or `..._BM_NN` as the giant Majini's `em2400_BM_01` is named."""
    name = path.replace('/', '\\').rsplit('\\', 1)[-1]
    return name.endswith('_BM') or (name.rsplit('_', 1)[0].endswith('_BM') and name.rsplit('_', 1)[-1].isdigit())


def bind_albedo(mrl: bytes, model: bytes | mt_model.ModFile, material_indices, texture_path: str):
    """Point selected materials' existing albedo command at an existing native BM slot.

    The caller writes its atlas to that texture resource separately. Secondary maps and
    shader choices remain native; gameplay appearance and skin still require evidence.
    """
    selected = list(material_indices)
    if not selected or len(set(selected)) != len(selected):
        raise MaterialBindingError('choose distinct material indices for albedo binding')
    table, records = parse(mrl), inspect_bindings(mrl, model)
    texture_path = texture_path.replace('/', '\\')
    matches = [i for i, path in enumerate(table['textures']) if path == texture_path]
    if len(matches) != 1 or not _is_albedo_name(texture_path):
        raise MaterialBindingError('atlas target must name one existing native BM texture slot')
    texture_index = matches[0]
    edits = []
    for index in selected:
        if not isinstance(index, int) or isinstance(index, bool) or not 0 <= index < len(records):
            raise MaterialBindingError('selected MOD material index is outside the model')
        record = records[index]
        albedo = [binding for binding in record['bindings'] if binding['shader_hash'] == ALBEDO_HASH]
        if len(albedo) != 1 or not _is_albedo_name(albedo[0]['path']):
            raise MaterialBindingError('selected material does not have one measured native albedo BM binding')
        edits.append((index, albedo[0]))
    result = bytearray(mrl)
    for _, binding in edits:
        struct.pack_into('<Q', result, binding['value_offset'], texture_index + 1)
    result = bytes(result)
    checked = inspect_bindings(result, model)
    for index, _ in edits:
        albedo = next(binding for binding in checked[index]['bindings'] if binding['shader_hash'] == ALBEDO_HASH)
        if albedo['path'] != texture_path:
            raise MaterialBindingError('written albedo binding failed reread')
    return result, {'texture_path': texture_path, 'texture_index': texture_index,
                    'materials': [{'index': index, 'previous_texture': binding['path']} for index, binding in edits],
                    'native_shader_preserved': True, 'secondary_maps_preserved': True, 'live_verified': False}
