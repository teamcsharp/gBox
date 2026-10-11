"""Acceptance checks against the owned DOA2 executable, not invented tables."""
from pathlib import Path
import unittest
import os
import struct

from gbox import doa2_bindings as bindings


class NativeBindingsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fixture = Path(os.environ.get("GBOX_DOA2_EXE", "gbox-data/doa2-re/geometry/1ST_READ.BIN"))
        if not fixture.is_file():
            raise unittest.SkipTest("Owned executable fixture absent; set GBOX_DOA2_EXE")
        cls.executable = fixture.read_bytes()

    def test_kasumi_real_matrix_order(self):
        b = bindings.resolve_archive_binding(self.executable, "DOA2/KAS00.CHR")
        self.assertEqual((b["render_slot"], b["costume"]), (5, 0))
        self.assertEqual(b["emit_models"],
                         [0, 4, 5, 13, 14, 15, 17, 21, 22, 29, 30, 31, 33, 37, 38, 12, 28])
        self.assertEqual(b["files"], {"control": "kasumi.bin", "textures": "kas00.bin",
                                      "geometry": "kas00.chr", "morph": "kas00.apv",
                                      "skin": "kas00.sup"})

    def test_ein_costume_zero_is_kte01(self):
        zero = bindings.render_part_mapping(self.executable, 3, 0)
        one = bindings.resolve_archive_binding(self.executable, "DOA2/KTE00.CHR")
        self.assertEqual(zero["files"]["geometry"], "kte01.chr")
        self.assertEqual((one["render_slot"], one["costume"]), (3, 1))

    def test_genfu_costume_zero_is_gen01(self):
        b = bindings.resolve_archive_binding(self.executable, "DOA2/GEN00.CHR")
        self.assertEqual((b["render_slot"], b["costume"]), (6, 1))

    def test_costume_order_is_native_order(self):
        entries = bindings.parse_render_scripts(self.executable)[5]["costumes"]
        self.assertEqual([e["files"]["geometry"] for e in entries],
                         [f"kas{i:02}.chr" for i in (0, 1, 2, 5, 3, 4, 6, 7, 9)])

    def test_windows_filename_and_case(self):
        b = bindings.resolve_archive_binding(self.executable, r"D:\DOA2\Aya00.ChR")
        self.assertEqual((b["render_slot"], b["costume"]), (13, 0))

    def test_alias_scripts_do_not_make_zack_ambiguous(self):
        b = bindings.resolve_archive_binding(self.executable, "DOA2/ZAC01.CHR")
        self.assertEqual((b["render_slot"], b["costume"]), (0, 0))
        for slot in (19, 20, 21, 22):
            alias = bindings.parse_render_scripts(self.executable)[slot]["costumes"][0]
            self.assertEqual(alias["files"]["geometry"], "zac01.chr")

    def test_unbound_variant_is_explicitly_unsupported(self):
        with self.assertRaisesRegex(ValueError, "0 verified native body bindings"):
            bindings.resolve_archive_binding(self.executable, "DOA2/YTI00.CHR")

    def test_unknown_and_non_chr_rejected(self):
        for value in ("DOA2/UNKNOWN00.CHR", "DOA2/KAS00.BIN"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                bindings.resolve_archive_binding(self.executable, value)

    def test_wrong_executable_version_rejected(self):
        altered = bytearray(self.executable)
        altered[0x100] ^= 1
        with self.assertRaisesRegex(ValueError, "version-specific"):
            bindings.resolve_archive_binding(bytes(altered), "DOA2/KAS00.CHR")

    def test_empty_slot_and_invalid_costume_rejected(self):
        for slot, costume in ((11, 0), (18, 0), (25, 0), (3, 100), (-1, 0), (3, -1)):
            with self.subTest(slot=slot, costume=costume), self.assertRaises(ValueError):
                bindings.render_part_mapping(self.executable, slot, costume)

    def test_accessory_names_use_native_costume_table(self):
        for archive, expected in (("KTE00.CHR", "kte_a00.acs"),
                                  ("KTE01.CHR", "kte_a01.acs"),
                                  ("JAN02.CHR", "jan_a01.acs")):
            b = bindings.resolve_archive_binding(self.executable, archive)
            result = bindings.accessory_filename(self.executable, b["render_slot"], b["costume"])
            self.assertEqual(result["filename"], expected)
            self.assertEqual(result["table_address"], 0x8c180130 + 50*b["costume"] + 2*b["render_slot"])

    def test_accessory_resolver_pins_owned_executable(self):
        altered = bytearray(self.executable)
        altered[0x100] ^= 1
        with self.assertRaisesRegex(ValueError, "version-specific"):
            bindings.accessory_filename(bytes(altered), 3, 0)


if __name__ == "__main__":
    unittest.main()
