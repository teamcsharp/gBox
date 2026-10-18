"""Experimental exact-source RE5 PS3 body topology encoder for offline fitting.

Replaces the complete normal-model draw list with one bounded four-weight mesh.
Skeleton matrices and animation IDs remain unchanged. Group/material behavior,
native motion, culling and gameplay acceptance are not established by readback.
"""
from __future__ import annotations

import struct
import numpy as np

from .re5ps3_arc import sha
from .re5ps3_models import Model, finite, MAX_MODEL
from .re5ps3_roles import role_evidence
from .re5ps3_write import _array


def _unit(values, label):
    finite(values, label)
    lengths = np.linalg.norm(values, axis=1)
    finite(lengths, label + ' lengths')
    if np.any(lengths <= 1e-12):
        raise ValueError(label + ' contains zero vectors')
    return values / lengths[:, None]


def _tangents(positions, normals, uv, faces):
    """UV derivative tangents with an orthogonal fallback for zero UV area."""
    result = np.zeros_like(positions)
    e1 = positions[faces[:, 1]] - positions[faces[:, 0]]
    e2 = positions[faces[:, 2]] - positions[faces[:, 0]]
    d1 = uv[faces[:, 1]] - uv[faces[:, 0]]
    d2 = uv[faces[:, 2]] - uv[faces[:, 0]]
    determinant = d1[:, 0] * d2[:, 1] - d1[:, 1] * d2[:, 0]
    selected = np.abs(determinant) > 1e-12
    tangent = np.zeros_like(e1)
    tangent[selected] = (e1[selected] * d2[selected, 1, None] - e2[selected] * d1[selected, 1, None]) / determinant[selected, None]
    for corner in range(3):
        np.add.at(result, faces[:, corner], tangent)
    result -= normals * (normals * result).sum(1)[:, None]
    zero = np.linalg.norm(result, axis=1) <= 1e-12
    axes = np.eye(3)[np.abs(normals[zero]).argmin(1)]
    result[zero] = np.cross(axes, normals[zero])
    return _unit(result, 'tangents')


def _envelope(bone, points, inverse, template):
    local = points @ inverse[:3, :3].T + inverse[:3, 3]
    finite(local, 'bone-space points')
    lo, hi = local.min(0) - .01, local.max(0) + .01
    center = (lo + hi) / 2
    radius = float(np.linalg.norm(local - center, axis=1).max()) + .02
    matrix = np.eye(4); matrix[:3, 3] = center
    values = np.concatenate((center, [radius], lo, [0], hi, [1], matrix.T.reshape(-1), (hi - lo) / 2, [.5]))
    with np.errstate(over='ignore', invalid='ignore'):
        converted = values.astype('>f4')
    finite(converted, 'native envelope float32')
    # The 12 opaque bytes after the bone ID are retained from that exact joint's
    # original envelope. They are not reinterpreted as floating-point geometry.
    return struct.pack('>I', bone) + template[4:16] + converted.tobytes()


def replace_body(data, geometry, *, template_mesh, expected_sha256):
    """Return new MOD bytes plus explicit offline-only receipt; no file writes.

    Geometry keys: positions/normals/uv/joints/weights/triangles. Positions are
    native centimetres. Up to four mapped influences are retained per vertex.
    """
    if sha(data) != expected_sha256:
        raise ValueError('MOD source hash differs from requested revision')
    model = Model(data)
    roles = role_evidence(model)
    if roles is None:
        raise ValueError('body topology encoder requires an exact verified original MOD')
    if type(template_mesh) is not int or not 0 <= template_mesh < len(model.meshes):
        raise ValueError('invalid native mesh template')
    if not isinstance(geometry, dict) or set(geometry) != {'positions', 'normals', 'uv', 'joints', 'weights', 'triangles'}:
        raise ValueError('expected exact bounded body geometry fields')
    positions = np.asarray(geometry['positions'])
    faces = np.asarray(geometry['triangles'])
    if positions.ndim != 2 or not 3 <= len(positions) <= 65534:
        raise ValueError('body vertex count outside supported u16 range')
    if faces.ndim != 2 or not 1 <= len(faces) <= 100000:
        raise ValueError('body triangle count outside supported range')
    n = len(positions)
    positions = _array(positions, (n, 3), 'positions')
    normals = _unit(_array(geometry['normals'], (n, 3), 'normals'), 'normals')
    uv = _array(geometry['uv'], (n, 2), 'UV')
    joints = _array(geometry['joints'], (n, 4), 'joints')
    weights = _array(geometry['weights'], (n, 4), 'weights')
    faces = _array(faces, (len(faces), 3), 'triangles')
    if np.any(faces != np.floor(faces)) or np.any(faces < 0) or np.any(faces >= n):
        raise ValueError('body triangle references an absent vertex')
    faces = faces.astype(np.int64)
    if len(np.unique(faces)) != n or np.any(np.diff(np.sort(faces, axis=1), axis=1) == 0):
        raise ValueError('body must reference every vertex and use distinct triangle indices')
    if np.any(joints != np.floor(joints)) or np.any(joints < 0) or np.any(joints >= len(model.parents)):
        raise ValueError('body joint references absent native bone')
    if np.any(weights < 0) or np.any(weights > 1) or not np.allclose(weights.sum(1), 1, atol=1e-6, rtol=0):
        raise ValueError('body weights must sum to one')
    allowed = set(roles['native_joint_ids'].values())
    if not set(joints[weights > 0].astype(int).tolist()) <= allowed:
        raise ValueError('body influences require verified native body anchors')
    h = list(struct.unpack_from('>4H15I', data, 4))
    nb, nm, ng, bones, groups, meshes, vertices = h[1], h[2], h[10], h[12], h[13], h[15], h[16]
    original_mesh = model.meshes[template_mesh]
    descriptor = bytearray(data[meshes + template_mesh * 52:meshes + (template_mesh + 1) * 52])
    material = model.materials[original_mesh['material']]
    if material['vertex_type'] != 0 or descriptor[9] or material['texture'] < 0:
        raise ValueError('body template requires four-weight textured vertex layout without secondary stream')
    old_start, old_offset = struct.unpack_from('>2I', descriptor, 16)
    template_vertex = data[vertices + old_offset + old_start * 32:vertices + old_offset + old_start * 32 + 32]
    palette_id = descriptor[46]
    palette = sorted(set(joints[weights > 0].astype(int).tolist()))
    quantized = np.floor(weights * 255).astype(np.uint16)
    remainder = weights * 255 - quantized
    for i in range(n):
        order = np.argsort(-remainder[i], kind='stable')
        quantized[i, order[:255 - int(quantized[i].sum())]] += 1
    used = sorted(set(joints[quantized > 0].astype(int).tolist()))
    lo, hi = positions.min(0) - .01, positions.max(0) + .01
    packed = np.rint((positions - lo) / (hi - lo) * 32767)
    finite(packed, 'native positions')
    if np.any(packed < 0) or np.any(packed > 32767):
        raise ValueError('body positions exceed chosen quantization bounds')
    vb = np.tile(np.frombuffer(template_vertex, dtype=np.uint8), (n, 1))
    vb[:, :6] = packed.astype('>i2').view(np.uint8).reshape(n, 6)
    for i in range(n):
        for c in range(4):
            vb[i, 8 + c] = palette.index(int(joints[i, c])) if quantized[i, c] else 0
    vb[:, 12:16] = quantized.astype(np.uint8)
    vb[:, 16:19] = np.rint((normals + 1) * 127.5).astype(np.uint8)
    vb[:, 20:23] = np.rint((_tangents(positions, normals, uv, faces) + 1) * 127.5).astype(np.uint8)
    with np.errstate(over='ignore', invalid='ignore'):
        uv16 = uv.astype('>f2')
    finite(uv16, 'native UV float16')
    vb[:, 24:28] = uv16.view(np.uint8).reshape(n, 4)
    vb[:, 28:32] = vb[:, 24:28]
    actual_positions = packed / 32767 * (hi - lo) + lo
    count_at = meshes + nm * 52
    count = struct.unpack_from('>I', data, count_at)[0]
    if count_at + 4 + count * 144 != vertices:
        raise ValueError('unsupported original envelope section layout')
    templates = {}
    for index in range(count):
        raw = data[count_at + 4 + index * 144:count_at + 4 + (index + 1) * 144]
        templates.setdefault(struct.unpack_from('>I', raw)[0], raw)
    new_envelope_joints = [j for j in used if j not in templates]
    envelopes = [_envelope(j, actual_positions[np.any((joints == j) & (quantized > 0), axis=1)],
                           model.inverse_bind[j], templates.get(j, bytes(144))) for j in used]
    out = bytearray(data)
    out += bytes((-len(out)) % 16)
    new_meshes = len(out)
    descriptor[4:6] = bytes((1, 255))
    descriptor[7] = int(np.count_nonzero(quantized, axis=1).max())
    struct.pack_into('>HH', descriptor, 12, n, n - 1)
    indices = np.column_stack((faces, np.full(len(faces), 65535))).astype('>u2')
    struct.pack_into('>6I', descriptor, 16, 0, 0, 0, 0, indices.size, 0)
    struct.pack_into('>H', descriptor, 42, 0)
    descriptor[47] = len(envelopes)
    out += descriptor + struct.pack('>I', len(envelopes)) + b''.join(envelopes)
    new_vertices = len(out); out += vb.tobytes(); new_indices = len(out); out += indices.tobytes()
    if len(out) > MAX_MODEL:
        raise ValueError('rebuilt MOD exceeds bounded size')
    h[2], h[4], h[5], h[7], h[8] = 1, n, indices.size + 1, vb.nbytes, 0
    h[15:19] = [new_meshes, new_vertices, new_indices, new_indices]
    struct.pack_into('>4H15I', out, 4, *h)
    center = (lo + hi) / 2; radius = float(np.linalg.norm(actual_positions - center, axis=1).max()) + .02
    for values, label in (([center, [radius]*3], 'body sphere'), ([lo, hi], 'body bounds')):
        with np.errstate(over='ignore', invalid='ignore'):
            converted = np.asarray(values, dtype='>f4')
        finite(converted, label)
    struct.pack_into('>4f', out, 80, *center, radius)
    struct.pack_into('>3f', out, 96, *lo); struct.pack_into('>3f', out, 112, *hi)
    for index in range(ng):
        struct.pack_into('>4f', out, groups + index * 32 + 16, *center, radius)
    palette_at = bones + nb * 152 + 256 + palette_id * 68
    struct.pack_into('>I', out, palette_at, len(palette))
    out[palette_at + 4:palette_at + 4 + len(palette)] = bytes(palette)
    output = bytes(out); checked = Model(output); mesh = checked.meshes[0]
    if not np.array_equal(mesh['triangles'], faces) or not np.array_equal(checked.local, model.local) or not np.array_equal(checked.inverse_bind, model.inverse_bind):
        raise ValueError('native topology or skeleton readback differs')
    if not np.allclose(mesh['positions'], positions, atol=float(np.max(hi-lo))/32767 + .0001, rtol=0):
        raise ValueError('native position readback exceeds quantization tolerance')
    if not np.array_equal(mesh['joints'][quantized > 0], joints[quantized > 0]):
        raise ValueError('native joint palette readback differs')
    if not np.allclose(mesh['weights'], quantized / 255, atol=1e-12, rtol=0):
        raise ValueError('native weight readback differs')
    # Validate the actual float32 bounds against positions decoded with the
    # written float32 model bounds. Finite input alone does not guarantee that
    # float32 rounding leaves a usable enclosure, especially at extreme scales.
    body_sphere = np.array(struct.unpack_from('>4f', output, 80))
    if np.any(np.linalg.norm(mesh['positions'] - body_sphere[:3], axis=1) > body_sphere[3]):
        raise ValueError('written body sphere does not enclose native readback')
    for joint, raw in zip(used, envelopes):
        selected = np.any((mesh['joints'] == joint) & (mesh['weights'] > 0), axis=1)
        points = mesh['positions'][selected] @ model.inverse_bind[joint, :3, :3].T + model.inverse_bind[joint, :3, 3]
        finite(points, 'written envelope points')
        sphere = np.array(struct.unpack_from('>4f', raw, 16))
        lower, upper = np.array(struct.unpack_from('>3f', raw, 32)), np.array(struct.unpack_from('>3f', raw, 48))
        center = np.array(struct.unpack_from('>3f', raw, 112))
        dimensions = np.array(struct.unpack_from('>3f', raw, 128))
        if (np.any(points < lower) or np.any(points > upper)
                or np.any(np.linalg.norm(points - sphere[:3], axis=1) > sphere[3])
                or np.any(np.abs(points - center) > dimensions)):
            raise ValueError('written bone bounds do not enclose native readback')
    return output, {'source_sha256':sha(data),'sha256':sha(output),'source_role_evidence':roles,
                    'template_mesh':template_mesh,'template_material':original_mesh['material'],
                    'diffuse_texture':model.texture_names[material['texture']], 'vertices':n,'triangles':len(faces),
                    'weighted_bones':used,'max_influences':int(descriptor[7]),'lod_mask':255,
                    'new_envelope_joints_with_zero_opaque_fields':new_envelope_joints,
                    'scope':'experimental complete normal-model draw-list replacement; offline readback only',
                    'native_materials_retained':True,'native_skeleton_matrices_unchanged':True,
                    'unknown_original_bytes_retained_in_orphaned_sections':True,
                    'group_visibility_motion_culling_verified':False,'gameplay_verified':False}
