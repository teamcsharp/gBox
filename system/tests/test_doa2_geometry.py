import math
import struct
import unittest

from gbox import doa2_geometry as geometry


def material():
    out = bytearray(80)
    struct.pack_into('<4I', out, 0, 0x8000002c, 0x83000000, 0x20282452, 0x4c000000)
    struct.pack_into('<4f', out, 16, 0, 0, 0, 1)
    struct.pack_into('<ii', out, 32, 0, 1)
    struct.pack_into('<9f', out, 40, .75, 1, 1, 1, 1, 0, .2, .2, .2)
    return bytes(out)


def quad():
    return {'header': material(), 'vertices': [(0, 0, 0, 0, 0, 1, 0, 0),
        (1, 0, 0, 0, 0, 1, 1, 0), (1, 1, 0, 0, 0, 1, 1, -1),
        (0, 1, 0, 0, 0, 1, 0, -1)], 'triangles': [(0, 1, 2), (0, 2, 3)]}


def archive(model_count=2):
    models = [geometry.encode_model({'global_flags': (1, 1)}, [quad()]) for _ in range(model_count)]
    data = bytearray(24)
    ptrs = []
    for model in models:
        ptrs.append(0x0c300000+len(data)-24)
        data.extend(model)
    data.extend(bytes(8))
    table = len(data)
    data.extend(struct.pack('<%dI' % model_count, *ptrs))
    texture_table = len(data)
    data.extend(struct.pack('<3I', 8192, 0x08000000, 0x0c300000))
    struct.pack_into('<6I', data, 0, 24, table, texture_table, model_count, 1, 0)
    return bytes(data)


class TestGeometry(unittest.TestCase):
    def test_native_reference_pair_and_triangle_attributes(self):
        a = geometry.decode_chr(archive())
        m = a['models'][0]['meshes'][0]
        self.assertEqual(len(m['vertices']), 4)
        self.assertEqual(m['triangles'], [(0, 1, 2), (0, 2, 3)])
        refs = [r for r in m['records'] if r['reference']]
        self.assertEqual(len(refs), 2)
        self.assertEqual(struct.unpack('<Ii', refs[0]['raw']), (0x5fffffa0, -104))
        self.assertEqual(struct.unpack('<Ii', refs[1]['raw']), (0x5fffffc0, -48))

    def test_identity_field_and_vertex_serialization(self):
        data = archive()
        self.assertEqual(geometry.roundtrip_chr(geometry.decode_chr(data)), data)
        self.assertEqual(geometry.replace_models(data, {}), data)

    def test_larger_model_relocates_tables_and_next_model_pointers(self):
        data = archive()
        orig = geometry.decode_chr(data)
        old = orig['models'][0]
        bigger = geometry.encode_model(old, [quad(), quad()])
        new = geometry.decode_chr(geometry.replace_models(data, {0: bigger}))
        self.assertEqual(len(new['models'][0]['meshes']), 2)
        self.assertGreater(new['model_table_offset'], orig['model_table_offset'])
        self.assertEqual(new['models'][1]['offset']-orig['models'][1]['offset'],
                         len(bigger)-(old['end_offset']-old['offset']))
        self.assertEqual(new['textures'], orig['textures'])

    def test_budget_rejection(self):
        data = archive()
        with self.assertRaisesRegex(ValueError, 'budget exceeded'):
            geometry.replace_models(data, {}, size_budget=len(data)-1)

    def test_reference_to_header_or_future_rejected(self):
        data = bytearray(archive())
        orig = geometry.decode_chr(data)
        ref = next(r for r in orig['models'][0]['meshes'][0]['records'] if r['reference'])
        struct.pack_into('<i', data, ref['offset']+4, 0)
        with self.assertRaisesRegex(ValueError, 'reference misses'):
            geometry.decode_chr(data)

    def test_declared_count_corruption_rejected(self):
        data = bytearray(archive())
        model = geometry.decode_chr(data)['models'][0]
        struct.pack_into('<I', data, model['end_offset']-4, 7)
        with self.assertRaisesRegex(ValueError, 'vertex count'):
            geometry.decode_chr(data)

    def test_header_texture_count_is_not_bone_count(self):
        a = geometry.decode_chr(archive())
        self.assertEqual(len(a['textures']), 1)
        self.assertEqual(len(a['models']), 2)
        self.assertNotIn('bones', a)

    def test_no_references_preserves_triangle_attributes(self):
        m = geometry.decode_chr(archive())['models'][0]
        rebuilt = geometry.encode_model(m, [quad()], references=False)
        changed = geometry.decode_chr(geometry.replace_models(archive(), {0: rebuilt}))
        records = changed['models'][0]['meshes'][0]['records']
        self.assertEqual(len(records), 6)
        self.assertFalse(any(r['reference'] for r in records))

    def test_nonfinite_import_rejected(self):
        mesh = quad()
        mesh['vertices'][0] = (math.inf, 0, 0, 0, 0, 1, 0, 0)
        with self.assertRaisesRegex(ValueError, 'finite'):
            geometry.encode_model({'global_flags': (1, 1)}, [mesh])

    def test_removed_part_retains_header_for_unconditional_native_draw(self):
        data = archive()
        old = geometry.decode_chr(data)['models'][0]
        with self.assertRaisesRegex(ValueError, 'material header'):
            geometry.encode_model(old, [])
        rebuilt = geometry.replace_models(data, {0: geometry.invisible_model(old, material())})
        model = geometry.decode_chr(rebuilt)['models'][0]
        self.assertEqual(model['vertex_count'], 3)
        self.assertEqual(model['meshes'][0]['triangles'], [])
        self.assertEqual(model['meshes'][0]['offset'], model['offset'] + 24)

    def test_reordered_inherited_material_initializes_its_own_colors(self):
        mesh = quad()
        header = bytearray(material())
        struct.pack_into('<I', header, 0, 0x8000003c)
        struct.pack_into('<I', header, 40, struct.unpack_from('<I', header, 40)[0] | 1)
        mesh['header'] = bytes(header)
        blob = geometry.encode_model({'global_flags': (0, 1)}, [mesh])
        self.assertEqual(struct.unpack_from('<2I', blob), (1, 1))
        self.assertEqual(struct.unpack_from('<I', blob, 24)[0], 0x8000002c)
        self.assertEqual(struct.unpack_from('<I', blob, 64)[0] & 1, 0)
        self.assertEqual(blob[68:100], header[44:76])
        self.assertEqual(struct.unpack_from('<I', blob, 104)[0], 0x69)
        decoded = geometry.decode_chr(geometry.replace_models(archive(), {0: blob}))
        for record in decoded['models'][0]['meshes'][0]['records']:
            if not record['reference']:
                self.assertEqual(struct.unpack_from('<I', record['raw'], 0)[0] & 1, 1)
                self.assertEqual(struct.unpack_from('<I', record['raw'], 28)[0] & 1, 1)


if __name__ == '__main__':
    unittest.main()
