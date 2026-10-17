"""A 3x3x3 quadratic deformation cage in donor coordinates, before retargeting.

Offsets are fractions of donor height. Geometry changes; rig anchors, topology,
UVs and skin weights remain intact. Normals use the deformation Jacobian.
"""
from __future__ import annotations

import numpy as np


def normalize(value):
    if not isinstance(value, dict):
        raise ValueError('lattice must contain an offsets object')
    offsets = value.get('offsets', {})
    if not isinstance(offsets, dict) or len(offsets) > 27:
        raise ValueError('lattice has at most 27 control points')
    out = {}
    for key, vector in offsets.items():
        if str(key) not in {str(i) for i in range(27)}:
            raise ValueError('lattice control index must be 0..26')
        if not isinstance(vector, (list, tuple)) or len(vector) != 3:
            raise ValueError('lattice offset must be [x,y,z]')
        v = np.asarray(vector, float)
        if not np.isfinite(v).all():
            raise ValueError('lattice offsets must be finite')
        v = np.clip(v, -.25, .25).round(6)
        if np.any(v):
            out[str(key)] = v.tolist()
    return {'offsets': out}


def deform(points, lattice, lower, upper, height, normals=None):
    points = np.asarray(points, float)
    offsets = normalize(lattice)['offsets']
    if not offsets:
        return points.copy(), None if normals is None else np.asarray(normals, float).copy()
    size = np.maximum(np.asarray(upper) - lower, max(height, 1e-9) * .001)
    raw = (points - lower) / size
    t = np.clip(raw, 0, 1)
    weights = [(1-t)**2, 2*t*(1-t), t*t]
    deriv = [-2*(1-t), 2-4*t, 2*t]
    delta = np.zeros_like(points)
    jac = np.repeat(np.eye(3)[None], len(points), axis=0)
    for key, offset in offsets.items():
        i = int(key); x, y, z = i % 3, i // 3 % 3, i // 9
        indices = (x, y, z)
        v = np.asarray(offset) * height
        w = weights[x][:, 0] * weights[y][:, 1] * weights[z][:, 2]
        delta += w[:, None] * v
        if normals is not None:
            for axis in range(3):
                d = deriv[indices[axis]][:, axis] / size[axis]
                d = d * ((raw[:, axis] >= 0) & (raw[:, axis] <= 1))
                for other in range(3):
                    if other != axis:
                        d = d * weights[indices[other]][:, other]
                jac[:, :, axis] += d[:, None] * v
    adjusted = points + delta
    if normals is None:
        return adjusted, None
    if np.any(np.linalg.det(jac) <= 1e-6):
        raise ValueError('The cage folds or collapses the mesh. Reduce the control-point displacement.')
    n = np.linalg.solve(jac.transpose(0, 2, 1), np.asarray(normals, float)[..., None])[..., 0]
    n /= np.maximum(np.linalg.norm(n, axis=1, keepdims=True), 1e-12)
    return adjusted, n


def apply(rig, lattice):
    offsets = normalize(lattice)['offsets']
    if not offsets:
        return rig
    from .retarget_profile import donor_frame
    basis, height = donor_frame(rig)
    body = [p for p in rig['prims'] if not p.get('prop')]
    if not body:
        return rig
    allp = np.concatenate([np.asarray(p['pos']) @ basis.T for p in body])
    lower, upper = allp.min(0), allp.max(0)
    prims = []
    for p in rig['prims']:
        if p.get('prop'):
            prims.append(p); continue
        points, normals = deform(np.asarray(p['pos']) @ basis.T, {'offsets': offsets}, lower, upper, height,
                                 np.asarray(p['nrm']) @ basis.T)
        prims.append({**p, 'pos': points @ basis, 'nrm': normals @ basis})
    return {**rig, 'prims': prims}
