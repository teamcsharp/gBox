"""Focused checks for the Metal Arms inventory probe (game 7e103ec3aab47fa2, GM5E7D GC)."""
import json
import unittest
from pathlib import Path

ISO = Path("/home/ehm_eckx/gbox-cache/modbase/7e103ec3aab47fa2/Metal Arms - Glitch in the System (USA).iso")
MANIFEST = Path(__file__).resolve().parent.parent / "metal_arms_inventory.json"

EXPECTED = {
    "game_code": "GM5E7D",
    "iso_sha256": "62d752e07d3e00ccc074f360e5edcbd88787bf72d584c8d2807516a7e8775354",
    "dol_sha256": "0404e788ec43fd675e030bc80e4a177f889bc36cb86a94440b6de12dc55e903d",
    "master_entries": 12048,
    "roster_count": 8,
}


@unittest.skipUnless(ISO.exists(), "Metal Arms ISO not present in gbox-cache")
class TestInventory(unittest.TestCase):
    def test_manifest_matches_disc(self):
        m = json.loads(MANIFEST.read_text())
        self.assertTrue(m["disc_magic_ok"])
        self.assertEqual(m["game_code"], EXPECTED["game_code"])
        self.assertEqual(m["iso"]["sha256"], EXPECTED["iso_sha256"])
        self.assertEqual(m["executable"]["sha256"], EXPECTED["dol_sha256"])
        self.assertEqual(m["master_file"]["entry_count"], EXPECTED["master_entries"])

    def test_roster_complete(self):
        m = json.loads(MANIFEST.read_text())
        self.assertEqual(len(m["roster"]), EXPECTED["roster_count"])
        for c in m["roster"]:
            self.assertTrue(c["mesh_ok"], c["slug"])
            self.assertIsNotNone(c["mesh_entry"]["crc"])
            self.assertTrue(c["textures"], c["slug"])
            self.assertTrue(c["anim_banks"], c["slug"])


if __name__ == "__main__":
    unittest.main()
