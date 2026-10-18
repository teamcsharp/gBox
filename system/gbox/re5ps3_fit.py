"""Experimental, exact-source Sonic/Peach body fitting for two RE5 PS3 packs.

This writes new ARC copies for offline inspection. It does not install assets,
launch a game, replace the full cast, or establish native motion/culling safety.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import struct
import tempfile

import numpy as np
from PIL import Image

from . import attachments, doa2_weighted_retarget as R
from .re5ps3_arc import Arc, sha, MAX_ARCHIVE
from .re5ps3_collection import CHRIS, SHEVA, FILES
from .re5ps3_models import Model, Texture, finite
from .re5ps3_roles import role_evidence
from .re5ps3_topology import replace_body
from .re5ps3_write import replace_texture, _publish_archive, MAX_GLB

FIT_VERSION = 1
# Selected reproducibly from the owned library for order2396. These exact GLBs
# were checked with independent weighted Blender controls, not name inference.
DONORS = {
    CHRIS: {
        'slug': 'sa2_super_sonic', 'label': 'Sonic (blue library texture; not super-yellow)',
        'sha256': 'a2fe5100cb09202f7f470fa0abcbb0ba4f47d8f9c4b211db3cb2a20ff8a62246',
        'source_game_id': 'd95ed7ed1e40552a', 'source_platform': 'dreamcast',
        'source_files': ['SONIC2/SSONICMDL.PRS', 'SONIC2/SSONICTEX.PRS'],
        'model_member': r'pawn\pl\pl00\model\pl0000', 'source_triangles': 1369,
        'roles': dict(hip='node002', chest='node033', head='node044',
                      l_upper='node037', l_fore='node038', l_hand='node039',
                      r_upper='node056', r_fore='node057', r_hand='node058',
                      l_thigh='node017', l_shin='node019', l_foot='node023',
                      r_thigh='node007', r_shin='node009', r_foot='node013'),
        'unweighted_roles': [],
    },
    SHEVA: {
        'slug': 'sm64ds_peach', 'label': 'Princess Peach (Super Mario 64 DS)',
        'sha256': '2437b114788a6a75de1ab1995a2d484eeade85b7d1b97f79dd38b692b3f78d73',
        'source_game_id': '917483267d246594', 'source_platform': 'nds',
        'source_files': ['data/enemy/peach/peach_high.bmd'],
        'model_member': r'pawn\pl\pl01\model\pl0100', 'source_triangles': 798,
        'roles': dict(hip='skl_root', chest='spin', head='face_1',
                      l_upper='arm_l1', l_fore='arm_l2', l_hand='wrist_l1',
                      r_upper='arm_r1', r_fore='arm_r2', r_hand='wrist_r1',
                      l_thigh='leg_l1', l_shin='leg_l2', l_foot='ankle_l1',
                      r_thigh='leg_r1', r_shin='leg_r2', r_foot='ankle_r1'),
        # No rendered leg geometry moves under these controls. They are retained
        # as source identities, not presented as visually proven anatomy.
        'unweighted_roles': ['l_thigh', 'l_shin', 'l_foot', 'r_thigh', 'r_shin', 'r_foot'],
    },
}


def _descendants(parents, joint):
    result = {joint}
    for _ in parents:
        result.update(i for i, p in enumerate(parents) if p in result)
    return result


def _bounds(points):
    return {'min': points.min(0).tolist(), 'max': points.max(0).tolist()}


def _verify_influences(rig, fitted, roles):
    """Independently sum every source weight by its nearest explicit role."""
    named = {joint: role for role, joint in rig['roles'].items()}
    mapped = []
    for joint in range(len(rig['parent'])):
        visited = set()
        while joint >= 0 and joint not in named:
            if joint in visited:
                raise ValueError('donor joint hierarchy contains a cycle')
            visited.add(joint); joint = rig['parent'][joint]
        mapped.append(roles[named.get(joint, 'hip')])
    for original, converted in zip(rig['prims'], fitted, strict=True):
        if not np.array_equal(original['tris'], converted['tris']):
            raise ValueError('fit changed source triangle winding or topology')
        expected = np.zeros((len(original['pos']), max(roles.values()) + 1))
        actual = np.zeros_like(expected)
        for row, (joints, weights) in enumerate(zip(original['J'], original['W'])):
            for joint, weight in zip(joints, weights):
                expected[row, mapped[int(joint)]] += weight
        for row, (joints, weights) in enumerate(zip(converted['J'], converted['W'])):
            for joint, weight in zip(joints, weights):
                if weight:
                    actual[row, int(joint)] += weight
        if not np.allclose(actual, expected, atol=1e-12, rtol=0):
            raise ValueError('fit dropped or reassigned a mapped source influence')
    return mapped


def fit_primitives(model, rig):
    """Fit the verified target, retaining source weights and explicit body roles."""
    evidence = role_evidence(model)
    if evidence is None:
        raise ValueError('fitting requires an exact original native body role map')
    roles = evidence['native_joint_ids']
    meshes = [m for m in model.meshes if m['visible'] and m['lod'] & 1]
    positions = np.concatenate([m['positions'] for m in meshes])
    head = _descendants(model.parents, roles['head'])
    head_points = np.concatenate([m['positions'][(m['weights'] * np.isin(m['joints'], list(head))).sum(1) > .5]
                                  for m in meshes])
    target = {'T': model.world[:, :3, 3], 'parent': [-1 if p == 255 else p for p in model.parents],
              'joints': len(model.parents), 'ground': float(positions[:, 1].min()),
              'head_h': float(np.ptp(head_points[:, 1])), 'fit_height': float(np.ptp(positions[:, 1])), 'jmap': roles}
    if any(p.get('prop') for p in rig['prims']):
        raise ValueError('this exact body fitter does not support attachment reassignment')
    prims, report = R.retarget(rig, target, {'head': 1.}, jmap=roles)
    if not np.array_equal(report['facing'], np.eye(3)) or report['normals_flipped']:
        raise ValueError('verified donor orientation changed')
    source_to_native = _verify_influences(rig, prims, roles)
    s = report['scale']
    if not np.isfinite(s) or s <= 0:
        raise ValueError('fit scale must be finite and positive')

    # Keep the donor's head proportions, anchoring its actual head joint rather
    # than the lowest head vertex. The result may exceed original model height.
    source_head = _descendants(rig['parent'], rig['roles']['head'])
    head_points = np.concatenate([p['pos'][np.isin(p['owner'], list(source_head))] for p in rig['prims']])
    pivot = rig['joints'][rig['roles']['head']]
    head_base = pivot.copy(); head_base[1] = head_points[:, 1].min()
    delta = head_base - rig['joints'][rig['roles']['hip']]
    torso_base = target['T'][roles['hip']] + [delta[0] * s * report['shoulder_widen'],
                    delta[1] * s * (report['torso_up'] if delta[1] > 0 else report['torso_down']), delta[2] * s]
    old_pivot = torso_base + (pivot - head_base) * s * report['head_scale']
    anchor_delta = target['T'][roles['head']] - old_pivot
    for p in prims:
        mass = (p['W'] * (p['J'] == roles['head'])).sum(1)
        p['pos'] += mass[:, None] * anchor_delta
    report['head_anchor_translation_cm'] = anchor_delta.tolist()
    report['head_policy'] = 'retain donor proportions and anchor to native head; original height is not a cap'

    # These donors have rigid boot geometry, or no visible foot geometry. A
    # blended foot requires a separate proven correction; fail rather than
    # assigning it to the strongest joint. Preserve donor up/front at the ankle.
    feet = {}; separation = abs(target['T'][roles['l_foot'], 0] - target['T'][roles['r_foot'], 0])
    if not np.isfinite(separation) or separation <= 0:
        raise ValueError('native ankle separation is not positive')
    for side in ('l', 'r'):
        joint = roles[side + '_foot']; anchor = target['T'][joint]
        pivot = rig['joints'][rig['roles'][side + '_foot']]
        masks = [(p['W'] * (p['J'] == joint)).sum(1) for p in prims]
        if any(np.any((mass > 1e-8) & (np.abs(mass - 1) > 1e-8)) for mass in masks):
            raise ValueError('blended foot frame correction is not verified')
        points = np.concatenate([p['pos'][mass > .5] for p, mass in zip(rig['prims'], masks)])
        if not len(points):
            feet[side] = {'visible_vertices': 0, 'anatomical_motion_verified': False}
            continue
        extent = float(np.max(np.abs(points[:, 0] - pivot[0]))) * s
        below = max(0., float(pivot[1] - points[:, 1].min())) * s
        scale_x = min(1., .45 * separation / max(extent, 1e-9))
        scale_y = min(1., (anchor[1] - target['ground']) / max(below, 1e-9))
        axis_scale = np.array([scale_x, scale_y, 1.]) * s
        if not np.isfinite(axis_scale).all() or np.any(axis_scale <= 0):
            raise ValueError('foot scale must be finite and positive')
        written = []
        for original, p, mass in zip(rig['prims'], prims, masks):
            selected = mass > .5
            p['pos'][selected] = anchor + (original['pos'][selected] - pivot) * axis_scale
            normal = original['nrm'][selected] / axis_scale
            if len(normal):
                p['nrm'][selected] = normal / np.linalg.norm(normal, axis=1)[:, None]
                written.append(p['pos'][selected])
        points = np.concatenate(written)
        feet[side] = {'visible_vertices': len(points), 'axis_scale': axis_scale.tolist(),
                      'bounds_cm': _bounds(points), 'frame': 'donor up/front around native ankle'}
    if all(feet[s]['visible_vertices'] for s in ('l', 'r')):
        left, right = sorted(feet.values(), key=lambda f: f['bounds_cm']['min'][0])
        gap = right['bounds_cm']['min'][0] - left['bounds_cm']['max'][0]
        if gap < .099 * separation:
            raise ValueError('fitted foot bounds overlap or lose their required gap')
        report['foot_gap_cm'] = gap
    else:
        report['foot_gap_cm'] = None
    fitted_points = np.concatenate([p['pos'] for p in prims])
    for p in prims:
        finite(p['pos'], 'fitted positions'); finite(p['nrm'], 'fitted normals')
    ground_error = float(fitted_points[:, 1].min() - target['ground'])
    if abs(ground_error) > .01:
        raise ValueError('fitted ground differs by more than .01 native centimetres')
    report.update(foot_fits=feet, source_joint_to_native=source_to_native,
                  source_weights_preserved_before_native_quantization=True,
                  original_bounds_cm=_bounds(positions), fitted_bounds_cm=_bounds(fitted_points),
                  ground_error_cm=ground_error, gameplay_verified=False)
    json.dumps(report, allow_nan=False)
    return prims, report


def atlas_geometry(prims, size):
    """Bake bounded donor wrap modes; retain triangles and explicit back faces."""
    if type(size) is not int or not 32 <= size <= 4096 or not 1 <= len(prims) <= 256:
        raise ValueError('atlas size or primitive count outside bounds')
    expanded_vertices = sum(3 * len(p['tris']) * (2 if p['double_sided'] else 1) for p in prims)
    if not 3 <= expanded_vertices <= 65534:
        raise ValueError('expanded donor exceeds native body vertex budget')
    cols = int(np.ceil(np.sqrt(len(prims)))); cell = size // cols; pad = 2; inside = cell - 2 * pad
    if inside < 2:
        raise ValueError('native texture too small for this donor atlas')
    canvas = np.zeros((size, size, 4), np.uint8)
    columns = {k: [] for k in ('positions', 'normals', 'uv', 'joints', 'weights')}; counts = []
    for index, p in enumerate(prims):
        uv = np.asarray(p['uv']); finite(uv, 'donor UV')
        lo = np.floor(uv.min(0)); hi = np.maximum(np.ceil(uv.max(0)), lo + 1)
        if np.max(hi - lo) > 8 or np.max(np.abs(uv)) > 100:
            raise ValueError('donor UV tiling exceeds bounded atlas support')
        tex = np.asarray(p['tex']) if p['tex'] is not None else np.full((1, 1, 4), 255, np.uint8)
        if tex.ndim != 3 or tex.shape[2] not in (3, 4):
            raise ValueError('donor image must be RGB or RGBA')
        if tex.shape[2] == 3:
            tex = np.concatenate((tex, np.full(tex.shape[:2] + (1,), 255, np.uint8)), axis=2)
        coords = []
        for axis, wrap in enumerate(p['wrap']):
            value = lo[axis] + (np.arange(inside) + .5) / inside * (hi[axis] - lo[axis])
            if wrap == 10497: value = value % 1
            elif wrap == 33648: value = 1 - np.abs(value % 2 - 1)
            elif wrap == 33071: value = np.clip(value, 0, 1)
            else: raise ValueError('unsupported donor texture wrap')
            coords.append(np.minimum((value * tex.shape[1 - axis]).astype(int), tex.shape[1 - axis] - 1))
        tile = np.clip(tex[coords[1][:, None], coords[0][None, :]].astype(float) * np.asarray(p['color']) / 255, 0, 255).astype(np.uint8)
        tile = np.pad(tile, ((pad, pad), (pad, pad), (0, 0)), mode='edge')
        x, y = index % cols * cell, index // cols * cell
        canvas[y:y + cell, x:x + cell] = tile
        uv = np.column_stack(((x + pad + .5 + (uv[:, 0] - lo[0]) / (hi[0] - lo[0]) * (inside - 1)) / size,
                              (y + pad + .5 + (uv[:, 1] - lo[1]) / (hi[1] - lo[1]) * (inside - 1)) / size))
        faces = p['tris']; flat = faces.reshape(-1)
        arrays = {'positions': p['pos'][flat], 'normals': p['nrm'][flat], 'uv': uv[flat],
                  'joints': p['J'][flat], 'weights': p['W'][flat]}
        active = np.count_nonzero(arrays['weights'] > 0, axis=1)
        if np.any(active > 4):
            raise ValueError('donor exceeds native four-influence body layout')
        # _merge orders all nonzero weights first. Drop only zero columns.
        if np.any(arrays['weights'][:, 4:] != 0):
            raise ValueError('donor influences are not compacted')
        for key in ('joints', 'weights'):
            value = arrays[key][:, :4]
            arrays[key] = np.pad(value, ((0, 0), (0, 4 - value.shape[1])))
        for key, value in arrays.items(): columns[key].append(value)
        if p['double_sided']:
            for key, value in arrays.items():
                back = value.reshape(len(faces), 3, -1)[:, ::-1].reshape(value.shape)
                columns[key].append(-back if key == 'normals' else back)
        counts.append({'source': len(faces), 'back_faces_added': len(faces) if p['double_sided'] else 0})
    geometry = {k: np.concatenate(v) for k, v in columns.items()}
    geometry['triangles'] = np.arange(len(geometry['positions'])).reshape(-1, 3)
    if len(geometry['positions']) > 65534:
        raise ValueError('expanded donor exceeds native body vertex budget')
    return geometry, Image.fromarray(canvas), counts


def build_fitted_archive(source, donor_bytes, *, expected_sha256):
    """Validate and construct in memory from exact original ARC/donor snapshots."""
    if len(source) > MAX_ARCHIVE or sha(source) != expected_sha256:
        raise ValueError('ARC source hash or size differs from request')
    key = next((key for key in DONORS if FILES[key][1] == expected_sha256), None)
    if key is None:
        raise ValueError('fitting only supports exact original Chris/Sheva normal packs')
    donor = DONORS[key]
    if len(donor_bytes) > MAX_GLB or sha(donor_bytes) != donor['sha256']:
        raise ValueError('donor GLB hash differs from verified fitting source')
    original = Arc(source)
    model_entry = next(e for e in original.entries if e.name == donor['model_member'] and original.read(e)[:4] == b'\0DOM')
    model_data = original.read(model_entry); model = Model(model_data)
    # The loader sees only the immutable exact-hash snapshot. Embedded resources
    # belong to these verified GLBs; no arbitrary external donor is accepted.
    with tempfile.TemporaryDirectory(prefix='gbox-re5-fit-') as temporary, attachments.paused():
        path = Path(temporary) / 'donor.glb'; path.write_bytes(donor_bytes)
        rig = R.load_rig(path, donor['roles'])
        if sum(len(p['tris']) for p in rig['prims']) != donor['source_triangles']:
            raise ValueError('donor triangle count differs from verified source')
        prims, fit = fit_primitives(model, rig)
    at = struct.unpack_from('>I', model_data, 56)[0]
    candidates = [m for m in model.meshes if m['visible'] and m['lod'] & 1 and m['group'] == 0
                  and model.materials[m['material']]['vertex_type'] == 0
                  and model.materials[m['material']]['texture'] >= 0 and model_data[at + m['index'] * 52 + 9] == 0]
    template = max(candidates, key=lambda m: len(m['positions']))
    texture_name = model.texture_names[model.materials[template['material']]['texture']]
    texture_entry = next(e for e in original.entries if e.name == texture_name and original.read(e)[:4] == b'\0XET')
    texture_data = original.read(texture_entry); texture = Texture(texture_data)
    if texture.width != texture.height:
        raise ValueError('verified atlas target must be square')
    geometry, atlas, counts = atlas_geometry(prims, texture.width)
    replaced, native = replace_body(model_data, geometry, template_mesh=template['index'], expected_sha256=sha(model_data))
    tex_bytes, tex_receipt = replace_texture(texture_data, atlas, expected_sha256=sha(texture_data))
    output = original.replace(model_entry.name, model_entry.type_hash, replaced, expected_sha256=sha(source))
    output = Arc(output).replace(texture_entry.name, texture_entry.type_hash, tex_bytes, expected_sha256=sha(output))
    checked = Arc(output)
    for entry in original.entries:
        expected = replaced if entry.key == model_entry.key else tex_bytes if entry.key == texture_entry.key else original.read(entry)
        if checked.read(checked.find(entry.name, entry.type_hash)) != expected:
            raise ValueError('archive resource readback differs')
    receipt = {'version': FIT_VERSION, 'target_member': key, 'source_arc_sha256': sha(source),
               'sha256': sha(output), 'donor': donor, 'fit': fit, 'native': native, 'texture': tex_receipt,
               'triangles': counts, 'all_archive_resources_verified': len(original.entries),
               'scope': 'experimental two-normal-model body fitting; offline readback only',
               'full_cast': False, 'gameplay_verified': False, 'camera_culling_motion_verified': False,
               'native_shader_normal_mask_textures_retained': True}
    json.dumps(receipt, allow_nan=False)
    return output, receipt


def _read_bounded(path, limit):
    with Path(path).open('rb') as stream:
        data = stream.read(limit + 1)
    if len(data) > limit:
        raise ValueError('input exceeds bounded fitting size')
    return data


def fit_archive(source, donor, output, *, expected_sha256):
    """Publish a new ARC exclusively, after all conversions and readback pass."""
    source, donor, output = Path(source), Path(donor), Path(output)
    if output.exists() or output.is_symlink():
        raise FileExistsError(output)
    data = _read_bounded(source, MAX_ARCHIVE); donor_bytes = _read_bounded(donor, MAX_GLB)
    written, receipt = build_fitted_archive(data, donor_bytes, expected_sha256=expected_sha256)
    if sha(_read_bounded(source, MAX_ARCHIVE)) != sha(data) or sha(_read_bounded(donor, MAX_GLB)) != sha(donor_bytes):
        raise ValueError('source changed while fitting; output not published')
    _publish_archive(written, output)
    return receipt


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('--donor-glb', type=Path, required=True)
    parser.add_argument('--expected-sha256', required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args(argv)
    result = fit_archive(args.source, args.donor_glb, args.out, expected_sha256=args.expected_sha256)
    print(json.dumps(result, indent=2, allow_nan=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
