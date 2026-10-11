import unittest
import numpy as np
from gbox.doa2_sup_plan import plan_seams,canonical_vertices


def primitive(influences, tris=None, ids=None, opaque=True):
    count=len(influences)
    j,w=np.zeros((count,4),int),np.zeros((count,4),float)
    for i,items in enumerate(influences):
        for k,(a,b) in enumerate(items):j[i,k],w[i,k]=a,b
    return {'pos':np.column_stack((np.arange(count),np.zeros((count,2)))),
            'nrm':np.tile([0.,1,0],(count,1)),'uv':np.zeros((count,2)),
            'tris':np.asarray(tris if tris is not None else [[0,1,2]],int),
            'J':j,'W':w,'logical_vertex_id':np.arange(count) if ids is None else np.asarray(ids),
            'opaque':opaque}


class NativeSeamPlannerTests(unittest.TestCase):
    def test_three_joint_face_preserves_triangle_and_two_curves(self):
        p=primitive([[(2,.5),(6,.5)],[(2,.75),(12,.25)],[(2,1)]])
        plan=plan_seams([p]);m=plan['models'][0];c=m['chunks'][0]
        self.assertEqual(m['bone_a'],2);self.assertEqual(m['bone_bs'],[6,12])
        self.assertEqual(c['sup_sample'].tolist(),[8,4,0])
        self.assertEqual(c['sup_bone_b'].tolist(),[6,12,-1])
        np.testing.assert_array_equal(c['tris'],p['tris'])
        self.assertEqual(plan['report']['geometry_deleted'],0)

    def test_canonical_half_tie_is_complemented_not_requantized(self):
        p=primitive([[(2,31/32),(6,1/32)],[(2,.5),(6,.5)],[(6,1)]])
        # Force reversed owner6 with a second pair6/7 in the same triangle.
        p['J'][1,:2]=[6,7];p['W'][1,:2]=[.5,.5]
        plan=plan_seams([p]);c=plan['models'][0]['chunks'][0]
        self.assertEqual(plan['models'][0]['bone_a'],6)
        self.assertEqual(c['sup_sample'][0],15)
        self.assertEqual(c['canonical_sample'][0],1)

    def test_endpoint_quantization_does_not_delete_cross_joint_face(self):
        p=primitive([[(2,.02),(6,.98)],[(2,.02),(12,.98)],[(2,1)]])
        plan=plan_seams([p])
        self.assertEqual(plan['report']['triangles'],1)
        self.assertEqual(plan['report']['endpoint_snapped_logical_vertices'],2)
        self.assertEqual(plan['report']['native_descriptors'],2)

    def test_transparent_pair_is_not_repeated_with_opaque_model(self):
        opaque=primitive([[(2,.5),(6,.5)],[(2,.5),(12,.5)],[(2,1)]])
        transparent=primitive([[(2,.5),(6,.5)],[(2,1)],[(6,1)]],ids=[3,4,5],opaque=False)
        plan=plan_seams([opaque,transparent])
        self.assertEqual(len(plan['models']),2)
        self.assertEqual([m['draw_count'] for m in plan['models']],[2,1])
        self.assertEqual(plan['report']['transparent_repeated_models'],0)

    def test_transparent_three_joint_face_is_explicitly_unsupported(self):
        p=primitive([[(2,.5),(6,.5)],[(2,.5),(12,.5)],[(2,1)]],opaque=False)
        with self.assertRaisesRegex(ValueError,'transparent'):plan_seams([p])

    def test_shared_logical_position_and_weight_mismatch_rejected(self):
        a=primitive([[(2,.5),(6,.5)],[(2,1)],[(6,1)]])
        b={k:v.copy() if isinstance(v,np.ndarray) else v for k,v in a.items()}
        b['W'][0,:2]=[.4,.6]
        with self.assertRaisesRegex(ValueError,'inconsistent'):canonical_vertices([a,b])
        b['W'][0,:2]=[.5,.5];b['pos'][0,0]+=.01
        with self.assertRaisesRegex(ValueError,'inconsistent'):canonical_vertices([a,b])

    def test_more_than_two_influences_requires_explicit_policy(self):
        p=primitive([[(0,.3),(2,.3),(6,.4)],[(2,1)],[(6,1)]])
        with self.assertRaisesRegex(ValueError,'explicit reduction'):plan_seams([p])

    def test_disjoint_pair_face_and_native_capacity_rejected(self):
        p=primitive([[(0,.5),(2,.5)],[(6,.5),(7,.5)],[(2,1)]])
        with self.assertRaisesRegex(ValueError,'no common owner'):plan_seams([p])
        p=primitive([[(2,.5),(6,.5)],[(2,.5),(12,.5)],[(2,1)]])
        with self.assertRaisesRegex(ValueError,'exceeding1'):plan_seams([p],maximum_seams=1)


if __name__=='__main__':unittest.main()
