from pathlib import Path
import collections
import struct
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[3]))
from gbox import doa2_geometry as G
from gbox.doa2_strip_encode import stripify,encode_model,_strip_faces,_cyclic


def archive(model):
    table=24+len(model)+8
    return struct.pack('<6I',24,table,table+4,1,0,0)+model+bytes(8)+struct.pack('<I',0x0c010000)


def material(shader):
    header=bytearray(80)
    struct.pack_into('<4I',header,0,0x808c003e,0x80000000,0,0)
    struct.pack_into('<ii',header,32,0,shader)
    struct.pack_into('<I',header,40,0x3f800001)
    return bytes(header)


class StripTests(unittest.TestCase):
    def test_quad_uses_one_strip_with_original_winding(self):
        faces=[(0,1,2),(2,1,3)]
        strips=stripify(faces)
        self.assertEqual(len(strips),1)
        self.assertEqual(len(strips[0]),4)
        self.assertEqual(collections.Counter(map(_cyclic,_strip_faces(strips[0]))),collections.Counter(map(_cyclic,faces)))

    def test_grid_multiplicity_and_winding_are_preserved(self):
        faces=[]
        for y in range(11):
            for x in range(15):
                a=y*16+x;b=a+1;c=a+16;d=c+1
                faces.extend([(a,b,c),(c,b,d)])
        faces.extend([faces[17],tuple(reversed(faces[30]))])
        strips=stripify(faces)
        self.assertEqual(collections.Counter(_cyclic(t) for strip in strips for t in _strip_faces(strip)),
                         collections.Counter(map(_cyclic,faces)))
        self.assertLess(sum(map(len,strips)),len(faces)*2)

    def test_native_decode_all_supported_shaders_and_reference_modes(self):
        verts=[(0.,0.,0.,0.,0.,1.,0.,0.),(1.,0.,0.,0.,0.,1.,1.,0.),
               (0.,1.,0.,0.,0.,1.,0.,1.),(1.,1.,0.,0.,0.,1.,1.,1.)]
        faces=[(0,1,2),(2,1,3),(0,1,2)]
        for shader in (-1,0,1):
            for references in (False,True):
                h=bytearray(material(shader))
                if shader==-1:struct.pack_into('<I',h,0,0x808c000e)
                m={'vertices':verts,'triangles':faces,'header':bytes(h),'texture_id':0}
                template={'global_flags':(1,0)}
                result=G.decode_chr(archive(encode_model(template,[m],references=references)))['models'][0]
                baseline=G.decode_chr(archive(G.encode_model(template,[m],references=references)))['models'][0]
                def triangles(model):
                    mesh=model['meshes'][0]
                    return collections.Counter(_cyclic(tuple(tuple(mesh['vertices'][v]) for v in t)) for t in mesh['triangles'])
                self.assertEqual(triangles(result),triangles(baseline))
                mesh=result['meshes'][0]
                self.assertTrue(all(not s['flags']&8 and s['flags']&0x10 and s['flags']&3==1 for s in mesh['strips']))
                self.assertEqual(mesh['shader'],shader)
                self.assertEqual(any(r['reference'] for r in mesh['records']),references)
                dma=0;registered={}
                for strip in mesh['strips']:
                    if not strip['flags']&0x80:dma+=32
                    for record in mesh['records'][strip['records_start']:strip['records_start']+strip['records_count']]:
                        if record['reference']:
                            tag,ram_delta=struct.unpack('<Ii',record['raw'])
                            target=record['offset']+8+ram_delta
                            self.assertEqual(tag,0x60000000-(dma-registered[target]))
                        else:registered[record['offset']]=dma
                        dma+=32
                for record in mesh['records']:
                    if not record['reference']:
                        self.assertTrue(struct.unpack_from('<I',record['raw'],0)[0]&1)
                        self.assertTrue(struct.unpack_from('<I',record['raw'],28)[0]&1)
                if shader>=0:
                    self.assertEqual((struct.unpack_from('<I',mesh['header'],0)[0]>>4)&3,2)
                    self.assertEqual(struct.unpack_from('<I',mesh['header'],40)[0]&1,0)

    def test_degenerate_placeholder_stays_native_drawable(self):
        v=(0.,0.,0.,0.,1.,0.,0.,0.)
        result=encode_model({'global_flags':(1,0)},[{'header':material(1),'vertices':[v],'triangles':[(0,0,0)]}])
        model=G.decode_chr(archive(result))['models'][0]
        self.assertEqual(model['vertex_count'],3)
        self.assertEqual(model['meshes'][0]['triangles'],[])
        self.assertEqual(len(model['meshes'][0]['records']),3)

    def test_invalid_input_rejected(self):
        for faces in ([(0,1)],[(0,1,2.5)]):
            with self.assertRaises(ValueError):stripify(faces)

    def test_known_native_strip_culling_rotates_winding(self):
        self.assertEqual(G._triangles(0x72,[0,1,2,3]),[(1,0,2),(1,2,3)])
        self.assertEqual(G._triangles(0x71,[0,1,2,3]),[(0,1,2),(2,1,3)])

    def test_transparent_face_sequence_is_retained(self):
        faces=[(0,1,2),(7,8,9),(2,1,3),(9,8,10),(3,1,4)]
        strips=stripify(faces,preserve_order=True)
        self.assertEqual([_cyclic(t) for strip in strips for t in _strip_faces(strip)],list(map(_cyclic,faces)))


if __name__=='__main__':unittest.main()
