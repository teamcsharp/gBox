"""Focused tests for the NAOMI ROM-board container reader.

Validates the reader against the owned Sega Tetris (Sega New Tetris) NAOMI
build: physical file table, rom.lst manifest sections, and the contiguous
NaomiLib model runs that hold character geometry.  A synthetic container is
also exercised so the test runs without the owned ROM present.

Run:  python3 tests/test_naomi_container.py -v
"""

import os
import struct
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from gbox import naomilib
from gbox import naomi_container

ROM_DIR = Path(os.environ.get(
    "SGTETRIS_ROMS", "/home/ehm_eckx/.hermes/cache/scratch/sgtetris/roms"))
IC1 = ROM_DIR / "mpr-22910.ic1"


def synth_container():
    """Build a minimal synthetic NAOMI ROM-board chip in memory."""
    manifest = (b"rom.lst\n%rom_texture\nsprpal.thb\n%poly_hie\n"
                b"chr0000.mtd\nchr0000.pl4\nchr0000.thb\n%rom_sound\nAICADRV.BIN\n")
    mf_off = 0x800
    mf_pad = 0x100 - len(manifest)
    payload = b"PAYLOAD-DATA" * 40
    data_len = 0x900 + len(payload)
    chunk = len(payload) // 11
    entries = [mf_off] + [0x900 + i * chunk for i in range(10)] + [data_len]
    blob = bytearray(data_len)
    blob[0:16] = b"SYNTH NAOMI     "
    struct.pack_into("<12I", blob, naomi_container.TABLE_OFFSET, *entries)
    blob[mf_off:mf_off + len(manifest)] = manifest
    blob[mf_off + len(manifest):0x900] = b" " * mf_pad
    blob[0x900:0x900 + len(payload)] = payload
    return bytes(blob)


class SyntheticContainerTest(unittest.TestCase):
    def test_synthetic_container_parses(self):
        data = synth_container()
        self.assertTrue(naomi_container.is_naomi_container(data))
        files = naomi_container.parse_file_table(data)
        self.assertEqual(len(files), 12)
        self.assertEqual(files[0]["offset"], 0x800)
        m = naomi_container.parse_manifest(data)
        self.assertIn("%poly_hie", m["section_names"])
        self.assertIn("%rom_texture", m["section_names"])
        self.assertIn("chr0000.pl4", m["order"])
        self.assertNotIn("chr0000.pl4", m["root"]["files"])

    def test_non_container_is_rejected(self):
        self.assertFalse(naomi_container.is_naomi_container(b"\x00" * 4096))


class OwnedBuildContainerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not IC1.exists():
            raise unittest.SkipTest("owned ROM not present: %s" % IC1)
        cls.data = IC1.read_bytes()

    def test_ic1_is_a_naomi_container(self):
        self.assertTrue(naomi_container.is_naomi_container(self.data))
        self.assertEqual(
            naomi_container.parse_file_table(self.data)[0]["offset"], 0x800)

    def test_physical_file_table_is_monotonic_and_covers_chip(self):
        files = naomi_container.parse_file_table(self.data)
        self.assertEqual(len(files), 12)
        for i, f in enumerate(files):
            self.assertLess(f["offset"], f["end"])
            self.assertGreater(f["size"], 0)
            if i:
                self.assertEqual(files[i - 1]["end"], f["offset"])
        self.assertEqual(files[-1]["end"], len(self.data))

    def test_manifest_lists_poly_hie_character_models(self):
        m = naomi_container.parse_manifest(self.data)
        self.assertIn("%poly_hie", m["section_names"])
        self.assertIn("%rom_texture", m["section_names"])
        self.assertIn("%rom_poly", m["section_names"])
        pl4 = [n for n in m["order"] if n.endswith(".pl4")]
        self.assertEqual(len(pl4), 7)
        self.assertEqual(pl4[0], "chr0000.pl4")
        self.assertEqual(pl4[-1], "chr0060.pl4")

    def test_model_runs_are_contiguous_and_inside_physical_files(self):
        runs, models = naomi_container.find_model_runs(self.data, naomilib.scan)
        self.assertEqual(len(models), 96)
        self.assertEqual(len(runs), 2)
        self.assertEqual([r["models"] for r in runs], [54, 42])
        for r in runs:
            self.assertEqual(r["bytes"], r["end"] - r["start"])
            self.assertGreater(r["models"], 1)

    def test_streamed_hash_is_lowercase_sha256(self):
        h = naomi_container.sha256_stream(IC1)
        self.assertEqual(len(h), 64)
        self.assertEqual(h, h.lower())


if __name__ == "__main__":
    unittest.main()
