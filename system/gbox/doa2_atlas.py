"""Conservative RGBA atlas planning for native DOA2 material capacities.

Geometry and skin arrays are never reordered, split, or modified. A repeated
UV domain is baked into a rectangle and UVs are mapped affinely, so triangles
crossing repeat boundaries retain continuous sampling. Alpha classes use
separate pages. Native BIN encoding remains doa2_materials.allocate's job.
"""
from __future__ import annotations

from dataclasses import replace
import hashlib
import math
import struct

import numpy as np
from PIL import Image


class AtlasCapacityError(ValueError):
    def __init__(self, message: str, report: dict):
        super().__init__(message)
        self.report = report


def native_capacities(archive: dict, bin_data: bytes, *, excluded_slots=(),
                      synthesize_headers=False, retype_argb4444=False) -> list[dict]:
    """Return actual eligible slot sizes and header-compatible alpha classes.

    Descriptor conversion is only described when the caller explicitly enables
    the same conversion/header options in its final native material allocator.
    This function never changes descriptors, headers, or BIN bytes.
    """
    from . import doa2_materials as M, doa2_textures as T
    from .doa2_pvr import extend_bank
    textures = T.descriptors(M.texture_directory(archive), bin_data)
    bank, _ = M.native_header_bank(archive, textures)
    if synthesize_headers:
        bank = extend_bank(archive, textures, bank)
    if retype_argb4444 and not synthesize_headers:
        raise ValueError('descriptor conversion requires header synthesis opt-in')
    virtual = [replace(tex, pixel=2) for tex in textures] if retype_argb4444 else textures
    virtual_bank = extend_bank(archive, virtual, {}) if retype_argb4444 else {}
    excluded = set(excluded_slots)
    if any(not isinstance(i, int) or not 0 <= i < len(textures) for i in excluded):
        raise ValueError('excluded native texture slot is invalid')
    capacities = []
    for tex in textures:
        if tex.index in excluded or tex.index not in bank or (tex.format == 3 and tex.width != tex.height):
            continue
        options = bank[tex.index]
        classes = ['opaque']
        if tex.pixel in (0, 2) and any(o['binary_alpha'] for o in options):
            classes.append('binary')
        if tex.pixel == 2 and any(o['alpha'] for o in options):
            classes.append('graded')
        if retype_argb4444 and any(o['alpha'] for o in virtual_bank.get(tex.index, [])):
            classes = ['opaque', 'binary', 'graded']
        capacities.append({'index': tex.index, 'width': tex.width, 'height': tex.height,
                           'alpha_classes': classes, 'pixel': tex.pixel, 'format': tex.format,
                           'descriptor_retype_opt_in': bool(retype_argb4444)})
    return capacities


def _bake(primitive):
    color = np.asarray(primitive.get('color', (255, 255, 255, 255)), dtype=float)
    if color.shape != (4,) or not np.isfinite(color).all() or np.any(color < 0) or np.any(color > 255):
        raise ValueError('material color must contain four finite byte values')
    texture = primitive.get('tex')
    if texture is None:
        rgba = np.full((1, 1, 4), 255, np.uint8)
    elif isinstance(texture, Image.Image):
        rgba = np.asarray(texture.convert('RGBA'))
    else:
        rgba = np.asarray(texture)
        if rgba.dtype != np.uint8 or rgba.ndim != 3 or rgba.shape[2] not in (3, 4) or min(rgba.shape[:2]) <= 0:
            raise ValueError('texture must be a nonempty uint8 RGB/RGBA image')
        if rgba.shape[2] == 3:
            rgba = np.concatenate((rgba, np.full((*rgba.shape[:2], 1), 255, np.uint8)), axis=2)
    return np.rint(rgba.astype(float) * color[None, None, :] / 255).clip(0, 255).astype(np.uint8)


def _wrap(primitive, default):
    modes = primitive.get('wrap', default)
    if isinstance(modes, str):
        modes = (modes, modes)
    names = {10497: 'repeat', 33071: 'clamp', 33648: 'mirror'}
    modes = tuple(names.get(mode, mode) for mode in modes)
    if len(modes) != 2 or any(mode not in ('repeat', 'clamp', 'mirror') for mode in modes):
        raise ValueError('wrap must specify repeat, clamp, or mirror for U and V')
    return tuple(modes)


def _materials(primitives, default_wrap, max_repeat):
    materials, lookup, ids = [], {}, []
    for i, primitive in enumerate(primitives):
        pos, nrm, uv = (np.asarray(primitive[k]) for k in ('pos', 'nrm', 'uv'))
        triangles = np.asarray(primitive['tris'])
        if pos.ndim != 2 or pos.shape[1:] != (3,) or nrm.shape != pos.shape or uv.shape != (len(pos), 2):
            raise ValueError('vertex attributes must contain matching position, normal and UV arrays')
        if triangles.ndim != 2 or triangles.shape[1:] != (3,) or not np.issubdtype(triangles.dtype, np.integer):
            raise ValueError('triangles must be an integer Nx3 array')
        if not all(np.isfinite(a).all() for a in (pos, nrm, uv)):
            raise ValueError('vertex attributes must be finite')
        if np.any(triangles < 0) or np.any(triangles >= len(pos)):
            raise ValueError('triangle references an invalid vertex')
        for name in ('J', 'W'):
            if name in primitive and len(np.asarray(primitive[name])) != len(pos):
                raise ValueError(f'{name} skin array length differs from geometry')
        rgba, wrap = _bake(primitive), _wrap(primitive, default_wrap)
        key = hashlib.sha256(struct.pack('<2I', rgba.shape[1], rgba.shape[0]) + rgba.tobytes()
                             + repr(wrap).encode()).hexdigest()
        if key not in lookup:
            alpha = rgba[..., 3]
            kind = 'opaque' if np.all(alpha == 255) else 'binary' if np.all((alpha == 0) | (alpha == 255)) else 'graded'
            lookup[key] = len(materials)
            materials.append({'id': len(materials), 'rgba': rgba, 'wrap': wrap, 'alpha': kind,
                              'primitives': [], 'lo': np.array([0, 0], dtype=np.int64),
                              'hi': np.array([1, 1], dtype=np.int64), 'uv_bounds': None})
        material = materials[lookup[key]]
        material['primitives'].append(i)
        referenced = uv[np.unique(triangles)] if len(triangles) else uv
        if len(referenced):
            if np.any(np.abs(referenced) > 1e12):
                raise ValueError('UV coordinates exceed supported atlas numeric range')
            bounds = (referenced.min(0), referenced.max(0))
            if material['uv_bounds'] is None:
                material['uv_bounds'] = bounds
            else:
                material['uv_bounds'] = (np.minimum(material['uv_bounds'][0], bounds[0]),
                                         np.maximum(material['uv_bounds'][1], bounds[1]))
        ids.append(material['id'])
    for material in materials:
        if material['uv_bounds'] is not None:
            low, high = material['uv_bounds']
            material['lo'] = np.floor(low).astype(np.int64)
            material['hi'] = np.maximum(material['lo'] + 1, np.ceil(high).astype(np.int64))
        material['bake_allowed'] = bool(np.all(material['hi'] - material['lo'] <= max_repeat))
    return materials, ids


def _normalize_capacities(capacities):
    result = []
    for i, capacity in enumerate(capacities):
        item = dict(capacity)
        width, height = item['width'], item['height']
        if any(not isinstance(v, int) or not 8 <= v <= 1024 or v & (v - 1) for v in (width, height)):
            raise ValueError('native page sizes must be powers of two from 8 to 1024')
        classes = item.get('alpha_classes', [item.get('alpha', 'opaque')])
        if not classes or any(kind not in ('opaque', 'binary', 'graded') for kind in classes):
            raise ValueError('invalid native alpha capacity')
        item.update(index=item.get('index', i), alpha_classes=tuple(classes))
        result.append(item)
    if len({item['index'] for item in result}) != len(result):
        raise ValueError('native page indices must be unique')
    return result


def _fits(free, width, height):
    choices = [(min(w - width, h - height), w * h - width * height, y, x)
               for x, y, w, h in free if width <= w and height <= h]
    if not choices:
        return None
    _, _, y, x = min(choices)
    return x, y


def _occupy(free, rect):
    x, y, width, height = rect
    result = []
    for fx, fy, fw, fh in free:
        if x >= fx + fw or x + width <= fx or y >= fy + fh or y + height <= fy:
            result.append((fx, fy, fw, fh))
            continue
        if x > fx:
            result.append((fx, fy, x - fx, fh))
        if x + width < fx + fw:
            result.append((x + width, fy, fx + fw - x - width, fh))
        if y > fy:
            result.append((fx, fy, fw, y - fy))
        if y + height < fy + fh:
            result.append((fx, y + height, fw, fy + fh - y - height))
    result = list(dict.fromkeys(result))
    return [r for r in result if not any(r != s and r[0] >= s[0] and r[1] >= s[1]
                                        and r[0] + r[2] <= s[0] + s[2]
                                        and r[1] + r[3] <= s[1] + s[3] for s in result)]


def _plan(materials, capacities, scale, gutter, preferred_size):
    remaining, pages, placements = list(capacities), [], {}
    dimensions = {}
    for material in materials:
        height, width = material['rgba'].shape[:2]
        ratio = scale.get(material['id'], 1.) if isinstance(scale, dict) else scale
        tile_w, tile_h = max(1, round(width * ratio)), max(1, round(height * ratio))
        low, high = material['uv_bounds'] or (np.array([0, 0]), np.array([1, 1]))
        window_lo = np.floor(low * (tile_w, tile_h)).astype(np.int64)
        window_hi = np.maximum(window_lo + 1, np.ceil(high * (tile_w, tile_h)).astype(np.int64))
        material['window_lo'] = window_lo
        width, height = window_hi - window_lo
        dimensions[material['id']] = (tile_w, tile_h, int(width), int(height))
    order = sorted(materials, key=lambda m: (-max(dimensions[m['id']][2:]),
                                            -math.prod(dimensions[m['id']][2:]), m['id']))
    for material in order:
        tile_w, tile_h, width, height = dimensions[material['id']]
        padded_w, padded_h = width + 2 * gutter, height + 2 * gutter
        candidates = [(p['width'] * p['height'], p['id'], spot)
                      for p in pages if p['alpha'] == material['alpha'] and not p.get('direct') and material['bake_allowed']
                      and (spot := _fits(p['free'], padded_w, padded_h)) is not None]
        direct = False
        if candidates:
            _, page_id, (x, y) = min(candidates)
            page = pages[page_id]
        else:
            choices = []
            for slot in remaining:
                if material['alpha'] not in slot['alpha_classes']:
                    continue
                is_direct = (tile_w, tile_h) == (slot['width'], slot['height'])
                if not is_direct and (not material['bake_allowed'] or padded_w > slot['width'] or padded_h > slot['height']):
                    continue
                score = (abs(math.log2(slot['width'] * slot['height'] / preferred_size ** 2)),
                         slot['width'] * slot['height'], slot['index'])
                choices.append((score, slot, is_direct))
            if not choices:
                return None
            _, slot, direct = min(choices, key=lambda c: c[0])
            remaining.remove(slot)
            page = {**slot, 'id': len(pages), 'alpha': material['alpha'], 'direct': direct,
                    'free': [(0, 0, slot['width'], slot['height'])]}
            pages.append(page)
            x, y = 0, 0
        if direct:
            page['free'] = []
        else:
            page['free'] = _occupy(page['free'], (x, y, padded_w, padded_h))
        placements[material['id']] = {'page': page['id'], 'x': x, 'y': y, 'direct': direct,
                                      'tile': (tile_w, tile_h), 'expanded': (width, height),
                                      'window_lo': material['window_lo'].copy()}
    return pages, placements


def _axis_indices(start, length, size, mode):
    indexes = np.arange(start, start + length)
    if mode == 'repeat':
        return indexes % size
    if mode == 'clamp':
        return np.clip(indexes, 0, size - 1)
    indexes %= 2 * size
    return np.where(indexes < size, indexes, 2 * size - 1 - indexes)


def atlas_primitives(primitives: list[dict], capacities: list[dict], *, allow_downscale=False,
                     gutter=2, preferred_size=256, default_wrap='repeat', max_repeat=16) -> dict:
    """Return copied primitive dictionaries and RGBA pages, or a capacity error.

    Direct native_sampler pages retain original UVs and their original sampler
    modes. Other pages bake repeat/clamp/mirror
    domains with wrap-aware gutters. No UV is silently clipped. Downsampling is
    opt-in, attempts full resolution first, and reports exact per-image sizes.
    """
    if not primitives:
        raise ValueError('atlas needs donor primitives')
    if not isinstance(gutter, int) or gutter < 1 or gutter > 16:
        raise ValueError('atlas gutter must be from 1 to 16 pixels')
    if not isinstance(max_repeat, int) or max_repeat < 1:
        raise ValueError('repeat limit must be a positive integer')
    if preferred_size < 8 or preferred_size > 1024:
        raise ValueError('preferred page size must be from 8 to 1024')
    capacities = _normalize_capacities(capacities)
    materials, material_ids = _materials(primitives, default_wrap, max_repeat)
    plan = _plan(materials, capacities, 1., gutter, preferred_size)
    scale, scope = 1., 'all'
    if plan is None and allow_downscale:
        candidates, seen = [], set()
        scopes = [('small_64', lambda size: size <= 64),
                  ('small_128', lambda size: size <= 128),
                  ('large_128', lambda size: size >= 128), ('all', lambda size: True)]
        for ratio in (.875, .75, .625, .5, .375, .25, .125, .0625, .03125, .015625, .0078125):
            for scope_name, applies in scopes:
                scales = {m['id']: ratio if applies(max(m['rgba'].shape[:2])) else 1. for m in materials}
                identity = tuple(scales.values())
                if identity in seen:
                    continue
                seen.add(identity)
                candidate = _plan(materials, capacities, scales, gutter, preferred_size)
                if candidate is None:
                    continue
                _, placed = candidate
                # Preserve larger detail maps when only small buckets need
                # consolidation. Alpha maps receive extra weight; neither
                # alpha nor geometry is discarded to obtain a cheaper plan.
                lost = sum((math.prod(m['rgba'].shape[:2]) - math.prod(placed[m['id']]['tile']))
                           * (2 if m['alpha'] != 'opaque' else 1) for m in materials)
                changed = sum(tuple(reversed(m['rgba'].shape[:2])) != placed[m['id']]['tile'] for m in materials)
                candidates.append(((lost, changed, len(candidate[0])), ratio, scope_name, candidate))
        if candidates:
            _, scale, scope, plan = min(candidates, key=lambda item: item[0])
    summary = {'source_primitives': len(primitives), 'source_materials': len(materials),
               'native_eligible_slots': len(capacities), 'allow_downscale': bool(allow_downscale),
               'gutter_pixels': gutter, 'default_wrap': default_wrap, 'repeat_limit': max_repeat, 'uvs_clamped': False,
               'triangles_split': False, 'geometry_modified': False}
    if plan is None:
        raise AtlasCapacityError('RGBA atlas cannot fit the compatible native page capacities', summary)
    pages, placements = plan
    images = [Image.new('RGBA', (p['width'], p['height']),
                        (0, 0, 0, 255 if p['alpha'] == 'opaque' else 0)) for p in pages]
    records = []
    for material in materials:
        placement = placements[material['id']]
        page, image = pages[placement['page']], images[placement['page']]
        rgba = material['rgba']
        source_size = (rgba.shape[1], rgba.shape[0])
        tile_size = placement['tile']
        resized = tile_size != source_size
        if resized:
            resample = Image.Resampling.NEAREST if material['alpha'] == 'binary' else Image.Resampling.LANCZOS
            rgba = np.asarray(Image.fromarray(rgba).resize(tile_size, resample))
        if placement['direct']:
            image.paste(Image.fromarray(rgba), (0, 0))
            rect = [0, 0, *tile_size]
        else:
            width, height = placement['expanded']
            u = _axis_indices(int(placement['window_lo'][0]) - gutter,
                              width + 2 * gutter, tile_size[0], material['wrap'][0])
            v = _axis_indices(int(placement['window_lo'][1]) - gutter,
                              height + 2 * gutter, tile_size[1], material['wrap'][1])
            image.paste(Image.fromarray(rgba[v[:, None], u[None, :]]),
                        (placement['x'], placement['y']))
            rect = [placement['x'] + gutter, placement['y'] + gutter, width, height]
        records.append({'material': material['id'], 'page': page['id'], 'native_slot_hint': page['index'],
                        'alpha': material['alpha'], 'source_size': source_size, 'tile_size': tile_size,
                        'resized': resized, 'repeat_domain': [material['lo'].tolist(), material['hi'].tolist()],
                        'wrap': list(material['wrap']), 'rect': rect,
                        'window_origin_pixels': placement['window_lo'].tolist(),
                        'mode': 'native_sampler' if placement['direct'] else 'baked_domain',
                        'primitives': material['primitives']})
    output = []
    for primitive, material_id in zip(primitives, material_ids):
        material, record = materials[material_id], records[material_id]
        page = pages[record['page']]
        uv = np.asarray(primitive['uv'], dtype=float).copy()
        if record['mode'] != 'native_sampler':
            x, y, _, _ = record['rect']
            uv = (uv * record['tile_size'] - record['window_origin_pixels'] + (x, y)) / (page['width'], page['height'])
        enums = {'repeat': 10497, 'clamp': 33071, 'mirror': 33648}
        wrap = tuple(enums[m] for m in material['wrap']) if record['mode'] == 'native_sampler' else (33071, 33071)
        output.append({**primitive, 'uv': uv, 'tex': images[record['page']],
                       'color': (255, 255, 255, 255), 'wrap': wrap})
    summary.update(atlas_pages=len(pages), scale_attempt=scale, resize_scope=scope,
                   resize_selection='minimize weighted lost source pixels across conservative size buckets',
                   resized_materials=sum(r['resized'] for r in records), materials=records,
                   pages=[{k: p[k] for k in ('id', 'index', 'width', 'height', 'alpha', 'direct')} for p in pages],
                   source_triangles=sum(len(p['tris']) for p in primitives),
                   output_triangles=sum(len(p['tris']) for p in output))
    return {'primitives': output, 'pages': images, 'report': summary}
