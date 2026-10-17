"""#1638: DOA2 SUP seams are owned by the child joint and blend toward its parent on the owned disc."""
import os
import unittest

import numpy as np

from gbox.doa2_rig import PARENT
from gbox.doa2_sup_plan import fit_native_skin, native_edges, plan_seams, reversed_pairs


def primitive(influences, tris=None):
    count = len(influences)
    j, w = np.zeros((count, 4), int), np.zeros((count, 4), float)
    for i, items in enumerate(influences):
        for k, (a, b) in enumerate(items):
            j[i, k], w[i, k] = a, b
    return {'pos': np.column_stack((np.arange(count), np.zeros((count, 2)))),
            'nrm': np.tile([0., 1, 0], (count, 1)), 'uv': np.zeros((count, 2)),
            'tris': np.asarray(tris if tris is not None else [[0, 1, 2]], int),
            'J': j, 'W': w, 'logical_vertex_id': np.arange(count), 'opaque': True}


# Models of the doa2_roster_59d8ed0e AYA (Sonic) costume build report: thigh 6 owned the l_shin 7 seam.
SONIC_AYA_MODELS = [{'bone_a': 2, 'bone_bs': [0, 6, 12]}, {'bone_a': 4, 'bone_bs': [5, 8]},
                    {'bone_a': 6, 'bone_bs': [7]}, {'bone_a': 10, 'bone_bs': [11, 14]},
                    {'bone_a': 12, 'bone_bs': [13]}]


class NativeSeamDirectionTests(unittest.TestCase):
    def test_native_edges_are_child_to_parent(self):
        edges = native_edges(PARENT)
        self.assertIn((7, 6), edges)       # l_shin -> l_thigh, as stock AYA/KAS SUPs
        self.assertNotIn((6, 7), edges)
        self.assertEqual(len(edges), len(PARENT) - 1)

    def test_shipped_sonic_build_has_reversed_leg_seams(self):
        bad = reversed_pairs(SONIC_AYA_MODELS, PARENT)
        self.assertIn((6, 7), bad)
        self.assertIn((12, 13), bad)
        self.assertNotIn((4, 8), bad)

    def test_two_joint_leg_face_is_owned_by_the_shin(self):
        p = primitive([[(6, .5), (7, .5)], [(7, 1)], [(6, .25), (7, .75)]])
        fitted, report = fit_native_skin([p], parents=PARENT)
        plan = plan_seams(fitted, allowed=report['allowed'], single=report['single'])
        self.assertEqual(reversed_pairs(plan, PARENT), [])
        self.assertEqual([(m['bone_a'], m['bone_bs']) for m in plan['models']], [(7, [6])])
        self.assertEqual(report['vertices_changed'], 0)
        self.assertEqual(plan['report']['triangles'], 1)

    def test_parent_owned_face_is_refitted_without_losing_geometry(self):
        # Default planning must own this face by thigh 6 and blend toward shin 7 (a reversed pair).
        p = primitive([[(2, 31 / 32), (6, 1 / 32)], [(6, .5), (7, .5)], [(6, 1)]])
        self.assertIn((6, 7), reversed_pairs(plan_seams([p]), PARENT))
        fitted, report = fit_native_skin([p], parents=PARENT)
        plan = plan_seams(fitted, allowed=report['allowed'], single=report['single'])
        self.assertEqual(reversed_pairs(plan, PARENT), [])
        self.assertEqual(plan['report']['triangles'], 1)
        self.assertEqual(plan['report']['geometry_deleted'], 0)
        self.assertGreater(report['vertices_changed'], 0)
        self.assertIn('native_direction', report['by_reason'])

    def test_default_fit_is_unchanged_without_parents(self):
        p = primitive([[(6, .5), (7, .5)], [(7, 1)], [(6, .25), (7, .75)]])
        a = plan_seams(*[fit_native_skin([p])[0]])['report']
        b = plan_seams([p])['report']
        self.assertEqual(a, b)

    @unittest.skipUnless(os.path.exists(os.environ.get(
        'GBOX_DOA2_LE_GDI', os.path.expanduser('~/gbox-cache/dc/1de2e7634f3161ff/disc.gdi'))), 'owned DOA2 LE disc')
    def test_every_owned_body_seam_blends_toward_the_parent(self):
        from gbox.gdrom import GDRom
        from gbox import doa2_seams as S
        disc = GDRom(os.environ.get('GBOX_DOA2_LE_GDI',
                                    os.path.expanduser('~/gbox-cache/dc/1de2e7634f3161ff/disc.gdi')))
        files = disc.files() if callable(disc.files) else disc.files
        names = [n for n in files if str(n).upper().endswith('.SUP')]
        self.assertEqual(len(names), 80)
        body = [(s['bone_a'], s['bone_b']) for n in names for s in S.decode_sup(disc.read(n))
                if s['bone_a'] < len(PARENT)]
        self.assertEqual(len(body), 898)
        self.assertTrue(all(b == PARENT[a] for a, b in body))


if __name__ == '__main__':
    unittest.main()
