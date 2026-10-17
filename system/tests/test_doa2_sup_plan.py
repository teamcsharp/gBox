import unittest
import numpy as np
from gbox.doa2_sup_plan import plan_seams,canonical_vertices,fit_native_skin


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

    def test_single_pair_model_holds_opaque_and_transparent_faces_once(self):
        opaque=primitive([[(2,.5),(6,.5)],[(2,1)],[(6,1)]])
        transparent=primitive([[(2,.25),(6,.75)],[(2,1)],[(6,1)]],ids=[3,4,5],opaque=False)
        plan=plan_seams([opaque,transparent])
        self.assertEqual([(m['bone_a'],m['bone_bs'],m['draw_count'],m['opaque']) for m in plan['models']],
                         [(2,[6],1,False)])
        self.assertEqual(plan['report']['native_descriptors'],1)


def plan_fitted(primitives, **kw):
    fitted,report=fit_native_skin(primitives,**kw)
    return fitted,report,plan_seams(fitted,allowed=report['allowed'],single=report['single'],**kw)


class NativeSkinFitTests(unittest.TestCase):
    # Dr. Eggman's glasses (DOA2 BAS, cast swap 2026-10-13): one transparent triangle whose blended corners span
    # chest0 with hip2 and with r_upper14 - native SUP would have to draw the blended surface once per pair.
    EGGMAN=[[(0,.69),(2,.31)],[(0,.69),(14,.31)],[(14,1)]]

    def test_transparent_two_bone_triangle_failure_is_reproduced_then_fitted(self):
        p=primitive(self.EGGMAN,opaque=False)
        with self.assertRaisesRegex(ValueError,'weighted triangle requires unsupported transparent repeated drawing'):
            plan_seams([p])
        fitted,report,plan=plan_fitted([p])
        # Only the lightest influence moved: hip 0.31 folds onto chest, the face keeps the chest/r_upper pair.
        self.assertEqual(fitted[0]['J'][0,0],0);self.assertEqual(fitted[0]['W'][0].tolist(),[1,0,0,0])
        np.testing.assert_array_equal(fitted[0]['J'][1:],p['J'][1:])
        np.testing.assert_array_equal(fitted[0]['W'][1:],p['W'][1:])
        self.assertEqual(report['vertices_changed'],1);self.assertEqual(report['triangles_changed'],1)
        self.assertEqual(report['by_reason'],{'transparent_single_pair':1})
        self.assertAlmostEqual(report['max_weight_moved'],.31)
        self.assertEqual(report['rigid_reassigned'],0)
        self.assertEqual([(m['bone_bs'],m['draw_count'],m['opaque']) for m in plan['models']],[([14],1,False)])
        self.assertEqual(plan['report']['triangles'],1);self.assertEqual(plan['report']['geometry_deleted'],0)
        np.testing.assert_array_equal(p['W'][0,:2],[.69,.31])          # the caller's arrays are untouched

    def test_fit_rewrites_a_shared_corner_in_every_primitive(self):
        transparent=primitive(self.EGGMAN,opaque=False)
        opaque=primitive([[(0,.69),(2,.31)],[(2,1)],[(0,1)]],ids=[0,7,8])
        fitted,report,plan=plan_fitted([opaque,transparent])
        self.assertEqual(fitted[0]['W'][0].tolist(),fitted[1]['W'][0].tolist())
        self.assertEqual(report['primitives'][0]['triangles'],1);self.assertEqual(report['primitives'][1]['triangles'],1)
        self.assertEqual(plan['report']['triangles'],2)

    def test_transparent_rigid_three_joint_face_follows_one_pair(self):
        p=primitive([[(2,1)],[(6,1)],[(12,1)]],opaque=False)
        fitted,report,plan=plan_fitted([p])
        self.assertEqual(report['rigid_reassigned'],1)
        self.assertEqual(plan['report']['native_descriptors'],1)
        self.assertTrue(all(m['draw_count']==1 for m in plan['models']))

    def test_opaque_face_without_common_owner_is_fitted(self):
        p=primitive([[(0,.4),(2,.6)],[(6,.5),(7,.5)],[(2,1)]])
        fitted,report,plan=plan_fitted([p])
        self.assertEqual(report['by_reason'],{'common_owner':1})
        self.assertAlmostEqual(report['max_weight_moved'],.4)

    def test_descriptor_limit_is_met_by_the_lightest_snap(self):
        p=primitive([[(2,.5),(6,.5)],[(2,.75),(12,.25)],[(2,1)]])
        fitted,report,plan=plan_fitted([p],maximum_seams=1)
        self.assertEqual(plan['report']['native_descriptors'],1)
        self.assertEqual(report['by_reason'],{'descriptor_limit':1})
        self.assertAlmostEqual(report['max_weight_moved'],.25)
        self.assertEqual((report['descriptors_before'],report['descriptors']),(2,1))

    def test_drawable_skin_is_returned_unchanged(self):
        p=primitive([[(2,.5),(6,.5)],[(2,.75),(12,.25)],[(2,1)]])
        fitted,report,plan=plan_fitted([p])
        self.assertEqual(report['vertices_changed'],0);self.assertEqual(report['triangles_changed'],0)
        np.testing.assert_array_equal(fitted[0]['W'],p['W'])
        self.assertEqual(plan['report']['native_descriptors'],2)


if __name__=='__main__':unittest.main()
