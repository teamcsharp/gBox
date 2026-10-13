"""Private DOA influence-preserving loader and bind-shape adapter.

Fitting follows the existing sm64_swap body-role rules, but source skin weights
are retained and each vertex is fitted by the weighted role transforms. This
module does not reduce influences to the native SUP two-joint representation.
That distinct, measurable conversion belongs to the seam writer.
"""
from __future__ import annotations

from pathlib import Path
import re
import numpy as np
from gbox import sm64_swap as S
from gbox.re4gc_enemies import _role_of_joint


def _normal(v):
    return v / np.maximum(np.linalg.norm(v, axis=-1, keepdims=True), 1e-12)


class _LogicalVertices:
    """Use rounded lookup buckets without welding distinct fitted skin vertices."""
    def __init__(self):
        self.buckets = {}
        self.count = 0

    def add(self, key, position, joints, weights):
        influence = tuple(sorted((int(j), float(w)) for j, w in zip(joints, weights) if w > 0))
        candidates = self.buckets.setdefault(key, [])
        for logical_id, old_position, old_influence in candidates:
            if (len(influence) == len(old_influence)
                    and all(j == old_j and abs(w - old_w) <= 1e-12
                            for (j, w), (old_j, old_w) in zip(influence, old_influence))
                    and np.max(np.abs(position - old_position)) <= 1e-10):
                return logical_id
        logical_id = self.count
        self.count += 1
        candidates.append((logical_id, np.array(position, copy=True), influence))
        return logical_id


def _merge(joints, weights):
    joints, weights = np.asarray(joints, int), np.asarray(weights, float)
    if joints.shape != weights.shape or joints.ndim != 2 or not np.isfinite(weights).all() or np.any(weights < 0):
        raise ValueError('skin influences must be matching finite nonnegative arrays')
    total = weights.sum(axis=1)
    if np.any(total <= 1e-12):
        raise ValueError('skin vertex has no weighted joint')
    weights = weights / total[:, None]
    out_j, out_w = np.zeros_like(joints), np.zeros_like(weights)
    for vertex in range(len(joints)):
        combined = {}
        for joint, weight in zip(joints[vertex], weights[vertex]):
            if weight > 0:
                combined[int(joint)] = combined.get(int(joint), 0.) + float(weight)
        items = sorted(combined.items(), key=lambda item: (-item[1], item[0]))
        for column, (joint, weight) in enumerate(items):
            out_j[vertex, column], out_w[vertex, column] = joint, weight
    return out_j, out_w


def load_rig(path: Path, roles: dict, props=()):
    """Load all glTF JOINTS/WEIGHTS sets and evaluate their complete bind pose."""
    from gbox.re4gc_models import _gltf_load, _node_world
    gl, acc, image = _gltf_load(path)
    wn = _node_world(gl)
    skins = gl.get('skins') or []
    if not skins:
        raise ValueError('DOA donor requires a glTF skin')
    main = max(skins, key=lambda skin: len(skin['joints']))
    jn = main['joints']
    names = [gl['nodes'][node].get('name', f'node{node}') for node in jn]
    node_to_main = {node: index for index, node in enumerate(jn)}
    by_name = {name: index for index, name in reversed(list(enumerate(names)))}
    par_node = {child: index for index, node in enumerate(gl['nodes']) for child in node.get('children', [])}
    parents = []
    for node in jn:
        parent = par_node.get(node)
        while parent is not None and parent not in node_to_main:
            parent = par_node.get(parent)
        parents.append(node_to_main[parent] if parent is not None else -1)
    ri = {}
    for role in S.ORDER:
        index = by_name.get(roles.get(role))
        if index is not None and index not in ri.values():
            ri[role] = index
    if not {'hip', 'head'} <= ri.keys():
        raise ValueError('DOA donor needs identified hip and head joints')

    def to_main(node):
        while node is not None:
            if node in node_to_main:
                return node_to_main[node]
            index = by_name.get(gl['nodes'][node].get('name'))
            if index is not None:
                return index
            node = par_node.get(node)
        return ri['hip']

    props, cache, primitives = set(props or ()), {}, []
    for node_id, node in enumerate(gl['nodes']):
        if 'mesh' not in node:
            continue
        skin = skins[node['skin']] if 'skin' in node else None
        if skin is not None:
            ibm = (acc(skin['inverseBindMatrices']).reshape(-1, 4, 4).transpose(0, 2, 1)
                   if 'inverseBindMatrices' in skin else np.repeat(np.eye(4)[None], len(skin['joints']), axis=0))
            matrices = np.array([wn[joint] @ ibm[index] for index, joint in enumerate(skin['joints'])])
            loc = np.array([to_main(joint) for joint in skin['joints']])
        for primitive_id, primitive in enumerate(gl['meshes'][node['mesh']]['primitives']):
            if primitive.get('mode', 4) != 4:
                continue
            attributes = primitive['attributes']
            p = acc(attributes['POSITION']).astype(float)
            n = acc(attributes['NORMAL']).astype(float) if 'NORMAL' in attributes else np.tile([0., 1, 0], (len(p), 1))
            uv = acc(attributes['TEXCOORD_0']).astype(float) if 'TEXCOORD_0' in attributes else np.zeros((len(p), 2))
            sets = sorted(int(key.split('_')[1]) for key in attributes if key.startswith('JOINTS_'))
            if skin is not None and sets:
                if sets != list(range(len(sets))) or any(f'WEIGHTS_{key}' not in attributes for key in sets):
                    raise ValueError('donor skin influence sets are incomplete')
                raw_j = np.concatenate([acc(attributes[f'JOINTS_{key}']).astype(int) for key in sets], axis=1)
                raw_w = np.concatenate([acc(attributes[f'WEIGHTS_{key}']).astype(float) for key in sets], axis=1)
                if raw_j.shape[0] != len(p) or np.any(raw_j < 0) or np.any(raw_j >= len(loc)):
                    raise ValueError('donor influence references a missing skin joint')
                raw_j, raw_w = _merge(raw_j, raw_w)
                chosen = matrices[raw_j]
                blended = np.einsum('nwij,nw->nij', chosen, raw_w)
                if not np.isfinite(blended).all() or np.any(np.abs(np.linalg.det(blended[:, :3, :3])) < 1e-12):
                    raise ValueError('donor skin blend creates singular geometry')
                p = np.einsum('nij,nj->ni', blended[:, :3, :3], p) + blended[:, :3, 3]
                n = np.einsum('nij,nj->ni', np.linalg.inv(blended[:, :3, :3]).transpose(0, 2, 1), n)
                joints, weights = _merge(loc[raw_j], raw_w)
            else:
                p = p @ wn[node_id][:3, :3].T + wn[node_id][:3, 3]
                n = n @ np.linalg.inv(wn[node_id][:3, :3])
                joints, weights = np.zeros((len(p), 4), int), np.zeros((len(p), 4))
                joints[:, 0], weights[:, 0] = to_main(node_id), 1
            n = _normal(n)
            tris = acc(primitive['indices']).reshape(-1, 3).astype(int) if 'indices' in primitive else np.arange(len(p) // 3 * 3).reshape(-1, 3)
            texture, color, wrap = None, (255, 255, 255, 255), (10497, 10497)
            if (material_id := primitive.get('material')) is not None:
                material = gl['materials'][material_id].get('pbrMetallicRoughness', {})
                color = tuple(int(round(value * 255)) for value in material.get('baseColorFactor', [1, 1, 1, 1]))
                if (reference := material.get('baseColorTexture')) is not None:
                    texture_id = reference['index']
                    if texture_id not in cache:
                        cache[texture_id] = image(texture_id)
                    texture = cache[texture_id]
                    sampler_id = gl['textures'][texture_id].get('sampler')
                    settings = gl.get('samplers', [])[sampler_id] if sampler_id is not None else {}
                    wrap = (settings.get('wrapS', 10497), settings.get('wrapT', 10497))
            primitives.append({'pos': p, 'nrm': n, 'uv': uv, 'tris': tris, 'J': joints, 'W': weights,
                               'owner': joints[:, 0], 'tex': texture, 'color': color, 'wrap': wrap,
                               'prop': node.get('name') in props, 'source_mesh_node': node_id,
                               'source_primitive': primitive_id})
    if not primitives:
        raise ValueError('DOA donor has no triangle primitives')
    return {'joints': np.array([wn[node][:3, 3] for node in jn]), 'parent': parents,
            'roles': ri, 'prims': primitives, 'names': names, 'source': str(path),
            'influence_policy': 'all glTF influence sets preserved; no strongest-owner reduction'}


def retarget(rig: dict, target: dict, scale=None, jmap=None):
    """Fit bind geometry continuously and preserve each mapped native influence."""
    from gbox.retarget_profile import move_joints, profile_of
    rig, moved = move_joints(rig, profile_of(scale))      # the Retarget editor's joint moves: pivots + segments
    jmap = jmap or target['jmap']
    hip_joint, chest_joint = jmap['hip'], jmap.get('chest', jmap['hip'])
    basis = S.facing(rig)
    source, ri, destination = np.asarray(rig['joints']) @ basis.T, rig['roles'], target['T']
    # Roles absent on the 15-joint target resolve through actual source ancestry.
    mappable = {role: joint for role, joint in ri.items() if role in jmap}
    joint_role = np.array(_role_of_joint({'roles': mappable, 'parent': rig['parent']}))
    prims = [{**p, 'pos': p['pos'] @ basis.T, 'nrm': p['nrm'] @ basis.T,
              'role': joint_role[p['owner']]} for p in rig['prims']]
    all_p, all_role = np.concatenate([p['pos'] for p in prims]), np.concatenate([p['role'] for p in prims])
    props = np.concatenate([np.full(len(p['pos']), p.get('prop', False)) for p in prims])
    arms = np.isin(all_role, ['l_upper', 'l_fore', 'l_hand', 'r_upper', 'r_fore', 'r_hand']) | props
    body = all_p[~arms] if np.count_nonzero(~arms) > 10 else all_p
    ground = float(body[:, 1].min())
    hip = source[ri['hip']]
    head_p = all_p[(all_role == 'head') & ~props]
    head_y = source[ri['head'], 1]
    s = (destination[jmap['head'], 1] - target['ground']) / max(head_y - ground, 1e-9)
    if target.get('fit_height'):
        s = target['fit_height'] / max(float(all_p[~props, 1].max()) - ground, 1e-9)
    upper = float(np.clip((destination[jmap['head'], 1] - destination[hip_joint, 1]) / max(head_y - hip[1], 1e-9), .6 * s, 1.8 * s))
    lower = float(np.clip((destination[hip_joint, 1] - target['ground']) / max(hip[1] - ground, 1e-9), .6 * s, 1.8 * s))
    widen = 1.
    if 'l_upper' in ri and 'r_upper' in ri:
        half_s = abs(source[ri['l_upper'], 0] - source[ri['r_upper'], 0]) / 2 * s
        half_t = abs(destination[jmap['l_upper'], 0] - destination[jmap['r_upper'], 0]) / 2
        widen = float(np.clip(half_t / max(half_s, 1e-9), 1., 1.5))

    def torso(p):
        delta = np.atleast_2d(p) - hip
        return destination[hip_joint] + np.stack([delta[:, 0] * s * widen,
                 np.where(delta[:, 1] > 0, delta[:, 1] * upper, delta[:, 1] * lower), delta[:, 2] * s], axis=1)

    rules, stretch, head_scale = {}, {}, 1.
    if len(head_p):
        base = np.array([source[ri['head'], 0], head_p[:, 1].min(), source[ri['head'], 2]])
        head_scale = float(np.clip(target['head_h'] / max(np.ptp(head_p[:, 1]) * s, 1e-9), 1., 1.5)) * float((scale or {}).get('head', 1.))
        rules['head'] = (np.eye(3) * s * head_scale, base, torso(base)[0], jmap['head'])

    for a, b, c in S.LIMBS:
        rotation = None
        for segment, (role, following, next2) in enumerate(((a, b, c), (b, c, None))):
            if role not in ri or role not in jmap or following not in jmap:
                continue
            start = torso(source[ri[role]])[0] if segment == 0 else destination[jmap[role]]
            if following in ri:
                end_source, free = source[ri[following]], True
            elif next2 and next2 in ri and next2 in jmap:
                end_source, free = source[ri[next2]], True
            else:
                selected = all_role == role
                if not np.any(selected):
                    continue
                end_source, free = all_p[selected].mean(axis=0), False
            ds, dt = end_source - source[ri[role]], destination[jmap[following]] - start
            if np.linalg.norm(ds) < 1e-6 * np.ptp(all_p[:, 1]) or np.linalg.norm(dt) < 1e-6:
                continue
            rotation = S._rot_between(ds, dt)
            k = float(np.clip(np.linalg.norm(dt) / (np.linalg.norm(ds) * s), .5, 2.)) if free else 1.
            direction = dt / np.linalg.norm(dt)
            matrix = s * (np.eye(3) + (k - 1) * np.outer(direction, direction)) @ rotation
            rules[role] = (matrix, source[ri[role]], start, jmap[role])
            stretch[role] = k
        if c in ri and c in jmap and rotation is not None:
            rules[c] = (s * rotation, source[ri[c]], destination[jmap[c]], jmap[c])

    out, logical_keys = [], _LogicalVertices()
    extent = max(float(np.ptp(all_p, axis=0).max()), 1e-12)
    split = destination[hip_joint, 1] + .5 * (destination[chest_joint, 1] - destination[hip_joint, 1])
    for primitive_id, primitive in enumerate(prims):
        source_j, weights = _merge(primitive['J'], primitive['W'])
        p, n = np.zeros_like(primitive['pos']), np.zeros_like(primitive['nrm'])
        native_j = np.zeros_like(source_j)
        for column in range(source_j.shape[1]):
            roles = joint_role[source_j[:, column]]
            for role in set(roles.tolist()):
                selected = (roles == role) & (weights[:, column] > 0)
                if not np.any(selected):
                    continue
                if role in rules:
                    matrix, pivot, at, joint = rules[role]
                    positions = (primitive['pos'][selected] - pivot) @ matrix.T + at
                    normals = _normal(primitive['nrm'][selected] @ np.linalg.inv(matrix))
                    native_j[selected, column] = joint
                else:
                    positions = torso(primitive['pos'][selected])
                    # Keep the mapped role when one exists; no arbitrary torso relabeling of weighted chest.
                    joint = jmap.get(role)
                    native_j[selected, column] = joint if joint is not None else np.where(positions[:, 1] >= split, chest_joint, hip_joint)
                    scale_y = np.where(primitive['pos'][selected, 1] > hip[1], upper, lower)
                    normals = _normal(primitive['nrm'][selected] / np.stack([np.full(len(positions), s * widen), scale_y, np.full(len(positions), s)], axis=1))
                factor = weights[selected, column, None]
                p[selected] += factor * positions
                n[selected] += factor * normals
        native_j, native_w = _merge(native_j, weights)
        logical = np.empty(len(p), np.int64)
        for vertex in range(len(p)):
            influences = tuple((int(j), round(float(w), 9)) for j, w in zip(source_j[vertex], weights[vertex]) if w > 0)
            key = (primitive.get('source_mesh_node', 0), tuple(np.round(primitive['pos'][vertex] / extent, 8)), influences)
            logical[vertex] = logical_keys.add(key, p[vertex], native_j[vertex], native_w[vertex])
        out.append({**primitive, 'pos': p, 'nrm': _normal(n), 'J': native_j, 'W': native_w,
                    'owner': native_j[:, 0], 'logical_vertex_id': logical, 'name': f'm{primitive_id}'})
    flipped = S._orient(out)
    influence_counts = np.concatenate([np.count_nonzero(p['W'] > 1e-8, axis=1) for p in out])
    report = {'influence_policy': 'all mapped weights preserved; weighted role fit; no native seam reduction',
                 'logical_vertices': logical_keys.count, 'vertices': len(influence_counts),
                 'blended_vertices': int(np.count_nonzero(influence_counts > 1)),
                 'max_influences': int(influence_counts.max()),
                 'scale': s, 'torso_up': upper / s, 'torso_down': lower / s, 'shoulder_widen': widen,
                 'head_scale': head_scale, 'limb_stretch': stretch, 'normals_flipped': flipped,
                 'roles_used': sorted(ri), 'facing': basis.tolist(), 'runtime_verified': False}
    if moved['moved']:
        report['joints_moved'] = moved
    # Fitting pop-up stages and the operator's retarget profile (weights blend the role adjustments per vertex).
    return S._profiled(rig, target, out, report, scale, destination, jmap)


def read_rigged(path: Path, target_roles: dict):
    """Read the DOA Blender LOD intermediate without dropping its skin weights.

    Intermediate joint names follow sm64_swap.write_rigged's jNN contract.
    Target role IDs are passed explicitly; no DOA skeleton order is invented.
    """
    roles = {role: f'j{joint:02d}' for role, joint in target_roles.items()}
    rig = load_rig(path, roles)
    ids = []
    for name in rig['names']:
        match = re.fullmatch(r'j(\d+)', name)
        if not match:
            raise ValueError(f'LOD joint does not preserve native joint ID: {name}')
        ids.append(int(match.group(1)))
    extent = max(float(np.ptp(np.concatenate([p['pos'] for p in rig['prims']]), axis=0).max()), 1e-12)
    logical, primitives = _LogicalVertices(), []
    for primitive in rig['prims']:
        joints, weights = _merge(np.asarray(ids)[primitive['J']], primitive['W'])
        logical_ids = np.empty(len(joints), np.int64)
        for vertex in range(len(joints)):
            influences = tuple((int(j), round(float(w), 9)) for j, w in zip(joints[vertex], weights[vertex]) if w > 0)
            key = (tuple(np.round(primitive['pos'][vertex] / extent, 8)), influences)
            logical_ids[vertex] = logical.add(key, primitive['pos'][vertex], joints[vertex], weights[vertex])
        primitives.append({**primitive, 'J': joints, 'W': weights, 'owner': joints[:, 0],
                           'logical_vertex_id': logical_ids})
    return primitives
