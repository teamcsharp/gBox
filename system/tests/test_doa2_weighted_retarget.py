from pathlib import Path
import base64
import json
import sys
import tempfile
import unittest

import numpy as np

from gbox.melee_models import write_gltf
from gbox.doa2_weighted_retarget import _LogicalVertices, _merge, load_rig, retarget, read_rigged
from gbox.sm64_swap import write_rigged


NAMES = ['hip', 'chest', 'head', 'l_upper', 'l_fore', 'l_hand', 'r_upper', 'r_fore', 'r_hand', 'l_clav']
POSITIONS = np.array([[0, 1., 0], [0, 1.5, 0], [0, 2, 0], [.5, 1.5, 0], [1., 1.5, 0], [1.5, 1.5, 0],
                      [-.5, 1.5, 0], [-1., 1.5, 0], [-1.5, 1.5, 0], [.3, 1.5, 0]])
PARENTS = [-1, 0, 1, 9, 3, 4, 1, 6, 7, 1]


def rig():
    p = np.array([[0, 0, 0], [.1, .1, 0], [-.1, .1, 0], [0, 1.8, 0], [.1, 2, 0], [-.1, 2.1, 0],
                  [1.2, 1.4, 0], [1.2, 1.5, .1], [1.2, 1.6, 0], [1.2, 1.4, 0], [1.2, 1.5, .1], [1.2, 1.6, 0],
                  [.2, .6, 0], [.2, .8, 0], [.2, .9, 0]])
    j, w = np.zeros((len(p), 4), int), np.zeros((len(p), 4))
    j[:, 0] = [0, 0, 0, 2, 2, 2, 4, 4, 4, 4, 4, 4, 0, 0, 0]; w[:, 0] = 1
    j[6:12, :2] = [4, 5]; w[6:12, :2] = [.6, .4]
    primitive = {'pos': p, 'nrm': np.tile([0., 0, 1], (len(p), 1)), 'uv': np.zeros((len(p), 2)),
                 'tris': np.arange(len(p)).reshape(-1, 3), 'J': j, 'W': w, 'owner': j[:, 0],
                 'tex': np.array([[[11, 22, 33, 123]]], np.uint8), 'color': (100, 150, 200, 128),
                 'wrap': (33071, 33648), 'source_mesh_node': 10}
    return {'joints': POSITIONS.copy(), 'parent': PARENTS[:], 'roles': {n: i for i, n in enumerate(NAMES)},
            'names': NAMES[:], 'prims': [primitive]}


def target():
    jmap = {name: index for index, name in enumerate(NAMES) if name != 'l_clav'}
    return {'T': POSITIONS * 1.3, 'jmap': jmap, 'ground': 0., 'head_h': .4}


class WeightedTests(unittest.TestCase):
    def test_rounded_bucket_does_not_weld_distinct_fitted_positions_or_weights(self):
        logical = _LogicalVertices()
        first = logical.add('same rounded source', np.array([0., 1., 0.]), [4, 5], [.6, .4])
        shared = logical.add('same rounded source', np.array([0., 1., 0.]), [5, 4], [.4, .6])
        offset = logical.add('same rounded source', np.array([0., 1. + 2e-8, 0.]), [4, 5], [.6, .4])
        weighted = logical.add('same rounded source', np.array([0., 1., 0.]), [4, 5], [.6 + 2e-10, .4 - 2e-10])
        self.assertEqual(first, shared)
        self.assertNotEqual(first, offset)
        self.assertNotEqual(first, weighted)

    def test_joint_alias_weights_merge_without_dropping_mass(self):
        j, w = _merge([[2, 1, 2, 4]], [[.2, .3, .4, .1]])
        np.testing.assert_array_equal(j[0], [2, 1, 4, 0])
        np.testing.assert_allclose(w[0], [.6, .3, .1, 0])

    def test_actual_gltf_loader_preserves_blend_and_sampler_alpha(self):
        source = rig()
        joints = []
        for parent, position in zip(PARENTS, POSITIONS):
            world = np.eye(4); world[:3, 3] = position
            joints.append({'parent': parent, 'world': world})
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'donor.gltf'
            write_gltf(path, joints, source['prims'], joint_names=NAMES)
            gl = json.loads(path.read_text())
            # Deliberately move the second influencing joint after bind creation.
            # A complete skin evaluates the .4 weight; strongest-owner loading does not.
            gl['nodes'][5]['translation'][2] += 2
            path.write_text(json.dumps(gl))
            loaded = load_rig(path, {name: name for name in NAMES})
        primitive = loaded['prims'][0]
        np.testing.assert_allclose(primitive['W'][6], [.6, .4, 0, 0], atol=1e-7)
        np.testing.assert_allclose(primitive['pos'][6], source['prims'][0]['pos'][6] + [0, 0, .8], atol=2e-7)
        self.assertEqual(primitive['wrap'], (33071, 33648))
        np.testing.assert_array_equal(primitive['tex'][0, 0], [11, 22, 33, 123])
        self.assertEqual(primitive['color'], (100, 150, 200, 128))

    def test_retarget_preserves_weights_and_identifies_shared_uv_vertices(self):
        source = rig()
        source['prims'][0]['uv'][9:12] = 1
        out, report = retarget(source, target())
        np.testing.assert_allclose(out[0]['W'][6:12, :2], [.6, .4] * np.ones((6, 1)))
        np.testing.assert_array_equal(out[0]['J'][6:12, :2], np.tile([4, 5], (6, 1)))
        np.testing.assert_array_equal(out[0]['logical_vertex_id'][6:9], out[0]['logical_vertex_id'][9:12])
        np.testing.assert_allclose(out[0]['pos'][6:9], out[0]['pos'][9:12], atol=1e-14)
        self.assertEqual(report['blended_vertices'], 6)
        self.assertEqual(report['max_influences'], 2)
        self.assertEqual(report['logical_vertices'], 12)
        self.assertEqual(len(out[0]['tris']), 5)

    def test_role_aliases_collapse_to_native_ancestor_without_losing_weights(self):
        source = rig()
        source['prims'][0]['J'][12, :2] = [9, 1]
        source['prims'][0]['W'][12, :2] = [.3, .7]
        out, _ = retarget(source, target())
        self.assertEqual(out[0]['J'][12, 0], 1)
        np.testing.assert_allclose(out[0]['W'][12], [1, 0, 0, 0])

    def test_weight_crossing_does_not_create_position_step(self):
        first, second = rig(), rig()
        first['prims'][0]['W'][6:12, :2] = [.50001, .49999]
        second['prims'][0]['W'][6:12, :2] = [.49999, .50001]
        # Owner is used only for common fitting estimates, held steady here.
        a, _ = retarget(first, target()); b, _ = retarget(second, target())
        self.assertLess(np.max(np.abs(a[0]['pos'][6:12] - b[0]['pos'][6:12])), .0001)

    def test_rejects_negative_or_zero_total_weight(self):
        for weights in ([[1, -.1]], [[0, 0]]):
            with self.assertRaises(ValueError):
                _merge([[0, 1]], weights)

    def test_lod_intermediate_roundtrip_preserves_weighted_joint_ids(self):
        source = rig()
        t = target(); t['joints'] = len(POSITIONS); t['parent'] = PARENTS
        primitives, _ = retarget(source, t)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'lod_source.gltf'
            write_rigged(primitives, t, path, 'weighted-donor')
            recovered = read_rigged(path, t['jmap'])
        np.testing.assert_allclose(recovered[0]['pos'], primitives[0]['pos'], atol=3e-7)
        np.testing.assert_array_equal(recovered[0]['J'], primitives[0]['J'])
        np.testing.assert_allclose(recovered[0]['W'], primitives[0]['W'], atol=1e-7)
        self.assertEqual(recovered[0]['wrap'], primitives[0]['wrap'])
        np.testing.assert_array_equal(recovered[0]['logical_vertex_id'][6:9], recovered[0]['logical_vertex_id'][9:12])

    def test_second_gltf_influence_set_is_preserved_without_silent_truncation(self):
        source = rig()
        joints = []
        for parent, position in zip(PARENTS, POSITIONS):
            world = np.eye(4); world[:3, 3] = position
            joints.append({'parent': parent, 'world': world})
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'eight_influences.gltf'
            write_gltf(path, joints, source['prims'], joint_names=NAMES)
            gl = json.loads(path.read_text())
            blob = bytearray(base64.b64decode(gl['buffers'][0]['uri'].split(',', 1)[1]))
            def append(array, component):
                while len(blob) % 4:
                    blob.append(0)
                offset = len(blob); blob.extend(array.tobytes())
                view = len(gl['bufferViews'])
                gl['bufferViews'].append({'buffer': 0, 'byteOffset': offset, 'byteLength': array.nbytes})
                accessor = len(gl['accessors'])
                gl['accessors'].append({'bufferView': view, 'componentType': component, 'count': len(array), 'type': 'VEC4'})
                return accessor
            attributes = gl['meshes'][0]['primitives'][0]['attributes']
            attributes['JOINTS_1'] = append(np.tile([0, 2, 6, 7], (15, 1)).astype(np.uint16), 5123)
            attributes['WEIGHTS_1'] = append(np.tile([.1, .2, .3, .4], (15, 1)).astype(np.float32), 5126)
            gl['buffers'][0].update(byteLength=len(blob), uri='data:application/octet-stream;base64,' + base64.b64encode(blob).decode())
            path.write_text(json.dumps(gl))
            loaded = load_rig(path, {name: name for name in NAMES})
        self.assertEqual(loaded['prims'][0]['J'].shape, (15, 8))
        vertex = loaded['prims'][0]
        self.assertEqual(np.count_nonzero(vertex['W'][6]), 6)
        actual = {int(j): float(w) for j, w in zip(vertex['J'][6], vertex['W'][6]) if w > 0}
        for joint, expected in {4: .3, 5: .2, 0: .05, 2: .1, 6: .15, 7: .2}.items():
            self.assertAlmostEqual(actual[joint], expected, places=7)
        np.testing.assert_allclose(vertex['pos'], source['prims'][0]['pos'], atol=3e-7)


if __name__ == '__main__':
    unittest.main()
