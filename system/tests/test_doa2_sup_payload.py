from pathlib import Path
import sys
import unittest

import numpy as np

from gbox import doa2_seams as S
from gbox.doa2_sup_payload import bind_payload, evaluate_payload, quantize_sample, symmetric_seam
from sup_test_coefficients import complementary_coefficients


def rotation_z(angle):
    c, s = np.cos(angle), np.sin(angle)
    return np.array([[c, -s, 0], [s, c, 0], [0, 0, 1.]])


class PayloadTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.coefficients = complementary_coefficients()
        cls.seam = {'bone_a': 0, 'bone_b': 1,
                    'axis_pairs': np.repeat(np.eye(3)[:, None, :], 2, axis=1),
                    'controls': np.array([[0., 0, 0], [0, 0, 0], [0, 0, 0], [0, 0, 0]])}
        cls.world = np.repeat(np.eye(4)[None], 2, axis=0)
        cls.world[0, :3, :3] = rotation_z(.37)
        cls.world[0, :3, 3] = [2, 3, -1]
        cls.world[1, :3, :3] = rotation_z(-.41)
        cls.world[1, :3, 3] = [3, 3, -1]

    def test_every_native_sample_reconstructs_bind_attributes(self):
        rng = np.random.default_rng(17)
        p, n = rng.normal(size=(17, 3)), rng.normal(size=(17, 3))
        n /= np.linalg.norm(n, axis=1)[:, None]
        result = bind_payload(self.seam, self.world, p, n, np.arange(17), self.coefficients)
        out_p, out_n = evaluate_payload(self.seam, self.world, result, self.coefficients)
        np.testing.assert_allclose(out_p, p, atol=2e-14)
        np.testing.assert_allclose(out_n, n, atol=2e-14)
        self.assertEqual(result['write_mask'].tolist(), [False] + [True] * 16)

    def test_endpoints_follow_exact_native_bones_after_motion(self):
        p = np.array([[1., 2, 3], [4, 5, 6]])
        n = np.array([[1., 0, 0], [0, 1, 0]])
        result = bind_payload(self.seam, self.world, p, n, np.array([0, 16]), self.coefficients)
        moved = self.world.copy()
        moved[0, :3, :3] = rotation_z(.9)
        moved[1, :3, :3] = rotation_z(1.3)
        moved[:, :3, 3] += [[-1, 2, 0], [3, -4, 1]]
        out_p, out_n = evaluate_payload(self.seam, moved, result, self.coefficients)
        for index in range(2):
            delta = moved[index] @ np.linalg.inv(self.world[index])
            np.testing.assert_allclose(out_p[index], delta[:3, :3] @ p[index] + delta[:3, 3], atol=2e-14)
            np.testing.assert_allclose(out_n[index], delta[:3, :3] @ n[index], atol=2e-14)

    def test_curved_normal_has_unit_length_under_bending(self):
        p, n = np.array([[.2, .3, .4]]), np.array([[1., 0, 0]])
        result = bind_payload(self.seam, self.world, p, n, np.array([8]), self.coefficients)
        moved = self.world.copy()
        moved[1, :3, :3] = rotation_z(1.5)
        _, normals = evaluate_payload(self.seam, moved, result, self.coefficients)
        self.assertAlmostEqual(np.linalg.norm(normals[0]), 1, places=13)
        # A normalized curved basis differs from raw linear blended rotation.
        local = self.world[0, :3, :3].T @ n[0]
        linear = .5 * (moved[0, :3, :3] @ local + moved[1, :3, :3] @ (self.world[1, :3, :3].T @ n[0]))
        self.assertLess(np.linalg.norm(linear), .9)

    def test_shared_logical_vertices_produce_identical_payloads(self):
        p = np.repeat(np.array([[.2, .3, .4]]), 3, axis=0)
        n = np.repeat(np.array([[0., 1, 0]]), 3, axis=0)
        result = bind_payload(self.seam, self.world, p, n, np.full(3, 9), self.coefficients)
        np.testing.assert_array_equal(result['payload_positions'][0], result['payload_positions'][2])
        np.testing.assert_array_equal(result['payload_normals'][0], result['payload_normals'][2])

    def test_quantization_preserves_endpoints_and_reports_discrete_parameter(self):
        self.assertEqual(quantize_sample(0), 0)
        self.assertEqual(quantize_sample(1), 16)
        self.assertEqual(quantize_sample(.49), 8)
        for invalid in (-.1, 1.1, np.nan):
            with self.assertRaises(ValueError):
                quantize_sample(invalid)

    def test_rejects_unverified_nonrigid_pose_and_invalid_samples(self):
        bad = self.world.copy(); bad[0, 0, :3] *= 2
        for pose, samples in ((bad, np.array([8])), (self.world, np.array([17])), (self.world, np.array([8.]))):
            with self.assertRaises(ValueError):
                bind_payload(self.seam, pose, [[0, 0, 0]], [[0, 1, 0]], samples, self.coefficients)

    def test_reversed_owner_and_complementary_samples_have_same_world_motion(self):
        a, b = symmetric_seam(self.world, 0, 1), symmetric_seam(self.world, 1, 0)
        rng = np.random.default_rng(16)
        samples = np.arange(17)
        p, n = rng.normal(size=(17, 3)), rng.normal(size=(17, 3))
        n /= np.linalg.norm(n, axis=1)[:, None]
        pa = bind_payload(a, self.world, p, n, samples, self.coefficients)
        pb = bind_payload(b, self.world, p, n, 16 - samples, self.coefficients)
        for _ in range(20):
            pose = self.world.copy()
            for joint in range(2):
                pose[joint, :3, :3] = rotation_z(rng.uniform(-1.4, 1.4))
                pose[joint, :3, 3] = rng.normal(size=3)
            ap, an = evaluate_payload(a, pose, pa, self.coefficients)
            bp, bn = evaluate_payload(b, pose, pb, self.coefficients)
            np.testing.assert_allclose(ap, bp, atol=3e-13)
            np.testing.assert_allclose(an, bn, atol=3e-13)

    def test_synthetic_fixture_has_exact_complement_symmetry(self):
        np.testing.assert_array_equal(self.coefficients[0], [1, 0, 0])
        for sample in range(1, 16):
            ca, cb, cm = self.coefficients[sample]
            np.testing.assert_array_equal(self.coefficients[16 - sample], [cb, ca, cm])


if __name__ == '__main__':
    unittest.main()
