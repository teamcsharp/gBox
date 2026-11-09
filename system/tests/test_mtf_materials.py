"""Atlas pixels and remapped UVs must describe the same source appearance."""
import numpy as np
import pytest

from gbox import mtf_materials as materials
from gbox.crazy_taxi_look import atlas_uv


def test_rgba_factor_and_wrap_gutter_are_preserved_in_atlas():
    source = np.array([[[240, 80, 20, 0], [20, 180, 60, 128]],
                       [[40, 60, 220, 255], [120, 120, 120, 64]]], dtype=np.uint8)
    atlas, regions, report = materials.build_atlas(
        [{'tex': source, 'colour': (255, 255, 255, 128)}], {0: (-1, 0, 1, 1)}, size=(32, 32))
    region = regions[0]
    expected = source.copy()
    expected[..., 3] = np.rint(source[..., 3].astype(float) * 128 / 255).astype(np.uint8)
    assert np.array_equal(atlas[region.y:region.y + 2, region.x:region.x + 2], expected)
    assert np.array_equal(atlas[region.y:region.y + 2, region.x + 2:region.x + 4], expected)
    assert np.array_equal(atlas[region.y, region.x - 1], expected[0, -1])
    points = atlas_uv(region, np.array([[-.75, .25], [.25, .25]]), 32, 32)
    for u, v in points:
        assert np.array_equal(atlas[int(v * 32), int(u * 32)], expected[0, 0])
    assert report['alpha_preserved'] and report['texture_scale'] == 1


def test_flat_colour_keeps_transparency_and_distinct_material_regions():
    source = [{'colour': (10, 20, 30, 0)}, {'colour': (40, 50, 60, 255)}]
    atlas, regions, _ = materials.build_atlas(source, {0: (0, 0, 1, 1), 1: (0, 0, 1, 1)}, size=(16, 16))
    for i in range(2):
        u, v = atlas_uv(regions[i], np.array([[0.5, 0.5]]), 16, 16)[0]
        assert tuple(atlas[int(v * 16), int(u * 16)]) == source[i]['colour']


@pytest.mark.parametrize('bounds', [(float('nan'), 0, 1, 1), (2, 0, 1, 1), (0, 0, 17, 1)])
def test_invalid_or_unbounded_uv_ranges_are_refused(bounds):
    with pytest.raises(materials.MaterialError):
        materials.build_atlas([{'colour': (255, 255, 255, 255)}], {0: bounds})


def source_fixture(tmp_path, monkeypatch):
    path = tmp_path / 'source.glb'
    path.write_bytes(b'test fixture read through the existing glTF loader')
    positions = np.array([[0., 0., 0.], [1., 0., 0.], [0., 1., 0.]])
    uv = np.array([[.25, .25], [.75, .25], [.25, .75]])
    index = np.array([0, 1, 2], np.uint16)
    arrays = [positions, uv, index]
    gl = {'nodes': [{'mesh': 0}], 'meshes': [{'primitives': [
        {'attributes': {'POSITION': 0, 'TEXCOORD_0': 1}, 'indices': 2, 'material': i} for i in range(2)]}],
        'materials': [{'alphaMode': 'BLEND', 'pbrMetallicRoughness': {'baseColorTexture': {'index': 0}}},
                      {'pbrMetallicRoughness': {'baseColorFactor': [1, 0, 0, .5]}}],
        'textures': [{'source': 0}]}
    image = np.full((2, 2, 4), (0, 255, 0, 64), dtype=np.uint8)
    matrix = np.eye(4)
    matrix[0, 3] = 10
    monkeypatch.setattr(materials.characters, '_load', lambda _: (gl, lambda i: arrays[i], lambda _: image, [matrix]))
    return path, gl, arrays


def test_source_materials_remap_uvs_and_keep_world_pose_and_rgba(tmp_path, monkeypatch):
    path, _, _ = source_fixture(tmp_path, monkeypatch)
    vertices, triangles, image, report = materials.source_mesh(path, atlas_size=(32, 32))
    assert len(vertices) == 6 and len(triangles) == 2
    assert min(v['position'][0] for v in vertices) == 10
    assert report['materials'] == 2 and report['source_alpha_modes'] == ['BLEND', 'OPAQUE']
    assert report['native_materials_bound'] is False and report['live_verified'] is False
    pixels = np.asarray(image)
    for triangle, expected in zip(triangles, [(0, 255, 0, 64), (255, 0, 0, 128)]):
        for index in triangle:
            u, v = vertices[index]['uv']
            assert tuple(pixels[int(v * 32), int(u * 32)]) == expected


def test_bad_indices_and_unsupported_texture_sampling_fail_before_import(tmp_path, monkeypatch):
    path, gl, arrays = source_fixture(tmp_path, monkeypatch)
    arrays[2] = np.array([0, 1, 3], np.uint16)
    with pytest.raises(materials.MaterialError, match='indices'):
        materials.source_mesh(path)
    arrays[2] = np.array([0, 1, 2], np.uint16)
    gl['textures'][0]['sampler'] = 0
    gl['samplers'] = [{'wrapS': 33071}]
    with pytest.raises(materials.MaterialError, match='repeat'):
        materials.source_mesh(path)


def test_skin_keeps_actual_node_ids_normalized_weights_and_blended_pose(tmp_path, monkeypatch):
    path, gl, arrays = source_fixture(tmp_path, monkeypatch)
    # The skin list order differs from the scene node IDs; both weighted transforms matter.
    gl['nodes'] = [{'mesh': 0, 'skin': 0}, {}, {}]
    gl['skins'] = [{'joints': [2, 1]}]
    arrays.extend([np.array([[0, 1, 0, 0]] * 3, np.uint8), np.array([[1., 3., 0., 0.]] * 3)])
    for primitive in gl['meshes'][0]['primitives']:
        primitive['attributes'].update({'JOINTS_0': 3, 'WEIGHTS_0': 4})
    world = [np.eye(4), np.eye(4), np.eye(4)]
    world[1][0, 3], world[2][0, 3] = 4., 12.
    image = np.full((2, 2, 4), (0, 255, 0, 64), dtype=np.uint8)
    monkeypatch.setattr(materials.characters, '_load', lambda _: (gl, lambda i: arrays[i], lambda _: image, world))
    vertices, _, _, report = materials.source_mesh(path, atlas_size=(32, 32))
    assert min(v['position'][0] for v in vertices) == 6.
    assert all(v['source_joints'] == (1, 2) and v['source_weights'] == (.75, .25) for v in vertices)
    assert 'target weights not retargeted' in report['skin']
    arrays[4][0] = 0
    with pytest.raises(materials.MaterialError, match='positive influence'):
        materials.source_mesh(path)


def test_node_normals_preserve_source_smoothing_with_nonuniform_scale(tmp_path, monkeypatch):
    path, gl, arrays = source_fixture(tmp_path, monkeypatch)
    arrays.append(np.array([[1., 1., 1.]] * 3))
    for primitive in gl['meshes'][0]['primitives']:
        primitive['attributes']['NORMAL'] = 3
    matrix = np.diag([2., 3., 4., 1.])
    matrix[:3, 3] = (8., 9., 10.)
    monkeypatch.setattr(materials.characters, '_load', lambda _: (
        gl, lambda i: arrays[i], lambda _: np.full((2, 2, 4), 255, np.uint8), [matrix]))
    vertices, _, _, report = materials.source_mesh(path, atlas_size=(32, 32))
    expected = np.array([.5, 1/3, .25]); expected /= np.linalg.norm(expected)
    assert all(v['normal'] == pytest.approx(expected) for v in vertices)
    assert report['source_normal_corners'] == 6 and report['face_normal_fallback_corners'] == 0


def test_skin_normals_use_inverse_transpose_of_weighted_pose(tmp_path, monkeypatch):
    path, gl, arrays = source_fixture(tmp_path, monkeypatch)
    gl['nodes'] = [{'mesh': 0, 'skin': 0}, {}, {}]
    gl['skins'] = [{'joints': [2, 1]}]
    arrays.extend([np.array([[0, 1, 0, 0]] * 3, np.uint8),
                   np.array([[1., 3., 0., 0.]] * 3), np.array([[1., 1., 1.]] * 3)])
    for primitive in gl['meshes'][0]['primitives']:
        primitive['attributes'].update(JOINTS_0=3, WEIGHTS_0=4, NORMAL=5)
    world = [np.eye(4), np.diag([2., 1., 4., 1.]), np.diag([1., 3., 2., 1.])]
    # A translation cannot influence a normal; both skin joints must influence its linear map.
    world[1][:3, 3], world[2][:3, 3] = (5., 6., 7.), (20., 10., -3.)
    monkeypatch.setattr(materials.characters, '_load', lambda _: (
        gl, lambda i: arrays[i], lambda _: np.full((2, 2, 4), 255, np.uint8), world))
    vertices, _, _, report = materials.source_mesh(path, atlas_size=(32, 32))
    expected = 1 / np.array([1.75, 1.5, 3.5]); expected /= np.linalg.norm(expected)
    assert all(v['normal'] == pytest.approx(expected) for v in vertices)
    assert report['face_normal_fallback_corners'] == 0


def test_only_invalid_source_normals_fall_back_to_face_normal(tmp_path, monkeypatch):
    path, gl, arrays = source_fixture(tmp_path, monkeypatch)
    arrays.append(np.array([[1., 1., 1.], [0., 0., 0.], [float('nan'), 0., 1.]]))
    for primitive in gl['meshes'][0]['primitives']:
        primitive['attributes']['NORMAL'] = 3
    vertices, triangles, _, report = materials.source_mesh(path, atlas_size=(32, 32))
    for a, b, c in triangles:
        assert vertices[a]['normal'] == pytest.approx(np.ones(3) / np.sqrt(3))
        assert vertices[b]['normal'] == vertices[c]['normal'] == (0., 0., 1.)
    assert report['source_normal_corners'] == 2 and report['face_normal_fallback_corners'] == 4


def test_smooth_normals_do_not_merge_opposite_uv_tangent_handedness(tmp_path, monkeypatch):
    from gbox import mtf_author
    path, gl, arrays = source_fixture(tmp_path, monkeypatch)
    arrays[0] = np.array([[0., 0., 0.], [1., 0., 0.], [0., 1., 0.], [-1., 0., 0.]])
    arrays[1] = np.array([[0., 0.], [1., 0.], [0., 1.], [1., 0.]])
    arrays[2] = np.array([0, 1, 2, 0, 2, 3], np.uint16)
    arrays.append(np.array([[0., 0., 1.]] * 4))
    gl['meshes'][0]['primitives'] = gl['meshes'][0]['primitives'][:1]
    gl['meshes'][0]['primitives'][0]['attributes']['NORMAL'] = 3
    vertices, faces, _, report = materials.source_mesh(path, atlas_size=(32, 32))
    assert len(vertices) == 6 and len(faces) == 2
    assert vertices[faces[0][0]] == vertices[faces[1][0]]
    assert faces[0][0] != faces[1][0]
    derived = mtf_author.tangent_frames(vertices, faces)
    assert [derived[i]['tangent_sign'] for i in faces[0]] == [1., 1., 1.]
    assert [derived[i]['tangent_sign'] for i in faces[1]] == [-1., -1., -1.]
    assert report['uv_handedness_seams_preserved']
