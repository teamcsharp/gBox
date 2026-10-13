"""Allocate donor materials to existing, correctly described DOA2 texture slots.

This is a native BIN/material allocator. It never edits the CHR texture
descriptors, invents headers or packs several donor materials into an atlas.
The caller supplies an archive from doa2_geometry.decode_chr and primitives
from sm64_swap.load_rig. Headers are taken byte-for-byte from that archive.

PVR field definitions: KallistiOS dc/pvr.h; NaomiLib texture size table.
"""
from __future__ import annotations

import hashlib
import math
import struct
from collections import Counter
from dataclasses import replace as replace_dataclass

import numpy as np
from PIL import Image

from . import doa2_textures as T


class MaterialCapacityError(ValueError):
    """The existing archive cannot represent the requested donor materials."""

    def __init__(self, message: str, report: dict):
        super().__init__(message)
        self.report = report


def texture_directory(archive: dict) -> bytes:
    """A descriptor-only view for the BIN encoder; triples remain unchanged."""
    descriptors = archive['textures']
    return (struct.pack('<6I', 24, 24, 24, 0, len(descriptors), 0)
            + b''.join(struct.pack('<3I', *d) for d in descriptors))


def _image(primitive: dict) -> Image.Image:
    tex = primitive.get('tex')
    color = np.asarray(primitive.get('color', (255, 255, 255, 255)), dtype=float)
    if color.shape != (4,) or not np.isfinite(color).all() or np.any(color < 0) or np.any(color > 255):
        raise ValueError('donor base color must contain four finite byte values')
    if tex is None:
        rgba = np.full((1, 1, 4), 255, dtype=np.uint8)
    elif isinstance(tex, Image.Image):
        rgba = np.asarray(tex.convert('RGBA'), dtype=np.uint8)
    else:
        rgba = np.asarray(tex)
        if rgba.ndim != 3 or rgba.shape[2] not in (3, 4) or not rgba.shape[0] or not rgba.shape[1]:
            raise ValueError('donor texture must be a nonempty RGB/RGBA image')
        if rgba.dtype != np.uint8:
            raise ValueError('donor texture channels must be uint8 bytes')
        if rgba.shape[2] == 3:
            rgba = np.concatenate((rgba, np.full((*rgba.shape[:2], 1), 255, np.uint8)), axis=2)
    # Bake glTF baseColorFactor; do not discard or premultiply texture alpha.
    rgba = np.rint(rgba.astype(float) * color[None, None, :] / 255).clip(0, 255).astype(np.uint8)
    return Image.fromarray(rgba, 'RGBA')


def donor_materials(primitives: list[dict]) -> tuple[list[dict], list[int]]:
    """Deduplicate identical baked images without treating all RGBA as alpha."""
    materials, lookup, indexes = [], {}, []
    for primitive in primitives:
        image = _image(primitive)
        raw = image.tobytes()
        key = hashlib.sha256(struct.pack('<2I', *image.size) + raw).hexdigest()
        if key not in lookup:
            alpha = np.asarray(image)[..., 3]
            kind = 'opaque' if np.all(alpha == 255) else 'binary' if np.all((alpha == 0) | (alpha == 255)) else 'graded'
            lookup[key] = len(materials)
            materials.append({'id': len(materials), 'key': key, 'image': image,
                              'width': image.width, 'height': image.height,
                              'alpha': kind, 'primitives': []})
        index = lookup[key]
        materials[index]['primitives'].append(len(indexes))
        indexes.append(index)
    return materials, indexes


def native_header_bank(archive: dict, textures: list[T.Texture]) -> tuple[dict[int, list[dict]], dict]:
    """Only headers already describing their exact texture allocation qualify.

    DOA's original translucent headers use PVR list 2, SRCALPHA/INVSRCALPHA
    blending and texture alpha enabled. Their polygon-alpha bit is set by the
    game's draw path, so this does not synthesize that bit in the stored header.
    """
    bank, rejected = {}, Counter()
    seen = set()
    for model in archive['models']:
        for mesh_index, mesh in enumerate(model['meshes']):
            header = bytes(mesh['header'])
            if len(header) != 80:
                raise ValueError('native material header must contain 80 bytes')
            pcw, isp, tsp, tcw = struct.unpack_from('<4I', header)
            slot, shader = struct.unpack_from('<2i', header, 32)
            if slot < 0:
                rejected['untextured_or_shadow'] += 1
                continue
            if slot >= len(textures):
                raise ValueError(f'native material references missing texture {slot}')
            if shader not in (0, 1):
                rejected['unsupported_shader'] += 1
                continue
            tex = textures[slot]
            dimensions = (8 << ((tsp >> 3) & 7), 8 << (tsp & 7))
            if dimensions != (tex.width, tex.height):
                rejected['header_dimensions_mismatch'] += 1
                continue
            if ((tcw >> 27) & 7) != tex.pixel:
                rejected['header_pixel_mismatch'] += 1
                continue
            if bool(tcw & (1 << 30)) != (tex.format == 3):
                rejected['header_compression_mismatch'] += 1
                continue
            if tcw & (1 << 31):
                rejected['mipmapped_header'] += 1
                continue
            if not pcw & 8:
                rejected['texturing_disabled'] += 1
                continue
            fingerprint = (slot, header)
            if fingerprint in seen:
                continue
            seen.add(fingerprint)
            list_type = (pcw >> 24) & 7
            tex_alpha = not bool(tsp & (1 << 19))
            src_blend, dst_blend = (tsp >> 29) & 7, (tsp >> 26) & 7
            tex_env = (tsp >> 6) & 3
            alpha = tex.pixel in (0, 2) and list_type == 2 and tex_alpha and (src_blend, dst_blend) == (4, 5) and tex_env != 2
            punch = tex.pixel in (0, 2) and list_type == 4 and tex_alpha and tex_env != 2
            bank.setdefault(slot, []).append({'header': header, 'model_id': model['id'],
                                             'mesh_index': mesh_index, 'shader': shader,
                                             'list_type': list_type, 'alpha': alpha,
                                             'binary_alpha': alpha or punch})
    return bank, dict(rejected)


def _candidate(material: dict, tex: T.Texture, options: list[dict], allow_downscale: bool) -> tuple[int, dict] | None:
    alpha = material['alpha']
    if alpha == 'graded' and tex.pixel != 2:
        return None
    if alpha == 'binary' and tex.pixel not in (0, 2):
        return None
    if alpha == 'graded':
        options = [o for o in options if o['alpha']]
    elif alpha == 'binary':
        options = [o for o in options if o['binary_alpha']]
    # Above selection is intentionally strict for graded alpha: native
    # translucent headers only. Binary transparency may also use punch-through.
    if not options:
        return None
    sw, sh, w, h = material['width'], material['height'], tex.width, tex.height
    if not allow_downscale and (w < sw or h < sh):
        return None
    # Resolution loss dominates; aspect distortion and color quantization follow.
    down = max(0, math.log2(sw / w)) + max(0, math.log2(sh / h))
    aspect = abs(math.log2((w / h) / (sw / sh)))
    up = max(0, math.log2(w / sw)) + max(0, math.log2(h / sh))
    # colour precision first: RGB565 for opaque donors; ARGB1555 for binary alpha (5-bit colour, its 1-bit alpha is
    # exactly a cut-out) ahead of ARGB4444 (4-bit colour bands smooth shading); graded alpha needs ARGB4444
    pixel_penalty = {('opaque', 1): 0, ('opaque', 0): 1, ('opaque', 2): 3,
                     ('binary', 0): 0, ('binary', 2): 2, ('graded', 2): 0}.get((alpha, tex.pixel), 3)
    compression = 8 if tex.format == 3 else 0
    # RGB donors prefer an opaque header; avoid inheriting an eye/hair draw mode.
    def header_rank(option):
        return ((option['list_type'] != 0) if alpha == 'opaque' else False,
                option.get('synthetic', False), option['shader'] != 1, option['model_id'], option['mesh_index'])
    chosen = min(options, key=header_rank)
    mode_penalty = 12 if alpha == 'opaque' and chosen['list_type'] != 0 else 0
    cost = int(round(10000 * down + 300 * aspect + 50 * up + 40 * pixel_penalty + 100 * compression + 100 * mode_penalty)) * 4096 + tex.index
    return cost, chosen


def _assignment(costs: list[list[int | None]]) -> list[int] | None:
    """Rectangular Hungarian assignment, avoiding an extra SciPy dependency."""
    rows = len(costs)
    if not rows:
        return []
    columns = len(costs[0])
    if columns < rows:
        return None
    infinity = 10 ** 18
    values = [[infinity if c is None else c for c in row] for row in costs]
    u, v, matching, way = [0] * (rows + 1), [0] * (columns + 1), [0] * (columns + 1), [0] * (columns + 1)
    for row in range(1, rows + 1):
        matching[0] = row
        minima, visited = [infinity] * (columns + 1), [False] * (columns + 1)
        column = 0
        while True:
            visited[column] = True
            active = matching[column]
            delta, next_column = infinity, 0
            for candidate in range(1, columns + 1):
                if visited[candidate]:
                    continue
                current = values[active - 1][candidate - 1] - u[active] - v[candidate]
                if current < minima[candidate]:
                    minima[candidate], way[candidate] = current, column
                if minima[candidate] < delta:
                    delta, next_column = minima[candidate], candidate
            if delta >= infinity // 2:
                return None
            for candidate in range(columns + 1):
                if visited[candidate]:
                    u[matching[candidate]] += delta
                    v[candidate] -= delta
                else:
                    minima[candidate] -= delta
            column = next_column
            if matching[column] == 0:
                break
        while column:
            previous = way[column]
            matching[column] = matching[previous]
            column = previous
    result = [-1] * rows
    for column in range(1, columns + 1):
        if matching[column]:
            result[matching[column] - 1] = column - 1
    if any(i < 0 or costs[row][i] is None for row, i in enumerate(result)):
        return None
    return result


def allocate(archive: dict, bin_data: bytes, primitives: list[dict], *, allow_downscale: bool = False,
             encode: bool = True, iterations: int = 12, excluded_slots=(), synthesize_headers: bool = False,
             retype_argb4444: bool = False) -> dict:
    """Return native BIN and per-primitive header/texture mapping, or fail honestly.

    ``encode=False`` performs capacity planning only. ``excluded_slots`` protects
    slots still referenced by any original meshes the caller intends to retain.
    All unselected slots and padding remain byte-identical. CHR descriptors
    remain unchanged unless ``retype_argb4444`` is explicitly enabled alongside
    header synthesis. That opt-in changes only selected descriptor pixel bytes;
    the caller must omit all original meshes referencing those selected slots.
    """
    directory = texture_directory(archive)
    textures = T.descriptors(directory, bin_data)
    bank, rejected = native_header_bank(archive, textures)
    if synthesize_headers:
        from .doa2_pvr import extend_bank
        bank = extend_bank(archive, textures, bank)
    if retype_argb4444 and not synthesize_headers:
        raise ValueError('descriptor pixel conversion requires native header synthesis opt-in')
    materials, primitive_materials = donor_materials(primitives)
    excluded = set(excluded_slots)
    if any(not isinstance(i, int) or not 0 <= i < len(textures) for i in excluded):
        raise ValueError('excluded texture slot outside native archive')
    slots = [i for i in sorted(bank) if i not in excluded]
    choices = [[_candidate(m, textures[i], bank[i], allow_downscale) for i in slots] for m in materials]
    if retype_argb4444:
        # ARGB4444 for graded alpha; binary alpha may also take ARGB1555 (same size, five bits of colour instead of
        # four), which _candidate ranks above ARGB4444
        virtual_textures = {pix: [replace_dataclass(tex, pixel=pix) for tex in textures] for pix in (0, 2)}
        virtual_bank = {pix: extend_bank(archive, virtual_textures[pix], {}) for pix in (0, 2)}
        for row, material in enumerate(materials):
            if material['alpha'] == 'opaque':
                continue
            targets = (0, 2) if material['alpha'] == 'binary' else (2,)
            for column, slot in enumerate(slots):
                native = textures[slot].pixel
                for pix in targets:
                    if native == pix or (native == 0 and pix == 2):     # never trade ARGB1555 for ARGB4444
                        continue
                    virtual = virtual_textures[pix][slot]
                    converted = _candidate(material, virtual, virtual_bank[pix][slot], allow_downscale)
                    if converted is None:
                        continue
                    cost, option = converted
                    # Strongly prefer unchanged descriptors when a suitable slot
                    # exists; conversion still wins over destructive downsampling.
                    cost += 2_000_000
                    if choices[row][column] is None or cost < choices[row][column][0]:
                        choices[row][column] = (cost, {**option, 'texture_override': virtual,
                                                      'retyped_descriptor': True})
    costs = [[c[0] if c is not None else None for c in row] for row in choices]
    summary = {'donor_primitives': len(primitives), 'donor_materials': len(materials),
               'native_textures': len(textures), 'eligible_slots': len(slots),
               'eligible_alpha_slots': sum(any(o['alpha'] for o in bank[i]) for i in slots),
               'eligible_binary_alpha_slots': sum(any(o['binary_alpha'] for o in bank[i]) for i in slots),
               'excluded_slots': sorted(excluded), 'rejected_headers': rejected,
               'allow_downscale': allow_downscale,
               'synthesized_headers_opt_in': synthesize_headers,
               'descriptor_retype_opt_in': retype_argb4444,
               'donor': [{'id': m['id'], 'width': m['width'], 'height': m['height'], 'alpha': m['alpha'],
                          'candidate_slots': sum(c is not None for c in choices[m['id']]),
                          'primitives': m['primitives']} for m in materials]}
    assignment = _assignment(costs)
    if assignment is None:
        unavailable = [m['id'] for m in materials if not any(c is not None for c in choices[m['id']])]
        detail = f'; no compatible native slot for materials {unavailable}' if unavailable else '; distinct compatible slots are insufficient'
        raise MaterialCapacityError(f'Native material capacity cannot hold {len(materials)} donor images{detail}', summary)
    allocated, replacements, modified_descriptors, retypes = [], {}, list(archive['textures']), []
    for material, column in zip(materials, assignment):
        slot, chosen = slots[column], choices[material['id']][column][1]
        original_tex = textures[slot]
        tex = chosen.get('texture_override', original_tex)
        if chosen.get('retyped_descriptor'):
            wh, flags, address = modified_descriptors[slot]
            modified_descriptors[slot] = (wh, (flags & ~255) | tex.pixel, address)
            if T.texture_size(tex.width, tex.height, tex.pixel, tex.format) != original_tex.size:
                raise AssertionError('pixel conversion changes allocation size')
            retypes.append({'texture_id': slot, 'old_pixel': original_tex.pixel,
                            'new_pixel': tex.pixel, 'offset': tex.offset,
                            'payload_bytes': tex.size, 'capacity': tex.capacity,
                            'width': tex.width, 'height': tex.height, 'format': tex.format})
        replacements[slot] = material['image']
        allocated.append({'material_id': material['id'], 'texture_id': slot,
                          'header': chosen['header'], 'native_model': chosen['model_id'],
                          'native_mesh': chosen['mesh_index'], 'shader': chosen['shader'],
                          'source_size': (material['width'], material['height']),
                          'target_size': (tex.width, tex.height), 'pixel': tex.pixel,
                          'format': tex.format, 'alpha': material['alpha'],
                          'synthetic_header': chosen.get('synthetic', False),
                          'retyped_descriptor': chosen.get('retyped_descriptor', False),
                          'payload_bytes': tex.size, 'offset': tex.offset,
                          'primitives': material['primitives']})
    result_directory = texture_directory({'textures': modified_descriptors})
    result_bin = T.replace(result_directory, bin_data, replacements, iterations=iterations) if encode else None
    if result_bin is not None and len(result_bin) != len(bin_data):
        raise AssertionError('native BIN size changed')
    summary['allocations'] = [{k: value for k, value in item.items() if k != 'header'} for item in allocated]
    summary['descriptor_retypes'] = retypes
    return {'bin_data': result_bin, 'materials': allocated,
            'primitives': [allocated[i] for i in primitive_materials],
            'descriptor_bytes': b''.join(struct.pack('<3I', *d) for d in modified_descriptors),
            'textures': modified_descriptors,
            'report': summary}
