import os
import unittest

from gbox import mm64_asset as A

ROM = "/mnt/gbox/hyperspin/Arcade/collections/Nintendo 64/roms/USA/Mega Man 64 (USA).zip"


def _rom():
    if not os.path.exists(ROM):
        raise unittest.SkipTest("owned ROM not mounted: " + ROM)
    src, rom = A.load_rom(ROM)
    import hashlib
    h = hashlib.sha256(rom).hexdigest()
    if h != A.ROM_IMAGE_SHA256:
        raise unittest.SkipTest("ROM sha256 mismatch: " + h)
    return rom


class TestDirectory(unittest.TestCase):
    def test_445_chained_entries(self):
        ents = A.directory_entries(_rom())
        self.assertEqual(len(ents), 445)
        self.assertEqual(ents[0][2], 0x80)  # LZSS flag on entry #0

    def test_entry0_decodes_to_1264(self):
        data = A.unpack(_rom(), 0)
        self.assertEqual(len(data), 1264)


class TestEntry0Payload(unittest.TestCase):
    def setUp(self):
        self.payload = A.unpack(_rom(), 0)
        self.sections = A.sections(self.payload)

    def test_five_sections(self):
        self.assertEqual(len(self.sections), 5)
        self.assertEqual([len(s) for s in self.sections],
                         [144, 48, 208, 240, 576])

    def test_roundtrip_is_identity(self):
        # header pad = bytes between offset table and first section
        hdr_end = 4 * (len(self.sections) + 1)
        first_off = 48
        pad = self.payload[hdr_end:first_off]
        self.assertEqual(A.repack(self.sections, pad), self.payload)

    def test_rsp_vertex_array(self):
        verts = A.rsp_vertices(self.sections[3])  # section @448
        self.assertEqual(len(verts), 15)
        xs = [v["x"] for v in verts]
        self.assertTrue(all(-4096 <= x <= 4095 for x in xs))
        self.assertIn(128, xs)  # observed geometry scale

    def test_index_groups(self):
        groups = A.index_groups(self.sections[1])  # section @192
        self.assertEqual(len(groups), 12)
        prims, tail = groups[:8], groups[8:]
        self.assertTrue(all(g[0] in (0x00, 0x06) for g in prims))
        self.assertTrue(all(max(g[1:]) <= 0x36 for g in prims))
        # command tail: 0xDF sync word then zero padding
        self.assertEqual(tail[0][0], 0xDF)
        self.assertTrue(all(g == (0, 0, 0, 0) for g in tail[1:]))


if __name__ == "__main__":
    unittest.main()
