"""Source-only native SUP regressions; fixtures contain no game-owned bytes."""
import copy,struct,unittest
import numpy as np
from gbox import doa2_geometry as G,doa2_seams as S
try:
    from gbox import doa2_sup_writer as W
except ImportError:
    import doa2_sup_writer as W


def synthetic_chr():
    header=bytearray(80)
    struct.pack_into('<4I',header,0,0x8000002c,0x83000000,0,0)
    struct.pack_into('<2i',header,32,0,1)
    vertices=[(0.,0.,0.,0.,1.,0.,0.,0.),(1.,0.,0.,0.,1.,0.,1.,0.),
              (0.,1.,0.,0.,1.,0.,0.,1.),(1.,1.,0.,0.,1.,0.,1.,1.)]
    model=G.encode_model({'global_flags':(1,0)},[{'header':bytes(header),'vertices':vertices,
                                                'triangles':[(0,1,2),(0,2,3)]}])
    table=24+len(model)+8
    result=struct.pack('<6I',24,table,table+4,1,1,0)+model+b'\0'*8
    return result+struct.pack('<4I',0x0c000000,0,0,0)


def seam(groups,model=0):
    return {'bone_a':2,'bone_b':6,'model_id':model,'initialized':0,
            'axis_pairs':np.repeat(np.eye(3)[:,None,:],2,axis=1),
            'controls':np.zeros((4,3)),'groups':groups}


class PortableNativeSupWriterTests(unittest.TestCase):
    def setUp(self):
        self.chr=synthetic_chr();self.model=G.decode_chr(self.chr)['models'][0]
        self.keys=[(mi,r['vertex']) for mi,m in enumerate(self.model['meshes'])
                   for r in m['records'] if not r['reference']]
        self.payloads={key:{'sample':16 if i<2 else 8,'position':[1.,2.,3.],
                            'normal':[0.,1.,0.]} for i,key in enumerate(self.keys)}

    def test_direct_b_and_curve_aliases_preserve_payloads_and_mutable_targets(self):
        groups=W.groups_for_model(self.model,self.payloads)
        result=W.encode_sup([seam(groups)],chr_data=self.chr)
        parsed=S.decode_sup(result)[0]
        self.assertEqual([(g['sample'],len(g['vertices'])) for g in parsed['groups']],[(16,2),(8,2)])
        self.assertEqual(sum(v['alias'] for g in parsed['groups'] for v in g['vertices']),2)
        for group in parsed['groups']:
            np.testing.assert_array_equal(group['vertices'][0]['position'],[1.,2.,3.])
            np.testing.assert_array_equal(group['vertices'][0]['normal'],[0.,1.,0.])
        inline={r['offset']-self.model['offset'] for m in self.model['meshes']
                for r in m['records'] if not r['reference']}
        self.assertEqual({v['offset'] for g in parsed['groups'] for v in g['vertices']},inline)

    def test_sample_zero_is_unwritten_and_native_initial_group_is_still_present(self):
        payloads={key:{**row,'sample':0} for key,row in self.payloads.items()}
        groups=W.groups_for_model(self.model,payloads)
        self.assertEqual(groups,[{'sample':16,'vertices':[]}])
        parsed=S.decode_sup(W.encode_sup([seam(groups)],chr_data=self.chr))[0]
        self.assertEqual(parsed['initialized'],0)
        self.assertEqual(parsed['bone_a'],2);self.assertEqual(parsed['bone_b'],6)
        self.assertEqual(parsed['groups'],groups)

    def test_fourteen_handles_fit_with_sentinel_and_fifteenth_is_rejected(self):
        empty=[{'sample':16,'vertices':[]}]
        result=W.encode_sup([seam(empty,model=i) for i in range(14)])
        self.assertEqual(len(S.decode_sup(result)),14)
        self.assertEqual(struct.unpack_from('<I',result,14*4)[0],0)
        with self.assertRaisesRegex(ValueError,'14'):W.encode_sup([seam(empty,model=i) for i in range(15)])

    def test_invalid_signed_model_joint_and_allocation_fields_reject(self):
        groups=W.groups_for_model(self.model,self.payloads)
        for fields in ({'model_id':128},{'model_id':-1},{'bone_a':44},{'bone_b':2}):
            with self.assertRaises(ValueError):W.encode_sup([{**seam(groups),**fields}])
        result=W.encode_sup([seam(groups)],chr_data=self.chr)
        with self.assertRaisesRegex(ValueError,'allocation'):
            W.encode_sup([seam(groups)],chr_data=self.chr,maximum_bytes=len(result)-1)

    def test_compact_references_and_middle_of_inline_vertex_are_not_write_targets(self):
        reference=next(r for m in self.model['meshes'] for r in m['records'] if r['reference'])
        inline=next(r for m in self.model['meshes'] for r in m['records'] if not r['reference'])
        for target in (reference['offset']-self.model['offset'],inline['offset']-self.model['offset']+4):
            groups=W.groups_for_model(self.model,self.payloads)
            groups[0]['vertices'][0]['offset']=target
            with self.assertRaisesRegex(ValueError,'inline'):W.encode_sup([seam(groups)],chr_data=self.chr)

    def test_packed_normals_reject_in_both_model_mapping_and_final_chr_validation(self):
        bad=bytearray(self.chr)
        struct.pack_into('<i',bad,self.model['meshes'][0]['offset']+36,-3)
        model=G.decode_chr(bytes(bad))['models'][0]
        with self.assertRaisesRegex(ValueError,'packed-normal'):W.groups_for_model(model,self.payloads)
        with self.assertRaisesRegex(ValueError,'packed normals'):
            W.encode_sup([seam(W.groups_for_model(self.model,self.payloads))],chr_data=bytes(bad))

    def test_alias_first_duplicate_writes_and_nonfinite_payload_reject(self):
        groups=W.groups_for_model(self.model,self.payloads)
        bad=copy.deepcopy(groups);bad[0]['vertices'][0]['alias']=True
        with self.assertRaisesRegex(ValueError,'precedes'):W.encode_sup([seam(bad)])
        bad=copy.deepcopy(groups);bad[1]['vertices'][0]['offset']=bad[0]['vertices'][0]['offset']
        with self.assertRaisesRegex(ValueError,'more than once'):W.encode_sup([seam(bad)])
        bad=copy.deepcopy(groups);bad[0]['vertices'][0]['position']=[float('nan'),0,0]
        with self.assertRaisesRegex(ValueError,'finite'):W.encode_sup([seam(bad)])

    def test_missing_or_duplicate_native_sample_groups_reject(self):
        with self.assertRaisesRegex(ValueError,'initial'):
            W.encode_sup([seam([{'sample':8,'vertices':[]}])])
        with self.assertRaisesRegex(ValueError,'repeated'):
            W.encode_sup([seam([{'sample':16,'vertices':[]},{'sample':16,'vertices':[]}])])


if __name__=='__main__':unittest.main()
