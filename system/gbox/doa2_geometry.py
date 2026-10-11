"""DOA2 Dreamcast CHR / NaomiLib geometry, independently implemented.

Format references: NaomiMod/games-ExtractTools/DOA2/CHR_Format.md and
NaomiMod/NL-ModelFormat/wiki (VincentNL, EgregiousGuy, The_Zocker160).
Verified against the owned DOA2 LE Japan KAS00, AYA00 and GEN00 archives.
No Blender dependency. A CHR is a mesh archive, NOT a bone container.
"""
from __future__ import annotations

import math
import struct
from typing import Iterable

_U32 = struct.Struct('<I')


def _u32(data: bytes, offset: int) -> int:
    if offset < 0 or offset + 4 > len(data):
        raise ValueError(f'u32 outside archive at {offset:#x}')
    return _U32.unpack_from(data, offset)[0]


def _sphere(vertices: Iterable[tuple[float, ...]]) -> tuple[float, ...]:
    pts = list(vertices)
    if not pts:
        return (0.0, 0.0, 0.0, 0.0)
    center = tuple((min(p[k] for p in pts) + max(p[k] for p in pts)) / 2 for k in range(3))
    radius = max(math.dist(center, p[:3]) for p in pts)
    return (*center, radius)


def _triangles(flags: int, indices: list[int]) -> list[tuple[int, int, int]]:
    culling = flags & 3
    if flags & 8:
        triples = [tuple(indices[k:k+3]) for k in range(0, len(indices), 3)]
        if culling == 2:
            triples = [(y, x, z) for x, y, z in triples]
    else:
        triples = []
        for k in range(len(indices)-2):
            x, y, z = indices[k:k+3]
            if (k % 2 == 0) == (culling == 2):
                x, y = y, x
            triples.append((x, y, z))
    return [t for t in triples if len(set(t)) == 3]


def decode_chr(data: bytes) -> dict:
    if len(data) < 24 or _u32(data, 0) != 24:
        raise ValueError('not a DOA2 CHR archive')
    table, texture_table, count, texture_count = struct.unpack_from('<4I', data, 4)
    if not 0 < count <= 4096 or texture_count > 4096:
        raise ValueError('invalid model/texture count')
    if table + 4*count > texture_table or texture_table + 12*texture_count > len(data):
        raise ValueError('archive pointer tables outside CHR')
    pointers = [_u32(data, table+4*k) for k in range(count)]
    base = pointers[0]
    if base >> 24 != 0x0c:
        raise ValueError('expected absolute Dreamcast work RAM model pointers')
    offsets = [p-base+24 for p in pointers]
    if offsets != sorted(set(offsets)) or offsets[0] != 24:
        raise ValueError('non-monotonic model pointers')
    models = []
    for model_id, start in enumerate(offsets):
        model_limit = offsets[model_id+1] if model_id+1<count else table
        limit = model_limit-8 if model_id+1<count else table
        if start+24 > limit:
            raise ValueError('short NaomiLib model')
        gp0, gp1 = struct.unpack_from('<2I', data, start)
        centroid = struct.unpack_from('<4f', data, start+8)
        cursor = start+24
        meshes = []
        vertex_total = 0
        while cursor + 4 <= limit and _u32(data, cursor):
            if cursor+80 > limit:
                raise ValueError(f'truncated submesh header at {cursor:#x}')
            header = data[cursor:cursor+80]
            if _u32(header, 0) >> 29 != 4:
                raise ValueError(f'unsupported NaomiLib parameter at {cursor:#x}')
            shader = struct.unpack_from('<i', header, 36)[0]
            texture_id = struct.unpack_from('<i', header, 32)[0]
            length = _u32(header, 76)
            position = cursor+80
            stop = position+length
            if stop > limit:
                raise ValueError('submesh crosses model boundary')
            vertices, records, strips, triangles = [], [], [], []
            registered = {}
            while position < stop:
                if position+8 > stop:
                    raise ValueError('short polygon header')
                flags, count_in = struct.unpack_from('<2I', data, position)
                if flags > 0x1ff or not 0 < count_in <= 65536:
                    raise ValueError(f'invalid polygon at {position:#x}')
                logical_count = count_in * (3 if flags & 8 else 1)
                indices = []
                records_start = len(records)
                position += 8
                for _ in range(logical_count):
                    if position+4 > stop:
                        raise ValueError('short vertex record')
                    tag = _u32(data, position)
                    if 0x5ff00000 <= tag <= 0x5fffffff:
                        if position+8 > stop:
                            raise ValueError('short vertex reference')
                        rel = struct.unpack_from('<i', data, position+4)[0]
                        target = position+8+rel
                        if target not in registered:
                            raise ValueError(f'vertex reference misses earlier inline vertex at {position:#x}')
                        idx = registered[target]
                        records.append({'offset': position, 'raw': data[position:position+8], 'vertex': idx, 'reference': True})
                        position += 8
                    else:
                        size = 56 if shader == -2 else 32
                        if position+size > stop:
                            raise ValueError('inline vertex crosses submesh boundary')
                        raw = data[position:position+size]
                        xyz = struct.unpack_from('<3f', raw)
                        if shader == -3:
                            normal = tuple(max(-1, v/127) for v in struct.unpack_from('<3b', raw, 12))
                            uv = struct.unpack_from('<2f', raw, 24)
                        else:
                            normal = struct.unpack_from('<3f', raw, 12)
                            uv = struct.unpack_from('<2f', raw, size-8)
                        if not all(math.isfinite(v) for v in (*xyz, *normal, *uv)):
                            raise ValueError('non-finite decoded vertex')
                        idx = len(vertices)
                        vertices.append((*xyz, *normal, *uv))
                        registered[position] = idx
                        records.append({'offset': position, 'raw': raw, 'vertex': idx, 'reference': False})
                        position += size
                    indices.append(idx)
                strips.append({'flags': flags, 'count': count_in, 'indices': indices,
                               'records_start': records_start, 'records_count': logical_count})
                triangles.extend(_triangles(flags, indices))
                vertex_total += logical_count
            meshes.append({'offset': cursor, 'header': header, 'texture_id': texture_id,
                           'shader': shader, 'vertices': vertices, 'triangles': triangles,
                           'strips': strips, 'records': records})
            cursor = stop
        if cursor+8 > model_limit or _u32(data, cursor) != 0:
            raise ValueError(f'model has no end marker at {cursor:#x}')
        declared_vertices = _u32(data, cursor+4)
        if declared_vertices != vertex_total:
            raise ValueError(f'model {model_id} vertex count {declared_vertices} != {vertex_total}')
        gap = data[cursor+8:model_limit]
        if any(gap):
            raise ValueError('nonzero data after model end marker')
        models.append({'id': model_id, 'offset': start, 'global_flags': (gp0, gp1),
                       'centroid': centroid, 'meshes': meshes, 'vertex_count': vertex_total,
                       'end_offset': cursor+8, 'padding': gap})
    textures = [struct.unpack_from('<3I', data, texture_table+12*k) for k in range(texture_count)]
    return {'header': data[:24], 'pointer_base': base, 'model_table_offset': table,
            'texture_table_offset': texture_table, 'pointers': pointers,
            'models': models, 'textures': textures,
            'table_padding': data[table+4*count:texture_table],
            'trailing': data[texture_table+12*texture_count:]}


def roundtrip_chr(archive: dict) -> bytes:
    """Serialize decoded records/fields, retaining binary float payloads and hardware references."""
    out = bytearray(archive['header'])
    for model in archive['models']:
        if len(out) != model['offset']:
            raise ValueError('model offsets changed in identity serialization')
        out.extend(struct.pack('<2I4f', *model['global_flags'], *model['centroid']))
        for mesh in model['meshes']:
            out.extend(mesh['header'])
            for strip in mesh['strips']:
                out.extend(struct.pack('<2I', strip['flags'], strip['count']))
                n = strip['records_start']
                for record in mesh['records'][n:n+strip['records_count']]:
                    out.extend(record['raw'])
        out.extend(struct.pack('<2I', 0, model['vertex_count']))
        out.extend(model['padding'])
    out.extend(struct.pack('<%dI' % len(archive['pointers']), *archive['pointers']))
    out.extend(archive['table_padding'])
    for descriptor in archive['textures']:
        out.extend(struct.pack('<3I', *descriptor))
    out.extend(archive['trailing'])
    return bytes(out)


def encode_model(template: dict, meshes: list[dict], *, references: bool = True) -> bytes:
    """Build native NL1 triangle geometry from position/normal/UV vertices.

    Each mesh supplies ``vertices`` (8 floats), ``triangles`` (three indexes),
    and an 80-byte native material ``header``. ``texture_id`` can override its slot.
    Template supplies global_flags. Textures and game animation remain separate.
    """
    meshes = [mesh for mesh in meshes if mesh['triangles']]
    if not meshes:
        raise ValueError('native drawing requires a material header; use invisible_model for an unused part')
    pts = [v for mesh in meshes for v in mesh['vertices']]
    # Global word zero selects the indexed reference grammar, not a draw gate.
    global_flags = (int(references), template['global_flags'][1])
    out = bytearray(struct.pack('<2I4f', *global_flags, *_sphere(pts)))
    logical_total = 0
    for mesh in meshes:
        vertices = mesh['vertices']
        faces = mesh['triangles']
        if not faces:
            continue
        header = bytearray(mesh['header'])
        if len(header) != 80:
            raise ValueError('need a native 80-byte NaomiLib material header')
        shader = struct.unpack_from('<i', header, 36)[0]
        if shader not in (-1, 0, 1):
            raise ValueError('new geometry requires normal-float Lambert/constant material')
        # Reordered materials cannot inherit the preceding group's intensity
        # colors. Native format2 emits its own ARGB packet; format3 reuses it.
        pcw = _u32(header, 0)
        if (pcw >> 4) & 3 == 3:
            if shader not in (0, 1):
                raise ValueError('unsupported inherited-color material shader')
            _U32.pack_into(header, 0, pcw & ~0x10)
            _U32.pack_into(header, 40, _u32(header, 40) & ~1)
        struct.pack_into('<4f', header, 16, *_sphere(vertices))
        if 'texture_id' in mesh:
            struct.pack_into('<i', header, 32, mesh['texture_id'])
        # Native cull-small mode1, Gouraud, independent triangles. Mode1 keeps
        # donor winding without suppressing either side of a thin garment.
        flags = 0x49 | (0x20 if references else 0)
        stream = bytearray(struct.pack('<2I', flags, len(faces)))
        seen: dict[bytes, tuple[int, int]] = {}
        dma_vertex = 0
        for face in faces:
            if len(face) != 3:
                raise ValueError('only triangles can be encoded')
            for idx in face:
                if not isinstance(idx, int) or not 0 <= idx < len(vertices):
                    raise ValueError('triangle index outside vertex array')
                v = vertices[idx]
                if len(v) != 8 or not all(math.isfinite(x) for x in v):
                    raise ValueError('vertex must contain 8 finite floats')
                raw = bytearray(struct.pack('<8f', *v))
                # Both payload tags occur on every inline vertex in the owned
                # corpus and the original NaomiLib exporter.
                _U32.pack_into(raw, 0, _u32(raw, 0) | 1)
                _U32.pack_into(raw, 28, _u32(raw, 28) | 1)
                raw_key = bytes(raw)
                previous = seen.get(raw_key) if references else None
                if previous is None:
                    seen[raw_key] = (len(stream), dma_vertex)
                    stream.extend(raw)
                else:
                    target_pos, target_dma = previous
                    dma_delta = dma_vertex-target_dma
                    if dma_delta > 0xfffff:
                        seen[raw_key] = (len(stream), dma_vertex)
                        stream.extend(raw)
                    else:
                        ram_delta = target_pos-(len(stream)+8)
                        stream.extend(struct.pack('<Ii', 0x60000000-dma_delta, ram_delta))
                dma_vertex += 32
                logical_total += 1
        struct.pack_into('<I', header, 76, len(stream))
        out.extend(header)
        out.extend(stream)
    out.extend(struct.pack('<2I', 0, logical_total))
    return bytes(out)


def invisible_model(template: dict, header: bytes) -> bytes:
    """A zero-area native triangle, safe for unconditional primary rendering.

    The primary renderer consumes the first material at model+24 before it
    checks the next-group end marker. A 32-byte empty/null record lets it read
    neighboring archive bytes as a header and is not a valid removed part.
    """
    return encode_model(template, [{'header': header,
        'vertices': [(0., 0., 0., 0., 1., 0., 0., 0.)],
        'triangles': [(0, 0, 0)]}])


def replace_models(data: bytes, replacements: dict[int, bytes], *, size_budget: int | None = None) -> bytes:
    """Reassemble CHR with model pointer relocation; preserve exact texture descriptors."""
    archive = decode_chr(data)
    count = len(archive['models'])
    if any(not isinstance(k, int) or not 0 <= k < count for k in replacements):
        raise ValueError('replacement model id outside archive')
    out = bytearray(archive['header'])
    pointers = []
    for model in archive['models']:
        pointers.append(archive['pointer_base']+len(out)-24)
        body = replacements.get(model['id'])
        if body is None:
            body = data[model['offset']:model['end_offset']]
        out.extend(body)
    # Owned archives have eight zero bytes after the final model's end marker.
    out.extend(archive['models'][-1]['padding'])
    model_table = len(out)
    out.extend(struct.pack('<%dI' % count, *pointers))
    out.extend(archive['table_padding'])
    texture_table = len(out)
    for descriptor in archive['textures']:
        out.extend(struct.pack('<3I', *descriptor))
    out.extend(archive['trailing'])
    struct.pack_into('<2I', out, 4, model_table, texture_table)
    if size_budget is not None and len(out) > size_budget:
        raise ValueError(f'CHR budget exceeded: {len(out)} > {size_budget} bytes')
    result = bytes(out)
    decode_chr(result)
    return result
