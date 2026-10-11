"""Bake native DOA2 SUP seam geometry for an observed joint pose.

The owned SH4 consumer at 0x8c0e6ea4 builds a 16-sample curved seam transform.
The SUP contains original-model-relative inline vertex offsets, local positions
and normals, and aliases. This baker changes a copied CHR's seam vertices only.
It reproduces native neutral geometry; a two-joint GLTF weight approximation
does not claim to reproduce the game's curved deformation at arbitrary poses.
"""
from __future__ import annotations

import hashlib
import struct

import numpy as np

from . import doa2_morphs as M
try:
    from gbox import doa2_geometry as G
except ImportError:
    import doa2_geometry as G

EXECUTABLE_SHA256 = '27a014aeda35983df749f7d575bbddbea3f1ffd1f7776194ef503108c20c97e1'
COEFFICIENT_ADDRESS = 0x8c1dbe68


def native_coefficients(executable: bytes) -> np.ndarray:
    if hashlib.sha256(executable).hexdigest() != EXECUTABLE_SHA256:
        raise ValueError('SUP coefficient address belongs to a different executable')
    offset = COEFFICIENT_ADDRESS - 0x8c010000
    result = np.array(struct.unpack_from('<48f', executable, offset)).reshape(16, 3)
    if not np.allclose(result.sum(axis=1), 1) or not np.allclose(result[:, 1] + .5 * result[:, 2], np.arange(16) / 16):
        raise ValueError('native SUP curve coefficients failed their parameter invariants')
    return result


def decode_sup(data: bytes) -> list[dict]:
    seams = M.inspect_sup(data)['seams']
    output = []
    for seam in seams:
        pointer, end = seam['data_offset'], seam['offset'] + seam['bytes']
        raw = np.array(struct.unpack_from('<30f', data, pointer))
        if not np.isfinite(raw).all():
            raise ValueError('SUP contains non-finite seam controls')
        groups, cursor = [], pointer + 120
        while True:
            if cursor + 4 > end:
                raise ValueError('SUP seam lacks its directory terminator')
            sample = struct.unpack_from('<I', data, cursor)[0]
            cursor += 4
            if sample == 0:
                break
            if sample > 16 or not groups and sample != 16 or groups and sample == 16:
                raise ValueError('SUP expects initial direct-B group16 followed by curve groups1..15')
            vertices = []
            while True:
                if cursor + 4 > end:
                    raise ValueError('SUP vertex group lacks its terminator')
                target = struct.unpack_from('<I', data, cursor)[0]
                cursor += 4
                if target == 0:
                    break
                if target & ~1 & 3:
                    raise ValueError('SUP vertex target is not four-byte aligned')
                if target & 1:
                    if not vertices:
                        raise ValueError('SUP alias has no preceding unique vertex in its sample group')
                    item = {'offset': target - 1, 'alias': True}
                else:
                    if cursor + 24 > end:
                        raise ValueError('SUP vertex payload exceeds its seam allocation')
                    payload = np.array(struct.unpack_from('<6f', data, cursor))
                    cursor += 24
                    if not np.isfinite(payload).all():
                        raise ValueError('SUP vertex payload contains non-finite values')
                    item = {'offset': target, 'alias': False,
                            'position': payload[:3], 'normal': payload[3:]}
                vertices.append(item)
            groups.append({'sample': sample, 'vertices': vertices})
        if cursor != end:
            raise ValueError('SUP seam has unexplained trailing bytes')
        output.append({**seam, 'axis_pairs': raw[:18].reshape(3, 2, 3),
                       'controls': raw[18:].reshape(4, 3), 'groups': groups})
    return output


def _normal(vector):
    length = np.linalg.norm(vector)
    if not np.isfinite(length) or length < 1e-9:
        raise ValueError('SUP pose creates a singular seam axis')
    return vector / length


def curve_matrix(seam: dict, relative: np.ndarray, sample: int, coefficients: np.ndarray) -> np.ndarray:
    """Return the native group transform from seam space into bone-A space."""
    if sample == 16:
        return relative.copy()
    if not 1 <= sample <= 15:
        raise ValueError('SUP curve sample must be1..15 or direct-B16')
    if np.asarray(relative).shape != (4, 4) or np.asarray(coefficients).shape != (16, 3):
        raise ValueError('SUP transform/coefficient shape is invalid')
    a_columns = seam['axis_pairs'][:, 0].T
    b_columns = relative[:3, :3] @ seam['axis_pairs'][:, 1].T
    middle_columns = np.column_stack([_normal(a_columns[:, k] + b_columns[:, k]) for k in range(3)])
    ca, cb, cm = coefficients[sample]
    axes = ca * a_columns + cb * b_columns + cm * middle_columns
    # Native Gram-Schmidt order from 0x8c0e7094..0x8c0e717e: Z, Y, X.
    z = _normal(axes[:, 2])
    y = _normal(axes[:, 1] - np.dot(axes[:, 1], z) * z)
    x = axes[:, 0] - np.dot(axes[:, 0], z) * z
    x = _normal(x - np.dot(x, y) * y)
    controls = seam['controls']
    a_position = controls[0]
    b_position = relative[:3, :3] @ controls[1] + relative[:3, 3]
    middle_position = .5 * (relative[:3, :3] @ controls[2] + relative[:3, 3] + controls[3])
    result = np.eye(4)
    result[:3, :3] = np.column_stack((x, y, z))
    result[:3, 3] = ca * a_position + cb * b_position + cm * middle_position
    return result


def bake_chr(chr_data: bytes, sup_data: bytes, world: np.ndarray, coefficients: np.ndarray,
             *, emulate_marker: bool = True) -> dict:
    """Return copied CHR with native seam positions/normals and export evidence."""
    world = np.asarray(world, dtype=float)
    if world.ndim != 3 or world.shape[1:] != (4, 4) or not np.isfinite(world).all():
        raise ValueError('SUP pose needs finite affine joint matrices')
    if not np.allclose(world[:, 3], [0, 0, 0, 1]) or np.any(np.abs(np.linalg.det(world[:, :3, :3])) < 1e-9):
        raise ValueError('SUP pose matrices must be invertible and affine')
    coefficients = np.asarray(coefficients, dtype=float)
    if coefficients.shape != (16, 3) or not np.isfinite(coefficients).all():
        raise ValueError('SUP coefficients need16 finite float3 values')
    archive, seams, result = G.decode_chr(chr_data), decode_sup(sup_data), bytearray(chr_data)
    writes, models, reports = {}, {}, []
    for seam in seams:
        model_id, a, b = seam['model_id'], seam['bone_a'], seam['bone_b']
        if max(a, b) >= len(world) or model_id >= len(archive['models']):
            raise ValueError('SUP seam references an absent joint or model')
        model = archive['models'][model_id]
        inline = {r['offset'] for mesh in model['meshes'] for r in mesh['records'] if not r['reference']}
        relative = np.linalg.inv(world[a]) @ world[b]
        models[model_id] = {'bone_a': a, 'bone_b': b, 'world': world[a].tolist()}
        count = aliases = 0
        for group in seam['groups']:
            matrix, last = curve_matrix(seam, relative, group['sample'], coefficients), None
            for vertex in group['vertices']:
                offset = model['offset'] + vertex['offset']
                if offset not in inline or offset + 24 > model['end_offset']:
                    raise ValueError('SUP write does not reference a complete inline CHR vertex')
                if vertex['alias']:
                    payload = last
                    aliases += 1
                else:
                    p = matrix[:3, :3] @ vertex['position'] + matrix[:3, 3]
                    n = matrix[:3, :3] @ vertex['normal']
                    payload = struct.pack('<6f', *p, *n)
                    if emulate_marker:
                        first = struct.unpack_from('<I', payload)[0] | 1
                        payload = struct.pack('<I', first) + payload[4:]
                    last = payload
                result[offset:offset + 24] = payload
                parameter = group['sample'] / 16
                writes[offset] = {'model_id': model_id, 'bone_a': a, 'bone_b': b,
                                  'sample': group['sample'], 'joints': [a, b],
                                  'weights': [1 - parameter, parameter], 'alias': vertex['alias']}
                count += 1
        reports.append({'model_id': model_id, 'bone_a': a, 'bone_b': b,
                        'written_vertices': count, 'aliases': aliases,
                        'curve_samples': [g['sample'] for g in seam['groups']]})
    return {'chr_data': bytes(result), 'seam_models': models, 'vertex_influences': writes,
            'report': {'seams': reports, 'written_vertices': len(writes),
                       'source_chr_sha256': hashlib.sha256(chr_data).hexdigest(),
                       'baked_chr_sha256': hashlib.sha256(result).hexdigest(),
                       'byte_count': len(result), 'emulate_processed_marker': emulate_marker,
                       'native_deformation': 'SUP curve transforms reproduced for the supplied pose',
                       'export_weights': 'two-joint sample/16 approximation; arbitrary-pose GLTF skin is not the native curved seam solver'}}


def assemble_core(chr_data: bytes, sup_data: bytes, bin_data: bytes, world: np.ndarray,
                  primary_models: dict[int, int], coefficients: np.ndarray) -> dict:
    """Assemble verified primary parts and baked native seams as donor meshes.

    ``primary_models`` maps model ID to its native joint ID. This intentionally
    does not attach cloth, eyes or wing parts through guessed joints.
    Every mesh uses original triangles, UVs and decoded native textures.
    """
    try:
        from gbox import doa2_textures as T
    except ImportError:
        import doa2_textures as T
    world = np.asarray(world, dtype=float)
    baked = bake_chr(chr_data, sup_data, world, coefficients)
    archive = G.decode_chr(baked['chr_data'])
    texture_directory = T.descriptors(chr_data, bin_data)
    decoded_textures = {}
    mapping = {int(model): int(joint) for model, joint in primary_models.items()}
    if not mapping or any(not 0 <= model < len(archive['models']) or not 0 <= joint < len(world)
                          for model, joint in mapping.items()):
        raise ValueError('core assembly requires verified native model/joint bindings')
    for model, seam in baked['seam_models'].items():
        if model in mapping and mapping[model] != seam['bone_a']:
            raise ValueError('native primary and SUP model bindings conflict')
        mapping[model] = seam['bone_a']
    primitives = []
    for model_id, joint in sorted(mapping.items()):
        matrix = world[joint]
        normal_matrix = np.linalg.inv(matrix[:3, :3]).T
        for mesh_index, mesh in enumerate(archive['models'][model_id]['meshes']):
            attributes = np.array(mesh['vertices'])
            if not len(attributes):
                continue
            count = len(attributes)
            positions = attributes[:, :3] @ matrix[:3, :3].T + matrix[:3, 3]
            normals = attributes[:, 3:6] @ normal_matrix.T
            normals /= np.maximum(np.linalg.norm(normals, axis=1, keepdims=True), 1e-12)
            joints = np.zeros((count, 4), np.uint16);joints[:, 0] = joint
            weights = np.zeros((count, 4), np.float32);weights[:, 0] = 1
            for record in mesh['records']:
                if record['reference']:
                    continue
                influence = baked['vertex_influences'].get(record['offset'])
                if influence:
                    joints[record['vertex'], :2] = influence['joints']
                    weights[record['vertex'], :2] = influence['weights']
            mode2 = struct.unpack_from('<I',mesh['header'],8)[0]
            wrap=tuple(33071 if mode2&(1<<clamp) else 33648 if mode2&(1<<mirror) else 10497
                       for clamp,mirror in ((16,18),(15,17)))
            slot = mesh['texture_id']
            tex = None
            if slot >= 0:
                if slot >= len(texture_directory):
                    raise ValueError('core material references a missing native texture')
                if slot not in decoded_textures:
                    decoded_textures[slot] = np.asarray(T.decode(texture_directory[slot], bin_data), dtype=np.uint8)
                tex = decoded_textures[slot]
            color = struct.unpack_from('<4f', mesh['header'], 44)
            rgba = tuple(int(round(max(0, min(1, value))*255)) for value in (*color[1:], color[0]))
            # Keep actual native UV values, including their repeat-domain signs.
            uv = attributes[:, 6:8].copy()
            primitives.append({'name': f'native_model{model_id}_mesh{mesh_index}',
                               'native_model': model_id, 'native_texture': slot,
                               'pos': positions, 'nrm': normals, 'uv': uv,
                               'tris': np.array(mesh['triangles'],dtype=np.int32),
                               'J': joints, 'W': weights, 'owner': joints[np.arange(count),weights.argmax(axis=1)],
                               'tex': tex, 'color': rgba, 'prop': False, 'wrap':wrap})
    return {'prims': primitives, 'baked_chr': baked['chr_data'],
            'report': {**baked['report'], 'assembled_models': sorted(mapping),
                       'primary_models': sorted(map(int,primary_models)),
                       'triangles': sum(len(p['tris']) for p in primitives),
                       'vertices': sum(len(p['pos']) for p in primitives),
                       'textures': len(decoded_textures),
                       'omitted_components': 'ACS cloth and repeated hair/prop attachments require their native controllers; eyes/wings are supplied through verified component mappings'}}


def write_core(path, assembled, profile, name):
    """Write the recovered neutral body with full joint matrices/inverse binds."""
    import base64
    import json
    from .melee_models import write_gltf
    world = np.asarray(profile['world'], float)
    joint_count = len(world)
    parents = profile['parent']
    role_names = {joint: role for role, joint in profile['roles'].items()}
    names = [role_names.get(j, f'attachment{j}') for j in range(joint_count)]
    joints = [{'parent': parents[j], 'world': world[j]} for j in range(joint_count)]
    write_gltf(path, joints, assembled['prims'], 1, name, names, assembled['report'])
    gl = json.loads(path.read_text(encoding='utf-8'))
    for j, node in enumerate(gl['nodes'][:joint_count]):
        local = np.linalg.inv(world[parents[j]]) @ world[j] if parents[j] >= 0 else world[j]
        node.pop('translation', None)
        node['matrix'] = local.T.reshape(-1).tolist()
    accessor = gl['accessors'][gl['skins'][0]['inverseBindMatrices']]
    view = gl['bufferViews'][accessor['bufferView']]
    offset = view.get('byteOffset',0) + accessor.get('byteOffset',0)
    blob = bytearray(base64.b64decode(gl['buffers'][0]['uri'].split(',',1)[1]))
    inverse = np.asarray([np.linalg.inv(w).T.reshape(16) for w in world], np.float32)
    blob[offset:offset + inverse.nbytes] = inverse.tobytes()
    gl['buffers'][0]['uri'] = 'data:application/octet-stream;base64,' + base64.b64encode(blob).decode()
    for material, primitive in zip(gl['materials'], assembled['prims']):
        color_map = material.get('pbrMetallicRoughness',{}).get('baseColorTexture')
        if color_map:
            previous = gl['textures'][color_map['index']]
            wrap = primitive.get('wrap',(10497,10497))
            settings = {'magFilter':9729,'minFilter':9729,'wrapS':wrap[0],'wrapT':wrap[1]}
            gl['samplers'].append(settings)
            gl['textures'].append({**previous,'sampler':len(gl['samplers'])-1})
            color_map['index']=len(gl['textures'])-1
        texture = primitive['tex']
        if texture is not None and np.any((texture[...,3] != 0) & (texture[...,3] != 255)):
            material['alphaMode'] = 'BLEND'
    path.write_text(json.dumps(gl), encoding='utf-8')
    return path
