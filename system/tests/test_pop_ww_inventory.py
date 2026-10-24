"""Focused test: PoP:WW GCZ disc walk through gbox.pop_ww_inventory (read-only, skips if source absent)."""
import os
import unittest

from gbox.pop_ww_inventory import PoPWWDisc

SRC = "/mnt/gbox/hyperspin/Arcade/collections/Nintendo GameCube/roms/Prince of Persia - Warrior Within (USA).gcz"


@unittest.skipUnless(os.path.exists(SRC), "owned source not mounted")
class PoPWWDiscWalk(unittest.TestCase):
    def test_walk(self):
        with PoPWWDisc(SRC) as d:
            self.assertEqual(d.disc_id, "G2OE41")
            self.assertEqual(d.title, "PoP:WW")
            self.assertEqual(d.dol_offset, 0x20300)
            self.assertEqual(len(d.files), 244)
            off, size = d.files["prince.bf"]
            self.assertEqual(size, 343834624)
            self.assertEqual(d.read_range(off, 3), b"BIG")
            self.assertEqual(d.read_file("BannerGC.tpl")[:4], b"\x00\x20\xaf\x30")
            self.assertEqual(d.read_file("MENU/ENGLISH/P5MAIN.MGM")[:8], b"<PACKAGE")


if __name__ == "__main__":
    unittest.main()
