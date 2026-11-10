"""Focused loader-evidence test for Resident Evil - Survivor (PSX).

Runs against the real owned CHD (no fixtures): the loader's disc path, the
container it names and the PS-X EXE load base must all come out of the owned
KERNEL.BIN bytes.
"""
import os
import sys
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from gbox.res_survivor_formats import (  # noqa: E402
    DEFAULT_CHD, detect_pbav, open_disc, parse_psx_exe, read_range,
)
from gbox.res_survivor_loader import (  # noqa: E402
    KERNEL_MEMBER, loader_cd_paths, load_kernel_bytes,
)


class ResSurvivorLoaderTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not os.path.exists(DEFAULT_CHD):
            raise unittest.SkipTest("owned CHD not present on this host")
        cls.disc, cls.iso, cls.members = open_disc()
        cls.by = {m["path"]: m for m in cls.members}
        cls.kernel = load_kernel_bytes(cls.disc, cls.members)

    def test_loader_names_exactly_one_cd_container(self):
        paths = loader_cd_paths(self.kernel)
        self.assertEqual(len(paths), 1, paths)
        self.assertEqual(paths[0]["text"], "..\\..\\CD\\NOISE.BIN")
        self.assertEqual(paths[0]["offset"], 0x82C)
        self.assertEqual(paths[0]["basename"], "NOISE.BIN")

    def test_loader_target_is_the_pBAV_container(self):
        member = self.by["NOISE.BIN"]
        pbav = detect_pbav(read_range(self.disc, member, 0, 4096))
        self.assertIsNotNone(pbav, "NOISE.BIN must carry the pBAV container header")
        self.assertEqual(pbav["magic"], "pBAV")
        self.assertEqual(pbav["offset"], 12)
        self.assertEqual(pbav["version"], 2)

    def test_psx_exe_load_base(self):
        exe = parse_psx_exe(self.kernel)
        self.assertIsNotNone(exe, "KERNEL.BIN must be a PS-X EXE")
        self.assertEqual(exe["text_addr"], 0x80010000)
        self.assertEqual(exe["pc0"], 0x80010B08)

    def test_kernel_member_is_owned_executable(self):
        self.assertIn(KERNEL_MEMBER, self.by)
        self.assertEqual(self.by[KERNEL_MEMBER]["size"], len(self.kernel))


if __name__ == "__main__":
    unittest.main(verbosity=2)
