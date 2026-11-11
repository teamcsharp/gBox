import os, sys, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from gbox import res_survivor_loadsite as L
K = os.path.join(os.path.dirname(__file__), '..', '..', 'work', 'KERNEL.BIN')


@unittest.skipUnless(os.path.exists(K), 'owned KERNEL.BIN absent')
class T(unittest.TestCase):
    def test_noise_xref(self):
        d = open(K, 'rb').read()
        self.assertEqual(d[0x82C:0x82C + 18], b'..\\..\\CD\\NOISE.BIN')
        va, refs = L.find_string_xrefs(d, 0x82C)
        self.assertEqual(va, 0x8001002C)
        self.assertEqual(refs, [0x80011CD8])

    def test_wrapper_calls_loader(self):
        import struct
        d = open(K, 'rb').read()
        o = L.va_to_off(0x80011CF4)
        w = struct.unpack_from('<I', d, o)[0]
        self.assertEqual(w >> 26, 3)  # jal
        self.assertEqual(((w & 0x3FFFFFF) << 2) | 0x80000000, 0x800115C0)


if __name__ == '__main__':
    unittest.main()
