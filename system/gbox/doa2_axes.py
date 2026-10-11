"""Solve observed native SUP orientation constraints relative to one joint.

This produces rotations only. It does not invent translations or replace the
game's neutral-pose validation. The SUP renderer mixes A/B-local axis vectors;
the candidate neutral relationship is R_a A = R_b B. Input comes from the
owned-disc all_sup_axes audit, where each common pair is consistent.
"""
from __future__ import annotations

import numpy as np


def solve(records: list[dict], anchor: int = 2, joint_ids=range(15), tolerance: float = 1e-5) -> dict:
    joint_ids = set(joint_ids)
    if anchor not in joint_ids:
        raise ValueError('axis anchor is outside the requested joint set')
    edges, evidence = [], []
    for record in records:
        a, b = record['bone_a'], record['bone_b']
        if a not in joint_ids or b not in joint_ids:
            continue
        ac, bc = np.asarray(record['a_columns'], dtype=float), np.asarray(record['b_columns'], dtype=float)
        for matrix in (ac, bc):
            if matrix.shape != (3, 3) or not np.isfinite(matrix).all():
                raise ValueError('SUP axis basis must contain a finite 3x3 matrix')
            if not np.allclose(matrix.T @ matrix, np.eye(3), atol=tolerance) or not np.isclose(np.linalg.det(matrix), 1, atol=tolerance):
                raise ValueError('SUP basis is not a proper orthogonal rotation')
        # R_a A = R_b B, so R_a = R_b B A^-1.
        relative = bc @ ac.T
        edges.append((a, b, relative))
        evidence.append({'bone_a': a, 'bone_b': b, 'source': record.get('name'),
                         'relative_rotation': relative.tolist()})
    rotations = {anchor: np.eye(3)}
    while True:
        previous = len(rotations)
        for a, b, relative in edges:
            if b in rotations and a not in rotations:
                rotations[a] = rotations[b] @ relative
            elif a in rotations and b not in rotations:
                rotations[b] = rotations[a] @ relative.T
            if a in rotations and b in rotations and not np.allclose(rotations[a], rotations[b] @ relative, atol=tolerance):
                raise ValueError(f'inconsistent SUP orientation constraints at joints {a}/{b}')
        if len(rotations) == previous:
            break
    missing = joint_ids - rotations.keys()
    if missing:
        raise ValueError(f'SUP evidence does not connect joints {sorted(missing)} to anchor {anchor}')
    return {'anchor_joint': anchor, 'rotations': {str(k): v.tolist() for k, v in sorted(rotations.items())},
            'evidence': evidence, 'translation_policy': 'not derived by this solver',
            'interpretation': 'SUP axis coincidence in a neutral pose; requires native validation'}
