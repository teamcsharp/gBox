"""Optional owned-source/Blender proof; no copyrighted model bytes in git."""
from itertools import product
import json
import os
from pathlib import Path

import numpy as np
import pytest

from gbox import characters as C
from gbox.re5ps3_arc import sha
from gbox.re5ps3_models import Model
from gbox.re5ps3_roles import role_evidence


def point_witnesses(points, reference, tolerance=.00005):
    buckets = {}
    for point, cell in zip(reference, np.floor(reference / tolerance).astype(np.int64)):
        buckets.setdefault(tuple(cell), []).append(point)
    offsets = [(0, 0, 0)] + [p for p in product((-1, 0, 1), repeat=3) if p != (0, 0, 0)]
    for point in np.unique(points, axis=0):
        cell = np.floor(point / tolerance).astype(np.int64)
        for delta in offsets:
            matches = buckets.get(tuple(cell + delta), ())
            if len(matches) and np.linalg.norm(np.asarray(matches) - point, axis=1).min() < tolerance:
                break
        else:
            pytest.fail(f'Blender/native weighted pose differs at {point.tolist()}')


def test_every_owned_role_has_independent_blender_controlled_skin_evidence():
    evidence = Path(os.environ.get('GBOX_RE5_EVIDENCE', str(Path.home()/'gbox-pr-audit-20261017/re-export-evidence')))
    root = Path(os.environ.get('GBOX_RE5_ROLE_POSES', str(evidence/'re5-role-pose-proof-v3'))).resolve()
    manifest = root / 'blender-proof.json'
    if not manifest.exists():
        pytest.skip('owned offline Blender role poses unavailable')
    proof = json.loads(manifest.read_text())
    assert proof['tool'] == '4.0.2' and len(proof['targets']) == 2
    verified_models = set()
    for target in proof['targets']:
        source = Path(target['source']).resolve()
        assert source.is_relative_to(evidence.resolve()) and sha(source.read_bytes()) == target['source_sha256']
        tag = source.name.split('-bind-')[0]
        model_path = evidence / (tag + '-model.bin')
        assert model_path.resolve().is_relative_to(evidence.resolve())
        native = model_path.read_bytes()
        assert sha(native) == target['native_model_sha256']
        model = Model(native); roles = role_evidence(model)
        assert roles
        assert sha(native) not in verified_models; verified_models.add(sha(native))
        wanted = set(roles['native_joint_ids'].values()) | {None}
        assert len(target['poses']) == len(wanted) == 19
        assert {p['joint'] for p in target['poses']} == wanted
        for pose in target['poses']:
            joint = pose['joint']
            assert pose['translation_world_blender_m'] == ([0, 0, 0] if joint is None else [.35, 0, 0])
            path = Path(pose['file']).resolve()
            assert path.is_relative_to(root) and sha(path.read_bytes()) == pose['sha256']
            descendants = set() if joint is None else {joint}
            for _ in model.parents:
                descendants.update(i for i, p in enumerate(model.parents) if p in descendants)
            expected, triangle_count = [], 0
            for mesh in model.meshes:
                if not mesh['visible'] or not mesh['lod'] & 1 or not len(mesh['triangles']):
                    continue
                ids = np.unique(mesh['triangles'])
                mass = (mesh['weights'][ids] * np.isin(mesh['joints'][ids], list(descendants))).sum(1)
                expected.append(mesh['positions'][ids] * .01 + mass[:, None] * [.35, 0, 0])
                # Blender mesh.validate() drops repeated faces (including reversed
                # winding), not every geometrically degenerate triangle. Native
                # strips contain 30 such repeats for Chris and 2 for Sheva.
                triangle_count += len(np.unique(np.sort(mesh['triangles'], axis=1), axis=0))
            expected = np.concatenate(expected)
            actual = np.concatenate([t[0] for t in C._triangles(path)])
            assert len(actual) == triangle_count * 3
            point_witnesses(actual, expected)
            point_witnesses(expected, actual)
