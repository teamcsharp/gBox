"""Experimental donor appearance preparation for native MT Framework texture writers.

This module makes an RGBA atlas and matching UVs. It does not write TEX/MRL resources,
retarget skin weights, or establish that a native shader renders this appearance.
"""
from __future__ import annotations

from pathlib import Path
import math

import numpy as np
from PIL import Image

from . import characters
from .crazy_taxi_look import Region, _pack, atlas_uv

MAX_TRIANGLES = 200_000
MAX_PIXELS = 16_777_216
MAX_MATERIALS = 256
MAX_UV_TILES = 16


class MaterialError(ValueError):
    """Source appearance cannot be represented by this bounded atlas path."""


def _normal_pose(normals, linear):
    """Inverse transpose of the same posed linear map used by each vertex.

    Invalid source normals or singular transforms remain NaN so their corners
    use geometric face normals; a valid source smoothing normal is never lost.
    """
    if normals is None:
        return None
    linear = np.broadcast_to(linear, (len(normals), 3, 3))
    result = np.full_like(normals, np.nan)
    valid = np.isfinite(normals).all(axis=1) & (np.linalg.norm(normals, axis=1) > 1e-12)
    valid &= np.isfinite(linear).all(axis=(1, 2)) & (np.abs(np.linalg.det(linear)) > 1e-12)
    if np.any(valid):
        normal_matrix = np.linalg.inv(linear[valid]).transpose(0, 2, 1)
        posed = np.einsum('nij,nj->ni', normal_matrix, normals[valid])
        lengths = np.linalg.norm(posed, axis=1)
        good = np.isfinite(posed).all(axis=1) & (lengths > 1e-12)
        result[np.flatnonzero(valid)[good]] = posed[good] / lengths[good, None]
    return result


def _skin_source(gl, acc, world, node, attributes, positions, normals=None):
    """Pose the donor with all supplied influences and retain actual glTF node IDs."""
    skin = gl['skins'][node['skin']]
    joint_nodes = skin['joints']
    if not joint_nodes or any(not isinstance(j, int) or not 0 <= j < len(world) for j in joint_nodes):
        raise MaterialError('source skin joint nodes are outside the scene')
    channels, weights = [], []
    for suffix in ('0', '1'):
        jkey, wkey = 'JOINTS_' + suffix, 'WEIGHTS_' + suffix
        if jkey not in attributes and wkey not in attributes and suffix == '1':
            continue
        if jkey not in attributes or wkey not in attributes:
            raise MaterialError('source skin needs matching joint and weight attributes')
        joints = np.asarray(acc(attributes[jkey]))
        influence = np.asarray(acc(attributes[wkey]), float)
        if (joints.shape != (len(positions), 4) or joints.dtype.kind not in 'ui'
                or influence.shape != joints.shape or not np.isfinite(influence).all()
                or np.any(influence < 0) or np.any(joints < 0) or np.any(joints >= len(joint_nodes))):
            raise MaterialError('source skin joint/weight channels are invalid')
        channels.append(joints.astype(int))
        weights.append(influence)
    joints, influence = np.concatenate(channels, axis=1), np.concatenate(weights, axis=1)
    total = influence.sum(axis=1)
    if np.any(total <= 0):
        raise MaterialError('source skin vertex has no positive influence')
    influence = influence / total[:, None]
    if 'inverseBindMatrices' in skin:
        inverse = np.asarray(acc(skin['inverseBindMatrices']), float)
        if inverse.shape != (len(joint_nodes), 16) or not np.isfinite(inverse).all():
            raise MaterialError('source inverse bind matrices are invalid')
        inverse = inverse.reshape(-1, 4, 4).transpose(0, 2, 1)
    else:
        inverse = np.tile(np.eye(4), (len(joint_nodes), 1, 1))
    matrices = np.asarray([world[node_id] @ inverse[i] for i, node_id in enumerate(joint_nodes)])
    if not np.isfinite(matrices).all() or not np.allclose(matrices[:, 3, :], [0, 0, 0, 1], atol=1e-6):
        raise MaterialError('source skin matrices are not finite affine transforms')
    posed = np.zeros_like(positions)
    linear = np.zeros((len(positions), 3, 3)) if normals is not None else None
    for column in range(joints.shape[1]):
        matrix = matrices[joints[:, column]]
        transformed = np.einsum('nij,nj->ni', matrix[:, :3, :3], positions) + matrix[:, :3, 3]
        posed += transformed * influence[:, column, None]
        if linear is not None:
            linear += matrix[:, :3, :3] * influence[:, column, None, None]
    owners = []
    for vertex_joints, vertex_weights in zip(joints, influence):
        merged = {}
        for joint, weight in zip(vertex_joints, vertex_weights):
            if weight > 0:
                node_id = joint_nodes[int(joint)]
                merged[node_id] = merged.get(node_id, 0.0) + float(weight)
        ordered = sorted(merged.items())
        owners.append((tuple(j for j, _ in ordered), tuple(w for _, w in ordered)))
    return posed, owners, _normal_pose(normals, linear)


def build_atlas(materials: list[dict], uv_ranges: dict[int, tuple], *, size=(512, 512)):
    """Return fixed-size RGBA pixels and regions; colours multiply all four source channels.

    Reuses the established shelf packing and UV mapping from crazy_taxi_look. Unlike
    its opaque driver atlas, texture alpha and flat-colour alpha are retained here.
    Supported sampler behaviour is repeat, including negative and repeated UV tiles.
    """
    width, height = size
    if any(not isinstance(v, int) or v < 16 or v > 4096 for v in size) or width * height > MAX_PIXELS:
        raise MaterialError('atlas dimensions must be integers from 16 to 4096 within the pixel budget')
    if not 1 <= len(uv_ranges) <= MAX_MATERIALS or len(materials) > MAX_MATERIALS:
        raise MaterialError('atlas material count is outside limits')
    prepared = {}
    pixels = 0
    for index, bounds in uv_ranges.items():
        if not isinstance(index, int) or not 0 <= index < len(materials):
            raise MaterialError('atlas material index is outside the source')
        if len(bounds) != 4 or not all(math.isfinite(float(v)) for v in bounds):
            raise MaterialError('material UV bounds must be finite')
        umin, vmin, umax, vmax = map(float, bounds)
        if umin > umax or vmin > vmax:
            raise MaterialError('material UV bounds are reversed')
        colour = np.asarray(materials[index].get('colour', (255, 255, 255, 255)), float)
        if colour.shape != (4,) or not np.isfinite(colour).all() or np.any(colour < 0) or np.any(colour > 255):
            raise MaterialError('material colour must contain four finite byte channels')
        texture = materials[index].get('tex')
        if texture is not None:
            texture = np.asarray(texture)
            if texture.ndim != 3 or texture.shape[2] != 4 or texture.dtype != np.uint8 or min(texture.shape[:2]) < 1:
                raise MaterialError('material textures must be nonempty uint8 RGBA images')
            pixels += texture.shape[0] * texture.shape[1]
            if pixels > MAX_PIXELS:
                raise MaterialError('source textures exceed the pixel budget')
        u0, v0 = math.floor(umin), math.floor(vmin)
        tiles_u, tiles_v = max(1, math.ceil(umax) - u0), max(1, math.ceil(vmax) - v0)
        if max(tiles_u, tiles_v) > MAX_UV_TILES:
            raise MaterialError('material UV repetition exceeds the atlas tile budget')
        prepared[index] = texture, colour, u0, v0, tiles_u, tiles_v
    regions = {}
    scale = 1.0
    while scale >= 1 / 16:
        regions = {}
        for index, (texture, colour, u0, v0, tu, tv) in prepared.items():
            if texture is None:
                regions[index] = Region(flat=True)
            else:
                th, tw = texture.shape[:2]
                regions[index] = Region(cw=max(1, round(tw * scale)), ch=max(1, round(th * scale)),
                                        u0=u0, v0=v0, tiles_u=tu, tiles_v=tv, flat=False)
        if _pack(regions, width, height):
            break
        scale /= 2
    else:
        raise MaterialError('source materials do not fit the requested atlas')
    result = np.zeros((height, width, 4), np.uint8)
    for index, region in regions.items():
        texture, colour, *_ = prepared[index]
        if texture is None:
            result[region.y:region.y + region.h, region.x:region.x + region.w] = np.rint(colour).astype(np.uint8)
            continue
        if (texture.shape[1], texture.shape[0]) != (region.cw, region.ch):
            texture = np.asarray(Image.fromarray(texture).resize((region.cw, region.ch), Image.Resampling.BOX))
        tile = np.rint(texture.astype(float) * colour / 255).clip(0, 255).astype(np.uint8)
        g = region.gutter
        ys = np.arange(-g, region.h + g) % region.ch
        xs = np.arange(-g, region.w + g) % region.cw
        result[region.y - g:region.y + region.h + g, region.x - g:region.x + region.w + g] = tile[np.ix_(ys, xs)]
    return result, regions, {'width': width, 'height': height, 'materials': len(regions), 'texture_scale': scale,
                              'alpha_preserved': True}


def source_mesh(path: Path, *, atlas_size=(512, 512), strict_samplers: bool | str = True):
    """Return (vertices, triangles, PIL RGBA atlas, report) in the source's posed world space.

    Vertex records carry atlas UVs and source_material for diagnostics. Skin matrices
    place the source bind pose; these records do not claim target skeleton bindings.
    Unsupported UV transforms, sampler modes and nontriangle geometry fail explicitly.
    ``strict_samplers='in_range'`` accepts a clamped or mirrored sampler whose UVs stay
    inside 0..1, where its wrap mode cannot show; outside that range it still fails.
    """
    path = Path(path)
    if path.stat().st_size > 64 * 1024 * 1024:
        raise MaterialError('source model exceeds the 64 MiB input budget')
    gl, acc, image, world = characters._load(path)
    materials, material_map, ranges, chunks, bounded = [], {}, {}, [], set()
    count = 0
    alpha_modes = set()
    for ni, node in enumerate(gl.get('nodes', [])):
        if 'mesh' not in node:
            continue
        for primitive in gl['meshes'][node['mesh']]['primitives']:
            if primitive.get('mode', 4) != 4:
                raise MaterialError('atlas import requires triangle-list primitives')
            attrs = primitive['attributes']
            if 'COLOR_0' in attrs:
                raise MaterialError('vertex colours require baking before atlas import')
            positions = np.asarray(acc(attrs['POSITION']), float)
            if positions.ndim != 2 or positions.shape[1] != 3 or not np.isfinite(positions).all():
                raise MaterialError('source positions must be finite three-component vectors')
            normals = np.asarray(acc(attrs['NORMAL']), float) if 'NORMAL' in attrs else None
            if normals is not None and normals.shape != positions.shape:
                normals = None
            if 'skin' in node:
                positions, owners, normals = _skin_source(gl, acc, world, node, attrs, positions, normals)
            else:
                matrix = world[ni]
                positions = positions @ matrix[:3, :3].T + matrix[:3, 3]
                normals = _normal_pose(normals, matrix[:3, :3])
                owners = [((ni,), (1.0,))] * len(positions)
            uv = np.asarray(acc(attrs['TEXCOORD_0']), float) if 'TEXCOORD_0' in attrs else np.zeros((len(positions), 2))
            if uv.shape != (len(positions), 2) or not np.isfinite(uv).all() or not np.isfinite(positions).all():
                raise MaterialError('source UVs or transformed positions are invalid')
            indices = np.asarray(acc(primitive['indices'])).reshape(-1) if 'indices' in primitive else np.arange(len(positions))
            if indices.dtype.kind not in 'ui' or len(indices) % 3 or np.any(indices < 0) or np.any(indices >= len(positions)):
                raise MaterialError('source triangle indices are outside their vertex array')
            count += len(indices) // 3
            if count > MAX_TRIANGLES:
                raise MaterialError('source exceeds the triangle budget')
            if not len(indices):
                continue
            source_material = primitive.get('material')
            if source_material not in material_map:
                material = {} if source_material is None else gl['materials'][source_material]
                pbr = material.get('pbrMetallicRoughness', {})
                colour = np.asarray(pbr.get('baseColorFactor', (1, 1, 1, 1)), float)
                if colour.shape != (4,) or not np.isfinite(colour).all() or np.any(colour < 0) or np.any(colour > 1):
                    raise MaterialError('source base colour factor is invalid')
                tex = None
                texture_info = pbr.get('baseColorTexture')
                if texture_info is not None:
                    if texture_info.get('texCoord', 0) != 0 or texture_info.get('extensions'):
                        raise MaterialError('atlas import supports only untransformed TEXCOORD_0')
                    texture = gl['textures'][texture_info['index']]
                    sampler = gl.get('samplers', [])[texture['sampler']] if 'sampler' in texture else {}
                    if strict_samplers and any(sampler.get(key, 10497) != 10497 for key in ('wrapS', 'wrapT')):
                        if strict_samplers != 'in_range':
                            raise MaterialError('atlas import currently supports repeat texture samplers only')
                        bounded.add(len(materials))
                    if 'TEXCOORD_0' not in attrs:
                        raise MaterialError('textured source primitive has no UVs')
                    tex = image(texture_info['index'])
                alpha_modes.add(material.get('alphaMode', 'OPAQUE'))
                material_map[source_material] = len(materials)
                materials.append({'tex': tex, 'colour': colour * 255})
                if len(materials) > MAX_MATERIALS:
                    raise MaterialError('source exceeds the material budget')
            mi = material_map[source_material]
            if materials[mi]['tex'] is not None and 'TEXCOORD_0' not in attrs:
                raise MaterialError('textured source primitive has no UVs')
            used_uv = uv[indices]
            bounds = (*used_uv.min(axis=0), *used_uv.max(axis=0))
            if mi in ranges:
                old = ranges[mi]
                bounds = (min(old[0], bounds[0]), min(old[1], bounds[1]), max(old[2], bounds[2]), max(old[3], bounds[3]))
            ranges[mi] = bounds
            chunks.append((positions, uv, indices.reshape(-1, 3), mi, owners, normals))
    for index in sorted(bounded & set(ranges)):
        if min(ranges[index][:2]) < -1e-4 or max(ranges[index][2:]) > 1 + 1e-4:
            raise MaterialError('a clamped or mirrored sampler is used outside the 0..1 UV range; '
                                'the atlas cannot reproduce it')
    atlas, regions, report = build_atlas(materials, ranges, size=atlas_size)
    vertices, triangles, lookup = [], [], {}
    skipped = 0
    source_normal_corners = fallback_normal_corners = 0
    for positions, uv, faces, mi, owners, normals in chunks:
        mapped_uv = atlas_uv(regions[mi], uv, atlas.shape[1], atlas.shape[0])
        for face in faces:
            points = positions[face]
            normal = np.cross(points[1] - points[0], points[2] - points[0])
            length = float(np.linalg.norm(normal))
            if not length:
                skipped += 1
                continue
            face_normal = tuple(float(v) for v in normal / length)
            # Oppositely oriented UV charts may meet at identical position,
            # normal and UV values. Keep their tangent handedness seams split
            # before the native author averages UV derivatives per vertex.
            delta = mapped_uv[face[1:]] - mapped_uv[face[0]]
            determinant = delta[0, 0] * delta[1, 1] - delta[0, 1] * delta[1, 0]
            tangent = bitangent = None
            if abs(determinant) >= 1e-12:
                e1, e2 = points[1] - points[0], points[2] - points[0]
                tangent = (e1 * delta[1, 1] - e2 * delta[0, 1]) / determinant
                bitangent = (e2 * delta[0, 0] - e1 * delta[1, 0]) / determinant
            triangle = []
            for index in face:
                if normals is not None and np.isfinite(normals[index]).all():
                    normal = tuple(map(float, normals[index]))
                    source_normal_corners += 1
                else:
                    normal = face_normal
                    fallback_normal_corners += 1
                point, texcoord = tuple(float(v) for v in positions[index]), tuple(float(v) for v in mapped_uv[index])
                source_joints, source_weights = owners[index]
                handedness = 0 if tangent is None else (-1 if np.dot(np.cross(normal, tangent), bitangent) < 0 else 1)
                key = point, normal, texcoord, mi, source_joints, source_weights, handedness
                if key not in lookup:
                    lookup[key] = len(vertices)
                    vertices.append({'position': point, 'normal': normal, 'uv': texcoord, 'source_material': mi,
                                     'source_joints': source_joints, 'source_weights': source_weights})
                triangle.append(lookup[key])
            triangles.append(tuple(triangle))
    if not triangles:
        raise MaterialError('source contains no nondegenerate triangles')
    return vertices, triangles, Image.fromarray(atlas), report | {
        'source_vertices': len(vertices), 'triangles': len(triangles), 'degenerate_triangles_skipped': skipped,
        'source_normal_corners': source_normal_corners, 'face_normal_fallback_corners': fallback_normal_corners,
        'uv_handedness_seams_preserved': True,
        'source_alpha_modes': sorted(alpha_modes), 'skin': 'source pose and influences retained; target weights not retargeted',
        'native_materials_bound': False, 'live_verified': False}
