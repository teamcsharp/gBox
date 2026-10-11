"""Convert donor bind attributes into the game's original curved SUP space.

The solver itself lives in doa2_seams.curve_matrix and was traced at 8c0e6ea4.
This inverse conversion does not substitute linear skinning for that solver.
It supports exactly one native bone pair per seam model; it deliberately does
not infer arbitrary donor joint-pair reductions or invent native controllers.
"""
from __future__ import annotations

import numpy as np
from gbox import doa2_seams as S


def quantize_sample(weight_b: float) -> int:
    """Nearest native parameter, including unwritten A endpoint0 and direct B16."""
    if not np.isfinite(weight_b) or not 0 <= weight_b <= 1:
        raise ValueError('bone-B weight must be finite and in [0,1]')
    return min(16, int(np.floor(float(weight_b) * 16 + .5)))


def _pose(world):
    world = np.asarray(world, dtype=float)
    if world.ndim != 3 or world.shape[1:] != (4, 4) or not np.isfinite(world).all():
        raise ValueError('SUP conversion requires finite joint matrices')
    if not np.allclose(world[:, 3], [0, 0, 0, 1], atol=1e-7):
        raise ValueError('SUP joint matrices must be affine')
    rotations = world[:, :3, :3]
    if not np.allclose(rotations.transpose(0, 2, 1) @ rotations, np.eye(3), atol=1e-5):
        raise ValueError('native SUP conversion requires rigid joint matrices')
    if not np.allclose(np.linalg.det(rotations), 1, atol=1e-5):
        raise ValueError('native SUP matrices must preserve orientation')
    return world


def symmetric_seam(world, bone_a: int, bone_b: int):
    """Data-only native seam whose world deformation is independent of owner.

    Its endpoint axes are the shared neutral world basis, expressed in each
    joint's bind frame. Zero controls put the curve origin between actual joint
    origins. Reverse A/B with sample16-s to obtain the same world transform.
    The consumer still uses the existing native curve; no engine patch applies.
    """
    world = _pose(world)
    if not 0 <= bone_a < len(world) or not 0 <= bone_b < len(world) or bone_a == bone_b:
        raise ValueError('symmetric SUP seam needs two existing distinct joints')
    pairs = np.empty((3, 2, 3))
    # axis_pairs[:,endpoint].T are the endpoint's local basis columns.
    pairs[:, 0] = world[bone_a, :3, :3]
    pairs[:, 1] = world[bone_b, :3, :3]
    return {'bone_a': int(bone_a), 'bone_b': int(bone_b), 'axis_pairs': pairs,
            'controls': np.zeros((4, 3)), 'evidence': 'native 8c0e6ea4 solver; common neutral world axes; zero origin controls'}


def bind_payload(seam, world, positions, normals, samples, coefficients):
    """Return local CHR attributes and native SUP payloads for one seam model.

    Arrays correspond to logical vertices, not individual triangles. Callers
    must reuse each result for every CHR occurrence of the same donor vertex.
    Sample0 stays in bone-A local space and must not appear as a SUP group.
    For samples1..16 SUP payloads are curve-local, while initial CHR attributes
    still hold the exact bind geometry in bone-A space.
    """
    world = _pose(world)
    a, b = int(seam['bone_a']), int(seam['bone_b'])
    if not 0 <= a < len(world) or not 0 <= b < len(world) or a == b:
        raise ValueError('SUP pair references absent or identical joints')
    positions, normals = np.asarray(positions, float), np.asarray(normals, float)
    samples = np.asarray(samples)
    if positions.ndim != 2 or positions.shape[1:] != (3,) or normals.shape != positions.shape:
        raise ValueError('SUP attributes must be matching Nx3 arrays')
    if not np.isfinite(positions).all() or not np.isfinite(normals).all():
        raise ValueError('SUP attributes must be finite')
    if samples.shape != (len(positions),) or not np.issubdtype(samples.dtype, np.integer):
        raise ValueError('SUP samples must be an integer per logical vertex')
    if np.any((samples < 0) | (samples > 16)):
        raise ValueError('SUP samples must be in [0,16]')
    coefficients = np.asarray(coefficients, float)
    if coefficients.shape != (16, 3) or not np.isfinite(coefficients).all():
        raise ValueError('SUP requires the owned 16x3 coefficient table')
    local_p = (positions - world[a, :3, 3]) @ world[a, :3, :3]
    local_n = normals @ world[a, :3, :3]
    payload_p, payload_n = local_p.copy(), local_n.copy()
    relative = np.linalg.inv(world[a]) @ world[b]
    max_error = 0.0
    for sample in sorted(set(samples.tolist()) - {0}):
        matrix = S.curve_matrix(seam, relative, sample, coefficients)
        selected = samples == sample
        inverse = np.linalg.inv(matrix)
        payload_p[selected] = local_p[selected] @ inverse[:3, :3].T + inverse[:3, 3]
        # SUP directly rotates normals; no position translation applies.
        payload_n[selected] = local_n[selected] @ inverse[:3, :3].T
        recovered = payload_p[selected] @ matrix[:3, :3].T + matrix[:3, 3]
        max_error = max(max_error, float(np.max(np.abs(recovered - local_p[selected]))))
    return {'chr_positions': local_p, 'chr_normals': local_n,
            'payload_positions': payload_p, 'payload_normals': payload_n,
            'samples': samples.astype(np.uint8), 'write_mask': samples != 0,
            'report': {'bone_a': a, 'bone_b': b, 'logical_vertices': len(positions),
                       'written_vertices': int(np.count_nonzero(samples)),
                       'sample_counts': {str(s): int(np.count_nonzero(samples == s))
                                         for s in sorted(set(samples.tolist()))},
                       'max_bind_reconstruction_error': max_error,
                       'solver': 'original curved SUP, including native direct-B group16',
                       'runtime_verified': False}}


def evaluate_payload(seam, world, payload, coefficients):
    """Evaluate native positions/normals at a supplied pose for offline checks."""
    world = _pose(world)
    a, b = int(seam['bone_a']), int(seam['bone_b'])
    p = np.asarray(payload['payload_positions'], float).copy()
    n = np.asarray(payload['payload_normals'], float).copy()
    samples = np.asarray(payload['samples'])
    relative = np.linalg.inv(world[a]) @ world[b]
    for sample in sorted(set(samples.tolist()) - {0}):
        matrix = S.curve_matrix(seam, relative, sample, coefficients)
        selected = samples == sample
        p[selected] = p[selected] @ matrix[:3, :3].T + matrix[:3, 3]
        n[selected] = n[selected] @ matrix[:3, :3].T
    return p @ world[a, :3, :3].T + world[a, :3, 3], n @ world[a, :3, :3].T
