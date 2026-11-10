import hashlib
import os
import struct
import unittest
from pathlib import Path

from gbox import savemgo_target as t

ROOT = os.environ.get("SAVEMGO_TEST_ROOT")  # dir containing dev_hdd0/game/NPMG00020/USRDIR


def _mdn(size=0x80):
    words = [0x832E62] + [1] * 8 + [0x80] * 13 + [size]
    return b"MDN " + struct.pack(">23I", *words) + bytes(size - 4 - 92)


class HeaderTests(unittest.TestCase):
    def test_mdn_header(self):
        self.assertEqual(t.parse_mdn_header(_mdn())["declared_size"], 0x80)
        with self.assertRaises(ValueError):
            t.parse_mdn_header(_mdn() + b"\0")
        with self.assertRaises(ValueError):
            t.parse_mdn_header(b"XXXX" + _mdn()[4:])

    def test_slot_header(self):
        head = struct.pack(">IHHHHI", 0xCC9B, 1, 1, 0x28, 0, 1)
        self.assertEqual(t.parse_slot_header(head), {"id": 0xCC9B, "count": 0x28})
        with self.assertRaises(ValueError):
            t.parse_slot_header(struct.pack(">IHHHHI", 1, 2, 1, 5, 0, 1))


@unittest.skipUnless(ROOT, "owned SaveMGO extraction not provided")
class OwnedBuildTests(unittest.TestCase):
    def test_target_member(self):
        r = t.locate_member(Path(ROOT))
        self.assertEqual(r["archive_sha256"], t.TARGET_ARCHIVE_SHA256)
        self.assertEqual(r["sha256"], t.TARGET_MEMBER_SHA256)
        self.assertEqual(r["size"], t.TARGET_MEMBER_SIZE)
        self.assertEqual(r["kind"], "models")
        self.assertEqual(t.parse_mdn_header(r["blob"])["declared_size"], r["size"])

    def test_slot_chest(self):
        p = Path(ROOT) / "dev_hdd0/game/NPMG00020/USRDIR/o/dl/p/slotdat/slot_online_chest.slot"
        self.assertEqual(t.parse_slot_header(p.read_bytes()[:16]), {"id": 0xCC9B, "count": 0x28})


if __name__ == "__main__":
    unittest.main()
