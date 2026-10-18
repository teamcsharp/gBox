import json
import math
import os
from pathlib import Path
import struct

import numpy as np
import pytest

from gbox import attachments, doa2_weighted_retarget as R
from gbox.re5ps3_arc import Arc, sha
from gbox.re5ps3_collection import FILES, CHRIS, SHEVA
from gbox.re5ps3_fit import DONORS, build_fitted_archive, fit_archive, atlas_geometry, main
from gbox.re5ps3_models import Model
from gbox.re5ps3_roles import role_evidence


def evidence_root():
    return Path(os.environ.get('GBOX_RE5_EVIDENCE', str(Path.home() / 'gbox-pr-audit-20261017/re-export-evidence')))


@pytest.fixture(scope='module', params=[CHRIS, SHEVA])
def fitted(request):
    key = request.param; donor = DONORS[key]; root = evidence_root()
    matches = list(root.glob('re5/**/' + Path(key).name))
    path = root / 're5-donor-fitting-v1' / Path(key).stem / 'donor.glb'
    if not matches or not path.exists():
        pytest.skip('owned RE5 archive and exact donor snapshot unavailable')
    source = matches[0].read_bytes(); donor_bytes = path.read_bytes()
    output, receipt = build_fitted_archive(source, donor_bytes, expected_sha256=FILES[key][1])
    arc, written = Arc(source), Arc(output)
    entry = next(e for e in arc.entries if e.name == donor['model_member'] and arc.read(e)[:4] == b'\0DOM')
    original = Model(arc.read(entry)); model = Model(written.read(written.find(entry.name, entry.type_hash)))
    with attachments.paused():
        rig = R.load_rig(path, donor['roles'])
    return dict(key=key, donor=donor, source=source, donor_bytes=donor_bytes, output=output, receipt=receipt,
                arc=arc, written=written, original=original, model=model, rig=rig,
                source_path=matches[0], donor_path=path)


def mapped_joint(rig, roles, source_joint):
    # Independent ancestry walk, retaining every source influence before sum.
    named = {index: role for role, index in rig['roles'].items()}
    joint = int(source_joint)
    while joint >= 0 and joint not in named:
        joint = rig['parent'][joint]
    return roles[named.get(joint, 'hip')]


def test_real_native_body_preserves_every_mapped_weight_and_source_triangle(fitted):
    f = fitted; mesh = f['model'].meshes[0]; roles = role_evidence(f['original'])['native_joint_ids']; row = 0
    for primitive in f['rig']['prims']:
        faces = [primitive['tris']]
        if primitive['double_sided']: faces.append(primitive['tris'][:, ::-1])
        for triangles in faces:
            for source_vertex in triangles.reshape(-1):
                expected = {}
                for joint, weight in zip(primitive['J'][source_vertex], primitive['W'][source_vertex]):
                    if weight:
                        target = mapped_joint(f['rig'], roles, joint)
                        expected[target] = expected.get(target, 0.) + weight
                actual = {int(j): float(w) for j, w in zip(mesh['joints'][row], mesh['weights'][row]) if w > 0}
                assert set(actual) == set(expected)
                assert all(abs(actual[j] - expected[j]) <= 1 / 255 + 1e-12 for j in expected)
                row += 1
    assert row == len(mesh['positions'])
    assert np.array_equal(mesh['triangles'], np.arange(row).reshape(-1, 3))
    assert len(mesh['triangles']) == (1369 if f['key'] == CHRIS else 1013)
    assert sum(c['back_faces_added'] for c in f['receipt']['triangles']) == (0 if f['key'] == CHRIS else 215)
    assert sum(c['source'] for c in f['receipt']['triangles']) == f['donor']['source_triangles']
    assert f['receipt']['fit']['source_weights_preserved_before_native_quantization']


def test_real_native_bounds_ground_scale_and_foot_gap(fitted):
    f = fitted; mesh = f['model'].meshes[0]; report = f['receipt']['fit']; roles = role_evidence(f['original'])['native_joint_ids']
    original_points = np.concatenate([m['positions'] for m in f['original'].meshes if m['visible'] and m['lod'] & 1])
    points = mesh['positions']; tolerance = np.ptp(points, axis=0).max() / 32767 + .0001
    assert math.isfinite(report['scale']) and report['scale'] > 0
    assert abs(points[:, 1].min() - original_points[:, 1].min()) < tolerance
    assert abs(report['ground_error_cm']) < 1e-8
    assert np.isfinite(points).all()
    # Head scale is deliberately not a camera-height promise.
    assert report['fitted_bounds_cm']['max'][1] > report['original_bounds_cm']['max'][1]
    feet = []
    for side in ('l', 'r'):
        selected = np.any((mesh['joints'] == roles[side + '_foot']) & (mesh['weights'] > 0), axis=1)
        if f['key'] == SHEVA:
            assert not selected.any() and report['foot_fits'][side]['visible_vertices'] == 0
            continue
        foot = points[selected]; feet.append(foot)
        assert len(foot) > 0 and foot[:, 1].min() >= original_points[:, 1].min() - tolerance
        assert np.isfinite(report['foot_fits'][side]['axis_scale']).all()
        assert min(report['foot_fits'][side]['axis_scale']) > 0
    if feet:
        low, high = sorted(feet, key=lambda p: p[:, 0].min())
        separation = abs(f['original'].world[roles['l_foot'], 0, 3] - f['original'].world[roles['r_foot'], 0, 3])
        gap = high[:, 0].min() - low[:, 0].max()
        assert gap > .099 * separation - 2 * tolerance
        assert abs(gap - report['foot_gap_cm']) < 2 * tolerance
    else:
        assert report['foot_gap_cm'] is None


def test_source_skeleton_and_every_unrelated_archive_resource_stay_exact(fitted):
    f = fitted; source, result = f['original'], f['model']
    at = struct.unpack_from('>I', source.data, 44)[0]; end = at + len(source.parents) * 152 + 256
    assert result.data[at:end] == source.data[at:end]
    assert source.parents == result.parents and source.anim_map == result.anim_map
    assert np.array_equal(source.local, result.local) and np.array_equal(source.inverse_bind, result.inverse_bind)
    changed = []
    for entry in f['arc'].entries:
        if f['arc'].read(entry) != f['written'].read(f['written'].find(entry.name, entry.type_hash)):
            changed.append(entry.name)
    assert set(changed) == {f['donor']['model_member'], f['receipt']['native']['diffuse_texture']}
    assert sha(f['source_path'].read_bytes()) == FILES[f['key']][1]
    assert sha(f['donor_path'].read_bytes()) == f['donor']['sha256']
    assert role_evidence(result) is None  # changed bytes cannot inherit original semantic evidence
    assert not f['receipt']['full_cast'] and not f['receipt']['gameplay_verified']
    assert not f['receipt']['camera_culling_motion_verified']
    reviewed = evidence_root() / 're5-donor-fitting-v1/native-first-fit-v6' / Path(f['key']).stem / 'experimental.mod'
    assert result.data == reviewed.read_bytes()  # tie the CLI to the visually reviewed native pose source
    assert 'not super-yellow' in DONORS[CHRIS]['label']
    assert len(DONORS[SHEVA]['unweighted_roles']) == 6


def test_actual_written_envelopes_enclose_all_weighted_native_points(fitted):
    model = fitted['model']; mesh = model.meshes[0]; at = struct.unpack_from('>I', model.data, 56)[0] + 52
    count = struct.unpack_from('>I', model.data, at)[0]
    assert count == len(set(mesh['joints'][mesh['weights'] > 0].tolist()))
    for i in range(count):
        raw = model.data[at + 4 + i * 144:at + 4 + (i + 1) * 144]; joint = struct.unpack_from('>I', raw)[0]
        selected = np.any((mesh['joints'] == joint) & (mesh['weights'] > 0), axis=1)
        points = np.column_stack((mesh['positions'][selected], np.ones(selected.sum()))) @ model.inverse_bind[joint].T
        sphere = np.array(struct.unpack_from('>4f', raw, 16)); lo = np.array(struct.unpack_from('>3f', raw, 32)); hi = np.array(struct.unpack_from('>3f', raw, 48))
        matrix = np.array(struct.unpack_from('>16f', raw, 64)).reshape(4, 4).T; dims = np.array(struct.unpack_from('>3f', raw, 128))
        assert np.all(points[:, :3] >= lo) and np.all(points[:, :3] <= hi)
        assert np.all(np.linalg.norm(points[:, :3] - sphere[:3], axis=1) <= sphere[3])
        assert np.all(np.abs((points @ np.linalg.inv(matrix).T)[:, :3]) <= dims + .0001)


def test_exact_cli_publishes_only_new_output_with_machine_readable_receipt(fitted, tmp_path, capsys):
    f = fitted; output = tmp_path / 'new.arc'
    assert main([str(f['source_path']), '--donor-glb', str(f['donor_path']), '--expected-sha256', FILES[f['key']][1], '--out', str(output)]) == 0
    receipt = json.loads(capsys.readouterr().out)
    assert receipt['sha256'] == sha(output.read_bytes()) == sha(f['output'])
    assert receipt['donor']['source_game_id'] == f['donor']['source_game_id']
    with pytest.raises(FileExistsError):
        fit_archive(f['source_path'], f['donor_path'], output, expected_sha256=FILES[f['key']][1])
    assert output.read_bytes() == f['output']


def test_wrong_source_or_donor_never_creates_output(fitted, tmp_path):
    f = fitted; output = tmp_path / 'absent' / 'new.arc'; bad = tmp_path / 'wrong.glb'; bad.write_bytes(f['donor_bytes'] + b'changed')
    with pytest.raises(ValueError, match='donor GLB hash'):
        fit_archive(f['source_path'], bad, output, expected_sha256=FILES[f['key']][1])
    assert not output.parent.exists()
    with pytest.raises(ValueError, match='ARC source hash'):
        fit_archive(f['source_path'], f['donor_path'], output, expected_sha256='0' * 64)
    assert not output.parent.exists()


def tiny_primitive(wrap=10497, double=False):
    return dict(pos=np.array([[0., 0, 0], [1, 0, 0], [0, 1, 0]]), nrm=np.tile([0., 0, 1], (3, 1)),
                uv=np.array([[-1., 0], [2, 0], [-1, 1]]), tris=np.array([[0, 1, 2]]),
                J=np.tile([2, 3, 0, 0], (3, 1)), W=np.tile([.7, .3, 0, 0], (3, 1)),
                tex=np.array([[[255, 0, 0, 255], [0, 0, 255, 0]]], np.uint8),
                color=(255, 255, 255, 255), wrap=(wrap, 33071), double_sided=double)


@pytest.mark.parametrize('wrap', [10497, 33648, 33071])
def test_atlas_bakes_wrap_and_binary_alpha_without_dropping_weights(wrap):
    p = tiny_primitive(wrap, True); geometry, atlas, counts = atlas_geometry([p], 64)
    assert np.array_equal(geometry['joints'], np.vstack((p['J'], p['J'][::-1])))
    assert np.array_equal(geometry['weights'], np.vstack((p['W'], p['W'][::-1])))
    assert np.array_equal(geometry['normals'][3:], -p['nrm'][::-1])
    assert counts == [{'source': 1, 'back_faces_added': 1}]
    # Independently sample the authored 2-color image along the tile's row.
    coords = -1 + (np.arange(60) + .5) / 60 * 3
    if wrap == 10497: coords %= 1
    elif wrap == 33648: coords = 1 - np.abs(coords % 2 - 1)
    else: coords = np.clip(coords, 0, 1)
    expected = p['tex'][0, np.minimum((coords * 2).astype(int), 1)]
    pixels = np.asarray(atlas)
    assert np.array_equal(pixels[2, 2:62], expected)
    assert set(np.unique(pixels[:, :, 3])) <= {0, 255}
    assert np.isfinite(geometry['uv']).all() and geometry['uv'].min() > 0 and geometry['uv'].max() < 1


@pytest.mark.parametrize('change', ['tiling', 'nonfinite', 'wrap', 'influences'])
def test_unbounded_atlas_inputs_rejected(change):
    p = tiny_primitive()
    if change == 'tiling': p['uv'][0, 0] = -1000
    if change == 'nonfinite': p['uv'][0, 0] = np.nan
    if change == 'wrap': p['wrap'] = (123, 33071)
    if change == 'influences': p['J'] = np.tile(np.arange(5), (3, 1)); p['W'] = np.full((3, 5), .2)
    with pytest.raises(ValueError): atlas_geometry([p], 64)


def test_source_native_peach_joint_controls_match_full_weighted_prediction():
    from gbox.characters import _triangles
    from test_re5ps3_role_pose_evidence import point_witnesses
    root = evidence_root() / 're5-donor-fitting-v1/peach-joint-comparison-v1'
    path = root / 'independent-proof.json'
    if not path.exists(): pytest.skip('offline Peach joint-control evidence unavailable')
    proof = json.loads(path.read_text()); count = 0
    for target in proof['targets']:
        source = Path(target['source']); assert sha(source.read_bytes()) == target['source_sha256']
        with attachments.paused(): rig = R.load_rig(source, target['roles'])
        for pose in target['poses']:
            baked = Path(pose['file']); assert baked.resolve().is_relative_to(root) and sha(baked.read_bytes()) == pose['sha256']
            joint = None if pose['name'] is None else rig['names'].index(pose['name']); descendants = set() if joint is None else {joint}
            for _ in rig['parent']: descendants.update(i for i, parent in enumerate(rig['parent']) if parent in descendants)
            angle = math.radians(pose['angle_degrees']); c, s = math.cos(angle), math.sin(angle)
            rotation = np.array([[c, -s, 0], [s, c, 0], [0, 0, 1]])
            expected = []
            for primitive in rig['prims']:
                ids = np.unique(primitive['tris']); points = primitive['pos'][ids]
                mass = (primitive['W'][ids] * np.isin(primitive['J'][ids], list(descendants))).sum(1)
                rotated = (points - pose['pivot']) @ rotation.T + pose['pivot']
                expected.append(points + mass[:, None] * (rotated - points))
            expected = np.concatenate(expected); actual = np.concatenate([t[0] for t in _triangles(baked)])
            tolerance = .0002 if target['label'] == 'original' else .00001
            point_witnesses(actual, expected, tolerance=tolerance); point_witnesses(expected, actual, tolerance=tolerance)
            count += 1
    assert count == 14


def test_atlas_rejects_expanded_vertex_budget_before_any_output_allocation(monkeypatch):
    p = tiny_primitive(double=True)
    p['tris'] = np.zeros((11000, 3), dtype=int)
    def allocation(*args, **kwargs):
        raise AssertionError('output allocated before checking expanded budget')
    monkeypatch.setattr('gbox.re5ps3_fit.np.zeros', allocation)
    with pytest.raises(ValueError, match='vertex budget'):
        atlas_geometry([p], 4096)


def test_source_changed_during_fit_prevents_publication(fitted, tmp_path, monkeypatch):
    f = fitted; donor = tmp_path / 'donor.glb'; donor.write_bytes(f['donor_bytes'])
    def changed(*args, **kwargs):
        donor.write_bytes(f['donor_bytes'] + b'changed after snapshot')
        return f['output'], f['receipt']
    monkeypatch.setattr('gbox.re5ps3_fit.build_fitted_archive', changed)
    output = tmp_path / 'absent' / 'new.arc'
    with pytest.raises(ValueError, match='source changed'):
        fit_archive(f['source_path'], donor, output, expected_sha256=FILES[f['key']][1])
    assert not output.parent.exists()
