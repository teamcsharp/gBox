"""Experimental bind-pose transfer with explicit anatomical anchors.

This transforms donor geometry and skin weights; it does not infer a universal rig
mapping or register a game writer. Callers must supply measured source/target roles.
"""
from __future__ import annotations

import numpy as np


def map_weights(vertices: list[dict], parents: dict[int, int], roles: dict[str, tuple[int, int]]):
    """Preserve the source surface and map every positive influence through a named ancestor."""
    anchors = {source: (role, target) for role, (source, target) in roles.items()}
    if not roles or len(anchors) != len(roles):
        raise ValueError('source role anchors must be nonempty and distinct')
    output, mapping = [], {}
    for vertex in vertices:
        joints, weights = vertex.get('source_joints', ()), vertex.get('source_weights', ())
        if (not 1 <= len(joints) <= 8 or len(joints) != len(weights)
                or any(not np.isfinite(w) or w < 0 for w in weights) or abs(sum(weights)-1.) > 1e-6):
            raise ValueError('retarget needs normalized source joint influences')
        merged = {}
        for joint, weight in zip(joints, weights):
            if not weight:
                continue
            current, seen = joint, set()
            while current not in anchors:
                if current in seen or current not in parents:
                    raise ValueError(f'source joint {joint} has no anatomical ancestor')
                seen.add(current)
                current = parents[current]
            role, target = anchors[current]
            merged[target] = merged.get(target, 0.) + weight
            mapping[joint] = {'role': role, 'target': target}
        if len(merged) > 4:
            raise ValueError('retarget produces more than four native influences; none are silently discarded')
        pairs = sorted(merged.items(), key=lambda pair: (-pair[1], pair[0]))
        output.append(vertex | {'bones': [b for b, _ in pairs], 'weights': [w for _, w in pairs], 'bone': pairs[0][0]})
    return output, {'joint_mapping': mapping, 'discarded_influences': 0, 'vertices': len(output),
                    'method': 'source surface retained; explicit ancestor weight correspondence', 'live_verified': False}


def reposition_bind_pose(model, anchors: dict[int, tuple], *, retarget_root_translation: bool = False):
    """Experimental native-ID rig proportions, preserving rotations and the root compression transform.

    Anchors are model-space positions of existing native bones. Intermediate bones on each anchor path move by
    arc-length interpolation; other descendants retain their parent-local bind transform. The root must remain
    unchanged unless the caller explicitly pairs the output with authored root
    translation channels, because native LMT root translations are absolute.
    This function does not itself rewrite animation channels.
    """
    import struct
    from . import mt_model

    table = model.bone_table()
    if not table.get('consistent') or model.position_transform() is None:
        raise ValueError('bind authoring requires a complete native skeleton and position transform')
    count, parents = table['bone_count'], table['parents']
    old_world = [np.asarray(m, float).reshape(4, 4) for m in model.bone_world_matrices()]
    old_local = [np.asarray(struct.unpack('<16f', m)).reshape(4, 4) for m in table['local']]
    compression = np.asarray(model.position_transform()).reshape(4, 4)
    targets = {int(i): np.asarray(point, float) for i, point in anchors.items()}
    if any(not 0 <= i < count or point.shape != (3,) or not np.isfinite(point).all() for i, point in targets.items()):
        raise ValueError('bind anchor references an invalid bone or position')
    if parents[0] != 255 or any(p == 255 for p in parents[1:]):
        raise ValueError('only a single native root at bone0 is supported')
    root_changed = 0 in targets and np.linalg.norm(targets[0]-old_world[0][3,:3]) > 1e-5
    if root_changed and not retarget_root_translation:
        raise ValueError('changing the root requires explicit animation-channel retargeting')
    if not retarget_root_translation or 0 not in targets:
        targets[0] = old_world[0][3,:3]
    intermediate = {}
    for index in list(targets):
        if index == 0:
            continue
        chain, seen, parent = [index], {index}, parents[index]
        while parent not in targets:
            if parent >= count or parent in seen:
                raise ValueError('invalid native skeleton parent chain')
            seen.add(parent)
            chain.append(parent)
            parent = parents[parent]
        chain.append(parent)
        chain.reverse()
        distances = [0.]
        for a, b in zip(chain, chain[1:]):
            distances.append(distances[-1]+np.linalg.norm(old_world[b][3,:3]-old_world[a][3,:3]))
        for bone, distance in zip(chain[1:-1], distances[1:-1]):
            fraction = distance / distances[-1] if distances[-1] else 0.
            point = targets[parent]*(1-fraction)+targets[index]*fraction
            if bone in intermediate and np.linalg.norm(intermediate[bone]-point) > 1e-5:
                raise ValueError('incompatible anchors share an unconstrained branch; supply its branch anchor')
            intermediate[bone] = point
    targets.update(intermediate)
    world, local = {}, {}
    visiting = set()
    def compose(index):
        if index in world:
            return world[index]
        if index in visiting:
            raise ValueError('cyclic native skeleton parent chain')
        visiting.add(index)
        parent = parents[index]
        ancestor = np.eye(4) if parent == 255 else compose(parent)
        matrix = old_local[index].copy() @ ancestor
        if index in targets:
            matrix[3,:3] = targets[index]
        world[index] = matrix
        local[index] = matrix @ np.linalg.inv(ancestor)
        visiting.remove(index)
        return matrix
    for index in range(count):
        compose(index)
    raw, start = bytearray(model.raw), model.header()['offsets']['bones']
    for index in range(count):
        inverse = compression @ np.linalg.inv(world[index])
        struct.pack_into('<16f', raw, start+count*24+index*64, *local[index].ravel())
        struct.pack_into('<16f', raw, start+count*88+index*64, *inverse.ravel())
        position = local[index][3,:3]
        struct.pack_into('<4f', raw, start+index*24+8, float(np.linalg.norm(position)), *position)
    rebuilt = mt_model.parse_mod(bytes(raw))
    error = max(np.abs(np.asarray(rebuilt.position_transform())-np.asarray(model.position_transform())))
    if error > 1e-4:
        raise ValueError('bind adjustment changed native position compression')
    return rebuilt, {'anchors': {str(i): list(map(float, p)) for i,p in targets.items()},
                     'root_unchanged': not root_changed, 'rotations_preserved': True, 'animation_channels_changed': False,
                     'requires_root_translation_retarget': bool(root_changed),
                     'position_transform_max_error': float(error), 'live_verified': False}


def _aim_rotation(source, target):
    """Align segment directions while retaining the model's forward-facing axis."""
    def frame(direction):
        axis = np.array(direction, dtype=float, copy=True)
        length = float(np.linalg.norm(axis))
        if length < 1e-8:
            raise ValueError("retarget segment has zero length")
        axis /= length
        reference = np.array((0., 0., 1.))
        if abs(float(axis @ reference)) > .95:
            reference = np.array((0., 1., 0.))
        across = np.cross(axis, reference)
        across /= np.linalg.norm(across)
        forward = np.cross(across, axis)
        return np.stack((axis, across, forward), axis=1)
    return frame(target) @ frame(source).T


def direction_frame(direction, reference):
    """A proper orthonormal frame from an axis and a measured transverse direction.

    The reference fixes roll (for example, the thumb side of a hand). It must
    not be parallel to the main axis. Columns are axis, transverse, cross.
    """
    axis, side = np.array(direction, float, copy=True), np.array(reference, float, copy=True)
    if axis.shape != (3,) or side.shape != (3,) or not np.isfinite([axis, side]).all():
        raise ValueError('an anatomical frame needs finite XYZ directions')
    length = np.linalg.norm(axis)
    if length < 1e-8:
        raise ValueError('an anatomical frame has a zero direction')
    axis /= length
    side -= axis * (side @ axis)
    length = np.linalg.norm(side)
    if length < 1e-8:
        raise ValueError('an anatomical frame reference is parallel to its direction')
    side /= length
    return np.stack((axis, side, np.cross(axis, side)), axis=1)


def repose(vertices: list[dict], source_positions: dict[int, tuple], source_parents: dict[int, int],
           target_positions: dict[int, tuple], roles: dict[str, tuple[int, int]],
           segments: dict[str, str], *, scale: float, root_role: str, root_position: tuple,
           frames: dict[str, tuple] | None = None):
    """Repose the donor into native bind directions, retaining donor segment lengths.

    Each named influence receives a proper rotation and uniform scale. Its new
    anchor follows the closest named ancestor, so the incoming and outgoing
    segment meet at one joint. Explicit frames contain source direction,
    source transverse direction, target direction, target transverse direction;
    they fix hand/foot roll without reflection or inferred left/right symmetry.
    The returned anchors are geometry anchors, not a request to move root0.
    """
    if not roles or root_role not in roles or not np.isfinite(scale) or scale <= 0:
        raise ValueError('repose needs explicit roles, a root role, and a positive uniform scale')
    source_role = {source: role for role, (source, _) in roles.items()}
    if len(source_role) != len(roles):
        raise ValueError('source role anchors must be distinct')
    if len({target for _,target in roles.values()}) != len(roles):
        raise ValueError('repose target role anchors must be distinct')
    if set(frames or {}) - set(roles) or set(segments) - set(roles):
        raise ValueError('repose frames and segments must reference named roles')
    if any(source not in source_positions or target not in target_positions for source, target in roles.values()):
        raise ValueError('repose role references an absent joint')
    role_parents = {}
    for role, (source, _) in roles.items():
        if role == root_role:
            continue
        seen, ancestor = {source}, source_parents.get(source)
        while ancestor not in source_role:
            if ancestor is None or ancestor in seen:
                raise ValueError(f'repose role {role} has no named ancestor')
            seen.add(ancestor)
            ancestor = source_parents.get(ancestor)
        role_parents[role] = source_role[ancestor]
    rotations = {}
    for role, (source, target) in roles.items():
        if role in (frames or {}):
            source_axis, source_side, target_axis, target_side = frames[role]
            rotation = direction_frame(target_axis, target_side) @ direction_frame(source_axis, source_side).T
        elif role in segments:
            child = segments[role]
            if child not in roles or role_parents.get(child) != role:
                raise ValueError('repose segments must connect adjacent named roles')
            next_source, next_target = roles[child]
            rotation = _aim_rotation(np.subtract(source_positions[next_source], source_positions[source]),
                                     np.subtract(target_positions[next_target], target_positions[target]))
        else:
            rotation = None
        rotations[role] = rotation
    anchors, visiting = {}, set()
    root_position = np.asarray(root_position, float)
    if root_position.shape != (3,) or not np.isfinite(root_position).all():
        raise ValueError('repose root position must be finite XYZ')
    def place(role):
        if role in anchors:
            return anchors[role]
        if role in visiting:
            raise ValueError('cyclic source role hierarchy')
        visiting.add(role)
        if role == root_role:
            anchors[role] = root_position
            if rotations[role] is None:
                rotations[role] = np.eye(3)
        else:
            parent = role_parents[role]
            position = place(parent)
            offset = np.subtract(source_positions[roles[role][0]], source_positions[roles[parent][0]])
            anchors[role] = position + rotations[parent] @ offset * scale
            if rotations[role] is None:
                rotations[role] = rotations[parent]
        visiting.remove(role)
        return anchors[role]
    for role in roles:
        place(role)
    mapped, receipt = map_weights(vertices, source_parents, roles)
    for original, output in zip(vertices, mapped):
        point, normal = np.asarray(original['position']), np.asarray(original['normal'])
        moved, rotated = np.zeros(3), np.zeros(3)
        for joint, weight in zip(original['source_joints'], original['source_weights']):
            if not weight:
                continue
            role = receipt['joint_mapping'][joint]['role']
            moved += weight * (anchors[role] + scale * rotations[role] @ (point-source_positions[roles[role][0]]))
            rotated += weight * (rotations[role] @ normal)
        length = np.linalg.norm(rotated)
        if length < 1e-8 or not np.isfinite(moved).all():
            raise ValueError('repose produced an undefined normal or position')
        output.update(position=tuple(map(float, moved)), normal=tuple(map(float, rotated/length)))
    receipt.update(method='source segment lengths; native bind directions; explicit proper rotation frames',
                   scale=scale, role_parents=role_parents,
                   rotations={role: matrix.tolist() for role, matrix in rotations.items()},
                   rotation_determinants={role: float(np.linalg.det(matrix)) for role,matrix in rotations.items()},
                   geometry_anchors={role: point.tolist() for role,point in anchors.items()},
                   explicit_frame_roles=sorted(frames or {}))
    return mapped, {roles[role][1]: tuple(map(float, point)) for role,point in anchors.items()}, receipt


def transfer(vertices: list[dict], source_positions: dict[int, tuple], source_parents: dict[int, int],
             target_positions: dict[int, tuple], roles: dict[str, tuple[int, int]],
             segments: dict[str, str], *, scale: float, continuous: bool = False):
    """Transfer each influence through its nearest named ancestor's anatomical frame.

    ``roles`` maps role -> (source scene node, target bone). ``segments`` maps a role
    to its next anatomical joint. Longitudinal scale matches actual segment lengths,
    while cross sections use the supplied uniform scale. Terminal parts inherit the
    incoming segment orientation, keeping both sides of a joint coincident. Geometry
    uses complete source weights; normalized target weights are merged by bone.
    """
    if not roles or not np.isfinite(scale) or scale <= 0:
        raise ValueError("retarget needs roles and a finite positive uniform scale")
    for source, target in roles.values():
        if source not in source_positions or target not in target_positions:
            raise ValueError("retarget role references an absent joint")
    by_source = {source: role for role, (source, _) in roles.items()}
    if len(by_source) != len(roles):
        raise ValueError("source role anchors must be distinct")
    transforms = {}
    for role, (source, target) in roles.items():
        transform = np.eye(3) * scale
        if role in segments:
            if segments[role] not in roles:
                raise ValueError("retarget segment references an absent role")
            next_source, next_target = roles[segments[role]]
            source_vector = np.subtract(source_positions[next_source], source_positions[source])
            target_vector = np.subtract(target_positions[next_target], target_positions[target])
            rotation = _aim_rotation(source_vector, target_vector)
            axis = source_vector / np.linalg.norm(source_vector)
            along_scale = np.linalg.norm(target_vector) / np.linalg.norm(source_vector)
            transform = rotation @ (np.eye(3) * scale + (along_scale - scale) * np.outer(axis, axis))
        else:
            incoming = [start for start, end in segments.items() if end == role]
            if len(incoming) == 1:
                previous_source, previous_target = roles[incoming[0]]
                transform = _aim_rotation(np.subtract(source_positions[source], source_positions[previous_source]),
                                          np.subtract(target_positions[target], target_positions[previous_target])) * scale
        transforms[role] = transform
    mapping = {}
    output = []
    for vertex in vertices:
        joints, weights = vertex.get("source_joints", ()), vertex.get("source_weights", ())
        if (not 1 <= len(joints) <= 8 or len(joints) != len(weights)
                or any(not np.isfinite(w) or w < 0 for w in weights) or abs(sum(weights) - 1.) > 1e-6):
            raise ValueError("retarget needs normalized source joint influences")
        point, normal = np.asarray(vertex["position"], float), np.asarray(vertex["normal"], float)
        moved, rotated = np.zeros(3), np.zeros(3)
        target_weights = {}
        for joint, weight in zip(joints, weights):
            if weight == 0:
                continue
            chain = set()
            anchor = joint
            while anchor not in by_source:
                if anchor in chain or anchor not in source_parents:
                    raise ValueError(f"source joint {joint} has no anatomical ancestor")
                chain.add(anchor)
                anchor = source_parents[anchor]
            role = by_source[anchor]
            source, target = roles[role]
            transform = transforms[role]
            moved += weight * (transform @ (point - source_positions[source]) + target_positions[target])
            rotated += weight * (np.linalg.inv(transform).T @ normal)
            target_weights[target] = target_weights.get(target, 0.) + weight
            mapping[joint] = {"role": role, "target": target}
        if len(target_weights) > 4:
            raise ValueError("retarget produces more than four native influences; none are silently discarded")
        pairs = sorted(target_weights.items(), key=lambda item: (-item[1], item[0]))
        length = float(np.linalg.norm(rotated))
        if length < 1e-8 or not np.isfinite(moved).all():
            raise ValueError("retarget produces an invalid normal or position")
        output.append(vertex | {"position": tuple(map(float, moved)), "normal": tuple(map(float, rotated / length)),
                                "bones": [b for b, _ in pairs], "weights": [w for _, w in pairs],
                                "bone": pairs[0][0]})
    if continuous:
        # One spatial field maps coincident vertices identically across separate donor components. Blend displacement
        # from the uniform donor pose with positive inverse-distance weights: every displacement stays inside the
        # control displacement hull, unlike an unconstrained interpolant that can overshoot the quantisation range.
        controls = {}
        for joint, point in source_positions.items():
            anchor, seen = joint, set()
            while anchor not in by_source and anchor in source_parents and anchor not in seen:
                seen.add(anchor)
                anchor = source_parents[anchor]
            if anchor not in by_source:
                continue
            role = by_source[anchor]
            source, target = roles[role]
            mapped = transforms[role] @ (np.asarray(point) - source_positions[source]) + target_positions[target]
            key = tuple(round(float(v), 6) for v in point)
            controls.setdefault(key, []).append(mapped)
        original = np.asarray(list(controls), float)
        desired = np.asarray([np.mean(v, axis=0) for v in controls.values()])
        query = np.asarray([v['position'] for v in vertices])
        distances = np.sum((query[:, None] - original[None, :]) ** 2, axis=2)
        weights = 1. / np.maximum(distances, 1e-12) ** 2
        weights /= weights.sum(axis=1, keepdims=True)
        displacement = desired - original * scale
        moved = query * scale + weights @ displacement
        if not np.isfinite(moved).all():
            raise ValueError("continuous retarget produced nonfinite geometry")
        for vertex, point in zip(output, moved):
            vertex['position'] = tuple(map(float, point))
    return output, {"scale": scale, "joint_mapping": mapping,
                    "method": "bounded inverse-distance anatomical warp" if continuous else "anatomical segment lengths; uniform cross sections",
                    "vertices": len(output), "discarded_influences": 0, "live_verified": False}
