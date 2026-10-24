import struct
import tempfile
import unittest
from pathlib import Path

from gbox import x360_inventory as x

S = 2048


def entry(left, right, sector, length, attr, name):
    raw = struct.pack("<HHIIBB", left, right, sector, length, attr, len(name)) + name
    return raw + b"\xff" * (-len(raw) % 4)


def build(path, base=0):
    # root dir at sector 34 holds default.xex (left) and a subdir "d" (right)
    root_sector, sub_sector = 34, 35
    e_xex = entry(0, 0, 36, 8, 0, b"default.xex")
    e_sub = entry(0, 0, sub_sector, S, 0x10, b"d")
    # root node: "d" first, with right child -> default.xex? use node ordering "d" < "default.xex"
    e_d_off = 0
    d = entry(0, 0, sub_sector, S, 0x10, b"d")
    xex_off = len(d) // 4
    d = entry(0, xex_off, sub_sector, S, 0x10, b"d")
    xex = entry(0, 0, 36, 8, 0, b"default.xex")
    root = (d + xex).ljust(S, b"\xff")
    sub = entry(0, 0, 37, 4, 0, b"a.cpk").ljust(S, b"\xff")
    img = bytearray(base + 38 * S + 8192 * 0 + 16 * S)
    desc = x.MAGIC + struct.pack("<II", root_sector, S) + bytes(S - 48) + x.MAGIC
    img[base + 0x10000:base + 0x10000 + S] = desc
    img[base + root_sector * S:base + root_sector * S + S] = root
    img[base + sub_sector * S:base + sub_sector * S + S] = sub
    img[base + 36 * S:base + 36 * S + 8] = b"XEX2\0\0\0\1"
    img[base + 37 * S:base + 37 * S + 4] = b"CPK "
    Path(path).write_bytes(bytes(img))


class X360Inventory(unittest.TestCase):
    def test_walk_xgd_zero_base(self):
        with tempfile.TemporaryDirectory() as t:
            p = Path(t) / "a.iso"
            build(p)
            r = x.inventory(p)
            self.assertEqual(r["file_count"], 2)
            self.assertEqual({f["path"] for f in r["files"]}, {"default.xex", "d/a.cpk"})
            self.assertEqual(r["default_xex"]["size"], 8)
            self.assertEqual(len(r["default_xex"]["sha256"]), 64)
            self.assertEqual(r["magic_census"].get("CPK "), 1)

    def test_rejects_missing_volume(self):
        with tempfile.TemporaryDirectory() as t:
            p = Path(t) / "b.iso"
            p.write_bytes(bytes(0x20000))
            with self.assertRaises(ValueError):
                x.inventory(p)

    def test_rejects_cycle(self):
        with tempfile.TemporaryDirectory() as t:
            p = Path(t) / "c.iso"
            build(p)
            data = bytearray(p.read_bytes())
            # point root "d" subdir at the root itself
            struct.pack_into("<I", data, 34 * S + 4, 34)
            p.write_bytes(bytes(data))
            with self.assertRaises(ValueError):
                x.inventory(p)


if __name__ == "__main__":
    unittest.main()
