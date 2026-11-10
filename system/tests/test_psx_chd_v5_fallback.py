"""PSX disc reader: a CHD v5 image must not abort the whole disc.

gbox.psxdisc.CHD decodes CHD v4 (zlib hunks) only. The HyperSpin PSX set is
chdman ``createcd`` images, which are CHD v5, so gbox.formats.disc.listing()
died with "CHD v5 not supported (v4 only)" and the assimilate fingerprint for
Bloody Roar (USA) produced no evidence at all ("[metadata] engine unknown").
gbox.chd.ChdDisc already reads v5 CD images; psxdisc now falls back to it
instead of raising, so the owned disc can actually be listed and read.
"""

import unittest
from unittest.mock import patch

from gbox import psxdisc


class _StubV5:
    """Minimal ChdDisc stand-in: uppercase ISO paths, 2048-byte user sectors."""

    instances = []

    def __init__(self, path):
        self.path = str(path)
        self.files = {"A/B.BIN": (100, 2048)}
        self.reads = []
        self.closed = False
        _StubV5.instances.append(self)

    def sector(self, lba):
        return bytes(2048)

    def read(self, name, offset=0, size=None):
        self.reads.append((name, offset, size))
        if name.upper() not in self.files:
            raise KeyError(name)
        return b"\x5a" * 8

    def close(self):
        self.closed = True


class TestCHDv5Fallback(unittest.TestCase):
    def setUp(self):
        _StubV5.instances = []

    def _v5_unsupported(self, path):
        raise NotImplementedError("CHD v5 not supported (v4 only)")

    def test_v5_chd_uses_the_v5_reader(self):
        with patch.object(psxdisc, "CHD", self._v5_unsupported), \
             patch("gbox.chd.ChdDisc", _StubV5):
            d = psxdisc.PSXDisc("disc.chd")
            self.assertIsNone(d.chd)
            self.assertEqual(d.read("A/B.BIN", 0, 8), b"\x5a" * 8)
            self.assertEqual(len(d.data(0)), 2048)
            self.assertEqual(_StubV5.instances[-1].reads, [("A/B.BIN", 0, 8)])
            d.close()
            self.assertTrue(_StubV5.instances[-1].closed)

    def test_v5_read_is_case_insensitive(self):
        with patch.object(psxdisc, "CHD", self._v5_unsupported), \
             patch("gbox.chd.ChdDisc", _StubV5):
            d = psxdisc.PSXDisc("disc.chd")
            self.assertEqual(d.read("a/b.bin", 0, 8), b"\x5a" * 8)

    def test_other_not_implemented_is_not_swallowed(self):
        def boom(path):
            raise NotImplementedError("hunk type 9")
        with patch.object(psxdisc, "CHD", boom):
            with self.assertRaises(NotImplementedError):
                psxdisc.PSXDisc("disc.chd")


if __name__ == "__main__":
    unittest.main()
